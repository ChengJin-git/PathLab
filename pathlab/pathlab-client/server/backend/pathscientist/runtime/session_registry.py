"""Session-scoped dependency registry.

Tools resolve their workspace/tracker/config from this registry
via session_id, instead of closing over process-global objects.
This makes concurrent sessions safe.
"""
from __future__ import annotations

import os
import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
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
    external_test_history: list[dict] = field(default_factory=list)
    # Structured skip log for runs whose evidence could not be persisted —
    # entries are ``{"run_id": str, "reason": str}`` dicts. IntegrityGuard
    # reads this to enrich ``evidence_run_missing`` issues with the concrete
    # reason (``no_last_experiment`` / ``no_workspace`` /
    # ``exception:<Type>:<msg>``) instead of an opaque missing-record error.
    evidence_skipped_runs: list[dict] = field(default_factory=list)


@dataclass
class ActiveProcess:
    """A process group currently owned by a PathScientist session."""

    session_id: str
    run_id: str
    pid: int
    pgid: int
    tool_name: str = ""
    command: str = ""
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "pid": self.pid,
            "pgid": self.pgid,
            "tool_name": self.tool_name,
            "command": self.command,
            "started_at": self.started_at,
        }


_lock = threading.Lock()
_sessions: dict[str, SessionDeps] = {}
_active_processes: dict[str, dict[str, ActiveProcess]] = {}
_cancelled_sessions: set[str] = set()
# Plan-2026-05-17 file-editor-guard: reverse index workspace_dir → session_id
# so the FileEditorTool factory can resolve config from ``conv_state``
# (which only exposes workspace.working_dir, not session_id).
_workspace_index: dict[Path, str] = {}


def register_session(session_id: str, deps: SessionDeps) -> None:
    with _lock:
        _sessions[session_id] = deps
        _cancelled_sessions.discard(session_id)


def get_session(session_id: str) -> SessionDeps:
    with _lock:
        if session_id not in _sessions:
            raise KeyError(f"Session '{session_id}' not found in registry")
        return _sessions[session_id]


def remove_session(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)
        _active_processes.pop(session_id, None)
        _cancelled_sessions.discard(session_id)
        # Drop any workspace entries pointing at this session so a later
        # session reusing the same workspace_dir gets a clean lookup.
        stale = [ws for ws, sid in _workspace_index.items() if sid == session_id]
        for ws in stale:
            _workspace_index.pop(ws, None)


def register_active_process(
    *,
    session_id: str,
    run_id: str,
    pid: int,
    pgid: int,
    tool_name: str = "",
    command: str = "",
) -> None:
    """Register a live process group so UI stop can kill it."""
    if not session_id or not run_id or not pgid:
        return
    process = ActiveProcess(
        session_id=session_id,
        run_id=run_id,
        pid=int(pid),
        pgid=int(pgid),
        tool_name=tool_name,
        command=command,
    )
    with _lock:
        _active_processes.setdefault(session_id, {})[run_id] = process


def unregister_active_process(session_id: str, run_id: str) -> None:
    if not session_id or not run_id:
        return
    with _lock:
        processes = _active_processes.get(session_id)
        if not processes:
            return
        processes.pop(run_id, None)
        if not processes:
            _active_processes.pop(session_id, None)


def active_processes(session_id: str) -> list[dict[str, Any]]:
    with _lock:
        return [
            process.to_dict()
            for process in _active_processes.get(session_id, {}).values()
        ]


def mark_session_cancelled(session_id: str) -> None:
    if not session_id:
        return
    with _lock:
        _cancelled_sessions.add(session_id)


def is_session_cancelled(session_id: str) -> bool:
    with _lock:
        return session_id in _cancelled_sessions


def _kill_process_group(pgid: int, sig: int) -> bool:
    try:
        os.killpg(pgid, sig)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return False


def cancel_session_processes(
    session_id: str,
    *,
    term_timeout: float = 3.0,
    kill_timeout: float = 0.5,
) -> dict[str, Any]:
    """Terminate all active process groups for a session.

    Sends SIGTERM first, waits briefly, then sends SIGKILL as a hard-stop
    fallback. The sandbox unregisters processes again when it reaps them; this
    function also removes registry entries so repeated stop clicks are safe.
    """
    mark_session_cancelled(session_id)
    with _lock:
        processes = list(_active_processes.get(session_id, {}).values())

    sigterm_sent: list[int] = []
    sigkill_sent: list[int] = []
    for process in processes:
        if _kill_process_group(process.pgid, signal.SIGTERM):
            sigterm_sent.append(process.pgid)

    if processes and term_timeout > 0:
        time.sleep(term_timeout)

    for process in processes:
        if _kill_process_group(process.pgid, signal.SIGKILL):
            sigkill_sent.append(process.pgid)

    if processes and kill_timeout > 0:
        time.sleep(kill_timeout)

    with _lock:
        current = _active_processes.get(session_id, {})
        for process in processes:
            current.pop(process.run_id, None)
        if not current:
            _active_processes.pop(session_id, None)

    pgids = sorted({process.pgid for process in processes})
    return {
        "active_process_count": len(processes),
        "terminated_process_groups": pgids,
        "sigterm_sent": sigterm_sent,
        "sigkill_sent": sigkill_sent,
        "processes": [process.to_dict() for process in processes],
    }


def register_workspace(workspace_dir: str | Path, session_id: str) -> None:
    """Bind a workspace_dir to a session_id so tool factories with only
    ``conv_state.workspace.working_dir`` can find the SessionDeps."""
    with _lock:
        try:
            key = Path(workspace_dir).resolve()
        except Exception:
            key = Path(str(workspace_dir))
        _workspace_index[key] = session_id


def lookup_session_by_workspace(workspace_dir: str | Path) -> SessionDeps | None:
    """Return the SessionDeps registered for this workspace, or None.

    Returns None (instead of raising) so callers in tool-factory paths
    can fall through to a permissive default when the lookup misses
    (test harnesses, unrelated tools, etc.).
    """
    try:
        key = Path(workspace_dir).resolve()
    except Exception:
        key = Path(str(workspace_dir))
    with _lock:
        sid = _workspace_index.get(key)
        if sid is None:
            return None
        return _sessions.get(sid)
