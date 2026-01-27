"""
外层对话总控图：负责路由到 chat 或 deep research 子图。

架构：
- DialogState：外层 state，维护 messages 和研究相关字段
- route_intent：意图路由节点，判断是 chat 还是 research
- chat_node：普通对话节点
- run_research_subgraph：调用 deep_researcher 子图
"""
import sys
from pathlib import Path
from typing import Annotated, Literal, TypedDict, Optional, List

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, get_buffer_string
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import Command
from pydantic import BaseModel, Field

from .llm import get_llm

# 导入 deep_researcher 子图
_deep_researcher = None
_odr_src = Path(__file__).resolve().parent / "open_deep_research" / "src"
if _odr_src.exists() and str(_odr_src) not in sys.path:
    sys.path.insert(0, str(_odr_src))
try:
    from open_deep_research.deep_researcher import deep_researcher as _deep_researcher
except Exception:
    pass


def override_reducer(current_value, new_value):
    """Reducer function that allows overriding values in state."""
    import operator
    if isinstance(new_value, dict) and new_value.get("type") == "override":
        return new_value.get("value", new_value)
    else:
        # 对于列表，使用 add；对于其他类型，使用新值
        if isinstance(current_value, list) and isinstance(new_value, list):
            return operator.add(current_value, new_value)
        return new_value if current_value is None else current_value


class DialogState(TypedDict, total=False):
    """外层对话 state，维护 messages 和研究相关字段。"""
    messages: Annotated[List[BaseMessage], add_messages]
    route: Literal["chat", "research"]  # 当前路由目标
    # 直接复用研究字段，避免来回搬运
    research_brief: Optional[str]
    research_plan: Optional[dict]
    notes: Annotated[List[str], override_reducer]
    raw_notes: Annotated[List[str], override_reducer]
    final_report: Optional[str]
    supervisor_messages: Annotated[List[BaseMessage], override_reducer]
    research_status: Optional[str]  # "idle" | "awaiting_user" | "running" | "done"


class RouteDecision(BaseModel):
    """路由决策：判断用户意图是聊天还是启动研究。"""
    route: Literal["chat", "research"] = Field(description="路由目标：chat 或 research")
    reason: str = Field(default="", description="决策理由")


async def route_intent(state: DialogState, config: RunnableConfig) -> Command:
    """
    意图路由节点：判断用户这轮输入是要正常对话，还是要启动 deep research。
    
    判断逻辑：
    - 如果用户提出明确的"调研/综述/文献/找方法+数据集+模型建议"请求，选 research
    - 否则选 chat
    """
    messages = state.get("messages", [])
    if not messages:
        return Command(goto="chat", update={"route": "chat"})
    
    # 检查最后一条用户消息
    last_msg = messages[-1]
    if not isinstance(last_msg, HumanMessage):
        return Command(goto="chat", update={"route": "chat"})
    
    content = last_msg.content.strip() if isinstance(last_msg.content, str) else str(last_msg.content).strip()
    
    # 简单规则：如果以 /research 开头，直接路由到 research
    if content.lower().startswith("/research"):
        return Command(goto="research", update={"route": "research"})
    
    # 使用 LLM 做结构化输出判断
    llm = get_llm()
    model = llm.with_structured_output(RouteDecision)
    
    # 只看最近 12 条消息，避免喂太多历史
    recent_messages = messages[-12:]
    buf = get_buffer_string(recent_messages)
    
    prompt = f"""你是一个路由器。判断用户这轮是要正常对话，还是要启动 deep research 文献调研流程。

判断标准：
- 如果用户在提出明确的"调研/综述/文献/找方法+数据集+模型建议/实验设计"请求，选 research
- 如果只是普通问答、闲聊、技术咨询（不涉及深度文献调研），选 chat
- 如果用户想了解某个医学/AI主题，但没有明确要求文献调研，选 chat

对话历史：
{buf}

请判断这轮用户输入应该路由到哪里。"""
    
    try:
        decision = await model.ainvoke([HumanMessage(content=prompt)], config=config)
        return Command(goto=decision.route, update={"route": decision.route})
    except Exception as e:
        # 如果 LLM 判断失败，默认路由到 chat
        print(f"[route_intent] Error: {e}, defaulting to chat", flush=True)
        return Command(goto="chat", update={"route": "chat"})


async def chat_node(state: DialogState, config: RunnableConfig) -> Command:
    """
    Chat 节点：普通对话 agent，可以绑定常用工具（PathLab 工具、简短搜索工具等）。
    
    注意：不要把"深度研究"也塞进这里，避免它每次都想开大。
    """
    messages = state.get("messages", [])
    if not messages:
        return Command(goto=END, update={"messages": [AIMessage(content="No messages to reply to.")]})
    
    llm = get_llm()
    # Chat tools disabled - no PathLab tools for now
    # 如果需要，可以在这里添加工具
    
    try:
        resp = await llm.ainvoke(messages, config=config)
        return Command(goto=END, update={"messages": [resp]})
    except Exception as e:
        error_msg = f"Chat error: {e}"
        print(f"[chat_node] {error_msg}", flush=True)
        return Command(goto=END, update={"messages": [AIMessage(content=error_msg)]})


