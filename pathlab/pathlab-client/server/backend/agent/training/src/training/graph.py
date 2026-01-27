"""
Training graph with clarify: propose_create_training_task -> user confirm/modify -> create_training_task.
确认/取消/修改/参数抽取 均基于 LLM，无正则兜底。
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .tool import (
    _create_training_task_sync,
    _format_training_params_for_confirm,
    delete_training_task_tool,
    get_training_logs_tool,
    get_recent_training_logs_tool,
    get_training_task_tool,
    get_training_task_models_tool,
    list_training_tasks_tool,
    list_wsi_tool,
    propose_create_training_task_tool,
)
from backend.agent.tools.pathlab import list_datasets_tool


def _strip_markdown_json(text: str) -> str:
    """从 LLM 返回中取出 JSON 串，兼容 ```json ... ``` 或 ``` ... ```，无正则。"""
    s = (text or "").strip()
    if "```" not in s:
        return s
    i = s.find("```")
    rest = s[i + 3 :].lstrip()
    if rest.lower().startswith("json"):
        rest = rest[4:].lstrip()
    j = rest.find("```")
    rest = rest[: j].strip() if j >= 0 else rest.strip()
    return rest or s


# Agent 只用 propose，不用 create_training_task；其余不变
TRAINING_TOOLS = [
    list_datasets_tool,
    list_wsi_tool,
    propose_create_training_task_tool,
    list_training_tasks_tool,
    get_training_task_tool,
    get_training_task_models_tool,
    delete_training_task_tool,
    get_training_logs_tool,
    get_recent_training_logs_tool,
]

TRAINING_AGENT_PROMPT = """You help users run WSI training: list datasets, list slides, create training tasks, check task status or models, view logs, and delete tasks.

Training pipelines:
- WSI-level (data_level='wsi'): preprocess (compute_patches) -> feature extraction -> MIL training (uses aggregator like abmil)
- Patch-level (data_level='patch'): Feature Extractor + Linear Probe training (skips patch extraction and feature extraction, does NOT use MIL/aggregator)

Tools:
- list_datasets: list all datasets in the database with file count and total size. Use this to help users understand what data is available before creating training tasks. Optionally filter by data_level (wsi or patch).
- list_wsi: list WSI slides. Output shows type=patch (裁切块) or type=slide (整张切片). Optionally filter by dataset_name to list WSI from a specific dataset. Use limit=0 to return all files (no pagination). Use wsi_ids for propose_create_training_task.
  IMPORTANT: If the user wants to use all data or mentions "全部"/"all"/"全部数据", use limit=0 to get all WSI IDs.
- propose_create_training_task: when the user wants to create a training task, you can:
  * First call list_datasets to show available datasets
  * Then call list_wsi (optionally with dataset_name, and use limit=0 if user wants all data) to see WSI slides and their types
  * Then determine data_level:
  * If user explicitly mentions "patch"/"patch-level"/"裁切块" → data_level='patch'
  * If user explicitly mentions "wsi"/"wsi-level"/"整张切片"/"slide" → data_level='wsi'
  * If list_wsi shows type=patch for selected wsi_ids → data_level='patch'
  * If list_wsi shows type=slide for selected wsi_ids → data_level='wsi'
  * If mixed types or unclear → default to 'wsi' and mention in confirmation
  Do NOT call create_training_task directly; always use propose_create_training_task first so the user can confirm or modify. Optional: tile_size, stride, feature_extractor, epochs, learning_rate, aggregator (aggregator only used for WSI-level, ignored for patch-level).
- list_training_tasks: list all training tasks and their status.
- get_training_task: get status and progress for a task_id.
- get_training_task_models: list trained models for a task_id (after training completes).
- delete_training_task: delete a training task and its files. Use mode='standard' to keep models, or 'complete' to delete everything.
- get_training_logs: get training logs for a task with optional level filtering (INFO, WARNING, ERROR) and pagination. Use to check training progress or debug issues.
- get_recent_training_logs: get the most recent N logs for a task. Quick way to see latest training progress.

