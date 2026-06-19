"""
DatasetRepository - Data Access Layer
"""

import logging
from datetime import datetime
from typing import Any, List, Optional, Dict
from sqlalchemy import select, update, delete, func, insert, desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

from ..models import (
    DataGroup,
    Dataset,
    DatasetGrant,
    SegmentationAnnotation,
    WSISlide,
    AITask,
    AIResult,
    TrainingTaskWSI,
    utc_now,
)
from .base import BaseRepository


class DatasetNameConflictError(ValueError):
    pass


class DatasetRepository(BaseRepository[Dataset]):
    """Repository for Dataset operations"""

    model = Dataset
    pk_field = "dataset_id"

    @classmethod
    async def get_by_id(cls, db: AsyncSession, pk_value: Any) -> Optional[Dataset]:
        result = await db.execute(
            select(Dataset)
            .options(selectinload(Dataset.data_group))
            .where(Dataset.dataset_id == pk_value)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_name(
        db: AsyncSession, name: str, user_id: Optional[str] = None
    ) -> Optional[Dataset]:
        """Get dataset by display name with data_group relationship loaded"""
        query = (
            select(Dataset)
            .options(selectinload(Dataset.data_group))
            .where(Dataset.name == name)
        )
        if user_id is not None:
            query = query.where(Dataset.user_id == user_id)

        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_or_create(
        db: AsyncSession,
        name: str,
        group_id: str,
        user_id: str = None,
        source_organ: str = None,
        parent_dataset_id: str = None,
        is_public: bool = False,
        reuse_existing: bool = True,
    ) -> Dataset:
        import uuid

        existing = await DatasetRepository.get_by_name(db, name, user_id=user_id)
        if existing:
            if not reuse_existing:
                raise DatasetNameConflictError(name)
            return existing
        dataset_id = str(uuid.uuid4())
        try:
            async with db.begin_nested():
                await DatasetRepository.create(
                    db,
                    dataset_id=dataset_id,
                    name=name,
                    group_id=group_id,
                    user_id=user_id,
                    source_organ=source_organ,
                    parent_dataset_id=parent_dataset_id,
                    is_public=is_public,
                )
            fetched = await DatasetRepository.get_by_id(db, dataset_id)
            if fetched is not None:
                return fetched
            raise RuntimeError(f"Dataset {dataset_id} not found after creation")
        except IntegrityError:
            logger.debug(
                f"Dataset concurrent insert detected for name='{name}', re-querying"
            )
            existing = await DatasetRepository.get_by_name(db, name, user_id=user_id)
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
    async def get_empty_datasets(db: AsyncSession) -> List[Dataset]:
        """Get datasets that no longer have any WSI rows."""
        empty_dataset_ids = (
            select(Dataset.dataset_id)
            .outerjoin(WSISlide, Dataset.dataset_id == WSISlide.dataset_id)
            .group_by(Dataset.dataset_id)
            .having(func.count(WSISlide.id) == 0)
        )

        result = await db.execute(
            select(Dataset)
            .options(selectinload(Dataset.data_group))
            .where(Dataset.dataset_id.in_(empty_dataset_ids))
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
    async def delete(db: AsyncSession, dataset_id: str) -> bool:
        """Delete dataset and all associated records.

        Deletion order (PostgreSQL FK-safe):
        1. Leaf records of WSI slides (ai_results, ai_tasks, training_task_wsi)
        2. Dataset-level records (segmentation annotations, permissions)
        3. WSI slides in this dataset
        4. The dataset itself
        """
        # Get all wsi_ids in this dataset
        wsi_query = await db.execute(
            select(WSISlide.wsi_id).where(WSISlide.dataset_id == dataset_id)
        )
        wsi_ids = [row[0] for row in wsi_query.fetchall()]

        if wsi_ids:
            # Delete WSI children: ai_results first (FK to ai_tasks), then ai_tasks, then training_task_wsi
            await db.execute(delete(AIResult).where(AIResult.wsi_id.in_(wsi_ids)))
            await db.execute(delete(AITask).where(AITask.wsi_id.in_(wsi_ids)))
            await db.execute(
                delete(TrainingTaskWSI).where(TrainingTaskWSI.wsi_id.in_(wsi_ids))
            )

        await db.execute(
            delete(SegmentationAnnotation).where(
                SegmentationAnnotation.source_dataset_id == dataset_id
            )
        )
        await db.execute(
            delete(DatasetGrant).where(DatasetGrant.dataset_id == dataset_id)
        )

        # Delete WSI slides
        await db.execute(delete(WSISlide).where(WSISlide.dataset_id == dataset_id))

        result = await db.execute(
            delete(Dataset).where(Dataset.dataset_id == dataset_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def get_wsi_ids(db: AsyncSession, dataset_id: str) -> List[str]:
        result = await db.execute(
            select(WSISlide.wsi_id)
            .where(WSISlide.dataset_id == dataset_id)
            .order_by(desc(WSISlide.created_at))
        )
        return [row[0] for row in result.all()]

    @staticmethod
    async def get_wsi_ids_batch(
        db: AsyncSession, dataset_ids: List[str]
    ) -> Dict[str, List[str]]:
        if not dataset_ids:
            return {}
        result = await db.execute(
            select(WSISlide.dataset_id, WSISlide.wsi_id).where(
                WSISlide.dataset_id.in_(dataset_ids)
            )
        )
        mapping: Dict[str, List[str]] = {did: [] for did in dataset_ids}
        for dataset_id, wsi_id in result.all():
            mapping[dataset_id].append(wsi_id)
        return mapping

    @staticmethod
    async def get_wsi_path_refs_batch(
        db: AsyncSession, dataset_ids: List[str]
    ) -> Dict[str, List[Dict[str, str]]]:
        if not dataset_ids:
            return {}
        result = await db.execute(
            select(WSISlide.dataset_id, WSISlide.wsi_id, WSISlide.wsi_path).where(
                WSISlide.dataset_id.in_(dataset_ids)
            )
        )
        mapping: Dict[str, List[Dict[str, str]]] = {did: [] for did in dataset_ids}
        for dataset_id, wsi_id, wsi_path in result.all():
            mapping[dataset_id].append({"wsi_id": wsi_id, "wsi_path": wsi_path})
        return mapping

    @staticmethod
    async def get_wsi_case_ids(db: AsyncSession, dataset_id: str) -> Dict[str, str]:
        """Get case_id mapping for all WSIs in a dataset.

        Returns:
            Dict mapping wsi_id to case_id. If case_id is None, uses wsi_id as fallback.
        """
        result = await db.execute(
            select(WSISlide.wsi_id, WSISlide.case_id).where(
                WSISlide.dataset_id == dataset_id
            )
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
    async def get_distinct_labels(db: AsyncSession, dataset_id: str) -> list[Any]:
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

    @staticmethod
    async def get_public_dataset_ids(db: AsyncSession) -> List[str]:
        result = await db.execute(
            select(Dataset.dataset_id).where(Dataset.is_public.is_(True))
        )
        return [row[0] for row in result.all()]

    @staticmethod
    async def get_child_dataset_ids(
        db: AsyncSession, parent_ids: List[str], max_depth: int = 3
    ) -> List[str]:
        if not parent_ids:
            return []
        all_child_ids: set = set()
        frontier = list(parent_ids)
        for _ in range(max_depth):
            result = await db.execute(
                select(Dataset.dataset_id).where(
                    Dataset.parent_dataset_id.in_(frontier)
                )
            )
            new_ids = [
                row[0]
                for row in result.all()
                if row[0] not in all_child_ids and row[0] not in parent_ids
            ]
            if not new_ids:
                break
            all_child_ids.update(new_ids)
            frontier = new_ids
        return list(all_child_ids)

    @staticmethod
    async def get_ancestor_dataset_ids(
        db: AsyncSession, dataset_id: Optional[str], max_depth: int = 8
    ) -> List[str]:
        if not dataset_id:
            return []

        ancestors: List[str] = []
        seen: set[str] = set()
        current_id = dataset_id

        for _ in range(max_depth):
            if not current_id or current_id in seen:
                break
            seen.add(current_id)

            result = await db.execute(
                select(Dataset.parent_dataset_id).where(
                    Dataset.dataset_id == current_id
                )
            )
            parent_id = result.scalar_one_or_none()
            if not parent_id:
                break

            ancestors.append(parent_id)
            current_id = parent_id

        return ancestors
