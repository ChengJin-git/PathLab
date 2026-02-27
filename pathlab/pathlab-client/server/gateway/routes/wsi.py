"""
WSI management routes
Handles WSI CRUD operations, file uploads, and metadata management

Authentication & Authorization:
- All endpoints require authentication (current_active_user)
- Users can only see their own data (filtered by user_id)
- Admin users can see all data
- Upload operations require pathologist or admin role
"""
import csv
import io
import httpx
from typing import Optional, List
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete as sql_delete

from backend.database import get_db
from backend.database.repositories import (
    WSIRepository,
    DatasetRepository,
    DataGroupRepository,
    AIResultRepository,
    DatasetPermissionRepository,
)
from backend.database.models import AIResult, AITask, TrainingTaskWSI
from backend.auth import current_active_user, User
from backend.auth.dependencies import require_pathologist_or_admin, check_data_ownership, get_user_id_filter, check_wsi_access_permission
from ..dependencies import logger, storage_manager, PREPROCESSING_SERVICE_URL
from ..models import DeletionMode, WSIMetadataUpdateRequest, DatasetRenameRequest, DatasetUpdateTypeRequest, DatasetUpdateDataLevelRequest

router = APIRouter(prefix="/wsi", tags=["WSI Management"])

# Include permissions sub-router FIRST — routes like /my-permissions must be
# registered before /{wsi_id} to avoid path parameter conflicts.
from .wsi_permissions import router as wsi_permissions_router
router.include_router(wsi_permissions_router)


