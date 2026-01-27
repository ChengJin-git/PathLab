"""
LangGraph conversation agent with optional deep research subgraph.

Routes to research subgraph if user input starts with "/research", otherwise uses simple LLM chat.
"""
import sys
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .llm import get_llm
import httpx
import json

# 可选：加载 open_deep_research 作为子图
_deep_researcher = None
_odr_src = Path(__file__).resolve().parent / "open_deep_research" / "src"
if _odr_src.exists() and str(_odr_src) not in sys.path:
    sys.path.insert(0, str(_odr_src))
try:
    from open_deep_research.deep_researcher import deep_researcher as _deep_researcher
except Exception:
    pass

# 可选：加载 training 子图
_create_training_graph = None
try:
    from backend.agent.training import create_training_graph as _create_training_graph
except Exception:
    pass

# adapter：从 research 报告解析 training 参数
try:
    from backend.agent.adapters.report_to_training import (
        parse_model_config_from_report,
        model_config_to_training_params,
    )
except Exception:
    parse_model_config_from_report = None
    model_config_to_training_params = None


def _get_chat_tools():
    """Chat tools - currently disabled. Returns empty list."""
    return []


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


class AgentState(TypedDict, total=False):
    """Main agent state compatible with chat, research, and training subgraph."""
    messages: Annotated[list[BaseMessage], add_messages]
    # Research status: "idle" | "awaiting_user" | "running" | "done"
    research_status: str | None
    # Research subgraph 需要的字段（可选，用于兼容）
    supervisor_messages: Annotated[list[BaseMessage], override_reducer]
    research_brief: str | None
    raw_notes: Annotated[list[str], override_reducer]
    notes: Annotated[list[str], override_reducer]
    final_report: str | None
    # Token usage tracking
    last_token_usage: dict | None  # {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
    # Training 子图：propose -> 用户确认/修改 -> create_training_task
    proposed_training: dict | None
    initial_training_params: dict | None
    # 内部：research 最终报告是否已展示（避免重复打印）
    _shown_final_report: bool | None


async def _chat_node_async(state: AgentState, config: RunnableConfig | None = None) -> dict:
    """Chat 节点：LLM 流式输出，通过 custom 事件 llm_chunk 实时打印；聚合成 AIMessage 写回 state。"""
    msgs = state.get("messages", [])
    if not msgs:
        return {"messages": [AIMessage(content="No messages to reply to.")]}
    base_llm = get_llm()
    # Chat tools disabled - no PathLab tools
    tools = []
    llm = base_llm

    cfg = config if isinstance(config, dict) else {}
    parent_writer = None
    try:
        parent_writer = get_stream_writer()
    except Exception:
        pass

    full = None
    async for chunk in llm.astream(msgs, config=cfg):
        if parent_writer and callable(parent_writer):
            c = getattr(chunk, "content", None) or ""
            if isinstance(c, list):
                c = "".join(str(x) for x in c) if c else ""
            else:
                c = str(c) if c is not None else ""
            if c:
                try:
                    parent_writer({"type": "llm_chunk", "content": c})
                except Exception:
                    pass
        try:
            full = (full + chunk) if full is not None else chunk
        except Exception:
            full = chunk if full is None else full

    out = full if full is not None else AIMessage(content="")
    return {"messages": [out]}


