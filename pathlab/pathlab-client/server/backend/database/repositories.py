"""
Data Access Layer (Repository Pattern)

Provides high-level database operations for all models.
"""

from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy import select, update, delete, func, desc, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Dataset, WSISlide, AITask, AIResult, ChatConversation, ChatMessage, TrainingTask, TrainingTaskWSI, TrainedModel, TrainingLog, UserProfile, DatasetPermission, utc_now
from backend.ai.utils.data_splitter import split_wsi_dataset


class DatasetRepository:
    """Repository for Dataset operations"""

    @staticmethod
    async def create(db: AsyncSession, dataset_id: str, name: str, description: str = None) -> Dataset:
        """Create a new dataset record"""
        dataset = Dataset(dataset_id=dataset_id, name=name, description=description)
        db.add(dataset)
        await db.flush()
        await db.refresh(dataset)
        return dataset

    @staticmethod
    async def get_by_id(db: AsyncSession, dataset_id: str) -> Optional[Dataset]:
        """Get dataset by dataset_id (UUID)"""
        result = await db.execute(
            select(Dataset).where(Dataset.dataset_id == dataset_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_name(db: AsyncSession, name: str) -> Optional[Dataset]:
        """Get dataset by display name"""
        result = await db.execute(
            select(Dataset).where(Dataset.name == name)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_or_create(db: AsyncSession, name: str) -> Dataset:
        """Get existing dataset by name or create new one with UUID"""
        import uuid
        existing = await DatasetRepository.get_by_name(db, name)
        if existing:
            return existing
        dataset_id = str(uuid.uuid4())
        return await DatasetRepository.create(db, dataset_id, name)

    @staticmethod
    async def get_all(db: AsyncSession) -> List[Dataset]:
        """Get all datasets"""
        result = await db.execute(
            select(Dataset).order_by(Dataset.name)
        )
        return result.scalars().all()

    @staticmethod
    async def get_by_ids(db: AsyncSession, dataset_ids: List[str]) -> List[Dataset]:
        """Get multiple datasets by IDs in a single query (batch operation)"""
        if not dataset_ids:
            return []
        result = await db.execute(
            select(Dataset).where(Dataset.dataset_id.in_(dataset_ids))
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
    async def get_all_with_dataset(db: AsyncSession, skip: int = 0, limit: int = 0, user_id: Optional[str] = None) -> List[WSISlide]:
        """Get all WSI slides with dataset relationship loaded.

        Args:
            db: Database session
            skip: Number of records to skip
            limit: Maximum number of records to return (0 = all)
            user_id: Optional user ID filter. If provided, only returns WSI belonging to this user.
                     If None, returns all WSI (for admin users).
        """
        query = select(WSISlide).options(selectinload(WSISlide.dataset))
        if user_id is not None:
            query = query.where(WSISlide.user_id == user_id)
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
    async def count(db: AsyncSession, user_id: Optional[str] = None) -> int:
        """Get total count of WSI slides.

        Args:
            db: Database session
            user_id: Optional user ID filter. If provided, only counts WSI belonging to this user.
                     If None, counts all WSI (for admin users).
        """
        query = select(func.count(WSISlide.id))
        if user_id is not None:
            query = query.where(WSISlide.user_id == user_id)
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

    # File type classification constants
    WSI_EXTENSIONS = ('.svs', '.svslide', '.ndpi', '.scn', '.mrxs', '.bif', '.vsi', '.vms', '.vmu', '.kfb', '.sdpc', '.tmap', '.mds', '.mdsx', '.qptiff', '.tron', '.isyntax')
    PATCH_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp')
    TIF_EXTENSIONS = ('.tif', '.tiff')
    SIZE_THRESHOLD = 100 * 1024 * 1024  # 100 MB threshold for .tif/.tiff files

    @staticmethod
    async def get_chat_context_stats(db: AsyncSession, user_id: Optional[str] = None) -> Dict:
        """
        Get all statistics needed for chat context in a SINGLE optimized query.
        This combines count, label distribution, data type distribution, and dataset info.

        Args:
            db: Database session
            user_id: Optional user ID filter.

        Returns:
            Dict with total_count, labels (dict), data_types (dict), datasets (list)
        """
        from sqlalchemy import case, or_, and_

        # Build WSI/Patch conditions
        wsi_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSIRepository.WSI_EXTENSIONS]
        tif_wsi_condition = and_(
            or_(*[func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSIRepository.TIF_EXTENSIONS]),
            WSISlide.file_size >= WSIRepository.SIZE_THRESHOLD
        )
        is_wsi = or_(*wsi_ext_conditions, tif_wsi_condition)

        patch_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSIRepository.PATCH_EXTENSIONS]
        tif_patch_condition = and_(
            or_(*[func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSIRepository.TIF_EXTENSIONS]),
            or_(WSISlide.file_size < WSIRepository.SIZE_THRESHOLD, WSISlide.file_size.is_(None))
        )
        is_patch = or_(*patch_ext_conditions, tif_patch_condition)

        # Single query for total count and data type distribution
        stats_query = select(
            func.count(WSISlide.id).label("total_count"),
            func.sum(case((is_wsi, 1), else_=0)).label("wsi_count"),
            func.sum(case((is_patch, 1), else_=0)).label("patch_count")
        )
        if user_id is not None:
            stats_query = stats_query.where(WSISlide.user_id == user_id)

        stats_result = await db.execute(stats_query)
        stats_row = stats_result.one()

        # Query for label distribution (simple GROUP BY)
        labels_query = select(WSISlide.label, func.count(WSISlide.id)).group_by(WSISlide.label)
        if user_id is not None:
            labels_query = labels_query.where(WSISlide.user_id == user_id)
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
            func.count(WSISlide.id).label("file_count"),
            func.sum(is_wsi_case).label("wsi_count"),
            func.sum(is_patch_case).label("patch_count")
        ).select_from(WSISlide).outerjoin(Dataset, WSISlide.dataset_id == Dataset.dataset_id)

        if user_id is not None:
            datasets_query = datasets_query.where(WSISlide.user_id == user_id)

        datasets_query = datasets_query.group_by(Dataset.dataset_id, Dataset.name).order_by(Dataset.name)
        datasets_result = await db.execute(datasets_query)

        # Get labels per dataset
        labels_per_dataset_query = select(
            Dataset.dataset_id,
            WSISlide.label,
            func.count(WSISlide.id).label("count")
        ).select_from(WSISlide).outerjoin(Dataset, WSISlide.dataset_id == Dataset.dataset_id)

        if user_id is not None:
            labels_per_dataset_query = labels_per_dataset_query.where(WSISlide.user_id == user_id)

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

        if user_id is not None:
            survival_per_dataset_query = survival_per_dataset_query.where(WSISlide.user_id == user_id)

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
            datasets.append({
                "dataset_id": row.dataset_id,
                "dataset_name": row.dataset_name or "Uncategorized",
                "file_count": row.file_count,
                "data_type": data_type,
                "labels": ds_labels,
                "survival_count": survival_count  # Number of records with survival data
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
        wsi_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSIRepository.WSI_EXTENSIONS]
        tif_wsi_condition = and_(
            or_(*[func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSIRepository.TIF_EXTENSIONS]),
            WSISlide.file_size >= WSIRepository.SIZE_THRESHOLD
        )
        is_wsi = or_(*wsi_ext_conditions, tif_wsi_condition)

        # Build Patch condition
        patch_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSIRepository.PATCH_EXTENSIONS]
        tif_patch_condition = and_(
            or_(*[func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSIRepository.TIF_EXTENSIONS]),
            or_(WSISlide.file_size < WSIRepository.SIZE_THRESHOLD, WSISlide.file_size.is_(None))
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
    async def get_datasets(db: AsyncSession, data_level: Optional[str] = None, user_id: Optional[str] = None) -> List[Dict]:
        """
        Get all datasets with file count and total size.

        Args:
            db: Database session
            data_level: Optional filter - "wsi" for WSI files, "patch" for image files
                       If None, returns all datasets
            user_id: Optional user ID filter. If provided, only returns datasets containing WSI belonging to this user.
                     If None, returns all datasets (for admin users).

        Returns:
            List of dicts with dataset_id (UUID), name (display), file_count, total_size, dataset_type
        """
        from sqlalchemy import or_, and_, case

        # Build file type filter based on data_level
        if data_level == "wsi":
            wsi_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSIRepository.WSI_EXTENSIONS]
            tif_conditions = [
                and_(
                    or_(
                        func.lower(WSISlide.wsi_path).like('%' + ext)
                        for ext in WSIRepository.TIF_EXTENSIONS
                    ),
                    WSISlide.file_size >= WSIRepository.SIZE_THRESHOLD
                )
            ]
            file_filter = or_(*wsi_ext_conditions, *tif_conditions)
        elif data_level == "patch":
            patch_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSIRepository.PATCH_EXTENSIONS]
            tif_conditions = [
                and_(
                    or_(
                        func.lower(WSISlide.wsi_path).like('%' + ext)
                        for ext in WSIRepository.TIF_EXTENSIONS
                    ),
                    or_(
                        WSISlide.file_size < WSIRepository.SIZE_THRESHOLD,
                        WSISlide.file_size.is_(None)
                    )
                )
            ]
            file_filter = or_(*patch_ext_conditions, *tif_conditions)
        else:
            file_filter = None

        # Build query with join to Dataset table
        survival_count = func.sum(
            case(
                (WSISlide.event_time.isnot(None), 1),
                else_=0
            )
        ).label("survival_count")

        # Join with Dataset table to get dataset_id and name
        query = select(
            Dataset.dataset_id,
            Dataset.name.label("dataset_name"),
            func.count(WSISlide.id).label("file_count"),
            func.sum(WSISlide.file_size).label("total_size"),
            survival_count
        ).select_from(WSISlide).outerjoin(Dataset, WSISlide.dataset_id == Dataset.dataset_id)

        # Apply user_id filter
        if user_id is not None:
            query = query.where(WSISlide.user_id == user_id)

        if file_filter is not None:
            query = query.where(file_filter)

        query = query.group_by(Dataset.dataset_id, Dataset.name).order_by(Dataset.name)

        result = await db.execute(query)
        datasets = []
        for row in result.all():
            dataset_type = "survival" if (row.survival_count or 0) > 0 else "classification"
            datasets.append({
                "dataset_id": row.dataset_id,  # UUID for API calls
                "dataset_name": row.dataset_name or "Uncategorized",  # Display name
                "file_count": row.file_count,
                "total_size": row.total_size or 0,
                "dataset_type": dataset_type
            })
        return datasets

    @staticmethod
    async def get_by_dataset(db: AsyncSession, dataset_id: str, skip: int = 0, limit: int = 0, user_id: Optional[str] = None) -> List[WSISlide]:
        """
        Get all WSI slides in a specific dataset with pagination.

        Args:
            db: Database session
            dataset_id: Dataset UUID to filter by (use "Uncategorized" for NULL dataset_id)
            skip: Number of records to skip
            limit: Maximum number of records to return (0 = all)
            user_id: Optional user ID filter. If provided, only returns WSI belonging to this user.
                     If None, returns all WSI in the dataset (for admin users).

        Returns:
            List of WSISlide objects with dataset relationship loaded
        """
        query = select(WSISlide).options(selectinload(WSISlide.dataset))

        if dataset_id == "Uncategorized":
            query = query.where(WSISlide.dataset_id.is_(None))
        else:
            query = query.where(WSISlide.dataset_id == dataset_id)

        # Apply user_id filter
        if user_id is not None:
            query = query.where(WSISlide.user_id == user_id)

        query = query.order_by(desc(WSISlide.created_at)).offset(skip)
        if limit > 0:
            query = query.limit(limit)

        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def count_by_dataset(db: AsyncSession, dataset_id: str, user_id: Optional[str] = None) -> int:
        """
        Count WSI slides in a specific dataset.

        Args:
            db: Database session
            dataset_id: Dataset UUID to filter by (use "Uncategorized" for NULL dataset_id)
            user_id: Optional user ID filter. If provided, only counts WSI belonging to this user.
                     If None, counts all WSI in the dataset (for admin users).

        Returns:
            Number of WSI slides in the dataset
        """
        query = select(func.count(WSISlide.id))

        if dataset_id == "Uncategorized":
            query = query.where(WSISlide.dataset_id.is_(None))
        else:
            query = query.where(WSISlide.dataset_id == dataset_id)

        # Apply user_id filter
        if user_id is not None:
            query = query.where(WSISlide.user_id == user_id)

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

        if status == "running" and not await AITaskRepository._has_started(db, task_id):
            update_data["started_at"] = utc_now()

        if status in ["completed", "failed", "cancelled"]:
            update_data["finished_at"] = utc_now()
            if status == "completed":
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
        query = select(func.count(AITask.id)).where(AITask.status == "completed")
        if user_id is not None:
            query = query.where(AITask.user_id == user_id)
        result = await db.execute(query)
        return result.scalar_one()


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


