"""Conversation inspection helpers — read persisted state without starting an agent."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..cli_render import format_duration


def _parse_event_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _event_time_summary(events_dir: Path) -> dict:
    timestamps: list[datetime] = []
    if not events_dir.is_dir():
        return {
            "started_at": "",
            "updated_at": "",
            "duration_seconds": 0.0,
            "duration": "-",
        }
    for event_file in sorted(events_dir.glob("event-*.json")):
        try:
            payload = json.loads(event_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        parsed = _parse_event_timestamp(str(payload.get("timestamp", "")))
        if parsed is not None:
            timestamps.append(parsed)
    if not timestamps:
        return {
            "started_at": "",
            "updated_at": "",
            "duration_seconds": 0.0,
            "duration": "-",
        }
    started = min(timestamps)
    updated = max(timestamps)
    duration = max(0.0, (updated - started).total_seconds())
    return {
        "started_at": started.isoformat(),
        "updated_at": updated.isoformat(),
        "duration_seconds": duration,
        "duration": format_duration(duration),
    }


def load_conversation_summary(conversation_dir: Path) -> dict:
    """Read base_state.json and count events for a quick summary.

    Does NOT instantiate an Agent or LocalConversation — pure file reads.
    """
    base_state_path = conversation_dir / "base_state.json"
    if not base_state_path.exists():
        raise FileNotFoundError(f"No base_state.json in {conversation_dir}")

    data = json.loads(base_state_path.read_text(encoding="utf-8"))

    # Count event files and aggregate their timestamps for CLI duration display.
    events_dir = conversation_dir / "events"
    event_count = 0
    if events_dir.is_dir():
        event_count = sum(
            1 for f in events_dir.iterdir()
            if f.name.startswith("event-") and f.suffix == ".json"
        )
    time_summary = _event_time_summary(events_dir)

    agent_state = data.get("agent_state", {})

    return {
        "conversation_id": str(data.get("id", "")),
        "execution_status": data.get("execution_status", "unknown"),
        "event_count": event_count,
        "tags": data.get("tags", {}),
        "workspace_dir": agent_state.get("workspace_dir", ""),
        "loaded_skill": agent_state.get("loaded_skill", ""),
        "research_question": agent_state.get("research_question", ""),
        "best_metric": agent_state.get("best_metric", {}),
        "tracker_state": agent_state.get("tracker_state", {}),
        "iteration_state": agent_state.get("iteration_state", {}),
        "research_summary": agent_state.get("research_session", {}).get("final_summary", ""),
        **time_summary,
    }


def list_conversations(persistence_root: Path) -> list[dict]:
    """List all persisted conversations under persistence_root.

    Returns a list of summary dicts, sorted by modification time (newest first).
    """
    if not persistence_root.is_dir():
        return []

    conversations = []
    for child in sorted(persistence_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not child.is_dir():
            continue
        base_state = child / "base_state.json"
        if not base_state.exists():
            continue
        try:
            conversations.append(load_conversation_summary(child))
        except Exception:
            continue

    return conversations
