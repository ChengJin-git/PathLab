"""
TrainingTaskRepository - Data Access Layer
"""

import asyncio
from functools import partial
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Set, Tuple, Any
from sqlalchemy import (
    select,
    update,
    delete,
    func,
    desc,
    asc,
    insert,
    or_,
    cast,
    String,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

from ..models import (
    DataGroup,
    Dataset,
    WSISlide,
    TrainingTask,
    TrainingTaskWSI,
    TrainedModel,
    TrainingLog,
    utc_now,
)
from .base import BaseRepository
from backend.ai.utils.data_splitter import split_wsi_dataset, split_case_dataset
from backend.ai.schemas.base import TaskStatus
from backend.annotation.coco_utils import (
    merge_coco_datasets,
    extract_coco_wsi_label_sets,
)


def _build_segmentation_wsi_lookups(
    wsis: List[WSISlide],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    exact_lookup: Dict[str, str] = {}
    stem_candidates: Dict[str, Set[str]] = {}

    for wsi in wsis:
        candidate_names = []
        if wsi.original_filename:
            candidate_names.append(str(wsi.original_filename))
        if wsi.wsi_path:
            candidate_names.append(Path(str(wsi.wsi_path)).name)

        for candidate in candidate_names:
            normalized = Path(candidate).name.strip().lower()
            if not normalized:
                continue
            exact_lookup.setdefault(normalized, wsi.wsi_id)
            stem_candidates.setdefault(Path(normalized).stem, set()).add(wsi.wsi_id)

    stem_lookup = {
        stem: next(iter(wsi_ids))
        for stem, wsi_ids in stem_candidates.items()
        if len(wsi_ids) == 1
    }
    return exact_lookup, stem_lookup


def _extract_segmentation_multilabels_from_payloads(
    payloads: List[dict[str, Any]],
    wsis: List[WSISlide],
) -> Tuple[List[str], Dict[str, Set[str]]]:
    merged_coco = merge_coco_datasets(payloads)
    exact_lookup, stem_lookup = _build_segmentation_wsi_lookups(wsis)
    multilabels = extract_coco_wsi_label_sets(merged_coco, exact_lookup, stem_lookup)
    classes = sorted(
        {label for label_set in multilabels.values() for label in label_set}
    )
    return classes, multilabels


def _build_training_task_wsi_batches(
    task_id: str,
    wsi_ids: List[str],
    wsi_splits: Dict[str, str],
    insert_batch_size: int,
) -> List[List[Dict[str, object]]]:
    batches: List[List[Dict[str, object]]] = []
    for i in range(0, len(wsi_ids), insert_batch_size):
        batch_wsi_ids = wsi_ids[i : i + insert_batch_size]
        batch_created_at = utc_now()
        batches.append(
            [
                {
                    "task_id": task_id,
                    "wsi_id": wsi_id,
                    "split": wsi_splits.get(wsi_id, "train"),
                    "created_at": batch_created_at,
                }
                for wsi_id in batch_wsi_ids
            ]
        )
    return batches


async def _load_segmentation_multilabels(
    db: AsyncSession,
    wsis: List[WSISlide],
) -> Tuple[List[str], Dict[str, Set[str]]]:
    dataset_ids = {wsi.dataset_id for wsi in wsis if wsi.dataset_id}
    if len(dataset_ids) != 1:
        return [], {}

    from .annotation import SegmentationAnnotationRepository

    dataset_id = next(iter(dataset_ids))
    records = await SegmentationAnnotationRepository.get_all_by_dataset(
        db,
        dataset_id,
        include_drafts=False,
    )
    if not records:
        return [], {}

    dataset_level_record = next(
        (record for record in records if record.annotation_id == f"label_{dataset_id}"),
        None,
    )
    payloads = (
        [dataset_level_record.annotations]
        if dataset_level_record
        else [
            record.annotations
            for record in records
            if isinstance(record.annotations, dict)
        ]
    )
    return await asyncio.to_thread(
        _extract_segmentation_multilabels_from_payloads, payloads, wsis
    )


class TrainingTaskRepository(BaseRepository[TrainingTask]):
    """Repository for Training Task operations"""

    model = TrainingTask
    pk_field = "task_id"

    @staticmethod
    async def create(
        db: AsyncSession,
        task_data: Dict[str, Any],
        wsi_ids: List[str],
        split_config: Optional[Dict[str, Any]] = None,
        prefetched_wsis: Optional[List[Any]] = None,
    ) -> TrainingTask:
        """
        Create a new training task with associated WSI slides.
        Automatically extracts classes from WSI labels.

        For large datasets (10k+ WSIs), uses bulk inserts for performance.

        Args:
            prefetched_wsis: Optional list of already-fetched WSISlide objects.
                             If provided, skips redundant DB query for WSI data.
        """
        # Use pre-fetched WSIs if available, otherwise query from DB
        if prefetched_wsis is not None:
            wsis = prefetched_wsis
        else:
            # Extract unique classes from WSI labels
            # For large datasets, query in batches for memory efficiency
            wsis = []
            batch_size = 500
            for i in range(0, len(wsi_ids), batch_size):
                batch_ids = wsi_ids[i : i + batch_size]
                wsi_list = await db.execute(
                    select(WSISlide).where(WSISlide.wsi_id.in_(batch_ids))
                )
                wsis.extend(wsi_list.scalars().all())

        # Validate task based on task_type
        task_type = task_data.get("task_type", "classification")
        classes = sorted(list(set(wsi.label for wsi in wsis if wsi.label)))
        segmentation_multilabels: Dict[str, Set[str]] = {}

        if task_type == "segmentation":
            classes, segmentation_multilabels = await _load_segmentation_multilabels(
                db, wsis
            )
            if not classes:
                raise ValueError(
                    "Segmentation tasks require at least one COCO category in the selected dataset."
                )

        if task_type == "classification":
            # Classification tasks require at least 2 classes
            if len(classes) < 2:
                raise ValueError(
                    f"Classification tasks require at least 2 different classes. "
                    f"Found {len(classes)} class(es): {classes}. "
                    f"Please assign different labels to your slides."
                )
        elif task_type == "survival":
            # Survival tasks require both event (status=1) and censored (status=0) samples
            event_statuses = set(
                wsi.event_status
                for wsi in wsis
                if wsi.event_status is not None and wsi.event_time is not None
            )
            if len(event_statuses) < 2:
                event_count = sum(
                    1
                    for wsi in wsis
                    if wsi.event_status == 1 and wsi.event_time is not None
                )
                censored_count = sum(
                    1
                    for wsi in wsis
                    if wsi.event_status == 0 and wsi.event_time is not None
                )
                missing_type = (
                    "Event (status=1)" if event_count == 0 else "Censored (status=0)"
                )
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
                            is_case_level = group_row[0] == "case"
                            task_type_from_group = group_row[1]

                # Determine task type from DataGroup for split behavior
                is_survival = task_type_from_group == "survival"
                is_segmentation = task_type_from_group == "segmentation"

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
                    wsi_splits = await asyncio.to_thread(
                        partial(
                            split_case_dataset,
                            wsi_ids,
                            case_id_map,
                            labels=case_labels,
                            multilabels=segmentation_multilabels
                            if is_segmentation
                            else None,
                            **split_config_copy,
                        )
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
                    wsi_splits = await asyncio.to_thread(
                        partial(
                            split_wsi_dataset,
                            wsi_ids,
                            labels=None if is_segmentation else wsi_labels,
                            multilabels=segmentation_multilabels
                            if is_segmentation
                            else None,
                            **split_config,
                        )
                    )

        # Pre-build bulk insert payloads before opening the write-heavy phase.
        insert_batch_size = 1000

        # Remove task_type from task_data before creating TrainingTask
        # (task_type is stored in the associated DataGroup, not in TrainingTask directly)
        task_data_cleaned = {k: v for k, v in task_data.items() if k != "task_type"}
        task_id = task_data_cleaned["task_id"]
        association_batches = await asyncio.to_thread(
            _build_training_task_wsi_batches,
            task_id,
            wsi_ids,
            wsi_splits,
            insert_batch_size,
        )

        # Create training task only after the expensive preparation work is done,
        # to minimize how long we hold the database write transaction.
        task = TrainingTask(
            **task_data_cleaned, classes=classes, status=TaskStatus.PENDING, progress=0
        )
        db.add(task)
        await db.flush()

        # Use bulk insert to avoid ORM identity map issues and improve performance
        # This is much faster and more reliable for large datasets
        for records in association_batches:
            if records:
                await db.execute(insert(TrainingTaskWSI), records)

        # Single commit for task + all WSI associations (avoids multiple write lock acquisitions)
        await db.commit()

        # Re-fetch task with data_group relationship loaded to avoid lazy loading issues
        # This is necessary because to_dict() accesses data_group attributes
        result = await db.execute(
            select(TrainingTask)
            .options(selectinload(TrainingTask.data_group))
            .where(TrainingTask.task_id == task_id)
        )
        return result.scalar_one()

    @staticmethod
    async def get_by_id(db: AsyncSession, task_id: str, include_username: bool = False):
        """Get training task by task_id with data_group relationship loaded.

        Args:
            db: Database session
            task_id: Training task ID
            include_username: If True, joins with User table to include username (for admin view).
                              Returns dict instead of TrainingTask object.

        Returns:
            If include_username=False: Optional[TrainingTask]
            If include_username=True: Optional[Dict] with username field added
        """
        if not include_username:
            # Original behavior - return TrainingTask object
            result = await db.execute(
                select(TrainingTask)
                .options(selectinload(TrainingTask.data_group))
                .where(TrainingTask.task_id == task_id)
            )
            return result.scalar_one_or_none()
        else:
            # Admin view - join with User table to get username
            from backend.auth.models import User as AuthUser
            from sqlalchemy import cast, String

            result = await db.execute(
                select(TrainingTask, AuthUser.email, AuthUser.nickname)
                .options(selectinload(TrainingTask.data_group))
                .outerjoin(AuthUser, TrainingTask.user_id == cast(AuthUser.id, String))
                .where(TrainingTask.task_id == task_id)
            )
            row = result.one_or_none()
            if not row:
                return None

            task = row[0]  # TrainingTask object
            email = row[1]  # User.email (username)
            nickname = row[2]  # User.nickname

            task_dict = task.to_dict()
            # Use nickname if available, otherwise use email (username)
            task_dict["username"] = nickname or email or None
            return task_dict

    @staticmethod
    async def get_by_ids(
        db: AsyncSession, task_ids: List[str]
    ) -> Dict[str, TrainingTask]:
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
    def _apply_task_list_filters(
        query,
        user_id: Optional[str] = None,
        search: Optional[str] = None,
        status_filter: str = "all",
    ):
        if user_id is not None:
            query = query.where(TrainingTask.user_id == user_id)

        normalized_search = search.strip() if search else None
        if normalized_search:
            like_term = f"%{normalized_search}%"
            query = query.where(
                or_(
                    TrainingTask.task_name.ilike(like_term),
                    TrainingTask.task_id.ilike(like_term),
                )
            )

        if status_filter == "running":
            query = query.where(
                TrainingTask.status.in_(
                    [
                        TaskStatus.PATCHING,
                        TaskStatus.TRAINING,
                        TaskStatus.PENDING,
                        TaskStatus.QUEUED,
                        TaskStatus.EXTRACTING,
                    ]
                )
            )
        elif status_filter == "completed":
            query = query.where(TrainingTask.status == TaskStatus.COMPLETED)
        elif status_filter == "failed":
            query = query.where(TrainingTask.status == TaskStatus.FAILED)
        elif status_filter == "cancelled":
            query = query.where(TrainingTask.status == TaskStatus.CANCELLED)

        return query

    @staticmethod
    def _apply_task_list_sort(query, sort_by: str = "updated"):
        if sort_by == "created":
            return query.order_by(desc(TrainingTask.created_at))
        if sort_by == "name":
            return query.order_by(
                asc(TrainingTask.task_name), desc(TrainingTask.created_at)
            )
        return query.order_by(
            desc(TrainingTask.updated_at), desc(TrainingTask.created_at)
        )

    @staticmethod
    async def get_all(
        db: AsyncSession,
        limit: int = 100,
        offset: int = 0,
        user_id: Optional[str] = None,
        include_username: bool = False,
        search: Optional[str] = None,
        status_filter: str = "all",
        sort_by: str = "updated",
    ):
        """Get all training tasks with data_group relationship loaded.

        Args:
            db: Database session
            limit: Maximum number of records to return
            offset: Number of records to skip
            user_id: Optional user ID filter. If provided, only returns tasks belonging to this user.
                     If None, returns all tasks (for admin users).
            include_username: If True, joins with User table to include username (for admin view).
                              Returns list of dicts instead of TrainingTask objects.

        Returns:
            If include_username=False: List[TrainingTask]
            If include_username=True: List[Dict] with username field added
        """
        if not include_username:
            # Original behavior - return TrainingTask objects
            query = select(TrainingTask).options(selectinload(TrainingTask.data_group))
            query = TrainingTaskRepository._apply_task_list_filters(
                query,
                user_id=user_id,
                search=search,
                status_filter=status_filter,
            )
            query = (
                TrainingTaskRepository._apply_task_list_sort(query, sort_by)
                .limit(limit)
                .offset(offset)
            )
            result = await db.execute(query)
            return result.scalars().all()
        else:
            # Admin view - join with User table to get username
            from backend.auth.models import User as AuthUser
            from sqlalchemy import cast, String

            query = (
                select(TrainingTask, AuthUser.email, AuthUser.nickname)
                .options(selectinload(TrainingTask.data_group))
                .outerjoin(AuthUser, TrainingTask.user_id == cast(AuthUser.id, String))
            )
            query = TrainingTaskRepository._apply_task_list_filters(
                query,
                user_id=user_id,
                search=search,
                status_filter=status_filter,
            )
            query = (
                TrainingTaskRepository._apply_task_list_sort(query, sort_by)
                .limit(limit)
                .offset(offset)
            )
            result = await db.execute(query)
            rows = result.all()

            # Convert to dict with username
            tasks_with_username = []
            for row in rows:
                task = row[0]  # TrainingTask object
                email = row[1]  # User.email (username)
                nickname = row[2]  # User.nickname

                task_dict = task.to_dict()
                # Use nickname if available, otherwise use email (username)
                task_dict["username"] = nickname or email or None
                tasks_with_username.append(task_dict)

            return tasks_with_username

    @staticmethod
    async def count(
        db: AsyncSession,
        user_id: Optional[str] = None,
        search: Optional[str] = None,
        status_filter: str = "all",
    ) -> int:
        """Count total training tasks.

        Args:
            db: Database session
            user_id: Optional user ID filter. If provided, only counts tasks belonging to this user.
                     If None, counts all tasks (for admin users).
        """
        query = select(func.count(TrainingTask.id))
        query = TrainingTaskRepository._apply_task_list_filters(
            query,
            user_id=user_id,
            search=search,
            status_filter=status_filter,
        )
        result = await db.execute(query)
        return result.scalar()

    @staticmethod
    async def get_status_counts(
        db: AsyncSession, user_id: Optional[str] = None
    ) -> Dict[str, int]:
        """Get counts of training tasks by status.

        Args:
            db: Database session
            user_id: Optional user ID filter. If provided, only counts tasks belonging to this user.

        Returns:
            Dict with keys: total, completed, running, failed, pending
            Note: "running" includes all in-progress statuses: patching, training, pending, queued, extracting
        """
        from sqlalchemy import case, or_

        # Define in-progress statuses (tasks that are actively running or waiting to run)
        in_progress_statuses = [
            TaskStatus.PATCHING,
            TaskStatus.TRAINING,
            TaskStatus.PENDING,
            TaskStatus.QUEUED,
            TaskStatus.EXTRACTING,
        ]

        query = select(
            func.count(TrainingTask.id).label("total"),
            func.sum(
                case((TrainingTask.status == TaskStatus.COMPLETED, 1), else_=0)
            ).label("completed"),
            func.sum(
                case((TrainingTask.status.in_(in_progress_statuses), 1), else_=0)
            ).label("running"),
            func.sum(
                case((TrainingTask.status == TaskStatus.FAILED, 1), else_=0)
            ).label("failed"),
            func.sum(
                case((TrainingTask.status == TaskStatus.CANCELLED, 1), else_=0)
            ).label("cancelled"),
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
            "cancelled": row.cancelled or 0,
        }

    @staticmethod
    async def get_wsi_ids(db: AsyncSession, task_id: str) -> List[str]:
        """Get all WSI IDs associated with a training task"""
        result = await db.execute(
            select(TrainingTaskWSI.wsi_id).where(TrainingTaskWSI.task_id == task_id)
        )
        return [row[0] for row in result.all()]

    @staticmethod
    async def get_wsi_ids_batch(
        db: AsyncSession, task_ids: List[str]
    ) -> Dict[str, List[str]]:
        """Get all WSI IDs for multiple tasks in a single query (batch operation).

        Args:
            db: Database session
            task_ids: List of task IDs to get WSI IDs for

        Returns:
            Dict mapping task_id to list of wsi_ids. Tasks with no WSIs will have empty list.
        """
        if not task_ids:
            return {}
        result = await db.execute(
            select(TrainingTaskWSI.task_id, TrainingTaskWSI.wsi_id).where(
                TrainingTaskWSI.task_id.in_(task_ids)
            )
        )
        wsi_ids_by_task: Dict[str, List[str]] = {tid: [] for tid in task_ids}
        for row in result.all():
            wsi_ids_by_task[row[0]].append(row[1])
        return wsi_ids_by_task

    @staticmethod
    async def get_source_dataset_ids_batch(
        db: AsyncSession, task_ids: List[str]
    ) -> Dict[str, Optional[str]]:
        """Return the source dataset_id for each task when all WSIs come from one dataset."""
        if not task_ids:
            return {}

        result = await db.execute(
            select(
                TrainingTaskWSI.task_id.label("task_id"),
                func.count(func.distinct(WSISlide.dataset_id)).label("dataset_count"),
                func.min(WSISlide.dataset_id).label("dataset_id"),
            )
            .join(WSISlide, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
            .where(TrainingTaskWSI.task_id.in_(task_ids))
            .group_by(TrainingTaskWSI.task_id)
        )

        source_dataset_ids: Dict[str, Optional[str]] = {
            task_id: None for task_id in task_ids
        }
        for row in result.all():
            source_dataset_ids[row.task_id] = (
                row.dataset_id if row.dataset_count == 1 else None
            )
        return source_dataset_ids

    @staticmethod
    async def get_wsi_counts_batch(
        db: AsyncSession, task_ids: List[str]
    ) -> Dict[str, int]:
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
                func.count(TrainingTaskWSI.wsi_id).label("wsi_count"),
            )
            .where(TrainingTaskWSI.task_id.in_(task_ids))
            .group_by(TrainingTaskWSI.task_id)
        )
        counts = {row.task_id: row.wsi_count for row in result.all()}
        # Ensure all requested task_ids have a count (default 0)
        return {task_id: counts.get(task_id, 0) for task_id in task_ids}

    @staticmethod
    async def get_wsi_with_labels(
        db: AsyncSession, task_id: str
    ) -> List[Dict[str, Any]]:
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
                TrainingTaskWSI.split,
            )
            .join(TrainingTaskWSI, WSISlide.wsi_id == TrainingTaskWSI.wsi_id)
            .where(TrainingTaskWSI.task_id == task_id)
        )
        return [
            {"wsi_id": row[0], "wsi_path": row[1], "label": row[2], "split": row[3]}
            for row in result.all()
        ]

    @staticmethod
    async def get_wsi_ids_by_split(
        db: AsyncSession, task_id: str
    ) -> Dict[str, List[str]]:
        """
        Get WSI IDs grouped by their split assignment.

        Returns:
            Dict with split names as keys and lists of wsi_ids as values.
            For regular splits: {'train': [...], 'val': [...], 'test': [...]}
            For k-fold: {'fold_0': [...], 'fold_1': [...], ...}
        """
        result = await db.execute(
            select(TrainingTaskWSI.wsi_id, TrainingTaskWSI.split).where(
                TrainingTaskWSI.task_id == task_id
            )
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
    async def get_dataset_aggregation_level(
        db: AsyncSession, task_id: str
    ) -> Optional[str]:
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
        error_message: Optional[str] = None,
    ) -> Optional[TrainingTask]:
        """Update training task status"""
        update_data = {"status": status}

        if progress is not None:
            update_data["progress"] = progress

        if error_message is not None:
            update_data["error_message"] = error_message

        if status == TaskStatus.PATCHING:
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

    @staticmethod
    async def update_task_name(
        db: AsyncSession, task_id: str, task_name: str
    ) -> Optional[TrainingTask]:
        """
        Update training task name.

        Args:
            db: Database session
            task_id: Task ID
            task_name: New task name

        Returns:
            Updated TrainingTask object or None if not found
        """
        update_data = {"task_name": task_name, "updated_at": utc_now()}

        await db.execute(
            update(TrainingTask)
            .where(TrainingTask.task_id == task_id)
            .values(**update_data)
        )
        await db.flush()
        return await TrainingTaskRepository.get_by_id(db, task_id)

    @staticmethod
    async def update_preprocessing_config(
        db: AsyncSession,
        task_id: str,
        preprocessing_config: Dict[str, Any],
    ) -> Optional[TrainingTask]:
        """Update a training task's preprocessing_config JSON blob."""
        await db.execute(
            update(TrainingTask)
            .where(TrainingTask.task_id == task_id)
            .values(preprocessing_config=preprocessing_config, updated_at=utc_now())
        )
        await db.flush()
        return await TrainingTaskRepository.get_by_id(db, task_id)

    # Status values that indicate a task was interrupted (not failed normally)
    # and can be claimed for recovery by a restarted process.
    # - 'pending': legacy pre-queue status before the route updates to 'queued'
    # - 'queued': task was accepted into the in-memory queue but not yet started
    # - 'patching', 'extracting', 'training': task was actively processing
    # Note: 'resuming' is intentionally excluded here to preserve CAS (compare-and-swap)
    # safety in try_claim_for_resume(). See RECOVERABLE_STATUSES for the full set.
    INTERRUPTED_STATUSES = [
        TaskStatus.PENDING,
        TaskStatus.QUEUED,
        TaskStatus.PATCHING,
        TaskStatus.EXTRACTING,
        TaskStatus.TRAINING,
    ]

    # All statuses that need recovery on restart, including 'resuming'.
    # 'resuming' means a previous restart claimed the task but the pipeline never started
    # (e.g., due to another crash or process restart). These tasks must be re-submitted
    # to the queue without going through CAS again.
    RECOVERABLE_STATUSES = INTERRUPTED_STATUSES + [TaskStatus.RESUMING]

    @staticmethod
    async def get_interrupted_tasks(db: AsyncSession) -> List[TrainingTask]:
        """
        Get all training tasks that need recovery (e.g., after system shutdown).

        These are tasks with status 'pending', 'queued', 'patching', 'extracting',
        'training', or 'resuming' - states that indicate the task was queued, in progress, or
        claimed for resume but never completed or failed.

        Note: 'failed' tasks are NOT considered interrupted - they failed normally.
        Note: 'pending' and 'queued' tasks are included because the in-memory queue
              is lost on restart.
        Note: 'resuming' tasks are included because a previous restart may have claimed
              them but the pipeline never started (e.g., due to another crash).
        """
        result = await db.execute(
            select(TrainingTask)
            .options(
                selectinload(TrainingTask.data_group)
            )  # Eagerly load data_group for resume
            .where(TrainingTask.status.in_(TrainingTaskRepository.RECOVERABLE_STATUSES))
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
        update it to 'patching' (WSI tasks) or 'training' (patch tasks) when it starts.

        Returns:
            True if this instance successfully claimed the task
            False if another instance already claimed it or task not found
        """
        result = await db.execute(
            update(TrainingTask)
            .where(TrainingTask.task_id == task_id)
            .where(TrainingTask.status.in_(TrainingTaskRepository.INTERRUPTED_STATUSES))
            .values(
                status="resuming",  # Temporary until pipeline starts (different from 'pending' for CAS)
                error_message=None,  # Clear previous error if any
                updated_at=utc_now(),
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

        # Delete associated WSI records
        await db.execute(
            delete(TrainingTaskWSI).where(TrainingTaskWSI.task_id == task_id)
        )

        # Delete associated trained models
        await db.execute(delete(TrainedModel).where(TrainedModel.task_id == task_id))

        # Delete associated training logs
        await db.execute(delete(TrainingLog).where(TrainingLog.task_id == task_id))

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

        # Only delete failed/cancelled tasks older than cutoff (keep completed tasks permanently)
        finished_statuses = ["failed", "cancelled"]

        # First get task_ids to delete (for cascade cleanup)
        result = await db.execute(
            select(TrainingTask.task_id).where(
                TrainingTask.status.in_(finished_statuses),
                TrainingTask.finished_at < cutoff,
            )
        )
        task_ids_to_delete = [row[0] for row in result.all()]

        if not task_ids_to_delete:
            return 0

        # Delete associated WSI records
        await db.execute(
            delete(TrainingTaskWSI).where(
                TrainingTaskWSI.task_id.in_(task_ids_to_delete)
            )
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
