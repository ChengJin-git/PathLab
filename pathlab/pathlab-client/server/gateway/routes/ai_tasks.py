"""
AI inference task management routes
Handles WSI classification and other AI inference tasks
"""

import asyncio
import os
import uuid
from typing import cast
import httpx
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.schemas.base import TaskStatus
from backend.database import get_db, async_session, safe_session
from backend.database.repositories import (
    WSIRepository,
    AITaskRepository,
    TrainingTaskRepository,
    TrainedModelRepository,
)
from backend.auth import current_active_user, User
from backend.auth.dependencies import (
    require_dataset_gpu_permission,
    check_wsi_access_permission,
    get_permitted_dataset_ids,
)
from .access_control import assert_owner
from ..dependencies import logger, AI_SERVICE_URL
from ..models import WSIClassifyRequest
from ..utils import require_no_active_batch_imports
from gateway.chat.context_cache import invalidate_chat_context
from gateway.task_dispatch import (
    build_task_descriptor,
    enqueue_task_descriptor,
    is_worker_healthy,
    JsonPayload,
)

router = APIRouter(prefix="/tasks", tags=["AI Inference"])


@router.get("/extractors")
async def list_available_extractors(user: User = Depends(current_active_user)):
    """List all available feature extractors from AI Service. Requires authentication."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{AI_SERVICE_URL}/api/ai/training/extractors")
            response.raise_for_status()
            data = response.json()
            # Normalize response format: wrap array in {items: [...]} if needed
            if isinstance(data, list):
                return {"items": data}
            return data
    except Exception as e:
        logger.error(f"Failed to fetch extractors from AI Service: {e}")
        # Comprehensive fallback if AI Service is down or hasn't reloaded
        return {
            "items": [
                {
                    "id": "resnet50",
                    "name": "ResNet50",
                    "description": "ImageNet pretrained CNN, 2048-dim, general-purpose baseline",
                    "supports_spatial": False,
                },
                {
                    "id": "vit_l_16",
                    "name": "ViT-Large",
                    "description": "ImageNet pretrained ViT-L/16, 1024-dim, general-purpose baseline",
                    "supports_spatial": False,
                },
                {
                    "id": "uni",
                    "name": "UNI",
                    "description": "DINOv2 ViT-L/16, 1024-dim (Mahmood Lab)",
                    "supports_spatial": True,
                },
                {
                    "id": "uni2",
                    "name": "UNI2",
                    "description": "ViT-G/14, 1536-dim (Mahmood Lab)",
                    "supports_spatial": True,
                },
                {
                    "id": "conch",
                    "name": "CONCH",
                    "description": "CLIP ViT-B/16, 512-dim (Mahmood Lab)",
                    "supports_spatial": True,
                },
                {
                    "id": "conch15",
                    "name": "CONCH 1.5",
                    "description": "CLIP ViT-B/16, 512-dim (Mahmood Lab)",
                    "supports_spatial": True,
                },
                {
                    "id": "virchow",
                    "name": "Virchow",
                    "description": "DINOv2 ViT-H/14, 1280-dim (Paige AI)",
                    "supports_spatial": True,
                },
                {
                    "id": "virchow2",
                    "name": "Virchow2",
                    "description": "DINOv2 ViT-H/14, 1280-dim (Paige AI)",
                    "supports_spatial": True,
                },
                {
                    "id": "H-Optimus-1",
                    "name": "H-Optimus-1",
                    "description": "ViT 1.1B, 1536-dim (Bioptimus)",
                    "supports_spatial": True,
                },
                {
                    "id": "plip",
                    "name": "PLIP",
                    "description": "CLIP ViT-B/16, 512-dim (James Zou Lab)",
                    "supports_spatial": True,
                },
                {
                    "id": "phikon2",
                    "name": "Phikon2",
                    "description": "DINOv2 ViT-L/16, 1024-dim (Owkin)",
                    "supports_spatial": True,
                },
                {
                    "id": "mSTAR",
                    "name": "mSTAR",
                    "description": "ViT-L/16, 1024-dim (SmartXlab)",
                    "supports_spatial": True,
                },
                {
                    "id": "GPFM",
                    "name": "GPFM",
                    "description": "DINOv2 ViT-L/14, 1024-dim (SmartXlab)",
                    "supports_spatial": True,
                },
                {
                    "id": "SmartCCS",
                    "name": "Smart-CCS",
                    "description": "DINOv2 ViT-L/14, 1024-dim (SmartXlab)",
                    "supports_spatial": True,
                },
                {
                    "id": "SmartCyto",
                    "name": "SmartCyto",
                    "description": "DINOv3 ViT-B/16, 768-dim (SmartXlab)",
                    "supports_spatial": True,
                },
            ]
        }


@router.post("/wsi_classification")
async def create_wsi_classification(
    req: WSIClassifyRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a WSI classification task.
    Requires pathologist/admin role OR temporary elevated permission for the dataset.

    The task is submitted to the GPU task queue for execution.
    When it's the task's turn, Gateway calls AI Service's sync endpoint.

    If classes are not provided, they will be auto-detected from labels in the
    current WSI's accessible dataset scope.
    """
    # Validate WSI exists in database
    wsi = await WSIRepository.get_by_id_with_dataset(db, req.wsi_id)
    if not wsi:
        raise HTTPException(status_code=404, detail="wsi_id not found")

    # Check access permission (ownership or elevated dataset grant)
    has_access = await check_wsi_access_permission(
        user, wsi.dataset_id, wsi.user_id, db
    )
    if not has_access:
        raise HTTPException(
            status_code=403, detail="You don't have permission to analyze this WSI"
        )

    # Check if file is accessible (with timeout for external storage)
    if wsi.wsi_path:
        FILE_CHECK_TIMEOUT = 10  # seconds
        try:
            exists = await asyncio.wait_for(
                asyncio.to_thread(os.path.exists, wsi.wsi_path),
                timeout=FILE_CHECK_TIMEOUT,
            )
            if not exists:
                raise HTTPException(
                    status_code=400,
                    detail=f"File is not accessible: {wsi.original_filename or req.wsi_id}",
                )
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=408,
                detail=f"External storage not responding (timed out after {FILE_CHECK_TIMEOUT}s). "
                f"Cannot verify accessibility of {wsi.original_filename or req.wsi_id}. "
                f"Please check your network storage connection and try again.",
            )

    await require_no_active_batch_imports(
        db,
        detail="Cannot submit inference task while files are being imported. Please wait for all imports to complete.",
    )

    # Check GPU permission: either user has GPU access OR has temporary elevated permission for this dataset
    await require_dataset_gpu_permission(user, wsi.dataset_id, db)

    # Auto-detect classes if not provided
    classes = req.classes
    if not classes:
        elevated_dataset_ids = await get_permitted_dataset_ids(user, db)
        dataset_scope = wsi.dataset_id or "Uncategorized"
        visible_wsi = await WSIRepository.get_by_dataset(
            db,
            dataset_scope,
            user_id=None if user.is_admin() else str(user.id),
            elevated_dataset_ids=elevated_dataset_ids,
        )
        unique_labels = {
            candidate.label for candidate in visible_wsi if candidate.label
        }

        if not unique_labels:
            raise HTTPException(
                status_code=400,
                detail="No classes provided and no labeled WSI found in the accessible dataset scope. Please provide classes parameter.",
            )

        classes = sorted(list(unique_labels))
        logger.info(
            "Auto-detected classes for WSI %s from dataset scope %s: %s",
            req.wsi_id,
            dataset_scope,
            classes,
        )

    # Validate model exists
    model_id = req.model_id
    if model_id:
        model = await TrainedModelRepository.get_by_id(db, model_id)
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
    else:
        # Find default active model
        models = await TrainedModelRepository.get_all(db)
        active_model = next((m for m in models if m.is_active), None)
        if not active_model:
            raise HTTPException(
                status_code=400,
                detail="No trained model available. Please train a model first.",
            )
        model_id = active_model.model_id

    if not await is_worker_healthy():
        raise HTTPException(status_code=503, detail="Task worker unavailable")

    # Create task ID and store in database
    task_id = f"inf_{uuid.uuid4().hex[:16]}"

    task_data = {
        "task_id": task_id,
        "wsi_id": req.wsi_id,
        "task_type": "wsi_classification",
        "status": TaskStatus.PENDING,
        "progress": 0,
        "params": {"classes": classes, "model_id": model_id, **(req.params or {})},
        "user_id": str(user.id),  # Associate with current user
    }
    await AITaskRepository.create(db, task_data)
    await db.commit()

    descriptor_payload = cast(
        JsonPayload,
        {
            "task_id": task_id,
            "wsi_id": req.wsi_id,
            "model_id": model_id,
        },
    )
    descriptor = build_task_descriptor(
        job_id=task_id,
        job_kind="inference",
        handler="inference.single",
        payload=descriptor_payload,
    )
    try:
        await enqueue_task_descriptor(descriptor)
    except Exception as e:
        detail = f"Failed to enqueue task descriptor: {e}"
        logger.error(f"Failed to enqueue inference task {task_id}: {e}")
        async with safe_session() as db_cleanup:
            await AITaskRepository.update_status(
                db_cleanup,
                task_id,
                TaskStatus.FAILED,
                error_message=detail,
            )
            await db_cleanup.commit()
        raise HTTPException(status_code=503, detail="Task worker unavailable")

    await invalidate_chat_context(str(user.id))
    logger.info(f"Inference task {task_id} descriptor enqueued")

    return {
        "task_id": task_id,
        "status": TaskStatus.PENDING,
        "message": "Inference task queued successfully",
    }


