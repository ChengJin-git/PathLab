"""
LangGraph 对话 agent REPL，默认连本地 vLLM。

  cd server && uv run python -m backend.agent

Key/URL/模型 从 backend.agent.api_keys 读取，见 api_keys.env.example。
/research <问题> 调用 open_deep_research 做深度研究（需 TAVILY_API_KEY、VLLM_* 或云模型）。

Research 现在是主 agent graph 的子图，会自动处理多轮交互（clarify、confirm_brief 等）。
使用 astream 实现流式：Research 的 status/search_result/search_hit 等 custom 事件会实时打印。
"""
import asyncio
import os
import sys

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import HumanMessage

from . import api_keys
from .graph import create_agent


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


def _print_custom_event(chunk: dict) -> None:
    """格式化并打印 Research 的 custom 流式事件。"""
    if not isinstance(chunk, dict):
        print(f"[Research] {chunk}", flush=True)
        return
    t = chunk.get("type", "")
    if t == "status":
        stage = chunk.get("stage", "")
        topic = (chunk.get("topic") or "")[:80]
        print(f"[Research] {stage} {topic}".strip(), flush=True)
    elif t == "search_result":
        topic = (chunk.get("topic") or "")[:60]
        snip = (chunk.get("snippet") or "")[:100]
        print(f"[Research] 结果: {topic}: {snip}…", flush=True)
    elif t == "search_hit":
        src = chunk.get("source", "")
        topic = (chunk.get("topic") or "")[:60]
        print(f"[Research] 搜索: {src} | {topic}", flush=True)
    else:
        print(f"[Research] {chunk}", flush=True)


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
    print("PathLab Agent (LangGraph) — 本地 vLLM", flush=True)
    print(f"  URL:   {base}", flush=True)
    print(f"  Model: {model}", flush=True)
    print("  /quit 或 /q 退出，/clear 清空历史", flush=True)
    print("  /research <问题> 深度研究；/training 或 根据报告建任务 创建训练（可接在 research 后）", flush=True)
    print("  普通对话可调 list_wsi 等 PathLab tools（如：帮我列一下 WSI）", flush=True)
    print("  控制 research 搜索量: MAX_RESEARCHER_ITERATIONS, MAX_CONCURRENT_RESEARCH_UNITS, MAX_REACT_TOOL_CALLS, TAVILY_MAX_RESULTS_PER_QUERY", flush=True)
    print("-" * 50, flush=True)

    app = create_agent()
    state: dict = {"messages": []}
    config = {"configurable": {"thread_id": "main-repl"}}

    while True:
        try:
            line = (await asyncio.to_thread(input, "You: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.", flush=True)
            sys.exit(0)
        if not line:
            continue
        if line.lower() in ("/quit", "/q", "quit", "exit"):
            print("Bye.", flush=True)
            sys.exit(0)
        if line.lower() == "/clear":
            state = {
                "messages": [],
                "research_status": "idle",
                "proposed_training": None,
                "initial_training_params": None,
                "_shown_final_report": False,
            }
            print("[History cleared]", flush=True)
            continue

        # 添加用户消息到 state
        state["messages"].append(HumanMessage(content=line))

        # 如果是 research 请求，显示提示信息
        if line.lower().startswith("/research"):
            print("Research 运行中（Tavily 搜索 + 多轮推理，可能需要较长时间，请稍候）…", flush=True)
        # 如果是 training 请求，显示提示
        if (
            line.strip().lower().startswith("/training")
            or "根据报告建任务" in line
            or "根据报告创建" in line
        ):
            print("Training 运行中（list_wsi → propose → 确认/修改 → create_training_task）…", flush=True)

        # UsageMetadataCallbackHandler 聚合全图 LLM 调用的 token，经 config 传入
        callback = UsageMetadataCallbackHandler()
        iter_config = {**config, "callbacks": [callback]}

        # 使用 astream 消费 values + custom；llm_chunk 实时打印（打字机效果）
        try:
            last_values = None
            did_stream_llm = False
            need_agent_prefix = True
            last_custom_was_llm_chunk = False

            async for event in app.astream(state, iter_config, stream_mode=["values", "custom"]):
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
                        print(chunk.get("content", ""), end="", flush=True)
                    else:
                        _print_custom_event(chunk)
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

            # 全图 token 用量（Chat / Research / Training 的 LLM 调用）
            pi, po, pt = _usage_from_callback(callback)
            if pi or po or pt:
                print(f"[Token使用] 输入: {pi} | 输出: {po} | 总计: {pt}", flush=True)

            # 显示所有消息（包括中间搜索结果和最终报告）
            messages = out.get("messages", [])
            if messages:
                final_report = out.get("final_report")
                has_research_brief = out.get("research_brief") is not None
                # 仅当 research 刚完成且尚未展示过最终报告时，整块打印并提示 /training
                if final_report and not out.get("_shown_final_report"):
                    for msg in messages:
                        if hasattr(msg, "content") and msg.content:
                            print(f"Agent: {msg.content}", flush=True)
                    out["research_brief"] = None
                    out["supervisor_messages"] = None
                    out["notes"] = None
                    out["raw_notes"] = None
                    out["research_status"] = "idle"
                    out["_shown_final_report"] = True
                    state = out
                    print("根据报告创建训练任务：输入 /training 或 根据报告建任务", flush=True)
                    print("-" * 50, flush=True)
                    continue
                
                # 非 final_report：显示最后一条消息（若已通过 llm_chunk 流式打印则跳过）
                if not did_stream_llm:
                    last = messages[-1]
                    text = last.content if hasattr(last, "content") else str(last)
                    print(f"Agent: {text}", flush=True)

                if out.get("proposed_training") is not None:
                    print("[--] 已列出参数，等待确认。回复 确认/运行 执行，或说明修改（如 epochs 20）；取消 则放弃。", flush=True)
                research_status = out.get("research_status") or "idle"
                if research_status in ("awaiting_user", "running"):
                    print("-" * 50, flush=True)
                    continue
            else:
                if not did_stream_llm:
                    print("Agent: (无回复)", flush=True)
            
            print("-" * 50, flush=True)
        except Exception as e:
            print(f"Error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            print("-" * 50, flush=True)


def main() -> None:
    asyncio.run(run_repl())


if __name__ == "__main__":
    main()
