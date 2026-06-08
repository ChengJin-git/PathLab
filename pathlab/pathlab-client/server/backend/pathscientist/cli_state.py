"""Interactive CLI runtime state."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InteractiveCLIState:
    """Mutable state for the interactive CLI session."""
    mode: str = "research"
    details: bool = False
    agent: Any = None
    workspace: Any = None
    tracker: Any = None
    conversation: Any = None
    session: Any = None
    research_state: Any = None
    session_started_monotonic: float = 0.0
    last_turn_seconds: float = 0.0

    @property
    def ready(self) -> bool:
        return self.conversation is not None

    def reset_session(self) -> None:
        """Close and clean up the active session, then clear state."""
        # Close conversation if present
        if self.conversation is not None:
            try:
                self.conversation.close()
            except Exception:
                pass

        # Remove from session registry
        if self.session is not None:
            try:
                from .runtime.session_registry import remove_session
                remove_session(self.session.session_id)
            except Exception:
                pass

        self.agent = None
        self.workspace = None
        self.tracker = None
        self.conversation = None
        self.session = None
        self.research_state = None
        self.session_started_monotonic = 0.0
        self.last_turn_seconds = 0.0
