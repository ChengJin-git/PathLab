import httpx
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Form, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import User, current_active_user
from backend.auth.dependencies import require_admin
from backend.database import get_db, async_session
from backend.database.models import Dataset, TrainingTask, WSISlide
from backend.database.repositories import (
    DatasetGrantRepository,
    DatasetRepository,
    PermissionAuditLogRepository,
    TrainingTaskRepository,
)
from ..dependencies import AI_SERVICE_URL, logger
from ..models import DatasetUpdateVisibilityRequest
from gateway.chat.context_cache import (
    invalidate_chat_context,
    invalidate_all_user_chat_contexts,
)

router = APIRouter(tags=["WSI Grants"])


class BatchGrantDatasetGrantRequest(BaseModel):
    user_ids: List[str] = Field(default_factory=list)
    expires_in_hours: Optional[int] = None
    can_read: Optional[bool] = True
    can_collaborate: Optional[bool] = False
    can_use_gpu: Optional[bool] = False


class BatchRevokeDatasetGrantRequest(BaseModel):
    user_ids: List[str] = Field(default_factory=list)


def _calculate_expires_at(expires_in_hours: Optional[int]) -> Optional[datetime]:
    if expires_in_hours is None or expires_in_hours <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)).replace(
        tzinfo=None
    )


async def _grant_or_renew_permission(
    db: AsyncSession,
    dataset_id: str,
    user_id: str,
    granted_by: str,
    can_read: bool = True,
    can_collaborate: bool = False,
    can_use_gpu: bool = False,
    expires_at: Optional[datetime] = None,
) -> Tuple[str, Dict[str, Any]]:
    target_user = None
    if can_use_gpu:
        from backend.auth.models import User as UserModel

        try:
            target_uuid = uuid.UUID(str(user_id))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid target user id")

        target_row = await db.execute(
            select(UserModel.id, UserModel.role).where(UserModel.id == target_uuid)
        )
        target_user = target_row.first()
        if target_user is None:
            raise HTTPException(status_code=404, detail="Target user not found")
        if target_user.role == UserModel.ROLE_GUEST:
            raise HTTPException(
                status_code=400,
                detail="Guest users cannot be granted GPU permission",
            )

    existing = await DatasetGrantRepository.get_by_dataset_and_user(
        db, dataset_id, user_id
    )
    if existing:
        if existing.is_expired():
            existing.expires_at = expires_at
            existing.granted_by = granted_by
            existing.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
            existing.can_read = can_read
            existing.can_collaborate = can_collaborate
            existing.can_use_gpu = can_use_gpu
            await db.flush()
            return "Permission renewed successfully", existing.to_dict()
        existing.can_read = can_read
        existing.can_collaborate = can_collaborate
        existing.can_use_gpu = can_use_gpu
        existing.granted_by = granted_by
        await db.flush()
        return "Permission updated successfully", existing.to_dict()

    grant = await DatasetGrantRepository.create(
        db=db,
        dataset_id=dataset_id,
        user_id=user_id,
        granted_by=granted_by,
        can_read=can_read,
        can_collaborate=can_collaborate,
        can_use_gpu=can_use_gpu,
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
    from backend.ai.permission_revocation import revoke_task_permission as _local_revoke

    revoked: List[str] = []
    for task_id in task_ids:
        _local_revoke(task_id)
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


async def _stop_non_owner_training_tasks(
    db: AsyncSession,
    dataset_id: str,
    owner_user_id: Optional[str],
) -> Dict[str, List[str]]:
    wsi_ids_result = await db.execute(
        select(WSISlide.wsi_id).where(WSISlide.dataset_id == dataset_id)
    )
    dataset_wsi_ids = {row[0] for row in wsi_ids_result.all()}
    if not dataset_wsi_ids:
        return {}

    running_statuses = ["pending", "patching", "extracting", "training", "resuming"]
    running_tasks_result = await db.execute(
        select(TrainingTask.task_id, TrainingTask.user_id).where(
            TrainingTask.status.in_(running_statuses)
        )
    )
    all_running = running_tasks_result.all()

    affected_by_user: Dict[str, List[str]] = {}
    for task_id, task_user_id in all_running:
        if owner_user_id and str(task_user_id) == str(owner_user_id):
            continue
        task_wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task_id)
        if any(wsi_id in dataset_wsi_ids for wsi_id in task_wsi_ids):
            affected_by_user.setdefault(str(task_user_id), []).append(task_id)

    for user_id, task_ids in affected_by_user.items():
        await _notify_ai_service_permission_revocation(task_ids)

    return affected_by_user