@router.get("")
async def list_wsi(
    dataset_id: Optional[str] = Query(None, description="Filter by dataset UUID"),
    data_type: Optional[str] = Query(None, description="Filter by data type: 'wsi' for WSI files, 'patch' for image files"),
    search: Optional[str] = Query(None, description="Search across filename, case_id, label, source, wsi_id"),
    page: int = Query(1, ge=1, description="Page number (1-based) for case-level pagination"),
    page_size: int = Query(10, ge=0, le=10000, description="Number of case groups per page. 0 = return all (no pagination)."),
    user: User = Depends(current_active_user),
    user_id_filter: Optional[str] = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db)
):
    """List WSI slides with server-side case-level pagination.

    When dataset_id is provided, pagination is case-level:
    - Each distinct case_id is one page unit
    - All files without case_id form one __no_case__ group (always last)
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
    elevated_dataset_ids = None
    if not user.is_admin():
        permissions = await DatasetPermissionRepository.get_valid_by_user(db, str(user.id))
        elevated_dataset_ids = [p.dataset_id for p in permissions if p.is_valid()]

    user_id_str = str(user.id)
    is_admin = user.is_admin()

    if dataset_id is not None:
        if page_size == 0:
            # ---- No pagination: return ALL files in this dataset ----
            wsi_slides = await WSIRepository.get_by_dataset(
                db, dataset_id, skip=0, limit=0,
                user_id=user_id_filter, data_type=data_type,
                elevated_dataset_ids=elevated_dataset_ids,
            )
            total = await WSIRepository.count_by_dataset(
                db, dataset_id, user_id=user_id_filter, data_type=data_type,
                elevated_dataset_ids=elevated_dataset_ids,
            )
            items = []
            for wsi in wsi_slides:
                item = wsi.to_summary_dict()
                item["can_delete"] = is_admin or (wsi.user_id == user_id_str)
                items.append(item)
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
            db, dataset_id, search=search,
            user_id=user_id_filter, data_type=data_type,
            elevated_dataset_ids=elevated_dataset_ids,
        )
        wsi_slides = await WSIRepository.get_by_dataset_case_paginated(
            db, dataset_id, page=page, page_size=page_size,
            search=search, user_id=user_id_filter, data_type=data_type,
            elevated_dataset_ids=elevated_dataset_ids,
        )

        items = []
        for wsi in wsi_slides:
            item = wsi.to_summary_dict()
            item["can_delete"] = is_admin or (wsi.user_id == user_id_str)
            items.append(item)

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
                db, skip=0, limit=0,
                user_id=user_id_filter, data_type=data_type,
                elevated_dataset_ids=elevated_dataset_ids
            )
            total = await WSIRepository.count(
                db, user_id=user_id_filter, data_type=data_type,
                elevated_dataset_ids=elevated_dataset_ids
            )
        else:
            # ---- File-level pagination (all-datasets view) ----
            skip = (page - 1) * page_size
            wsi_slides = await WSIRepository.get_all_with_dataset(
                db, skip=skip, limit=page_size,
                user_id=user_id_filter, data_type=data_type,
                elevated_dataset_ids=elevated_dataset_ids
            )
            total = await WSIRepository.count(
                db, user_id=user_id_filter, data_type=data_type,
                elevated_dataset_ids=elevated_dataset_ids
            )

        items = []
        for wsi in wsi_slides:
            item = wsi.to_summary_dict()
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


@router.get("/datasets")
async def list_datasets(
    data_type: Optional[str] = None,
    user: User = Depends(current_active_user),
    user_id_filter: Optional[str] = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db)
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

    Returns:
        {
            "items": [
                {"dataset_id": str, "dataset_name": str, "file_count": int, "total_size": int, "task_type": str},
                ...
            ],
            "total": int
        }
    """
    # Get elevated dataset IDs for non-admin users
    elevated_dataset_ids = None
    if not user.is_admin():
        permissions = await DatasetPermissionRepository.get_valid_by_user(db, str(user.id))
        elevated_dataset_ids = [p.dataset_id for p in permissions if p.is_valid()]

    datasets = await WSIRepository.get_datasets(
        db,
        data_type=data_type,
        user_id=user_id_filter,
        elevated_dataset_ids=elevated_dataset_ids
    )

    # Add can_delete flag to each dataset
    # User can delete if: admin OR owns the dataset
    user_id_str = str(user.id)
    is_admin = user.is_admin()

    # For admin users, batch-lookup usernames for all dataset owners
    username_map: dict = {}
    if is_admin:
        from sqlalchemy import select as sql_select, cast, String
        from backend.auth.models import User as AuthUser
        owner_ids = list({d.get("user_id") for d in datasets if d.get("user_id")})
        if owner_ids:
            result = await db.execute(
                sql_select(cast(AuthUser.id, String), AuthUser.email, AuthUser.nickname)
                .where(cast(AuthUser.id, String).in_(owner_ids))
            )
            for uid, email, nickname in result.all():
                username_map[uid] = nickname or email or None

    items = []
    for dataset in datasets:
        # can_delete: True if admin or user owns the dataset
        dataset["can_delete"] = is_admin or (dataset.get("user_id") == user_id_str)
        # Add username for admin users
        if is_admin:
            dataset["username"] = username_map.get(dataset.get("user_id")) if dataset.get("user_id") else None
        items.append(dataset)

    return {"items": items, "total": len(items)}


