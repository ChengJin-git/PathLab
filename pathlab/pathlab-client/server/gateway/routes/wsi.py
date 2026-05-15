"""
WSI management routes
Handles WSI CRUD operations, file uploads, and metadata management

Authentication & Authorization:
- All endpoints require authentication (current_active_user)
- Users can only see their own data (filtered by user_id)
- Admin users can see all data
- Upload operations require pathologist or admin role
"""

import asyncio
import csv
import io
from pathlib import Path
from typing import Optional, List, Dict, Set, Literal, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete as sql_delete
from sklearn.exceptions import NotFittedError

from gateway.chat.context_cache import invalidate_chat_context
from backend.database import get_db
from backend.database.repositories import (
    WSIRepository,
    DatasetRepository,
    DataGroupRepository,
    AIResultRepository,
    SegmentationAnnotationRepository,
    DatasetStatsRepository,
)
from backend.database.models import AIResult, AITask, TrainingTaskWSI
from backend.common.split_generation import (
    generate_split_assignments,
    load_segmentation_multilabels,
)
from backend.ai.task_taxonomy import is_canonical_task_type, is_segmentation_task, is_survival_task
from backend.auth import current_active_user, User
from backend.auth.dependencies import (
    require_pathologist_or_admin,
    get_dataset_with_access,
    get_permitted_dataset_ids,
    get_user_id_filter,
    get_wsi_with_access,
)
from backend.annotation.summary_cache import (
    load_dataset_annotation_summary_cache,
    is_dataset_annotation_summary_cache_valid,
)
from ..dependencies import logger, storage_manager
from ..models import (
    DeletionMode,
    WSIMetadataUpdateRequest,
    DatasetRenameRequest,
    DatasetUpdateTypeRequest,
    DatasetUpdateDataLevelRequest,
    DatasetUpdateSourceRequest,
)
from ..utils import (
    ensure_coords_ready,
    get_effective_wsi_data_type,
    ensure_segmentation_contract,
    ensure_dataset_segmentation_contract,
    SEGMENTATION_TASK_TYPE,
)

router = APIRouter(prefix="/wsi", tags=["WSI Management"])

from .wsi_grants import router as wsi_grants_router

router.include_router(wsi_grants_router)


def _normalize_annotation_file_key(file_name: Optional[str]) -> Optional[str]:
    if not file_name:
        return None
    normalized = Path(str(file_name)).name.strip().lower()
    return normalized or None


def _build_segmentation_wsi_lookups(wsis) -> tuple[Dict[str, str], Dict[str, str]]:
    exact_lookup: Dict[str, str] = {}
    stem_candidates: Dict[str, Set[str]] = {}

    for wsi in wsis:
        candidates = [
            str(getattr(wsi, "original_filename", "") or "").strip(),
            str(getattr(wsi, "wsi_path", "") or "").strip(),
        ]
        for candidate in candidates:
            key = _normalize_annotation_file_key(candidate)
            if not key:
                continue
            exact_lookup[key] = wsi.wsi_id
            stem_candidates.setdefault(Path(key).stem, set()).add(wsi.wsi_id)

    stem_lookup = {
        stem: next(iter(wsi_ids))
        for stem, wsi_ids in stem_candidates.items()
        if len(wsi_ids) == 1
    }
    return exact_lookup, stem_lookup


def _build_split_wsi_lookups(wsis) -> tuple[Dict[str, Any], Dict[str, Any], Set[str]]:
    exact_lookup: Dict[str, Any] = {}
    stem_candidates: Dict[str, Dict[str, Any]] = {}

    for wsi in wsis:
        for candidate in (
            getattr(wsi, "original_filename", None),
            getattr(wsi, "wsi_path", None),
        ):
            key = _normalize_annotation_file_key(candidate)
            if not key:
                continue
            exact_lookup[key] = wsi
            stem_candidates.setdefault(Path(key).stem, {})[wsi.wsi_id] = wsi

    stem_lookup = {
        stem: next(iter(candidates.values()))
        for stem, candidates in stem_candidates.items()
        if len(candidates) == 1
    }
    ambiguous_stems = {
        stem for stem, candidates in stem_candidates.items() if len(candidates) > 1
    }
    return exact_lookup, stem_lookup, ambiguous_stems


def _resolve_split_wsi_by_filename(
    filename: str,
    exact_lookup: Dict[str, Any],
    stem_lookup: Dict[str, Any],
    ambiguous_stems: Set[str],
):
    key = _normalize_annotation_file_key(filename)
    if not key:
        return None

    if key in exact_lookup:
        return exact_lookup[key]

    stem = Path(key).stem
    if stem in ambiguous_stems:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Ambiguous filename '{filename}' in CSV. Include the full filename "
                "with extension to match the target slide."
            ),
        )

    return stem_lookup.get(stem)


def _get_wsi_data_type(wsi) -> str:
    return get_effective_wsi_data_type(wsi)


def _is_split_stratification_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return isinstance(exc, (ValueError, NotFittedError)) and any(
        token in message
        for token in (
            "least populated class",
            "n_splits",
            "test_size",
            "train_size",
            "number of groups",
            "minimum number of groups",
            "inconsistent numbers of samples",
        )
    )


def _build_export_fieldnames(task_type: str) -> List[str]:
    common = ["filename", "case_id", "age", "gender", "split"]
    if is_survival_task(task_type):
        return [
            "filename",
            "event_time",
            "event_status",
            "case_id",
            "age",
            "gender",
            "split",
        ]
    if is_segmentation_task(task_type):
        return common
    return ["filename", "label", *common[1:]]


def _build_export_row(wsi, task_type: str, split_value: str) -> Dict[str, object]:
    row: Dict[str, object] = {
        "filename": wsi.original_filename,
        "case_id": wsi.case_id or "",
        "age": wsi.age if wsi.age is not None else "",
        "gender": wsi.gender or "",
        "split": split_value,
    }
    if is_survival_task(task_type):
        row["event_time"] = wsi.event_time if wsi.event_time is not None else ""
        row["event_status"] = wsi.event_status if wsi.event_status is not None else ""
    elif not is_segmentation_task(task_type):
        row["label"] = wsi.label or ""
    return row