async def _research_node_async(state: AgentState, config: RunnableConfig | None = None) -> dict:
    """Research subgraph node wrapper (async).
    
    Handles both initial research requests and follow-up interactions (clarify, confirm_brief).
    If research_brief exists in state, it means we're continuing a research session.
    """
    if _deep_researcher is None:
        return {
            "messages": [
                AIMessage(content="Research 不可用：未安装 open_deep_research 依赖（tavily、mcp 等）。")
            ],
            "research_status": "idle"
        }
    
    messages = state.get("messages", [])
    if not messages:
        return {
            "messages": [AIMessage(content="请提供研究问题。")],
            "research_status": "idle"
        }
    
    # 从 RunnableConfig 中提取 thread_id，并合并父级 config 以继承 stream_writer 等
    thread_id = "main-research"
    cfg = {}
    if config and isinstance(config, dict):
        cfg = (config.get("configurable") or {}) if isinstance(config.get("configurable"), dict) else {}
        if isinstance(cfg, dict):
            thread_id = cfg.get("thread_id", "main-research")
    research_config = {
        **(config or {}),
        "configurable": {
            **cfg,
            "thread_id": thread_id,
            "allow_clarification": False,
        },
    }
    
    # 检查是否是继续 research 会话（有 research_brief 或其他 research 字段）
    # 或者最后一条消息是用户的回复（不是以 /research 开头）
    # 但是，如果已经有 final_report，说明 research 已完成，不应该继续
    has_final_report = state.get("final_report") is not None
    has_research_brief = state.get("research_brief") is not None
    has_supervisor_messages = bool(state.get("supervisor_messages"))
    is_user_reply = (
        len(messages) >= 2 
        and isinstance(messages[-1], HumanMessage) 
        and not messages[-1].content.strip().lower().startswith("/research")
    )
    
    # 如果有 final_report，说明 research 已完成，不应该继续
    is_continuing = (has_research_brief or has_supervisor_messages or is_user_reply) and not has_final_report

    if is_continuing:
        # 继续 research 会话：传递所有 messages（包括用户的回复）和 research_brief
        research_input = {"messages": messages}
        # 确保 research_brief 被传递（如果存在）
        if has_research_brief:
            research_input["research_brief"] = state.get("research_brief")
        # 确保 research_plan 被传递（如果存在）
        if state.get("research_plan"):
            research_input["research_plan"] = state.get("research_plan")
        # 也传递其他 research 相关字段
        if has_supervisor_messages:
            research_input["supervisor_messages"] = state.get("supervisor_messages")
    else:
        # 新的 research 请求：提取研究问题
        last_msg = messages[-1]
        if isinstance(last_msg, HumanMessage):
            query = last_msg.content
            # 移除 /research 前缀（如果存在）
            if query.lower().startswith("/research "):
                query = query[9:].strip()
            elif query.lower() == "/research":
                query = ""
            
            if not query:
                return {
                    "messages": [AIMessage(content="用法: /research <你的研究问题>")],
                    "research_status": "idle"
                }
            
            # 只传递研究问题（新的 research 会话）
            research_input = {"messages": [HumanMessage(content=query)]}
        else:
            return {
                "messages": [AIMessage(content="无法识别研究请求。")],
                "research_status": "idle"
            }
    
    # 调用 research 子图（astream 以输出 custom 事件；取最后 values 为 result）
    parent_writer = None
    try:
        parent_writer = get_stream_writer()
    except Exception:
        pass

    result = None
    try:
        async for event in _deep_researcher.astream(
            research_input, research_config, stream_mode=["values", "custom"]
        ):
            if isinstance(event, (list, tuple)) and len(event) >= 2:
                mode, chunk = event[0], event[1]
            else:
                mode, chunk = "values", event
            if mode == "custom" and parent_writer and callable(parent_writer):
                try:
                    parent_writer(chunk)
                except Exception:
                    pass
            if mode == "values":
                result = chunk
        if result is None:
            result = await _deep_researcher.ainvoke(research_input, research_config)
    except Exception as e:
        import traceback
        error_msg = f"Research 子图执行出错: {e}\n{traceback.format_exc()}"
        return {
            "messages": [AIMessage(content=error_msg)],
            "final_report": None,
            "research_status": "idle",
        }
    
    # 合并 research 子图返回的 state 到主 state
    # 这样 research_brief、supervisor_messages 等字段会被保留，用于后续交互
    output = {}
    
    # 提取最终报告
    final_report = result.get("final_report")
    if final_report:
        # Research 完成：返回所有消息（包括中间搜索结果和最终报告），并清理 research 相关字段
        output["final_report"] = final_report
        # 保留所有消息（包括 show_search_results 输出的中间消息和 final_report_generation 输出的最终报告）
        research_messages = result.get("messages", [])
        if research_messages:
            output["messages"] = research_messages
        else:
            # 如果没有消息，至少包含最终报告
            output["messages"] = [AIMessage(content=final_report)]
        output["research_status"] = "done"  # 明确标记为完成
        # 清理 research 相关字段，避免下次输入时误认为是继续 research 会话
        output["research_brief"] = None
        output["supervisor_messages"] = None
        output["notes"] = None
        # 保留 raw_notes 供 REPL 打印「搜索与参考」，之后再清掉
        output["raw_notes"] = result.get("raw_notes") or []
    else:
        # 如果没有最终报告，返回最后的消息（可能是澄清问题或确认请求）
        research_messages = result.get("messages", [])
        if research_messages:
            output["messages"] = research_messages
        
        # 判断 research_status：
        # - 如果返回的是澄清问题或确认请求（clarify_with_user 或 confirm_research_brief），标记为 "awaiting_user"
        # - 如果正在进行研究（有 supervisor_messages），标记为 "running"
        # - 否则标记为 "awaiting_user"（等待用户回复）
        last_message = research_messages[-1] if research_messages else None
        has_supervisor_in_result = bool(result.get("supervisor_messages"))
        has_supervisor_in_state = bool(state.get("supervisor_messages"))
        
        # 如果 result 中有 supervisor_messages，说明已经进入研究阶段
        if has_supervisor_in_result:
            # 正在进行研究（supervisor 在工作）
            output["research_status"] = "running"
        elif has_supervisor_in_state:
            # state 中有 supervisor_messages，说明之前已经进入研究阶段，应该继续
            output["research_status"] = "running"
        elif has_research_brief or result.get("research_brief"):
            # 有 research_brief 但没有 supervisor_messages，说明在等待用户确认
            output["research_status"] = "awaiting_user"
        else:
            # 等待用户回复（澄清问题）
            output["research_status"] = "awaiting_user"
        
        # 保留 research 相关字段，以便后续交互
        if "research_brief" in result:
            output["research_brief"] = result["research_brief"]
        elif has_research_brief:
            # 如果 result 中没有 research_brief，但 state 中有，保留 state 中的
            output["research_brief"] = state.get("research_brief")
        if "research_plan" in result:
            output["research_plan"] = result["research_plan"]
        elif state.get("research_plan"):
            # 保留 state 中的 research_plan
            output["research_plan"] = state.get("research_plan")
        if "supervisor_messages" in result:
            output["supervisor_messages"] = result["supervisor_messages"]
        elif has_supervisor_in_state:
            # 保留 state 中的 supervisor_messages
            output["supervisor_messages"] = state.get("supervisor_messages")
        if "notes" in result:
            output["notes"] = result["notes"]
        if "raw_notes" in result:
            output["raw_notes"] = result["raw_notes"]
        if state.get("_shown_final_report") is not None:
            output["_shown_final_report"] = state["_shown_final_report"]
    
    if not output.get("messages"):
        output["messages"] = [AIMessage(content="Research 完成但无最终报告")]
        output["research_status"] = "done"
    
    return output


