"""
DatasetRepository - Data Access Layer
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy import select, update, delete, func, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

from ..models import DataGroup, Dataset, WSISlide, AITask, AIResult, TrainingTaskWSI, utc_now


class DatasetRepository:
    """Repository for Dataset operations"""

    @staticmethod
    async def create(
        db: AsyncSession,
        dataset_id: str,
        name: str,
        group_id: str,
        description: str = None,
        user_id: str = None
    ) -> Dataset:
        """Create a new dataset record with data_group relationship loaded"""
        dataset = Dataset(
            dataset_id=dataset_id,
            name=name,
            group_id=group_id,
            description=description,
            user_id=user_id
        )
        db.add(dataset)
        await db.flush()
        # Re-fetch with data_group relationship loaded to avoid lazy loading issues
        result = await db.execute(
            select(Dataset)
            .options(selectinload(Dataset.data_group))
            .where(Dataset.dataset_id == dataset_id)
        )
        return result.scalar_one()

    @staticmethod
    async def get_by_id(db: AsyncSession, dataset_id: str) -> Optional[Dataset]:
        """Get dataset by dataset_id (UUID) with data_group relationship loaded"""
        result = await db.execute(
            select(Dataset)
            .options(selectinload(Dataset.data_group))
            .where(Dataset.dataset_id == dataset_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_name(db: AsyncSession, name: str) -> Optional[Dataset]:
        """Get dataset by display name with data_group relationship loaded"""
        result = await db.execute(
            select(Dataset)
            .options(selectinload(Dataset.data_group))
            .where(Dataset.name == name)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_or_create(
        db: AsyncSession,
        name: str,
        group_id: str,
        user_id: str = None
    ) -> Dataset:
        """Get existing dataset by name or create new one with UUID.

        Note: Dataset name does not have a UNIQUE constraint (different users may
        share dataset names). Under PostgreSQL READ COMMITTED, concurrent calls with
        the same name may create duplicate datasets. This is acceptable as
        get_by_name returns the first match, and duplicates are rare in practice.
        A SAVEPOINT is still used to handle any unexpected IntegrityError gracefully.
        """
        import uuid
        existing = await DatasetRepository.get_by_name(db, name)
        if existing:
            return existing
        dataset_id = str(uuid.uuid4())
        try:
            async with db.begin_nested():
                return await DatasetRepository.create(db, dataset_id, name, group_id=group_id, user_id=user_id)
        except IntegrityError:
            # Unlikely but handle gracefully — re-query
            logger.debug(f"Dataset concurrent insert detected for name='{name}', re-querying")
            existing = await DatasetRepository.get_by_name(db, name)
            if existing:
                return existing
            raise

    @staticmethod
    async def get_all(db: AsyncSession) -> List[Dataset]:
        """Get all datasets with data_group relationship loaded"""
        result = await db.execute(
            select(Dataset)
            .options(selectinload(Dataset.data_group))
            .order_by(Dataset.name)
        )
        return result.scalars().all()

    @staticmethod
    async def get_by_ids(db: AsyncSession, dataset_ids: List[str]) -> List[Dataset]:
        """Get multiple datasets by IDs in a single query (batch operation)"""
        if not dataset_ids:
            return []
        result = await db.execute(
            select(Dataset)
            .options(selectinload(Dataset.data_group))
            .where(Dataset.dataset_id.in_(dataset_ids))
        )
        return result.scalars().all()

    @staticmethod
    async def update(db: AsyncSession, dataset_id: str, update_data: Dict) -> Optional[Dataset]:
        """Update dataset"""
        update_data["updated_at"] = utc_now()
        await db.execute(
            update(Dataset)
            .where(Dataset.dataset_id == dataset_id)
            .values(**update_data)
        )
        await db.flush()
        return await DatasetRepository.get_by_id(db, dataset_id)

    @staticmethod
    async def delete(db: AsyncSession, dataset_id: str) -> bool:
        """Delete dataset and all associated records.

        Deletion order (PostgreSQL FK-safe):
        1. Leaf records of WSI slides (ai_results, ai_tasks, training_task_wsi)
        2. WSI slides in this dataset
        3. The dataset itself (dataset_permissions auto-cascade via DB ondelete=CASCADE)
        """
        # Get all wsi_ids in this dataset
        wsi_query = await db.execute(
            select(WSISlide.wsi_id).where(WSISlide.dataset_id == dataset_id)
        )
        wsi_ids = [row[0] for row in wsi_query.fetchall()]

        if wsi_ids:
            # Delete WSI children: ai_results first (FK to ai_tasks), then ai_tasks, then training_task_wsi
            await db.execute(
                delete(AIResult).where(AIResult.wsi_id.in_(wsi_ids))
            )
            await db.execute(
                delete(AITask).where(AITask.wsi_id.in_(wsi_ids))
            )
            await db.execute(
                delete(TrainingTaskWSI).where(TrainingTaskWSI.wsi_id.in_(wsi_ids))
            )

        # Delete WSI slides
        await db.execute(
            delete(WSISlide).where(WSISlide.dataset_id == dataset_id)
        )

        # Delete the dataset (dataset_permissions has ondelete=CASCADE, DB handles it)
        result = await db.execute(
            delete(Dataset).where(Dataset.dataset_id == dataset_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def get_wsi_ids(db: AsyncSession, dataset_id: str) -> List[str]:
        """Get all WSI IDs in a dataset."""
        result = await db.execute(
            select(WSISlide.wsi_id).where(WSISlide.dataset_id == dataset_id)
        )
        return [row[0] for row in result.all()]

    @staticmethod
    async def get_wsi_case_ids(db: AsyncSession, dataset_id: str) -> Dict[str, str]:
        """Get case_id mapping for all WSIs in a dataset.

        Returns:
            Dict mapping wsi_id to case_id. If case_id is None, uses wsi_id as fallback.
        """
        result = await db.execute(
            select(WSISlide.wsi_id, WSISlide.case_id)
            .where(WSISlide.dataset_id == dataset_id)
        )
        case_id_map: Dict[str, str] = {}
        for row in result.all():
            wsi_id, case_id = row[0], row[1]
            case_id_map[wsi_id] = case_id if case_id else wsi_id
        return case_id_map

    @staticmethod
    async def get_aggregation_level(db: AsyncSession, dataset_id: str) -> Optional[str]:
        """Get the aggregation_level of a dataset via its DataGroup.

        Returns:
            'case' or 'file', or None if dataset not found.
        """
        result = await db.execute(
            select(DataGroup.aggregation_level)
            .join(Dataset, Dataset.group_id == DataGroup.group_id)
            .where(Dataset.dataset_id == dataset_id)
            .limit(1)
        )
        row = result.first()
        return row[0] if row else None

    @staticmethod
    async def get_distinct_label_count(db: AsyncSession, dataset_id: str) -> int:
        """Get the count of distinct non-null labels in a dataset."""
        result = await db.execute(
            select(func.count(func.distinct(WSISlide.label)))
            .where(WSISlide.dataset_id == dataset_id)
            .where(WSISlide.label.isnot(None))
        )
        return result.scalar() or 0

    @staticmethod
    async def get_distinct_labels(db: AsyncSession, dataset_id: str) -> list:
        """Get the list of distinct non-null labels in a dataset."""
        result = await db.execute(
            select(WSISlide.label)
            .where(WSISlide.dataset_id == dataset_id)
            .where(WSISlide.label.isnot(None))
            .distinct()
        )
        return [row[0] for row in result.all()]

    @staticmethod
    async def get_feature_extracted_count(db: AsyncSession, dataset_id: str) -> int:
        """Get the count of WSIs with feature_extracted=True in a dataset."""
        result = await db.execute(
            select(func.count(WSISlide.id))
            .where(WSISlide.dataset_id == dataset_id)
            .where(WSISlide.feature_extracted == True)  # noqa: E712
        )
        return result.scalar() or 0