async def run_inference_via_ai_service(
    task_id: str,
    wsi_id: str,
    model_id: str,
):
    """
    Execute inference by calling AI Service's synchronous endpoint.

    This function is called by the task queue when it's the task's turn to run.
    """
    try:
        async with httpx.AsyncClient(
            timeout=600.0
        ) as client:  # 10 min timeout for inference
            response = await client.post(
                f"{AI_SERVICE_URL}/api/ai/analyze/sync",
                json={
                    "task_id": task_id,
                    "wsi_id": wsi_id,
                    "model_id": model_id,
                },
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Inference task {task_id} completed: {result.get('pred')}")
            return result
    except httpx.HTTPStatusError as e:
        logger.error(f"AI Service returned error for task {task_id}: {e.response.text}")
        # Update task status to failed - use safe_session for proper cleanup on cancel
        async with safe_session() as db:
            await AITaskRepository.update_status(
                db,
                task_id,
                TaskStatus.FAILED,
                error_message=f"AI Service error: {e.response.text}",
            )
            await db.commit()
        raise
    except httpx.RequestError as e:
        logger.error(f"AI Service unavailable for task {task_id}: {e}")
        async with safe_session() as db:
            await AITaskRepository.update_status(
                db,
                task_id,
                TaskStatus.FAILED,
                error_message=f"AI Service unavailable: {str(e)}",
            )
            await db.commit()
        raise
    except Exception as e:
        logger.error(f"Inference task {task_id} failed: {e}")
        async with safe_session() as db:
            await AITaskRepository.update_status(
                db, task_id, TaskStatus.FAILED, error_message=str(e)
            )
            await db.commit()
        raise


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get task status from database.
    Checks both AI inference tasks and training tasks.
    Users can only view their own tasks, admin can view all.
    """
    # Try AI task first
    task = await AITaskRepository.get_by_id(db, task_id)
    if task:
        assert_owner(task.user_id, user, "You don't have permission to view this task")
        return task.to_dict()

    # Try training task
    training_task = await TrainingTaskRepository.get_by_id(db, task_id)
    if training_task:
        assert_owner(
            training_task.user_id, user, "You don't have permission to view this task"
        )
        return training_task.to_dict()

    return {"task_id": task_id, "status": "not_found"}
