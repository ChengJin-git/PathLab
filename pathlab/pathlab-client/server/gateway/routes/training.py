"""
Training task management routes
Handles training task creation, monitoring, and deletion
"""
import asyncio
import json
import os
import uuid
from typing import Optional
import httpx
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.database.repositories import (
    WSIRepository,
    TrainingTaskRepository,
    TrainedModelRepository,
    TrainingLogRepository,
    DataGroupRepository,
    DatasetRepository,
    StorageTaskRepository,
)
from backend.auth import current_active_user, User, get_user_from_token_param
from backend.auth.dependencies import require_can_use_gpu, require_pathologist_or_admin, check_data_ownership, check_dataset_gpu_permission, get_user_id_filter, check_wsi_access_permission
from backend.common.config import Config
from ..dependencies import logger, storage_manager, AI_SERVICE_URL
from ..models import TrainingTaskRequest, DeletionMode
from ..pipeline import run_training_pipeline
from ..task_queue import get_task_queue, TaskType

router = APIRouter(prefix="/tasks/training", tags=["Training Tasks"])


async def _cancel_ai_service_training(task_id: str) -> None:
    """
    Request AI service to cancel a training task and release GPU.

    Called when deleting a task that might still be running.
    Uses fire-and-forget pattern since AI service may be blocked by GPU training.
    """
    try:
        # Fire-and-forget: very short timeout, we don't care about the response
        async with httpx.AsyncClient(timeout=1.0) as client:
            await client.delete(f"{AI_SERVICE_URL}/api/ai/training/{task_id}")
            logger.info(f"Sent cancellation request to AI service for task {task_id}")
    except httpx.TimeoutException:
        # Expected - AI service is blocked by GPU training, but flag is already set
        logger.debug(f"Cancellation request sent to AI service for task {task_id} (fire-and-forget)")
    except Exception as e:
        # Best effort - don't fail the delete if cancellation fails
        logger.debug(f"Failed to send cancellation to AI service for task {task_id}: {e}")

