"""
AIResultRepository - Data Access Layer
"""

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from ..models import AIResult
from .base import BaseRepository


class AIResultRepository(BaseRepository[AIResult]):
    """Repository for AI Result operations"""

    model = AIResult
    pk_field = "id"

    @staticmethod
    async def create(  # pyright: ignore[reportIncompatibleMethodOverride]
        db: AsyncSession, result_data: Dict[str, Any]
    ) -> AIResult:
        """Create a new AI result"""
        result = AIResult(**result_data)
        db.add(result)
        await db.flush()
        await db.refresh(result)
        return result

    @staticmethod
    async def bulk_create(
        db: AsyncSession, results_data: List[Dict[str, Any]], batch_size: int = 100
    ) -> int:
        """
        Bulk insert AI results for performance optimization.

        Args:
            db: Database session
            results_data: List of result dictionaries to insert
            batch_size: Number of records per batch (default 100)

        Returns:
            Number of records inserted
        """
        if not results_data:
            return 0

        total_inserted = 0
        for i in range(0, len(results_data), batch_size):
            batch = results_data[i : i + batch_size]
            objects = [AIResult(**data) for data in batch]
            db.add_all(objects)
            await db.flush()
            total_inserted += len(batch)

        return total_inserted

    @staticmethod
    async def get_by_wsi_id(db: AsyncSession, wsi_id: str) -> Optional[AIResult]:
        """Get latest result for a WSI"""
        result = await db.execute(
            select(AIResult)
            .where(AIResult.wsi_id == wsi_id)
            .order_by(desc(AIResult.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_task_id(db: AsyncSession, task_id: str) -> Optional[AIResult]:
        """Get result by task_id"""
        result = await db.execute(select(AIResult).where(AIResult.task_id == task_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def count(db: AsyncSession, user_id: Optional[str] = None) -> int:
        """Count total results.

        Args:
            db: Database session
            user_id: Optional user ID filter. If provided, only counts results belonging to this user.
                     If None, counts all results (for admin users).
        """
        query = select(func.count(AIResult.id))
        if user_id is not None:
            query = query.where(AIResult.user_id == user_id)
        result = await db.execute(query)
        return result.scalar_one()

    @staticmethod
    async def delete_by_task_id(db: AsyncSession, task_id: str) -> int:
        """Delete all AI results for a given task_id.

        Used by regenerate to remove old results before creating new ones.

        Args:
            db: Database session
            task_id: Training task ID

        Returns:
            Number of deleted records
        """
        result = await db.execute(delete(AIResult).where(AIResult.task_id == task_id))
        await db.flush()
        return result.rowcount