class TrainingTaskRepository:
    """Repository for Training Task operations"""

    @staticmethod
    async def create(
        db: AsyncSession,
        task_data: Dict,
        wsi_ids: List[str],
        split_config: Optional[Dict] = None
    ) -> TrainingTask:
        """
        Create a new training task with associated WSI slides.
        Automatically extracts classes from WSI labels.

        For large datasets (10k+ WSIs), uses bulk inserts to avoid SQLite issues.
        """
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

        # Add split_config to preprocessing_config for persistence
        if split_config:
            preprocessing_config = task_data.get("preprocessing_config", {}) or {}
            preprocessing_config["split_config"] = split_config
            task_data["preprocessing_config"] = preprocessing_config

        # Create training task
        task = TrainingTask(
            **task_data,
            classes=classes,
            status="pending",
            progress=0
        )
        db.add(task)
        await db.flush()
        await db.refresh(task)

        # Commit the task first to ensure it exists before associations
        await db.commit()

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
                # For other strategies (random, k_fold), use the splitter function
                wsi_splits = split_wsi_dataset(wsi_ids, **split_config)

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
                await db.commit()

        return task

    @staticmethod
    async def get_by_id(db: AsyncSession, task_id: str) -> Optional[TrainingTask]:
        """Get training task by task_id"""
        result = await db.execute(
            select(TrainingTask).where(TrainingTask.task_id == task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(db: AsyncSession, limit: int = 100, offset: int = 0, user_id: Optional[str] = None) -> List[TrainingTask]:
        """Get all training tasks.

        Args:
            db: Database session
            limit: Maximum number of records to return
            offset: Number of records to skip
            user_id: Optional user ID filter. If provided, only returns tasks belonging to this user.
                     If None, returns all tasks (for admin users).
        """
        query = select(TrainingTask)
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
    async def get_wsi_ids(db: AsyncSession, task_id: str) -> List[str]:
        """Get all WSI IDs associated with a training task"""
        result = await db.execute(
            select(TrainingTaskWSI.wsi_id)
            .where(TrainingTaskWSI.task_id == task_id)
        )
        return [row[0] for row in result.all()]

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

        if status == "running":
            update_data["started_at"] = utc_now()

        if status in ["completed", "failed", "cancelled"]:
            update_data["finished_at"] = utc_now()
            if status == "completed":
                update_data["progress"] = 100

        await db.execute(
            update(TrainingTask)
            .where(TrainingTask.task_id == task_id)
            .values(**update_data)
        )
        await db.flush()
        return await TrainingTaskRepository.get_by_id(db, task_id)

    # Status values that indicate a task was interrupted (not failed normally)
    INTERRUPTED_STATUSES = ['running', 'extracting', 'training']

    @staticmethod
    async def get_interrupted_tasks(db: AsyncSession) -> List[TrainingTask]:
        """
        Get all training tasks that were interrupted (e.g., by system shutdown).

        These are tasks with status 'running', 'extracting', or 'training' -
        states that indicate the task was in progress but never completed or failed.
        If the system restarts and a task has one of these statuses, it was interrupted.

        Note: 'failed' tasks are NOT considered interrupted - they failed normally.
        """
        result = await db.execute(
            select(TrainingTask)
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
        3. If another instance already claimed it (changed status to 'pending'),
           this UPDATE will affect 0 rows

        The task is set to 'pending' status temporarily. The pipeline will
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
                status='pending',  # Temporary until pipeline starts
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


class UserProfileRepository:
    """Repository for User Profile operations"""

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: str) -> Optional[UserProfile]:
        """Get user profile by user_id"""
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_current_user(db: AsyncSession) -> Optional[UserProfile]:
        """Get the current logged-in user"""
        result = await db.execute(
            select(UserProfile).where(UserProfile.is_current == True)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(db: AsyncSession, profile_data: Dict) -> UserProfile:
        """Create or update user profile"""
        user_id = profile_data.get("user_id")
        existing = await UserProfileRepository.get_by_id(db, user_id)

        if existing:
            # Update existing profile
            for key, value in profile_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            existing.updated_at = utc_now()
            await db.flush()
            return existing
        else:
            # Create new profile
            profile = UserProfile(**profile_data)
            db.add(profile)
            await db.flush()
            return profile

    @staticmethod
    async def update(db: AsyncSession, user_id: str, updates: Dict) -> Optional[UserProfile]:
        """Update user profile"""
        await db.execute(
            update(UserProfile)
            .where(UserProfile.user_id == user_id)
            .values(**updates, updated_at=utc_now())
        )
        await db.flush()
        return await UserProfileRepository.get_by_id(db, user_id)

    @staticmethod
    async def set_current_user(db: AsyncSession, user_id: str) -> None:
        """Set a user as the current user (unsets all others)"""
        # Unset all current flags
        await db.execute(
            update(UserProfile).values(is_current=False)
        )
        # Set the specified user as current
        await db.execute(
            update(UserProfile)
            .where(UserProfile.user_id == user_id)
            .values(is_current=True)
        )
        await db.flush()

    @staticmethod
    async def update_tokens(
        db: AsyncSession,
        user_id: str,
        access_token: str,
        refresh_token: Optional[str],
        expires_at: Optional[datetime]
    ) -> None:
        """Update user tokens"""
        updates = {
            "access_token_encrypted": access_token,
            "token_expires_at": expires_at,
            "updated_at": utc_now()
        }
        if refresh_token:
            updates["refresh_token_encrypted"] = refresh_token

        await db.execute(
            update(UserProfile)
            .where(UserProfile.user_id == user_id)
            .values(**updates)
        )
        await db.flush()

    @staticmethod
    async def delete(db: AsyncSession, user_id: str) -> bool:
        """Delete user profile"""
        result = await db.execute(
            delete(UserProfile).where(UserProfile.user_id == user_id)
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