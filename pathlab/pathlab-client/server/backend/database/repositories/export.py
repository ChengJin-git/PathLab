"""
ExportTaskRepository - Data Access Layer
"""

import logging
from typing import Any, Dict, Optional
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from ..models import ExportTask, utc_now
from .base import BaseRepository


class ExportTaskRepository(BaseRepository[ExportTask]):
    """Repository for Export Task operations"""

    model = ExportTask
    pk_field = "task_id"

    @staticmethod
    async def create(  # pyright: ignore[reportIncompatibleMethodOverride]
        db: AsyncSession,
        task_id: str,
        user_id: str,
        export_type: str,
        file_format: str,
        filter_params: Optional[Dict[str, Any]] = None,
    ) -> ExportTask:
        """Create a new export task"""
        task = ExportTask(
            task_id=task_id,
            user_id=user_id,
            export_type=export_type,
            file_format=file_format,
            filter_params=filter_params,
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
        error_message: Optional[str] = None,
        file_path: Optional[str] = None,
        total_records: Optional[int] = None,
    ) -> bool:
        """Update export task status"""
        update_data: Dict[str, Any] = {"status": status}

        if progress is not None:
            update_data["progress"] = progress
        if error_message is not None:
            update_data["error_message"] = error_message
        if file_path is not None:
            update_data["file_path"] = file_path
        if total_records is not None:
            update_data["total_records"] = total_records

        if status == "processing" and "started_at" not in update_data:
            update_data["started_at"] = utc_now()
        if status in ("completed", "failed", "cancelled"):
            update_data["completed_at"] = utc_now()

        result = await db.execute(
            update(ExportTask)
            .where(ExportTask.task_id == task_id)
            .values(**update_data)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def cleanup_old_tasks(db: AsyncSession, days: int = 7) -> int:
        """Delete failed export tasks older than specified days (keep completed tasks permanently)"""
        from datetime import timedelta

        cutoff = utc_now() - timedelta(days=days)

        result = await db.execute(
            delete(ExportTask).where(
                ExportTask.status.in_(["failed"]), ExportTask.completed_at < cutoff
            )
        )
        return result.rowcount
