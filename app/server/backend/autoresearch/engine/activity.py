"""Small public research receipts. Raw tool state stays in the research runtime."""

from __future__ import annotations

import json
import re


# Unknown/internal tools have no public step. Never use a raw tool name as copy.
PUBLIC_ACTIONS = {
    "search_web": "search_sources",
    "search_papers": "search_literature",
    "search_verified_citations": "search_literature",
    "search_passages": "review_evidence",
    "find_baselines": "review_evidence",
    "find_sota": "review_evidence",
    "read_paper": "read_source",
    "webfetch": "read_source",
    "websearch": "search_sources",
    "search_datasets": "search_data",
    "prepare_dataset": "prepare_data",
    "acquire_dataset": "download_data",
    "submit_computation": "analyze",
    "submit_experiment": "experiment",
    "get_job": "check_results",
    "cancel_job": "stop_work",
    "update_plan": "plan",
    "record_study_protocol": "plan",
    "record_study_review": "review_evidence",
    "record_research_decision": "review_evidence",
    "save_report_draft": "write_report",
    "generate_article": "write_report",
    "register_artifact": "save_file",
    "register_model": "publish_results",
    "register_features": "publish_results",
    "publish_analysis": "publish_results",
    "finish_research": "summarize",
    "request_help": "request_help",
}

_PRIVATE = re.compile(
    r"(?:https?|file)://|(?:^|\s)(?:/|~/|[A-Za-z]:[\\/])|"
    r"\b(?:api[_ -]?key|token|authorization|password|secret)\s*[:=]|"
    r"\b(?:pathlab_\w+|get_research_context|set_task_scope|load_skill|"
    r"skill|connector\w*|system[_ ]prompt|traceback|AGENTS\.md|opencode)\b|"
    r"系统提示|系統提示|内部指令|內部指令|加载技能|載入技能|"
    r"[{}<>`·•\x00-\x08\x0b\x0c\x0e-\x1f\u202a-\u202e\u2066-\u2069]",
    re.I,
)
_TOOL_NAME = re.compile(r"\b(?:" + "|".join(map(re.escape, PUBLIC_ACTIONS)) + r")\b", re.I)


def public_description(value: object) -> str:
    if not isinstance(value, str) or len(value) > 240 or _PRIVATE.search(value):
        return ""
    if _TOOL_NAME.search(value):
        return ""
    value = re.sub(r"\s+", " ", value).strip()
    return value[:117] + "…" if len(value) > 120 else value


def public_status(value: object) -> str:
    if not isinstance(value, str):
        return "running"
    if value in {"failed", "error"}:
        return "failed"
    if value in {"interrupted", "cancelled", "paused"}:
        return "interrupted"
    if value in {"completed", "success"}:
        return "completed"
    return "running"


def _failed_output(value: object) -> bool:
    if isinstance(value, str):
        if len(value) > 16000:
            return False
        try:
            value = json.loads(value)
        except ValueError:
            return False
    if not isinstance(value, dict):
        return False
    if value.get("success") is False or value.get("isError") is True:
        return True
    # The MCP bridge wraps business results in JSON text. Inspect one bounded
    # level only, never pass any of that content into the public activity.
    for part in (value.get("content") or [])[:1]:
        if not isinstance(part, dict) or part.get("type") != "text":
            continue
        text = part.get("text")
        if isinstance(text, str) and len(text) <= 16000:
            try:
                result = json.loads(text)
            except ValueError:
                continue
            if isinstance(result, dict) and result.get("success") is False:
                return True
    return False


def project_tool(part: dict, language: str) -> dict | None:
    action = PUBLIC_ACTIONS.get(str(part.get("name", "")).removeprefix("pathlab_"))
    if not action:
        return None
    state = part.get("state") or {}
    arguments = state.get("input")
    arguments = arguments if isinstance(arguments, dict) else {}
    if action == "read_source" and arguments.get("action") == "download":
        action = "download_source"
    status = public_status(state.get("status"))
    # A successful tool invocation can still report a failed article read/job.
    if _failed_output(state.get("output")):
        status = "failed"
    return {
        "type": "activity", "id": part.get("id", ""),
        "action": action, "status": status,
        "description": public_description(arguments.get("activity")),
        "language": language,
    }


def project_event(event: dict, language: str) -> dict:
    """One API projection for SSE, initial snapshots and paged activity."""
    kind = event.get("kind")
    base = {key: event[key] for key in ("kind", "seq", "ts", "activity_seq", "step_id") if key in event}
    if kind == "native_work":
        active = bool(event.get("root_active") or event.get("children") or event.get("shells") or event.get("inbox"))
        # At most one public topic, regardless of how many descendants are active.
        titles = (public_description(child.get("title")) for child in reversed(event.get("children") or []))
        return {**base, "status": "running" if active else "completed", "action": "work",
                "description": next((title for title in titles if title), ""), "language": language}
    if kind == "message":
        message = event.get("message") or {}
        if message.get("type") != "assistant" or (message.get("metadata") or {}).get("pathlabInternal"):
            return {**base, "kind": "internal"}
        content = []
        for part in message.get("content", []):
            if part.get("type") == "text":
                content.append({"type": "text", "text": part.get("text", "")})
            elif part.get("type") == "tool":
                projected = project_tool(part, language)
                if projected:
                    content.append(projected)
        return {**base, "message": {"id": message.get("id"), "type": "assistant",
                                    "text": message.get("text", ""), "content": content}}
    if kind in {"literature", "dataset", "job", "error"}:
        action = {"literature": "search_literature", "dataset": "prepare_data", "job": "check_results", "error": "work"}[kind]
        # Metrics and logs have dedicated result/file APIs; no raw tool payloads here.
        return {**base, **({"job_id": event["job_id"]} if event.get("job_id") else {}),
                "action": action, "status": "failed" if kind == "error" else public_status(event.get("status", "completed")),
                "description": ""}
    return event
