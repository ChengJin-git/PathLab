"""Session-scoped dependency registry.

Tools resolve their workspace/tracker/config from this registry
via session_id, instead of closing over process-global objects.
This makes concurrent sessions safe.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionDeps:
    """Runtime dependencies for a single session."""
    workspace: Any  # Workspace
    tracker: Any    # MetricsTracker
    config: Any     # PathScientistConfig
    iteration_state: Any = None  # IterationState (optional)
    conversation: Any = None     # LocalConversation — set after create_conversation()
    last_experiment: dict = None  # Latest run_experiment output for evidence collection
    # Structured skip log for runs whose evidence could not be persisted —
    # entries are ``{"run_id": str, "reason": str}`` dicts. IntegrityGuard
    # reads this to enrich ``evidence_run_missing`` issues with the concrete
    # reason (``no_last_experiment`` / ``no_workspace`` /
    # ``exception:<Type>:<msg>``) instead of an opaque missing-record error.
    evidence_skipped_runs: list[dict] = field(default_factory=list)


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
