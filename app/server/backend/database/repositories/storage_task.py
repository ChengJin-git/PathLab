"""
StorageTaskRepository - Data Access Layer
"""

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from ..models import StorageTask, utc_now
from .base import BaseRepository


class StorageTaskRepository(BaseRepository[StorageTask]):
    """Repository for Storage Task operations (batch import, delete external files)"""

    model = StorageTask
    pk_field = "task_id"

    @staticmethod
    async def create(  # pyright: ignore[reportIncompatibleMethodOverride]
        db: AsyncSession,
        task_id: str,
        user_id: str,
        task_type: str,
        total_items: int = 0,
        params: Optional[Dict[str, Any]] = None,
    ) -> StorageTask:
        """Create a new storage task"""
        task = StorageTask(
            task_id=task_id,
            user_id=user_id,
            task_type=task_type,
            total_items=total_items,
            params=params,
            status="pending",
        )
        db.add(task)
        await db.flush()
        await db.refresh(task)
        return task

    @staticmethod
    async def update_status(
        db: AsyncSession,
        task_id: str,
        status: str,
        progress: Optional[int] = None,
        processed_items: Optional[int] = None,
        total_items: Optional[int] = None,
        success_count: Optional[int] = None,
        failed_count: Optional[int] = None,
        skipped_count: Optional[int] = None,
        error_message: Optional[str] = None,
        results: Optional[list[Any]] = None,
    ) -> bool:
        """Update storage task status"""
        update_data: Dict[str, Any] = {"status": status}

        if progress is not None:
            update_data["progress"] = progress
        if processed_items is not None:
            update_data["processed_items"] = processed_items
        if total_items is not None:
            update_data['total_items'] = total_items
        if success_count is not None:
            update_data["success_count"] = success_count
        if failed_count is not None:
            update_data["failed_count"] = failed_count
        if skipped_count is not None:
            update_data["skipped_count"] = skipped_count
        if error_message is not None or status == "completed":
            update_data["error_message"] = error_message
        if results is not None:
            update_data["results"] = results

        if status == "processing" and "started_at" not in update_data:
            update_data["started_at"] = utc_now()
        if status in ("completed", "failed", "cancelled"):
            update_data["completed_at"] = utc_now()

        result = await db.execute(
            update(StorageTask)
            .where(StorageTask.task_id == task_id)
            .values(**update_data)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def get_user_tasks(
        db: AsyncSession, user_id: Optional[str] = None, limit: int = 50
    ) -> List[StorageTask]:
        """Get user-visible tasks; internal housekeeping never consumes page slots."""
        query = (
            select(StorageTask)
            .where(~StorageTask.task_type.in_(["chat_delete", "file_cleanup", "storage_scan", "storage_cleanup"]))
            .order_by(StorageTask.created_at.desc())
            .limit(limit)
        )
        if user_id:
            query = query.where(StorageTask.user_id == user_id)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_active_tasks(
        db: AsyncSession, user_id: Optional[str] = None
    ) -> List[StorageTask]:
        """Get active (non-completed) storage tasks. If user_id is None, get all (admin)."""
        query = (
            select(StorageTask)
            .where(StorageTask.status.in_(["pending", "processing"]))
            .where(~StorageTask.task_type.in_(['chat_delete','file_cleanup','storage_scan','storage_cleanup']))
            .order_by(StorageTask.created_at.desc())
        )
        if user_id:
            query = query.where(StorageTask.user_id == user_id)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def cleanup_old_tasks(db: AsyncSession, days: int = 7) -> int:
        """Expire user-facing failures; retain durable cleanup and completed tasks."""
        from datetime import timedelta

        cutoff = utc_now() - timedelta(days=days)

        result = await db.execute(
            delete(StorageTask).where(
                ~StorageTask.task_type.in_(['chat_delete','file_cleanup','storage_scan','storage_cleanup']),
                StorageTask.status.in_(["failed", "cancelled"]),
                StorageTask.completed_at < cutoff,
            )
        )
        return result.rowcount
