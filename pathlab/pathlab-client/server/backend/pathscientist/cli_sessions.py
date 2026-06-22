"""CLI session lifecycle helpers — new, list, resume."""
from __future__ import annotations

from uuid import UUID

from .persistence.resume import resume_conversation
from .runtime.session_registry import get_session


def start_resumed_session(state, config, conversation_id: str) -> None:
    """Resume a saved conversation and hydrate CLI state."""
    conversation, session = resume_conversation(config, UUID(conversation_id))
    deps = get_session(session.session_id)
    state.conversation = conversation
    state.session = session
    state.workspace = deps.workspace
    state.tracker = deps.tracker

    # Also load orchestrator research state if present
    try:
        from .orchestrator.state_bridge import load_research_session_state
        research_state = load_research_session_state(conversation)
        if research_state:
            state.research_state = research_state
            state.mode = "research"
    except Exception:
        pass
