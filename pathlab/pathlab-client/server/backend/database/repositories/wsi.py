"""
WSIRepository - Data Access Layer
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy import select, update, delete, func, desc, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

from ..models import DataGroup, Dataset, WSISlide, utc_now
from backend.common.file_types import WSI_EXTENSIONS, PATCH_EXTENSIONS, TIF_EXTENSIONS, SIZE_THRESHOLD


def _dataset_with_group_loader():
    return selectinload(WSISlide.dataset).selectinload(Dataset.data_group)


class WSIRepository:
    """Repository for WSI Slide operations"""

    @staticmethod
    def _has_elevated_dataset_access(
        dataset_id: Optional[str],
        elevated_dataset_ids: Optional[List[str]] = None,
    ) -> bool:
        return bool(dataset_id and elevated_dataset_ids and dataset_id in elevated_dataset_ids)

    @staticmethod
    def _build_visibility_filter(
        user_id: Optional[str] = None,
        elevated_dataset_ids: Optional[List[str]] = None,
    ):
        if user_id is None:
            return None
        if elevated_dataset_ids:
            return or_(
                WSISlide.user_id == user_id,
                WSISlide.dataset_id.in_(elevated_dataset_ids),
            )
        return WSISlide.user_id == user_id

    @staticmethod
    def _build_dataset_membership_filter(dataset_id: str):
        if dataset_id == "Uncategorized":
            return WSISlide.dataset_id.is_(None)
        return WSISlide.dataset_id == dataset_id

    @staticmethod
    def _build_dataset_filters(
        dataset_id: str,
        user_id: Optional[str] = None,
        data_type: Optional[str] = None,
        search: Optional[str] = None,
        elevated_dataset_ids: Optional[List[str]] = None,
    ) -> List:
        filters = [WSIRepository._build_dataset_membership_filter(dataset_id)]

        if user_id is not None and not WSIRepository._has_elevated_dataset_access(dataset_id, elevated_dataset_ids):
            filters.append(WSISlide.user_id == user_id)

        data_type_filter = WSIRepository._build_data_type_filter(data_type)
        if data_type_filter is not None:
            filters.append(data_type_filter)

        search_filter = WSIRepository._build_search_filter(search)
        if search_filter is not None:
            filters.append(search_filter)

        return filters

    @staticmethod
    def _build_path_extension_filter(extensions):
        path_lower = func.lower(WSISlide.wsi_path)
        return or_(*[path_lower.like(f'%{ext}') for ext in extensions])

    @staticmethod
    def _build_file_level_data_type_conditions():
        tif_path_filter = WSIRepository._build_path_extension_filter(TIF_EXTENSIONS)
        is_wsi = or_(
            WSIRepository._build_path_extension_filter(WSI_EXTENSIONS),
            and_(tif_path_filter, WSISlide.file_size >= SIZE_THRESHOLD),
        )
        is_patch = or_(
            WSIRepository._build_path_extension_filter(PATCH_EXTENSIONS),
            and_(
                tif_path_filter,
                or_(
                    WSISlide.file_size < SIZE_THRESHOLD,
                    WSISlide.file_size.is_(None),
                ),
            ),
        )
        return is_wsi, is_patch

    @staticmethod
    def _build_file_level_data_type_filter(target_type: str):
        is_wsi, is_patch = WSIRepository._build_file_level_data_type_conditions()
        return is_wsi if target_type == "wsi" else is_patch

    @staticmethod
    async def get_by_id_with_dataset(db: AsyncSession, wsi_id: str) -> Optional[WSISlide]:
        """Get WSI by wsi_id with dataset relationship loaded"""
        result = await db.execute(
            select(WSISlide).options(_dataset_with_group_loader()).where(WSISlide.wsi_id == wsi_id)
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
        For datasets exceeding batch_size, queries are batched for memory efficiency.

        Args:
            db: Database session
            wsi_ids: List of WSI IDs to fetch
            batch_size: Number of IDs per batch (default 500)

        Returns:
            Dict mapping wsi_id to WSISlide for found slides
        """
        if not wsi_ids:
            return {}

        result_dict: Dict[str, WSISlide] = {}

        # Batch query for memory efficiency with large ID lists
        for i in range(0, len(wsi_ids), batch_size):
            batch_ids = wsi_ids[i:i + batch_size]
            result = await db.execute(
                select(WSISlide)
                .options(_dataset_with_group_loader())
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
            batch_size: Number of IDs per batch (default 500)

        Returns:
            Dict mapping wsi_id to WSISlide for found slides
        """
        if not wsi_ids:
            return {}

        result_dict: Dict[str, WSISlide] = {}

        # Batch query for memory efficiency with large ID lists
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
        query = select(WSISlide).options(_dataset_with_group_loader())

        visibility_filter = WSIRepository._build_visibility_filter(user_id, elevated_dataset_ids)
        if visibility_filter is not None:
            query = query.where(visibility_filter)

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
        query = select(func.count(WSISlide.id))

        visibility_filter = WSIRepository._build_visibility_filter(user_id, elevated_dataset_ids)
        if visibility_filter is not None:
            query = query.where(visibility_filter)

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
            # but for simplicity relative to list size, individual updates are acceptable
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
        if data_type in {"wsi", "patch"}:
            file_level_filter = WSIRepository._build_file_level_data_type_filter(data_type)
            dataset_level_filter = WSISlide.dataset.has(
                Dataset.data_group.has(DataGroup.data_type == data_type)
            )
            ungrouped_fallback = and_(
                or_(
                    WSISlide.dataset_id.is_(None),
                    WSISlide.dataset.has(Dataset.group_id.is_(None)),
                ),
                file_level_filter,
            )
            return or_(dataset_level_filter, ungrouped_fallback)
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
        from sqlalchemy import case, and_

        is_wsi, is_patch = WSIRepository._build_file_level_data_type_conditions()
        user_filter = WSIRepository._build_visibility_filter(user_id, elevated_dataset_ids)

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

        # Query for datasets (with join to Dataset and DataGroup tables)
        # Chat upload-related context must use only the authoritative dataset
        # data_type from DataGroup. Do not derive a "mixed" state or apply
        # file-count heuristics here.
        from ..models import Dataset, DataGroup

        # Build data_type case expressions
        is_wsi_case = case((is_wsi, 1), else_=0)
        is_patch_case = case((is_patch, 1), else_=0)
        split_unit_identifier = case(
            (DataGroup.aggregation_level == 'case', func.coalesce(WSISlide.case_id, WSISlide.wsi_id)),
            else_=WSISlide.wsi_id,
        )

        datasets_query = select(
            Dataset.dataset_id,
            Dataset.name.label("dataset_name"),
            Dataset.user_id.label("dataset_owner_id"),
            DataGroup.data_type.label("group_data_type"),
            DataGroup.task_type.label("group_task_type"),
            func.count(WSISlide.id).label("file_count"),
            func.sum(is_wsi_case).label("wsi_count"),
            func.sum(is_patch_case).label("patch_count")
        ).select_from(WSISlide).outerjoin(
            Dataset, WSISlide.dataset_id == Dataset.dataset_id
        ).outerjoin(
            DataGroup, Dataset.group_id == DataGroup.group_id
        )

        if user_filter is not None:
            datasets_query = datasets_query.where(user_filter)

        datasets_query = datasets_query.group_by(
            Dataset.dataset_id,
            Dataset.name,
            Dataset.user_id,
            DataGroup.data_type,
            DataGroup.task_type,
        ).order_by(Dataset.name)
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
            func.count(func.distinct(case(
                (func.lower(WSISlide.split) == 'train', split_unit_identifier),
                else_=None,
            ))).label("split_train_count"),
            func.count(func.distinct(case(
                (or_(func.lower(WSISlide.split) == 'val', func.lower(WSISlide.split) == 'validation'), split_unit_identifier),
                else_=None,
            ))).label("split_val_count"),
            func.count(func.distinct(case(
                (func.lower(WSISlide.split) == 'test', split_unit_identifier),
                else_=None,
            ))).label("split_test_count"),
        ).select_from(WSISlide).outerjoin(
            Dataset, WSISlide.dataset_id == Dataset.dataset_id
        ).outerjoin(
            DataGroup, Dataset.group_id == DataGroup.group_id
        )

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
                "has_predefined_splits": (train_count + val_count + test_count) > 0,
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
            group_data_type = row.group_data_type if row.group_data_type in {"wsi", "patch"} else None
            data_type = group_data_type or "unknown"

            ds_labels = dataset_labels_map.get(row.dataset_id, {})
            survival_count = dataset_survival_map.get(row.dataset_id, 0)
            splits_info = dataset_splits_map.get(row.dataset_id, {"has_predefined_splits": False, "train": 0, "val": 0, "test": 0})
            event_status_dist = dataset_event_status_map.get(row.dataset_id, {})

            # Determine access_type: "own" if user owns it, "elevated" if via temporary permission
            if (
                user_id is not None
                and row.dataset_owner_id != user_id
                and WSIRepository._has_elevated_dataset_access(row.dataset_id, elevated_dataset_ids)
            ):
                access_type = "elevated"
            else:
                access_type = "own"

            datasets.append({
                "dataset_id": row.dataset_id,
                "dataset_name": row.dataset_name or "Uncategorized",
                "file_count": row.file_count,
                "data_type": data_type,
                "group_task_type": row.group_task_type,  # DataGroup task_type: 'classification', 'survival', 'segmentation'
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
        from sqlalchemy import case

        is_wsi, is_patch = WSIRepository._build_file_level_data_type_conditions()

        # Count WSI and Patch
        query = select(
            func.sum(case((is_wsi, 1), else_=0)).label("wsi_count"),
            func.sum(case((is_patch, 1), else_=0)).label("patch_count")
        )

        visibility_filter = WSIRepository._build_visibility_filter(user_id)
        if visibility_filter is not None:
            query = query.where(visibility_filter)

        result = await db.execute(query)
        row = result.one()

        return {
            "wsi": row.wsi_count or 0,
            "patch": row.patch_count or 0
        }

    @staticmethod
    def _build_dataset_summary_query(
        data_type: Optional[str] = None,
        user_id: Optional[str] = None,
        elevated_dataset_ids: Optional[List[str]] = None,
        search: Optional[str] = None,
        dataset_id: Optional[str] = None,
        task_type: Optional[str] = None,
        aggregation_level: Optional[str] = None,
        source_organ: Optional[str] = None,
    ):
        from sqlalchemy import case

        # Dataset list should trust stored DataGroup data_type for grouped datasets.
        # Only uncategorized/ungrouped files fall back to file-level heuristics.
        file_filter = WSIRepository._build_data_type_filter(data_type)

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
            func.min(func.nullif(func.trim(WSISlide.source), '')).label("source_organ"),
            func.count(func.distinct(case(
                (func.lower(WSISlide.split) == 'train', case(
                    (DataGroup.aggregation_level == 'case', func.coalesce(WSISlide.case_id, WSISlide.wsi_id)),
                    else_=WSISlide.wsi_id,
                )),
                else_=None,
            ))).label("split_train_count"),
            func.count(func.distinct(case(
                (or_(func.lower(WSISlide.split) == 'val', func.lower(WSISlide.split) == 'validation'), case(
                    (DataGroup.aggregation_level == 'case', func.coalesce(WSISlide.case_id, WSISlide.wsi_id)),
                    else_=WSISlide.wsi_id,
                )),
                else_=None,
            ))).label("split_val_count"),
            func.count(func.distinct(case(
                (func.lower(WSISlide.split) == 'test', case(
                    (DataGroup.aggregation_level == 'case', func.coalesce(WSISlide.case_id, WSISlide.wsi_id)),
                    else_=WSISlide.wsi_id,
                )),
                else_=None,
            ))).label("split_test_count"),
        ).select_from(WSISlide).outerjoin(
            Dataset, WSISlide.dataset_id == Dataset.dataset_id
        ).outerjoin(
            DataGroup, Dataset.group_id == DataGroup.group_id
        )

        visibility_filter = WSIRepository._build_visibility_filter(user_id, elevated_dataset_ids)
        if visibility_filter is not None:
            query = query.where(visibility_filter)

        if file_filter is not None:
            query = query.where(file_filter)

        normalized_search = search.strip() if search else None
        if normalized_search:
            query = query.where(Dataset.name.ilike(f"%{normalized_search}%"))

        if dataset_id:
            query = query.where(Dataset.dataset_id == dataset_id)

        if task_type:
            query = query.where(DataGroup.task_type == task_type)

        if aggregation_level:
            query = query.where(DataGroup.aggregation_level == aggregation_level)

        if source_organ:
            normalized_source = source_organ.strip()
            if normalized_source:
                source_expr = func.coalesce(func.nullif(func.trim(WSISlide.source), ''), '__unknown__')
                query = query.where(source_expr == normalized_source)

        return query.group_by(
            Dataset.dataset_id, Dataset.name, Dataset.user_id, Dataset.group_id,
            DataGroup.data_type, DataGroup.aggregation_level, DataGroup.task_type
        )

    @staticmethod
    async def count_datasets(
        db: AsyncSession,
        data_type: Optional[str] = None,
        user_id: Optional[str] = None,
        elevated_dataset_ids: Optional[List[str]] = None,
        search: Optional[str] = None,
        dataset_id: Optional[str] = None,
        task_type: Optional[str] = None,
        aggregation_level: Optional[str] = None,
        source_organ: Optional[str] = None,
    ) -> int:
        """Count datasets visible under the current filter set."""
        grouped_query = WSIRepository._build_dataset_summary_query(
            data_type=data_type,
            user_id=user_id,
            elevated_dataset_ids=elevated_dataset_ids,
            search=search,
            dataset_id=dataset_id,
            task_type=task_type,
            aggregation_level=aggregation_level,
            source_organ=source_organ,
        )
        result = await db.execute(select(func.count()).select_from(grouped_query.subquery()))
        return result.scalar() or 0

    @staticmethod
    async def get_datasets(
        db: AsyncSession,
        data_type: Optional[str] = None,
        user_id: Optional[str] = None,
        elevated_dataset_ids: Optional[List[str]] = None,
        search: Optional[str] = None,
        dataset_id: Optional[str] = None,
        task_type: Optional[str] = None,
        aggregation_level: Optional[str] = None,
        source_organ: Optional[str] = None,
        skip: int = 0,
        limit: int = 0,
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
        query = WSIRepository._build_dataset_summary_query(
            data_type=data_type,
            user_id=user_id,
            elevated_dataset_ids=elevated_dataset_ids,
            search=search,
            dataset_id=dataset_id,
            task_type=task_type,
            aggregation_level=aggregation_level,
            source_organ=source_organ,
        ).order_by(Dataset.name)

        if skip > 0:
            query = query.offset(skip)
        if limit > 0:
            query = query.limit(limit)

        result = await db.execute(query)
        datasets = []
        for row in result.all():
            train_count = row.split_train_count or 0
            val_count = row.split_val_count or 0
            test_count = row.split_test_count or 0
            has_predefined_splits = (train_count + val_count + test_count) > 0

            dataset_dict = {
                "dataset_id": row.dataset_id,  # UUID for API calls
                "dataset_name": row.dataset_name or "Uncategorized",  # Display name
                "user_id": row.dataset_user_id,  # Dataset owner
                "group_id": row.group_id,
                "data_type": row.data_type,  # wsi or patch (for frontend display)
                "aggregation_level": row.aggregation_level,  # file or case
                "task_type": row.task_type or "classification",  # classification, survival
                "source_organ": row.source_organ,
                "file_count": row.file_count,
                "total_size": row.total_size or 0,
                "has_predefined_splits": has_predefined_splits,
                "predefined_split_unit": "cases" if row.aggregation_level == "case" else "files",
                "predefined_split_counts": {
                    "train": train_count,
                    "val": val_count,
                    "test": test_count
                }
            }

            # For segmentation datasets, fetch COCO categories from annotation files
            if row.task_type == "segmentation" and row.dataset_id:
                coco_categories = await WSIRepository._get_coco_categories_for_dataset(db, row.dataset_id)
                if coco_categories:
                    dataset_dict["coco_categories"] = coco_categories
                    dataset_dict["num_coco_categories"] = len(coco_categories)
                else:
                    dataset_dict["num_coco_categories"] = 0

            datasets.append(dataset_dict)
        return datasets

    @staticmethod
    async def _get_coco_categories_for_dataset(db: AsyncSession, dataset_id: str) -> List[Dict]:
        """
        Extract COCO categories from segmentation annotations stored in DB.

        Looks up SegmentationAnnotation records linked to this dataset_id
        and extracts categories from the COCO JSON.

        Args:
            db: Database session
            dataset_id: Dataset UUID

        Returns:
            List of category dicts with id, name, and optionally supercategory
        """
        from backend.database.models import SegmentationAnnotation

        # Query annotations linked to this dataset
        query = select(SegmentationAnnotation).where(
            SegmentationAnnotation.source_dataset_id == dataset_id
        ).limit(1)

        result = await db.execute(query)
        annotation = result.scalar_one_or_none()

        if not annotation or not annotation.annotations:
            return []

        try:
            coco_data = annotation.annotations
            if not isinstance(coco_data, dict):
                return []

            # Extract categories from COCO format
            categories = coco_data.get('categories', [])
            if not categories:
                # Legacy format: categories as dict { "0": "label", ... }
                return []

            # Handle list format (standard COCO)
            if isinstance(categories, list):
                return [
                    {
                        "id": cat.get("id"),
                        "name": cat.get("name"),
                        "supercategory": cat.get("supercategory")
                    }
                    for cat in categories
                    if cat.get("id") is not None and cat.get("name")
                ]

            # Handle dict format { "0": "label", "1": "label2" }
            if isinstance(categories, dict):
                return [
                    {"id": int(cat_id), "name": cat_name}
                    for cat_id, cat_name in categories.items()
                ]

            return []
        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.warning(f"Failed to extract COCO categories for dataset {dataset_id}: {e}")
            return []

    @staticmethod
    async def get_by_dataset(
        db: AsyncSession,
        dataset_id: str,
        skip: int = 0,
        limit: int = 0,
        user_id: Optional[str] = None,
        data_type: Optional[str] = None,
        search: Optional[str] = None,
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
            search: Optional search term matched against filename/case/label/source/wsi_id
            elevated_dataset_ids: Optional list of dataset IDs that the user has temporary elevated permissions for.
                                  If the requested dataset_id is in this list, user_id filter is bypassed.

        Returns:
            List of WSISlide objects with dataset relationship loaded
        """
        query = select(WSISlide).options(_dataset_with_group_loader())
        filters = WSIRepository._build_dataset_filters(
            dataset_id,
            user_id=user_id,
            data_type=data_type,
            search=search,
            elevated_dataset_ids=elevated_dataset_ids,
        )
        query = query.where(*filters)

        query = query.order_by(desc(WSISlide.created_at)).offset(skip)
        if limit > 0:
            query = query.limit(limit)

        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def get_ids_by_dataset(
        db: AsyncSession,
        dataset_id: str,
        user_id: Optional[str] = None,
        data_type: Optional[str] = None,
        search: Optional[str] = None,
        elevated_dataset_ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Get matching WSI IDs in a dataset without loading full slide objects."""
        query = select(WSISlide.wsi_id)
        filters = WSIRepository._build_dataset_filters(
            dataset_id,
            user_id=user_id,
            data_type=data_type,
            search=search,
            elevated_dataset_ids=elevated_dataset_ids,
        )
        query = query.where(*filters)

        query = query.order_by(desc(WSISlide.created_at))

        result = await db.execute(query)
        return [row[0] for row in result.all()]

    @staticmethod
    async def count_by_dataset(
        db: AsyncSession,
        dataset_id: str,
        user_id: Optional[str] = None,
        data_type: Optional[str] = None,
        search: Optional[str] = None,
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
            search: Optional search term matched against filename/case/label/source/wsi_id
            elevated_dataset_ids: Optional list of dataset IDs that the user has temporary elevated permissions for.
                                  If the requested dataset_id is in this list, user_id filter is bypassed.

        Returns:
            Number of WSI slides in the dataset
        """
        query = select(func.count(WSISlide.id))
        filters = WSIRepository._build_dataset_filters(
            dataset_id,
            user_id=user_id,
            data_type=data_type,
            search=search,
            elevated_dataset_ids=elevated_dataset_ids,
        )
        query = query.where(*filters)

        result = await db.execute(query)
        return result.scalar_one()

    @staticmethod
    async def get_dataset_cache_key(db: AsyncSession, dataset_id: str) -> dict:
        """Return a lightweight cache key for WSI membership/metadata in a dataset."""
        query = select(func.count(WSISlide.id), func.max(WSISlide.updated_at))

        if dataset_id == "Uncategorized":
            query = query.where(WSISlide.dataset_id.is_(None))
        else:
            query = query.where(WSISlide.dataset_id == dataset_id)

        result = await db.execute(query)
        count, latest_updated_at = result.one()
        return {
            "count": int(count or 0),
            "latest_updated_at": latest_updated_at.isoformat() if latest_updated_at else None,
        }

    # ------------------------------------------------------------------
    # Search helper
    # ------------------------------------------------------------------

    @staticmethod
    def _build_search_filter(search: Optional[str]):
        """Build ILIKE filter across searchable columns.

        Matches original_filename, case_id, label, source, wsi_id.
        Returns None when *search* is empty/None.
        """
        if not search or not search.strip():
            return None
        from sqlalchemy import or_
        pattern = f"%{search.strip()}%"
        return or_(
            WSISlide.original_filename.ilike(pattern),
            WSISlide.case_id.ilike(pattern),
            WSISlide.label.ilike(pattern),
            WSISlide.source.ilike(pattern),
            WSISlide.wsi_id.ilike(pattern),
        )

    # ------------------------------------------------------------------
    # Case-level pagination helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def count_cases_by_dataset(
        db: AsyncSession,
        dataset_id: str,
        search: Optional[str] = None,
        user_id: Optional[str] = None,
        data_type: Optional[str] = None,
        elevated_dataset_ids: Optional[List[str]] = None,
    ) -> dict:
        """Count distinct case groups for case-level pagination.

        A "case" is a distinct non-NULL case_id.  Files with NULL case_id
        are each treated as individual pagination units.

        Returns dict with keys:
            named_case_count  – number of distinct non-NULL case_ids
            no_case_count     – number of files without case_id
            total_cases       – named_case_count + no_case_count (each uncased file = 1 unit)
            total_files       – total matching file count
            has_multi_slide_cases – whether any case_id has more than one file
        """
        from sqlalchemy import case, literal_column

        filters = WSIRepository._build_dataset_filters(
            dataset_id,
            user_id=user_id,
            data_type=data_type,
            search=search,
            elevated_dataset_ids=elevated_dataset_ids,
        )

        # named_case_count
        q_named = select(func.count(func.distinct(WSISlide.case_id))).where(
            WSISlide.case_id.isnot(None), *filters
        )
        named_case_count = (await db.execute(q_named)).scalar_one()

        # no_case_count (files without case_id)
        q_no_case = select(func.count(WSISlide.id)).where(
            WSISlide.case_id.is_(None), *filters
        )
        no_case_count = (await db.execute(q_no_case)).scalar_one()

        # total files
        q_total = select(func.count(WSISlide.id)).where(*filters)
        total_files = (await db.execute(q_total)).scalar_one()

        total_cases = named_case_count + no_case_count

        # has_multi_slide_cases: any non-NULL case_id with count > 1
        q_multi = (
            select(func.count())
            .select_from(
                select(WSISlide.case_id)
                .where(WSISlide.case_id.isnot(None), *filters)
                .group_by(WSISlide.case_id)
                .having(func.count(WSISlide.id) > 1)
                .subquery()
            )
        )
        multi_count = (await db.execute(q_multi)).scalar_one()
        has_multi_slide_cases = multi_count > 0

        return {
            "named_case_count": named_case_count,
            "no_case_count": no_case_count,
            "total_cases": total_cases,
            "total_files": total_files,
            "has_multi_slide_cases": has_multi_slide_cases,
        }

    @staticmethod
    async def get_by_dataset_case_paginated(
        db: AsyncSession,
        dataset_id: str,
        page: int = 1,
        page_size: int = 10,
        search: Optional[str] = None,
        user_id: Optional[str] = None,
        data_type: Optional[str] = None,
        elevated_dataset_ids: Optional[List[str]] = None,
    ) -> List[WSISlide]:
        """Fetch files for a *page* of case groups.

        Ordering: named cases alphabetically by case_id first, then the
        ``__no_case__`` group (NULL case_id files) last.

        Each named case_id counts as 1 page unit; each file without case_id
        counts as 1 individual page unit (paginated with OFFSET/LIMIT).

        Returns the list of WSISlide objects belonging to the cases on the
        requested page (with dataset relationship loaded).
        """
        filters = WSIRepository._build_dataset_filters(
            dataset_id,
            user_id=user_id,
            data_type=data_type,
            search=search,
            elevated_dataset_ids=elevated_dataset_ids,
        )

        # Step 1: Get paginated named case_ids
        offset = (page - 1) * page_size
        q_case_ids = (
            select(WSISlide.case_id)
            .where(WSISlide.case_id.isnot(None), *filters)
            .group_by(WSISlide.case_id)
            .order_by(WSISlide.case_id)
            .offset(offset)
            .limit(page_size)
        )
        case_ids_result = await db.execute(q_case_ids)
        page_case_ids = [row[0] for row in case_ids_result.all()]

        results: List[WSISlide] = []

        # Step 2: Fetch files for the named cases
        if page_case_ids:
            q_files = (
                select(WSISlide)
                .options(_dataset_with_group_loader())
                .where(WSISlide.case_id.in_(page_case_ids), *filters)
                .order_by(WSISlide.case_id, desc(WSISlide.created_at))
            )
            file_result = await db.execute(q_files)
            results.extend(file_result.scalars().all())

        # Step 3: Check if __no_case__ files fall on this page
        # __no_case__ files are individually paginated after all named cases.
        # Compute offset into uncased files based on how many page slots remain.
        q_named_count = select(func.count(func.distinct(WSISlide.case_id))).where(
            WSISlide.case_id.isnot(None), *filters
        )
        named_count = (await db.execute(q_named_count)).scalar_one()

        # __no_case__ files start at virtual index = named_count (0-based)
        no_case_index = named_count
        page_start = offset
        page_end = offset + page_size  # exclusive
        if page_end > no_case_index:
            # This page overlaps with the uncased-file region — paginate them
            no_case_offset = max(0, page_start - no_case_index)
            # How many named-case slots were consumed on this page
            named_on_page = len(page_case_ids)
            no_case_limit = page_size - named_on_page
            if no_case_limit > 0:
                q_no_case = (
                    select(WSISlide)
                    .options(_dataset_with_group_loader())
                    .where(WSISlide.case_id.is_(None), *filters)
                    .order_by(desc(WSISlide.created_at))
                    .offset(no_case_offset)
                    .limit(no_case_limit)
                )
                no_case_result = await db.execute(q_no_case)
                results.extend(no_case_result.scalars().all())

        return results

    @staticmethod
    async def bulk_update_feature_extracted(
        db: AsyncSession, wsi_ids: List[str], extracted: bool = True
    ) -> int:
        """Bulk update feature_extracted flag for multiple WSIs.

        Args:
            db: Database session
            wsi_ids: List of WSI IDs to update
            extracted: Value to set (default True)

        Returns:
            Number of rows updated
        """
        if not wsi_ids:
            return 0
        total_updated = 0
        batch_size = 500
        for i in range(0, len(wsi_ids), batch_size):
            batch = wsi_ids[i:i + batch_size]
            result = await db.execute(
                update(WSISlide)
                .where(WSISlide.wsi_id.in_(batch))
                .values(feature_extracted=extracted)
            )
            total_updated += result.rowcount
        return total_updated


