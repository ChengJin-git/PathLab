"""
Training task management routes
Handles training task creation, monitoring, and deletion
"""

import asyncio
import json
import uuid
from typing import Optional, Any
from fastapi import APIRouter, HTTPException, Depends, Query

from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session, safe_session
from backend.database.repositories import (
    WSIRepository,
    AIResultRepository,
    TrainingTaskRepository,
    TrainedModelRepository,
    TrainingLogRepository,
    DataGroupRepository,
    DatasetRepository,
)
from backend.auth import current_active_user, User, get_user_from_token_param
from backend.auth.dependencies import (
    require_can_use_gpu,
    require_pathologist_or_admin,
    check_dataset_gpu_permission,
    get_user_id_filter,
    check_wsi_access_permission,
)
from .access_control import assert_owner
from ..utils import ensure_dataset_segmentation_contract
from backend.ai.schemas.base import TaskStatus
from backend.common.config import Config
from backend.database.utils.training_logger import TrainingLogger
from ..dependencies import logger, make_sse_response, storage_manager
from ..models import TrainingTaskRequest, TrainingTaskUpdateRequest, DeletionMode
from ..pipeline import run_training_pipeline, run_patching_then_submit
from ..task_queue import get_task_queue, TaskType
from ..utils import cancel_ai_service_training, require_no_active_batch_imports
from gateway.chat.context_cache import invalidate_chat_context
from gateway.training_preflight import (
    build_training_preflight_policy,
    check_training_inputs,
)

router = APIRouter(prefix="/tasks/training", tags=["Training Tasks"])


async def _has_wsi_training_access(user: User, wsi: Any, db: AsyncSession) -> bool:
    dataset_is_public = bool(wsi.dataset and getattr(wsi.dataset, "is_public", False))
    parent_dataset_id = (
        wsi.dataset.parent_dataset_id
        if wsi.dataset and getattr(wsi.dataset, "parent_dataset_id", None)
        else None
    )
    return await check_wsi_access_permission(
        user,
        wsi.dataset_id,
        wsi.user_id,
        db,
        dataset_is_public=dataset_is_public,
        parent_dataset_id=parent_dataset_id,
    )


async def _check_file_accessibility(
    paths_to_check: list[tuple[Any, ...]],
    uploads_dir: str,
) -> list[str]:
    result = await check_training_inputs(
        paths_to_check=paths_to_check,
        uploads_dir=uploads_dir,
        policy=build_training_preflight_policy(),
        warn_fn=logger.warning,
    )
    return result.inaccessible


async def _validate_files_and_enqueue(
    task_id: str,
    paths_to_check: list[tuple[Any, ...]],
    uploads_dir: str,
    pipeline_kwargs: dict[str, Any],
) -> None:
    training_logger = TrainingLogger(task_id)

    async def _fail(detail: str) -> None:
        logger.error(f"Training task {task_id} failed pre-flight file check: {detail}")
        async with safe_session() as db:
            await TrainingTaskRepository.update_status(db, task_id, TaskStatus.FAILED)
            await db.commit()
        await training_logger.error(
            f"[PreFlight] {detail}",
            metadata={"status": TaskStatus.FAILED},
        )

    try:
        inaccessible = await _check_file_accessibility(paths_to_check, uploads_dir)
    except HTTPException as exc:
        await _fail(exc.detail)
        return
    except Exception as exc:
        await _fail(f"Unexpected error during file accessibility check: {exc}")
        return

    if inaccessible:
        if len(inaccessible) <= 5:
            files_str = ", ".join(inaccessible)
        else:
            files_str = (
                ", ".join(inaccessible[:5]) + f" and {len(inaccessible) - 5} more"
            )
        await _fail(f"The following files are not accessible: {files_str}")
        return

    task_queue = get_task_queue()

    if pipeline_kwargs.get("data_type") == "wsi":
        patching_coro = run_patching_then_submit(task_id, pipeline_kwargs)
        patching_task = asyncio.create_task(patching_coro)
        task_queue.register_patching_task(task_id, patching_task)

        await training_logger.info(
            "[PreQueue] Starting patch extraction before GPU queue submission",
            metadata={
                "status": TaskStatus.PATCHING,
                "task_type": pipeline_kwargs.get("training_task_type"),
                "data_type": "wsi",
                "wsi_count": len(pipeline_kwargs.get("wsi_ids", [])),
            },
        )
    else:
        await task_queue.submit(
            task_id=task_id,
            task_type=TaskType.TRAINING,
            coro_func=run_training_pipeline,
            **pipeline_kwargs,
        )

        async with safe_session() as db:
            await TrainingTaskRepository.update_status(
                db, task_id, TaskStatus.QUEUED, progress=0
            )
            await db.commit()

        await training_logger.info(
            "[Queue] Patch task submitted to GPU queue, waiting for available worker/GPU resources",
            metadata={
                "status": TaskStatus.QUEUED,
                "task_type": pipeline_kwargs.get("training_task_type"),
                "data_type": pipeline_kwargs.get("data_type"),
                "wsi_count": len(pipeline_kwargs.get("wsi_ids", [])),
            },
        )


