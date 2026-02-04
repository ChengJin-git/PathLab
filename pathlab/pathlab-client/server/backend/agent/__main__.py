"""
LangGraph 对话 agent REPL，默认连本地 vLLM。

  cd server && uv run python -m backend.agent

Key/URL/模型 从 backend.agent.api_keys 读取，见 api_keys.env.example。
/research <问题> 调用 open_deep_research 做深度研究（需 TAVILY_API_KEY、VLLM_* 或云模型）。

架构：
- 外层对话总控图（dialog_graph）：负责路由到 chat 或 research
- deep_researcher 子图：处理深度研究流程（clarify、confirm_brief、research_supervisor 等）
- 使用 astream 实现流式：Research 的 status/search_result/search_hit 等 custom 事件会实时打印。
- 支持 interrupt()：research 子图中的 interrupt 会暂停执行，等待用户输入后继续。
"""
import asyncio
import os
import sys
import time

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from . import api_keys
from .dialog_graph import create_dialog_agent
from .logger import build_logger, new_session_id


def _usage_from_callback(handler: UsageMetadataCallbackHandler) -> tuple[int, int, int]:
    """从 UsageMetadataCallbackHandler.usage_metadata 汇总 input/output/total。支持单层或 per-model 嵌套。"""
    um = getattr(handler, "usage_metadata", None) or {}
    if not isinstance(um, dict):
        return 0, 0, 0
    inp, out, tot = 0, 0, 0
    for k, v in um.items():
        if isinstance(v, dict):
            inp += int(v.get("input_tokens") or v.get("prompt_tokens") or 0)
            out += int(v.get("output_tokens") or v.get("completion_tokens") or 0)
            tot += int(v.get("total_tokens") or 0)
        elif k in ("input_tokens", "prompt_tokens") and isinstance(v, (int, float)):
            inp = int(v)
        elif k in ("output_tokens", "completion_tokens") and isinstance(v, (int, float)):
            out = int(v)
        elif k == "total_tokens" and isinstance(v, (int, float)):
            tot = int(v)
    if inp == 0 and out == 0 and tot == 0 and um:
        # 单层：input_tokens/output_tokens/total_tokens 在顶层
        inp = int(um.get("input_tokens") or um.get("prompt_tokens") or 0)
        out = int(um.get("output_tokens") or um.get("completion_tokens") or 0)
        tot = int(um.get("total_tokens") or 0)
    if tot == 0 and (inp or out):
        tot = inp + out
    return inp, out, tot


def _print_custom_event(chunk: dict, *, logger=None, turn_start: float | None = None) -> None:
    """格式化并打印 Research 的 custom 流式事件。"""
    if not isinstance(chunk, dict):
        print(f"[Research] {chunk}", flush=True)
        if logger:
            logger.log_event({
                "event": "custom",
                "content": str(chunk),
                "meta": _timing_meta(turn_start),
            })
        return
    t = chunk.get("type", "")
    if t == "status":
        stage = chunk.get("stage", "")
        topic = (chunk.get("topic") or "")[:80]
        print(f"[Research] {stage} {topic}".strip(), flush=True)
        if logger:
            logger.log_event({
                "event": "status",
                "meta": {**_timing_meta(turn_start), "stage": stage, "topic": topic},
            })
    elif t == "search_result":
        topic = (chunk.get("topic") or "")[:60]
        snip = (chunk.get("snippet") or "")[:100]
        print(f"[Research] 结果: {topic}: {snip}…", flush=True)
        if logger:
            logger.log_event({
                "event": "search_result",
                "meta": {**_timing_meta(turn_start), "topic": topic, "snippet": snip},
            })
    elif t == "search_hit":
        src = chunk.get("source", "")
        topic = (chunk.get("topic") or "")[:60]
        print(f"[Research] 搜索: {src} | {topic}", flush=True)
        if logger:
            logger.log_event({
                "event": "search_hit",
                "meta": {**_timing_meta(turn_start), "source": src, "topic": topic},
            })
    else:
        print(f"[Research] {chunk}", flush=True)
        if logger:
            logger.log_event({
                "event": "custom",
                "meta": {**_timing_meta(turn_start), "data": chunk},
            })


