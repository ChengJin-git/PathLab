"""
WSI dataset permission routes
Handles temporary elevated access permissions for datasets (demo/review use case).
"""
import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Tuple
from fastapi import APIRouter, HTTPException, Form, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field

from backend.database import get_db
from backend.database.repositories import (
    DatasetRepository,
    DatasetPermissionRepository,
    SegmentationAnnotationRepository,
    TrainingTaskRepository,
)
from backend.database.models import Dataset, TrainingTask, WSISlide
from backend.auth import current_active_user, User
from backend.auth.dependencies import require_admin
from ..dependencies import logger, AI_SERVICE_URL

router = APIRouter(tags=["WSI Permissions"])


class BatchGrantDatasetPermissionRequest(BaseModel):
    """Grant one dataset to many users in a single request."""
    user_ids: List[str] = Field(default_factory=list)
    expires_in_hours: Optional[int] = None


class BatchRevokeDatasetPermissionRequest(BaseModel):
    """Revoke one dataset from many users in a single request."""
    user_ids: List[str] = Field(default_factory=list)


def _calculate_expires_at(expires_in_hours: Optional[int]) -> Optional[datetime]:
    """Convert hours into a naive UTC expiration timestamp for PostgreSQL compatibility."""
    if expires_in_hours is None or expires_in_hours <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)).replace(tzinfo=None)


async def _grant_or_renew_dataset_permission(
    db: AsyncSession,
    dataset_id: str,
    user_id: str,
    granted_by: str,
    expires_at: Optional[datetime],
) -> Tuple[str, Dict]:
    existing = await DatasetPermissionRepository.get_by_dataset_and_user(db, dataset_id, user_id)
    if existing:
        if existing.is_expired():
            existing.expires_at = expires_at
            existing.granted_by = granted_by
            existing.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.flush()
            return "Permission renewed successfully", existing.to_dict()

        raise HTTPException(
            status_code=400,
            detail="Valid permission already exists for this user on this dataset"
        )

    permission = await DatasetPermissionRepository.create(
        db=db,
        dataset_id=dataset_id,
        user_id=user_id,
        granted_by=granted_by,
        permission_level="pathologist",
        expires_at=expires_at,
    )
    return "Permission granted successfully", permission.to_dict()


async def _find_affected_training_tasks(
    db: AsyncSession,
    target_user_id: str,
    dataset_wsi_ids: set,
) -> List[str]:
    affected_task_ids: List[str] = []
    if not dataset_wsi_ids:
        return affected_task_ids

    running_statuses = ['pending', 'patching', 'extracting', 'training', 'resuming']
    running_tasks_result = await db.execute(
        select(TrainingTask.task_id)
        .where(TrainingTask.user_id == target_user_id)
        .where(TrainingTask.status.in_(running_statuses))
    )
    candidate_task_ids = [row[0] for row in running_tasks_result.all()]

    for task_id in candidate_task_ids:
        task_wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task_id)
        if any(wsi_id in dataset_wsi_ids for wsi_id in task_wsi_ids):
            affected_task_ids.append(task_id)

    return affected_task_ids


async def _notify_ai_service_permission_revocation(task_ids: List[str]) -> List[str]:
    revoked_tasks: List[str] = []
    for task_id in task_ids:
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                await client.post(f"{AI_SERVICE_URL}/api/ai/training/{task_id}/revoke-permission")
                revoked_tasks.append(task_id)
                logger.info(f"Permission revocation sent to AI service for task {task_id}")
        except httpx.TimeoutException:
            revoked_tasks.append(task_id)
            logger.debug(f"Permission revocation sent to AI service for task {task_id} (fire-and-forget)")
        except Exception as e:
            logger.warning(f"Failed to send permission revocation to AI service for task {task_id}: {e}")
    return revoked_tasks


