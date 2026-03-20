import httpx
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Form, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import User, current_active_user
from backend.auth.dependencies import require_admin
from backend.database import get_db
from backend.database.models import Dataset, TrainingTask, WSISlide
from backend.database.repositories import (
    DatasetGrantRepository,
    DatasetRepository,
    PermissionAuditLogRepository,
    SegmentationAnnotationRepository,
    TrainingTaskRepository,
)
from ..dependencies import AI_SERVICE_URL, logger
from ..models import DatasetUpdateVisibilityRequest

router = APIRouter(tags=["WSI Grants"])


class BatchGrantDatasetGrantRequest(BaseModel):
    user_ids: List[str] = Field(default_factory=list)
    expires_in_hours: Optional[int] = None


class BatchRevokeDatasetGrantRequest(BaseModel):
    user_ids: List[str] = Field(default_factory=list)


def _calculate_expires_at(expires_in_hours: Optional[int]) -> Optional[datetime]:
    if expires_in_hours is None or expires_in_hours <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)).replace(
        tzinfo=None
    )


async def _grant_or_renew_gpu_permission(
    db: AsyncSession,
    dataset_id: str,
    user_id: str,
    granted_by: str,
    expires_at: Optional[datetime],
) -> Tuple[str, Dict[str, Any]]:
    existing = await DatasetGrantRepository.get_by_dataset_and_user(
        db, dataset_id, user_id
    )
    if existing:
        if existing.is_expired():
            existing.expires_at = expires_at
            existing.granted_by = granted_by
            existing.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
            existing.can_use_gpu = True
            await db.flush()
            return "Permission renewed successfully", existing.to_dict()
        if existing.can_use_gpu:
            raise HTTPException(
                status_code=400,
                detail="Valid GPU permission already exists for this user on this dataset",
            )
        existing.can_use_gpu = True
        existing.granted_by = granted_by
        await db.flush()
        return "GPU permission added successfully", existing.to_dict()

    grant = await DatasetGrantRepository.create(
        db=db,
        dataset_id=dataset_id,
        user_id=user_id,
        granted_by=granted_by,
        can_use_gpu=True,
        expires_at=expires_at,
    )
    return "Permission granted successfully", grant.to_dict()


async def _find_affected_training_tasks(
    db: AsyncSession,
    target_user_id: str,
    dataset_wsi_ids: set,
) -> List[str]:
    if not dataset_wsi_ids:
        return []

    running_statuses = ["pending", "patching", "extracting", "training", "resuming"]
    running_tasks_result = await db.execute(
        select(TrainingTask.task_id)
        .where(TrainingTask.user_id == target_user_id)
        .where(TrainingTask.status.in_(running_statuses))
    )
    candidate_task_ids = [row[0] for row in running_tasks_result.all()]

    affected: List[str] = []
    for task_id in candidate_task_ids:
        task_wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task_id)
        if any(wsi_id in dataset_wsi_ids for wsi_id in task_wsi_ids):
            affected.append(task_id)
    return affected


async def _notify_ai_service_permission_revocation(task_ids: List[str]) -> List[str]:
    revoked: List[str] = []
    for task_id in task_ids:
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                await client.post(
                    f"{AI_SERVICE_URL}/api/ai/training/{task_id}/revoke-permission"
                )
                revoked.append(task_id)
        except httpx.TimeoutException:
            revoked.append(task_id)
        except Exception as e:
            logger.warning(
                f"Failed to send permission revocation to AI service for task {task_id}: {e}"
            )
    return revoked