def _generate_split_assignments(
    wsis,
    *,
    dataset_id: str,
    aggregation_level: str,
    task_type: str,
    strategy: str,
    n_splits: int,
    seed: int,
    stratified: bool,
    train_ratio: float,
    val_ratio: float,
    test_ratio: float,
    segmentation_multilabels: Dict[str, Set[str]],
) -> tuple[Dict[str, str], bool]:
    split_config: Dict[str, object] = {
        "strategy": strategy,
        "seed": seed,
        "stratified": stratified,
    }
    if strategy == "k_fold":
        split_config["n_splits"] = n_splits
    else:
        split_config["ratios"] = {
            "train": train_ratio,
            "val": val_ratio,
            "test": test_ratio,
        }

    survival_task = is_survival_task(task_type)
    segmentation_task = is_segmentation_task(task_type)
    splitter_task_type = (
        "segmentation" if segmentation_task else "survival" if survival_task else "classification"
    )

    if survival_task:
        labels = {
            wsi.wsi_id: str(wsi.event_status)
            for wsi in wsis
            if wsi.event_status is not None
        }
    elif segmentation_task:
        labels = {}
    else:
        labels = {wsi.wsi_id: wsi.label for wsi in wsis if wsi.label}

    wsi_ids = [wsi.wsi_id for wsi in wsis]

    try:
        return generate_split_assignments(
            wsis,
            aggregation_level=aggregation_level,
            task_type=splitter_task_type,
            split_config=split_config,
            segmentation_multilabels=segmentation_multilabels,
        )
    except Exception as exc:
        if _is_split_stratification_error(exc):
            logger.warning(
                "Export label split fallback triggered: dataset_id=%s, task_type=%s, aggregation_level=%s, strategy=%s, stratified=%s. "
                "Reason=%s. Falling back to non-stratified split generation.",
                dataset_id,
                task_type,
                aggregation_level,
                strategy,
                stratified,
                exc,
            )
            fallback_config = dict(split_config)
            fallback_config["stratified"] = False
            assignments, _ = generate_split_assignments(
                wsis,
                aggregation_level=aggregation_level,
                task_type=splitter_task_type,
                split_config=fallback_config,
                segmentation_multilabels=segmentation_multilabels,
            )
            return assignments, True
        raise


def _mark_coco_image_matches(
    payload: Optional[dict[str, Any]],
    *,
    exact_lookup: Dict[str, str],
    stem_lookup: Dict[str, str],
    presence_map: Dict[str, bool],
) -> None:
    if not isinstance(payload, dict):
        return

    for image in payload.get("images") or []:
        if not isinstance(image, dict):
            continue
        key = _normalize_annotation_file_key(image.get("file_name"))
        if not key:
            continue
        wsi_id = exact_lookup.get(key) or stem_lookup.get(Path(key).stem)
        if wsi_id in presence_map:
            presence_map[wsi_id] = True


async def _get_segmentation_annotation_presence_map(
    db: AsyncSession,
    dataset_id: str,
    wsis,
) -> Dict[str, bool]:
    presence_map = {wsi.wsi_id: False for wsi in wsis}
    if not presence_map:
        return presence_map

    try:
        finalized_annotations_key = (
            await SegmentationAnnotationRepository.get_finalized_dataset_cache_key(
                db,
                dataset_id,
            )
        )
        wsi_key = await WSIRepository.get_dataset_cache_key(db, dataset_id)
        cache_data = load_dataset_annotation_summary_cache(dataset_id)
        if is_dataset_annotation_summary_cache_valid(
            cache_data, finalized_annotations_key, wsi_key
        ):
            slide_summaries = (cache_data or {}).get("slides") or {}
            for wsi_id in presence_map:
                presence_map[wsi_id] = wsi_id in slide_summaries
            return presence_map
    except Exception as cache_err:
        logger.warning(
            f"Failed to resolve segmentation annotation cache for {dataset_id}: {cache_err}"
        )

    page_records = (
        await SegmentationAnnotationRepository.get_finalized_for_wsis_or_dataset(
            db,
            dataset_id,
            list(presence_map.keys()),
        )
    )
    if not page_records:
        return presence_map

    exact_lookup, stem_lookup = _build_segmentation_wsi_lookups(wsis)
    for record in page_records:
        annotation_id = str(getattr(record, "annotation_id", "") or "")
        if annotation_id.startswith("label_"):
            inferred_wsi_id = annotation_id[len("label_") :]
            if inferred_wsi_id in presence_map:
                presence_map[inferred_wsi_id] = True
        _mark_coco_image_matches(
            getattr(record, "annotations", None),
            exact_lookup=exact_lookup,
            stem_lookup=stem_lookup,
            presence_map=presence_map,
        )

    return presence_map


async def _load_segmentation_multilabels(
    db: AsyncSession,
    dataset_id: str,
    wsis,
) -> Dict[str, Set[str]]:
    records = await SegmentationAnnotationRepository.get_all_by_dataset(
        db,
        dataset_id,
        include_drafts=False,
    )
    if not records:
        return {}

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
    if not payloads:
        return {}

    def _build_multilabels() -> Dict[str, Set[str]]:
        merged_coco = merge_coco_datasets(payloads)
        exact_lookup, stem_lookup = _build_segmentation_wsi_lookups(wsis)
        return extract_coco_wsi_label_sets(merged_coco, exact_lookup, stem_lookup)

    return await asyncio.to_thread(_build_multilabels)


async def _serialize_dataset_wsi_items(
    db: AsyncSession,
    dataset_id: str,
    wsi_slides,
    *,
    is_admin: bool,
    user_id_str: str,
) -> List[dict[str, Any]]:
    annotation_presence: Dict[str, bool] = {}
    dataset_data_type: Optional[str] = None

    if dataset_id != "Uncategorized":
        dataset = await DatasetRepository.get_by_id(db, dataset_id)
        dataset_data_type = (
            dataset.data_group.data_type if dataset and dataset.data_group else None
        )
        task_type = (
            dataset.data_group.task_type if dataset and dataset.data_group else None
        )
        if task_type == SEGMENTATION_TASK_TYPE:
            annotation_presence = await _get_segmentation_annotation_presence_map(
                db, dataset_id, wsi_slides
            )

    items = []
    for wsi in wsi_slides:
        item = wsi.to_summary_dict()
        item["data_type"] = dataset_data_type or _get_wsi_data_type(wsi)
        item["can_delete"] = is_admin or (wsi.user_id == user_id_str)
        if annotation_presence:
            item["has_segmentation_annotation"] = annotation_presence.get(
                wsi.wsi_id, False
            )
        items.append(item)
    return items


