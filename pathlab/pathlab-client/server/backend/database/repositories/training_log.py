"""
TrainingLogRepository - Data Access Layer
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy import select, delete, desc
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from ..models import TrainingLog


class TrainingLogRepository:
    """Repository for Training Log operations"""

    @staticmethod
    async def create(db: AsyncSession, log_data: Dict) -> TrainingLog:
        """Create a new training log entry"""
        log = TrainingLog(**log_data)
        db.add(log)
        await db.flush()
        await db.refresh(log)
        return log

    @staticmethod
    async def get_by_task_id(
        db: AsyncSession,
        task_id: str,
        level: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0
    ) -> List[TrainingLog]:
        """
        Get logs for a training task with optional filtering.

        Args:
            db: Database session
            task_id: Training task ID
            level: Optional log level filter (INFO, WARNING, ERROR, DEBUG)
            limit: Maximum number of logs to return
            offset: Offset for pagination
        """
        query = select(TrainingLog).where(TrainingLog.task_id == task_id)

        if level:
            query = query.where(TrainingLog.level == level)

        query = query.order_by(TrainingLog.created_at, TrainingLog.sequence)
        query = query.limit(limit).offset(offset)

        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def get_recent(
        db: AsyncSession,
        task_id: str,
        count: int = 100
    ) -> List[TrainingLog]:
        """
        Get the most recent N logs for a training task.

        Args:
            db: Database session
            task_id: Training task ID
            count: Number of recent logs to return
        """
        query = select(TrainingLog).where(TrainingLog.task_id == task_id)
        query = query.order_by(desc(TrainingLog.created_at), desc(TrainingLog.sequence))
        query = query.limit(count)

        result = await db.execute(query)
        logs = result.scalars().all()

        # Return in chronological order
        return list(reversed(logs))

    @staticmethod
    async def get_logs_after_sequence(
        db: AsyncSession,
        task_id: str,
        after_sequence: int,
        limit: int = 100
    ) -> List[TrainingLog]:
        """
        Get logs after a specific sequence number (for streaming/polling).

        Args:
            db: Database session
            task_id: Training task ID
            after_sequence: Get logs with sequence > this value
            limit: Maximum number of logs to return
        """
        query = select(TrainingLog).where(
            TrainingLog.task_id == task_id,
            TrainingLog.sequence > after_sequence
        )
        query = query.order_by(TrainingLog.created_at, TrainingLog.sequence)
        query = query.limit(limit)

        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def delete_by_task_id(db: AsyncSession, task_id: str) -> bool:
        """Delete all logs for a training task"""
        result = await db.execute(
            delete(TrainingLog).where(TrainingLog.task_id == task_id)
        )
        await db.flush()
        return result.rowcount > 0


