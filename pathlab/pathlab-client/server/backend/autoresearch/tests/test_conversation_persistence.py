"""Contract tests for AutoResearch conversation persistence.

These tests define the persistence API surface. They are expected to fail
until Tasks 2–5 are implemented.
"""
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from persistence_helpers import (
    append_test_message_event,
    build_test_conversation,
    make_test_config,
    resume_test_conversation,
)


# --- Task 2: Session identity ---


def test_session_contains_conversation_identity_and_paths(tmp_path):
    cfg = make_test_config(tmp_path)
    session = cfg.create_session("improve auc")
    # conversation_id must be a real UUID
    UUID(str(session.conversation_id))
    # persistence_root must exist as a directory
    assert session.persistence_root.exists()
    assert session.persistence_root.is_dir()


# --- Task 3: OpenHands file layout ---


def test_create_conversation_writes_openhands_layout(tmp_path):
    conversation, session = build_test_conversation(tmp_path)
    append_test_message_event(conversation, "hello")
    # SDK computes: persistence_root / conversation_id.hex
    conv_dir = session.persistence_root / session.conversation_id.hex
    assert (conv_dir / "base_state.json").exists()
    assert (conv_dir / "events").is_dir()
    assert any((conv_dir / "events").glob("event-*.json"))


def test_create_conversation_uses_session_persistence_dir(tmp_path):
    conversation, session = build_test_conversation(tmp_path)
    # SDK resolves: persistence_root / conversation_id.hex
    expected_dir = str(session.persistence_root / session.conversation_id.hex)
    assert conversation.state.persistence_dir == expected_dir
    assert conversation.id == session.conversation_id


def test_base_state_persists_tags_and_agent_state(tmp_path):
    conversation, session = build_test_conversation(tmp_path)
    conversation.state.agent_state = {"loaded_skill": "mil_classification"}
    conv_dir = session.persistence_root / session.conversation_id.hex
    payload = (conv_dir / "base_state.json").read_text()
    assert "mil_classification" in payload


# --- Task 4: agent_state metadata ---


def test_loaded_skill_is_persisted_in_agent_state(tmp_path):
    conversation, session = build_test_conversation(tmp_path)
    from autoresearch.persistence.state_bridge import update_agent_state

    update_agent_state(conversation, loaded_skill="mil_classification")
    reopened, _ = resume_test_conversation(tmp_path, session.conversation_id)
    assert reopened.state.agent_state["loaded_skill"] == "mil_classification"


def test_tracker_state_is_persisted_in_agent_state(tmp_path):
    conversation, session = build_test_conversation(tmp_path)
    from autoresearch.persistence.state_bridge import update_agent_state

    update_agent_state(
        conversation,
        tracker_state={
            "primary_metric": "auc",
            "best_value": 0.88,
            "iteration": 2,
            "history": [
                {"iteration": 0, "metrics": {"auc": 0.81}, "committed": True},
                {"iteration": 1, "metrics": {"auc": 0.88}, "committed": True},
            ],
        },
    )
    reopened, _ = resume_test_conversation(tmp_path, session.conversation_id)
    assert reopened.state.agent_state["tracker_state"]["best_value"] == 0.88
    assert reopened.state.agent_state["tracker_state"]["history"][1]["iteration"] == 1


def test_iteration_state_persisted_in_agent_state(tmp_path):
    conversation, session = build_test_conversation(tmp_path)
    from autoresearch.persistence.state_bridge import update_agent_state

    update_agent_state(
        conversation,
        iteration_state={
            "iteration_index": 2,
            "remaining_budget": 3,
            "current_file_hash": "abc123",
            "last_validated_hash": "abc123",
            "last_quick_check_hash": "abc123",
            "last_run_id": "run001",
            "history": [
                {"iteration": 0, "metrics": {"auc": 0.8}, "committed": True},
            ],
        },
    )
    reopened, _ = resume_test_conversation(tmp_path, session.conversation_id)
    assert reopened.state.agent_state["iteration_state"]["iteration_index"] == 2
    assert (
        reopened.state.agent_state["iteration_state"]["last_quick_check_hash"]
        == "abc123"
    )


# --- Task 5: Resume ---


def test_reopen_same_conversation_recovers_existing_events(tmp_path):
    first, session = build_test_conversation(tmp_path)
    append_test_message_event(first, "first turn")
    reopened, _ = resume_test_conversation(tmp_path, session.conversation_id)
    assert len(reopened.state.events) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