async def _revoke_dataset_permission_with_side_effects(
    db: AsyncSession,
    dataset_id: str,
    target_user_id: str,
    dataset_wsi_ids: set,
) -> Dict:
    affected_task_ids = await _find_affected_training_tasks(db, target_user_id, dataset_wsi_ids)
    revoked_tasks = await _notify_ai_service_permission_revocation(affected_task_ids)

    deleted_annotation_count = await SegmentationAnnotationRepository.delete_by_dataset_and_user(
        db,
        dataset_id,
        target_user_id,
    )
    if deleted_annotation_count:
        logger.info(
            "Deleted %s annotation record(s) for user %s on dataset %s during permission revocation",
            deleted_annotation_count,
            target_user_id,
            dataset_id,
        )

    deleted = await DatasetPermissionRepository.delete_by_dataset_and_user(db, dataset_id, target_user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Permission not found")

    result: Dict = {"message": "Permission revoked successfully"}
    if revoked_tasks:
        result["affected_tasks"] = revoked_tasks
        result["message"] = f"Permission revoked. {len(revoked_tasks)} running task(s) will be stopped."
    return result


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
    dataset_ids = list({permission.dataset_id for permission in permissions})
    dataset_names: Dict[str, str] = {}
    if dataset_ids:
        dataset_rows = await db.execute(
            select(Dataset.dataset_id, Dataset.name).where(Dataset.dataset_id.in_(dataset_ids))
        )
        dataset_names = {row[0]: row[1] for row in dataset_rows.all()}

    serialized_permissions = [
        {
            **permission.to_dict(),
            "dataset_name": dataset_names.get(permission.dataset_id),
        }
        for permission in permissions
    ]

    return {
        "user_id": target_user_id,
        "permissions": serialized_permissions,
        "valid_permissions": [permission for permission in serialized_permissions if permission["is_valid"]]
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

    expires_at = _calculate_expires_at(expires_in_hours)

    try:
        message, permission = await _grant_or_renew_dataset_permission(
            db=db,
            dataset_id=dataset_id,
            user_id=user_id,
            granted_by=str(user.id),
            expires_at=expires_at,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Valid permission already exists for this user on this dataset"
        )

    return {
        "message": message,
        "permission": permission
    }


@router.post("/datasets/{dataset_id}/permissions/batch-grant")
async def batch_grant_dataset_permissions(
    dataset_id: str,
    request: BatchGrantDatasetPermissionRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Grant one dataset to many users in a single request."""
    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    expires_at = _calculate_expires_at(request.expires_in_hours)
    results = []
    granted = 0

    for user_id in list(dict.fromkeys(request.user_ids)):
        try:
            message, permission = await _grant_or_renew_dataset_permission(
                db=db,
                dataset_id=dataset_id,
                user_id=user_id,
                granted_by=str(user.id),
                expires_at=expires_at,
            )
            await db.commit()
            results.append({
                "user_id": user_id,
                "success": True,
                "message": message,
                "permission": permission,
            })
            granted += 1
        except HTTPException as exc:
            await db.rollback()
            results.append({
                "user_id": user_id,
                "success": False,
                "error": str(exc.detail),
            })
        except IntegrityError:
            await db.rollback()
            results.append({
                "user_id": user_id,
                "success": False,
                "error": "Valid permission already exists for this user on this dataset",
            })
        except Exception as exc:
            await db.rollback()
            logger.warning(
                "Failed to batch grant permission for user %s on dataset %s: %s",
                user_id,
                dataset_id,
                exc,
            )
            results.append({
                "user_id": user_id,
                "success": False,
                "error": str(exc),
            })

    return {
        "dataset_id": dataset_id,
        "granted": granted,
        "failed": len(results) - granted,
        "results": results,
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

    wsi_ids_result = await db.execute(
        select(WSISlide.wsi_id).where(WSISlide.dataset_id == dataset_id)
    )
    dataset_wsi_ids = set(row[0] for row in wsi_ids_result.all())
    result = await _revoke_dataset_permission_with_side_effects(
        db=db,
        dataset_id=dataset_id,
        target_user_id=target_user_id,
        dataset_wsi_ids=dataset_wsi_ids,
    )
    await db.commit()

    return result


@router.post("/datasets/{dataset_id}/permissions/batch-revoke")
async def batch_revoke_dataset_permissions(
    dataset_id: str,
    request: BatchRevokeDatasetPermissionRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Revoke one dataset from many users in a single request."""
    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    wsi_ids_result = await db.execute(
        select(WSISlide.wsi_id).where(WSISlide.dataset_id == dataset_id)
    )
    dataset_wsi_ids = set(row[0] for row in wsi_ids_result.all())

    results = []
    revoked = 0

    for target_user_id in list(dict.fromkeys(request.user_ids)):
        try:
            result = await _revoke_dataset_permission_with_side_effects(
                db=db,
                dataset_id=dataset_id,
                target_user_id=target_user_id,
                dataset_wsi_ids=dataset_wsi_ids,
            )
            await db.commit()
            results.append({
                "user_id": target_user_id,
                "success": True,
                **result,
            })
            revoked += 1
        except HTTPException as exc:
            await db.rollback()
            results.append({
                "user_id": target_user_id,
                "success": False,
                "error": str(exc.detail),
            })
        except Exception as exc:
            await db.rollback()
            logger.warning(
                "Failed to batch revoke permission for user %s on dataset %s: %s",
                target_user_id,
                dataset_id,
                exc,
            )
            results.append({
                "user_id": target_user_id,
                "success": False,
                "error": str(exc),
            })

    return {
        "dataset_id": dataset_id,
        "revoked": revoked,
        "failed": len(results) - revoked,
        "results": results,
    }
