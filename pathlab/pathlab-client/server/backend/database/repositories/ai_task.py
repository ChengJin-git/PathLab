"""
AITaskRepository - Data Access Layer
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy import select, update, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from ..models import AITask, utc_now
from backend.ai.schemas.base import TaskStatus


class AITaskRepository:
    """Repository for AI Task operations"""

    @staticmethod
    async def create(db: AsyncSession, task_data: Dict) -> AITask:
        """Create a new AI task"""
        task = AITask(**task_data)
        db.add(task)
        await db.flush()
        await db.refresh(task)
        return task

    @staticmethod
    async def get_by_id(db: AsyncSession, task_id: str) -> Optional[AITask]:
        """Get task by task_id"""
        result = await db.execute(
            select(AITask).where(AITask.task_id == task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_wsi_id(db: AsyncSession, wsi_id: str) -> List[AITask]:
        """Get all tasks for a WSI"""
        result = await db.execute(
            select(AITask)
            .where(AITask.wsi_id == wsi_id)
            .order_by(desc(AITask.created_at))
        )
        return result.scalars().all()

    @staticmethod
    async def get_latest_by_wsi_id(db: AsyncSession, wsi_id: str) -> Optional[AITask]:
        """Get latest task for a WSI"""
        result = await db.execute(
            select(AITask)
            .where(AITask.wsi_id == wsi_id)
            .order_by(desc(AITask.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_status(
        db: AsyncSession,
        task_id: str,
        status: str,
        progress: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> Optional[AITask]:
        """Update task status"""
        update_data = {"status": status}

        if progress is not None:
            update_data["progress"] = progress

        if error_message is not None:
            update_data["error_message"] = error_message

        if status == TaskStatus.PATCHING and not await AITaskRepository._has_started(db, task_id):
            update_data["started_at"] = utc_now()

        if status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            update_data["finished_at"] = utc_now()
            if status == TaskStatus.COMPLETED:
                update_data["progress"] = 100

        await db.execute(
            update(AITask)
            .where(AITask.task_id == task_id)
            .values(**update_data)
        )
        await db.flush()
        return await AITaskRepository.get_by_id(db, task_id)

    @staticmethod
    async def _has_started(db: AsyncSession, task_id: str) -> bool:
        """Check if task has started_at timestamp"""
        result = await db.execute(
            select(AITask.started_at).where(AITask.task_id == task_id)
        )
        started_at = result.scalar_one_or_none()
        return started_at is not None

    @staticmethod
    async def count(db: AsyncSession, user_id: Optional[str] = None) -> int:
        """Count total tasks.

        Args:
            db: Database session
            user_id: Optional user ID filter. If provided, only counts tasks belonging to this user.
                     If None, counts all tasks (for admin users).
        """
        query = select(func.count(AITask.id))
        if user_id is not None:
            query = query.where(AITask.user_id == user_id)
        result = await db.execute(query)
        return result.scalar_one()

    @staticmethod
    async def count_completed(db: AsyncSession, user_id: Optional[str] = None) -> int:
        """Count completed tasks.

        Args:
            db: Database session
            user_id: Optional user ID filter. If provided, only counts completed tasks belonging to this user.
                     If None, counts all completed tasks (for admin users).
        """
        query = select(func.count(AITask.id)).where(AITask.status == TaskStatus.COMPLETED)
        if user_id is not None:
            query = query.where(AITask.user_id == user_id)
        result = await db.execute(query)
        return result.scalar_one()

    @staticmethod
    async def get_recent(db: AsyncSession, limit: int = 10, user_id: Optional[str] = None) -> List[AITask]:
        """Get recent AI tasks (inference tasks).

        Args:
            db: Database session
            limit: Maximum number of records to return
            user_id: Optional user ID filter. If provided, only returns tasks belonging to this user.

        Returns:
            List of recent AI tasks ordered by created_at desc
        """
        query = select(AITask)
        if user_id is not None:
            query = query.where(AITask.user_id == user_id)
        query = query.order_by(desc(AITask.created_at)).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def get_status_counts(db: AsyncSession, user_id: Optional[str] = None) -> Dict[str, int]:
        """Get counts of AI tasks by status.

        Args:
            db: Database session
            user_id: Optional user ID filter. If provided, only counts tasks belonging to this user.

        Returns:
            Dict with keys: total, completed, running, pending, failed
        """
        from sqlalchemy import case

        query = select(
            func.count(AITask.id).label("total"),
            func.sum(case((AITask.status == TaskStatus.COMPLETED, 1), else_=0)).label("completed"),
            func.sum(case((AITask.status == TaskStatus.PATCHING, 1), else_=0)).label("running"),
            func.sum(case((AITask.status == TaskStatus.PENDING, 1), else_=0)).label("pending"),
            func.sum(case((AITask.status == TaskStatus.FAILED, 1), else_=0)).label("failed"),
        )
        if user_id is not None:
            query = query.where(AITask.user_id == user_id)
        result = await db.execute(query)
        row = result.one()
        return {
            "total": row.total or 0,
            "completed": row.completed or 0,
            "running": row.running or 0,
            "pending": row.pending or 0,
            "failed": row.failed or 0,
        }


