"""
Task Queue Management Routes

Provides API endpoints for monitoring and managing the GPU task queue.
"""

from collections.abc import Mapping
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import logger
from ..utils import cancel_ai_service_training
from ..task_dispatch import is_worker_healthy, publish_task_cancellation
from task_worker.runtime_status import get_runtime_status, empty_runtime_status, RUNTIME_STATUS_TTL_SECONDS
from backend.ai.schemas.base import TaskStatus
from datetime import datetime, timezone, timedelta
from backend.database import get_db
from backend.database.repositories import TrainingTaskRepository, AITaskRepository
from backend.common.config import Config
from backend.auth import current_active_user, User
from backend.auth.dependencies import require_admin, check_data_ownership
from gateway.models import QueueConfigRequest
from .access_control import assert_owner
from .analysis_state import get_analysis_state

router = APIRouter(prefix="/queue", tags=["Task Queue"])


@router.get("/config")
async def get_queue_config(user: User = Depends(require_admin)):
    """
    Get current queue and task configuration. Admin only.

    Returns:
        {
            "max_concurrent": int,    # Maximum concurrent GPU tasks
            "task_timeout": int       # Task timeout in seconds
        }
    """
    return {
        "max_concurrent": Config.get_max_concurrent(default=4),
        "task_timeout": Config.get_task_timeout(),
    }


@router.get("")
async def get_queue_status(user: User = Depends(require_admin)):
    """
    Get the current status of the task queue. Admin only.

    Returns:
        {
            "max_concurrent": int,       # Maximum concurrent tasks allowed
            "running_count": int,        # Number of currently running tasks
            "pending_count": int,        # Number of tasks waiting in queue
            "queue_size": int,           # Total queue size
            "running_task_ids": list,    # IDs of running tasks
            "pending_task_ids": list,    # IDs of pending tasks
            "is_running": bool           # Whether the queue worker is running
        }
    """
    snapshot = await get_runtime_status()
    if snapshot is not None and _is_snapshot_fresh(snapshot):
        return {
            "max_concurrent": snapshot.get("max_concurrent") or Config.get_max_concurrent(default=4),
            "task_timeout": snapshot.get("task_timeout") or Config.get_task_timeout(),
            "running_count": snapshot.get("running_count", 0),
            "pending_count": snapshot.get("pending_count", 0),
            "queue_size": snapshot.get("queue_size", 0),
            "descriptor_pending_count": snapshot.get("descriptor_pending_count", 0),
            "descriptor_processing_count": snapshot.get("descriptor_processing_count", 0),
            "descriptor_dlq_count": snapshot.get("descriptor_dlq_count", 0),
            "running_task_ids": snapshot.get("running_task_ids", []),
            "pending_task_ids": snapshot.get("pending_task_ids", []),
            "patching_count": snapshot.get("patching_count", 0),
            "patching_task_ids": snapshot.get("patching_task_ids", []),
            "is_running": snapshot.get("is_running", False),
        }

    worker_running = await is_worker_healthy()
    fallback = empty_runtime_status(is_running=worker_running)
    return {
        "max_concurrent": Config.get_max_concurrent(default=4),
        "task_timeout": Config.get_task_timeout(),
        "running_count": fallback["running_count"],
        "pending_count": fallback["pending_count"],
        "queue_size": fallback["queue_size"],
        "descriptor_pending_count": fallback["descriptor_pending_count"],
        "descriptor_processing_count": fallback["descriptor_processing_count"],
        "descriptor_dlq_count": fallback["descriptor_dlq_count"],
        "running_task_ids": fallback["running_task_ids"],
        "pending_task_ids": fallback["pending_task_ids"],
        "patching_count": fallback["patching_count"],
        "patching_task_ids": fallback["patching_task_ids"],
        "is_running": fallback["is_running"],
    }


def _is_snapshot_fresh(snapshot: Mapping[str, object]) -> bool:
    updated_at_raw = snapshot.get("updated_at")
    if not updated_at_raw:
        return False
    try:
        updated_at = datetime.fromisoformat(str(updated_at_raw))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - updated_at
        return age <= timedelta(seconds=RUNTIME_STATUS_TTL_SECONDS)
    except (ValueError, TypeError):
        return False


