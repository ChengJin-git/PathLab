"""Tests for AutoResearch conversation resume and inspection.

These tests verify that a resumed conversation rebuilds SessionDeps correctly
and that the inspection helpers work on persisted conversation directories.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from persistence_helpers import (
    append_test_message_event,
    build_test_conversation,
    resume_test_conversation,
)


def test_can_resume_existing_conversation_by_id(tmp_path):
    first, session = build_test_conversation(tmp_path)
    append_test_message_event(first, "first turn")
    resumed, _ = resume_test_conversation(tmp_path, session.conversation_id)
    assert resumed.id == session.conversation_id
    assert len(resumed.state.events) >= 1


def test_resume_rebuilds_session_deps(tmp_path):
    """After resume, tools must be able to resolve their SessionDeps."""
    first, session = build_test_conversation(tmp_path)
    from autoresearch.persistence.state_bridge import update_agent_state

    update_agent_state(first, workspace_dir=str(tmp_path / "workspace"))
    first.close()

    resumed_conv, resumed_session = resume_test_conversation(
        tmp_path, session.conversation_id
    )
    from autoresearch.runtime.session_registry import get_session

    deps = get_session(resumed_session.session_id)
    assert deps.workspace is not None
    assert deps.tracker is not None
    assert deps.iteration_state is not None


def test_resume_restores_iteration_state(tmp_path):
    """IterationState fields survive resume."""
    first, session = build_test_conversation(tmp_path)
    from autoresearch.persistence.state_bridge import update_agent_state

    update_agent_state(
        first,
        iteration_state={
            "iteration_index": 2,
            "remaining_budget": 3,
            "max_iterations": 5,
            "current_file_hash": "abc123",
            "last_validated_hash": "abc123",
            "last_quick_check_hash": "abc123",
            "last_run_id": "run001",
            "history": [
                {"iteration": 0, "metrics": {"auc": 0.8}, "committed": True},
            ],
        },
    )
    first.close()

    _, resumed_session = resume_test_conversation(tmp_path, session.conversation_id)
    from autoresearch.runtime.session_registry import get_session

    deps = get_session(resumed_session.session_id)
    assert deps.iteration_state.iteration_index == 2
    assert deps.iteration_state.remaining_budget == 3
    assert deps.iteration_state.last_quick_check_hash == "abc123"


def test_history_reader_returns_summary_from_disk(tmp_path):
    first, session = build_test_conversation(tmp_path)
    append_test_message_event(first, "hello")
    from autoresearch.persistence.history import load_conversation_summary

    conv_dir = session.persistence_root / session.conversation_id.hex
    summary = load_conversation_summary(conv_dir)
    assert summary["conversation_id"] == str(session.conversation_id)
    assert summary["event_count"] >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