IMPORTANT: If the most recent assistant message in the conversation already contains "Training task created" or "task_id=", and the user's new message is short and could mean run/confirm (e.g. 运行, 运行吧, 确认, 好, go, ok, 执行), do NOT call propose_create_training_task. The task was already created in the previous step. Reply that the task has been created and offer to check status with get_training_task if the user wants. Do NOT propose again.

Reply in the same language as the user."""


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class TrainingState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    proposed_training: dict | None
    _training_next: str | None  # "clarify" -> 再展示一次参数
    initial_training_params: dict | None  # 来自 research 报告 Section 7，作 propose 的默认


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def _agent_node_impl(state: TrainingState, llm: BaseChatModel) -> dict:
    msgs = state.get("messages") or []
    prompt = TRAINING_AGENT_PROMPT
    init = state.get("initial_training_params") or {}
    if init:
        prompt = prompt + "\n\n**Suggested parameters from research report (use as defaults when calling propose_create_training_task):**\n" + json.dumps(init, ensure_ascii=False, indent=2) + "\n\nYou must still call list_wsi first to get wsi_ids; merge the above into your propose call and let the user confirm or modify. task_name can be derived from the research topic or use a short default."
    to_invoke = [SystemMessage(content=prompt)] + msgs
    bound = llm.bind_tools(TRAINING_TOOLS)
    out = bound.invoke(to_invoke)
    return {"messages": [out]}


_CONFIRM_HINT = (
    "上面已列出将要使用的参数。请回复「确认」或「运行」以执行；"
    "若要修改请直接说明（如：epochs 20、tile_size 256）；取消请回复「取消」。"
)

_SKIP_CONFIRM_SYSTEM = """In this conversation the assistant already said "Training task created" or "task_id=". The user's most recent message is: "{last_user}".

Does this message mean the user wants to run/confirm that already-created task (e.g. 运行, 运行吧, 确认, 好, go, ok), so we should NOT show the parameter confirmation again? Answer only: yes or no."""


def _handle_tool_result_node_impl(state: TrainingState, llm: BaseChatModel) -> dict:
    msgs = state.get("messages") or []
    args = None
    aimessage_with_propose = None
    for m in reversed(msgs):
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                if tc.get("name") == "propose_create_training_task":
                    args = tc.get("args") or {}
                    aimessage_with_propose = m
                    break
            if args is not None:
                break

    if not args:
        return {}

    # 防护：若历史中已有「Training task created」，用 LLM 判断用户最后一条是否在确认已创建的任务，若是则不再设 proposed_training
    last_user = ""
    found_created = False
    for m in msgs:
        if isinstance(m, HumanMessage):
            last_user = (getattr(m, "content", None) or "").strip()
        elif isinstance(m, AIMessage) and m is not aimessage_with_propose:
            c = (getattr(m, "content", None) or "") or ""
            if "Training task created" in c or "task_id=" in c:
                found_created = True
    if found_created and last_user:
        try:
            prompt = _SKIP_CONFIRM_SYSTEM.format(last_user=last_user)
            resp = llm.invoke([HumanMessage(content=prompt)])
            text = (getattr(resp, "content", None) or "").strip().lower()
            if "yes" in text or "是" in text:
                return {}
        except Exception:
            pass

    return {"messages": [AIMessage(content=_CONFIRM_HINT)], "proposed_training": args}


# ---------------------------------------------------------------------------
# 确认/取消/修改：全 LLM 判定与参数抽取
# ---------------------------------------------------------------------------

_UPDATE_INT_KEYS = ("tile_size", "stride", "level", "feature_batch_size", "epochs")
_UPDATE_FLOAT_KEYS = ("learning_rate",)
_UPDATE_STR_KEYS = ("task_name", "task_type", "data_level", "feature_extractor", "aggregator", "task_description")

_EXTRACT_UPDATES_SYSTEM = """Extract parameter changes from the user's message. Valid keys: task_name, task_type, data_level, task_description, tile_size, stride, level, feature_extractor, feature_batch_size, epochs, learning_rate, aggregator.
Types: int (tile_size, stride, level, feature_batch_size, epochs), float (learning_rate), str (the rest).

User said: {user_text}