@router.post("")
async def create_training_task(
    req: TrainingTaskRequest,
    user: User = Depends(current_active_user),
):
    """
    Create a new training task.
    Requires pathologist/admin role OR temporary elevated permission for all involved datasets.
    Automatically extracts classes from selected WSI labels.

    Uses short-lived database sessions to avoid connection pool exhaustion when other
    training tasks are running.
    """
    try:
        effective_task_owner_user_id = str(user.id)

        # Resolve WSI IDs: prefer dataset_id (server-side resolution) over client-provided wsi_ids
        wsi_ids = req.wsi_ids or []
        if not wsi_ids and req.dataset_id:
            async with safe_session() as db:
                wsi_ids = await DatasetRepository.get_wsi_ids(db, req.dataset_id)
            if not wsi_ids:
                raise HTTPException(
                    status_code=400,
                    detail="No WSI files found in the specified dataset",
                )
        if not wsi_ids:
            raise HTTPException(
                status_code=400, detail="At least one WSI must be selected"
            )

        expected_task_type = None
        expected_data_type = None
        expected_aggregation_level = "file"

        # --- Session 1: Read-only validations (fetch WSIs, check permissions, check storage tasks) ---
        async with safe_session() as db:
            if user.is_admin() and req.rerun_from_task_id:
                source_task = await TrainingTaskRepository.get_by_id(
                    db, req.rerun_from_task_id
                )
                if not source_task:
                    raise HTTPException(
                        status_code=404,
                        detail="Source training task not found for rerun",
                    )
                if source_task.user_id:
                    effective_task_owner_user_id = source_task.user_id

            # Batch fetch all WSIs in a single query to avoid N+1 problem
            wsi_map = await WSIRepository.get_by_ids_with_dataset(db, wsi_ids)

            # Check for missing WSIs
            missing_wsi_ids = [wsi_id for wsi_id in wsi_ids if wsi_id not in wsi_map]
            if missing_wsi_ids:
                raise HTTPException(
                    status_code=404, detail=f"WSI not found: {missing_wsi_ids[0]}"
                )

            # Collect dataset IDs and check access permissions
            dataset_ids_involved = set()
            paths_to_check = []

            if user.is_admin():
                # Admin can access everything - skip per-WSI permission check
                for wsi_id in wsi_ids:
                    wsi = wsi_map[wsi_id]
                    dataset_ids_involved.add(wsi.dataset_id)
                    if wsi.wsi_path:
                        paths_to_check.append(
                            (wsi_id, wsi.wsi_path, wsi.original_filename)
                        )
            else:
                for wsi_id in wsi_ids:
                    wsi = wsi_map[wsi_id]
                    has_access = await _has_wsi_training_access(user, wsi, db)
                    if not has_access:
                        raise HTTPException(
                            status_code=403,
                            detail=f"You don't have permission to use WSI: {wsi_id}",
                        )
                    dataset_ids_involved.add(wsi.dataset_id)
                    if wsi.wsi_path:
                        paths_to_check.append(
                            (wsi_id, wsi.wsi_path, wsi.original_filename)
                        )

            await require_no_active_batch_imports(
                db,
                detail="Cannot submit training task while files are being imported. Please wait for all imports to complete.",
            )

            dataset_ids = [
                dataset_id for dataset_id in dataset_ids_involved if dataset_id
            ]
            dataset_map = {
                dataset.dataset_id: dataset
                for dataset in await DatasetRepository.get_by_ids(db, list(dataset_ids))
            }
            group_contracts = set()
            for dataset_id in dataset_ids:
                dataset = dataset_map.get(dataset_id)
                if dataset is None:
                    raise HTTPException(
                        status_code=400, detail=f"Dataset not found: {dataset_id}"
                    )
                data_group = ensure_dataset_segmentation_contract(
                    dataset, context="Training dataset"
                )
                group_contracts.add(
                    (
                        data_group.task_type,
                        data_group.data_type,
                        data_group.aggregation_level,
                    )
                )

            if len(group_contracts) != 1:
                raise HTTPException(
                    status_code=400,
                    detail="All selected files must belong to datasets with the same task_type, data_type, and aggregation_level",
                )

            if group_contracts:
                expected_task_type, expected_data_type, expected_aggregation_level = (
                    group_contracts.pop()
                )
                if req.task_type != expected_task_type:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Requested task_type '{req.task_type}' does not match dataset task_type '{expected_task_type}'",
                    )
                if req.data_type != expected_data_type:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Requested data_type '{req.data_type}' does not match dataset data_type '{expected_data_type}'",
                    )

            # Check GPU permission for non-GPU users (in same session)
            if not user.can_use_gpu():
                for dataset_id in dataset_ids_involved:
                    has_permission = await check_dataset_gpu_permission(
                        user, dataset_id, db
                    )
                    if not has_permission:
                        raise HTTPException(
                            status_code=403,
                            detail=f"GPU operations not available. You need pathologist access or temporary elevated permission for dataset: {dataset_id}",
                        )

        # Use client-provided task_id (for fire-and-forget submission) or generate one
        task_id = req.task_id or f"train_{uuid.uuid4().hex[:16]}"

        # --- Session 2: Write - create task and WSI associations ---
        async with safe_session() as db:
            aggregation_level = expected_aggregation_level

            # Get or create DataGroup for this training task
            data_group = await DataGroupRepository.get_or_create(
                db,
                data_type=req.data_type,  # 'wsi' or 'patch'
                aggregation_level=aggregation_level,  # 'file' or 'case'
                task_type=req.task_type,  # 'classification' or 'survival'
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
                "user_id": effective_task_owner_user_id,
            }

            # Create training task with pre-fetched WSIs (avoids redundant DB query)
            split_config_dict = req.split_config.dict() if req.split_config else None
            pipeline_preprocessing_config = dict(req.preprocessing or {})
            if split_config_dict is not None:
                pipeline_preprocessing_config["split_config"] = split_config_dict
            # Preserve the original WSI ordering used to resolve `wsi_ids`.
            # Survival/random/k-fold split generation is order-sensitive when
            # stratified splitting shuffles indices with a fixed seed, so we
            # must keep the same order as dataset export / selection flows.
            prefetched_wsis = [wsi_map[wsi_id] for wsi_id in wsi_ids if wsi_id in wsi_map]
            try:
                task = await TrainingTaskRepository.create(
                    db,
                    task_data,
                    wsi_ids,
                    split_config=split_config_dict,
                    prefetched_wsis=prefetched_wsis,
                )
                await db.commit()
            except ValueError as e:
                # Convert validation errors to HTTP 400 Bad Request
                raise HTTPException(status_code=400, detail=str(e))

        logger.info(f"Created training task: {task_id}")
        logger.info(f"  - Task name: {req.task_name}")
        logger.info(
            f"  - Task type: {req.task_type} (from DataGroup: {data_group.task_type})"
        )
        logger.info(
            f"  - Data type: {req.data_type}, Aggregation level: {aggregation_level}"
        )
        logger.info(f"  - WSI count: {len(wsi_ids)}")
        logger.info(f"  - Classes: {task.classes}")

        global_settings = Config.get_global_settings()
        huggingface_token = req.huggingface_token or global_settings.get(
            "huggingface_token", ""
        )

        pipeline_kwargs = {
            "data_type": req.data_type,
            "wsi_ids": wsi_ids,
            "preprocessing_config": pipeline_preprocessing_config,
            "model_config": req.model,
            "huggingface_token": huggingface_token,
            "training_task_type": req.task_type,
            "user_id": str(user.id),
            "user_is_admin": user.is_admin(),
        }

        asyncio.create_task(
            _validate_files_and_enqueue(
                task_id=task_id,
                paths_to_check=paths_to_check,
                uploads_dir=str(Config.get_uploads_dir()),
                pipeline_kwargs=pipeline_kwargs,
            )
        )
        await invalidate_chat_context(effective_task_owner_user_id)

        result = task.to_dict()
        result["status"] = TaskStatus.PENDING
        result["progress"] = 0
        result["wsi_count"] = len(wsi_ids)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create training task: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create training task: {str(e)}"
        )