@router.post("")
async def create_training_task(
    req: TrainingTaskRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new training task.
    Requires pathologist/admin role OR temporary elevated permission for all involved datasets.
    Automatically extracts classes from selected WSI labels.
    """
    try:
        # Validate WSI IDs exist
        if not req.wsi_ids or len(req.wsi_ids) == 0:
            raise HTTPException(status_code=400, detail="At least one WSI must be selected")

        # Batch fetch all WSIs in a single query to avoid N+1 problem
        # This is much faster than fetching one by one, especially for large datasets
        wsi_map = await WSIRepository.get_by_ids_with_dataset(db, req.wsi_ids)

        # Check for missing WSIs
        missing_wsi_ids = [wsi_id for wsi_id in req.wsi_ids if wsi_id not in wsi_map]
        if missing_wsi_ids:
            raise HTTPException(status_code=404, detail=f"WSI not found: {missing_wsi_ids[0]}")

        # Collect all dataset IDs involved in this training task
        dataset_ids_involved = set()

        # Track inaccessible files and permission issues
        inaccessible_files = []

        # Build list of paths to check for file existence
        paths_to_check = []
        for wsi_id in req.wsi_ids:
            wsi = wsi_map[wsi_id]
            # Check access permission (ownership or elevated dataset permission)
            has_access = await check_wsi_access_permission(user, wsi.dataset_id, wsi.user_id, db)
            if not has_access:
                raise HTTPException(status_code=403, detail=f"You don't have permission to use WSI: {wsi_id}")
            dataset_ids_involved.add(wsi.dataset_id)

            # Collect paths for concurrent file existence check
            if wsi.wsi_path:
                paths_to_check.append((wsi_id, wsi.wsi_path, wsi.original_filename))

        # Check file accessibility concurrently using asyncio.to_thread
        # This avoids blocking the event loop on I/O operations
        async def check_file_exists(wsi_id: str, path: str, filename: str) -> tuple:
            exists = await asyncio.to_thread(os.path.exists, path)
            return (wsi_id, path, filename, exists)

        if paths_to_check:
            file_check_tasks = [
                check_file_exists(wsi_id, path, filename)
                for wsi_id, path, filename in paths_to_check
            ]
            results = await asyncio.gather(*file_check_tasks)
            for wsi_id, path, filename, exists in results:
                if not exists:
                    inaccessible_files.append(filename or wsi_id)

        # Report inaccessible files
        if inaccessible_files:
            if len(inaccessible_files) <= 5:
                files_str = ", ".join(inaccessible_files)
            else:
                files_str = ", ".join(inaccessible_files[:5]) + f" and {len(inaccessible_files) - 5} more"
            raise HTTPException(
                status_code=400,
                detail=f"The following files are not accessible: {files_str}"
            )

        # Check if there are any active batch import tasks
        active_storage_tasks = await StorageTaskRepository.get_active_tasks(db)
        batch_import_tasks = [t for t in active_storage_tasks if t.task_type == 'batch_import']
        if batch_import_tasks:
            raise HTTPException(
                status_code=400,
                detail="Cannot submit training task while files are being imported. Please wait for all imports to complete."
            )

        # Check GPU permission for all involved datasets
        # User must have base GPU access OR temporary elevated permission for ALL datasets
        if not user.can_use_gpu():
            # Check each dataset for temporary elevated permission
            for dataset_id in dataset_ids_involved:
                has_permission = await check_dataset_gpu_permission(user, dataset_id, db)
                if not has_permission:
                    raise HTTPException(
                        status_code=403,
                        detail=f"GPU operations not available. You need pathologist access or temporary elevated permission for dataset: {dataset_id}"
                    )

        # Generate task ID
        task_id = f"train_{uuid.uuid4().hex[:16]}"

        # Determine aggregation_level from the first WSI's dataset's DataGroup
        # Default to 'file' if not found
        aggregation_level = "file"
        first_wsi = wsi_map.get(req.wsi_ids[0])
        if first_wsi and first_wsi.dataset_id:
            first_dataset = await DatasetRepository.get_by_id(db, first_wsi.dataset_id)
            if first_dataset and first_dataset.data_group:
                aggregation_level = first_dataset.data_group.aggregation_level

        # Get or create DataGroup for this training task
        data_group = await DataGroupRepository.get_or_create(
            db,
            data_type=req.data_level,  # 'wsi' or 'patch'
            aggregation_level=aggregation_level,  # 'file' or 'case'
            task_type=req.task_type  # 'classification' or 'survival_prediction'
        )

        # Prepare task data
        task_data = {
            "task_id": task_id,
            "task_name": req.task_name,
            "task_type": req.task_type,  # Add task_type for validation
            "group_id": data_group.group_id,
            "task_description": req.task_description,
            "preprocessing_config": req.preprocessing,
            "model_config": req.model,
            "user_id": str(user.id),  # Associate with current user
        }

        # Create training task (automatically extracts classes from WSI labels)
        # This will validate that classification tasks have >=2 classes and survival tasks have both event types
        split_config_dict = req.split_config.dict() if req.split_config else None
        try:
            task = await TrainingTaskRepository.create(db, task_data, req.wsi_ids, split_config=split_config_dict)
            await db.commit()
        except ValueError as e:
            # Convert validation errors to HTTP 400 Bad Request
            raise HTTPException(status_code=400, detail=str(e))

        logger.info(f"Created training task: {task_id}")
        logger.info(f"  - Task name: {req.task_name}")
        logger.info(f"  - Task type: {req.task_type} (from DataGroup: {data_group.task_type})")
        logger.info(f"  - Data type: {req.data_level}, Aggregation level: {aggregation_level}")
        logger.info(f"  - WSI count: {len(req.wsi_ids)}")
        logger.info(f"  - Classes: {task.classes}")

        # Submit task to queue for execution
        # The queue manages GPU task concurrency to prevent overload
        task_queue = get_task_queue()

        # Get huggingface_token: request > global settings
        global_settings = Config.get_global_settings()
        huggingface_token = req.huggingface_token or global_settings.get("huggingface_token", "")

        pipeline_kwargs = {
            # Note: task_id is automatically added by task_queue.submit()
            # data_level here refers to data_type ('wsi' or 'patch') - kept for pipeline compatibility
            "data_level": req.data_level,
            "wsi_ids": req.wsi_ids,
            "preprocessing_config": req.preprocessing,
            "model_config": req.model,
            "huggingface_token": huggingface_token,
            "training_task_type": req.task_type,  # Use different name to avoid conflict with TaskType enum
        }
        # Use positional arguments to avoid conflict: submit()'s task_type (for queue) vs pipeline_kwargs' training_task_type (for coro_func)
        await task_queue.submit(
            task_id,
            TaskType.TRAINING,  # This is for queue management (training/inference)
            run_training_pipeline,
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
    user_id_filter: Optional[str] = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db)
):
    """List training tasks. Users see only their own tasks, admin sees all."""
    tasks = await TrainingTaskRepository.get_all(db, limit, skip, user_id=user_id_filter)
    total = await TrainingTaskRepository.count(db, user_id=user_id_filter)

    # Batch get WSI counts for all tasks (avoids N+1 query)
    task_ids = [task.task_id for task in tasks]
    wsi_counts = await TrainingTaskRepository.get_wsi_counts_batch(db, task_ids)

    # Add WSI count to each task
    result_tasks = []
    for task in tasks:
        task_dict = task.to_dict()
        task_dict["wsi_count"] = wsi_counts.get(task.task_id, 0)
        result_tasks.append(task_dict)

    return {"items": result_tasks, "total": total}


@router.get("/stream")
async def stream_training_tasks(user: User = Depends(get_user_from_token_param)):
    """
    Server-Sent Events endpoint for real-time training task updates.
    Streams task status and progress updates to connected clients.
    Users see only their own tasks, admin sees all.

    Note: Uses token query parameter for authentication since EventSource API
    doesn't support custom headers. Token is passed via URL: ?token=<jwt>
    """
    # Capture user info before SSE stream starts
    user_id_filter = None if user.is_admin() else str(user.id)

    async def event_generator():
        """Generate SSE events with task updates"""
        try:
            while True:
                # Use async_session directly to ensure proper connection management
                # This avoids issues with get_db() generator in long-running SSE streams
                async with async_session() as db:
                    try:
                        # Fetch training tasks filtered by user
                        tasks = await TrainingTaskRepository.get_all(db, limit=100, offset=0, user_id=user_id_filter)

                        # Batch get WSI counts for all tasks (avoids N+1 query)
                        task_ids = [task.task_id for task in tasks]
                        wsi_counts = await TrainingTaskRepository.get_wsi_counts_batch(db, task_ids)

                        # Add WSI count to each task
                        result_tasks = []
                        for task in tasks:
                            task_dict = task.to_dict()
                            task_dict["wsi_count"] = wsi_counts.get(task.task_id, 0)
                            result_tasks.append(task_dict)

                        # Send SSE event
                        data = json.dumps({"items": result_tasks})
                        yield f"data: {data}\n\n"
                    except Exception as e:
                        logger.error(f"Error fetching training tasks in SSE: {e}")
                        yield f"data: {json.dumps({'error': str(e)})}\n\n"

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
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get training task details. Users can only view their own tasks, admin can view all."""
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    # Check ownership
    if not check_data_ownership(task.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to view this task")

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
    user: User = Depends(require_pathologist_or_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a training task and associated files.
    Requires pathologist or admin role. Users can only delete their own tasks, admin can delete any.

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

        # Check ownership
        if not check_data_ownership(task.user_id, user):
            raise HTTPException(status_code=403, detail="You don't have permission to delete this task")

        # If task is still running or queued, cancel it first to release GPU
        if task.status in ["pending", "resuming", "running", "preprocessing", "extracting", "training"]:
            await _cancel_ai_service_training(task_id)

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
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get training logs for a specific task with optional filtering and pagination.
    Users can only view logs for their own tasks, admin can view all.

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

    # Check ownership
    if not check_data_ownership(task.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to view this task's logs")

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
    user: User = Depends(get_user_from_token_param)
):
    """
    Real-time SSE streaming of training logs.
    Users can only stream logs for their own tasks, admin can stream all.

    Continuously streams new log entries as they are created.
    Uses Server-Sent Events (SSE) for true real-time updates.

    Note: Uses token query parameter for authentication since EventSource API
    doesn't support custom headers. Token is passed via URL: ?token=<jwt>

    The stream will:
    1. Send initial batch of recent logs (last 50)
    2. Poll database every 1 second for new logs
    3. Send new logs as SSE events
    4. Continue until client disconnects or task completes
    """
    # Verify task exists and check ownership first
    async with async_session() as db:
        task = await TrainingTaskRepository.get_by_id(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Training task not found")

        # Check ownership
        if not check_data_ownership(task.user_id, user):
            raise HTTPException(status_code=403, detail="You don't have permission to stream this task's logs")

    async def log_event_generator():
        """Generate SSE events with new logs and task status updates"""
        last_sequence = 0

        try:
            # Send initial batch of recent logs and task status
            async with async_session() as db:
                try:
                    task = await TrainingTaskRepository.get_by_id(db, task_id)
                    # For completed/failed tasks, load all logs; for running tasks, load recent 50
                    log_count = 10000 if task and task.status in ('completed', 'failed', 'cancelled') else 50
                    recent_logs = await TrainingLogRepository.get_recent(db, task_id, count=log_count)

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
                except Exception as e:
                    logger.error(f"Error fetching initial logs for task {task_id}: {e}")
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"

            # Continuously poll for new logs and task status
            while True:
                async with async_session() as db:
                    try:
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
                    except Exception as e:
                        logger.error(f"Error polling logs for task {task_id}: {e}")
                        yield f"data: {json.dumps({'error': str(e)})}\n\n"

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
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the most recent N logs for a training task.
    Users can only view logs for their own tasks, admin can view all.

    Useful for quickly displaying the latest logs without pagination.
    """
    # Verify task exists
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    # Check ownership
    if not check_data_ownership(task.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to view this task's logs")

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
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all models from a training task. Users can only view their own tasks' models, admin can view all."""
    # Verify task exists
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    # Check ownership
    if not check_data_ownership(task.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to view this task's models")

    models = await TrainedModelRepository.get_by_task_id(db, task_id)
    return {"items": [model.to_dict() for model in models], "total": len(models)}