async def _revoke_gpu_permission_with_side_effects(
    db: AsyncSession,
    dataset_id: str,
    target_user_id: str,
    dataset_wsi_ids: set,
) -> Dict[str, Any]:
    affected_task_ids = await _find_affected_training_tasks(
        db, target_user_id, dataset_wsi_ids
    )
    revoked_tasks = await _notify_ai_service_permission_revocation(affected_task_ids)

    deleted_annotation_count = (
        await SegmentationAnnotationRepository.delete_by_dataset_and_user(
            db,
            dataset_id,
            target_user_id,
        )
    )
    if deleted_annotation_count:
        logger.info(
            f"Deleted {deleted_annotation_count} annotation record(s) "
            f"for user {target_user_id} on dataset {dataset_id} during permission revocation"
        )

    grant = await DatasetGrantRepository.get_by_dataset_and_user(
        db, dataset_id, target_user_id
    )
    if not grant:
        raise HTTPException(status_code=404, detail="Permission not found")

    if grant.can_collaborate:
        grant.can_use_gpu = False
        await db.flush()
    else:
        await DatasetGrantRepository.delete(db, dataset_id, target_user_id)

    result: Dict[str, Any] = {"message": "Permission revoked successfully"}
    if revoked_tasks:
        result["affected_tasks"] = revoked_tasks
        result["message"] = (
            f"Permission revoked. {len(revoked_tasks)} running task(s) will be stopped."
        )
    return result


@router.patch("/datasets/{dataset_id}/visibility")
async def update_dataset_visibility(
    dataset_id: str,
    request: DatasetUpdateVisibilityRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    if not user.is_admin() and dataset.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="Not authorized to change dataset visibility"
        )

    updates: Dict[str, Any] = {"is_public": request.is_public}
    if request.is_open_collaboration is not None:
        updates["is_open_collaboration"] = request.is_open_collaboration
    if not request.is_public:
        updates["is_open_collaboration"] = False

    await DatasetRepository.update(db, dataset_id, updates)
    await db.commit()

    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    return {
        "dataset_id": dataset_id,
        "is_public": dataset.is_public,
        "is_open_collaboration": dataset.is_open_collaboration,
    }


@router.get("/my-grants")
async def get_my_dataset_grants(
    user: User = Depends(current_active_user), db: AsyncSession = Depends(get_db)
):
    grants = await DatasetGrantRepository.get_valid_by_user(db, str(user.id))
    gpu_grants = [g for g in grants if g.can_use_gpu and g.is_valid()]
    return {
        "user_id": str(user.id),
        "grants": [g.to_dict() for g in gpu_grants],
        "elevated_dataset_ids": [g.dataset_id for g in gpu_grants],
    }