@router.put("/datasets")
async def rename_dataset(
    req: DatasetRenameRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Rename a dataset (update display name).
    All authenticated users can rename their own datasets, admin can rename any.

    Args:
        dataset_id: UUID of the dataset
        new_name: New display name
    """
    try:
        dataset = await DatasetRepository.get_by_id(db, req.dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail=f"Dataset not found: {req.dataset_id}")

        # Check ownership (admin can rename any, others only their own)
        if not check_data_ownership(dataset.user_id, user):
            raise HTTPException(status_code=403, detail="You don't have permission to rename this dataset")

        updated = await DatasetRepository.update(db, req.dataset_id, {"name": req.new_name})
        await db.commit()
        return {"message": "Dataset renamed successfully", "dataset": updated.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to rename dataset: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to rename dataset: {str(e)}")


@router.put("/datasets/{dataset_id}/type")
async def update_dataset_type(
    dataset_id: str,
    req: DatasetUpdateTypeRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
        if req.task_type not in ["classification", "survival"]:
            raise HTTPException(status_code=400, detail="task_type must be 'classification' or 'survival'")

        # Check dataset exists (with data_group loaded)
        dataset = await DatasetRepository.get_by_id(db, dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

        # Check ownership (admin can update any, others only their own)
        if not check_data_ownership(dataset.user_id, user):
            raise HTTPException(status_code=403, detail="You don't have permission to update this dataset")

        # Get current DataGroup to preserve data_type and aggregation_level
        current_data_group = dataset.data_group
        if not current_data_group:
            raise HTTPException(status_code=400, detail="Dataset has no associated DataGroup")

        # Get all WSIs in this dataset
        from sqlalchemy import update as sql_update
        from backend.database.models import WSISlide

        if req.task_type == "survival":
            # Set default event_time=0, event_status=0 for WSIs without event_time
            result = await db.execute(
                sql_update(WSISlide)
                .where(WSISlide.dataset_id == dataset_id)
                .where(WSISlide.event_time.is_(None))
                .values(event_time=0.0, event_status=0)
            )
            updated_count = result.rowcount
            message = f"Dataset type changed to survival. Set default event_time/status for {updated_count} slides."
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
            task_type=req.task_type
        )

        # Update dataset's group_id
        await DatasetRepository.update(db, dataset_id, {"group_id": new_data_group.group_id})

        await db.commit()

        logger.info(f"Updated dataset {dataset_id} type to {req.task_type}: {updated_count} WSIs affected")

        return {
            "message": message,
            "dataset_id": dataset_id,
            "new_type": req.task_type,
            "updated_count": updated_count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update dataset type: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update dataset type: {str(e)}")


@router.put("/datasets/{dataset_id}/data-level")
async def update_dataset_data_level(
    dataset_id: str,
    req: DatasetUpdateDataLevelRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
            raise HTTPException(status_code=400, detail="aggregation_level must be 'case' or 'file'")

        # Check dataset exists (with data_group loaded)
        dataset = await DatasetRepository.get_by_id(db, dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

        # Check ownership (admin can update any, others only their own)
        if not check_data_ownership(dataset.user_id, user):
            raise HTTPException(status_code=403, detail="You don't have permission to update this dataset")

        # Get current DataGroup to preserve data_type and task_type
        current_group = dataset.data_group
        if not current_group:
            raise HTTPException(status_code=500, detail="Dataset has no associated DataGroup")

        # If aggregation_level hasn't changed, no update needed
        if current_group.aggregation_level == aggregation_level:
            return {
                "message": f"Dataset aggregation level is already {aggregation_level}",
                "dataset_id": dataset_id,
                "new_aggregation_level": aggregation_level
            }

        # Get or create a new DataGroup with the new aggregation_level
        new_group = await DataGroupRepository.get_or_create(
            db,
            data_type=current_group.data_type,
            aggregation_level=aggregation_level,
            task_type=current_group.task_type
        )

        # Update dataset's group_id
        dataset.group_id = new_group.group_id
        await db.commit()

        logger.info(f"Updated dataset {dataset_id} aggregation_level from {current_group.aggregation_level} to {aggregation_level}")

        return {
            "message": f"Dataset aggregation level changed to {aggregation_level}",
            "dataset_id": dataset_id,
            "new_aggregation_level": aggregation_level
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update dataset data level: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update dataset data level: {str(e)}")


@router.post("/check-duplicates")
async def check_duplicate_filenames(
    filenames: List[str],
    user_id_filter: Optional[str] = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db)
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

    existing = await WSIRepository.get_existing_original_filenames(db, filenames, user_id=user_id_filter)
    existing_set = set(existing)

    duplicates = [f for f in filenames if f in existing_set]
    new_files = [f for f in filenames if f not in existing_set]

    return {"duplicates": duplicates, "new": new_files}


@router.get("/{wsi_id}")
async def get_wsi(
    wsi_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get WSI metadata and latest result.
    Users can access their own WSI, WSI in datasets they have elevated permissions for, or admin can access all."""
    wsi = await WSIRepository.get_by_id_with_dataset(db, wsi_id)
    if not wsi:
        raise HTTPException(status_code=404, detail="wsi_id not found")

    # Check access permission (ownership or elevated dataset permission)
    has_access = await check_wsi_access_permission(user, wsi.dataset_id, wsi.user_id, db)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access this WSI")

    # Get latest result
    last_result = await AIResultRepository.get_by_wsi_id(db, wsi_id)

    # Build response with can_delete flag
    meta = wsi.to_dict()
    # can_delete: True if admin or user owns the WSI
    meta["can_delete"] = user.is_admin() or (wsi.user_id == str(user.id))

    return {
        "wsi_id": wsi_id,
        "meta": meta,
        "last_run": last_result.to_dict() if last_result else None
    }


@router.delete("/{wsi_id}")
async def delete_wsi(
    wsi_id: str,
    mode: DeletionMode = DeletionMode.STANDARD,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        # Check ownership
        if not check_data_ownership(wsi.user_id, user):
            raise HTTPException(status_code=403, detail="You don't have permission to delete this WSI")

        wsi_path = wsi.wsi_path

        # Delete all associated data before deleting the WSI
        # Using raw SQL for efficiency
        try:
            # Delete training task associations first (foreign key constraint)
            await db.execute(
                sql_delete(TrainingTaskWSI).where(TrainingTaskWSI.wsi_id == wsi_id)
            )

            # Delete AI results
            await db.execute(
                sql_delete(AIResult).where(AIResult.wsi_id == wsi_id)
            )

            # Delete AI tasks
            await db.execute(
                sql_delete(AITask).where(AITask.wsi_id == wsi_id)
            )
        except Exception as e:
            logger.warning(f"Failed to delete associated data for {wsi_id}: {e}")

        # Delete WSI from database
        await WSIRepository.delete(db, wsi_id)
        await db.commit()

        # Delete all files using StorageManager with specified mode
        storage_cleanup = storage_manager.delete_wsi_files(wsi_id, wsi_path, mode=mode.value)
        logger.info(storage_cleanup['summary'])

        return {
            "message": "WSI deleted successfully",
            "wsi_id": wsi_id,
            "storage_cleanup": storage_cleanup
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
    db: AsyncSession = Depends(get_db)
):
    """
    Update WSI metadata (label, case_id, age, gender, source).
    All authenticated users can update their own WSI metadata, admin can update any.

    Args:
        wsi_id: The WSI ID to update
        req: WSIMetadataUpdateRequest containing fields to update

    Returns:
        Updated WSI metadata
    """
    try:
        # Get WSI from database (with dataset for to_dict())
        wsi = await WSIRepository.get_by_id_with_dataset(db, wsi_id)
        if not wsi:
            raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        # Check ownership
        if not check_data_ownership(wsi.user_id, user):
            raise HTTPException(status_code=403, detail="You don't have permission to update this WSI")

        # Update fields if provided
        if req.label is not None:
            wsi.label = req.label
        if req.case_id is not None:
            wsi.case_id = req.case_id
        if req.age is not None:
            wsi.age = req.age
        if req.gender is not None:
            wsi.gender = req.gender
        if req.source is not None:
            wsi.source = req.source
        # Survival analysis fields
        if req.event_time is not None:
            wsi.event_time = req.event_time
        if req.event_status is not None:
            wsi.event_status = req.event_status

        await db.commit()

        # Re-fetch with dataset relationship to avoid lazy loading issues
        wsi = await WSIRepository.get_by_id_with_dataset(db, wsi_id)

        logger.info(f"Updated WSI metadata: {wsi_id}")

        return {
            "message": "WSI metadata updated successfully",
            "wsi": wsi.to_dict()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update WSI metadata: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update WSI metadata: {str(e)}")


@router.post("/{wsi_id}/compute_patches")
async def compute_patches(
    wsi_id: str,
    level: int = Query(0, description="Pyramid level (0 = highest resolution)"),
    force_recompute: bool = Query(False, description="Force recompute even if patches exist"),
    seg_level: int = Query(-1, description="Pyramid level for tissue segmentation (-1 = auto)"),
    sthresh: int = Query(5, description="Saturation threshold (0-255, low threshold for maximum tissue detection)"),
    mthresh: int = Query(7, description="Median filter kernel size (must be odd, default: 7)"),
    close: int = Query(4, description="Morphological closing kernel size (default: 4)"),
    use_otsu: bool = Query(False, description="Use Otsu auto-thresholding"),
    contour_fn: str = Query("four_pt", description="Contour check function (four_pt, center, basic)"),
    user: User = Depends(require_pathologist_or_admin),
    db: AsyncSession = Depends(get_db)
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
    wsi = await WSIRepository.get_by_id(db, wsi_id)
    if not wsi:
        raise HTTPException(status_code=404, detail="WSI not found")

    # Check ownership
    if not check_data_ownership(wsi.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to compute patches for this WSI")

    # Build query parameters (patch_size and stride are auto-determined by PrePATH-style tiling)
    params = {
        "level": level,
        "force_recompute": force_recompute,
        "seg_level": seg_level,
        "sthresh": sthresh,
        "mthresh": mthresh,
        "close": close,
        "use_otsu": use_otsu,
        "contour_fn": contour_fn
    }

    # Forward request to preprocessing service
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            response = await client.post(
                f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/compute_patches",
                params=params
            )

            if response.status_code != 200:
                logger.error(f"Preprocessing service error: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Preprocessing service error: {response.text}"
                )

            result = response.json()
            logger.info(f"Successfully computed patches for WSI: {wsi_id}")
            return result

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error from preprocessing service: {e}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Preprocessing service error: {e.response.text}"
        )
    except httpx.RequestError as e:
        logger.error(f"Failed to connect to preprocessing service: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Preprocessing service unavailable: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Failed to compute patches: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to compute patches: {str(e)}"
        )


@router.post("/datasets/{dataset_id}/splits")
async def upload_dataset_splits(
    dataset_id: str,
    file: UploadFile = File(...),
    user: User = Depends(current_active_user),
    user_id_filter: Optional[str] = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db)
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
    - split (train, val, test), label, case_id, age, gender, source, event_time, event_status

    If no 'val' split is provided, 10% of 'train' samples will be automatically
    assigned to 'val'.
    """
    # Validate file extension - accept CSV and Excel files (frontend converts Excel to CSV)
    allowed_extensions = ('.csv', '.xlsx', '.xls')
    if not file.filename or not file.filename.lower().endswith(allowed_extensions):
        raise HTTPException(status_code=400, detail="Only CSV and Excel (.xlsx, .xls) files are allowed")

    # Read and decode file content
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

    # Check file size (max 10MB)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds 10MB limit")

    # Decode as UTF-8
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Invalid CSV file: not valid UTF-8 encoding")

    # Parse CSV
    try:
        f = io.StringIO(text)
        reader = csv.DictReader(f)

        # Check columns exist
        if not reader.fieldnames:
            raise HTTPException(status_code=400, detail="CSV is empty or has no header row")

        # Identify filename column (required)
        filename_key = next((h for h in reader.fieldnames if h.strip().lower() in ['filename', 'file_name', 'original_filename']), None)
        if not filename_key:
            raise HTTPException(status_code=400, detail="CSV must contain 'filename' column")

        # Identify split column (optional)
        split_key = next((h for h in reader.fieldnames if h.strip().lower() == 'split'), None)

        rows = list(reader)
        if not rows:
            raise HTTPException(status_code=400, detail="CSV has no data rows")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {str(e)}")

    # Validate split values (only if split column exists)
    valid_splits = {'train', 'val', 'validation', 'test'}
    if split_key:
        for i, row in enumerate(rows, start=2):  # start=2 because row 1 is header
            split_val = row.get(split_key, '').strip().lower()
            if split_val and split_val not in valid_splits:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid split value '{row.get(split_key)}' at row {i}. Allowed values: train, val, test"
                )

    # Validate dataset exists
    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    # Check ownership (admin can modify any, others only their own)
    if not check_data_ownership(dataset.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to modify this dataset")

    # Get existing WSIs for mapping (only user's WSIs if not admin)
    wsis = await WSIRepository.get_by_dataset(db, dataset_id, user_id=user_id_filter)
    if not wsis:
        raise HTTPException(status_code=404, detail=f"No slides found in dataset: {dataset_id}")

    # Create lookup map: original filename -> WSI object
    filename_map = {w.original_filename: w for w in wsis}

    # Validate case-level + survival: all slides in a case must have same event_time/event_status
    # Access aggregation_level and task_type through the DataGroup relationship
    data_group = dataset.data_group
    aggregation_level = data_group.aggregation_level if data_group else 'file'
    task_type = data_group.task_type if data_group else 'classification'
    if aggregation_level == 'case' and task_type == 'survival':
        # Group rows by case_id to check for consistency
        case_groups = {}  # case_id -> [(event_time, event_status, filename), ...]
        case_id_key = next((h for h in rows[0].keys() if h.strip().lower() == 'case_id'), None) if rows else None
        event_time_key = next((h for h in rows[0].keys() if h.strip().lower() == 'event_time'), None) if rows else None
        event_status_key = next((h for h in rows[0].keys() if h.strip().lower() == 'event_status'), None) if rows else None

        if case_id_key and (event_time_key or event_status_key):
            for row in rows:
                case_id_val = row.get(case_id_key, '').strip()
                if not case_id_val:
                    continue

                event_time_val = row.get(event_time_key, '').strip() if event_time_key else None
                event_status_val = row.get(event_status_key, '').strip() if event_status_key else None
                fname = row.get(filename_key, '').strip()

                if case_id_val not in case_groups:
                    case_groups[case_id_val] = []
                case_groups[case_id_val].append({
                    'event_time': event_time_val,
                    'event_status': event_status_val,
                    'filename': fname
                })

            # Check consistency within each case
            inconsistent_cases = []
            for case_id_val, entries in case_groups.items():
                if len(entries) <= 1:
                    continue  # Single slide case, no need to check

                first_time = entries[0]['event_time']
                first_status = entries[0]['event_status']

                for entry in entries[1:]:
                    if entry['event_time'] != first_time or entry['event_status'] != first_status:
                        inconsistent_cases.append({
                            'case_id': case_id_val,
                            'files': [e['filename'] for e in entries],
                            'values': [(e['event_time'], e['event_status']) for e in entries]
                        })
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
        fname = row.get(filename_key, '').strip()
        if not fname:
            continue

        target_wsi = filename_map.get(fname)

        if not target_wsi:
            not_found_files.append(fname)
            continue

        # Update split (only if split column exists)
        if split_key:
            split_val = row.get(split_key, '').strip().lower()
            if split_val:
                if split_val == 'validation':
                    split_val = 'val'
                target_wsi.split = split_val

        # Update other metadata if present
        for key, val in row.items():
            norm_key = key.strip().lower()
            if not val:
                continue

            val = val.strip()
            if norm_key == 'label':
                target_wsi.label = val
            elif norm_key == 'case_id':
                target_wsi.case_id = val
            elif norm_key == 'age':
                if val.isdigit():
                    target_wsi.age = int(val)
            elif norm_key == 'gender':
                target_wsi.gender = val
            elif norm_key == 'source':
                target_wsi.source = val
            elif norm_key == 'event_time':
                try:
                    target_wsi.event_time = float(val)
                except (ValueError, TypeError):
                    pass
            elif norm_key == 'event_status':
                if val in ['0', '1']:
                    target_wsi.event_status = int(val)

        updated_count += 1

    # Auto-create val split if empty
    # Count splits after update
    train_wsis = [w for w in wsis if w.split == 'train']
    val_wsis = [w for w in wsis if w.split == 'val']

    auto_val_count = 0
    if len(val_wsis) == 0 and len(train_wsis) > 0:
        import random
        n_val = max(1, int(len(train_wsis) * 0.1))
        # Shuffle and select
        random.shuffle(train_wsis)
        for i in range(min(n_val, len(train_wsis))):
            train_wsis[i].split = 'val'
            auto_val_count += 1
        logger.info(f"Auto-created val split: moved {auto_val_count} samples from train to val")

    await db.commit()

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
        "not_found_files": not_found_files[:10] if not_found_files else []  # Return first 10 for debugging
    }




