"""
Training task management routes
Handles training task creation, monitoring, and deletion
"""
import asyncio
import json
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import (
    WSIRepository,
    TrainingTaskRepository,
    TrainedModelRepository,
    TrainingLogRepository,
)
from ..dependencies import logger, storage_manager
from ..models import TrainingTaskRequest, DeletionMode
from ..pipeline import run_training_pipeline
from ..task_queue import get_task_queue, TaskType

router = APIRouter(prefix="/tasks/training", tags=["Training Tasks"])

@router.post("")
async def create_training_task(
    req: TrainingTaskRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new training task.
    Automatically extracts classes from selected WSI labels.
    """
    try:
        # Validate WSI IDs exist
        if not req.wsi_ids or len(req.wsi_ids) == 0:
            raise HTTPException(status_code=400, detail="At least one WSI must be selected")

        # Check all WSI IDs exist
        for wsi_id in req.wsi_ids:
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if not wsi:
                raise HTTPException(status_code=404, detail=f"WSI not found: {wsi_id}")

        # Generate task ID
        task_id = f"train_{uuid.uuid4().hex[:16]}"

        # Prepare task data
        task_data = {
            "task_id": task_id,
            "task_name": req.task_name,
            "task_type": req.task_type,
            "data_level": req.data_level,
            "task_description": req.task_description,
            "preprocessing_config": req.preprocessing,
            "model_config": req.model,
        }

        # Create training task (automatically extracts classes from WSI labels)
        split_config_dict = req.split_config.dict() if req.split_config else None
        task = await TrainingTaskRepository.create(db, task_data, req.wsi_ids, split_config=split_config_dict)
        await db.commit()

        logger.info(f"Created training task: {task_id}")
        logger.info(f"  - Task name: {req.task_name}")
        logger.info(f"  - Task type: {req.task_type}")
        logger.info(f"  - Data level: {req.data_level}")
        logger.info(f"  - WSI count: {len(req.wsi_ids)}")
        logger.info(f"  - Classes: {task.classes}")

        # Submit task to queue for execution
        # The queue manages GPU task concurrency to prevent overload
        task_queue = get_task_queue()
        pipeline_kwargs = {
            # Note: task_id is automatically added by task_queue.submit()
            "data_level": req.data_level,
            "wsi_ids": req.wsi_ids,
            "preprocessing_config": req.preprocessing,
            "model_config": req.model,
            "huggingface_token": req.huggingface_token,
            "training_task_type": req.task_type,  # Use different name to avoid conflict with TaskType enum
        }
        await task_queue.submit(
            task_id=task_id,
            task_type=TaskType.TRAINING,
            coro_func=run_training_pipeline,
            **pipeline_kwargs
        )

        # Return task info
        result = task.to_dict()
        result["wsi_count"] = len(req.wsi_ids)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create training task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create training task: {str(e)}")


@router.get("")
async def list_training_tasks(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """List all training tasks"""
    tasks = await TrainingTaskRepository.get_all(db, limit, skip)

    # Add WSI count to each task
    result_tasks = []
    for task in tasks:
        task_dict = task.to_dict()
        wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task.task_id)
        task_dict["wsi_count"] = len(wsi_ids)
        result_tasks.append(task_dict)

    return {"items": result_tasks}


@router.get("/stream")
async def stream_training_tasks():
    """
    Server-Sent Events endpoint for real-time training task updates.
    Streams task status and progress updates to connected clients.
    """
    async def event_generator():
        """Generate SSE events with task updates"""
        try:
            while True:
                # Get database session - let get_db() handle session lifecycle
                async for db in get_db():
                    # Fetch all training tasks
                    tasks = await TrainingTaskRepository.get_all(db, limit=100, offset=0)

                    # Add WSI count to each task
                    result_tasks = []
                    for task in tasks:
                        task_dict = task.to_dict()
                        wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task.task_id)
                        task_dict["wsi_count"] = len(wsi_ids)
                        result_tasks.append(task_dict)

                    # Send SSE event
                    data = json.dumps({"items": result_tasks})
                    yield f"data: {data}\n\n"

                # Wait 2 seconds before next update
                await asyncio.sleep(2)

        except asyncio.CancelledError:
            # Client disconnected
            logger.info("SSE client disconnected")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@router.get("/{task_id}")
async def get_training_task(
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get training task details"""
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    # Get associated WSI IDs
    wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task_id)

    result = task.to_dict()
    result["wsi_ids"] = wsi_ids
    result["wsi_count"] = len(wsi_ids)

    return result


