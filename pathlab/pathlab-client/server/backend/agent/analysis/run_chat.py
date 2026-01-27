"""
REPL 对话测试 analysis tools: list_analysis_tasks, run_task_analysis, get_task_analysis, get_analysis_stats.

用法（在 pathlab-client/server 下）:
  export VLLM_URL="http://localhost:8000/v1"
  export VLLM_KEY="sk-pathlab"   # 如需要
  uv run python -m backend.agent.analysis.run_chat

示例输入：
  - 有哪些任务可以分析？ / list analysis tasks
  - 分析一下 train_xxx 任务 / run analysis for train_xxx
  - train_xxx 的分析历史 / analysis history for train_xxx
  - train_xxx 的统计信息 / stats for train_xxx
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.agent.analysis import create_analysis_graph


def _has_tool_message(msgs) -> bool:
    return any(isinstance(m, ToolMessage) for m in msgs)


def _last_ai_text(msgs) -> str:
    for m in reversed(msgs):
        if isinstance(m, AIMessage) and (getattr(m, "content", None) or "").strip():
            return (m.content or "").strip()
    return ""


def _tool_summary(msgs) -> str:
    lines = []
    for m in msgs:
        if isinstance(m, ToolMessage):
            name = getattr(m, "name", "?")
            content = (getattr(m, "content", "") or "")[:500]
            lines.append(f"[Tool {name}]: {content}")
    return "\n".join(lines) if lines else "(none)"


def main():
    g = create_analysis_graph()
    
    print("Analysis 对话测试（list_analysis_tasks / run_task_analysis / get_task_analysis / get_analysis_stats）")
    print("示例：有哪些任务可以分析 / 分析一下 train_xxx / train_xxx 的分析历史 / train_xxx 的统计信息")
    print("空行退出。\n")

    state: dict = {"messages": []}
    while True:
        try:
            user_input = input("User: ").strip()
            if not user_input:
                break

            state["messages"].append(HumanMessage(content=user_input))
            state = g.invoke(state)

            # Print tool calls if any
            if _has_tool_message(state["messages"]):
                print(f"\n[Tools used]:\n{_tool_summary(state['messages'])}\n")

            # Print last AI response
            ai_text = _last_ai_text(state["messages"])
            if ai_text:
                print(f"Assistant: {ai_text}\n")
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"Error: {e}\n")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