Output a JSON object with ONLY the changed key-value pairs, or {{}} if none. Output only valid JSON, no markdown or ```."""


def _extract_training_updates_from_text(content: str, llm: BaseChatModel) -> dict:
    if not (content or "").strip():
        return {}
    try:
        prompt = _EXTRACT_UPDATES_SYSTEM.format(user_text=(content or "").strip())
        resp = llm.invoke([HumanMessage(content=prompt)])
        text = _strip_markdown_json((getattr(resp, "content", None) or "").strip())
        obj = json.loads(text)
        return _validate_and_coerce_training_updates(obj) if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


_PARAM_INTENT_SYSTEM = """You classify the user's intent about training task parameters and extract any parameter changes.

Current parameters (JSON):
{current_json}

User said: {user_text}

Output a JSON object with exactly two keys:
- "action": one of "confirm" | "cancel" | "modify" | "unclear"
- "updates": object of parameter changes, or {{}} when not applicable

Meaning:
- "confirm": user agrees to run. E.g. 确认, 运行, ok, yes, 可以, 执行, 好, go, run, 不用改, 没问题. Set "updates" to {{}}.
- "cancel": user wants to abort. E.g. 取消, cancel, 不用了, 不做了, 算了, stop. Set "updates" to {{}}.
- "modify": user wants to change parameters. Put ONLY changed key-value pairs in "updates". E.g. "epochs 20" -> {{"action":"modify","updates":{{"epochs":20}}}}; "tile_size 256" -> {{"updates":{{"tile_size":256}}}}.
- "unclear": cannot tell. Set "updates" to {{}}.

Valid keys for "updates": task_name, task_type, data_level, task_description, tile_size, stride, level, feature_extractor, feature_batch_size, epochs, learning_rate, aggregator.
- int: tile_size, stride, level, feature_batch_size, epochs
- float: learning_rate
- str: task_name, task_type, data_level, feature_extractor, aggregator, task_description

Output only valid JSON, no markdown or ```."""

_VALID_ACTIONS = {"confirm", "cancel", "modify", "unclear"}


def _validate_and_coerce_training_updates(obj: dict) -> dict:
    out = {}
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        try:
            if k in _UPDATE_INT_KEYS:
                out[k] = int(v) if not isinstance(v, int) else v
            elif k in _UPDATE_FLOAT_KEYS:
                out[k] = float(v) if not isinstance(v, (int, float)) else float(v)
            elif k in _UPDATE_STR_KEYS and v is not None:
                out[k] = str(v).strip() if v != "" else None
                if out[k] is None and k != "task_description":
                    del out[k]
        except (TypeError, ValueError):
            continue
    return out


def _classify_training_intent(content: str, current: dict, llm: BaseChatModel) -> dict:
    if not (content or "").strip():
        return {"action": "unclear", "updates": {}}
    try:
        current_json = json.dumps(current, ensure_ascii=False, indent=2)
    except Exception:
        current_json = "{}"
    prompt = _PARAM_INTENT_SYSTEM.format(current_json=current_json, user_text=(content or "").strip())
    try:
        resp = llm.invoke([HumanMessage(content=prompt)])
        text = _strip_markdown_json((getattr(resp, "content", None) or "").strip())
        obj = json.loads(text)
        action = (obj.get("action") or "").strip().lower()
        if action not in _VALID_ACTIONS:
            action = "unclear"
        raw = obj.get("updates")
        updates = _validate_and_coerce_training_updates(raw) if isinstance(raw, dict) else {}
        return {"action": action, "updates": updates}
    except (json.JSONDecodeError, TypeError, ValueError, KeyError):
        return {"action": "unclear", "updates": {}}


def _handle_training_confirm_node_impl(state: TrainingState, llm: BaseChatModel) -> dict:
    prop = state.get("proposed_training") or {}
    msgs = state.get("messages") or []
    last = msgs[-1] if msgs else None
    if not isinstance(last, HumanMessage):
        return {"_training_next": None}

    content = (getattr(last, "content", None) or "") if last else ""
    intent = _classify_training_intent(content, prop, llm)

    if intent["action"] == "cancel":
        return {
            "messages": [AIMessage(content="已取消创建训练任务。")],
            "proposed_training": None,
            "_training_next": None,
        }

    if intent["action"] == "confirm":
        print(
            f"[DEBUG Training] 用户确认，调用 create_training_task 参数 keys={list(prop.keys())} "
            f"task_name={prop.get('task_name')!r} wsi_ids={prop.get('wsi_ids', [])[:3]}",
            flush=True,
        )
        res = _create_training_task_sync(**prop)
        return {
            "messages": [AIMessage(content=res)],
            "proposed_training": None,
            "_training_next": None,
        }

    if intent["action"] == "modify":
        up = intent.get("updates") or {}
        if not up:
            up = _extract_training_updates_from_text(content, llm)
        if up:
            new_prop = {**prop, **up}
            return {"proposed_training": new_prop, "_training_next": "clarify"}
        return {
            "messages": [AIMessage(content="未识别到要修改的参数，请直接说明（如 epochs 20、tile_size 256）；确认请回复 确认；取消请回复 取消。")],
            "_training_next": None,
        }

    # unclear：再试一次 LLM 纯参数抽取
    up = _extract_training_updates_from_text(content, llm)
    if up:
        new_prop = {**prop, **up}
        return {"proposed_training": new_prop, "_training_next": "clarify"}

    return {
        "messages": [AIMessage(content="请明确回复：确认/运行 以执行；或说明要修改的参数，例如 epochs 20、tile_size 256；取消 则放弃。")],
        "_training_next": None,
    }


def _clarify_training_node(state: TrainingState) -> dict:
    prop = state.get("proposed_training") or {}
    txt = _format_training_params_for_confirm(**prop)
    return {"messages": [AIMessage(content=txt)], "_training_next": None}


# ---------------------------------------------------------------------------
# Conditional edges
# ---------------------------------------------------------------------------

def _after_start(state: TrainingState) -> Literal["handle_training_confirm", "agent"]:
    prop = state.get("proposed_training")
    msgs = state.get("messages") or []
    if prop and msgs and isinstance(msgs[-1], HumanMessage):
        return "handle_training_confirm"
    return "agent"


def _after_agent(state: TrainingState) -> Literal["tools", "__end__"]:
    msgs = state.get("messages") or []
    if msgs and hasattr(msgs[-1], "tool_calls") and msgs[-1].tool_calls:
        return "tools"
    return "__end__"


def _after_tools(state: TrainingState) -> Literal["handle_tool_result"]:
    return "handle_tool_result"


def _after_handle_tool_result(state: TrainingState) -> Literal["__end__", "agent"]:
    if state.get("proposed_training") is not None:
        return "__end__"
    return "agent"


def _after_handle_training_confirm(state: TrainingState) -> Literal["clarify_training", "__end__"]:
    if state.get("_training_next") == "clarify":
        return "clarify_training"
    return "__end__"


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def create_training_graph(llm: BaseChatModel | None = None):
    """
    构建 training LangGraph：propose_create_training_task -> 用户确认或改参 -> create_training_task。
    - llm: None 时从 backend.agent.llm.get_llm 获取。
    - 输入 state：messages；多轮需传入 proposed_training。
    - 环境：GATEWAY_SERVICE_URL（tools 用）。
    """
    if llm is None:
        from backend.agent.llm import get_llm

        _llm = get_llm()
    else:
        _llm = llm

    def agent_node(s: TrainingState) -> dict:
        return _agent_node_impl(s, _llm)

    def handle_tool_result_node(s: TrainingState) -> dict:
        return _handle_tool_result_node_impl(s, _llm)

    def handle_training_confirm_node(s: TrainingState) -> dict:
        return _handle_training_confirm_node_impl(s, _llm)

    builder = StateGraph(TrainingState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(TRAINING_TOOLS))
    builder.add_node("handle_tool_result", handle_tool_result_node)
    builder.add_node("handle_training_confirm", handle_training_confirm_node)
    builder.add_node("clarify_training", _clarify_training_node)

    builder.add_conditional_edges(START, _after_start)
    builder.add_conditional_edges("agent", _after_agent)
    builder.add_edge("tools", "handle_tool_result")
    builder.add_conditional_edges("handle_tool_result", _after_handle_tool_result)
    builder.add_conditional_edges("handle_training_confirm", _after_handle_training_confirm)
    builder.add_edge("clarify_training", END)

    return builder.compile()
