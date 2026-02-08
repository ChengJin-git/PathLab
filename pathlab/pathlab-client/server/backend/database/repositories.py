"""
Data Access Layer (Repository Pattern)

Provides high-level database operations for all models.
"""

from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy import select, update, delete, func, desc, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import DataGroup, Dataset, WSISlide, AITask, AIResult, ChatConversation, ChatMessage, MessageFeedback, ExportTask, TrainingTask, TrainingTaskWSI, TrainedModel, TrainingLog, DatasetPermission, StorageTask, utc_now
from backend.ai.utils.data_splitter import split_wsi_dataset, split_case_dataset
from backend.ai.schemas.base import TaskStatus
from backend.common.file_types import WSI_EXTENSIONS, PATCH_EXTENSIONS, TIF_EXTENSIONS, SIZE_THRESHOLD


class DataGroupRepository:
    """Repository for DataGroup operations"""

    @staticmethod
    async def create(
        db: AsyncSession,
        group_id: str,
        name: str,
        data_type: str,
        aggregation_level: str,
        task_type: str,
        description: str = None
    ) -> DataGroup:
        """Create a new data group record"""
        data_group = DataGroup(
            group_id=group_id,
            name=name,
            data_type=data_type,
            aggregation_level=aggregation_level,
            task_type=task_type,
            description=description
        )
        db.add(data_group)
        await db.flush()
        await db.refresh(data_group)
        return data_group

    @staticmethod
    async def get_by_id(db: AsyncSession, group_id: str) -> Optional[DataGroup]:
        """Get data group by group_id (UUID)"""
        result = await db.execute(
            select(DataGroup).where(DataGroup.group_id == group_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_combination(
        db: AsyncSession,
        data_type: str,
        aggregation_level: str,
        task_type: str
    ) -> Optional[DataGroup]:
        """Get data group by unique combination of data_type, aggregation_level, task_type"""
        result = await db.execute(
            select(DataGroup).where(
                DataGroup.data_type == data_type,
                DataGroup.aggregation_level == aggregation_level,
                DataGroup.task_type == task_type
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_or_create(
        db: AsyncSession,
        data_type: str,
        aggregation_level: str,
        task_type: str,
        name: str = None,
        description: str = None
    ) -> DataGroup:
        """Get existing data group by combination or create new one with UUID"""
        import uuid
        existing = await DataGroupRepository.get_by_combination(
            db, data_type, aggregation_level, task_type
        )
        if existing:
            return existing

        # Auto-generate name if not provided
        if name is None:
            name = f"{data_type.upper()} {aggregation_level.capitalize()}-level {task_type.capitalize()}"

        group_id = str(uuid.uuid4())
        return await DataGroupRepository.create(
            db, group_id, name, data_type, aggregation_level, task_type, description
        )

    @staticmethod
    async def get_all(db: AsyncSession) -> List[DataGroup]:
        """Get all data groups"""
        result = await db.execute(
            select(DataGroup).order_by(DataGroup.name)
        )
        return result.scalars().all()

    @staticmethod
    async def update(db: AsyncSession, group_id: str, update_data: Dict) -> Optional[DataGroup]:
        """Update data group"""
        update_data["updated_at"] = utc_now()
        await db.execute(
            update(DataGroup)
            .where(DataGroup.group_id == group_id)
            .values(**update_data)
        )
        await db.flush()
        return await DataGroupRepository.get_by_id(db, group_id)

    @staticmethod
    async def delete(db: AsyncSession, group_id: str) -> bool:
        """Delete data group (cascades to datasets and training tasks)"""
        result = await db.execute(
            delete(DataGroup).where(DataGroup.group_id == group_id)
        )
        await db.flush()
        return result.rowcount > 0


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
        """Get existing dataset by name or create new one with UUID"""
        import uuid
        existing = await DatasetRepository.get_by_name(db, name)
        if existing:
            return existing
        dataset_id = str(uuid.uuid4())
        return await DatasetRepository.create(db, dataset_id, name, group_id=group_id, user_id=user_id)

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
        """Delete dataset (cascades to WSI slides)"""
        result = await db.execute(
            delete(Dataset).where(Dataset.dataset_id == dataset_id)
        )
        await db.flush()
        return result.rowcount > 0


class WSIRepository:
    """Repository for WSI Slide operations"""

    @staticmethod
    async def get_by_id_with_dataset(db: AsyncSession, wsi_id: str) -> Optional[WSISlide]:
        """Get WSI by wsi_id with dataset relationship loaded"""
        result = await db.execute(
            select(WSISlide).options(selectinload(WSISlide.dataset)).where(WSISlide.wsi_id == wsi_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_ids_with_dataset(
        db: AsyncSession,
        wsi_ids: List[str],
        batch_size: int = 500
    ) -> Dict[str, WSISlide]:
        """
        Get multiple WSI slides by IDs in a single query (batch operation).

        This is optimized for validating large numbers of WSI IDs - avoids N+1 query problem.
        For datasets exceeding batch_size, queries are batched to avoid SQLite limitations.

        Args:
            db: Database session
            wsi_ids: List of WSI IDs to fetch
            batch_size: Number of IDs per batch (default 500, SQLite limit is 999)

        Returns:
            Dict mapping wsi_id to WSISlide for found slides
        """
        if not wsi_ids:
            return {}

        result_dict: Dict[str, WSISlide] = {}

        # Batch query to avoid SQLite variable limit (999)
        for i in range(0, len(wsi_ids), batch_size):
            batch_ids = wsi_ids[i:i + batch_size]
            result = await db.execute(
                select(WSISlide)
                .options(selectinload(WSISlide.dataset))
                .where(WSISlide.wsi_id.in_(batch_ids))
            )
            wsis = result.scalars().all()
            for wsi in wsis:
                result_dict[wsi.wsi_id] = wsi

        return result_dict

    @staticmethod
    async def get_by_ids(
        db: AsyncSession,
        wsi_ids: List[str],
        batch_size: int = 500
    ) -> Dict[str, WSISlide]:
        """
        Get multiple WSI slides by IDs in a single query (batch operation).

        Simpler version without loading dataset relationship - faster when only
        basic WSI fields are needed (e.g., dataset_id, user_id, wsi_path).

        Args:
            db: Database session
            wsi_ids: List of WSI IDs to fetch
            batch_size: Number of IDs per batch (default 500, SQLite limit is 999)

        Returns:
            Dict mapping wsi_id to WSISlide for found slides
        """
        if not wsi_ids:
            return {}

        result_dict: Dict[str, WSISlide] = {}

        # Batch query to avoid SQLite variable limit (999)
        for i in range(0, len(wsi_ids), batch_size):
            batch_ids = wsi_ids[i:i + batch_size]
            result = await db.execute(
                select(WSISlide).where(WSISlide.wsi_id.in_(batch_ids))
            )
            wsis = result.scalars().all()
            for wsi in wsis:
                result_dict[wsi.wsi_id] = wsi

        return result_dict

    @staticmethod
    async def get_all_with_dataset(
        db: AsyncSession,
        skip: int = 0,
        limit: int = 0,
        user_id: Optional[str] = None,
        data_type: Optional[str] = None,
        elevated_dataset_ids: Optional[List[str]] = None
    ) -> List[WSISlide]:
        """Get all WSI slides with dataset relationship loaded.

        Args:
            db: Database session
            skip: Number of records to skip
            limit: Maximum number of records to return (0 = all)
            user_id: Optional user ID filter. If provided, only returns WSI belonging to this user.
                     If None, returns all WSI (for admin users).
            data_type: Optional filter - "wsi" for WSI files, "patch" for image files
            elevated_dataset_ids: Optional list of dataset IDs that the user has temporary elevated permissions for.
                                  WSI slides in these datasets will be included even if user doesn't own them.
        """
        from sqlalchemy import or_

        query = select(WSISlide).options(selectinload(WSISlide.dataset))

        # Apply user_id filter with elevated_dataset_ids support
        if user_id is not None:
            if elevated_dataset_ids:
                # Include user's own data OR data from elevated permission datasets
                query = query.where(
                    or_(
                        WSISlide.user_id == user_id,
                        WSISlide.dataset_id.in_(elevated_dataset_ids)
                    )
                )
            else:
                query = query.where(WSISlide.user_id == user_id)

        # Apply data_type filter
        data_type_filter = WSIRepository._build_data_type_filter(data_type)
        if data_type_filter is not None:
            query = query.where(data_type_filter)

        query = query.order_by(desc(WSISlide.created_at)).offset(skip)
        if limit > 0:
            query = query.limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def create(db: AsyncSession, wsi_data: Dict) -> WSISlide:
        """Create a new WSI slide record"""
        wsi = WSISlide(**wsi_data)
        db.add(wsi)
        await db.flush()
        await db.refresh(wsi)
        return wsi

    @staticmethod
    async def get_by_id(db: AsyncSession, wsi_id: str) -> Optional[WSISlide]:
        """Get WSI by wsi_id"""
        result = await db.execute(
            select(WSISlide).where(WSISlide.wsi_id == wsi_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(db: AsyncSession, skip: int = 0, limit: int = 0) -> List[WSISlide]:
        """Get all WSI slides with pagination. If limit=0, return all records."""
        query = select(WSISlide).order_by(desc(WSISlide.created_at)).offset(skip)
        if limit > 0:
            query = query.limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def count(
        db: AsyncSession,
        user_id: Optional[str] = None,
        data_type: Optional[str] = None,
        elevated_dataset_ids: Optional[List[str]] = None
    ) -> int:
        """Get total count of WSI slides.

        Args:
            db: Database session
            user_id: Optional user ID filter. If provided, only counts WSI belonging to this user.
                     If None, counts all WSI (for admin users).
            data_type: Optional filter - "wsi" for WSI files, "patch" for image files
            elevated_dataset_ids: Optional list of dataset IDs that the user has temporary elevated permissions for.
                                  WSI slides in these datasets will be counted even if user doesn't own them.
        """
        from sqlalchemy import or_

        query = select(func.count(WSISlide.id))

        # Apply user_id filter with elevated_dataset_ids support
        if user_id is not None:
            if elevated_dataset_ids:
                # Count user's own data OR data from elevated permission datasets
                query = query.where(
                    or_(
                        WSISlide.user_id == user_id,
                        WSISlide.dataset_id.in_(elevated_dataset_ids)
                    )
                )
            else:
                query = query.where(WSISlide.user_id == user_id)

        # Apply data_type filter
        data_type_filter = WSIRepository._build_data_type_filter(data_type)
        if data_type_filter is not None:
            query = query.where(data_type_filter)

        result = await db.execute(query)
        return result.scalar_one()

    @staticmethod
    async def get_by_label(db: AsyncSession, label: str) -> List[WSISlide]:
        """Get all WSI slides with specific label"""
        result = await db.execute(
            select(WSISlide).where(WSISlide.label == label)
        )
        return result.scalars().all()

    @staticmethod
    async def update(db: AsyncSession, wsi_id: str, update_data: Dict) -> Optional[WSISlide]:
        """Update WSI slide (returns WSISlide with dataset relationship loaded)"""
        update_data["updated_at"] = utc_now()
        await db.execute(
            update(WSISlide)
            .where(WSISlide.wsi_id == wsi_id)
            .values(**update_data)
        )
        await db.flush()
        return await WSIRepository.get_by_id_with_dataset(db, wsi_id)

    @staticmethod
    async def update_splits(db: AsyncSession, dataset_name: str, updates: List[tuple]) -> int:
        """
        Batch update split column for multiple WSIs.
        
        Args:
            db: Database session
            dataset_name: Dataset name for validation (optional but recommended)
            updates: List of (wsi_id, split_value) tuples
            
        Returns:
            Number of successfully updated records
        """
        count = 0
        for wsi_id, split_val in updates:
            # We can optimize this with a single update statement using a CASE/binding
            # but for SQLite simplicity relative to list size, individual updates are acceptable
            # or we could do `UPDATE wsi_slides SET split = :split WHERE wsi_id = :wsi_id` in a batch.
            
            # Simple check + update
            stmt = (
                update(WSISlide)
                .where(WSISlide.wsi_id == wsi_id)
                # .where(WSISlide.dataset_name == dataset_name) # Check dataset if needed
                .values(split=split_val, updated_at=utc_now())
            )
            result = await db.execute(stmt)
            count += result.rowcount
            
        await db.commit()
        return count


    @staticmethod
    async def delete(db: AsyncSession, wsi_id: str) -> bool:
        """Delete WSI slide"""
        result = await db.execute(
            delete(WSISlide).where(WSISlide.wsi_id == wsi_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def get_label_distribution(db: AsyncSession, user_id: Optional[str] = None) -> Dict[str, int]:
        """Get distribution of labels.

        Args:
            db: Database session
            user_id: Optional user ID filter. If provided, only counts labels for WSI belonging to this user.
                     If None, counts all labels (for admin users).
        """
        query = select(WSISlide.label, func.count(WSISlide.id)).group_by(WSISlide.label)
        if user_id is not None:
            query = query.where(WSISlide.user_id == user_id)
        result = await db.execute(query)
        return {label: count for label, count in result.all() if label}

    @staticmethod
    async def get_event_status_distribution(db: AsyncSession, user_id: Optional[str] = None) -> Dict[str, int]:
        """Get distribution of event_status for survival prediction tasks.

        Args:
            db: Database session
            user_id: Optional user ID filter. If provided, only counts event_status for WSI belonging to this user.
                     If None, counts all event_status (for admin users).

        Returns:
            Dict with keys 'event' (status=1) and 'censored' (status=0) and their counts
        """
        query = select(WSISlide.event_status, func.count(WSISlide.id)).group_by(WSISlide.event_status)
        if user_id is not None:
            query = query.where(WSISlide.user_id == user_id)
        # Only count WSI with valid survival data (event_status is not None and event_time is not None)
        query = query.where(WSISlide.event_status.isnot(None))
        query = query.where(WSISlide.event_time.isnot(None))

        result = await db.execute(query)
        distribution = {}
        for status, count in result.all():
            if status == 1:
                distribution['event'] = count
            elif status == 0:
                distribution['censored'] = count
        return distribution

    @staticmethod
    async def get_existing_original_filenames(db: AsyncSession, filenames: List[str], user_id: Optional[str] = None) -> List[str]:
        """
        Check which original_filenames already exist in the database.

        Args:
            db: Database session
            filenames: List of original_filename values to check
            user_id: Optional user ID filter. If provided, only checks filenames belonging to this user.
                     If None, checks all filenames (for admin users).

        Returns:
            List of filenames that already exist in the database
        """
        if not filenames:
            return []
        query = select(WSISlide.original_filename).where(WSISlide.original_filename.in_(filenames))
        if user_id is not None:
            query = query.where(WSISlide.user_id == user_id)
        result = await db.execute(query)
        return [row[0] for row in result.all() if row[0]]

    # File type constants imported from backend.common.file_types

    @staticmethod
    def _build_data_type_filter(data_type: Optional[str]):
        """
        Build SQLAlchemy filter for data_type (wsi/patch).

        Args:
            data_type: "wsi" for WSI files, "patch" for image files, None for all

        Returns:
            SQLAlchemy filter condition or None
        """
        from sqlalchemy import or_, and_

        if data_type == "wsi":
            wsi_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSI_EXTENSIONS]
            tif_conditions = [
                and_(
                    or_(*[func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in TIF_EXTENSIONS]),
                    WSISlide.file_size >= SIZE_THRESHOLD
                )
            ]
            return or_(*wsi_ext_conditions, *tif_conditions)
        elif data_type == "patch":
            patch_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in PATCH_EXTENSIONS]
            tif_conditions = [
                and_(
                    or_(*[func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in TIF_EXTENSIONS]),
                    or_(
                        WSISlide.file_size < SIZE_THRESHOLD,
                        WSISlide.file_size.is_(None)
                    )
                )
            ]
            return or_(*patch_ext_conditions, *tif_conditions)
        return None

    @staticmethod
    async def get_chat_context_stats(
        db: AsyncSession,
        user_id: Optional[str] = None,
        elevated_dataset_ids: Optional[List[str]] = None
    ) -> Dict:
        """
        Get all statistics needed for chat context in a SINGLE optimized query.
        This combines count, label distribution, data type distribution, and dataset info.

        Args:
            db: Database session
            user_id: Optional user ID filter.
            elevated_dataset_ids: Optional list of dataset IDs that the user has temporary elevated permissions for.
                                  These datasets will be included and marked as "elevated" access.

        Returns:
            Dict with total_count, labels (dict), data_types (dict), datasets (list)
            Each dataset in the list has an "access_type" field: "own" or "elevated"
        """
        from sqlalchemy import case, or_, and_

        # Build WSI/Patch conditions
        wsi_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSI_EXTENSIONS]
        tif_wsi_condition = and_(
            or_(*[func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in TIF_EXTENSIONS]),
            WSISlide.file_size >= SIZE_THRESHOLD
        )
        is_wsi = or_(*wsi_ext_conditions, tif_wsi_condition)

        patch_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in PATCH_EXTENSIONS]
        tif_patch_condition = and_(
            or_(*[func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in TIF_EXTENSIONS]),
            or_(WSISlide.file_size < SIZE_THRESHOLD, WSISlide.file_size.is_(None))
        )
        is_patch = or_(*patch_ext_conditions, tif_patch_condition)

        # Build user filter condition (own data OR elevated datasets)
        if user_id is not None:
            if elevated_dataset_ids:
                user_filter = or_(
                    WSISlide.user_id == user_id,
                    WSISlide.dataset_id.in_(elevated_dataset_ids)
                )
            else:
                user_filter = WSISlide.user_id == user_id
        else:
            user_filter = None

        # Single query for total count and data type distribution
        stats_query = select(
            func.count(WSISlide.id).label("total_count"),
            func.sum(case((is_wsi, 1), else_=0)).label("wsi_count"),
            func.sum(case((is_patch, 1), else_=0)).label("patch_count")
        )
        if user_filter is not None:
            stats_query = stats_query.where(user_filter)

        stats_result = await db.execute(stats_query)
        stats_row = stats_result.one()

        # Query for label distribution (simple GROUP BY)
        labels_query = select(WSISlide.label, func.count(WSISlide.id)).group_by(WSISlide.label)
        if user_filter is not None:
            labels_query = labels_query.where(user_filter)
        labels_result = await db.execute(labels_query)
        labels = {label: count for label, count in labels_result.all() if label}

        # Query for datasets (with join to Dataset table)
        # Include data_type (WSI/Patch) and labels per dataset
        from .models import Dataset

        # Build data_type case expressions
        is_wsi_case = case((is_wsi, 1), else_=0)
        is_patch_case = case((is_patch, 1), else_=0)

        datasets_query = select(
            Dataset.dataset_id,
            Dataset.name.label("dataset_name"),
            Dataset.user_id.label("dataset_owner_id"),
            func.count(WSISlide.id).label("file_count"),
            func.sum(is_wsi_case).label("wsi_count"),
            func.sum(is_patch_case).label("patch_count")
        ).select_from(WSISlide).outerjoin(Dataset, WSISlide.dataset_id == Dataset.dataset_id)

        if user_filter is not None:
            datasets_query = datasets_query.where(user_filter)

        datasets_query = datasets_query.group_by(Dataset.dataset_id, Dataset.name, Dataset.user_id).order_by(Dataset.name)
        datasets_result = await db.execute(datasets_query)

        # Get labels per dataset
        labels_per_dataset_query = select(
            Dataset.dataset_id,
            WSISlide.label,
            func.count(WSISlide.id).label("count")
        ).select_from(WSISlide).outerjoin(Dataset, WSISlide.dataset_id == Dataset.dataset_id)

        if user_filter is not None:
            labels_per_dataset_query = labels_per_dataset_query.where(user_filter)

        labels_per_dataset_query = labels_per_dataset_query.where(WSISlide.label.isnot(None))
        labels_per_dataset_query = labels_per_dataset_query.group_by(Dataset.dataset_id, WSISlide.label)
        labels_per_dataset_result = await db.execute(labels_per_dataset_query)

        # Build labels dict per dataset_id
        dataset_labels_map = {}
        for row in labels_per_dataset_result.all():
            ds_id = row.dataset_id
            if ds_id not in dataset_labels_map:
                dataset_labels_map[ds_id] = {}
            dataset_labels_map[ds_id][row.label] = row.count

        # Get survival data per dataset (count of records with event_time and event_status)
        survival_per_dataset_query = select(
            Dataset.dataset_id,
            func.count(WSISlide.id).label("survival_count")
        ).select_from(WSISlide).outerjoin(Dataset, WSISlide.dataset_id == Dataset.dataset_id)

        if user_filter is not None:
            survival_per_dataset_query = survival_per_dataset_query.where(user_filter)

        # Only count records that have both event_time and event_status
        survival_per_dataset_query = survival_per_dataset_query.where(
            and_(WSISlide.event_time.isnot(None), WSISlide.event_status.isnot(None))
        )
        survival_per_dataset_query = survival_per_dataset_query.group_by(Dataset.dataset_id)
        survival_per_dataset_result = await db.execute(survival_per_dataset_query)

        # Build survival count map per dataset_id
        dataset_survival_map = {}
        for row in survival_per_dataset_result.all():
            dataset_survival_map[row.dataset_id] = row.survival_count

        # Get split counts per dataset (train/val/test)
        splits_per_dataset_query = select(
            Dataset.dataset_id,
            func.sum(case(
                (func.lower(WSISlide.split) == 'train', 1),
                else_=0
            )).label("split_train_count"),
            func.sum(case(
                (or_(func.lower(WSISlide.split) == 'val', func.lower(WSISlide.split) == 'validation'), 1),
                else_=0
            )).label("split_val_count"),
            func.sum(case(
                (func.lower(WSISlide.split) == 'test', 1),
                else_=0
            )).label("split_test_count"),
        ).select_from(WSISlide).outerjoin(Dataset, WSISlide.dataset_id == Dataset.dataset_id)

        if user_filter is not None:
            splits_per_dataset_query = splits_per_dataset_query.where(user_filter)

        splits_per_dataset_query = splits_per_dataset_query.group_by(Dataset.dataset_id)
        splits_per_dataset_result = await db.execute(splits_per_dataset_query)

        # Build splits map per dataset_id
        dataset_splits_map = {}
        for row in splits_per_dataset_result.all():
            train_count = row.split_train_count or 0
            val_count = row.split_val_count or 0
            test_count = row.split_test_count or 0
            dataset_splits_map[row.dataset_id] = {
                "has_predefined_splits": train_count > 0,  # At least train split must exist
                "train": train_count,
                "val": val_count,
                "test": test_count
            }

        # Get event_status distribution per dataset (for survival prediction)
        event_status_per_dataset_query = select(
            Dataset.dataset_id,
            WSISlide.event_status,
            func.count(WSISlide.id).label("count")
        ).select_from(WSISlide).outerjoin(Dataset, WSISlide.dataset_id == Dataset.dataset_id)

        if user_filter is not None:
            event_status_per_dataset_query = event_status_per_dataset_query.where(user_filter)

        # Only count records that have both event_time and event_status
        event_status_per_dataset_query = event_status_per_dataset_query.where(
            and_(WSISlide.event_time.isnot(None), WSISlide.event_status.isnot(None))
        )
        event_status_per_dataset_query = event_status_per_dataset_query.group_by(Dataset.dataset_id, WSISlide.event_status)
        event_status_per_dataset_result = await db.execute(event_status_per_dataset_query)

        # Build event_status distribution map per dataset_id
        dataset_event_status_map = {}
        for row in event_status_per_dataset_result.all():
            ds_id = row.dataset_id
            if ds_id not in dataset_event_status_map:
                dataset_event_status_map[ds_id] = {}
            if row.event_status == 1:
                dataset_event_status_map[ds_id]['event'] = row.count
            elif row.event_status == 0:
                dataset_event_status_map[ds_id]['censored'] = row.count

        datasets = []
        for row in datasets_result.all():
            wsi_cnt = row.wsi_count or 0
            patch_cnt = row.patch_count or 0
            # Determine data_type based on file counts
            if wsi_cnt > 0 and patch_cnt == 0:
                data_type = "wsi"
            elif patch_cnt > 0 and wsi_cnt == 0:
                data_type = "patch"
            elif wsi_cnt > 0 and patch_cnt > 0:
                data_type = "mixed"
            else:
                data_type = "unknown"

            ds_labels = dataset_labels_map.get(row.dataset_id, {})
            survival_count = dataset_survival_map.get(row.dataset_id, 0)
            splits_info = dataset_splits_map.get(row.dataset_id, {"has_predefined_splits": False, "train": 0, "val": 0, "test": 0})
            event_status_dist = dataset_event_status_map.get(row.dataset_id, {})

            # Determine access_type: "own" if user owns it, "elevated" if via temporary permission
            elevated_set = set(elevated_dataset_ids) if elevated_dataset_ids else set()
            if user_id is not None and row.dataset_owner_id != user_id and row.dataset_id in elevated_set:
                access_type = "elevated"
            else:
                access_type = "own"

            datasets.append({
                "dataset_id": row.dataset_id,
                "dataset_name": row.dataset_name or "Uncategorized",
                "file_count": row.file_count,
                "data_type": data_type,
                "labels": ds_labels,
                "survival_count": survival_count,  # Number of records with survival data
                "event_status": event_status_dist,  # Distribution of event_status: {'event': count, 'censored': count}
                "has_predefined_splits": splits_info["has_predefined_splits"],
                "predefined_split_counts": {
                    "train": splits_info["train"],
                    "val": splits_info["val"],
                    "test": splits_info["test"]
                },
                "access_type": access_type  # "own" or "elevated"
            })

        return {
            "total_count": stats_row.total_count or 0,
            "data_types": {
                "wsi": stats_row.wsi_count or 0,
                "patch": stats_row.patch_count or 0
            },
            "labels": labels,
            "datasets": datasets
        }

    @staticmethod
    async def get_data_type_distribution(db: AsyncSession, user_id: Optional[str] = None) -> Dict[str, int]:
        """
        Get distribution of data types (WSI vs Patch).

        Args:
            db: Database session
            user_id: Optional user ID filter. If provided, only counts for WSI belonging to this user.
                     If None, counts all (for admin users).

        Returns:
            Dict with 'wsi' and 'patch' counts
        """
        from sqlalchemy import case, or_, and_

        # Build WSI condition
        wsi_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSI_EXTENSIONS]
        tif_wsi_condition = and_(
            or_(*[func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in TIF_EXTENSIONS]),
            WSISlide.file_size >= SIZE_THRESHOLD
        )
        is_wsi = or_(*wsi_ext_conditions, tif_wsi_condition)

        # Build Patch condition
        patch_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in PATCH_EXTENSIONS]
        tif_patch_condition = and_(
            or_(*[func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in TIF_EXTENSIONS]),
            or_(WSISlide.file_size < SIZE_THRESHOLD, WSISlide.file_size.is_(None))
        )
        is_patch = or_(*patch_ext_conditions, tif_patch_condition)

        # Count WSI and Patch
        query = select(
            func.sum(case((is_wsi, 1), else_=0)).label("wsi_count"),
            func.sum(case((is_patch, 1), else_=0)).label("patch_count")
        )

        if user_id is not None:
            query = query.where(WSISlide.user_id == user_id)

        result = await db.execute(query)
        row = result.one()

        return {
            "wsi": row.wsi_count or 0,
            "patch": row.patch_count or 0
        }

    @staticmethod
    async def get_datasets(
        db: AsyncSession,
        data_type: Optional[str] = None,
        user_id: Optional[str] = None,
        elevated_dataset_ids: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Get all datasets with file count, total size, and split statistics.

        Args:
            db: Database session
            data_type: Optional filter - "wsi" for WSI files, "patch" for image files
                       If None, returns all datasets
            user_id: Optional user ID filter. If provided, only returns datasets containing WSI belonging to this user.
                     If None, returns all datasets (for admin users).
            elevated_dataset_ids: Optional list of dataset IDs that the user has temporary elevated permissions for.
                                  These datasets will be included even if user doesn't own any WSI in them.

        Returns:
            List of dicts with dataset_id (UUID), name (display), file_count, total_size, group info,
            has_predefined_splits, and predefined_split_counts
        """
        from sqlalchemy import or_, and_, case

        # Build file type filter based on data_type
        if data_type == "wsi":
            wsi_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSI_EXTENSIONS]
            tif_conditions = [
                and_(
                    or_(
                        func.lower(WSISlide.wsi_path).like('%' + ext)
                        for ext in TIF_EXTENSIONS
                    ),
                    WSISlide.file_size >= SIZE_THRESHOLD
                )
            ]
            file_filter = or_(*wsi_ext_conditions, *tif_conditions)
        elif data_type == "patch":
            patch_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in PATCH_EXTENSIONS]
            tif_conditions = [
                and_(
                    or_(
                        func.lower(WSISlide.wsi_path).like('%' + ext)
                        for ext in TIF_EXTENSIONS
                    ),
                    or_(
                        WSISlide.file_size < SIZE_THRESHOLD,
                        WSISlide.file_size.is_(None)
                    )
                )
            ]
            file_filter = or_(*patch_ext_conditions, *tif_conditions)
        else:
            file_filter = None

        # Join with Dataset and DataGroup tables to get all info
        query = select(
            Dataset.dataset_id,
            Dataset.name.label("dataset_name"),
            Dataset.user_id.label("dataset_user_id"),
            Dataset.group_id,
            DataGroup.data_type,
            DataGroup.aggregation_level,
            DataGroup.task_type,
            func.count(WSISlide.id).label("file_count"),
            func.sum(WSISlide.file_size).label("total_size"),
            # Count splits - normalize 'validation' to 'val'
            func.sum(case(
                (func.lower(WSISlide.split) == 'train', 1),
                else_=0
            )).label("split_train_count"),
            func.sum(case(
                (or_(func.lower(WSISlide.split) == 'val', func.lower(WSISlide.split) == 'validation'), 1),
                else_=0
            )).label("split_val_count"),
            func.sum(case(
                (func.lower(WSISlide.split) == 'test', 1),
                else_=0
            )).label("split_test_count"),
        ).select_from(WSISlide).outerjoin(
            Dataset, WSISlide.dataset_id == Dataset.dataset_id
        ).outerjoin(
            DataGroup, Dataset.group_id == DataGroup.group_id
        )

        # Apply user_id filter with elevated_dataset_ids support
        # User can see: their own datasets OR datasets they have elevated permissions for
        if user_id is not None:
            if elevated_dataset_ids:
                # Include user's own data OR data from elevated permission datasets
                query = query.where(
                    or_(
                        WSISlide.user_id == user_id,
                        WSISlide.dataset_id.in_(elevated_dataset_ids)
                    )
                )
            else:
                query = query.where(WSISlide.user_id == user_id)

        if file_filter is not None:
            query = query.where(file_filter)

        query = query.group_by(
            Dataset.dataset_id, Dataset.name, Dataset.user_id, Dataset.group_id,
            DataGroup.data_type, DataGroup.aggregation_level, DataGroup.task_type
        ).order_by(Dataset.name)

        result = await db.execute(query)
        datasets = []
        for row in result.all():
            train_count = row.split_train_count or 0
            val_count = row.split_val_count or 0
            test_count = row.split_test_count or 0
            has_predefined_splits = train_count > 0  # At least train split must exist

            datasets.append({
                "dataset_id": row.dataset_id,  # UUID for API calls
                "dataset_name": row.dataset_name or "Uncategorized",  # Display name
                "user_id": row.dataset_user_id,  # Dataset owner
                "group_id": row.group_id,
                "data_type": row.data_type,  # wsi or patch (for frontend display)
                "data_level": row.aggregation_level,  # file or case (frontend expects data_level)
                "dataset_type": row.task_type or "classification",  # classification, survival (frontend expects dataset_type)
                "file_count": row.file_count,
                "total_size": row.total_size or 0,
                "has_predefined_splits": has_predefined_splits,
                "predefined_split_counts": {
                    "train": train_count,
                    "val": val_count,
                    "test": test_count
                }
            })
        return datasets

    @staticmethod
    async def get_by_dataset(
        db: AsyncSession,
        dataset_id: str,
        skip: int = 0,
        limit: int = 0,
        user_id: Optional[str] = None,
        data_type: Optional[str] = None,
        elevated_dataset_ids: Optional[List[str]] = None
    ) -> List[WSISlide]:
        """
        Get all WSI slides in a specific dataset with pagination.

        Args:
            db: Database session
            dataset_id: Dataset UUID to filter by (use "Uncategorized" for NULL dataset_id)
            skip: Number of records to skip
            limit: Maximum number of records to return (0 = all)
            user_id: Optional user ID filter. If provided, only returns WSI belonging to this user.
                     If None, returns all WSI in the dataset (for admin users).
            data_type: Optional filter - "wsi" for WSI files, "patch" for image files
            elevated_dataset_ids: Optional list of dataset IDs that the user has temporary elevated permissions for.
                                  If the requested dataset_id is in this list, user_id filter is bypassed.

        Returns:
            List of WSISlide objects with dataset relationship loaded
        """
        query = select(WSISlide).options(selectinload(WSISlide.dataset))

        if dataset_id == "Uncategorized":
            query = query.where(WSISlide.dataset_id.is_(None))
        else:
            query = query.where(WSISlide.dataset_id == dataset_id)

        # Apply user_id filter, but bypass if user has elevated permission for this dataset
        if user_id is not None:
            # Check if user has elevated permission for this specific dataset
            has_elevated_permission = elevated_dataset_ids and dataset_id in elevated_dataset_ids
            if not has_elevated_permission:
                # User doesn't have elevated permission, apply user_id filter
                query = query.where(WSISlide.user_id == user_id)
            # If has_elevated_permission is True, don't filter by user_id - show all files in dataset

        # Apply data_type filter
        data_type_filter = WSIRepository._build_data_type_filter(data_type)
        if data_type_filter is not None:
            query = query.where(data_type_filter)

        query = query.order_by(desc(WSISlide.created_at)).offset(skip)
        if limit > 0:
            query = query.limit(limit)

        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def count_by_dataset(
        db: AsyncSession,
        dataset_id: str,
        user_id: Optional[str] = None,
        data_type: Optional[str] = None,
        elevated_dataset_ids: Optional[List[str]] = None
    ) -> int:
        """
        Count WSI slides in a specific dataset.

        Args:
            db: Database session
            dataset_id: Dataset UUID to filter by (use "Uncategorized" for NULL dataset_id)
            user_id: Optional user ID filter. If provided, only counts WSI belonging to this user.
                     If None, counts all WSI in the dataset (for admin users).
            data_type: Optional filter - "wsi" for WSI files, "patch" for image files
            elevated_dataset_ids: Optional list of dataset IDs that the user has temporary elevated permissions for.
                                  If the requested dataset_id is in this list, user_id filter is bypassed.

        Returns:
            Number of WSI slides in the dataset
        """
        query = select(func.count(WSISlide.id))

        if dataset_id == "Uncategorized":
            query = query.where(WSISlide.dataset_id.is_(None))
        else:
            query = query.where(WSISlide.dataset_id == dataset_id)

        # Apply user_id filter, but bypass if user has elevated permission for this dataset
        if user_id is not None:
            # Check if user has elevated permission for this specific dataset
            has_elevated_permission = elevated_dataset_ids and dataset_id in elevated_dataset_ids
            if not has_elevated_permission:
                # User doesn't have elevated permission, apply user_id filter
                query = query.where(WSISlide.user_id == user_id)
            # If has_elevated_permission is True, don't filter by user_id - count all files in dataset

        # Apply data_type filter
        data_type_filter = WSIRepository._build_data_type_filter(data_type)
        if data_type_filter is not None:
            query = query.where(data_type_filter)

        result = await db.execute(query)
        return result.scalar_one()


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

        if status == TaskStatus.RUNNING and not await AITaskRepository._has_started(db, task_id):
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
            func.sum(case((AITask.status == TaskStatus.RUNNING, 1), else_=0)).label("running"),
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


class AIResultRepository:
    """Repository for AI Result operations"""

    @staticmethod
    async def create(db: AsyncSession, result_data: Dict) -> AIResult:
        """Create a new AI result"""
        result = AIResult(**result_data)
        db.add(result)
        await db.flush()
        await db.refresh(result)
        return result

    @staticmethod
    async def bulk_create(db: AsyncSession, results_data: List[Dict], batch_size: int = 100) -> int:
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
            batch = results_data[i:i + batch_size]
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
        result = await db.execute(
            select(AIResult).where(AIResult.task_id == task_id)
        )
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
        result = await db.execute(
            delete(AIResult).where(AIResult.task_id == task_id)
        )
        await db.flush()
        return result.rowcount


class ChatRepository:
    """Repository for Chat Conversation and Message operations"""

    @staticmethod
    async def create_conversation(db: AsyncSession, conversation_data: Dict) -> ChatConversation:
        """Create a new conversation"""
        conversation = ChatConversation(**conversation_data)
        db.add(conversation)
        await db.flush()
        await db.refresh(conversation)
        return conversation

    @staticmethod
    async def get_conversation(db: AsyncSession, conversation_id: str) -> Optional[ChatConversation]:
        """Get conversation by ID with messages"""
        result = await db.execute(
            select(ChatConversation)
            .where(ChatConversation.conversation_id == conversation_id)
            .options(selectinload(ChatConversation.messages))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_conversations(
        db: AsyncSession,
        user_id: str,
        skip: int = 0,
        limit: int = 50
    ) -> List[ChatConversation]:
        """Get all conversations for a user"""
        result = await db.execute(
            select(ChatConversation)
            .where(ChatConversation.user_id == user_id)
            .order_by(desc(ChatConversation.updated_at))
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def add_message(db: AsyncSession, message_data: Dict) -> ChatMessage:
        """Add a message to a conversation"""
        message = ChatMessage(**message_data)
        db.add(message)

        # Update conversation's updated_at timestamp
        await db.execute(
            update(ChatConversation)
            .where(ChatConversation.conversation_id == message_data["conversation_id"])
            .values(updated_at=utc_now())
        )

        await db.flush()
        await db.refresh(message)
        return message

    @staticmethod
    async def get_messages(
        db: AsyncSession,
        conversation_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[ChatMessage]:
        """Get messages for a conversation"""
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at)
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def update_message(
        db: AsyncSession,
        message_id: int,
        content: str
    ) -> Optional[ChatMessage]:
        """Update a message's content"""
        result = await db.execute(
            select(ChatMessage).where(ChatMessage.id == message_id)
        )
        message = result.scalar_one_or_none()
        if message:
            message.content = content
            await db.flush()
            await db.refresh(message)
        return message

    @staticmethod
    async def delete_messages_from_id(
        db: AsyncSession,
        conversation_id: str,
        message_id: int
    ) -> int:
        """
        Delete a message and all subsequent messages in a conversation.
        Used for conversation branching - delete from a point to start a new branch.

        Args:
            db: Database session
            conversation_id: Conversation ID
            message_id: The message ID from which to start deletion (inclusive)

        Returns:
            Number of deleted messages
        """
        # Get the message to find its created_at timestamp
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.id == message_id)
            .where(ChatMessage.conversation_id == conversation_id)
        )
        target_message = result.scalar_one_or_none()

        if not target_message:
            return 0

        # Delete all messages with id >= message_id in this conversation
        # (messages are ordered by id which corresponds to creation order)
        delete_result = await db.execute(
            delete(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .where(ChatMessage.id >= message_id)
        )

        await db.flush()
        return delete_result.rowcount

    @staticmethod
    async def delete_conversation(db: AsyncSession, conversation_id: str) -> bool:
        """Delete a conversation and all its messages"""
        # First delete all messages (due to foreign key constraint)
        await db.execute(
            delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
        )

        # Then delete the conversation
        result = await db.execute(
            delete(ChatConversation).where(ChatConversation.conversation_id == conversation_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def count_user_conversations(db: AsyncSession, user_id: str) -> int:
        """Count total conversations for a user"""
        result = await db.execute(
            select(func.count(ChatConversation.id))
            .where(ChatConversation.user_id == user_id)
        )
        return result.scalar()


class FeedbackRepository:
    """Repository for Message Feedback operations"""

    @staticmethod
    async def upsert_feedback(
        db: AsyncSession,
        message_id: int,
        user_id: str,
        feedback_type: Optional[str] = None,
        task_helpfulness: Optional[str] = None,
        related_task_id: Optional[str] = None,
        time_to_action_seconds: Optional[float] = None,
        message_content: Optional[str] = None,
        context_messages: Optional[List[dict]] = None,
        task_type: Optional[str] = None,
        task_title: Optional[str] = None
    ) -> MessageFeedback:
        """
        Create or update feedback for a message.
        Uses upsert logic: if feedback exists, update it; otherwise, create new.
        Preserves message content and task info for admin review even if conversation is deleted.
        """
        # Check if feedback already exists
        result = await db.execute(
            select(MessageFeedback)
            .where(MessageFeedback.message_id == message_id)
            .where(MessageFeedback.user_id == user_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing feedback
            if feedback_type is not None:
                existing.feedback_type = feedback_type
            if task_helpfulness is not None:
                existing.task_helpfulness = task_helpfulness
            if related_task_id is not None:
                existing.related_task_id = related_task_id
            if time_to_action_seconds is not None:
                existing.time_to_action_seconds = time_to_action_seconds
            if message_content is not None:
                existing.message_content = message_content
            if context_messages is not None:
                existing.context_messages = context_messages
            if task_type is not None:
                existing.task_type = task_type
            if task_title is not None:
                existing.task_title = task_title
            await db.flush()
            await db.refresh(existing)
            return existing
        else:
            # Create new feedback
            feedback = MessageFeedback(
                message_id=message_id,
                user_id=user_id,
                feedback_type=feedback_type,
                task_helpfulness=task_helpfulness,
                related_task_id=related_task_id,
                time_to_action_seconds=time_to_action_seconds,
                message_content=message_content,
                context_messages=context_messages,
                task_type=task_type,
                task_title=task_title
            )
            db.add(feedback)
            await db.flush()
            await db.refresh(feedback)
            return feedback

    @staticmethod
    async def get_feedback(
        db: AsyncSession,
        message_id: int,
        user_id: str
    ) -> Optional[MessageFeedback]:
        """Get feedback for a specific message and user"""
        result = await db.execute(
            select(MessageFeedback)
            .where(MessageFeedback.message_id == message_id)
            .where(MessageFeedback.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_feedbacks_for_conversation(
        db: AsyncSession,
        conversation_id: str,
        user_id: str
    ) -> List[MessageFeedback]:
        """Get all feedbacks for messages in a conversation"""
        result = await db.execute(
            select(MessageFeedback)
            .join(ChatMessage, MessageFeedback.message_id == ChatMessage.id)
            .where(ChatMessage.conversation_id == conversation_id)
            .where(MessageFeedback.user_id == user_id)
        )
        return result.scalars().all()

    @staticmethod
    async def delete_feedback(
        db: AsyncSession,
        message_id: int,
        user_id: str
    ) -> bool:
        """Delete feedback for a message"""
        result = await db.execute(
            delete(MessageFeedback)
            .where(MessageFeedback.message_id == message_id)
            .where(MessageFeedback.user_id == user_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def get_all_feedbacks(
        db: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        feedback_type_filter: Optional[str] = None,
        helpfulness_filter: Optional[str] = None,
        user_id_filter: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> tuple[List[dict], int]:
        """
        Get all feedbacks with pagination and filtering (admin only).
        Returns tuple of (feedbacks list with username, total count).
        """
        from backend.auth.models import User as AuthUser
        from sqlalchemy import cast, String

        # Build base query - join with User table to get username
        # Note: user_id in MessageFeedback is stored as string, User.id is UUID
        query = (
            select(MessageFeedback, AuthUser.email, AuthUser.nickname)
            .outerjoin(AuthUser, MessageFeedback.user_id == cast(AuthUser.id, String))
            .options(selectinload(MessageFeedback.message))
        )

        # Apply filters
        if feedback_type_filter:
            query = query.where(MessageFeedback.feedback_type == feedback_type_filter)
        if helpfulness_filter:
            query = query.where(MessageFeedback.task_helpfulness == helpfulness_filter)
        if user_id_filter:
            query = query.where(MessageFeedback.user_id == user_id_filter)
        if date_from:
            query = query.where(MessageFeedback.created_at >= date_from)
        if date_to:
            query = query.where(MessageFeedback.created_at <= date_to)

        # Get total count (only count MessageFeedback rows)
        count_subquery = select(MessageFeedback.id)
        if feedback_type_filter:
            count_subquery = count_subquery.where(MessageFeedback.feedback_type == feedback_type_filter)
        if helpfulness_filter:
            count_subquery = count_subquery.where(MessageFeedback.task_helpfulness == helpfulness_filter)
        if user_id_filter:
            count_subquery = count_subquery.where(MessageFeedback.user_id == user_id_filter)
        if date_from:
            count_subquery = count_subquery.where(MessageFeedback.created_at >= date_from)
        if date_to:
            count_subquery = count_subquery.where(MessageFeedback.created_at <= date_to)
        count_query = select(func.count()).select_from(count_subquery.subquery())
        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        # Apply pagination and ordering
        query = query.order_by(desc(MessageFeedback.created_at)).offset(skip).limit(limit)

        result = await db.execute(query)
        rows = result.all()

        # Convert to dict with username
        feedbacks_with_username = []
        for row in rows:
            feedback = row[0]  # MessageFeedback object
            email = row[1]  # User.email (username)
            nickname = row[2]  # User.nickname

            feedback_dict = feedback.to_dict()
            # Use nickname if available, otherwise use email (username)
            feedback_dict["username"] = nickname or email or None
            feedbacks_with_username.append(feedback_dict)

        return feedbacks_with_username, total

    @staticmethod
    async def get_feedback_stats(db: AsyncSession) -> Dict:
        """
        Get feedback statistics (admin only).
        Returns counts of different feedback types and helpfulness ratings.
        """
        # Total count
        total_result = await db.execute(select(func.count(MessageFeedback.id)))
        total = total_result.scalar() or 0

        # Thumbs up count
        thumbs_up_result = await db.execute(
            select(func.count(MessageFeedback.id))
            .where(MessageFeedback.feedback_type == 'thumbs_up')
        )
        thumbs_up = thumbs_up_result.scalar() or 0

        # Thumbs down count
        thumbs_down_result = await db.execute(
            select(func.count(MessageFeedback.id))
            .where(MessageFeedback.feedback_type == 'thumbs_down')
        )
        thumbs_down = thumbs_down_result.scalar() or 0

        # Helpful count
        helpful_result = await db.execute(
            select(func.count(MessageFeedback.id))
            .where(MessageFeedback.task_helpfulness == 'helpful')
        )
        helpful = helpful_result.scalar() or 0

        # Not helpful count
        not_helpful_result = await db.execute(
            select(func.count(MessageFeedback.id))
            .where(MessageFeedback.task_helpfulness == 'not_helpful')
        )
        not_helpful = not_helpful_result.scalar() or 0

        # Unique users count
        unique_users_result = await db.execute(
            select(func.count(func.distinct(MessageFeedback.user_id)))
        )
        unique_users = unique_users_result.scalar() or 0

        # Average time to action (only for records with time data)
        avg_time_result = await db.execute(
            select(func.avg(MessageFeedback.time_to_action_seconds))
            .where(MessageFeedback.time_to_action_seconds.isnot(None))
        )
        avg_time = avg_time_result.scalar()
        avg_time_to_action = round(avg_time, 1) if avg_time else None

        return {
            "total_feedbacks": total,
            "thumbs_up_count": thumbs_up,
            "thumbs_down_count": thumbs_down,
            "helpful_count": helpful,
            "not_helpful_count": not_helpful,
            "unique_users": unique_users,
            "avg_time_to_action_seconds": avg_time_to_action
        }

    @staticmethod
    async def delete_all_feedbacks(db: AsyncSession, batch_size: int = 1000) -> int:
        """
        Delete all feedbacks in batches (admin only).
        Uses batch deletion to handle large datasets efficiently.
        Returns the number of deleted records.
        """
        total_deleted = 0

        while True:
            # Get batch of IDs to delete
            result = await db.execute(
                select(MessageFeedback.id).limit(batch_size)
            )
            ids_to_delete = [row[0] for row in result.fetchall()]

            if not ids_to_delete:
                break

            # Delete this batch
            await db.execute(
                delete(MessageFeedback).where(MessageFeedback.id.in_(ids_to_delete))
            )
            await db.commit()
            total_deleted += len(ids_to_delete)

            # If we got fewer than batch_size, we're done
            if len(ids_to_delete) < batch_size:
                break

        return total_deleted

    @staticmethod
    async def get_feedbacks_count(
        db: AsyncSession,
        feedback_type_filter: Optional[str] = None,
        helpfulness_filter: Optional[str] = None,
        user_id_filter: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> int:
        """
        Get total count of feedbacks matching filters.
        Used for export progress tracking.
        """
        query = select(func.count(MessageFeedback.id))

        if feedback_type_filter:
            query = query.where(MessageFeedback.feedback_type == feedback_type_filter)
        if helpfulness_filter:
            query = query.where(MessageFeedback.task_helpfulness == helpfulness_filter)
        if user_id_filter:
            query = query.where(MessageFeedback.user_id == user_id_filter)
        if date_from:
            query = query.where(MessageFeedback.created_at >= date_from)
        if date_to:
            query = query.where(MessageFeedback.created_at <= date_to)

        result = await db.execute(query)
        return result.scalar() or 0

    @staticmethod
    async def get_feedbacks_batch(
        db: AsyncSession,
        offset: int,
        limit: int,
        feedback_type_filter: Optional[str] = None,
        helpfulness_filter: Optional[str] = None,
        user_id_filter: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> List[MessageFeedback]:
        """
        Get a batch of feedbacks for streaming export.
        Returns feedbacks without the total count for efficiency.
        """
        query = select(MessageFeedback).options(selectinload(MessageFeedback.message))

        if feedback_type_filter:
            query = query.where(MessageFeedback.feedback_type == feedback_type_filter)
        if helpfulness_filter:
            query = query.where(MessageFeedback.task_helpfulness == helpfulness_filter)
        if user_id_filter:
            query = query.where(MessageFeedback.user_id == user_id_filter)
        if date_from:
            query = query.where(MessageFeedback.created_at >= date_from)
        if date_to:
            query = query.where(MessageFeedback.created_at <= date_to)

        query = query.order_by(MessageFeedback.id).offset(offset).limit(limit)

        result = await db.execute(query)
        return result.scalars().all()


class ExportTaskRepository:
    """Repository for Export Task operations"""

    @staticmethod
    async def create(
        db: AsyncSession,
        task_id: str,
        user_id: str,
        export_type: str,
        file_format: str,
        filter_params: Optional[Dict] = None
    ) -> ExportTask:
        """Create a new export task"""
        task = ExportTask(
            task_id=task_id,
            user_id=user_id,
            export_type=export_type,
            file_format=file_format,
            filter_params=filter_params,
            status='pending'
        )
        db.add(task)
        await db.flush()
        await db.refresh(task)
        return task

    @staticmethod
    async def get_by_id(db: AsyncSession, task_id: str) -> Optional[ExportTask]:
        """Get export task by ID"""
        result = await db.execute(
            select(ExportTask).where(ExportTask.task_id == task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_status(
        db: AsyncSession,
        task_id: str,
        status: str,
        progress: int = None,
        error_message: str = None,
        file_path: str = None,
        total_records: int = None
    ) -> bool:
        """Update export task status"""
        update_data = {"status": status}

        if progress is not None:
            update_data["progress"] = progress
        if error_message is not None:
            update_data["error_message"] = error_message
        if file_path is not None:
            update_data["file_path"] = file_path
        if total_records is not None:
            update_data["total_records"] = total_records

        if status == 'processing' and 'started_at' not in update_data:
            update_data["started_at"] = utc_now()
        if status in ('completed', 'failed'):
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
        """Delete export tasks older than specified days"""
        from datetime import timedelta
        cutoff = utc_now() - timedelta(days=days)

        result = await db.execute(
            delete(ExportTask).where(ExportTask.created_at < cutoff)
        )
        return result.rowcount


class TrainingTaskRepository:
    """Repository for Training Task operations"""

    @staticmethod
    async def create(
        db: AsyncSession,
        task_data: Dict,
        wsi_ids: List[str],
        split_config: Optional[Dict] = None,
        prefetched_wsis: Optional[List] = None
    ) -> TrainingTask:
        """
        Create a new training task with associated WSI slides.
        Automatically extracts classes from WSI labels.

        For large datasets (10k+ WSIs), uses bulk inserts to avoid SQLite issues.

        Args:
            prefetched_wsis: Optional list of already-fetched WSISlide objects.
                             If provided, skips redundant DB query for WSI data.
        """
        # Use pre-fetched WSIs if available, otherwise query from DB
        if prefetched_wsis is not None:
            wsis = prefetched_wsis
        else:
            # Extract unique classes from WSI labels
            # For large datasets, query in batches to avoid SQLite limitations
            wsis = []
            batch_size = 500  # SQLite variable limit is 999, stay well below
            for i in range(0, len(wsi_ids), batch_size):
                batch_ids = wsi_ids[i:i + batch_size]
                wsi_list = await db.execute(
                    select(WSISlide).where(WSISlide.wsi_id.in_(batch_ids))
                )
                wsis.extend(wsi_list.scalars().all())

        # Get unique labels (classes)
        classes = sorted(list(set(wsi.label for wsi in wsis if wsi.label)))

        # Validate task based on task_type
        task_type = task_data.get("task_type", "classification")

        if task_type == "classification":
            # Classification tasks require at least 2 classes
            if len(classes) < 2:
                raise ValueError(
                    f"Classification tasks require at least 2 different classes. "
                    f"Found {len(classes)} class(es): {classes}. "
                    f"Please assign different labels to your slides."
                )
        elif task_type == "survival_prediction":
            # Survival prediction tasks require both event (status=1) and censored (status=0) samples
            event_statuses = set(wsi.event_status for wsi in wsis if wsi.event_status is not None and wsi.event_time is not None)
            if len(event_statuses) < 2:
                event_count = sum(1 for wsi in wsis if wsi.event_status == 1 and wsi.event_time is not None)
                censored_count = sum(1 for wsi in wsis if wsi.event_status == 0 and wsi.event_time is not None)
                missing_type = "Event (status=1)" if event_count == 0 else "Censored (status=0)"
                raise ValueError(
                    f"Survival prediction tasks require both Event and Censored samples. "
                    f"{missing_type} has 0 samples. "
                    f"Current distribution: Event={event_count}, Censored={censored_count}. "
                    f"Please ensure your data has both event types."
                )

        # Add split_config to preprocessing_config for persistence
        if split_config:
            preprocessing_config = task_data.get("preprocessing_config", {}) or {}
            preprocessing_config["split_config"] = split_config
            task_data["preprocessing_config"] = preprocessing_config

        # Remove task_type from task_data before creating TrainingTask
        # (task_type is stored in the associated DataGroup, not in TrainingTask directly)
        task_data_cleaned = {k: v for k, v in task_data.items() if k != "task_type"}

        # Create training task
        task = TrainingTask(
            **task_data_cleaned,
            classes=classes,
            status=TaskStatus.PENDING,
            progress=0
        )
        db.add(task)
        await db.flush()
        await db.refresh(task)

        # Calculate splits
        wsi_splits = {}
        if split_config:
            strategy = split_config.get("strategy", "random")

            if strategy == "manual":
                # For manual strategy, read splits directly from WSI records in database
                # This is more reliable than depending on frontend state which may be stale
                wsi_split_map = {wsi.wsi_id: wsi.split for wsi in wsis if wsi.split}
                wsi_splits = wsi_split_map
            else:
                # Check if dataset is case-level by looking at the first WSI's dataset via DataGroup
                # For case-level datasets, we must split by case_id to prevent data leakage
                is_case_level = False
                task_type_from_group = None
                if wsis:
                    # Get dataset's DataGroup to check aggregation_level and task_type
                    first_dataset_id = wsis[0].dataset_id
                    if first_dataset_id:
                        group_result = await db.execute(
                            select(DataGroup.aggregation_level, DataGroup.task_type)
                            .join(Dataset, Dataset.group_id == DataGroup.group_id)
                            .where(Dataset.dataset_id == first_dataset_id)
                        )
                        group_row = group_result.first()
                        if group_row:
                            is_case_level = (group_row[0] == "case")
                            task_type_from_group = group_row[1]

                # Determine if this is a survival task from DataGroup
                is_survival = (task_type_from_group == "survival")

                if is_case_level:
                    # Build case_id_map and case-level labels
                    case_id_map: Dict[str, str] = {}
                    case_labels: Dict[str, str] = {}
                    for wsi in wsis:
                        case_id = wsi.case_id if wsi.case_id else wsi.wsi_id
                        case_id_map[wsi.wsi_id] = case_id

                        # Determine label for stratification
                        label_val = None
                        if is_survival:
                            if wsi.event_status is not None:
                                label_val = str(wsi.event_status)
                        else:
                            label_val = wsi.label

                        # Use the first WSI's label for each case (they should be the same)
                        if label_val and case_id not in case_labels:
                            case_labels[case_id] = label_val

                    # Use case-level split to prevent data leakage
                    # Labels are keyed by case_id for stratification
                    split_config_copy = {**split_config}
                    if "labels" in split_config_copy:
                        del split_config_copy["labels"]  # We'll use case_labels instead
                    wsi_splits = split_case_dataset(
                        wsi_ids, case_id_map, labels=case_labels, **split_config_copy
                    )
                else:
                    # For slide-level datasets, use regular splitter
                    # Build labels dict for stratified splitting
                    wsi_labels: Dict[str, str] = {}

                    for wsi in wsis:
                        label_val = None
                        if is_survival:
                            if wsi.event_status is not None:
                                label_val = str(wsi.event_status)
                        else:
                            label_val = wsi.label

                        if label_val:
                            wsi_labels[wsi.wsi_id] = label_val
                    wsi_splits = split_wsi_dataset(wsi_ids, labels=wsi_labels, **split_config)

        # Use bulk insert to avoid ORM identity map issues and improve performance
        # This is much faster and more reliable for large datasets
        insert_batch_size = 1000
        for i in range(0, len(wsi_ids), insert_batch_size):
            batch_wsi_ids = wsi_ids[i:i + insert_batch_size]

            # Build list of records to insert
            records = []
            for wsi_id in batch_wsi_ids:
                split = wsi_splits.get(wsi_id, "train")
                records.append({
                    "task_id": task.task_id,
                    "wsi_id": wsi_id,
                    "split": split,
                    "created_at": utc_now()
                })

            # Bulk insert using Core API (bypasses ORM identity map)
            if records:
                await db.execute(insert(TrainingTaskWSI), records)

        # Single commit for task + all WSI associations (avoids multiple write lock acquisitions)
        await db.commit()

        # Re-fetch task with data_group relationship loaded to avoid lazy loading issues
        # This is necessary because to_dict() accesses data_group attributes
        result = await db.execute(
            select(TrainingTask)
            .options(selectinload(TrainingTask.data_group))
            .where(TrainingTask.task_id == task.task_id)
        )
        return result.scalar_one()

    @staticmethod
    async def get_by_id(db: AsyncSession, task_id: str) -> Optional[TrainingTask]:
        """Get training task by task_id with data_group relationship loaded"""
        result = await db.execute(
            select(TrainingTask)
            .options(selectinload(TrainingTask.data_group))
            .where(TrainingTask.task_id == task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_ids(db: AsyncSession, task_ids: List[str]) -> Dict[str, TrainingTask]:
        """Get multiple training tasks by IDs in a single query (batch operation).

        Returns:
            Dict mapping task_id to TrainingTask for found tasks
        """
        if not task_ids:
            return {}
        result = await db.execute(
            select(TrainingTask)
            .options(selectinload(TrainingTask.data_group))
            .where(TrainingTask.task_id.in_(task_ids))
        )
        tasks = result.scalars().all()
        return {task.task_id: task for task in tasks}

    @staticmethod
    async def get_all(db: AsyncSession, limit: int = 100, offset: int = 0, user_id: Optional[str] = None) -> List[TrainingTask]:
        """Get all training tasks with data_group relationship loaded.

        Args:
            db: Database session
            limit: Maximum number of records to return
            offset: Number of records to skip
            user_id: Optional user ID filter. If provided, only returns tasks belonging to this user.
                     If None, returns all tasks (for admin users).
        """
        query = select(TrainingTask).options(selectinload(TrainingTask.data_group))
        if user_id is not None:
            query = query.where(TrainingTask.user_id == user_id)
        query = query.order_by(desc(TrainingTask.created_at)).limit(limit).offset(offset)
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def count(db: AsyncSession, user_id: Optional[str] = None) -> int:
        """Count total training tasks.

        Args:
            db: Database session
            user_id: Optional user ID filter. If provided, only counts tasks belonging to this user.
                     If None, counts all tasks (for admin users).
        """
        query = select(func.count(TrainingTask.id))
        if user_id is not None:
            query = query.where(TrainingTask.user_id == user_id)
        result = await db.execute(query)
        return result.scalar()

    @staticmethod
    async def get_status_counts(db: AsyncSession, user_id: Optional[str] = None) -> Dict[str, int]:
        """Get counts of training tasks by status.

        Args:
            db: Database session
            user_id: Optional user ID filter. If provided, only counts tasks belonging to this user.

        Returns:
            Dict with keys: total, completed, running, failed, pending
            Note: "running" includes all in-progress statuses: running, training, pending, queued, preprocessing, extracting
        """
        from sqlalchemy import case, or_

        # Define in-progress statuses (tasks that are actively running or waiting to run)
        in_progress_statuses = [
            TaskStatus.RUNNING, TaskStatus.TRAINING, TaskStatus.PENDING,
            TaskStatus.QUEUED, TaskStatus.PREPROCESSING, TaskStatus.EXTRACTING,
        ]

        query = select(
            func.count(TrainingTask.id).label("total"),
            func.sum(case((TrainingTask.status == TaskStatus.COMPLETED, 1), else_=0)).label("completed"),
            func.sum(case((TrainingTask.status.in_(in_progress_statuses), 1), else_=0)).label("running"),
            func.sum(case((TrainingTask.status == TaskStatus.FAILED, 1), else_=0)).label("failed"),
        )
        if user_id is not None:
            query = query.where(TrainingTask.user_id == user_id)
        result = await db.execute(query)
        row = result.one()
        return {
            "total": row.total or 0,
            "completed": row.completed or 0,
            "running": row.running or 0,
            "failed": row.failed or 0,
        }

    @staticmethod
    async def get_wsi_ids(db: AsyncSession, task_id: str) -> List[str]:
        """Get all WSI IDs associated with a training task"""
        result = await db.execute(
            select(TrainingTaskWSI.wsi_id)
            .where(TrainingTaskWSI.task_id == task_id)
        )
        return [row[0] for row in result.all()]

    @staticmethod
    async def get_wsi_counts_batch(db: AsyncSession, task_ids: List[str]) -> Dict[str, int]:
        """
        Get WSI count for multiple tasks in a single query (batch operation).

        This is optimized for listing tasks - avoids N+1 query problem.

        Args:
            db: Database session
            task_ids: List of task IDs to get WSI counts for

        Returns:
            Dict mapping task_id to WSI count. Tasks with no WSI will have count 0.
        """
        if not task_ids:
            return {}
        result = await db.execute(
            select(
                TrainingTaskWSI.task_id,
                func.count(TrainingTaskWSI.wsi_id).label("wsi_count")
            )
            .where(TrainingTaskWSI.task_id.in_(task_ids))
            .group_by(TrainingTaskWSI.task_id)
        )
        counts = {row.task_id: row.wsi_count for row in result.all()}
        # Ensure all requested task_ids have a count (default 0)
        return {task_id: counts.get(task_id, 0) for task_id in task_ids}

    @staticmethod
    async def get_wsi_with_labels(db: AsyncSession, task_id: str) -> List[Dict]:
        """
        Get all WSI slides associated with a training task, including their labels and splits.

        Returns:
            List of dicts with keys: wsi_id, wsi_path, label, split
        """
        result = await db.execute(
            select(
                WSISlide.wsi_id,
                WSISlide.wsi_path,
                WSISlide.label,
                TrainingTaskWSI.split
            )
            .join(TrainingTaskWSI, WSISlide.wsi_id == TrainingTaskWSI.wsi_id)
            .where(TrainingTaskWSI.task_id == task_id)
        )
        return [
            {
                "wsi_id": row[0],
                "wsi_path": row[1],
                "label": row[2],
                "split": row[3]
            }
            for row in result.all()
        ]

    @staticmethod
    async def get_wsi_ids_by_split(db: AsyncSession, task_id: str) -> Dict[str, List[str]]:
        """
        Get WSI IDs grouped by their split assignment.

        Returns:
            Dict with split names as keys and lists of wsi_ids as values.
            For regular splits: {'train': [...], 'val': [...], 'test': [...]}
            For k-fold: {'fold_0': [...], 'fold_1': [...], ...}
        """
        result = await db.execute(
            select(TrainingTaskWSI.wsi_id, TrainingTaskWSI.split)
            .where(TrainingTaskWSI.task_id == task_id)
        )

        splits_map: Dict[str, List[str]] = {}
        for row in result.all():
            wsi_id, split = row[0], row[1]
            if split not in splits_map:
                splits_map[split] = []
            splits_map[split].append(wsi_id)

        return splits_map

    @staticmethod
    async def get_wsi_case_ids(db: AsyncSession, task_id: str) -> Dict[str, str]:
        """
        Get case_id for all WSI slides in a training task.

        Returns:
            Dict mapping wsi_id to case_id. If case_id is None, uses wsi_id as fallback.
        """
        result = await db.execute(
            select(WSISlide.wsi_id, WSISlide.case_id)
            .join(TrainingTaskWSI, WSISlide.wsi_id == TrainingTaskWSI.wsi_id)
            .where(TrainingTaskWSI.task_id == task_id)
        )

        case_id_map: Dict[str, str] = {}
        for row in result.all():
            wsi_id, case_id = row[0], row[1]
            # Use wsi_id as fallback if case_id is None
            case_id_map[wsi_id] = case_id if case_id else wsi_id

        return case_id_map

    @staticmethod
    async def get_dataset_aggregation_level(db: AsyncSession, task_id: str) -> Optional[str]:
        """
        Get the aggregation_level of the dataset associated with a training task via DataGroup.

        For training tasks involving multiple datasets, returns the first dataset's aggregation_level.
        This assumes all datasets in a training task have the same aggregation_level.

        Returns:
            'case' or 'file', or None if no dataset found.
        """
        # Get one WSI from the task and find its dataset's DataGroup
        result = await db.execute(
            select(DataGroup.aggregation_level)
            .join(Dataset, Dataset.group_id == DataGroup.group_id)
            .join(WSISlide, Dataset.dataset_id == WSISlide.dataset_id)
            .join(TrainingTaskWSI, WSISlide.wsi_id == TrainingTaskWSI.wsi_id)
            .where(TrainingTaskWSI.task_id == task_id)
            .limit(1)
        )
        row = result.first()
        return row[0] if row else None

    @staticmethod
    async def update_status(
        db: AsyncSession,
        task_id: str,
        status: str,
        progress: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> Optional[TrainingTask]:
        """Update training task status"""
        update_data = {"status": status}

        if progress is not None:
            update_data["progress"] = progress

        if error_message is not None:
            update_data["error_message"] = error_message

        if status == TaskStatus.RUNNING:
            update_data["started_at"] = utc_now()

        if status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            update_data["finished_at"] = utc_now()
            if status == TaskStatus.COMPLETED:
                update_data["progress"] = 100

        await db.execute(
            update(TrainingTask)
            .where(TrainingTask.task_id == task_id)
            .values(**update_data)
        )
        await db.flush()
        return await TrainingTaskRepository.get_by_id(db, task_id)

    # Status values that indicate a task was interrupted (not failed normally)
    # - 'pending': task was queued but not yet started (queue is in-memory, lost on restart)
    # - 'running', 'extracting', 'training': task was actively processing
    INTERRUPTED_STATUSES = [TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.EXTRACTING, TaskStatus.TRAINING]

    @staticmethod
    async def get_interrupted_tasks(db: AsyncSession) -> List[TrainingTask]:
        """
        Get all training tasks that were interrupted (e.g., by system shutdown).

        These are tasks with status 'pending', 'running', 'extracting', or 'training' -
        states that indicate the task was queued or in progress but never completed or failed.
        If the system restarts and a task has one of these statuses, it was interrupted.

        Note: 'failed' tasks are NOT considered interrupted - they failed normally.
        Note: 'pending' tasks are included because the in-memory queue is lost on restart.
        """
        result = await db.execute(
            select(TrainingTask)
            .options(selectinload(TrainingTask.data_group))  # Eagerly load data_group for resume
            .where(TrainingTask.status.in_(TrainingTaskRepository.INTERRUPTED_STATUSES))
            .order_by(TrainingTask.created_at)
        )
        return result.scalars().all()

    @staticmethod
    async def try_claim_for_resume(db: AsyncSession, task_id: str) -> bool:
        """
        Atomically try to claim a task for resume using compare-and-swap.

        This method is safe for multi-instance deployments. Only one instance
        can successfully claim a task because:
        1. The UPDATE uses WHERE status IN (interrupted_statuses)
        2. Only rows matching the condition are updated
        3. If another instance already claimed it (changed status to 'resuming'),
           this UPDATE will affect 0 rows

        The task is set to 'resuming' status temporarily. The pipeline will
        update it to 'running' when it starts.

        Returns:
            True if this instance successfully claimed the task
            False if another instance already claimed it or task not found
        """
        result = await db.execute(
            update(TrainingTask)
            .where(TrainingTask.task_id == task_id)
            .where(TrainingTask.status.in_(TrainingTaskRepository.INTERRUPTED_STATUSES))
            .values(
                status='resuming',  # Temporary until pipeline starts (different from 'pending' for CAS)
                progress=0,
                error_message=None,  # Clear previous error if any
                updated_at=utc_now()
            )
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def delete(db: AsyncSession, task_id: str) -> bool:
        """Delete a training task and all associated records"""
        # First check if task exists
        task = await TrainingTaskRepository.get_by_id(db, task_id)
        if not task:
            return False

        # Delete associated WSI records (should cascade automatically, but being explicit)
        await db.execute(
            delete(TrainingTaskWSI).where(TrainingTaskWSI.task_id == task_id)
        )

        # Delete associated trained models (should cascade automatically, but being explicit)
        await db.execute(
            delete(TrainedModel).where(TrainedModel.task_id == task_id)
        )

        # Delete the training task itself
        result = await db.execute(
            delete(TrainingTask).where(TrainingTask.task_id == task_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def cleanup_old_finished_tasks(db: AsyncSession, days: int = 7) -> int:
        """
        Delete old finished training tasks (completed, failed, cancelled) older than specified days.

        This helps clean up "zombie" tasks that accumulate over time.
        Only deletes tasks that have finished (not pending/running tasks).

        Note: This will cascade delete associated TrainingTaskWSI and TrainedModel records.

        Args:
            db: Database session
            days: Number of days to keep finished tasks (default: 7)

        Returns:
            Number of deleted tasks
        """
        from datetime import timedelta
        cutoff = utc_now() - timedelta(days=days)

        # Only delete finished tasks (completed, failed, cancelled) older than cutoff
        finished_statuses = ['completed', 'failed', 'cancelled']

        # First get task_ids to delete (for cascade cleanup)
        result = await db.execute(
            select(TrainingTask.task_id).where(
                TrainingTask.status.in_(finished_statuses),
                TrainingTask.finished_at < cutoff
            )
        )
        task_ids_to_delete = [row[0] for row in result.all()]

        if not task_ids_to_delete:
            return 0

        # Delete associated WSI records
        await db.execute(
            delete(TrainingTaskWSI).where(TrainingTaskWSI.task_id.in_(task_ids_to_delete))
        )

        # Delete associated trained models
        await db.execute(
            delete(TrainedModel).where(TrainedModel.task_id.in_(task_ids_to_delete))
        )

        # Delete training logs
        await db.execute(
            delete(TrainingLog).where(TrainingLog.task_id.in_(task_ids_to_delete))
        )

        # Delete the training tasks
        result = await db.execute(
            delete(TrainingTask).where(TrainingTask.task_id.in_(task_ids_to_delete))
        )

        await db.flush()
        return result.rowcount


class TrainedModelRepository:
    """Repository for Trained Model operations"""

    @staticmethod
    async def create(db: AsyncSession, model_data: Dict) -> TrainedModel:
        """Create a new trained model"""
        model = TrainedModel(**model_data)
        db.add(model)
        await db.flush()
        await db.refresh(model)
        return model

    @staticmethod
    async def get_by_id(db: AsyncSession, model_id: str) -> Optional[TrainedModel]:
        """Get trained model by model_id"""
        result = await db.execute(
            select(TrainedModel).where(TrainedModel.model_id == model_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_task_id(db: AsyncSession, task_id: str) -> List[TrainedModel]:
        """Get all models from a training task"""
        result = await db.execute(
            select(TrainedModel)
            .where(TrainedModel.task_id == task_id)
            .order_by(desc(TrainedModel.created_at))
        )
        return result.scalars().all()

    @staticmethod
    async def get_all(db: AsyncSession, limit: int = 100, offset: int = 0, user_id: Optional[str] = None) -> List[TrainedModel]:
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
        query = query.order_by(desc(TrainedModel.created_at)).limit(limit).offset(offset)
        result = await db.execute(query)
        return result.scalars().all()

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
        return result.scalar()

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
        return result.scalars().all()

    @staticmethod
    async def set_default(db: AsyncSession, model_id: str) -> Optional[TrainedModel]:
        """Set a model as default (unset all others)"""
        # First, unset all default flags
        await db.execute(
            update(TrainedModel).values(is_default=False)
        )

        # Then set the specified model as default
        await db.execute(
            update(TrainedModel)
            .where(TrainedModel.model_id == model_id)
            .values(is_default=True, is_active=True)
        )
        await db.flush()
        return await TrainedModelRepository.get_by_id(db, model_id)

    @staticmethod
    async def set_active(db: AsyncSession, model_id: str, is_active: bool) -> Optional[TrainedModel]:
        """Activate or deactivate a model"""
        await db.execute(
            update(TrainedModel)
            .where(TrainedModel.model_id == model_id)
            .values(is_active=is_active)
        )
        await db.flush()
        return await TrainedModelRepository.get_by_id(db, model_id)


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


class DatasetPermissionRepository:
    """Repository for Dataset Permission operations (temporary elevated access)"""

    @staticmethod
    async def create(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
        granted_by: str,
        permission_level: str = "pathologist",
        expires_at: datetime = None
    ) -> DatasetPermission:
        """
        Grant temporary elevated permission to a user for a specific dataset.

        Args:
            db: Database session
            dataset_id: Dataset UUID
            user_id: User UUID to grant permission to
            granted_by: Admin user UUID who granted the permission
            permission_level: Permission level (default: "pathologist")
            expires_at: Optional expiration time
        """
        permission = DatasetPermission(
            dataset_id=dataset_id,
            user_id=user_id,
            granted_by=granted_by,
            permission_level=permission_level,
            expires_at=expires_at
        )
        db.add(permission)
        await db.flush()
        await db.refresh(permission)
        return permission

    @staticmethod
    async def get_by_id(db: AsyncSession, permission_id: int) -> Optional[DatasetPermission]:
        """Get permission by ID"""
        result = await db.execute(
            select(DatasetPermission).where(DatasetPermission.id == permission_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_dataset_and_user(
        db: AsyncSession,
        dataset_id: str,
        user_id: str
    ) -> Optional[DatasetPermission]:
        """Get permission for a specific user on a specific dataset"""
        result = await db.execute(
            select(DatasetPermission)
            .where(DatasetPermission.dataset_id == dataset_id)
            .where(DatasetPermission.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_dataset(db: AsyncSession, dataset_id: str) -> List[DatasetPermission]:
        """Get all permissions for a dataset"""
        result = await db.execute(
            select(DatasetPermission)
            .where(DatasetPermission.dataset_id == dataset_id)
            .order_by(DatasetPermission.created_at)
        )
        return result.scalars().all()

    @staticmethod
    async def get_by_user(db: AsyncSession, user_id: str) -> List[DatasetPermission]:
        """Get all permissions granted to a user"""
        result = await db.execute(
            select(DatasetPermission)
            .where(DatasetPermission.user_id == user_id)
            .order_by(DatasetPermission.created_at)
        )
        return result.scalars().all()

    @staticmethod
    async def get_valid_by_user(db: AsyncSession, user_id: str) -> List[DatasetPermission]:
        """Get all valid (non-expired) permissions for a user"""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(DatasetPermission)
            .where(DatasetPermission.user_id == user_id)
            .where(
                (DatasetPermission.expires_at.is_(None)) |
                (DatasetPermission.expires_at > now)
            )
            .order_by(DatasetPermission.created_at)
        )
        return result.scalars().all()

    @staticmethod
    async def has_valid_permission(
        db: AsyncSession,
        dataset_id: str,
        user_id: str,
        permission_level: str = "pathologist"
    ) -> bool:
        """
        Check if a user has valid (non-expired) permission for a dataset.

        Args:
            db: Database session
            dataset_id: Dataset UUID
            user_id: User UUID
            permission_level: Required permission level

        Returns:
            True if user has valid permission at or above the required level
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(DatasetPermission)
            .where(DatasetPermission.dataset_id == dataset_id)
            .where(DatasetPermission.user_id == user_id)
            .where(DatasetPermission.permission_level == permission_level)
            .where(
                (DatasetPermission.expires_at.is_(None)) |
                (DatasetPermission.expires_at > now)
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def delete(db: AsyncSession, permission_id: int) -> bool:
        """Delete a permission by ID"""
        result = await db.execute(
            delete(DatasetPermission).where(DatasetPermission.id == permission_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def delete_by_dataset_and_user(
        db: AsyncSession,
        dataset_id: str,
        user_id: str
    ) -> bool:
        """Delete permission for a specific user on a specific dataset"""
        result = await db.execute(
            delete(DatasetPermission)
            .where(DatasetPermission.dataset_id == dataset_id)
            .where(DatasetPermission.user_id == user_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def delete_expired(db: AsyncSession) -> int:
        """Delete all expired permissions. Returns count of deleted records."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        result = await db.execute(
            delete(DatasetPermission)
            .where(DatasetPermission.expires_at.isnot(None))
            .where(DatasetPermission.expires_at <= now)
        )
        await db.flush()
        return result.rowcount


class StorageTaskRepository:
    """Repository for Storage Task operations (batch import, delete external files)"""

    @staticmethod
    async def create(
        db: AsyncSession,
        task_id: str,
        user_id: str,
        task_type: str,
        total_items: int = 0,
        params: Optional[Dict] = None
    ) -> StorageTask:
        """Create a new storage task"""
        task = StorageTask(
            task_id=task_id,
            user_id=user_id,
            task_type=task_type,
            total_items=total_items,
            params=params,
            status='pending'
        )
        db.add(task)
        await db.flush()
        await db.refresh(task)
        return task

    @staticmethod
    async def get_by_id(db: AsyncSession, task_id: str) -> Optional[StorageTask]:
        """Get storage task by ID"""
        result = await db.execute(
            select(StorageTask).where(StorageTask.task_id == task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_status(
        db: AsyncSession,
        task_id: str,
        status: str,
        progress: int = None,
        processed_items: int = None,
        success_count: int = None,
        failed_count: int = None,
        skipped_count: int = None,
        error_message: str = None,
        results: list = None
    ) -> bool:
        """Update storage task status"""
        update_data = {"status": status}

        if progress is not None:
            update_data["progress"] = progress
        if processed_items is not None:
            update_data["processed_items"] = processed_items
        if success_count is not None:
            update_data["success_count"] = success_count
        if failed_count is not None:
            update_data["failed_count"] = failed_count
        if skipped_count is not None:
            update_data["skipped_count"] = skipped_count
        if error_message is not None:
            update_data["error_message"] = error_message
        if results is not None:
            update_data["results"] = results

        if status == 'processing' and 'started_at' not in update_data:
            update_data["started_at"] = utc_now()
        if status in ('completed', 'failed', 'cancelled'):
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
        db: AsyncSession,
        user_id: str = None,
        limit: int = 50
    ) -> List[StorageTask]:
        """Get recent storage tasks. If user_id is None, get all tasks (admin)."""
        query = select(StorageTask).order_by(StorageTask.created_at.desc()).limit(limit)
        if user_id:
            query = query.where(StorageTask.user_id == user_id)
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def get_active_tasks(
        db: AsyncSession,
        user_id: str = None
    ) -> List[StorageTask]:
        """Get active (non-completed) storage tasks. If user_id is None, get all (admin)."""
        query = select(StorageTask).where(
            StorageTask.status.in_(['pending', 'processing'])
        ).order_by(StorageTask.created_at.desc())
        if user_id:
            query = query.where(StorageTask.user_id == user_id)
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def cleanup_old_tasks(db: AsyncSession, days: int = 7) -> int:
        """Delete storage tasks older than specified days"""
        from datetime import timedelta
        cutoff = utc_now() - timedelta(days=days)

        result = await db.execute(
            delete(StorageTask).where(StorageTask.created_at < cutoff)
        )
        return result.rowcount


class OrphanedRecordsRepository:
    """
    Repository for detecting and cleaning up orphaned database records.

    Orphaned records are database entries whose referenced entities no longer exist.
    This is the inverse of orphaned files (files without database records).
    """

    @staticmethod
    async def detect_orphaned_records(db: AsyncSession) -> Dict:
        """
        Detect orphaned records in the database.

        Returns:
            {
                "orphaned_ai_tasks": [{"task_id": str, "wsi_id": str}, ...],
                "orphaned_ai_results": [{"id": int, "wsi_id": str, "task_id": str}, ...],
                "orphaned_training_task_wsi": [{"id": int, "task_id": str, "wsi_id": str}, ...],
                "orphaned_training_logs": [{"id": int, "task_id": str}, ...],
                "orphaned_trained_models": [{"model_id": str, "task_id": str}, ...],
                "orphaned_message_feedbacks": [{"id": int, "message_id": int}, ...],
                "orphaned_dataset_permissions": [{"id": int, "dataset_id": str}, ...],
                "total_orphaned_count": int,
                "summary": {category: count, ...}
            }
        """
        from .models import (
            AITask, AIResult, TrainingTaskWSI, TrainingLog, TrainedModel,
            MessageFeedback, DatasetPermission, WSISlide, TrainingTask,
            ChatMessage, Dataset
        )

        result = {
            "orphaned_ai_tasks": [],
            "orphaned_ai_results": [],
            "orphaned_training_task_wsi": [],
            "orphaned_training_logs": [],
            "orphaned_trained_models": [],
            "orphaned_message_feedbacks": [],
            "orphaned_dataset_permissions": [],
            "total_orphaned_count": 0,
            "summary": {}
        }

        # 1. AI Tasks with non-existent WSI
        # Use LEFT JOIN to find ai_tasks where wsi_slide is NULL
        from sqlalchemy import text

        orphaned_ai_tasks_query = await db.execute(
            select(AITask)
            .outerjoin(WSISlide, AITask.wsi_id == WSISlide.wsi_id)
            .where(WSISlide.wsi_id == None)
        )
        orphaned_ai_tasks = orphaned_ai_tasks_query.scalars().all()
        result["orphaned_ai_tasks"] = [
            {"task_id": t.task_id, "wsi_id": t.wsi_id, "status": t.status}
            for t in orphaned_ai_tasks
        ]

        # 2. AI Results with non-existent WSI
        orphaned_ai_results_query = await db.execute(
            select(AIResult)
            .outerjoin(WSISlide, AIResult.wsi_id == WSISlide.wsi_id)
            .where(WSISlide.wsi_id == None)
        )
        orphaned_ai_results = orphaned_ai_results_query.scalars().all()
        result["orphaned_ai_results"] = [
            {"id": r.id, "wsi_id": r.wsi_id, "task_id": r.task_id}
            for r in orphaned_ai_results
        ]

        # 3. TrainingTaskWSI with non-existent task or WSI
        # Check for missing training task
        orphaned_task_wsi_by_task = await db.execute(
            select(TrainingTaskWSI)
            .outerjoin(TrainingTask, TrainingTaskWSI.task_id == TrainingTask.task_id)
            .where(TrainingTask.task_id == None)
        )
        orphaned_by_task = orphaned_task_wsi_by_task.scalars().all()

        # Check for missing WSI
        orphaned_task_wsi_by_wsi = await db.execute(
            select(TrainingTaskWSI)
            .outerjoin(WSISlide, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
            .where(WSISlide.wsi_id == None)
        )
        orphaned_by_wsi = orphaned_task_wsi_by_wsi.scalars().all()

        # Combine and deduplicate
        seen_ids = set()
        orphaned_training_task_wsi = []
        for item in orphaned_by_task + orphaned_by_wsi:
            if item.id not in seen_ids:
                seen_ids.add(item.id)
                orphaned_training_task_wsi.append({
                    "id": item.id, "task_id": item.task_id, "wsi_id": item.wsi_id
                })
        result["orphaned_training_task_wsi"] = orphaned_training_task_wsi

        # 4. Training Logs with non-existent training task
        orphaned_logs_query = await db.execute(
            select(TrainingLog)
            .outerjoin(TrainingTask, TrainingLog.task_id == TrainingTask.task_id)
            .where(TrainingTask.task_id == None)
        )
        orphaned_logs = orphaned_logs_query.scalars().all()
        result["orphaned_training_logs"] = [
            {"id": l.id, "task_id": l.task_id, "level": l.level}
            for l in orphaned_logs
        ]

        # 5. Trained Models with non-existent training task
        orphaned_models_query = await db.execute(
            select(TrainedModel)
            .outerjoin(TrainingTask, TrainedModel.task_id == TrainingTask.task_id)
            .where(TrainingTask.task_id == None)
        )
        orphaned_models = orphaned_models_query.scalars().all()
        result["orphaned_trained_models"] = [
            {"model_id": m.model_id, "task_id": m.task_id, "model_name": m.model_name}
            for m in orphaned_models
        ]

        # 6. Message Feedbacks with non-existent message
        orphaned_feedbacks_query = await db.execute(
            select(MessageFeedback)
            .outerjoin(ChatMessage, MessageFeedback.message_id == ChatMessage.id)
            .where(ChatMessage.id == None)
        )
        orphaned_feedbacks = orphaned_feedbacks_query.scalars().all()
        result["orphaned_message_feedbacks"] = [
            {"id": f.id, "message_id": f.message_id, "feedback_type": f.feedback_type}
            for f in orphaned_feedbacks
        ]

        # 7. Dataset Permissions with non-existent dataset
        orphaned_permissions_query = await db.execute(
            select(DatasetPermission)
            .outerjoin(Dataset, DatasetPermission.dataset_id == Dataset.dataset_id)
            .where(Dataset.dataset_id == None)
        )
        orphaned_permissions = orphaned_permissions_query.scalars().all()
        result["orphaned_dataset_permissions"] = [
            {"id": p.id, "dataset_id": p.dataset_id, "user_id": p.user_id}
            for p in orphaned_permissions
        ]

        # Calculate totals
        result["summary"] = {
            "ai_tasks": len(result["orphaned_ai_tasks"]),
            "ai_results": len(result["orphaned_ai_results"]),
            "training_task_wsi": len(result["orphaned_training_task_wsi"]),
            "training_logs": len(result["orphaned_training_logs"]),
            "trained_models": len(result["orphaned_trained_models"]),
            "message_feedbacks": len(result["orphaned_message_feedbacks"]),
            "dataset_permissions": len(result["orphaned_dataset_permissions"]),
        }
        result["total_orphaned_count"] = sum(result["summary"].values())

        return result

    @staticmethod
    async def cleanup_orphaned_records(
        db: AsyncSession,
        categories: Optional[List[str]] = None
    ) -> Dict:
        """
        Clean up orphaned records from the database.

        Args:
            db: Database session
            categories: Optional list of categories to clean up.
                       If None, clean up all categories.
                       Options: ["ai_tasks", "ai_results", "training_task_wsi",
                                "training_logs", "trained_models",
                                "message_feedbacks", "dataset_permissions"]

        Returns:
            {
                "deleted_counts": {category: count, ...},
                "total_deleted": int,
                "summary": str
            }
        """
        from .models import (
            AITask, AIResult, TrainingTaskWSI, TrainingLog, TrainedModel,
            MessageFeedback, DatasetPermission, WSISlide, TrainingTask,
            ChatMessage, Dataset
        )

        if categories is None:
            categories = [
                "ai_tasks", "ai_results", "training_task_wsi",
                "training_logs", "trained_models",
                "message_feedbacks", "dataset_permissions"
            ]

        deleted_counts = {}

        # 1. Delete orphaned AI Tasks
        if "ai_tasks" in categories:
            # Get IDs of orphaned tasks first
            orphaned_query = await db.execute(
                select(AITask.task_id)
                .outerjoin(WSISlide, AITask.wsi_id == WSISlide.wsi_id)
                .where(WSISlide.wsi_id == None)
            )
            orphaned_ids = [row[0] for row in orphaned_query.fetchall()]
            if orphaned_ids:
                result = await db.execute(
                    delete(AITask).where(AITask.task_id.in_(orphaned_ids))
                )
                deleted_counts["ai_tasks"] = result.rowcount
            else:
                deleted_counts["ai_tasks"] = 0

        # 2. Delete orphaned AI Results
        if "ai_results" in categories:
            orphaned_query = await db.execute(
                select(AIResult.id)
                .outerjoin(WSISlide, AIResult.wsi_id == WSISlide.wsi_id)
                .where(WSISlide.wsi_id == None)
            )
            orphaned_ids = [row[0] for row in orphaned_query.fetchall()]
            if orphaned_ids:
                result = await db.execute(
                    delete(AIResult).where(AIResult.id.in_(orphaned_ids))
                )
                deleted_counts["ai_results"] = result.rowcount
            else:
                deleted_counts["ai_results"] = 0

        # 3. Delete orphaned TrainingTaskWSI
        if "training_task_wsi" in categories:
            # By missing task
            orphaned_by_task = await db.execute(
                select(TrainingTaskWSI.id)
                .outerjoin(TrainingTask, TrainingTaskWSI.task_id == TrainingTask.task_id)
                .where(TrainingTask.task_id == None)
            )
            ids_by_task = [row[0] for row in orphaned_by_task.fetchall()]

            # By missing WSI
            orphaned_by_wsi = await db.execute(
                select(TrainingTaskWSI.id)
                .outerjoin(WSISlide, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
                .where(WSISlide.wsi_id == None)
            )
            ids_by_wsi = [row[0] for row in orphaned_by_wsi.fetchall()]

            orphaned_ids = list(set(ids_by_task + ids_by_wsi))
            if orphaned_ids:
                result = await db.execute(
                    delete(TrainingTaskWSI).where(TrainingTaskWSI.id.in_(orphaned_ids))
                )
                deleted_counts["training_task_wsi"] = result.rowcount
            else:
                deleted_counts["training_task_wsi"] = 0

        # 4. Delete orphaned Training Logs
        if "training_logs" in categories:
            orphaned_query = await db.execute(
                select(TrainingLog.id)
                .outerjoin(TrainingTask, TrainingLog.task_id == TrainingTask.task_id)
                .where(TrainingTask.task_id == None)
            )
            orphaned_ids = [row[0] for row in orphaned_query.fetchall()]
            if orphaned_ids:
                result = await db.execute(
                    delete(TrainingLog).where(TrainingLog.id.in_(orphaned_ids))
                )
                deleted_counts["training_logs"] = result.rowcount
            else:
                deleted_counts["training_logs"] = 0

        # 5. Delete orphaned Trained Models
        if "trained_models" in categories:
            orphaned_query = await db.execute(
                select(TrainedModel.model_id)
                .outerjoin(TrainingTask, TrainedModel.task_id == TrainingTask.task_id)
                .where(TrainingTask.task_id == None)
            )
            orphaned_ids = [row[0] for row in orphaned_query.fetchall()]
            if orphaned_ids:
                result = await db.execute(
                    delete(TrainedModel).where(TrainedModel.model_id.in_(orphaned_ids))
                )
                deleted_counts["trained_models"] = result.rowcount
            else:
                deleted_counts["trained_models"] = 0

        # 6. Delete orphaned Message Feedbacks
        if "message_feedbacks" in categories:
            orphaned_query = await db.execute(
                select(MessageFeedback.id)
                .outerjoin(ChatMessage, MessageFeedback.message_id == ChatMessage.id)
                .where(ChatMessage.id == None)
            )
            orphaned_ids = [row[0] for row in orphaned_query.fetchall()]
            if orphaned_ids:
                result = await db.execute(
                    delete(MessageFeedback).where(MessageFeedback.id.in_(orphaned_ids))
                )
                deleted_counts["message_feedbacks"] = result.rowcount
            else:
                deleted_counts["message_feedbacks"] = 0

        # 7. Delete orphaned Dataset Permissions
        if "dataset_permissions" in categories:
            orphaned_query = await db.execute(
                select(DatasetPermission.id)
                .outerjoin(Dataset, DatasetPermission.dataset_id == Dataset.dataset_id)
                .where(Dataset.dataset_id == None)
            )
            orphaned_ids = [row[0] for row in orphaned_query.fetchall()]
            if orphaned_ids:
                result = await db.execute(
                    delete(DatasetPermission).where(DatasetPermission.id.in_(orphaned_ids))
                )
                deleted_counts["dataset_permissions"] = result.rowcount
            else:
                deleted_counts["dataset_permissions"] = 0

        total_deleted = sum(deleted_counts.values())

        # Build summary string
        parts = []
        for cat, count in deleted_counts.items():
            if count > 0:
                parts.append(f"{count} {cat.replace('_', ' ')}")

        summary = f"Deleted {total_deleted} orphaned records"
        if parts:
            summary += f": {', '.join(parts)}"

        return {
            "deleted_counts": deleted_counts,
            "total_deleted": total_deleted,
            "summary": summary
        }