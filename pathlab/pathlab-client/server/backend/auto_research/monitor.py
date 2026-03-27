"""
Auto Research Agent — Experiment Monitor

Background service that polls training task status via PathLab API.
When all tasks for a session complete/fail, resumes the LangGraph
via Command(resume=...).

This is the bridge between PathLab's hours-long training tasks and
LangGraph's interrupt/resume mechanism.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 30  # seconds between status checks
_TIMEOUT = 15.0


@dataclass
class MonitoredSession:
    """Tracks one auto-research session's active training tasks."""
    session_id: str
    thread_id: str
    task_ids: list[str]              # PathLab training task IDs
    experiment_map: dict[str, str]   # experiment_id → training_task_id
    gateway_url: str = "http://127.0.0.1:6100"
    auth_token: str = ""

    # Accumulated results
    completed: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)

    # Callback to resume graph
    on_complete: Optional[Any] = None  # async callable(session, completed, failed)

    # Callback to emit SSE events
    on_progress: Optional[Any] = None  # async callable(session, event_type, event_data)


class ExperimentMonitor:
    """
    Background service monitoring training tasks for auto-research sessions.

    Usage:
        monitor = ExperimentMonitor()
        await monitor.start()

        # When experiments are submitted:
        monitor.register(session)

        # When done:
        await monitor.stop()
    """

    def __init__(self):
        self._sessions: dict[str, MonitoredSession] = {}
        self._task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def active_sessions(self) -> int:
        return len(self._sessions)

    def register(self, session: MonitoredSession) -> None:
        """Register a session for monitoring."""
        self._sessions[session.session_id] = session
        logger.info(
            f"[monitor] Registered session {session.session_id} "
            f"with {len(session.task_ids)} tasks: {session.task_ids}"
        )

    def unregister(self, session_id: str) -> None:
        """Stop monitoring a session."""
        self._sessions.pop(session_id, None)
        logger.info(f"[monitor] Unregistered session {session_id}")

    async def start(self) -> None:
        """Start the background polling loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[monitor] Started")

    async def stop(self) -> None:
        """Stop the background polling loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[monitor] Stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop — checks all registered sessions periodically."""
        while self._running:
            try:
                # Copy keys to avoid mutation during iteration
                session_ids = list(self._sessions.keys())

                for session_id in session_ids:
                    session = self._sessions.get(session_id)
                    if not session:
                        continue

                    try:
                        await self._check_session(session)
                    except Exception as e:
                        logger.error(f"[monitor] Error checking session {session_id}: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[monitor] Poll loop error: {e}")

            await asyncio.sleep(_POLL_INTERVAL)

    async def _check_session(self, session: MonitoredSession) -> None:
        """Check status of all training tasks in a session."""
        remaining_task_ids = [
            tid for tid in session.task_ids
            if tid not in {r.get("training_task_id") for r in session.completed}
            and tid not in {r.get("training_task_id") for r in session.failed}
        ]

        if not remaining_task_ids:
            # All tasks already resolved
            await self._session_complete(session)
            return

        headers = {"Content-Type": "application/json"}
        if session.auth_token:
            headers["Authorization"] = f"Bearer {session.auth_token}"

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for task_id in remaining_task_ids:
                try:
                    resp = await client.get(
                        f"{session.gateway_url}/tasks/training/{task_id}",
                        headers=headers,
                    )
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    status = data.get("status", "").lower()
                    progress = data.get("progress", 0)

                    # Emit progress event
                    if session.on_progress:
                        exp_id = self._find_experiment_id(session, task_id)
                        await session.on_progress(session, "experiment_progress", {
                            "experiment_id": exp_id,
                            "training_task_id": task_id,
                            "status": status,
                            "progress": progress,
                        })

                    # Check terminal states
                    if status == "completed":
                        exp_id = self._find_experiment_id(session, task_id)
                        session.completed.append({
                            "experiment_id": exp_id,
                            "training_task_id": task_id,
                            "config": session.experiment_map.get(exp_id, {}),
                            "metrics": data.get("metrics", {}),
                        })
                        logger.info(f"[monitor] Task {task_id} completed (session {session.session_id})")

                        if session.on_progress:
                            await session.on_progress(session, "experiment_completed", {
                                "experiment_id": exp_id,
                                "training_task_id": task_id,
                                "metrics": data.get("metrics", {}),
                            })

                    elif status in ("failed", "cancelled", "error"):
                        exp_id = self._find_experiment_id(session, task_id)
                        session.failed.append({
                            "experiment_id": exp_id,
                            "training_task_id": task_id,
                            "error": data.get("error", data.get("error_message", "Unknown error")),
                        })
                        logger.info(f"[monitor] Task {task_id} {status} (session {session.session_id})")

                        if session.on_progress:
                            await session.on_progress(session, "experiment_failed", {
                                "experiment_id": exp_id,
                                "training_task_id": task_id,
                                "error": data.get("error", ""),
                            })

                except httpx.HTTPError as e:
                    logger.warning(f"[monitor] HTTP error checking task {task_id}: {e}")

        # Check if all tasks are now resolved
        new_remaining = [
            tid for tid in session.task_ids
            if tid not in {r.get("training_task_id") for r in session.completed}
            and tid not in {r.get("training_task_id") for r in session.failed}
        ]

        if not new_remaining:
            await self._session_complete(session)

    async def _session_complete(self, session: MonitoredSession) -> None:
        """All tasks for a session are done — trigger graph resume."""
        logger.info(
            f"[monitor] Session {session.session_id} all tasks done: "
            f"{len(session.completed)} completed, {len(session.failed)} failed"
        )

        if session.on_complete:
            try:
                await session.on_complete(session, session.completed, session.failed)
            except Exception as e:
                logger.error(f"[monitor] Error in on_complete callback: {e}")

        # Unregister — session is done
        self.unregister(session.session_id)

    @staticmethod
    def _find_experiment_id(session: MonitoredSession, task_id: str) -> str:
        """Reverse-lookup experiment_id from training_task_id."""
        for exp_id, tid in session.experiment_map.items():
            if tid == task_id:
                return exp_id
        return task_id  # fallback to task_id if not found


# Global singleton
_monitor: Optional[ExperimentMonitor] = None


def get_monitor() -> ExperimentMonitor:
    """Get or create the global ExperimentMonitor singleton."""
    global _monitor
    if _monitor is None:
        _monitor = ExperimentMonitor()
    return _monitor