async def _revoke_child_dataset_grants(
    db: AsyncSession,
    parent_dataset_id: str,
    target_user_id: str,
    actor_user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    child_ids = await DatasetRepository.get_child_dataset_ids(db, [parent_dataset_id])
    if not child_ids:
        return []

    child_wsi_rows = await db.execute(
        select(WSISlide.dataset_id, WSISlide.wsi_id).where(
            WSISlide.dataset_id.in_(child_ids)
        )
    )
    wsi_by_dataset: Dict[str, set] = {}
    for ds_id, wsi_id in child_wsi_rows.all():
        wsi_by_dataset.setdefault(str(ds_id), set()).add(str(wsi_id))

    results: List[Dict[str, Any]] = []
    for child_id in child_ids:
        grant = await DatasetGrantRepository.get_by_dataset_and_user(
            db, child_id, target_user_id
        )
        if not grant:
            continue

        child_wsi_ids = wsi_by_dataset.get(child_id, set())
        affected_task_ids = await _find_affected_training_tasks(
            db, target_user_id, child_wsi_ids
        )
        await _notify_ai_service_permission_revocation(affected_task_ids)

        await DatasetGrantRepository.delete(db, child_id, target_user_id)
        if actor_user_id:
            await PermissionAuditLogRepository.log(
                db,
                child_id,
                actor_user_id,
                target_user_id,
                "revoke_permission_cascade",
                {},
            )

        results.append(
            {
                "dataset_id": child_id,
                "stopped_tasks": affected_task_ids,
            }
        )

    return results


async def _revoke_permission_with_side_effects(
    db: AsyncSession,
    dataset_id: str,
    target_user_id: str,
    dataset_wsi_ids: set,
) -> Dict[str, Any]:
    affected_task_ids = await _find_affected_training_tasks(
        db, target_user_id, dataset_wsi_ids
    )
    revoked_tasks = await _notify_ai_service_permission_revocation(affected_task_ids)

    grant = await DatasetGrantRepository.get_by_dataset_and_user(
        db, dataset_id, target_user_id
    )
    if not grant:
        raise HTTPException(status_code=404, detail="Permission not found")

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

    was_public = bool(dataset.is_public)
    becoming_private = was_public and not request.is_public
    becoming_public = (not was_public) and request.is_public

    updates: Dict[str, Any] = {"is_public": request.is_public}

    revoked_by_user: Dict[str, List[str]] = {}
    if becoming_private:
        revoked_by_user = await _stop_non_owner_training_tasks(
            db, dataset_id, dataset.user_id
        )

    revoked_grants = 0
    if becoming_public:
        revoked_grants = await DatasetGrantRepository.delete_by_dataset(db, dataset_id)

    await DatasetRepository.update(db, dataset_id, updates)
    await db.commit()

    if becoming_public or becoming_private:
        try:
            async with async_session() as _db:
                _r = await _db.execute(select(User.id))
                all_user_ids = [str(row[0]) for row in _r.all()]
            await invalidate_all_user_chat_contexts(all_user_ids)
        except Exception as _exc:
            logger.warning("[ChatCtxCache] broadcast invalidate failed: %s", _exc)
            await invalidate_chat_context(str(user.id))
    else:
        await invalidate_chat_context(str(user.id))

    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    response: Dict[str, Any] = {
        "dataset_id": dataset_id,
        "is_public": dataset.is_public,
    }
    if revoked_by_user:
        total_revoked = sum(len(v) for v in revoked_by_user.values())
        response["revoked_training_tasks"] = total_revoked
        response["message"] = (
            f"Visibility updated. {total_revoked} running task(s) from "
            f"{len(revoked_by_user)} user(s) will be stopped."
        )
    if revoked_grants > 0:
        response["revoked_dataset_grants"] = revoked_grants
        response["message"] = (
            response.get("message", "Visibility updated.")
            + f" Removed {revoked_grants} temporary private grant(s) because dataset is now public."
        )
    return response


@router.get("/my-grants")
async def get_my_dataset_grants(
    user: User = Depends(current_active_user), db: AsyncSession = Depends(get_db)
):
    grants = await DatasetGrantRepository.get_valid_by_user(db, str(user.id))
    visible_private_grants = [g for g in grants if g.can_read and g.is_valid()]
    return {
        "user_id": str(user.id),
        "grants": [g.to_dict() for g in visible_private_grants],
        "elevated_dataset_ids": [g.dataset_id for g in visible_private_grants],
    }


@router.get("/user-grants/{target_user_id}")
async def get_user_dataset_grants(
    target_user_id: str,
    _: User = Depends(require_admin),
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
    _: User = Depends(require_admin),
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
    can_read: bool = Form(True),
    can_collaborate: bool = Form(False),
    can_use_gpu: bool = Form(False),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    if dataset.is_public:
        raise HTTPException(
            status_code=400,
            detail="Temporary grants are only available for private datasets",
        )

    can_read = True
    can_collaborate = False
    can_use_gpu = False

    expires_at = _calculate_expires_at(expires_in_hours)

    try:
        message, grant = await _grant_or_renew_permission(
            db=db,
            dataset_id=dataset_id,
            user_id=user_id,
            granted_by=str(user.id),
            can_read=can_read,
            can_collaborate=can_collaborate,
            can_use_gpu=can_use_gpu,
            expires_at=expires_at,
        )
        await PermissionAuditLogRepository.log(
            db,
            dataset_id,
            str(user.id),
            user_id,
            "grant_permission",
            {
                "expires_in_hours": expires_in_hours,
                "can_read": can_read,
                "can_collaborate": can_collaborate,
                "can_use_gpu": can_use_gpu,
            },
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

    if dataset.is_public:
        raise HTTPException(
            status_code=400,
            detail="Temporary grants are only available for private datasets",
        )

    expires_at = _calculate_expires_at(request.expires_in_hours)
    results = []
    granted = 0

    for uid in list(dict.fromkeys(request.user_ids)):
        try:
            message, grant = await _grant_or_renew_permission(
                db=db,
                dataset_id=dataset_id,
                user_id=uid,
                granted_by=str(user.id),
                can_read=request.can_read if request.can_read is not None else True,
                can_collaborate=False,
                can_use_gpu=False,
                expires_at=expires_at,
            )
            await PermissionAuditLogRepository.log(
                db,
                dataset_id,
                str(user.id),
                uid,
                "grant_permission",
                {
                    "expires_in_hours": request.expires_in_hours,
                    "can_read": request.can_read,
                    "can_collaborate": request.can_collaborate,
                    "can_use_gpu": request.can_use_gpu,
                },
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
    result = await _revoke_permission_with_side_effects(
        db=db,
        dataset_id=dataset_id,
        target_user_id=target_user_id,
        dataset_wsi_ids=dataset_wsi_ids,
    )
    child_results = await _revoke_child_dataset_grants(
        db, dataset_id, target_user_id, str(user.id)
    )
    if child_results:
        result["child_datasets_revoked"] = len(child_results)
        result["message"] = (
            f"{result['message']} Also revoked access to {len(child_results)} child dataset(s)."
        )
    await PermissionAuditLogRepository.log(
        db, dataset_id, str(user.id), target_user_id, "revoke_permission", {}
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
            result = await _revoke_permission_with_side_effects(
                db=db,
                dataset_id=dataset_id,
                target_user_id=uid,
                dataset_wsi_ids=dataset_wsi_ids,
            )
            child_results = await _revoke_child_dataset_grants(
                db, dataset_id, uid, str(user.id)
            )
            if child_results:
                result["child_datasets_revoked"] = len(child_results)
                result["message"] = (
                    f"{result['message']} Also revoked access to {len(child_results)} child dataset(s)."
                )
            await PermissionAuditLogRepository.log(
                db, dataset_id, str(user.id), uid, "revoke_permission", {}
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