def _training_node(state: AgentState, config: RunnableConfig | None = None) -> dict:
    """
    Training 子图封装：propose_create_training_task -> 用户确认/修改 -> create_training_task。
    若存在 final_report，从中解析 initial_training_params 作为 propose 的默认。
    """
    if _create_training_graph is None:
        return {
            "messages": [AIMessage(content="Training 不可用：未安装或无法导入 backend.agent.training。")],
            "proposed_training": None,
        }
    init = state.get("initial_training_params")
    if init is None and (parse_model_config_from_report and model_config_to_training_params):
        report = state.get("final_report")
        if report:
            cfg = parse_model_config_from_report(report)
            init = model_config_to_training_params(cfg) if cfg else {}
        else:
            init = {}
    inp = {
        "messages": state.get("messages", []),
        "initial_training_params": init or {},
        "proposed_training": state.get("proposed_training"),
    }
    tr = _create_training_graph()
    result = tr.invoke(inp, config)
    out = {
        "messages": result.get("messages", []),
        "proposed_training": result.get("proposed_training"),
    }
    if state.get("_shown_final_report") is not None:
        out["_shown_final_report"] = state["_shown_final_report"]
    return out


def _after_chat(state: AgentState) -> Literal["chat_tools", "__end__"]:
    """Chat 节点之后：若有 tool_calls 且 PathLab tools 可用则进入 chat_tools，否则 END。"""
    if not _get_chat_tools():
        return "__end__"
    messages = state.get("messages", [])
    if not messages:
        return "__end__"
    last = messages[-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "chat_tools"
    return "__end__"


def _route(state: AgentState) -> Literal["research", "chat", "training"]:
    """Route to research, training, or chat.

    - research: /research 或 research_status in (awaiting_user, running) 或存在 research_brief/research_plan
    - training: /training、根据报告建任务、提交任务 等，或 proposed_training 非空且最后一条为用户消息（确认/修改）
    - chat: 其余
    """
    import logging
    logger = logging.getLogger(__name__)
    
    messages = state.get("messages", [])
    logger.debug(f"[Route] Routing decision: messages_count={len(messages)}")
    
    if not messages:
        logger.debug(f"[Route] No messages, routing to chat")
        return "chat"
    
    status = state.get("research_status") or "idle"
    has_research_brief = state.get("research_brief") is not None
    has_research_plan = state.get("research_plan") is not None
    has_supervisor_messages = bool(state.get("supervisor_messages"))
    
    logger.debug(f"[Route] Current research_status: {status}, has_research_brief: {has_research_brief}, has_research_plan: {has_research_plan}, has_supervisor_messages: {has_supervisor_messages}")
    
    # Route to research if:
    # 1. research_status is awaiting_user or running
    # 2. OR has research_brief/research_plan (waiting for user confirmation or continuing research)
    # 3. OR has supervisor_messages (research is in progress)
    # CRITICAL: Check research_brief/research_plan FIRST before checking /research prefix
    # This ensures that when user replies to confirm_research_brief, it routes to research
    if has_research_brief or has_research_plan or has_supervisor_messages:
        logger.info(f"[Route] ✅ Routing to research: has_research_brief={has_research_brief}, has_research_plan={has_research_plan}, has_supervisor_messages={has_supervisor_messages}")
        return "research"
    elif status in ("awaiting_user", "running"):
        logger.info(f"[Route] ✅ Routing to research: research_status={status}")
        return "research"
    
    last_msg = messages[-1]
    logger.debug(f"[Route] Last message: type={type(last_msg).__name__}")
    
    if isinstance(last_msg, HumanMessage):
        content = last_msg.content.strip() if isinstance(last_msg.content, str) else str(last_msg.content)
        content_lower = content.lower()
        logger.debug(f"[Route] Last message content (first 200 chars): {content[:200]}")
        logger.debug(f"[Route] Last message content (lowercase, first 50 chars): {content_lower[:50]}")
        
        if content_lower.startswith("/research") or content_lower == "/research":
            logger.info(f"[Route] ✅ Routing to research: detected /research prefix in message: {content[:100]}")
            return "research"
        else:
            logger.debug(f"[Route] No /research prefix (starts with: {content_lower[:20]})")
        # 用户输入 /training、根据报告建任务、提交任务 等 -> training
        if (
            content.startswith("/training")
            or "根据报告建任务" in content
            or "根据报告创建" in content
            or content in ("提交任务", "提交", "提交训练")
            or "提交训练任务" in content
        ):
            if _create_training_graph is not None:
                return "training"
        # 已有 proposed_training 且最后一条是用户回复（确认/修改/取消）-> training
        if state.get("proposed_training") is not None and _create_training_graph is not None:
            return "training"
    return "chat"


def create_agent():
    """
    Build and compile the conversation graph:
    START -> route -> [research | training | llm] -> END
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("llm", _chat_node_async)
    if _deep_researcher is not None:
        workflow.add_node("research", _research_node_async)
    if _create_training_graph is not None:
        workflow.add_node("training", _training_node)

    # 路由：research | training | chat
    dest = {"chat": "llm"}
    if _deep_researcher is not None:
        dest["research"] = "research"
    if _create_training_graph is not None:
        dest["training"] = "training"
    workflow.add_conditional_edges(START, _route, dest)

    # llm 直接 END（chat tools disabled）
    workflow.add_edge("llm", END)
    if _deep_researcher is not None:
        workflow.add_edge("research", END)
    if _create_training_graph is not None:
        workflow.add_edge("training", END)

    return workflow.compile()