@router.post("/config")
async def update_queue_config(
    req: QueueConfigRequest, user: User = Depends(require_admin)
):
    """
    Update queue configuration. Admin only.

    Supports updating:
    - max_concurrent: Maximum concurrent GPU tasks (1-10)
    - task_timeout: Task timeout in seconds (60-259200, i.e. 1 min to 3 days)

    Changes to max_concurrent take effect for new tasks only.
    Changes to task_timeout take effect for future training requests.

    Returns:
        Updated configuration
    """
    messages = []

    # Update max_concurrent if provided
    if req.max_concurrent is not None:
        try:
            max_concurrent = Config.set_max_concurrent(req.max_concurrent)
            messages.append(f"max_concurrent updated to {max_concurrent}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Update task_timeout if provided
    if req.task_timeout is not None:
        try:
            timeout = Config.set_task_timeout(req.task_timeout)
            messages.append(f"task_timeout updated to {timeout} seconds")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    if not messages:
        raise HTTPException(
            status_code=400, detail="No configuration parameters provided"
        )

    return {
        "message": "; ".join(messages),
        "config": {
            "max_concurrent": Config.get_max_concurrent(default=4),
            "task_timeout": Config.get_task_timeout(),
        },
    }


def _status_to_queue_state(status: object) -> Optional[str]:
    value = status.value if isinstance(status, TaskStatus) else str(status)
    value = value.split(".")[-1].lower()
    if value in {
        TaskStatus.QUEUED.value,
        TaskStatus.PENDING.value,
        TaskStatus.PATCHING.value,
        TaskStatus.RESUMING.value,
    }:
        return "pending"
    if value in {TaskStatus.TRAINING.value, TaskStatus.EXTRACTING.value}:
        return "running"
    return None


@router.delete("/{task_id}")
async def cancel_queued_task(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel a task in the queue. Users can only cancel their own tasks.

    Supports:
    - Training tasks (stored in database)
    - Analysis tasks (stored in memory via AnalysisTaskState)

    - If the task is running, it will be cancelled and GPU memory released
    - If the task is pending, it will be removed from the queue
    - Always updates the task status to 'cancelled'

    Returns:
        {"cancelled": bool, "message": str}
    """
    # First, check if this is an analysis task (stored in memory)
    analysis_state = get_analysis_state()
    analysis_task = await analysis_state.get(task_id)

    if analysis_task:
        # This is an analysis task - check ownership
        if not user.is_admin() and analysis_task.get("user_id") != str(user.id):
            raise HTTPException(
                status_code=403, detail="You don't have permission to cancel this task"
            )

        await publish_task_cancellation(task_id)

        # Try to cancel the running asyncio.Task when this process owns one.
        task_cancelled = await analysis_state.cancel_running_task(task_id)

        # Update analysis state to cancelled
        if analysis_task.get("status") not in [
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        ]:
            await analysis_state.set_cancelled(task_id)
            logger.info(
                f"Analysis task {task_id} cancelled by user (task_cancelled={task_cancelled})"
            )
            return {
                "cancelled": True,
                "message": f"Analysis task {task_id} cancelled successfully",
            }
        elif task_cancelled:
            return {"cancelled": True, "message": f"Analysis task {task_id} cancelled"}
        else:
            return {
                "cancelled": False,
                "message": f"Analysis task {task_id} already completed or not found",
            }

    # Check if this is a training task (stored in database)
    ai_task = await AITaskRepository.get_by_id(db, task_id)
    if ai_task:
        assert_owner(
            ai_task.user_id, user, "You don't have permission to cancel this task"
        )

    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if task:
        assert_owner(
            task.user_id, user, "You don't have permission to cancel this task"
        )

    if not ai_task and not task:
        return {
            "cancelled": False,
            "message": f"Task {task_id} not found or already completed",
        }

    await publish_task_cancellation(task_id)

    # Also notify AI service to cancel training and release GPU
    # This is needed because the HTTP request to AI service may still be in progress
    await cancel_ai_service_training(task_id)

    # Always try to update database status (handles orphaned tasks after restart)
    if ai_task and ai_task.status not in [
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    ]:
        await AITaskRepository.update_status(
            db,
            task_id,
            status=TaskStatus.CANCELLED,
            error_message="Task cancelled by user",
        )
        await db.commit()

        return {"cancelled": True, "message": f"Task {task_id} cancelled successfully"}
    elif task and task.status not in [
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    ]:
        await TrainingTaskRepository.update_status(
            db,
            task_id,
            status=TaskStatus.CANCELLED,
            error_message="Task cancelled by user",
        )
        await db.commit()

        return {"cancelled": True, "message": f"Task {task_id} cancelled successfully"}
    return {
        "cancelled": False,
        "message": f"Task {task_id} not found or already completed",
    }


@router.get("/{task_id}")
async def check_task_in_queue(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check if a task is in the queue.

    Returns:
        {
            "task_id": str,
            "in_queue": bool,
            "status": "running" | "pending" | "not_found"
        }
    """
    if not user.is_admin():
        analysis_state = get_analysis_state()
        analysis_task = await analysis_state.get(task_id)

        if analysis_task:
            if analysis_task.get("user_id") != str(user.id):
                return {"task_id": task_id, "in_queue": False, "status": "not_found"}
        else:
            ai_task = await AITaskRepository.get_by_id(db, task_id)
            if ai_task:
                if not check_data_ownership(ai_task.user_id, user):
                    return {
                        "task_id": task_id,
                        "in_queue": False,
                        "status": "not_found",
                    }
            else:
                training_task = await TrainingTaskRepository.get_by_id(db, task_id)
                if not training_task or not check_data_ownership(
                    training_task.user_id, user
                ):
                    return {
                        "task_id": task_id,
                        "in_queue": False,
                        "status": "not_found",
                    }

    analysis_state = get_analysis_state()
    analysis_task = await analysis_state.get(task_id)
    if analysis_task:
        queue_status = _status_to_queue_state(analysis_task.get("status"))
        return {
            "task_id": task_id,
            "in_queue": queue_status is not None,
            "status": queue_status or "not_found",
        }

    ai_task = await AITaskRepository.get_by_id(db, task_id)
    if ai_task:
        queue_status = _status_to_queue_state(ai_task.status)
        return {
            "task_id": task_id,
            "in_queue": queue_status is not None,
            "status": queue_status or "not_found",
        }

    training_task = await TrainingTaskRepository.get_by_id(db, task_id)
    if training_task:
        queue_status = _status_to_queue_state(training_task.status)
        return {
            "task_id": task_id,
            "in_queue": queue_status is not None,
            "status": queue_status or "not_found",
        }

    return {"task_id": task_id, "in_queue": False, "status": "not_found"}