async def run_research_subgraph(state: DialogState, config: RunnableConfig) -> Command:
    """
    Research 节点：调用 deep_researcher 子图。
    
    传入至少要满足 deep_researcher 的 input schema，然后把子图产物并回外层 state。
    使用 astream 以支持流式输出和 custom 事件传递。
    """
    if _deep_researcher is None:
        return Command(
            goto=END,
            update={"messages": [AIMessage(content="Deep research 子图未加载，无法执行研究。")]}
        )
    
    # 传入至少要满足 deep_researcher 的 input schema
    # deep_researcher 的 AgentInputState 需要 messages 和可选的 research_brief
    sub_in = {
        "messages": state.get("messages", [])
    }
    
    # 如果有 research_brief，传递它（用于继续研究会话）
    if state.get("research_brief"):
        sub_in["research_brief"] = state["research_brief"]
    
    try:
        # 使用 astream 以支持流式输出和 custom 事件传递
        # 外层对话图的 astream 会捕获这些 custom 事件
        parent_writer = None
        try:
            parent_writer = get_stream_writer()
        except Exception:
            pass
        
        result = None
        async for event in _deep_researcher.astream(
            sub_in, config, stream_mode=["values", "custom"]
        ):
            if isinstance(event, (list, tuple)) and len(event) >= 2:
                mode, chunk = event[0], event[1]
            else:
                mode, chunk = "values", event
            
            # 传递 custom 事件到外层（外层会通过 astream 捕获）
            if mode == "custom" and parent_writer and callable(parent_writer):
                try:
                    parent_writer(chunk)
                except Exception:
                    pass
            
            if mode == "values":
                result = chunk
        
        # 如果 astream 没有返回结果，使用 ainvoke 作为后备
        if result is None:
            result = await _deep_researcher.ainvoke(sub_in, config=config)
        
        # 把子图产物并回外层 state
        updates = {}
        
        # 保留研究相关字段
        if "final_report" in result:
            updates["final_report"] = result["final_report"]
        if "research_brief" in result:
            updates["research_brief"] = result["research_brief"]
        if "research_plan" in result:
            updates["research_plan"] = result["research_plan"]
        if "supervisor_messages" in result:
            updates["supervisor_messages"] = result["supervisor_messages"]
        if "notes" in result:
            updates["notes"] = result["notes"]
        if "raw_notes" in result:
            updates["raw_notes"] = result["raw_notes"]
        if "research_status" in result:
            updates["research_status"] = result["research_status"]
        
        # 让用户在对话里看到最终结论（最后一条消息）
        if result.get("messages"):
            updates["messages"] = [result["messages"][-1]]
        
        return Command(goto=END, update=updates)
        
    except Exception as e:
        import traceback
        error_msg = f"Research 子图执行出错: {e}\n{traceback.format_exc()}"
        print(f"[run_research_subgraph] {error_msg}", flush=True)
        return Command(
            goto=END,
            update={"messages": [AIMessage(content=f"Research 执行出错: {e}")]}
        )


def create_dialog_agent(checkpointer=None):
    """
    构建并编译外层对话图。
    
    流程：
    START -> route_intent -> [chat | research] -> END
    
    注意：research 子图结束后自动回到 END，下一轮用户输入会再次从 route_intent 开始。
    """
    from langgraph.graph import START, END
    
    dialog_builder = StateGraph(DialogState)
    
    # 添加节点
    dialog_builder.add_node("route_intent", route_intent)
    dialog_builder.add_node("chat", chat_node)
    
    if _deep_researcher is not None:
        dialog_builder.add_node("research", run_research_subgraph)
    
    # 定义边
    dialog_builder.add_edge(START, "route_intent")
    
    # route_intent 返回 Command，Command.goto 会直接覆盖边的定义
    # 所以这里定义默认边（如果 Command.goto 没有指定，会使用这些默认边）
    if _deep_researcher is not None:
        # 如果 deep_researcher 可用，定义到 chat 和 research 的边
        # Command.goto 会覆盖这些边
        dialog_builder.add_edge("route_intent", "chat")  # 默认路由到 chat
    else:
        # 如果 deep_researcher 不可用，直接路由到 chat
        dialog_builder.add_edge("route_intent", "chat")
    
    # chat 和 research 都直接 END
    dialog_builder.add_edge("chat", END)
    if _deep_researcher is not None:
        dialog_builder.add_edge("research", END)
    
    # 编译（如果需要 checkpointer 支持 interrupt，传入它）
    if checkpointer:
        return dialog_builder.compile(checkpointer=checkpointer)
    else:
        return dialog_builder.compile()
