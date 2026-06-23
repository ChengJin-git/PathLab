"""
Analysis Task State Management (Redis-backed)

Task metadata stored in Redis hashes (survives restarts).
Running asyncio.Task references stay in-memory (not serializable).
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from backend.ai.schemas.base import TaskStatus
from backend.common.redis_client import get_redis, make_key
from gateway.models import AnalysisRequest

logger = logging.getLogger(__name__)

_HASH_TTL = 86400


class AnalysisTaskState:
    """Redis-backed state for tracking analysis tasks.

    _running_tasks stays in-memory (asyncio.Task objects are not serializable).
    """

    def __init__(self):
        self._running_tasks: Dict[str, asyncio.Task[Any]] = {}

    def _key(self, analysis_id: str) -> str:
        return make_key("analysis", analysis_id)

    async def _hash_to_dict(self, data: dict[str, Any]) -> Dict[str, Any]:
        progress = data.get("progress", "0")
        return {
            "analysis_id": data.get("analysis_id", ""),
            "task_id": data.get("task_id", ""),
            "user_id": data.get("user_id", ""),
            "title": data.get("title", ""),
            "analysis_type": data.get("analysis_type", "internal"),
            "task_category": data.get("task_category") or None,
            "status": TaskStatus(data.get("status", "pending")),
            "progress": int(progress) if progress else 0,
            "error_message": data.get("error_message") or None,
            "created_at": data.get("created_at") or None,
            "started_at": data.get("started_at") or None,
            "finished_at": data.get("finished_at") or None,
        }

    def _dict_to_hash(self, state: Dict[str, Any]) -> Dict[str, str]:
        status = state.get("status", TaskStatus.PENDING)
        status_str = status.value if isinstance(status, TaskStatus) else str(status)
        return {
            "analysis_id": state.get("analysis_id", ""),
            "task_id": state.get("task_id", ""),
            "user_id": state.get("user_id", ""),
            "title": state.get("title", ""),
            "analysis_type": state.get("analysis_type", "internal"),
            "task_category": state.get("task_category") or "",
            "status": status_str,
            "progress": str(state.get("progress", 0)),
            "error_message": state.get("error_message") or "",
            "created_at": state.get("created_at") or "",
            "started_at": state.get("started_at") or "",
            "finished_at": state.get("finished_at") or "",
        }

    async def create(
        self,
        analysis_id: str,
        task_id: str,
        user_id: str,
        title: str = "",
        analysis_type: str = "internal",
        task_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        state = {
            "analysis_id": analysis_id,
            "task_id": task_id,
            "user_id": user_id,
            "title": title or f"Analyzing task {task_id}",
            "analysis_type": analysis_type,
            "task_category": task_category,
            "status": TaskStatus.PENDING,
            "progress": 0,
            "error_message": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "finished_at": None,
        }
        r = get_redis()
        key = self._key(analysis_id)
        await r.hset(key, mapping=self._dict_to_hash(state))
        await r.expire(key, _HASH_TTL)
        logger.info(
            f"AnalysisTaskState.create: analysis_id={analysis_id}, task_id={task_id}, title={title}, user_id={user_id}"
        )
        return state.copy()

    async def get(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        r = get_redis()
        data = await r.hgetall(self._key(analysis_id))
        if not data:
            return None
        return await self._hash_to_dict(data)

    async def update(self, analysis_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        r = get_redis()
        key = self._key(analysis_id)
        if not await r.exists(key):
            return None

        update_map: Dict[str, str] = {}
        for k, v in kwargs.items():
            if k == "status":
                update_map[k] = v.value if isinstance(v, TaskStatus) else str(v)
            elif k == "progress":
                update_map[k] = str(v)
            elif v is None:
                update_map[k] = ""
            else:
                update_map[k] = str(v)
        if update_map:
            await r.hset(key, mapping=update_map)
            await r.expire(key, _HASH_TTL)

        data = await r.hgetall(key)
        return await self._hash_to_dict(data)

    async def set_queued(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        return await self.update(analysis_id, status=TaskStatus.QUEUED, progress=0)

    async def set_running(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        return await self.update(
            analysis_id,
            status=TaskStatus.PATCHING,
            progress=10,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    async def set_completed(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        return await self.update(
            analysis_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

    async def set_failed(
        self, analysis_id: str, error: str
    ) -> Optional[Dict[str, Any]]:
        return await self.update(
            analysis_id,
            status=TaskStatus.FAILED,
            error_message=error,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

    async def set_cancelled(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        return await self.update(
            analysis_id,
            status=TaskStatus.CANCELLED,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

    def register_task(self, analysis_id: str, task: asyncio.Task[Any]) -> None:
        self._running_tasks[analysis_id] = task

    def unregister_task(self, analysis_id: str) -> None:
        self._running_tasks.pop(analysis_id, None)

    async def cancel_running_task(self, analysis_id: str) -> bool:
        task = self._running_tasks.get(analysis_id)
        if task and not task.done():
            task.cancel()
            logger.info(f"Cancelled running analysis task: {analysis_id}")
            return True
        return False

    async def get_by_task_id(self, task_id: str) -> List[Dict[str, Any]]:
        r = get_redis()
        results = []
        async for key in r.scan_iter(match=make_key("analysis", "*")):
            data = await r.hgetall(key)
            if data and data.get("task_id") == task_id:
                results.append(await self._hash_to_dict(data))
        return results

    async def get_all(
        self, user_id: Optional[str] = None, max_age_minutes: int = 10
    ) -> List[Dict[str, Any]]:
        r = get_redis()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=max_age_minutes)
        results = []

        async for key in r.scan_iter(match=make_key("analysis", "*")):
            data = await r.hgetall(key)
            if not data:
                continue
            state = await self._hash_to_dict(data)

            if user_id and state.get("user_id") != user_id:
                continue

            if state["status"] in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            ):
                finished = state.get("finished_at")
                if finished:
                    try:
                        finished_dt = datetime.fromisoformat(
                            finished.replace("Z", "+00:00")
                        )
                        if finished_dt < cutoff:
                            continue
                    except Exception:
                        pass
            results.append(state)
        return results

    async def cleanup_old(self, max_age_hours: int = 24):
        r = get_redis()
        cutoff = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
        async for key in r.scan_iter(match=make_key("analysis", "*")):
            data = await r.hgetall(key)
            if not data:
                continue
            status_str = data.get("status", "")
            if status_str in (
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            ):
                finished = data.get("finished_at", "")
                if finished:
                    try:
                        finished_ts = datetime.fromisoformat(
                            finished.replace("Z", "+00:00")
                        ).timestamp()
                        if finished_ts < cutoff:
                            await r.delete(key)
                    except Exception:
                        pass


_analysis_state = AnalysisTaskState()


def get_analysis_state() -> AnalysisTaskState:
    return _analysis_state
