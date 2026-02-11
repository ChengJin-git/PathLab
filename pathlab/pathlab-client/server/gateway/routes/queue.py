"""
Task Queue Management Routes

Provides API endpoints for monitoring and managing the GPU task queue.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..task_queue import get_task_queue
from ..dependencies import logger
from ..utils import cancel_ai_service_training
from backend.ai.schemas.base import TaskStatus
from backend.database import get_db
from backend.database.repositories import TrainingTaskRepository
from backend.common.config import Config
from backend.auth import current_active_user, User
from backend.auth.dependencies import require_admin, check_data_ownership
from .results import get_analysis_state

router = APIRouter(prefix="/queue", tags=["Task Queue"])

class QueueConfigRequest(BaseModel):
    """Request to update queue configuration"""
    max_concurrent: Optional[int] = Field(None, ge=1, le=10, description="Maximum concurrent GPU tasks (1-10)")
    task_timeout: Optional[int] = Field(None, ge=60, le=259200, description="Task timeout in seconds (60-259200)")


@router.get("/config")
async def get_queue_config(user: User = Depends(current_active_user)):
    """
    Get current queue and task configuration.

    Returns:
        {
            "max_concurrent": int,    # Maximum concurrent GPU tasks
            "task_timeout": int       # Task timeout in seconds
        }
    """
    queue = get_task_queue()
    max_concurrent = queue.max_concurrent if queue else 4

    return {
        "max_concurrent": max_concurrent,
        "task_timeout": Config.get_task_timeout()
    }


@router.get("")
async def get_queue_status(user: User = Depends(current_active_user)):
    """
    Get the current status of the task queue.

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
    queue = get_task_queue()
    if not queue:
        raise HTTPException(status_code=503, detail="Task queue not initialized")

    return queue.get_status()


@router.post("/config")
async def update_queue_config(
    req: QueueConfigRequest,
    user: User = Depends(require_admin)
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
        queue = get_task_queue()
        if not queue:
            raise HTTPException(status_code=503, detail="Task queue not initialized")

        # Prevent changing max_concurrent on single GPU systems
        if queue.gpu_count == 1 and req.max_concurrent != 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot change max_concurrent with single GPU. Only 1 concurrent task allowed."
            )

        try:
            await queue.set_max_concurrent(req.max_concurrent)
            # Persist to config file so it survives service restart
            Config.set_max_concurrent(req.max_concurrent)
            messages.append(f"max_concurrent updated to {req.max_concurrent}")
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
        raise HTTPException(status_code=400, detail="No configuration parameters provided")

    # Get current config
    queue = get_task_queue()
    return {
        "message": "; ".join(messages),
        "config": {
            "max_concurrent": queue.max_concurrent if queue else 4,
            "task_timeout": Config.get_task_timeout()
        }
    }


@router.delete("/{task_id}")
async def cancel_queued_task(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
            raise HTTPException(status_code=403, detail="You don't have permission to cancel this task")

        # Try to cancel the running asyncio.Task (for CPU-only analysis)
        task_cancelled = await analysis_state.cancel_running_task(task_id)

        # Update analysis state to cancelled
        if analysis_task.get("status") not in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            await analysis_state.set_cancelled(task_id)
            logger.info(f"Analysis task {task_id} cancelled by user (task_cancelled={task_cancelled})")
            return {
                "cancelled": True,
                "message": f"Analysis task {task_id} cancelled successfully"
            }
        elif task_cancelled:
            return {
                "cancelled": True,
                "message": f"Analysis task {task_id} cancelled"
            }
        else:
            return {
                "cancelled": False,
                "message": f"Analysis task {task_id} already completed or not found"
            }

    # Check if this is a training task (stored in database)
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if task and not check_data_ownership(task.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to cancel this task")

    queue = get_task_queue()
    if not queue:
        raise HTTPException(status_code=503, detail="Task queue not initialized")

    # Try to cancel in memory queue (this triggers asyncio.CancelledError in pipeline)
    cancelled_in_queue = await queue.cancel_task(task_id)

    # Also notify AI service to cancel training and release GPU
    # This is needed because the HTTP request to AI service may still be in progress
    await cancel_ai_service_training(task_id)

    # Always try to update database status (handles orphaned tasks after restart)
    if task and task.status not in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
        await TrainingTaskRepository.update_status(
            db,
            task_id,
            status=TaskStatus.CANCELLED,
            error_message="Task cancelled by user"
        )
        await db.commit()

        return {
            "cancelled": True,
            "message": f"Task {task_id} cancelled successfully"
        }
    elif cancelled_in_queue:
        return {
            "cancelled": True,
            "message": f"Task {task_id} cancelled from queue"
        }
    else:
        return {
            "cancelled": False,
            "message": f"Task {task_id} not found or already completed"
        }


@router.get("/{task_id}")
async def check_task_in_queue(
    task_id: str,
    user: User = Depends(current_active_user)
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
    queue = get_task_queue()
    if not queue:
        raise HTTPException(status_code=503, detail="Task queue not initialized")

    status_info = queue.get_status()

    if task_id in status_info["running_task_ids"]:
        return {
            "task_id": task_id,
            "in_queue": True,
            "status": "running"
        }
    elif task_id in status_info["pending_task_ids"]:
        return {
            "task_id": task_id,
            "in_queue": True,
            "status": "pending"
        }
    else:
        return {
            "task_id": task_id,
            "in_queue": False,
            "status": "not_found"
        }

