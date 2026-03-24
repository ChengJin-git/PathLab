"""
TrainedModelRepository - Data Access Layer
"""

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import select, update, delete, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from ..models import TrainedModel
from .base import BaseRepository


class TrainedModelRepository(BaseRepository[TrainedModel]):
    """Repository for Trained Model operations"""

    model = TrainedModel
    pk_field = "model_id"

    @staticmethod
    async def create(  # pyright: ignore[reportIncompatibleMethodOverride]
        db: AsyncSession, model_data: Dict[str, Any]
    ) -> TrainedModel:
        """Create a new trained model"""
        model = TrainedModel(**model_data)
        db.add(model)
        await db.flush()
        await db.refresh(model)
        return model

    @staticmethod
    async def get_by_task_id(db: AsyncSession, task_id: str) -> List[TrainedModel]:
        """Get all models from a training task"""
        result = await db.execute(
            select(TrainedModel)
            .where(TrainedModel.task_id == task_id)
            .order_by(desc(TrainedModel.created_at))
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_all(
        db: AsyncSession,
        limit: int = 100,
        offset: int = 0,
        user_id: Optional[str] = None,
    ) -> List[TrainedModel]:
        """Get all trained models.

        Args:
            db: Database session
            limit: Maximum number of records to return
            offset: Number of records to skip
            user_id: Optional user ID filter. If provided, only returns models belonging to this user.
                     If None, returns all models (for admin users).
        """
        query = select(TrainedModel)
        if user_id is not None:
            query = query.where(TrainedModel.user_id == user_id)
        query = (
            query.order_by(desc(TrainedModel.created_at)).limit(limit).offset(offset)
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def count(db: AsyncSession, user_id: Optional[str] = None) -> int:
        """Count total trained models.

        Args:
            db: Database session
            user_id: Optional user ID filter. If provided, only counts models belonging to this user.
                     If None, counts all models (for admin users).
        """
        query = select(func.count(TrainedModel.id))
        if user_id is not None:
            query = query.where(TrainedModel.user_id == user_id)
        result = await db.execute(query)
        return result.scalar_one()

    @staticmethod
    async def delete(db: AsyncSession, model_id: str) -> bool:
        """Delete a trained model"""
        result = await db.execute(
            delete(TrainedModel).where(TrainedModel.model_id == model_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def get_default(db: AsyncSession) -> Optional[TrainedModel]:
        """Get the default model for inference"""
        result = await db.execute(
            select(TrainedModel)
            .where(TrainedModel.is_default == True)
            .where(TrainedModel.is_active == True)
            .order_by(desc(TrainedModel.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_active_models(db: AsyncSession) -> List[TrainedModel]:
        """Get all active models"""
        result = await db.execute(
            select(TrainedModel)
            .where(TrainedModel.is_active == True)
            .order_by(desc(TrainedModel.created_at))
        )
        return list(result.scalars().all())

    @staticmethod
    async def set_default(db: AsyncSession, model_id: str) -> Optional[TrainedModel]:
        """Set a model as default (unset all others).

        Race-condition safe under PostgreSQL READ COMMITTED:
        Uses SELECT FOR UPDATE to lock all TrainedModel rows before the
        two UPDATE statements, preventing interleaving with concurrent
        set_default calls that could leave multiple models as default.
        """
        # Lock all TrainedModel rows to prevent concurrent set_default interleaving
        await db.execute(select(TrainedModel).with_for_update())

        # First, unset all default flags
        await db.execute(update(TrainedModel).values(is_default=False))

        # Then set the specified model as default
        await db.execute(
            update(TrainedModel)
            .where(TrainedModel.model_id == model_id)
            .values(is_default=True, is_active=True)
        )
        await db.flush()
        return await TrainedModelRepository.get_by_id(db, model_id)

    @staticmethod
    async def set_active(
        db: AsyncSession, model_id: str, is_active: bool
    ) -> Optional[TrainedModel]:
        """Activate or deactivate a model"""
        await db.execute(
            update(TrainedModel)
            .where(TrainedModel.model_id == model_id)
            .values(is_active=is_active)
        )
        await db.flush()
        return await TrainedModelRepository.get_by_id(db, model_id)