@router.get("")
async def list_wsi(
    dataset_id: Optional[str] = Query(None, description="Filter by dataset UUID"),
    data_type: Optional[str] = Query(
        None,
        description="Filter by data type: 'wsi' for WSI files, 'patch' for image files",
    ),
    search: Optional[str] = Query(
        None, description="Search across filename, case_id, label, source, wsi_id"
    ),
    page: int = Query(
        1, ge=1, description="Page number (1-based) for case-level pagination"
    ),
    page_size: int = Query(
        10,
        ge=0,
        le=10000,
        description="Number of case groups per page. 0 = return all (no pagination).",
    ),
    sort_by: Optional[str] = Query(
        None,
        description="Sort field: original_filename, label, event_time, event_status",
    ),
    sort_order: str = Query(
        "asc",
        description="Sort direction: asc or desc",
    ),
    user: User = Depends(current_active_user),
    user_id_filter: Optional[str] = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db),
):
    """List WSI slides with server-side case-level pagination.

    When dataset_id is provided, pagination is case-level:
    - Each distinct case_id is one page unit
    - Files without case_id are individually paginated (one file = one page unit)
    - Response includes total_cases, has_multi_slide_cases metadata

    When dataset_id is NOT provided, falls back to file-level pagination
    (page/page_size converted to skip/limit).

    Data visibility:
    - Admin users can see all WSI slides
    - Other users can see:
      - Their own WSI slides
      - WSI slides in datasets they have temporary elevated permissions for
    """
    # Get elevated dataset IDs for non-admin users
    elevated_dataset_ids = await get_permitted_dataset_ids(user, db)

    user_id_str = str(user.id)
    is_admin = user.is_admin()

    if dataset_id is not None:
        if page_size == 0:
            # ---- No pagination: return ALL files in this dataset ----
            wsi_slides = await WSIRepository.get_by_dataset(
                db,
                dataset_id,
                skip=0,
                limit=0,
                user_id=user_id_filter,
                data_type=data_type,
                search=search,
                elevated_dataset_ids=elevated_dataset_ids,
                sort_by=sort_by,
                sort_order=sort_order,
            )
            total = await WSIRepository.count_by_dataset(
                db,
                dataset_id,
                user_id=user_id_filter,
                data_type=data_type,
                search=search,
                elevated_dataset_ids=elevated_dataset_ids,
            )
            items = await _serialize_dataset_wsi_items(
                db,
                dataset_id,
                wsi_slides,
                is_admin=is_admin,
                user_id_str=user_id_str,
            )
            return {
                "items": items,
                "total": total,
                "total_cases": 0,
                "page": 1,
                "page_size": 0,
                "has_multi_slide_cases": False,
            }

        # ---- Case-level pagination (dataset view) ----
        case_meta = await WSIRepository.count_cases_by_dataset(
            db,
            dataset_id,
            search=search,
            user_id=user_id_filter,
            data_type=data_type,
            elevated_dataset_ids=elevated_dataset_ids,
        )
        wsi_slides = await WSIRepository.get_by_dataset_case_paginated(
            db,
            dataset_id,
            page=page,
            page_size=page_size,
            search=search,
            user_id=user_id_filter,
            data_type=data_type,
            elevated_dataset_ids=elevated_dataset_ids,
            sort_by=sort_by,
            sort_order=sort_order,
            named_count=case_meta["named_case_count"],
        )

        items = await _serialize_dataset_wsi_items(
            db,
            dataset_id,
            wsi_slides,
            is_admin=is_admin,
            user_id_str=user_id_str,
        )

        return {
            "items": items,
            "total": case_meta["total_files"],
            "total_cases": case_meta["total_cases"],
            "page": page,
            "page_size": page_size,
            "has_multi_slide_cases": case_meta["has_multi_slide_cases"],
        }
    else:
        if page_size == 0:
            # ---- No pagination: return ALL files ----
            wsi_slides = await WSIRepository.get_all_with_dataset(
                db,
                skip=0,
                limit=0,
                user_id=user_id_filter,
                data_type=data_type,
                elevated_dataset_ids=elevated_dataset_ids,
            )
            total = await WSIRepository.count(
                db,
                user_id=user_id_filter,
                data_type=data_type,
                elevated_dataset_ids=elevated_dataset_ids,
            )
        else:
            # ---- File-level pagination (all-datasets view) ----
            skip = (page - 1) * page_size
            wsi_slides = await WSIRepository.get_all_with_dataset(
                db,
                skip=skip,
                limit=page_size,
                user_id=user_id_filter,
                data_type=data_type,
                elevated_dataset_ids=elevated_dataset_ids,
            )
            total = await WSIRepository.count(
                db,
                user_id=user_id_filter,
                data_type=data_type,
                elevated_dataset_ids=elevated_dataset_ids,
            )

        items = []
        for wsi in wsi_slides:
            item = wsi.to_summary_dict()
            item["data_type"] = _get_wsi_data_type(wsi)
            item["can_delete"] = is_admin or (wsi.user_id == user_id_str)
            items.append(item)

        return {
            "items": items,
            "total": total,
            "total_cases": 0,
            "page": page,
            "page_size": page_size,
            "has_multi_slide_cases": False,
        }


@router.get("/ids")
async def list_wsi_ids(
    dataset_id: str = Query(..., description="Filter by dataset UUID"),
    data_type: Optional[str] = Query(
        None,
        description="Filter by data type: 'wsi' for WSI files, 'patch' for image files",
    ),
    search: Optional[str] = Query(
        None, description="Search across filename, case_id, label, source, wsi_id"
    ),
    user: User = Depends(current_active_user),
    user_id_filter: Optional[str] = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db),
):
    """Return only matching WSI IDs for lightweight bulk selection flows."""
    elevated_dataset_ids = await get_permitted_dataset_ids(user, db)

    items = await WSIRepository.get_ids_by_dataset(
        db,
        dataset_id,
        user_id=user_id_filter,
        data_type=data_type,
        search=search,
        elevated_dataset_ids=elevated_dataset_ids,
    )
    total = await WSIRepository.count_by_dataset(
        db,
        dataset_id,
        user_id=user_id_filter,
        data_type=data_type,
        search=search,
        elevated_dataset_ids=elevated_dataset_ids,
    )

    return {"items": items, "total": total}


@router.get("/datasets")
async def list_datasets(
    data_type: Optional[str] = None,
    search: Optional[str] = Query(None, description="Search dataset names"),
    task_type: Optional[str] = Query(None, description="Filter by task type"),
    aggregation_level: Optional[str] = Query(
        None, description="Filter by aggregation level"
    ),
    source_organ: Optional[str] = Query(
        None, description="Filter by normalized source organ"
    ),
    page: int = Query(
        1, ge=1, description="Page number (1-based). Ignored when page_size=0."
    ),
    page_size: int = Query(
        0,
        ge=0,
        le=100,
        description="Datasets per page. 0 = return all (legacy behavior).",
    ),
    user: User = Depends(current_active_user),
    user_id_filter: Optional[str] = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db),
):
    """
    List all datasets with file count and total size.

    Data visibility:
    - Admin users can see all datasets
    - Other users can see:
      - Datasets containing their own WSI slides
      - Datasets they have temporary elevated permissions for

    Args:
        data_type: Optional filter - "wsi" for WSI files, "patch" for image files
        search: Optional dataset name search
        page: 1-based page number when pagination is enabled
        page_size: page size, 0 keeps legacy all-in-one behavior

    Returns:
        {
            "items": [
                {"dataset_id": str, "dataset_name": str, "file_count": int, "total_size": int, "task_type": str},
                ...
            ],
            "total": int,
            "page": int,
            "page_size": int
        }
    """
    # Get elevated dataset IDs for non-admin users
    elevated_dataset_ids = await get_permitted_dataset_ids(user, db)
    skip = 0 if page_size == 0 else (page - 1) * page_size

    datasets, total = await WSIRepository.get_datasets_with_total(
        db,
        data_type=data_type,
        user_id=user_id_filter,
        elevated_dataset_ids=elevated_dataset_ids,
        search=search,
        task_type=task_type,
        aggregation_level=aggregation_level,
        source_organ=source_organ,
        skip=skip,
        limit=page_size,
    )

    # Add can_delete flag to each dataset
    # User can delete if: admin OR owns the dataset
    user_id_str = str(user.id)
    is_admin = user.is_admin()

    # For admin users, batch-lookup usernames for all dataset owners
    username_map: dict[str, Any] = {}
    if is_admin:
        from sqlalchemy import select as sql_select, cast, String
        from backend.auth.models import User as AuthUser

        owner_ids = list({d.get("user_id") for d in datasets if d.get("user_id")})
        if owner_ids:
            result = await db.execute(
                sql_select(
                    cast(AuthUser.id, String), AuthUser.username, AuthUser.nickname
                ).where(cast(AuthUser.id, String).in_(owner_ids))
            )
            for uid, username, nickname in result.all():
                username_map[uid] = nickname or username or None

    items = []
    for dataset in datasets:
        # can_delete: True if admin or user owns the dataset
        dataset["can_delete"] = is_admin or (dataset.get("user_id") == user_id_str)
        # Add username for admin users
        if is_admin:
            dataset["username"] = (
                username_map.get(dataset.get("user_id"))
                if dataset.get("user_id")
                else None
            )
        items.append(dataset)

    return {
        "items": items,
        "total": total,
        "page": 1 if page_size == 0 else page,
        "page_size": page_size,
    }


