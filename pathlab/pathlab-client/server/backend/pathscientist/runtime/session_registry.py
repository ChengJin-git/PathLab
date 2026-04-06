"""Session-scoped dependency registry.

Tools resolve their workspace/tracker/config from this registry
via session_id, instead of closing over process-global objects.
This makes concurrent sessions safe.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


@dataclass
class SessionDeps:
    """Runtime dependencies for a single session."""
    workspace: Any  # Workspace
    tracker: Any    # MetricsTracker
    config: Any     # PathScientistConfig
    iteration_state: Any = None  # IterationState (optional)
    conversation: Any = None     # LocalConversation — set after create_conversation()


_lock = threading.Lock()
_sessions: dict[str, SessionDeps] = {}


def register_session(session_id: str, deps: SessionDeps) -> None:
    with _lock:
        _sessions[session_id] = deps


def get_session(session_id: str) -> SessionDeps:
    with _lock:
        if session_id not in _sessions:
            raise KeyError(f"Session '{session_id}' not found in registry")
        return _sessions[session_id]


def remove_session(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)