@router.get("/user-grants/{target_user_id}")
async def get_user_dataset_grants(
    target_user_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    grants = await DatasetGrantRepository.get_by_user(db, target_user_id)
    dataset_ids = list({g.dataset_id for g in grants})
    dataset_names: Dict[str, str] = {}
    if dataset_ids:
        rows = await db.execute(
            select(Dataset.dataset_id, Dataset.name).where(
                Dataset.dataset_id.in_(dataset_ids)
            )
        )
        dataset_names = {row[0]: row[1] for row in rows.all()}

    serialized = [
        {**g.to_dict(), "dataset_name": dataset_names.get(g.dataset_id)} for g in grants
    ]
    return {
        "user_id": target_user_id,
        "grants": serialized,
        "valid_grants": [g for g in serialized if g["is_valid"]],
    }


@router.get("/datasets/{dataset_id}/grants")
async def list_dataset_grants(
    dataset_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    grants = await DatasetGrantRepository.get_by_dataset(db, dataset_id)
    user_ids = list({g.user_id for g in grants})
    user_map: Dict[str, Dict[str, object]] = {}
    if user_ids:
        from backend.auth.models import User as UserModel

        user_rows = await db.execute(
            select(
                UserModel.id,
                UserModel.email,
                UserModel.nickname,
                UserModel.role,
                UserModel.is_active,
            ).where(UserModel.id.in_(user_ids))
        )
        user_map = {
            str(row[0]): {
                "user_email": row[1],
                "user_nickname": row[2],
                "user_role": row[3],
                "user_is_active": row[4],
            }
            for row in user_rows.all()
        }

    return {
        "dataset_id": dataset_id,
        "grants": [{**g.to_dict(), **user_map.get(g.user_id, {})} for g in grants],
    }


@router.post("/datasets/{dataset_id}/grants")
async def grant_dataset_grant(
    dataset_id: str,
    user_id: str = Form(...),
    expires_in_hours: Optional[int] = Form(None),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    expires_at = _calculate_expires_at(expires_in_hours)

    try:
        message, grant = await _grant_or_renew_gpu_permission(
            db=db,
            dataset_id=dataset_id,
            user_id=user_id,
            granted_by=str(user.id),
            expires_at=expires_at,
        )
        await PermissionAuditLogRepository.log(
            db,
            dataset_id,
            str(user.id),
            user_id,
            "grant_gpu",
            {"expires_in_hours": expires_in_hours},
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Valid permission already exists for this user on this dataset",
        )

    return {"message": message, "grant": grant}


@router.post("/datasets/{dataset_id}/grants/batch-grant")
async def batch_grant_dataset_grants(
    dataset_id: str,
    request: BatchGrantDatasetGrantRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    expires_at = _calculate_expires_at(request.expires_in_hours)
    results = []
    granted = 0

    for uid in list(dict.fromkeys(request.user_ids)):
        try:
            message, grant = await _grant_or_renew_gpu_permission(
                db=db,
                dataset_id=dataset_id,
                user_id=uid,
                granted_by=str(user.id),
                expires_at=expires_at,
            )
            await PermissionAuditLogRepository.log(
                db,
                dataset_id,
                str(user.id),
                uid,
                "grant_gpu",
                {"expires_in_hours": request.expires_in_hours},
            )
            await db.commit()
            results.append(
                {
                    "user_id": uid,
                    "success": True,
                    "message": message,
                    "grant": grant,
                }
            )
            granted += 1
        except HTTPException as exc:
            await db.rollback()
            results.append({"user_id": uid, "success": False, "error": str(exc.detail)})
        except IntegrityError:
            await db.rollback()
            results.append(
                {"user_id": uid, "success": False, "error": "Permission already exists"}
            )
        except Exception as exc:
            await db.rollback()
            logger.warning(
                f"Failed to batch grant for user {uid} on dataset {dataset_id}: {exc}"
            )
            results.append({"user_id": uid, "success": False, "error": str(exc)})

    return {
        "dataset_id": dataset_id,
        "granted": granted,
        "failed": len(results) - granted,
        "results": results,
    }


@router.delete("/datasets/{dataset_id}/grants/{target_user_id}")
async def revoke_dataset_grant(
    dataset_id: str,
    target_user_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    wsi_ids_result = await db.execute(
        select(WSISlide.wsi_id).where(WSISlide.dataset_id == dataset_id)
    )
    dataset_wsi_ids = {row[0] for row in wsi_ids_result.all()}
    result = await _revoke_gpu_permission_with_side_effects(
        db=db,
        dataset_id=dataset_id,
        target_user_id=target_user_id,
        dataset_wsi_ids=dataset_wsi_ids,
    )
    await PermissionAuditLogRepository.log(
        db, dataset_id, str(user.id), target_user_id, "revoke_gpu", {}
    )
    await db.commit()
    return result


@router.post("/datasets/{dataset_id}/grants/batch-revoke")
async def batch_revoke_dataset_grants(
    dataset_id: str,
    request: BatchRevokeDatasetGrantRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    wsi_ids_result = await db.execute(
        select(WSISlide.wsi_id).where(WSISlide.dataset_id == dataset_id)
    )
    dataset_wsi_ids = {row[0] for row in wsi_ids_result.all()}

    results = []
    revoked = 0

    for uid in list(dict.fromkeys(request.user_ids)):
        try:
            result = await _revoke_gpu_permission_with_side_effects(
                db=db,
                dataset_id=dataset_id,
                target_user_id=uid,
                dataset_wsi_ids=dataset_wsi_ids,
            )
            await PermissionAuditLogRepository.log(
                db, dataset_id, str(user.id), uid, "revoke_gpu", {}
            )
            await db.commit()
            results.append({"user_id": uid, "success": True, **result})
            revoked += 1
        except HTTPException as exc:
            await db.rollback()
            results.append({"user_id": uid, "success": False, "error": str(exc.detail)})
        except Exception as exc:
            await db.rollback()
            logger.warning(
                f"Failed to batch revoke for user {uid} on dataset {dataset_id}: {exc}"
            )
            results.append({"user_id": uid, "success": False, "error": str(exc)})

    return {
        "dataset_id": dataset_id,
        "revoked": revoked,
        "failed": len(results) - revoked,
        "results": results,
    }
