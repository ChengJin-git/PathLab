"""Private process-log helpers for paper-generation runs."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from .llm import LLMResponse
from .schemas import PaperManifest
from .storage import PaperRunPaths

PIPELINE_LOG_REL_PATH = "logs/pipeline_log.private.json"
LOG_TEXT_LIMIT = 200_000
EventSink = Callable[[dict[str, Any]], None]


def register_private_log_artifact(
    manifest: PaperManifest,
    rel_path: str,
    *,
    label: str,
) -> None:
    manifest.artifact_index[rel_path] = {
        "status": "ready",
        "visibility": "private_backend_only",
        "downloadable": False,
        "label": label,
        "content_type": "application/json",
    }


def append_pipeline_event(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    event: str,
    *,
    stage: str,
    **payload: Any,
) -> None:
    """Append a private, per-run event without bloating manifest.stage_log."""
    register_private_log_artifact(manifest, PIPELINE_LOG_REL_PATH, label="Pipeline process log")
    path = paths.root / PIPELINE_LOG_REL_PATH
    log = _read_log(path, paper_id=paths.paper_id)
    events = log.setdefault("events", [])
    if not isinstance(events, list):
        events = []
        log["events"] = events
    events.append(
        json_safe(
            {
                "ts": utc_iso(),
                "event": event,
                "stage": stage,
                "run_status": _enum_value(manifest.status),
                "current_stage": _enum_value(manifest.current_stage),
                "artifact_count": len(manifest.artifact_index),
                "stage_log_count": len(manifest.stage_log),
                **payload,
            }
        )
    )
    log["paper_id"] = paths.paper_id
    log["schema_version"] = 1
    log["event_count"] = len(events)
    log["updated_at"] = utc_iso()
    write_json_file(path, log)


def write_stage_process_log(
    paths: PaperRunPaths,
    rel_path: str,
    *,
    stage: str,
    status: str,
    started_at: datetime,
    events: Sequence[Mapping[str, Any]],
    error: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    finished_at = datetime.now(UTC)
    payload: dict[str, Any] = {
        "paper_id": paths.paper_id,
        "stage": stage,
        "status": status,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_ms": max(0, int((finished_at - started_at).total_seconds() * 1000)),
        "error": dict(error) if error is not None else None,
        "event_count": len(events),
        "events": list(events),
    }
    if extra:
        payload.update(dict(extra))
    write_json_file(paths.root / rel_path, json_safe(payload))


def emit_event(sink: EventSink | None, event: str, **payload: Any) -> None:
    if sink is None:
        return
    sink(json_safe({"ts": utc_iso(), "event": event, **payload}))


def emit_llm_request(
    sink: EventSink | None,
    step: str,
    *,
    messages: Sequence[Any],
    temperature: float,
    response_format: Mapping[str, Any] | None,
) -> None:
    emit_event(
        sink,
        "llm_request",
        step=step,
        temperature=temperature,
        response_format=dict(response_format or {}),
        messages=[
            {
                "role": _message_role(message),
                "content": truncate_text(_message_content(message)),
                "content_length": len(_message_content(message)),
                "truncated": len(_message_content(message)) > LOG_TEXT_LIMIT,
            }
            for message in messages
        ],
    )


def emit_llm_response(
    sink: EventSink | None,
    step: str,
    response: Any,
    *,
    duration_ms: int,
) -> None:
    text = response_text(response)
    emit_event(
        sink,
        "llm_response",
        step=step,
        duration_ms=duration_ms,
        response={
            "content": truncate_text(text),
            "content_length": len(text),
            "truncated": len(text) > LOG_TEXT_LIMIT,
            "model": getattr(response, "model", None),
            "provider": getattr(response, "provider", None),
        },
    )


def emit_llm_failure(
    sink: EventSink | None,
    step: str,
    *,
    started: float,
    error: BaseException,
) -> None:
    emit_event(
        sink,
        "llm_call_failed",
        step=step,
        duration_ms=elapsed_ms(started),
        error_type=type(error).__name__,
        error_message=str(error),
    )


def elapsed_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


def now_counter() -> float:
    return perf_counter()


def utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def truncate_text(value: str, limit: int = LOG_TEXT_LIMIT) -> str:
    if len(value) <= limit:
        return value
    return value[:limit]


def response_text(response: Any) -> str:
    raw_content = (
        response.content if isinstance(response, LLMResponse) else getattr(response, "content", response)
    )
    return raw_content if isinstance(raw_content, str) else str(raw_content)


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "to_dict"):
        return json_safe(value.to_dict())
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump(mode="json"))
    if hasattr(value, "value"):
        return value.value
    return str(value)


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=json_safe),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _read_log(path: Path, *, paper_id: str) -> dict[str, Any]:
    if not path.exists():
        return {"paper_id": paper_id, "schema_version": 1, "events": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"paper_id": paper_id, "schema_version": 1, "events": []}
    return value if isinstance(value, dict) else {"paper_id": paper_id, "schema_version": 1, "events": []}


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _message_role(message: Any) -> str:
    if isinstance(message, Mapping):
        return str(message.get("role", ""))
    return str(getattr(message, "role", ""))


def _message_content(message: Any) -> str:
    if isinstance(message, Mapping):
        return str(message.get("content", ""))
    return str(getattr(message, "content", ""))