@router.get("")
async def list_training_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search by task name or task ID"),
    status_filter: str = Query(
        "all", description="all|running|completed|failed|cancelled"
    ),
    sort_by: str = Query("updated", description="updated|created|name"),
    user: User = Depends(current_active_user),
    user_id_filter: Optional[str] = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db),
):
    """List training tasks. Users see only their own tasks, admin sees all (with username)."""
    valid_status_filters = {"all", "running", "completed", "failed", "cancelled"}
    if status_filter not in valid_status_filters:
        raise HTTPException(
            status_code=400, detail=f"Invalid status_filter: {status_filter}"
        )

    valid_sort_fields = {"updated", "created", "name"}
    if sort_by not in valid_sort_fields:
        raise HTTPException(status_code=400, detail=f"Invalid sort_by: {sort_by}")

    skip = (page - 1) * page_size
    # Admin users get username information
    include_username = user.is_admin()

    tasks = await TrainingTaskRepository.get_all(
        db,
        page_size,
        skip,
        user_id=user_id_filter,
        include_username=include_username,
        search=search,
        status_filter=status_filter,
        sort_by=sort_by,
    )
    total = await TrainingTaskRepository.count(
        db,
        user_id=user_id_filter,
        search=search,
        status_filter=status_filter,
    )
    stats = await TrainingTaskRepository.get_status_counts(db, user_id=user_id_filter)

    # Batch get WSI counts for all tasks (avoids N+1 query)
    if include_username:
        # tasks is already a list of dicts
        task_ids = [task["task_id"] for task in tasks]
    else:
        # tasks is a list of TrainingTask objects
        task_ids = [task.task_id for task in tasks]

    wsi_counts = await TrainingTaskRepository.get_wsi_counts_batch(db, task_ids)
    source_dataset_ids = await TrainingTaskRepository.get_source_dataset_ids_batch(
        db, task_ids
    )

    # Overlay real-time progress from shared store so list responses stay in sync
    # with SSE/detail endpoints during long-running tasks.
    from backend.common.progress_store import get_all_progress

    file_progress = await get_all_progress()

    # Add WSI count to each task
    result_tasks = []
    for task in tasks:
        if include_username:
            # task is already a dict with username
            task_dict = task
        else:
            # task is a TrainingTask object
            task_dict = task.to_dict()

        task_id = task_dict["task_id"]
        junction_count = wsi_counts.get(task_id, 0)
        if junction_count == 0 and task_dict.get("task_type") == "external_validation":
            task_dict["wsi_count"] = (task_dict.get("model_config") or {}).get(
                "total_wsi", 0
            )
        else:
            task_dict["wsi_count"] = junction_count
        task_dict["source_dataset_id"] = source_dataset_ids.get(task_id)
        if task_id in file_progress:
            task_dict["progress"] = file_progress[task_id]
        result_tasks.append(task_dict)

    return {
        "items": result_tasks,
        "total": total,
        "page": page,
        "page_size": page_size,
        "stats": stats,
    }


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
    include_username = user.is_admin()

    async def event_generator():
        """Generate SSE events with task updates"""
        consecutive_errors = 0
        last_data_hash = None
        BASE_INTERVAL = 5  # seconds between polls

        try:
            while True:
                # Use safe_session to ensure proper connection management even on cancel
                # This protects the close() operation with asyncio.shield()
                async with safe_session() as db:
                    try:
                        # Fetch training tasks filtered by user
                        tasks = await TrainingTaskRepository.get_all(
                            db,
                            limit=100,
                            offset=0,
                            user_id=user_id_filter,
                            include_username=include_username,
                        )

                        # Batch get WSI counts for all tasks (avoids N+1 query)
                        if include_username:
                            task_ids = [task["task_id"] for task in tasks]
                        else:
                            task_ids = [task.task_id for task in tasks]
                        wsi_counts = await TrainingTaskRepository.get_wsi_counts_batch(
                            db, task_ids
                        )

                        # Read real-time progress from shared files (no HTTP, no DB lock)
                        from backend.common.progress_store import get_all_progress

                        file_progress = await get_all_progress()

                        # Add WSI count and overlay file-based progress
                        result_tasks = []
                        for task in tasks:
                            if include_username:
                                # task is already a dict with username
                                task_dict = task
                                task_id = task["task_id"]
                                model_config = task.get("model_config") or {}
                            else:
                                # task is a TrainingTask object
                                task_dict = task.to_dict()
                                task_id = task.task_id
                                model_config = task.model_config or {}
                            # For external validation tasks, WSIs aren't in TrainingTaskWSI junction table
                            # so use model_config.total_wsi as the count
                            junction_count = wsi_counts.get(task_id, 0)
                            if (
                                junction_count == 0
                                and task_dict.get("task_type") == "external_validation"
                            ):
                                task_dict["wsi_count"] = model_config.get(
                                    "total_wsi", 0
                                )
                            else:
                                task_dict["wsi_count"] = junction_count
                            # Overlay file progress if available (more up-to-date than DB)
                            if task_id in file_progress:
                                task_dict["progress"] = file_progress[task_id]
                            result_tasks.append(task_dict)

                        # Change detection: only send if data changed
                        data = json.dumps({"items": result_tasks})
                        import hashlib

                        data_hash = hashlib.md5(data.encode()).hexdigest()
                        if data_hash != last_data_hash:
                            yield f"data: {data}\n\n"
                            last_data_hash = data_hash

                        consecutive_errors = 0  # Reset on success
                    except Exception as e:
                        consecutive_errors += 1
                        logger.error(
                            f"Error fetching training tasks in SSE (consecutive={consecutive_errors}): {e}"
                        )
                        yield f"data: {json.dumps({'error': str(e)})}\n\n"

                # Exponential backoff on consecutive errors: 5s → 10s → 20s → 30s (cap)
                if consecutive_errors > 0:
                    backoff = min(BASE_INTERVAL * (2**consecutive_errors), 30)
                    await asyncio.sleep(backoff)
                else:
                    await asyncio.sleep(BASE_INTERVAL)

        except asyncio.CancelledError:
            # Client disconnected
            logger.info("SSE client disconnected")

    return make_sse_response(event_generator())


