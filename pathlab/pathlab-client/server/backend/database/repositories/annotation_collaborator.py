from typing import List, Optional
from sqlalchemy import select, delete, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AnnotationCollaborator, utc_now


class AnnotationCollaboratorRepository:
    @staticmethod
    async def add(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
        added_by: str,
    ) -> AnnotationCollaborator:
        collab = AnnotationCollaborator(
            dataset_id=dataset_id,
            user_id=user_id,
            added_by=added_by,
            created_at=utc_now(),
        )
        db.add(collab)
        await db.flush()
        await db.refresh(collab)
        return collab

    @staticmethod
    async def remove(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
    ) -> bool:
        result = await db.execute(
            delete(AnnotationCollaborator)
            .where(AnnotationCollaborator.dataset_id == dataset_id)
            .where(AnnotationCollaborator.user_id == user_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def exists(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
    ) -> bool:
        result = await db.execute(
            select(AnnotationCollaborator.id)
            .where(AnnotationCollaborator.dataset_id == dataset_id)
            .where(AnnotationCollaborator.user_id == user_id)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def list_by_dataset(
        db: AsyncSession,
        dataset_id: str,
    ) -> List[AnnotationCollaborator]:
        result = await db.execute(
            select(AnnotationCollaborator)
            .where(AnnotationCollaborator.dataset_id == dataset_id)
            .order_by(AnnotationCollaborator.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_dataset_ids_for_user(
        db: AsyncSession,
        user_id: str,
    ) -> List[str]:
        result = await db.execute(
            select(distinct(AnnotationCollaborator.dataset_id)).where(
                AnnotationCollaborator.user_id == user_id
            )
        )
        return list(result.scalars().all())