def _timing_meta(turn_start: float | None) -> dict:
    if turn_start is None:
        return {}
    return {"since_turn_start_ms": int((time.monotonic() - turn_start) * 1000)}


async def run_repl() -> None:
    # 确保环境变量已设置（用于 research 子图）
    for k, v in [
        ("VLLM_URL", api_keys.vllm_url()),
        ("VLLM_KEY", api_keys.vllm_key()),
        ("VLLM_MODEL", api_keys.vllm_model()),
        ("TAVILY_API_KEY", api_keys.tavily_api_key()),
    ]:
        if v and not os.environ.get(k):
            os.environ[k] = str(v)

    base = api_keys.vllm_url() or api_keys.DEFAULT_VLLM_URL
    model = api_keys.vllm_model() or api_keys.DEFAULT_VLLM_MODEL

    session_id = new_session_id("repl")
    thread_id = "main-repl"
    logger = build_logger(session_id=session_id, thread_id=thread_id)
    session_start = time.monotonic()
    turns = 0

    logger.log_event({
        "event": "session_start",
        "meta": {"base_url": base, "model": model},
    })
    log_path = getattr(logger, "path", None)
    if log_path:
        print(f"[Log] {log_path}", flush=True)

    def _log_session_summary() -> None:
        logger.log_event({
            "event": "session_summary",
            "meta": {
                "duration_ms": int((time.monotonic() - session_start) * 1000),
                "turns": turns,
            },
        })

    def _exit(code: int = 0) -> None:
        _log_session_summary()
        logger.close()
        sys.exit(code)
    print("PathLab Agent (LangGraph) — 本地 vLLM", flush=True)
    print(f"  URL:   {base}", flush=True)
    print(f"  Model: {model}", flush=True)
    print("  /quit 或 /q 退出，/clear 清空历史", flush=True)
    print("  /research <问题> 深度研究", flush=True)
    print("  控制 research 搜索量: MAX_RESEARCHER_ITERATIONS, MAX_CONCURRENT_RESEARCH_UNITS, MAX_REACT_TOOL_CALLS, TAVILY_MAX_RESULTS_PER_QUERY", flush=True)
    print("-" * 50, flush=True)

    # 创建 checkpointer 以支持 interrupt()
    checkpointer = MemorySaver()
    app = create_dialog_agent(checkpointer=checkpointer)
    
    state: dict = {"messages": []}
    config = {"configurable": {"thread_id": thread_id}}

    while True:
        try:
            line = (await asyncio.to_thread(input, "You: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.", flush=True)
            logger.log_event({"event": "system", "content": "exit"})
            _exit(0)
        if not line:
            continue
        if line.lower() in ("/quit", "/q", "quit", "exit"):
            print("Bye.", flush=True)
            logger.log_event({"event": "system", "content": "exit_command"})
            _exit(0)
        if line.lower() == "/clear":
            state = {
                "messages": [],
                "research_status": "idle",
            }
            # 清空 checkpointer 中的状态
            checkpointer.put(config["configurable"], {})
            print("[History cleared]", flush=True)
            logger.log_event({"event": "system", "content": "clear_history"})
            continue

        turns += 1
        turn_id = turns
        turn_start = time.monotonic()
        logger.log_event({
            "event": "user_message",
            "content": line,
            "meta": {"turn_id": turn_id},
        })

        # 检查是否有 interrupt 需要恢复
        # 如果 state 中有 research_status="awaiting_user"，说明 research 子图在等待用户输入
        # 这种情况下，使用 Command(resume=...) 继续执行
        need_resume = state.get("research_status") == "awaiting_user"
        
        if need_resume:
            # 恢复 interrupt：使用 Command(resume=...) 继续执行
            input_data = Command(resume=line)
        else:
            # 正常流程：添加用户消息到 state
            state["messages"].append(HumanMessage(content=line))
            input_data = state

        # 如果是 research 请求，显示提示信息
        if line.lower().startswith("/research"):
            print("Research 运行中（Tavily 搜索 + 多轮推理，可能需要较长时间，请稍候）…", flush=True)
            logger.log_event({"event": "system", "content": "research_start", "meta": {"turn_id": turn_id}})

        # UsageMetadataCallbackHandler 聚合全图 LLM 调用的 token，经 config 传入
        callback = UsageMetadataCallbackHandler()
        iter_config = {**config, "callbacks": [callback]}

        # 使用 astream 消费 values + custom；llm_chunk 实时打印（打字机效果）
        try:
            last_values = None
            did_stream_llm = False
            need_agent_prefix = True
            last_custom_was_llm_chunk = False
            stream_buffer: list[str] = []
            before_len = len(state.get("messages", []))

            async for event in app.astream(input_data, iter_config, stream_mode=["values", "custom"]):
                if isinstance(event, (list, tuple)) and len(event) >= 2:
                    mode, chunk = event[0], event[1]
                else:
                    mode, chunk = "values", event

                if mode == "custom":
                    if isinstance(chunk, dict) and chunk.get("type") == "llm_chunk":
                        if need_agent_prefix:
                            print("Agent: ", end="", flush=True)
                            need_agent_prefix = False
                        did_stream_llm = True
                        last_custom_was_llm_chunk = True
                        content = chunk.get("content", "")
                        if content:
                            stream_buffer.append(content)
                            print(content, end="", flush=True)
                    else:
                        _print_custom_event(chunk, logger=logger, turn_start=turn_start)
                        last_custom_was_llm_chunk = False

                if mode == "values":
                    if last_custom_was_llm_chunk:
                        print(flush=True)
                        need_agent_prefix = True
                        last_custom_was_llm_chunk = False
                    last_values = chunk

            if last_custom_was_llm_chunk:
                print(flush=True)

            out = last_values if last_values is not None else state
            state = out

            # 全图 token 用量（Chat / Research 的 LLM 调用）
            pi, po, pt = _usage_from_callback(callback)
            if pi or po or pt:
                print(f"[Token使用] 输入: {pi} | 输出: {po} | 总计: {pt}", flush=True)
                logger.log_event({
                    "event": "token_usage",
                    "meta": {"input": pi, "output": po, "total": pt, "turn_id": turn_id},
                })

            # 显示所有消息（包括中间搜索结果和最终报告）
            messages = out.get("messages", [])
            if messages:
                final_report = out.get("final_report")
                # 仅当 research 刚完成时，整块打印最终报告
                if final_report:
                    for msg in messages:
                        if hasattr(msg, "content") and msg.content:
                            print(f"Agent: {msg.content}", flush=True)
                    # 清理 research 相关字段
                    out["research_brief"] = None
                    out["supervisor_messages"] = None
                    out["notes"] = None
                    out["raw_notes"] = None
                    out["research_status"] = "idle"
                    state = out
                    print("-" * 50, flush=True)
                    # log assistant output for this turn
                    new_messages = messages[before_len:] if len(messages) >= before_len else messages
                    assistant_texts = []
                    for msg in new_messages:
                        msg_type = getattr(msg, "type", "")
                        content = getattr(msg, "content", None)
                        if msg_type != "human" and content:
                            assistant_texts.append(str(content))
                    if not assistant_texts and stream_buffer:
                        assistant_texts = ["".join(stream_buffer)]
                    if assistant_texts:
                        logger.log_event({
                            "event": "assistant_message",
                            "content": "\n".join(assistant_texts),
                            "meta": {
                                "turn_id": turn_id,
                                "final_report": True,
                                "research_status": out.get("research_status") or "idle",
                            },
                        })
                    logger.log_event({
                        "event": "turn_timing",
                        "meta": {
                            "turn_id": turn_id,
                            "elapsed_ms": int((time.monotonic() - turn_start) * 1000),
                            "user_len": len(line),
                            "assistant_len": sum(len(t) for t in assistant_texts) if assistant_texts else 0,
                            "research_status": out.get("research_status") or "idle",
                        },
                    })
                    continue
                
                # 非 final_report：显示最后一条消息（若已通过 llm_chunk 流式打印则跳过）
                if not did_stream_llm:
                    last = messages[-1]
                    text = last.content if hasattr(last, "content") else str(last)
                    print(f"Agent: {text}", flush=True)

                research_status = out.get("research_status") or "idle"
                if research_status == "awaiting_user":
                    # research 子图在等待用户输入（interrupt），下一轮会使用 Command(resume=...)
                    print("[Research] 等待用户输入...", flush=True)
                    print("-" * 50, flush=True)
                    # log assistant output for this turn
                    new_messages = messages[before_len:] if len(messages) >= before_len else messages
                    assistant_texts = []
                    for msg in new_messages:
                        msg_type = getattr(msg, "type", "")
                        content = getattr(msg, "content", None)
                        if msg_type != "human" and content:
                            assistant_texts.append(str(content))
                    if not assistant_texts and stream_buffer:
                        assistant_texts = ["".join(stream_buffer)]
                    if assistant_texts:
                        logger.log_event({
                            "event": "assistant_message",
                            "content": "\n".join(assistant_texts),
                            "meta": {"turn_id": turn_id, "research_status": research_status},
                        })
                    logger.log_event({
                        "event": "turn_timing",
                        "meta": {
                            "turn_id": turn_id,
                            "elapsed_ms": int((time.monotonic() - turn_start) * 1000),
                            "user_len": len(line),
                            "assistant_len": sum(len(t) for t in assistant_texts) if assistant_texts else 0,
                            "research_status": research_status,
                        },
                    })
                    continue
                elif research_status == "running":
                    # research 正在运行中
                    print("-" * 50, flush=True)
                    # log assistant output for this turn
                    new_messages = messages[before_len:] if len(messages) >= before_len else messages
                    assistant_texts = []
                    for msg in new_messages:
                        msg_type = getattr(msg, "type", "")
                        content = getattr(msg, "content", None)
                        if msg_type != "human" and content:
                            assistant_texts.append(str(content))
                    if not assistant_texts and stream_buffer:
                        assistant_texts = ["".join(stream_buffer)]
                    if assistant_texts:
                        logger.log_event({
                            "event": "assistant_message",
                            "content": "\n".join(assistant_texts),
                            "meta": {"turn_id": turn_id, "research_status": research_status},
                        })
                    logger.log_event({
                        "event": "turn_timing",
                        "meta": {
                            "turn_id": turn_id,
                            "elapsed_ms": int((time.monotonic() - turn_start) * 1000),
                            "user_len": len(line),
                            "assistant_len": sum(len(t) for t in assistant_texts) if assistant_texts else 0,
                            "research_status": research_status,
                        },
                    })
                    continue
            else:
                if not did_stream_llm:
                    print("Agent: (无回复)", flush=True)

            # log assistant output for this turn
            new_messages = messages[before_len:] if len(messages) >= before_len else messages
            assistant_texts = []
            for msg in new_messages:
                msg_type = getattr(msg, "type", "")
                content = getattr(msg, "content", None)
                if msg_type != "human" and content:
                    assistant_texts.append(str(content))
            if not assistant_texts and stream_buffer:
                assistant_texts = ["".join(stream_buffer)]
            if assistant_texts:
                logger.log_event({
                    "event": "assistant_message",
                    "content": "\n".join(assistant_texts),
                    "meta": {
                        "turn_id": turn_id,
                        "research_status": out.get("research_status") or "idle",
                    },
                })
            logger.log_event({
                "event": "turn_timing",
                "meta": {
                    "turn_id": turn_id,
                    "elapsed_ms": int((time.monotonic() - turn_start) * 1000),
                    "user_len": len(line),
                    "assistant_len": sum(len(t) for t in assistant_texts) if assistant_texts else 0,
                    "research_status": out.get("research_status") or "idle",
                },
            })

            print("-" * 50, flush=True)
        except Exception as e:
            print(f"Error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            logger.log_event({
                "event": "error",
                "content": str(e),
                "meta": {
                    "turn_id": turn_id,
                    "elapsed_ms": int((time.monotonic() - turn_start) * 1000),
                },
            })
            print("-" * 50, flush=True)


def main() -> None:
    asyncio.run(run_repl())


if __name__ == "__main__":
    main()
