"""Import Gateway PathScientist file-backed sessions into auto_research_* tables."""
# pyright: reportImplicitRelativeImport=false, reportUnusedCallResult=false, reportAny=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportPrivateUsage=false, reportExplicitAny=false, reportUnknownArgumentType=false, reportUnnecessaryIsInstance=false, reportOptionalSubscript=false, reportGeneralTypeIssues=false
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.auth.models import User  # noqa: E402
from backend.database.database import safe_session  # noqa: E402
from gateway import pathscientist_persistence  # noqa: E402


GATEWAY_SESSION_REGISTRY = "gateway_sessions.json"
GATEWAY_EVENT_DIR = "gateway_events"


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import PathScientist gateway_sessions.json/jsonl events into PostgreSQL."
    )
    parser.add_argument(
        "--base-dir",
        default="",
        help="PathScientist base dir. Defaults to resolved PATHSCIENTIST_BASE_DIR.",
    )
    parser.add_argument(
        "--default-user-id",
        default="",
        help="User id for historical sessions without an owner. Defaults to admin user.",
    )
    args = parser.parse_args()

    base_dir = (
        Path(args.base_dir).expanduser().resolve()
        if args.base_dir
        else _resolve_pathscientist_base_dir()
    )
    default_user_id = args.default_user_id or await _admin_user_id()
    if not default_user_id:
        print("No --default-user-id provided and no admin user found; nothing imported.")
        return 1

    registry_path = base_dir / GATEWAY_SESSION_REGISTRY
    if not registry_path.exists():
        print(f"No gateway session registry found at {registry_path}")
        return 0

    sessions = _load_registry(registry_path)
    imported = 0
    skipped = 0
    for session in sessions:
        session_id = str(session.get("session_id") or "").strip()
        if not session_id:
            skipped += 1
            continue
        event_path = (
            base_dir
            / GATEWAY_EVENT_DIR
            / _safe_session_filename(session_id)
        )
        events = _load_events(event_path)
        conversation_id = str(session.get("conversation_id") or "").strip()
        conversation_dir = _conversation_dir(base_dir, conversation_id)
        if conversation_dir is not None:
            session.setdefault("persistence_dir", str(conversation_dir))
            session.setdefault("resume_available", (conversation_dir / "base_state.json").is_file())
            _merge_conversation_summary(session, conversation_dir)
        if not events and conversation_dir is not None:
            state = session.get("state") if isinstance(session.get("state"), dict) else {}
            summary = state.get("persisted_summary") if isinstance(state.get("persisted_summary"), dict) else {}
            events = _load_openhands_events(conversation_dir, summary)
        try:
            await pathscientist_persistence.import_session_bundle(
                session=session,
                events=events,
                default_user_id=default_user_id,
            )
            imported += 1
        except Exception as exc:
            skipped += 1
            print(f"Skipped {session_id}: {exc}")

    print(
        f"Imported {imported} PathScientist session(s), skipped {skipped}, base_dir={base_dir}"
    )
    return 0


def _resolve_pathscientist_base_dir() -> Path:
    try:
        from backend.pathscientist.runtime.session import _resolve_base_dir

        return Path(_resolve_base_dir()).expanduser().resolve()
    except Exception:
        default_base_dir = ROOT / "uploads" / "pathscientist"
        return Path(
            os.environ.get("PATHSCIENTIST_BASE_DIR", str(default_base_dir))
        ).expanduser().resolve()


def _safe_session_filename(session_id: str) -> str:
    safe = "".join(ch for ch in str(session_id) if ch.isalnum() or ch in {"-", "_"})
    return (safe[:128] or "unknown") + ".jsonl"


async def _admin_user_id() -> str:
    async with safe_session() as db:
        result = await db.execute(
            select(User).where(User.role == "admin").limit(1)
        )
        user = result.scalar_one_or_none()
        if user is None:
            result = await db.execute(
                select(User).where(User.username == "admin").limit(1)
            )
            user = result.scalar_one_or_none()
        return str(user.id) if user is not None else ""


