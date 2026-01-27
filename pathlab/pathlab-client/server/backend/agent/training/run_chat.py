"""
REPL 对话测试 training tools：list_wsi, propose_create_training_task（→ 确认/修改）→ create_training_task,
list_training_tasks, get_training_task, get_training_task_models.

用法（在 pathlab-client/server 下）:
  export VLLM_URL="http://localhost:8000/v1"
  export VLLM_KEY="sk-pathlab"   # 如需要
  uv run python -m backend.agent.training.run_chat

示例输入：
  - 有哪些 WSI？ / list wsi
  - 用 s1、s2 建一个分类训练任务 → 会先 propose 参数，确认/运行 执行，或说明修改（如 epochs 20）
  - 训练任务列表 / 任务 train_xxx 状态 / 任务 train_xxx 的模型
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.agent.training import create_training_graph


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
    g = create_training_graph()
    print("Training 对话测试（list_wsi / propose→确认参数→create_training_task / list_training_tasks / get_training_task / get_training_task_models）")
    print("示例：有哪些 WSI / 用 s1 s2 建训练任务（会先展示参数供确认或修改）/ 任务列表 / 任务 train_xxx 状态")
    print("空行退出。\n")

    state: dict = {"messages": []}
    while True:
        try:
            line = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break

        prev = state.get("messages") or []
        result = g.invoke({
            "messages": prev + [HumanMessage(content=line)],
            "proposed_training": state.get("proposed_training"),
        })
        state = result
        msgs = result.get("messages", [])

        if _has_tool_message(msgs):
            print("[OK] 检测到 ToolMessage：")
            print(_tool_summary(msgs))
        if state.get("proposed_training") is not None:
            print("[--] 已记录参数，等待确认。回复 确认/运行 执行，或说明修改（如 epochs 20、tile_size 256）。")

        last = _last_ai_text(msgs)
        if last:
            print("Model 最后回复:", last[:800] + ("..." if len(last) > 800 else ""))
        print()

    print("Bye.")


if __name__ == "__main__":
    main()