@router.get("/{task_id}")
async def get_training_task(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get training task details. Users can only view their own tasks, admin can view all (with username)."""
    # Admin users get username information
    include_username = user.is_admin()

    task = await TrainingTaskRepository.get_by_id(
        db, task_id, include_username=include_username
    )
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    # Check ownership
    task_user_id = task["user_id"] if include_username else task.user_id
    assert_owner(task_user_id, user, "You don't have permission to view this task")

    # Get associated WSI IDs
    wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task_id)

    if include_username:
        # task is already a dict with username
        result = task
    else:
        # task is a TrainingTask object
        result = task.to_dict()

    result["wsi_ids"] = wsi_ids
    # For external validation tasks, WSIs aren't in TrainingTaskWSI junction table
    if len(wsi_ids) == 0 and result.get("task_type") == "external_validation":
        # Get model_config from dict or object depending on include_username
        model_config = task["model_config"] if include_username else task.model_config
        result["wsi_count"] = (model_config or {}).get("total_wsi", 0)
    else:
        result["wsi_count"] = len(wsi_ids)

    # Overlay real-time progress from shared file (if available)
    # This ensures the initial load shows the most up-to-date progress
    from backend.common.progress_store import get_progress

    # Get task_id from dict or object depending on include_username
    task_id_for_progress = task["task_id"] if include_username else task.task_id
    file_prog = await get_progress(task_id_for_progress)
    if file_prog is not None:
        result["progress"] = file_prog

    return result


@router.patch("/{task_id}")
async def update_training_task(
    task_id: str,
    req: TrainingTaskUpdateRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a training task's name.
    Only the task creator or admin can update the task.

    This endpoint allows renaming tasks without affecting running services.
    The change is persisted to the database and immediately visible to all services.
    """
    # Get task from database
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    # Check ownership - only task creator or admin can update
    assert_owner(
        task.user_id, user, "Only the task creator or admin can update this task"
    )

    # Validate task name
    if not req.task_name or not req.task_name.strip():
        raise HTTPException(status_code=400, detail="Task name cannot be empty")

    # Update task name
    updated_task = await TrainingTaskRepository.update_task_name(
        db, task_id, req.task_name.strip()
    )
    await db.commit()

    if not updated_task:
        raise HTTPException(status_code=500, detail="Failed to update task")

    await invalidate_chat_context(str(task.user_id or user.id))
    logger.info(
        f"Training task {task_id} renamed to '{req.task_name}' by user {user.id}"
    )

    return updated_task.to_dict()


@router.delete("/{task_id}")
async def delete_training_task(
    task_id: str,
    mode: str = "standard",
    user: User = Depends(require_pathologist_or_admin),
    db: AsyncSession = Depends(get_db),
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
            raise HTTPException(
                status_code=404, detail=f"Training task not found: {task_id}"
            )

        # Check ownership
        assert_owner(
            task.user_id, user, "You don't have permission to delete this task"
        )

        # If task is still active, cancel it first in both gateway queue and AI service.
        # This makes delete behave as "cancel then delete" for running/queued tasks.
        if task.status in [
            TaskStatus.PENDING,
            TaskStatus.QUEUED,
            TaskStatus.RESUMING,
            TaskStatus.PATCHING,
            TaskStatus.EXTRACTING,
            TaskStatus.TRAINING,
        ]:
            queue = get_task_queue()
            await queue.cancel_task(task_id)
            await cancel_ai_service_training(task_id)

        # Get all trained models for this task
        models = await TrainedModelRepository.get_by_task_id(db, task_id)
        model_ids = [model.model_id for model in models]

        # Delete task-scoped AI result records before removing the task record itself.
        await AIResultRepository.delete_by_task_id(db, task_id)

        task_owner_id = str(task.user_id or user.id)
        await TrainingTaskRepository.delete(db, task_id)
        await db.commit()

        await invalidate_chat_context(task_owner_id)

        storage_cleanup = storage_manager.delete_training_task_files(
            task_id, model_ids, mode
        )
        logger.info(storage_cleanup["summary"])

        # Clean up progress file (ephemeral, may still exist if AI Service didn't finish cleanup)
        from backend.common.progress_store import clear_progress

        await clear_progress(task_id)

        return {
            "message": "Training task deleted successfully",
            "task_id": task_id,
            "storage_cleanup": storage_cleanup,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete training task: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete training task: {str(e)}"
        )


@router.get("/{task_id}/logs")
async def get_training_logs(
    task_id: str,
    level: Optional[str] = Query(
        None, description="Filter by log level (INFO, WARNING, ERROR)"
    ),
    limit: int = Query(100, description="Maximum number of logs to return"),
    offset: int = Query(0, description="Offset for pagination"),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
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

    assert_owner(
        task.user_id, user, "You don't have permission to view this task's logs"
    )

    # Get logs from database
    logs = await TrainingLogRepository.get_by_task_id(db, task_id, level, limit, offset)

    return {
        "task_id": task_id,
        "logs": [log.to_dict() for log in logs],
        "count": len(logs),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{task_id}/logs/stream")
async def stream_training_logs(
    task_id: str, user: User = Depends(get_user_from_token_param)
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
        assert_owner(
            task.user_id, user, "You don't have permission to stream this task's logs"
        )

    async def log_event_generator():
        """Generate SSE events with new logs and task status updates"""
        last_sequence = 0

        try:
            # Send initial batch of recent logs and task status
            async with safe_session() as db:
                try:
                    task = await TrainingTaskRepository.get_by_id(db, task_id)
                    # For completed/failed tasks, load all logs; for running tasks, load recent 50
                    log_count = (
                        10000
                        if task and task.status in ("completed", "failed", "cancelled")
                        else 50
                    )
                    recent_logs = await TrainingLogRepository.get_recent(
                        db, task_id, count=log_count
                    )

                    # Get WSI IDs for task
                    wsi_ids = (
                        await TrainingTaskRepository.get_wsi_ids(db, task_id)
                        if task
                        else []
                    )

                    # Build task dict with wsi_ids and wsi_count
                    task_dict = None
                    if task:
                        task_dict = task.to_dict()
                        task_dict["wsi_ids"] = wsi_ids
                        # For external validation tasks, WSIs aren't in junction table
                        if (
                            len(wsi_ids) == 0
                            and task_dict.get("task_type") == "external_validation"
                        ):
                            task_dict["wsi_count"] = (task.model_config or {}).get(
                                "total_wsi", 0
                            )
                        else:
                            task_dict["wsi_count"] = len(wsi_ids)
                        # Overlay real-time progress from shared file
                        from backend.common.progress_store import get_progress

                        file_prog = await get_progress(task.task_id)
                        if file_prog is not None:
                            task_dict["progress"] = file_prog

                    # Send initial data with both logs and task status
                    data = json.dumps(
                        {
                            "logs": [log.to_dict() for log in recent_logs]
                            if recent_logs
                            else [],
                            "last_sequence": recent_logs[-1].sequence
                            if recent_logs
                            else 0,
                            "task": task_dict,
                        }
                    )
                    yield f"data: {data}\n\n"

                    if recent_logs:
                        last_sequence = recent_logs[-1].sequence
                except Exception as e:
                    logger.error(f"Error fetching initial logs for task {task_id}: {e}")
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"

            # Continuously poll for new logs and task status
            consecutive_errors = 0
            last_data_hash = None
            BASE_INTERVAL = 3  # seconds between polls

            while True:
                task_completed = False
                cached_wsi_ids = []
                cached_task_dict = None

                async with safe_session() as db:
                    try:
                        # Get current task status
                        task = await TrainingTaskRepository.get_by_id(db, task_id)

                        # Get new logs since last sequence
                        new_logs = await TrainingLogRepository.get_logs_after_sequence(
                            db, task_id, last_sequence, limit=100
                        )

                        # Get WSI IDs for task
                        wsi_ids = (
                            await TrainingTaskRepository.get_wsi_ids(db, task_id)
                            if task
                            else []
                        )

                        # Build task dict with wsi_ids and wsi_count
                        task_dict = None
                        if task:
                            task_dict = task.to_dict()
                            task_dict["wsi_ids"] = wsi_ids
                            # For external validation tasks, WSIs aren't in junction table
                            if (
                                len(wsi_ids) == 0
                                and task_dict.get("task_type") == "external_validation"
                            ):
                                task_dict["wsi_count"] = (task.model_config or {}).get(
                                    "total_wsi", 0
                                )
                            else:
                                task_dict["wsi_count"] = len(wsi_ids)
                            # Overlay real-time progress from shared file
                            from backend.common.progress_store import get_progress

                            file_prog = await get_progress(task.task_id)
                            if file_prog is not None:
                                task_dict["progress"] = file_prog

                        # Build data payload
                        data = json.dumps(
                            {
                                "logs": [log.to_dict() for log in new_logs]
                                if new_logs
                                else [],
                                "last_sequence": new_logs[-1].sequence
                                if new_logs
                                else last_sequence,
                                "task": task_dict,
                            }
                        )

                        # Change detection: only send if data changed
                        import hashlib

                        data_hash = hashlib.md5(data.encode()).hexdigest()
                        if data_hash != last_data_hash:
                            yield f"data: {data}\n\n"
                            last_data_hash = data_hash

                        if new_logs:
                            last_sequence = new_logs[-1].sequence

                        # Check if task completed - handle outside session to avoid
                        # holding DB connection during sleep
                        if task and task.status in ["completed", "failed", "cancelled"]:
                            task_completed = True
                            cached_wsi_ids = wsi_ids
                            cached_task_dict = task.to_dict()

                        consecutive_errors = 0  # Reset on success
                    except Exception as e:
                        consecutive_errors += 1
                        logger.error(
                            f"Error polling logs for task {task_id} (consecutive={consecutive_errors}): {e}"
                        )
                        yield f"data: {json.dumps({'error': str(e)})}\n\n"

                # Handle task completion outside session to avoid holding DB
                # connection during sleep (was previously sleeping inside safe_session)
                if task_completed:
                    await asyncio.sleep(2)
                    # Open a new short-lived session for final log fetch
                    async with safe_session() as db:
                        try:
                            final_logs = (
                                await TrainingLogRepository.get_logs_after_sequence(
                                    db, task_id, last_sequence, limit=100
                                )
                            )

                            # Build final task dict with wsi_ids and wsi_count
                            final_task_dict = cached_task_dict.copy()
                            final_task_dict["wsi_ids"] = cached_wsi_ids
                            # For external validation tasks, WSIs aren't in junction table
                            if (
                                len(cached_wsi_ids) == 0
                                and final_task_dict.get("task_type")
                                == "external_validation"
                            ):
                                final_task_dict["wsi_count"] = final_task_dict.get(
                                    "model_config", {}
                                ).get("total_wsi", 0)
                            else:
                                final_task_dict["wsi_count"] = len(cached_wsi_ids)

                            data = json.dumps(
                                {
                                    "logs": [log.to_dict() for log in final_logs]
                                    if final_logs
                                    else [],
                                    "last_sequence": final_logs[-1].sequence
                                    if final_logs
                                    else last_sequence,
                                    "task": final_task_dict,
                                    "status": "complete",
                                }
                            )
                            yield f"data: {data}\n\n"
                        except Exception as e:
                            logger.error(
                                f"Error fetching final logs for task {task_id}: {e}"
                            )
                            yield f"data: {json.dumps({'error': str(e)})}\n\n"
                    return  # Use return instead of break to properly exit generator

                # Exponential backoff on consecutive errors: 3s → 6s → 12s → 24s → 30s (cap)
                if consecutive_errors > 0:
                    backoff = min(BASE_INTERVAL * (2**consecutive_errors), 30)
                    await asyncio.sleep(backoff)
                else:
                    await asyncio.sleep(BASE_INTERVAL)

        except asyncio.CancelledError:
            # Client disconnected
            logger.info(f"SSE log stream disconnected for task {task_id}")
        except Exception as e:
            logger.error(f"Error in log stream for task {task_id}: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return make_sse_response(log_event_generator())


@router.get("/{task_id}/logs/recent")
async def get_recent_training_logs(
    task_id: str,
    count: int = Query(100, description="Number of recent logs to return"),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
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

    assert_owner(
        task.user_id, user, "You don't have permission to view this task's logs"
    )

    # Get recent logs
    logs = await TrainingLogRepository.get_recent(db, task_id, count)

    return {
        "task_id": task_id,
        "logs": [log.to_dict() for log in logs],
        "count": len(logs),
    }


@router.get("/{task_id}/models")
async def get_task_models(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all models from a training task. Users can only view their own tasks' models, admin can view all."""
    # Verify task exists
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    assert_owner(
        task.user_id, user, "You don't have permission to view this task's models"
    )

    models = await TrainedModelRepository.get_by_task_id(db, task_id)
    return {"items": [model.to_dict() for model in models], "total": len(models)}