def _load_registry(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items", payload) if isinstance(payload, dict) else payload
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _conversation_dir(base_dir: Path, conversation_id: str) -> Path | None:
    if not conversation_id:
        return None
    try:
        from backend.pathscientist.persistence.layout import get_persistence_root

        root = Path(get_persistence_root(base_dir))
    except Exception:
        root = base_dir / "conversations"
    for candidate in (root / conversation_id, root / conversation_id.replace("-", "")):
        if candidate.is_dir():
            return candidate
    return None


def _merge_conversation_summary(session: dict[str, Any], conversation_dir: Path) -> None:
    try:
        from backend.pathscientist.persistence.history import load_conversation_summary

        summary = load_conversation_summary(conversation_dir)
    except Exception:
        summary = {}
    if not isinstance(summary, dict):
        summary = {}
    state = session.get("state") if isinstance(session.get("state"), dict) else {}
    persisted_summary = state.get("persisted_summary") if isinstance(state.get("persisted_summary"), dict) else {}
    state["persisted_summary"] = {
        **persisted_summary,
        **summary,
        "persistence_dir": str(conversation_dir),
        "resume_available": (conversation_dir / "base_state.json").is_file(),
    }
    if not session.get("question"):
        session["question"] = summary.get("research_question") or ""
    session["state"] = state


def _load_openhands_events(
    conversation_dir: Path,
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    stage_events = _build_persisted_stage_events(
        summary or {"execution_status": "completed"},
        start_seq=1,
    )
    return stage_events + _load_persisted_conversation_events(
        conversation_dir,
        start_seq=len(stage_events) + 1,
    )


def _normalize_gateway_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = dict(event)
    payload.setdefault("kind", "event")
    payload.setdefault("ts", time.time())
    return payload


def _timestamp_to_epoch(value: Any, *, fallback: float | None = None) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value or "").strip()
        if text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        pass
    return float(fallback if fallback is not None else time.time())


def _safe_text(value: Any, *, limit: int = 4000) -> str:
    return " ".join(str(value or "").split())[:limit]


def _safe_dump(value: Any) -> Any:
    try:
        json.dumps(value, default=str)
        return value
    except Exception:
        return str(value)


def _coerce_iteration(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _first_content_text(content: Any) -> str:
    if isinstance(content, str):
        return _safe_text(content)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(_safe_text(item.get("text")))
            elif isinstance(item, str):
                parts.append(_safe_text(item))
        return "\n".join(part for part in parts if part)[:4000]
    return _safe_text(content) if content else ""


def _compact_observation(observation: Any) -> dict[str, Any]:
    if not isinstance(observation, dict):
        return {"text": _safe_text(observation)}
    compact = {
        "kind": observation.get("kind"),
        "is_error": observation.get("is_error"),
        "exit_code": observation.get("exit_code"),
        "metrics": observation.get("metrics"),
        "duration": observation.get("duration"),
        "commit_hash": observation.get("commit_hash"),
        "reverted_to": observation.get("reverted_to"),
        "best_metric": observation.get("best_metric"),
        "best_metric_name": observation.get("best_metric_name"),
        "iteration": observation.get("iteration"),
        "history": observation.get("history"),
        "text": _first_content_text(observation.get("content")),
    }
    return {key: value for key, value in compact.items() if value not in (None, "", [])}


def _project_openhands_event(raw: dict[str, Any], *, iteration: int | None) -> dict[str, Any] | None:
    kind = str(raw.get("kind") or "")
    tool_name = str(raw.get("tool_name") or "").strip()
    base = {
        "source": raw.get("source"),
        "event_class": kind,
        "raw_event_id": raw.get("id"),
    }
    if kind == "ActionEvent" and tool_name:
        payload: dict[str, Any] = {
            **base,
            "kind": "tool_call",
            "tool": tool_name,
            "summary": _safe_text(raw.get("summary") or tool_name),
            "action": _safe_dump(raw.get("action")),
        }
        if iteration is not None:
            payload["iteration"] = iteration
        return payload
    if kind == "ObservationEvent" and tool_name:
        compact = _compact_observation(raw.get("observation"))
        payload = {
            **base,
            "kind": "tool_observation",
            "tool": tool_name,
            "exit_code": compact.get("exit_code"),
            "observation": compact,
        }
        if raw.get("summary"):
            payload["summary"] = _safe_text(raw.get("summary"))
        observed_iteration = _coerce_iteration(compact.get("iteration"))
        if observed_iteration is not None:
            payload["iteration"] = observed_iteration
        elif iteration is not None:
            payload["iteration"] = iteration
        return payload
    if kind == "MessageEvent":
        message = raw.get("llm_message") if isinstance(raw.get("llm_message"), dict) else {}
        return {
            **base,
            "kind": "message",
            "role": str(message.get("role") or raw.get("source") or "agent"),
            "text": _first_content_text(message.get("content")),
        }
    if kind == "SystemPromptEvent":
        return {
            **base,
            "kind": "message",
            "role": "system",
            "text": "PathScientist system prompt initialized",
        }
    if kind:
        return {**base, "kind": "agent_event", "summary": kind}
    return None


def _load_persisted_conversation_events(
    conversation_dir: Path,
    *,
    start_seq: int = 1,
) -> list[dict[str, Any]]:
    events_dir = conversation_dir / "events"
    if not events_dir.is_dir():
        return []
    events: list[dict[str, Any]] = []
    iteration = 0
    for raw_path in sorted(events_dir.glob("event-*.json")):
        try:
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        projected = _project_openhands_event(raw, iteration=iteration)
        if projected is None:
            continue
        events.append(_normalize_gateway_event({
            "seq": start_seq + len(events),
            "ts": _timestamp_to_epoch(raw.get("timestamp")),
            **projected,
        }))
        observation = raw.get("observation")
        if isinstance(observation, dict):
            observed_iteration = _coerce_iteration(observation.get("iteration"))
            if observed_iteration is not None:
                iteration = observed_iteration
            if raw.get("tool_name") in {"ratchet_commit", "ratchet_revert"}:
                iteration += 1
    return events


def _has_persisted_stage_context(summary: dict[str, Any]) -> bool:
    return any(
        summary.get(key)
        for key in (
            "research_question",
            "research_summary",
            "event_count",
            "tracker_state",
            "iteration_state",
        )
    )


def _build_persisted_stage_events(
    summary: dict[str, Any],
    *,
    start_seq: int = 1,
) -> list[dict[str, Any]]:
    if not _has_persisted_stage_context(summary):
        return []
    started_ts = _timestamp_to_epoch(summary.get("started_at"), fallback=time.time())
    updated_ts = _timestamp_to_epoch(summary.get("updated_at"), fallback=started_ts)
    span = max(1.0, updated_ts - started_ts)
    question = _safe_text(summary.get("research_question"), limit=140)
    status = str(summary.get("execution_status") or "completed")
    stage_summaries = [
        ("intake", f"Research request captured: {question}" if question else "Research request captured."),
        ("execution", "Persisted PathScientist execution events imported."),
        ("completed", f"Historical PathScientist run marked {status}."),
    ]
    events: list[dict[str, Any]] = []
    for index, (stage, text) in enumerate(stage_summaries):
        events.append(_normalize_gateway_event({
            "seq": start_seq + len(events),
            "ts": started_ts + (span * index / max(1, len(stage_summaries) - 1)),
            "kind": "stage_summary",
            "stage": stage,
            "source": "migration",
            "summary": text,
        }))
    return events


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
