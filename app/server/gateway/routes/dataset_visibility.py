"""Making a dataset private stops training that other users started on it."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import check_dataset_access_permission
from backend.auth.models import User
from backend.common.task_dispatch import publish_task_cancellation
from backend.database import async_session
from backend.database.models import TrainingTask, TrainingTaskWSI, WSISlide

from ..dependencies import AI_SERVICE_URL, logger

ACTIVE_TRAINING_STATUSES = (
    "pending",
    "queued",
    "patching",
    "extracting",
    "training",
    "resuming",
)


async def _cancel_training(task_ids: List[str]) -> None:
    from backend.ai.permission_revocation import revoke_task_permission

    for task_id in task_ids:
        revoke_task_permission(task_id)
        # Persist the terminal state for SSE/recovery and notify the process that
        # owns pending/patching jobs. An AI-only in-memory flag cannot stop them.
        async with async_session() as db:
            await db.execute(
                update(TrainingTask)
                .where(TrainingTask.task_id == task_id)
                .where(TrainingTask.status.in_(ACTIVE_TRAINING_STATUSES))
                .values(
                    status="cancelled",
                    error_message="Dataset is no longer shared",
                    finished_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
            await db.commit()
        try:
            await publish_task_cancellation(task_id)
        except Exception as exc:
            logger.warning("Cancellation transport unavailable for %s: %s", task_id, exc)
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                await client.post(f"{AI_SERVICE_URL}/api/ai/training/{task_id}/revoke-permission")
        except httpx.TimeoutException:
            pass
        except Exception as exc:
            logger.warning("Failed to stop AI-service training %s: %s", task_id, exc)


async def stop_non_owner_training_tasks(
    db: AsyncSession, dataset_id: str, owner_user_id: Optional[str]
) -> Dict[str, List[str]]:
    affected_inputs = (
        select(1)
        .select_from(TrainingTaskWSI)
        .join(WSISlide, WSISlide.wsi_id == TrainingTaskWSI.wsi_id)
        .where(TrainingTaskWSI.task_id == TrainingTask.task_id, WSISlide.dataset_id == dataset_id)
    )
    running = (
        await db.execute(
            select(TrainingTask.task_id, TrainingTask.user_id).where(
                TrainingTask.status.in_(ACTIVE_TRAINING_STATUSES), exists(affected_inputs)
            )
        )
    ).all()
    readable = set()
    for identity in {str(uid) for _, uid in running if uid}:
        try:
            target = await db.get(User, uuid.UUID(identity))
        except ValueError:
            target = None
        if target and await check_dataset_access_permission(target, dataset_id, owner_user_id, db):
            readable.add(identity)
    affected: Dict[str, List[str]] = {}
    for task_id, task_user_id in running:
        if (owner_user_id and str(task_user_id) == str(owner_user_id)) or str(task_user_id) in readable:
            continue
        affected.setdefault(str(task_user_id), []).append(task_id)
    for task_ids in affected.values():
        await _cancel_training(task_ids)
    return affected


async def apply_dataset_visibility(db, dataset, is_public: bool) -> Dict[str, Any]:
    """Apply a visibility change inside the caller's transaction."""
    result: Dict[str, Any] = {}
    if dataset.is_public and not is_public:
        dataset.is_public = False
        await db.flush()
        stopped = await stop_non_owner_training_tasks(db, dataset.dataset_id, dataset.user_id)
        if stopped:
            result["revoked_training_tasks"] = sum(len(ids) for ids in stopped.values())
    dataset.is_public = is_public
    return result
