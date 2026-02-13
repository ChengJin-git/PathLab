"""
WSI dataset permission routes
Handles temporary elevated access permissions for datasets (demo/review use case).
"""
import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Form, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.database import get_db
from backend.database.repositories import (
    DatasetRepository,
    DatasetPermissionRepository,
    TrainingTaskRepository,
)
from backend.database.models import TrainingTask, WSISlide
from backend.auth import current_active_user, User
from backend.auth.dependencies import require_admin
from ..dependencies import logger, AI_SERVICE_URL

router = APIRouter(tags=["WSI Permissions"])


# NOTE: These routes must be defined BEFORE /{wsi_id} to avoid path parameter conflicts
@router.get("/my-permissions")
async def get_my_dataset_permissions(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all valid (non-expired) dataset permissions for the current user.
    This allows the frontend to know which datasets the user has elevated access to.
    """
    permissions = await DatasetPermissionRepository.get_valid_by_user(db, str(user.id))
    return {
        "user_id": str(user.id),
        "permissions": [p.to_dict() for p in permissions],
        "elevated_dataset_ids": [p.dataset_id for p in permissions if p.is_valid()]
    }


@router.get("/user-permissions/{target_user_id}")
async def get_user_dataset_permissions(
    target_user_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all dataset permissions for a specific user.
    Admin only. Used for user management UI.
    """
    permissions = await DatasetPermissionRepository.get_by_user(db, target_user_id)
    return {
        "user_id": target_user_id,
        "permissions": [p.to_dict() for p in permissions],
        "valid_permissions": [p.to_dict() for p in permissions if p.is_valid()]
    }


@router.get("/datasets/{dataset_id}/permissions")
async def list_dataset_permissions(
    dataset_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List all permissions granted for a dataset.
    Admin only.
    """
    # Verify dataset exists
    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    permissions = await DatasetPermissionRepository.get_by_dataset(db, dataset_id)
    return {
        "dataset_id": dataset_id,
        "permissions": [p.to_dict() for p in permissions]
    }


@router.post("/datasets/{dataset_id}/permissions")
async def grant_dataset_permission(
    dataset_id: str,
    user_id: str = Form(..., description="User UUID to grant permission to"),
    expires_in_hours: Optional[int] = Form(None, description="Hours until permission expires (null = no expiration)"),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Grant temporary elevated permission (pathologist-level) to a user for a specific dataset.
    This allows Guest users to run AI analysis and training on the dataset during demos.
    Admin only.

    Args:
        dataset_id: Dataset UUID
        user_id: User UUID to grant permission to
        expires_in_hours: Optional expiration time in hours (null = no expiration)
    """
    # Verify dataset exists
    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    # Calculate expiration time
    # Use naive UTC datetime for PostgreSQL TIMESTAMP WITHOUT TIME ZONE compatibility
    expires_at = None
    if expires_in_hours is not None and expires_in_hours > 0:
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)).replace(tzinfo=None)

    # Check if permission already exists
    existing = await DatasetPermissionRepository.get_by_dataset_and_user(db, dataset_id, user_id)
    if existing:
        # If permission exists but is expired, update it instead of returning error
        if existing.is_expired():
            existing.expires_at = expires_at
            existing.granted_by = str(user.id)
            existing.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.commit()
            await db.refresh(existing)
            return {
                "message": "Permission renewed successfully",
                "permission": existing.to_dict()
            }
        else:
            raise HTTPException(
                status_code=400,
                detail="Valid permission already exists for this user on this dataset"
            )

    # Create permission
    # Race-condition safe: catch IntegrityError if concurrent grant
    # with same (user_id, dataset_id) passes the existence check above (PostgreSQL READ COMMITTED)
    try:
        permission = await DatasetPermissionRepository.create(
            db=db,
            dataset_id=dataset_id,
            user_id=user_id,
            granted_by=str(user.id),
            permission_level="pathologist",
            expires_at=expires_at
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Valid permission already exists for this user on this dataset"
        )

    return {
        "message": "Permission granted successfully",
        "permission": permission.to_dict()
    }


@router.delete("/datasets/{dataset_id}/permissions/{target_user_id}")
async def revoke_dataset_permission(
    dataset_id: str,
    target_user_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Revoke a user's permission for a dataset.
    Admin only.

    Also notifies AI Service to stop any running training tasks that:
    1. Belong to the target user
    2. Use WSIs from this dataset
    """
    # Verify dataset exists
    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    # Find running training tasks that belong to target_user_id and use this dataset's WSIs
    # Step 1: Get all WSI IDs in this dataset
    wsi_ids_result = await db.execute(
        select(WSISlide.wsi_id).where(WSISlide.dataset_id == dataset_id)
    )
    dataset_wsi_ids = set(row[0] for row in wsi_ids_result.all())

    # Step 2: Find running tasks belonging to target user that use any of these WSIs
    affected_task_ids = []
    if dataset_wsi_ids:
        # Get running tasks for target user
        running_statuses = ['pending', 'running', 'extracting', 'training', 'resuming']
        running_tasks_result = await db.execute(
            select(TrainingTask.task_id)
            .where(TrainingTask.user_id == target_user_id)
            .where(TrainingTask.status.in_(running_statuses))
        )
        candidate_task_ids = [row[0] for row in running_tasks_result.all()]

        # Check which tasks use WSIs from this dataset
        for task_id in candidate_task_ids:
            task_wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task_id)
            if any(wsi_id in dataset_wsi_ids for wsi_id in task_wsi_ids):
                affected_task_ids.append(task_id)

    # Step 3: Notify AI Service to revoke permissions for affected tasks
    revoked_tasks = []
    for task_id in affected_task_ids:
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                await client.post(f"{AI_SERVICE_URL}/api/ai/training/{task_id}/revoke-permission")
                revoked_tasks.append(task_id)
                logger.info(f"Permission revocation sent to AI service for task {task_id}")
        except httpx.TimeoutException:
            # Expected - AI service may be busy, but the flag is set
            revoked_tasks.append(task_id)
            logger.debug(f"Permission revocation sent to AI service for task {task_id} (fire-and-forget)")
        except Exception as e:
            logger.warning(f"Failed to send permission revocation to AI service for task {task_id}: {e}")

    # Delete permission from database
    deleted = await DatasetPermissionRepository.delete_by_dataset_and_user(db, dataset_id, target_user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Permission not found")

    await db.commit()

    result = {"message": "Permission revoked successfully"}
    if revoked_tasks:
        result["affected_tasks"] = revoked_tasks
        result["message"] = f"Permission revoked. {len(revoked_tasks)} running task(s) will be stopped."

    return result
