from typing import List, Optional
from sqlalchemy import select, delete, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DatasetCollaborator, utc_now


class DatasetCollaboratorRepository:
    @staticmethod
    async def add(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
        added_by: str,
    ) -> DatasetCollaborator:
        collab = DatasetCollaborator(
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
            delete(DatasetCollaborator)
            .where(DatasetCollaborator.dataset_id == dataset_id)
            .where(DatasetCollaborator.user_id == user_id)
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
            select(DatasetCollaborator.id)
            .where(DatasetCollaborator.dataset_id == dataset_id)
            .where(DatasetCollaborator.user_id == user_id)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def list_by_dataset(
        db: AsyncSession,
        dataset_id: str,
    ) -> List[DatasetCollaborator]:
        result = await db.execute(
            select(DatasetCollaborator)
            .where(DatasetCollaborator.dataset_id == dataset_id)
            .order_by(DatasetCollaborator.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_dataset_ids_for_user(
        db: AsyncSession,
        user_id: str,
    ) -> List[str]:
        result = await db.execute(
            select(distinct(DatasetCollaborator.dataset_id)).where(
                DatasetCollaborator.user_id == user_id
            )
        )
        return list(result.scalars().all())
