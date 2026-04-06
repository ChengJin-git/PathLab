"""Conversation inspection helpers — read persisted state without starting an agent."""
from __future__ import annotations

import json
from pathlib import Path


def load_conversation_summary(conversation_dir: Path) -> dict:
    """Read base_state.json and count events for a quick summary.

    Does NOT instantiate an Agent or LocalConversation — pure file reads.
    """
    base_state_path = conversation_dir / "base_state.json"
    if not base_state_path.exists():
        raise FileNotFoundError(f"No base_state.json in {conversation_dir}")

    data = json.loads(base_state_path.read_text(encoding="utf-8"))

    # Count event files
    events_dir = conversation_dir / "events"
    event_count = 0
    if events_dir.is_dir():
        event_count = sum(
            1 for f in events_dir.iterdir()
            if f.name.startswith("event-") and f.suffix == ".json"
        )

    agent_state = data.get("agent_state", {})

    return {
        "conversation_id": str(data.get("id", "")),
        "execution_status": data.get("execution_status", "unknown"),
        "event_count": event_count,
        "tags": data.get("tags", {}),
        "workspace_dir": agent_state.get("workspace_dir", ""),
        "loaded_skill": agent_state.get("loaded_skill", ""),
        "best_metric": agent_state.get("best_metric", {}),
        "tracker_state": agent_state.get("tracker_state", {}),
        "iteration_state": agent_state.get("iteration_state", {}),
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
