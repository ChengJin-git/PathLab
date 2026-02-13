"""
Analysis Task State Management (in-memory)

Provides AnalysisTaskState for tracking analysis task lifecycle,
and AnalysisRequest Pydantic model for API request bodies.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from backend.ai.schemas.base import TaskStatus

logger = logging.getLogger(__name__)


class AnalysisTaskState:
    """In-memory state for tracking analysis tasks."""

    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}  # Track running asyncio.Task for cancellation
        self._lock = asyncio.Lock()

    async def create(
        self,
        analysis_id: str,
        task_id: str,
        user_id: str,
        title: str = "",
        analysis_type: str = "internal"  # "internal" or "external"
    ) -> Dict[str, Any]:
        """Create a new analysis task entry."""
        async with self._lock:
            state = {
                "analysis_id": analysis_id,
                "task_id": task_id,
                "user_id": user_id,
                "title": title or f"Analyzing task {task_id}",
                "analysis_type": analysis_type,
                "status": TaskStatus.PENDING,  # pending, queued, running, completed, failed
                "progress": 0,
                "error_message": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "started_at": None,
                "finished_at": None,
            }
            self._tasks[analysis_id] = state
            logger.info(f"AnalysisTaskState.create: Created task analysis_id={analysis_id}, task_id={task_id}, title={title}, user_id={user_id}, total_tasks={len(self._tasks)}")
            return state.copy()

    async def get(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Get analysis task state."""
        async with self._lock:
            state = self._tasks.get(analysis_id)
            return state.copy() if state else None

    async def update(self, analysis_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Update analysis task state."""
        async with self._lock:
            if analysis_id not in self._tasks:
                return None
            self._tasks[analysis_id].update(kwargs)
            return self._tasks[analysis_id].copy()

    async def set_queued(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Mark task as queued (waiting in GPU queue)."""
        return await self.update(
            analysis_id,
            status=TaskStatus.QUEUED,
            progress=0
        )

    async def set_running(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Mark task as running."""
        return await self.update(
            analysis_id,
            status=TaskStatus.RUNNING,
            progress=10,
            started_at=datetime.now(timezone.utc).isoformat()
        )

    async def set_completed(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Mark task as completed."""
        return await self.update(
            analysis_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            finished_at=datetime.now(timezone.utc).isoformat()
        )

    async def set_failed(self, analysis_id: str, error: str) -> Optional[Dict[str, Any]]:
        """Mark task as failed."""
        return await self.update(
            analysis_id,
            status=TaskStatus.FAILED,
            error_message=error,
            finished_at=datetime.now(timezone.utc).isoformat()
        )

    async def set_cancelled(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Mark task as cancelled."""
        return await self.update(
            analysis_id,
            status=TaskStatus.CANCELLED,
            finished_at=datetime.now(timezone.utc).isoformat()
        )

    def register_task(self, analysis_id: str, task: asyncio.Task) -> None:
        """Register an asyncio.Task for potential cancellation."""
        self._running_tasks[analysis_id] = task

    def unregister_task(self, analysis_id: str) -> None:
        """Unregister an asyncio.Task after completion."""
        self._running_tasks.pop(analysis_id, None)

    async def cancel_running_task(self, analysis_id: str) -> bool:
        """Cancel a running asyncio.Task if it exists.

        Returns:
            True if task was found and cancel was called, False otherwise.
        """
        task = self._running_tasks.get(analysis_id)
        if task and not task.done():
            task.cancel()
            logger.info(f"Cancelled running analysis task: {analysis_id}")
            return True
        return False

    async def get_by_task_id(self, task_id: str) -> List[Dict[str, Any]]:
        """Get all analysis tasks for a training task."""
        async with self._lock:
            return [
                state.copy() for state in self._tasks.values()
                if state["task_id"] == task_id
            ]



    async def get_all(self, user_id: Optional[str] = None, max_age_minutes: int = 10) -> List[Dict[str, Any]]:
        """Get all analysis tasks, optionally filtered by user.

        Args:
            user_id: If provided, filter to this user's tasks. If None (admin), return all.
            max_age_minutes: Only return completed/failed tasks within this age.

        Returns:
            List of analysis task states.
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(minutes=max_age_minutes)
            results = []
            # Debug: log total tasks in memory
            if self._tasks:
                logger.debug(f"AnalysisTaskState.get_all: {len(self._tasks)} tasks in memory, user_id_filter={user_id}")
            for state in self._tasks.values():
                # Filter by user if specified
                if user_id and state.get("user_id") != user_id:
                    logger.debug(f"AnalysisTaskState.get_all: skipping task {state.get('analysis_id')} - user mismatch ({state.get('user_id')} != {user_id})")
                    continue
                # For completed/failed tasks, only include recent ones
                if state["status"] in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    finished = state.get("finished_at")
                    if finished:
                        try:
                            finished_dt = datetime.fromisoformat(finished.replace('Z', '+00:00'))
                            if finished_dt < cutoff:
                                logger.debug(f"AnalysisTaskState.get_all: skipping old completed task {state.get('analysis_id')}")
                                continue
                        except Exception:
                            pass
                results.append(state.copy())
            if results:
                logger.debug(f"AnalysisTaskState.get_all: returning {len(results)} tasks: {[(r.get('analysis_id'), r.get('status')) for r in results]}")
            return results

    async def cleanup_old(self, max_age_hours: int = 24):
        """Remove old completed/failed tasks from memory."""
        async with self._lock:
            cutoff = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
            to_remove = []
            for aid, state in self._tasks.items():
                if state["status"] in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    finished = state.get("finished_at")
                    if finished:
                        try:
                            finished_ts = datetime.fromisoformat(finished.replace('Z', '+00:00')).timestamp()
                            if finished_ts < cutoff:
                                to_remove.append(aid)
                        except Exception:
                            pass
            for aid in to_remove:
                del self._tasks[aid]


# Global analysis task state manager
_analysis_state = AnalysisTaskState()


def get_analysis_state() -> AnalysisTaskState:
    """Get the global analysis state manager."""
    return _analysis_state


class AnalysisRequest(BaseModel):
    """Request body for running analysis on a task."""
    metrics: List[str] = ["accuracy", "precision", "recall", "specificity", "f1", "auc"]
    charts: List[str] = ["roc_curve", "confusion_matrix", "loss_curve"]
    description: Optional[str] = None
    bootstrap_ci_metrics: List[str] = []  # List of metrics to compute 95% CI for (e.g., ["accuracy", "auc"])
    # Legacy support: compute_bootstrap_ci=True will compute CI for all requested metrics
    compute_bootstrap_ci: bool = False