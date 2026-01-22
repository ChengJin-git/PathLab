"""
Task Queue Management Routes

Provides API endpoints for monitoring and managing the GPU task queue.
"""
import httpx
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..task_queue import get_task_queue
from ..dependencies import logger, AI_SERVICE_URL
from backend.database import get_db
from backend.database.repositories import TrainingTaskRepository

router = APIRouter(prefix="/queue", tags=["Task Queue"])


async def _cancel_ai_service_training(task_id: str) -> None:
    """
    Request AI service to cancel a training task and release GPU.

    Called when user cancels a task. Uses fire-and-forget pattern:
    sends the request and returns immediately without waiting for response,
    since AI service may be blocked by GPU training.
    """
    try:
        # Fire-and-forget: very short timeout, we don't care about the response
        async with httpx.AsyncClient(timeout=1.0) as client:
            await client.delete(f"{AI_SERVICE_URL}/api/ai/training/{task_id}")
            logger.info(f"Sent cancellation request to AI service for task {task_id}")
    except httpx.TimeoutException:
        # Expected - AI service is blocked by GPU training, but flag is already set
        logger.info(f"Cancellation request sent to AI service for task {task_id} (fire-and-forget)")
    except Exception as e:
        # Best effort - don't fail the main flow if cancellation fails
        logger.warning(f"Failed to send cancellation to AI service for task {task_id}: {e}")


class QueueConfigRequest(BaseModel):
    """Request to update queue configuration"""
    max_concurrent: int = Field(..., ge=1, le=10, description="Maximum concurrent GPU tasks (1-10)")


@router.get("")
async def get_queue_status():
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
async def update_queue_config(req: QueueConfigRequest):
    """
    Update queue configuration.
    
    Currently supports updating max_concurrent only.
    Changes take effect for new tasks only - running tasks are not affected.
    
    Args:
        max_concurrent: New maximum concurrent GPU tasks (1-10)
        
    Returns:
        Updated queue status
    """
    queue = get_task_queue()
    if not queue:
        raise HTTPException(status_code=503, detail="Task queue not initialized")
    
    try:
        queue.set_max_concurrent(req.max_concurrent)
        return {
            "message": f"max_concurrent updated to {req.max_concurrent}",
            "status": queue.get_status()
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{task_id}")
async def cancel_queued_task(task_id: str, db: AsyncSession = Depends(get_db)):
    """
    Cancel a task in the queue.

    - If the task is running, it will be cancelled and GPU memory released
    - If the task is pending, it will be removed from the queue
    - Always updates the database status to 'cancelled'
      (handles orphaned tasks after server restart)

    Returns:
        {"cancelled": bool, "message": str}
    """
    queue = get_task_queue()
    if not queue:
        raise HTTPException(status_code=503, detail="Task queue not initialized")

    # Try to cancel in memory queue (this triggers asyncio.CancelledError in pipeline)
    cancelled_in_queue = await queue.cancel_task(task_id)

    # Also notify AI service to cancel training and release GPU
    # This is needed because the HTTP request to AI service may still be in progress
    await _cancel_ai_service_training(task_id)

    # Always try to update database status (handles orphaned tasks after restart)
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if task and task.status not in ["completed", "failed", "cancelled"]:
        await TrainingTaskRepository.update_status(
            db,
            task_id,
            status="cancelled",
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
async def check_task_in_queue(task_id: str):
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

