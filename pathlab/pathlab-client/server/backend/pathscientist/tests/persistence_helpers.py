"""Shared fixtures for conversation persistence tests.

These tests verify persistence layout and resume contracts without depending on
real LLM calls. Avoid ``conversation.send_message()`` in these tests; append a
synthetic event directly when you only need to verify OpenHands file layout.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from openhands.sdk.event import MessageEvent
from openhands.sdk.llm import Message, TextContent

from pathscientist.config import PathScientistConfig


def make_test_config(tmp_path: Path, **overrides) -> PathScientistConfig:
    """Minimal config suitable for test: no GPU, no sandbox, tmp workspace."""
    return PathScientistConfig(
        workspace_dir=str(tmp_path / "workspace"),
        output_dir=str(tmp_path / "output"),
        gpu_ids=[],
        sandbox_mode="local",
        max_iterations=2,
        primary_metric="auc",
        conversation_persistence_dir=str(tmp_path),
        **overrides,
    )


def build_test_conversation(tmp_path: Path, **config_overrides):
    """Create a PathScientist conversation with persistence enabled.

    Returns (conversation, session) tuple.
    """
    from pathscientist.agent import create_agent, create_conversation

    config = make_test_config(tmp_path, **config_overrides)
    agent, workspace, tracker, session = create_agent(config, research_question="test")
    conversation = create_conversation(agent, workspace, session)
    return conversation, session


def resume_test_conversation(tmp_path: Path, conversation_id: UUID):
    """Re-open an existing conversation by UUID (resume path).

    Returns (conversation, session) so tests can validate both the OpenHands
    state and the rebuilt PathScientist runtime state.
    """
    from pathscientist.persistence.resume import resume_conversation

    config = make_test_config(tmp_path)
    return resume_conversation(config, conversation_id)


def append_test_message_event(conversation, text: str = "hello") -> None:
    """Append a synthetic user message event for persistence-layout tests.

    This exercises the event store without requiring a real agent run.
    """
    conversation.state.events.append(
        MessageEvent(
            source="user",
            llm_message=Message(
                role="user",
                content=[TextContent(text=text)],
            ),
        )
    )