@router.delete("/{task_id}")
async def delete_training_task(
    task_id: str,
    mode: str = "standard",
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a training task and associated files.

    Deletion modes:
    - "standard" (default): Delete training directory and logs only. Keep trained models.
    - "complete": Delete all files including trained models.

    This will:
    1. Get all trained models associated with this task
    2. Delete database records (task, associations, models, logs)
    3. Delete files using StorageManager based on mode

    Returns:
        {
            "message": "Training task deleted successfully",
            "task_id": str,
            "storage_cleanup": dict
        }
    """
    try:
        # Get task from database
        task = await TrainingTaskRepository.get_by_id(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Training task not found: {task_id}")

        # Get all trained models for this task
        models = await TrainedModelRepository.get_by_task_id(db, task_id)
        model_ids = [model.model_id for model in models]

        # Delete task from database (cascades to associations, models, logs)
        await TrainingTaskRepository.delete(db, task_id)
        await db.commit()

        # Delete files using StorageManager based on mode
        storage_cleanup = storage_manager.delete_training_task_files(task_id, model_ids, mode)
        logger.info(storage_cleanup['summary'])

        return {
            "message": "Training task deleted successfully",
            "task_id": task_id,
            "storage_cleanup": storage_cleanup
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete training task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete training task: {str(e)}")


@router.get("/{task_id}/logs")
async def get_training_logs(
    task_id: str,
    level: Optional[str] = Query(None, description="Filter by log level (INFO, WARNING, ERROR)"),
    limit: int = Query(100, description="Maximum number of logs to return"),
    offset: int = Query(0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get training logs for a specific task with optional filtering and pagination.

    Args:
        task_id: Training task ID
        level: Optional log level filter (INFO, WARNING, ERROR)
        limit: Maximum number of logs to return (default: 100)
        offset: Offset for pagination (default: 0)

    Returns:
        {
            "task_id": str,
            "logs": List[dict],
            "count": int,
            "limit": int,
            "offset": int
        }
    """
    # Verify task exists
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    # Get logs from database
    logs = await TrainingLogRepository.get_by_task_id(db, task_id, level, limit, offset)

    return {
        "task_id": task_id,
        "logs": [log.to_dict() for log in logs],
        "count": len(logs),
        "limit": limit,
        "offset": offset
    }


@router.get("/{task_id}/logs/stream")
async def stream_training_logs(task_id: str):
    """
    Real-time SSE streaming of training logs.

    Continuously streams new log entries as they are created.
    Uses Server-Sent Events (SSE) for true real-time updates.

    The stream will:
    1. Send initial batch of recent logs (last 50)
    2. Poll database every 1 second for new logs
    3. Send new logs as SSE events
    4. Continue until client disconnects or task completes
    """
    # Verify task exists first - let get_db() handle session lifecycle
    async for db in get_db():
        task = await TrainingTaskRepository.get_by_id(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Training task not found")

    async def log_event_generator():
        """Generate SSE events with new logs and task status updates"""
        last_sequence = 0

        try:
            # Send initial batch of recent logs and task status
            async for db in get_db():
                task = await TrainingTaskRepository.get_by_id(db, task_id)
                recent_logs = await TrainingLogRepository.get_recent(db, task_id, count=50)

                # Get WSI IDs for task
                wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task_id) if task else []

                # Build task dict with wsi_ids and wsi_count
                task_dict = None
                if task:
                    task_dict = task.to_dict()
                    task_dict["wsi_ids"] = wsi_ids
                    task_dict["wsi_count"] = len(wsi_ids)

                # Send initial data with both logs and task status
                data = json.dumps({
                    "logs": [log.to_dict() for log in recent_logs] if recent_logs else [],
                    "last_sequence": recent_logs[-1].sequence if recent_logs else 0,
                    "task": task_dict
                })
                yield f"data: {data}\n\n"

                if recent_logs:
                    last_sequence = recent_logs[-1].sequence

            # Continuously poll for new logs and task status
            while True:
                async for db in get_db():
                    # Get current task status
                    task = await TrainingTaskRepository.get_by_id(db, task_id)

                    # Get new logs since last sequence
                    new_logs = await TrainingLogRepository.get_logs_after_sequence(
                        db, task_id, last_sequence, limit=100
                    )

                    # Get WSI IDs for task
                    wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task_id) if task else []

                    # Build task dict with wsi_ids and wsi_count
                    task_dict = None
                    if task:
                        task_dict = task.to_dict()
                        task_dict["wsi_ids"] = wsi_ids
                        task_dict["wsi_count"] = len(wsi_ids)

                    # Always send task status update (even if no new logs)
                    # This ensures progress bar and status are updated in real-time
                    data = json.dumps({
                        "logs": [log.to_dict() for log in new_logs] if new_logs else [],
                        "last_sequence": new_logs[-1].sequence if new_logs else last_sequence,
                        "task": task_dict
                    })
                    yield f"data: {data}\n\n"

                    if new_logs:
                        last_sequence = new_logs[-1].sequence

                    # If task is completed, failed, or cancelled, send final event and stop
                    if task and task.status in ['completed', 'failed', 'cancelled']:
                        # Wait a bit to ensure all logs are sent
                        await asyncio.sleep(2)
                        # Send one more batch to catch any final logs
                        final_logs = await TrainingLogRepository.get_logs_after_sequence(
                            db, task_id, last_sequence, limit=100
                        )

                        # Build final task dict with wsi_ids and wsi_count
                        final_task_dict = task.to_dict()
                        final_task_dict["wsi_ids"] = wsi_ids
                        final_task_dict["wsi_count"] = len(wsi_ids)

                        data = json.dumps({
                            "logs": [log.to_dict() for log in final_logs] if final_logs else [],
                            "last_sequence": final_logs[-1].sequence if final_logs else last_sequence,
                            "task": final_task_dict,
                            "status": "complete"
                        })
                        yield f"data: {data}\n\n"
                        return  # Use return instead of break to properly exit generator

                # Poll every 1 second
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            # Client disconnected
            logger.info(f"SSE log stream disconnected for task {task_id}")
        except Exception as e:
            logger.error(f"Error in log stream for task {task_id}: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        log_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@router.get("/{task_id}/logs/recent")
async def get_recent_training_logs(
    task_id: str,
    count: int = Query(100, description="Number of recent logs to return"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the most recent N logs for a training task.

    Useful for quickly displaying the latest logs without pagination.
    """
    # Verify task exists
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    # Get recent logs
    logs = await TrainingLogRepository.get_recent(db, task_id, count)

    return {
        "task_id": task_id,
        "logs": [log.to_dict() for log in logs],
        "count": len(logs)
    }


@router.get("/{task_id}/models")
async def get_task_models(
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get all models from a training task"""
    models = await TrainedModelRepository.get_by_task_id(db, task_id)
    return {"items": [model.to_dict() for model in models]}