@router.get("/datasets/{dataset_id}")
async def get_dataset_summary(
    dataset_id: str,
    user: User = Depends(current_active_user),
    user_id_filter: Optional[str] = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db),
):
    """Return one dataset summary row for repository/detail pages."""
    elevated_dataset_ids = await get_permitted_dataset_ids(user, db)
    datasets = await WSIRepository.get_datasets(
        db,
        user_id=user_id_filter,
        elevated_dataset_ids=elevated_dataset_ids,
        dataset_id=dataset_id,
        skip=0,
        limit=1,
    )

    if not datasets:
        raise HTTPException(status_code=404, detail="Dataset not found")

    dataset = datasets[0]
    user_id_str = str(user.id)
    dataset["can_delete"] = user.is_admin() or (dataset.get("user_id") == user_id_str)

    if user.is_admin() and dataset.get("user_id"):
        from sqlalchemy import select as sql_select, cast, String
        from backend.auth.models import User as AuthUser

        result = await db.execute(
            sql_select(AuthUser.username, AuthUser.nickname).where(
                cast(AuthUser.id, String) == dataset["user_id"]
            )
        )
        owner = result.one_or_none()
        dataset["username"] = (owner.nickname or owner.username) if owner else None

    return dataset


@router.put("/datasets")
async def rename_dataset(
    req: DatasetRenameRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Rename a dataset (update display name).
    All authenticated users can rename their own datasets, admin can rename any.

    Args:
        dataset_id: UUID of the dataset
        new_name: New display name
    """
    try:
        dataset = await get_dataset_with_access(
            req.dataset_id,
            user,
            db,
            require_owner=True,
            not_found_detail=f"Dataset not found: {req.dataset_id}",
            forbidden_detail="You don't have permission to rename this dataset",
        )

        updated = await DatasetRepository.update(db, req.dataset_id, name=req.new_name)
        await db.commit()
        await invalidate_chat_context(str(user.id))
        return {"message": "Dataset renamed successfully", "dataset": updated.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to rename dataset: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to rename dataset: {str(e)}"
        )


@router.put("/datasets/{dataset_id}/type")
async def update_dataset_type(
    dataset_id: str,
    req: DatasetUpdateTypeRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update dataset task type by modifying DataGroup reference.

    - To change to 'survival': Sets event_time=0 and event_status=0 for all WSIs that don't have event_time
    - To change to 'classification': Clears event_time and event_status for all WSIs

    This updates the dataset's DataGroup reference while preserving data_type and aggregation_level.

    All authenticated users can update their own datasets, admin can update any.

    Args:
        dataset_id: UUID of the dataset
        req: DatasetUpdateTypeRequest with task_type ("classification" or "survival")
    """
    try:
        # Validate task_type
        if not is_canonical_task_type(req.task_type):
            raise HTTPException(
                status_code=400,
                detail="task_type must be one of the canonical training task ids",
            )

        # Check dataset exists (with data_group loaded)
        dataset = await get_dataset_with_access(
            dataset_id,
            user,
            db,
            require_owner=True,
            not_found_detail=f"Dataset not found: {dataset_id}",
            forbidden_detail="You don't have permission to update this dataset",
        )

        # Get current DataGroup to preserve data_type and aggregation_level
        current_data_group = dataset.data_group
        if not current_data_group:
            raise HTTPException(
                status_code=400, detail="Dataset has no associated DataGroup"
            )
        ensure_dataset_segmentation_contract(dataset, context="Dataset update")

        if is_segmentation_task(req.task_type):
            ensure_segmentation_contract(
                req.task_type,
                current_data_group.data_type,
                current_data_group.aggregation_level,
                context="Dataset update",
            )

        # Get all WSIs in this dataset
        from sqlalchemy import update as sql_update
        from backend.database.models import WSISlide

        if is_survival_task(req.task_type):
            # Set default event_time=0, event_status=0 for WSIs without event_time
            result = await db.execute(
                sql_update(WSISlide)
                .where(WSISlide.dataset_id == dataset_id)
                .where(WSISlide.event_time.is_(None))
                .values(event_time=0.0, event_status=0)
            )
            updated_count = result.rowcount
            message = f"Dataset type changed to survival. Set default event_time/status for {updated_count} slides."
        elif is_segmentation_task(req.task_type):
            result = await db.execute(
                sql_update(WSISlide)
                .where(WSISlide.dataset_id == dataset_id)
                .values(label=None, event_time=None, event_status=None)
            )
            updated_count = result.rowcount
            message = (
                f"Dataset type changed to segmentation. Cleared image-level labels and survival metadata "
                f"for {updated_count} slides."
            )
        else:
            # Clear event_time and event_status for all WSIs
            result = await db.execute(
                sql_update(WSISlide)
                .where(WSISlide.dataset_id == dataset_id)
                .values(event_time=None, event_status=None)
            )
            updated_count = result.rowcount
            message = f"Dataset type changed to classification. Cleared event_time/status for {updated_count} slides."

        # Get or create new DataGroup with updated task_type
        new_data_group = await DataGroupRepository.get_or_create(
            db,
            data_type=current_data_group.data_type,
            aggregation_level=current_data_group.aggregation_level,
            task_type=req.task_type,
        )

        # Update dataset's group_id
        await DatasetRepository.update(db, dataset_id, group_id=new_data_group.group_id)

        await db.commit()
        await invalidate_chat_context(str(user.id))

        logger.info(
            f"Updated dataset {dataset_id} type to {req.task_type}: {updated_count} WSIs affected"
        )

        return {
            "message": message,
            "dataset_id": dataset_id,
            "new_type": req.task_type,
            "updated_count": updated_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update dataset type: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update dataset type: {str(e)}"
        )


@router.put("/datasets/{dataset_id}/data-level")
async def update_dataset_data_level(
    dataset_id: str,
    req: DatasetUpdateDataLevelRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update dataset aggregation level (case-level or file-level).

    - case: Slides are grouped by case_id. For survival datasets, all slides in a case
            must have the same event_time/event_status.
    - file: Each slide is independent (default).

    This updates the dataset's DataGroup reference while preserving data_type and task_type.

    All authenticated users can update their own datasets, admin can update any.

    Args:
        dataset_id: UUID of the dataset
        req: DatasetUpdateDataLevelRequest with aggregation_level ("case" or "file")
    """
    try:
        aggregation_level = req.aggregation_level

        # Validate aggregation_level
        if aggregation_level not in ["case", "file"]:
            raise HTTPException(
                status_code=400, detail="aggregation_level must be 'case' or 'file'"
            )

        # Check dataset exists (with data_group loaded)
        dataset = await get_dataset_with_access(
            dataset_id,
            user,
            db,
            require_owner=True,
            not_found_detail=f"Dataset not found: {dataset_id}",
            forbidden_detail="You don't have permission to update this dataset",
        )

        # Get current DataGroup to preserve data_type and task_type
        current_group = dataset.data_group
        if not current_group:
            raise HTTPException(
                status_code=500, detail="Dataset has no associated DataGroup"
            )
        ensure_dataset_segmentation_contract(
            dataset, context="Dataset data-level update"
        )

        if is_segmentation_task(current_group.task_type) and aggregation_level != "file":
            raise HTTPException(
                status_code=400,
                detail="Segmentation datasets must keep aggregation_level='file'",
            )

        # If aggregation_level hasn't changed, no update needed
        if current_group.aggregation_level == aggregation_level:
            return {
                "message": f"Dataset aggregation level is already {aggregation_level}",
                "dataset_id": dataset_id,
                "new_aggregation_level": aggregation_level,
            }

        # Get or create a new DataGroup with the new aggregation_level
        new_group = await DataGroupRepository.get_or_create(
            db,
            data_type=current_group.data_type,
            aggregation_level=aggregation_level,
            task_type=current_group.task_type,
        )

        # Update dataset's group_id
        dataset.group_id = new_group.group_id
        await db.commit()
        await invalidate_chat_context(str(user.id))

        logger.info(
            f"Updated dataset {dataset_id} aggregation_level from {current_group.aggregation_level} to {aggregation_level}"
        )

        return {
            "message": f"Dataset aggregation level changed to {aggregation_level}",
            "dataset_id": dataset_id,
            "new_aggregation_level": aggregation_level,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update dataset data level: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update dataset data level: {str(e)}"
        )


@router.put("/datasets/{dataset_id}/source")
async def update_dataset_source(
    dataset_id: str,
    req: DatasetUpdateSourceRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update dataset source organ/tissue by applying the same source to all files in the dataset.

    Empty string clears the source, which will be shown as unknown in the dataset repository.
    All authenticated users can update their own datasets, admin can update any.
    """
    try:
        await get_dataset_with_access(
            dataset_id,
            user,
            db,
            require_owner=True,
            not_found_detail=f"Dataset not found: {dataset_id}",
            forbidden_detail="You don't have permission to update this dataset",
        )

        from sqlalchemy import update as sql_update
        from backend.database.models import WSISlide, Dataset

        normalized_source = req.source.strip() if isinstance(req.source, str) else None
        if normalized_source == "":
            normalized_source = None

        await db.execute(
            sql_update(Dataset)
            .where(Dataset.dataset_id == dataset_id)
            .values(source_organ=normalized_source)
        )
        result = await db.execute(
            sql_update(WSISlide)
            .where(WSISlide.dataset_id == dataset_id)
            .values(source=normalized_source)
        )
        await db.commit()
        await invalidate_chat_context(str(user.id))

        logger.info(
            f"Updated dataset {dataset_id} source to {normalized_source!r}: {result.rowcount} WSIs affected"
        )

        return {
            "message": "Dataset source updated successfully",
            "dataset_id": dataset_id,
            "source": normalized_source,
            "updated_count": result.rowcount,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update dataset source: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update dataset source: {str(e)}"
        )


@router.post("/check-duplicates")
async def check_duplicate_filenames(
    filenames: List[str],
    user_id_filter: Optional[str] = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db),
):
    """
    Check which filenames already exist in the database.
    Only checks against the current user's files (admin sees all).

    This endpoint is used by the frontend to skip uploading files
    that already exist (based on original_filename).

    For special formats:
    - MRXS: Check by the .mrxs filename (e.g., "slide.mrxs")
    - TMAP: Check by the .tmap filename (e.g., "slide.tmap")
    - Standard: Check by the full filename (e.g., "slide.svs")

    Args:
        filenames: List of filenames to check

    Returns:
        {
            "duplicates": ["slide1.svs", "slide2.mrxs"],  # filenames that exist
            "new": ["slide3.ndpi"]  # filenames that don't exist
        }
    """
    if not filenames:
        return {"duplicates": [], "new": []}

    existing = await WSIRepository.get_existing_original_filenames(
        db, filenames, user_id=user_id_filter
    )
    existing_set = set(existing)

    duplicates = [f for f in filenames if f in existing_set]
    new_files = [f for f in filenames if f not in existing_set]

    return {"duplicates": duplicates, "new": new_files}


@router.get("/{wsi_id}")
async def get_wsi(
    wsi_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get WSI metadata and latest result.
    Users can access their own WSI, WSI in datasets they have elevated permissions for, or admin can access all."""
    wsi = await get_wsi_with_access(
        wsi_id,
        user,
        db,
        with_dataset=True,
        not_found_detail="wsi_id not found",
        forbidden_detail="You don't have permission to access this WSI",
    )

    # Get latest result
    last_result = await AIResultRepository.get_by_wsi_id(db, wsi_id)

    # Build response with can_delete flag
    meta = wsi.to_dict()
    meta["data_type"] = _get_wsi_data_type(wsi)
    # can_delete: True if admin or user owns the WSI
    meta["can_delete"] = user.is_admin() or (wsi.user_id == str(user.id))

    return {
        "wsi_id": wsi_id,
        "meta": meta,
        "last_run": last_result.to_dict() if last_result else None,
    }


@router.delete("/{wsi_id}")
async def delete_wsi(
    wsi_id: str,
    mode: DeletionMode = DeletionMode.STANDARD,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a WSI and its associated data.
    All authenticated users can delete their own WSI, admin can delete any.

    This will:
    1. Delete training task associations (TrainingTaskWSI)
    2. Delete all AI results associated with this WSI
    3. Delete all AI tasks associated with this WSI
    4. Delete the WSI record from database
    5. Delete WSI files using StorageManager (mode-dependent):

    Standard mode (recommended):
       - WSI file itself
       - Coordinates cache
       - Thumbnail
       - Mask
       - AI results directory
       - Keep training features (valuable for research)

    Complete mode:
       - All files from standard mode
       - Feature files from all training tasks

    Args:
        wsi_id: The WSI ID to delete
        mode: Deletion mode (DeletionMode.STANDARD or DeletionMode.COMPLETE)

    Returns:
        {
            "message": "WSI deleted successfully",
            "wsi_id": str,
            "storage_cleanup": dict  # Storage cleanup results
        }
    """
    try:
        # Get WSI from database
        wsi = await get_wsi_with_access(
            wsi_id,
            user,
            db,
            require_owner=True,
            not_found_detail=f"WSI not found: {wsi_id}",
            forbidden_detail="You don't have permission to delete this WSI",
        )

        wsi_path = wsi.wsi_path
        dataset_id = wsi.dataset_id

        # Delete all associated data before deleting the WSI
        # Using raw SQL for efficiency
        try:
            # Delete training task associations first (foreign key constraint)
            await db.execute(
                sql_delete(TrainingTaskWSI).where(TrainingTaskWSI.wsi_id == wsi_id)
            )

            # Delete AI results
            await db.execute(sql_delete(AIResult).where(AIResult.wsi_id == wsi_id))

            # Delete AI tasks
            await db.execute(sql_delete(AITask).where(AITask.wsi_id == wsi_id))
        except Exception as e:
            logger.warning(f"Failed to delete associated data for {wsi_id}: {e}")

        # Delete WSI from database
        await WSIRepository.delete(db, wsi_id)
        if dataset_id:
            await DatasetStatsRepository.recompute(db, dataset_id)
        await db.commit()
        await invalidate_chat_context(str(wsi.user_id or user.id))

        # Delete all files using StorageManager with specified mode
        storage_cleanup = storage_manager.delete_wsi_files(
            wsi_id, wsi_path, mode=mode.value
        )
        logger.info(storage_cleanup["summary"])

        return {
            "message": "WSI deleted successfully",
            "wsi_id": wsi_id,
            "storage_cleanup": storage_cleanup,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete WSI: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete WSI: {str(e)}")


@router.patch("/{wsi_id}")
async def update_wsi_metadata(
    wsi_id: str,
    req: WSIMetadataUpdateRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update WSI metadata (label, case_id, age, gender, event_time, event_status).
    All authenticated users can update their own WSI metadata, admin can update any.

    Args:
        wsi_id: The WSI ID to update
        req: WSIMetadataUpdateRequest containing fields to update

    Returns:
        Updated WSI metadata
    """
    try:
        # Get WSI from database (with dataset for to_dict())
        wsi = await get_wsi_with_access(
            wsi_id,
            user,
            db,
            require_owner=True,
            with_dataset=True,
            not_found_detail=f"WSI not found: {wsi_id}",
            forbidden_detail="You don't have permission to update this WSI",
        )

        dataset = (
            await DatasetRepository.get_by_id(db, wsi.dataset_id)
            if wsi.dataset_id
            else None
        )
        dataset_task_type = (
            dataset.data_group.task_type if dataset and dataset.data_group else None
        )
        if dataset_task_type == SEGMENTATION_TASK_TYPE and req.label is not None:
            raise HTTPException(
                status_code=400,
                detail="Segmentation WSIs do not support image-level label updates",
            )

        # Update fields if provided
        if req.label is not None:
            wsi.label = req.label
        if req.case_id is not None:
            wsi.case_id = req.case_id
        if req.age is not None:
            wsi.age = req.age
        if req.gender is not None:
            wsi.gender = req.gender
        # Survival analysis fields
        if req.event_time is not None:
            wsi.event_time = req.event_time
        if req.event_status is not None:
            wsi.event_status = req.event_status

        await db.commit()
        await invalidate_chat_context(str(wsi.user_id or user.id))

        # Re-fetch with dataset relationship to avoid lazy loading issues
        wsi = await WSIRepository.get_by_id_with_dataset(db, wsi_id)

        logger.info(f"Updated WSI metadata: {wsi_id}")

        return {"message": "WSI metadata updated successfully", "wsi": wsi.to_dict()}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update WSI metadata: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update WSI metadata: {str(e)}"
        )


@router.post("/{wsi_id}/compute_patches")
async def compute_patches(
    wsi_id: str,
    level: int = Query(0, description="Pyramid level (0 = highest resolution)"),
    force_recompute: bool = Query(
        False, description="Force recompute even if patches exist"
    ),
    seg_level: int = Query(
        -1, description="Pyramid level for tissue segmentation (-1 = auto)"
    ),
    sthresh: int = Query(
        5,
        description="Saturation threshold (0-255, low threshold for maximum tissue detection)",
    ),
    mthresh: int = Query(
        7, description="Median filter kernel size (must be odd, default: 7)"
    ),
    close: int = Query(4, description="Morphological closing kernel size (default: 4)"),
    use_otsu: bool = Query(False, description="Use Otsu auto-thresholding"),
    contour_fn: str = Query(
        "four_pt", description="Contour check function (four_pt, center, basic)"
    ),
    user: User = Depends(require_pathologist_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Proxy endpoint to compute patches via preprocessing service.
    Requires pathologist or admin role.
    Users can only compute patches for their own WSI, admin can compute for any.

    Note: patch_size and stride are auto-determined by PrePATH-style tiling
    based on WSI magnification to ensure consistent physical coverage (~128μm).

    This endpoint forwards the request to the preprocessing service
    to maintain a unified API interface through the Gateway.
    """
    logger.info(f"Proxying compute_patches request for WSI: {wsi_id}")

    # Verify WSI exists in database
    await get_wsi_with_access(
        wsi_id,
        user,
        db,
        require_owner=True,
        forbidden_detail="You don't have permission to compute patches for this WSI",
    )

    # Build query parameters (patch_size and stride are auto-determined by PrePATH-style tiling)
    params = {
        "level": level,
        "force_recompute": force_recompute,
        "seg_level": seg_level,
        "sthresh": sthresh,
        "mthresh": mthresh,
        "close": close,
        "use_otsu": use_otsu,
        "contour_fn": contour_fn,
    }

    result = await ensure_coords_ready(
        wsi_id,
        params=params,
        timeout=600.0,
    )
    logger.info(f"Successfully computed patches for WSI: {wsi_id}")
    return result


@router.post("/datasets/{dataset_id}/splits")
async def upload_dataset_splits(
    dataset_id: str,
    file: UploadFile = File(...),
    user: User = Depends(current_active_user),
    user_id_filter: Optional[str] = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a CSV/Excel file to define splits (train, val, test) and metadata for a dataset.
    All authenticated users can upload splits for their own datasets, admin can modify any.

    Supports CSV and Excel (.xlsx, .xls) formats. Frontend converts Excel files to CSV format.

    Args:
        dataset_id: Dataset UUID

    Required columns:
    - filename: The original filename of the WSI slide

    Optional columns:
    - split (train, val, test), label, case_id, age, gender, event_time, event_status

    If no 'val' split is provided, 10% of 'train' samples will be automatically
    assigned to 'val'.
    """
    # Validate file extension - accept CSV and Excel files (frontend converts Excel to CSV)
    allowed_extensions = (".csv", ".xlsx", ".xls")
    if not file.filename or not file.filename.lower().endswith(allowed_extensions):
        raise HTTPException(
            status_code=400, detail="Only CSV and Excel (.xlsx, .xls) files are allowed"
        )

    # Read and decode file content
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

    # Check file size (max 10MB)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds 10MB limit")

    # Decode as UTF-8 (utf-8-sig strips BOM if present — Excel often adds BOM to CSV)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400, detail="Invalid CSV file: not valid UTF-8 encoding"
        )

    # Parse CSV
    try:
        f = io.StringIO(text)
        reader = csv.DictReader(f)

        # Check columns exist
        if not reader.fieldnames:
            raise HTTPException(
                status_code=400, detail="CSV is empty or has no header row"
            )

        # Identify filename column (required)
        filename_key = next(
            (
                h
                for h in reader.fieldnames
                if h.strip().lower() in ["filename", "file_name", "original_filename"]
            ),
            None,
        )
        if not filename_key:
            raise HTTPException(
                status_code=400, detail="CSV must contain 'filename' column"
            )

        # Identify split column (optional)
        split_key = next(
            (h for h in reader.fieldnames if h.strip().lower() == "split"), None
        )

        rows = list(reader)
        if not rows:
            raise HTTPException(status_code=400, detail="CSV has no data rows")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {str(e)}")

    # Validate split values (only if split column exists)
    valid_splits = {"train", "val", "validation", "test"}
    if split_key:
        for i, row in enumerate(rows, start=2):  # start=2 because row 1 is header
            split_val = row.get(split_key, "").strip().lower()
            if split_val and split_val not in valid_splits:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid split value '{row.get(split_key)}' at row {i}. Allowed values: train, val, test",
                )

    # Validate dataset exists
    dataset = await get_dataset_with_access(
        dataset_id,
        user,
        db,
        require_owner=True,
        not_found_detail=f"Dataset not found: {dataset_id}",
        forbidden_detail="You don't have permission to modify this dataset",
    )

    # Get existing WSIs for mapping (only user's WSIs if not admin)
    wsis = await WSIRepository.get_by_dataset(db, dataset_id, user_id=user_id_filter)
    if not wsis:
        raise HTTPException(
            status_code=404, detail=f"No slides found in dataset: {dataset_id}"
        )

    exact_filename_map, stem_filename_map, ambiguous_filename_stems = (
        _build_split_wsi_lookups(wsis)
    )

    # Validate case-level + survival: all slides in a case must have same event_time/event_status
    # Access aggregation_level and task_type through the DataGroup relationship
    data_group = dataset.data_group
    aggregation_level = data_group.aggregation_level if data_group else "file"
    task_type = data_group.task_type if data_group else "wsi_classification"
    if task_type == SEGMENTATION_TASK_TYPE:
        label_key = (
            next((h for h in rows[0].keys() if h.strip().lower() == "label"), None)
            if rows
            else None
        )
        if label_key:
            invalid_rows = []
            for row_num, row in enumerate(rows, start=2):
                label_val = row.get(label_key, "")
                if isinstance(label_val, str) and label_val.strip():
                    invalid_rows.append(str(row_num))
                    if len(invalid_rows) >= 5:
                        break
            if invalid_rows:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Segmentation datasets do not support CSV label updates. "
                        "Remove the 'label' column values and use COCO category labels instead. "
                        f"Invalid rows: {', '.join(invalid_rows)}"
                    ),
                )
    if aggregation_level == "case" and is_survival_task(task_type):
        # Group rows by case_id to check for consistency
        case_groups = {}  # case_id -> [(event_time, event_status, filename), ...]
        case_id_key = (
            next((h for h in rows[0].keys() if h.strip().lower() == "case_id"), None)
            if rows
            else None
        )
        event_time_key = (
            next((h for h in rows[0].keys() if h.strip().lower() == "event_time"), None)
            if rows
            else None
        )
        event_status_key = (
            next(
                (h for h in rows[0].keys() if h.strip().lower() == "event_status"), None
            )
            if rows
            else None
        )

        if case_id_key and (event_time_key or event_status_key):
            for row in rows:
                case_id_val = row.get(case_id_key, "").strip()
                if not case_id_val:
                    continue

                event_time_val = (
                    row.get(event_time_key, "").strip() if event_time_key else None
                )
                event_status_val = (
                    row.get(event_status_key, "").strip() if event_status_key else None
                )
                fname = row.get(filename_key, "").strip()

                if case_id_val not in case_groups:
                    case_groups[case_id_val] = []
                case_groups[case_id_val].append(
                    {
                        "event_time": event_time_val,
                        "event_status": event_status_val,
                        "filename": fname,
                    }
                )

            # Check consistency within each case
            inconsistent_cases = []
            for case_id_val, entries in case_groups.items():
                if len(entries) <= 1:
                    continue  # Single slide case, no need to check

                first_time = entries[0]["event_time"]
                first_status = entries[0]["event_status"]

                for entry in entries[1:]:
                    if (
                        entry["event_time"] != first_time
                        or entry["event_status"] != first_status
                    ):
                        inconsistent_cases.append(
                            {
                                "case_id": case_id_val,
                                "files": [e["filename"] for e in entries],
                                "values": [
                                    (e["event_time"], e["event_status"])
                                    for e in entries
                                ],
                            }
                        )
                        break

            if inconsistent_cases:
                # Build error message
                error_details = []
                for ic in inconsistent_cases[:5]:  # Show max 5 cases in error
                    error_details.append(
                        f"Case '{ic['case_id']}': different event_time/event_status values found"
                    )
                error_msg = (
                    f"Case-level survival dataset requires all slides in a case to have the same "
                    f"event_time and event_status. Found {len(inconsistent_cases)} inconsistent case(s): "
                    + "; ".join(error_details)
                )
                raise HTTPException(status_code=400, detail=error_msg)

    updated_count = 0
    not_found_files = []

    for row in rows:
        fname = row.get(filename_key, "").strip()
        if not fname:
            continue

        target_wsi = _resolve_split_wsi_by_filename(
            fname,
            exact_filename_map,
            stem_filename_map,
            ambiguous_filename_stems,
        )

        if not target_wsi:
            not_found_files.append(fname)
            continue

        # Update split (only if split column exists)
        if split_key:
            split_val = row.get(split_key, "").strip().lower()
            if split_val:
                if split_val == "validation":
                    split_val = "val"
                target_wsi.split = split_val

        # Update other metadata if present
        for key, val in row.items():
            norm_key = key.strip().lower()
            if not val:
                continue

            val = val.strip()
            if norm_key == "label":
                if is_segmentation_task(task_type):
                    continue
                target_wsi.label = val
            elif norm_key == "case_id":
                target_wsi.case_id = val
            elif norm_key == "age":
                if val.isdigit():
                    target_wsi.age = int(val)
            elif norm_key == "gender":
                target_wsi.gender = val
            elif norm_key == "event_time":
                try:
                    target_wsi.event_time = float(val)
                except (ValueError, TypeError):
                    pass
            elif norm_key == "event_status":
                if val in ["0", "1"]:
                    target_wsi.event_status = int(val)

        updated_count += 1

    # Auto-create val split if empty
    # Count splits after update
    train_wsis = [w for w in wsis if w.split == "train"]
    val_wsis = [w for w in wsis if w.split == "val"]

    auto_val_count = 0
    if len(val_wsis) == 0 and len(train_wsis) > 0:
        import random

        n_val = max(1, int(len(train_wsis) * 0.1))
        # Shuffle and select
        random.shuffle(train_wsis)
        for i in range(min(n_val, len(train_wsis))):
            train_wsis[i].split = "val"
            auto_val_count += 1
        logger.info(
            f"Auto-created val split: moved {auto_val_count} samples from train to val"
        )

    await DatasetStatsRepository.recompute(db, dataset_id)
    await db.commit()
    await invalidate_chat_context(str(user.id))

    # Build response message
    message = f"Successfully updated {updated_count} slides from CSV"
    if auto_val_count > 0:
        message += f". Auto-assigned {auto_val_count} samples from train to val (10%)"
    if not_found_files:
        message += f". Warning: {len(not_found_files)} files not found in dataset"

    return {
        "message": message,
        "updated_count": updated_count,
        "auto_val_count": auto_val_count,
        "not_found_count": len(not_found_files),
        "not_found_files": not_found_files[:10]
        if not_found_files
        else [],  # Return first 10 for debugging
    }


@router.get("/datasets/{dataset_id}/export-labels")
async def export_dataset_labels(
    dataset_id: str,
    generate_split: bool = Query(
        False, description="Generate new split if no predefined split exists"
    ),
    strategy: Literal["random", "k_fold"] = Query(
        "random", description="Split strategy for generated splits"
    ),
    n_splits: int = Query(5, ge=2, le=20, description="Number of folds when strategy=k_fold"),
    seed: int = Query(42, description="Random seed for split generation"),
    stratified: bool = Query(
        True, description="Use stratified split (by label or event_status)"
    ),
    train_ratio: float = Query(0.7, ge=0.0, le=1.0, description="Training set ratio"),
    val_ratio: float = Query(0.1, ge=0.0, le=1.0, description="Validation set ratio"),
    test_ratio: float = Query(0.2, ge=0.0, le=1.0, description="Test set ratio"),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Export dataset labels as CSV file.

    Available to dataset owners and users with elevated access permissions.
    Non-blocking operation using StreamingResponse.

    If dataset has predefined splits, exports them directly.
    If generate_split=True and no predefined splits, generates splits using the same
    logic as training (respects file-level vs case-level aggregation).

    CSV columns vary by task_type and aggregation_level:
    - Classification (file-level): filename, label, case_id, age, gender, split
    - Classification (case-level): case_id, label, file_count, age, gender, split, filenames
    - Survival (file-level): filename, event_time, event_status, case_id, age, gender, split
    - Survival (case-level): case_id, event_time, event_status, file_count, age, gender, split, filenames
    """
    dataset = await get_dataset_with_access(
        dataset_id,
        user,
        db,
        require_owner=False,
        not_found_detail="Dataset not found",
        forbidden_detail="You don't have permission to export this dataset",
    )

    aggregation_level = (
        dataset.data_group.aggregation_level if dataset.data_group else "file"
    )
    task_type = dataset.data_group.task_type if dataset.data_group else "wsi_classification"

    # Get all WSI slides in dataset
    wsis = await WSIRepository.get_by_dataset(db, dataset_id, skip=0, limit=0)

    if not wsis:
        raise HTTPException(status_code=400, detail="Dataset is empty")

    # Check if dataset has predefined splits
    has_predefined_splits = any(wsi.split for wsi in wsis)

    # Determine splits
    splits: Dict[str, str] = {}
    split_fallback_applied = False

    if has_predefined_splits:
        # Use predefined splits
        splits = {wsi.wsi_id: wsi.split or "unknown" for wsi in wsis}
        logger.info(f"Exporting dataset {dataset_id} with predefined splits")
    elif generate_split:
        if strategy == "random":
            total_ratio = train_ratio + val_ratio + test_ratio
            if abs(total_ratio - 1.0) > 0.01:
                raise HTTPException(
                    status_code=400,
                    detail=f"Ratios must sum to 1.0, got {total_ratio:.2f}",
                )

        # Generate new splits using training logic
        logger.info(
            f"Generating splits for dataset {dataset_id}: aggregation_level={aggregation_level}, "
            f"task_type={task_type}, strategy={strategy}"
        )

        segmentation_multilabels: Dict[str, Set[str]] = {}
        if task_type == SEGMENTATION_TASK_TYPE:
            _, segmentation_multilabels = await load_segmentation_multilabels(db, wsis)

        split_config = {
            "strategy": strategy,
            "n_splits": n_splits,
            "seed": seed,
            "stratified": stratified,
            "ratios": {
                "train": train_ratio,
                "val": val_ratio,
                "test": test_ratio,
            },
        }
        splits, split_fallback_applied = _generate_split_assignments(
            wsis,
            dataset_id=dataset_id,
            aggregation_level=aggregation_level,
            task_type=task_type,
            strategy=strategy,
            n_splits=n_splits,
            seed=seed,
            stratified=stratified,
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            test_ratio=test_ratio,
            segmentation_multilabels=segmentation_multilabels,
        )

        logger.info(f"Generated splits for {len(splits)} items")
    else:
        # No splits - mark all as "unknown"
        splits = {wsi.wsi_id: "unknown" for wsi in wsis}

    # Generate CSV using streaming to avoid memory issues
    def generate_csv():
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=_build_export_fieldnames(task_type))
        writer.writeheader()
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        # Write one row per file, grouped by case_id for case-level datasets
        if aggregation_level == "case":
            case_groups: Dict[str, List[Any]] = {}
            for wsi in wsis:
                case_id = wsi.case_id or wsi.wsi_id
                if case_id not in case_groups:
                    case_groups[case_id] = []
                case_groups[case_id].append(wsi)
            ordered_wsis = [
                wsi for case_wsis in case_groups.values() for wsi in case_wsis
            ]
        else:
            ordered_wsis = wsis

        for wsi in ordered_wsis:
            row = _build_export_row(
                wsi,
                task_type=task_type,
                split_value=splits.get(wsi.wsi_id, "unknown"),
            )
            writer.writerow(row)
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{dataset.name}_labels_{timestamp}.csv"

    response_headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if split_fallback_applied:
        response_headers["X-PathLab-Export-Split-Fallback"] = "non_stratified"

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers=response_headers,
    )
