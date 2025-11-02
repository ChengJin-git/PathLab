"""
Training task management routes
Handles training task creation, monitoring, and deletion
"""
import json
import uuid
import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from smartresearch.services.backend.database import get_db
from smartresearch.services.backend.database.repositories import (
    WSIRepository,
    TrainingTaskRepository,
    TrainedModelRepository,
    TrainingLogRepository,
)
from ..dependencies import logger, storage_manager
from ..models import TrainingTaskRequest
from ..pipeline import run_training_pipeline

router = APIRouter(prefix="/tasks/training", tags=["Training Tasks"])


# Import training pipeline (will be defined in main.py or separate file)
async def run_training_pipeline(task_id, data_level, wsi_ids, preprocessing, model):
    """Placeholder - actual implementation in main.py"""
    pass


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
        task = await TrainingTaskRepository.create(db, task_data, req.wsi_ids)
        await db.commit()

        logger.info(f"Created training task: {task_id}")
        logger.info(f"  - Task name: {req.task_name}")
        logger.info(f"  - Task type: {req.task_type}")
        logger.info(f"  - Data level: {req.data_level}")
        logger.info(f"  - WSI count: {len(req.wsi_ids)}")
        logger.info(f"  - Classes: {task.classes}")

        # Start preprocessing pipeline asynchronously (with new DB session)
        asyncio.create_task(
            run_training_pipeline(task_id, req.data_level, req.wsi_ids, req.preprocessing, req.model)
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
                # Get database session
                async for db in get_db():
                    try:
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

                    finally:
                        await db.close()

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
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a training task and all associated files.

    This will:
    1. Get all trained models associated with this task
    2. Delete database records (task, associations, models, logs)
    3. Delete all files using StorageManager:
       - Training directory (all features)
       - Log files
       - Model directories

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

        # Delete all files using StorageManager
        storage_cleanup = storage_manager.delete_training_task_files(task_id, model_ids)
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
async def stream_training_logs(
    task_id: str,
    after_sequence: int = Query(0, description="Get logs after this sequence number"),
    db: AsyncSession = Depends(get_db)
):
    """
    Stream training logs using Server-Sent Events (SSE).

    This endpoint supports real-time log streaming by polling for new logs.
    Clients should track the last sequence number and request logs after that.

    For true real-time streaming, use WebSocket or implement SSE with async generators.
    This is a simplified polling-based approach.
    """
    # Verify task exists
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    # Get new logs after the specified sequence
    logs = await TrainingLogRepository.get_logs_after_sequence(db, task_id, after_sequence, limit=100)

    return {
        "task_id": task_id,
        "logs": [log.to_dict() for log in logs],
        "count": len(logs),
        "last_sequence": logs[-1].sequence if logs else after_sequence
    }


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

