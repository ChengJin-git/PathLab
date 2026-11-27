"""
WSI Inference Routes - Handles model inference requests

Unified entry/exit design:
- All inference requests use a unified schema
- All responses return a unified format
- Routed by task_type
"""

from __future__ import annotations

import asyncio
import uuid
import logging
import traceback
from typing import Dict, Any

import torch
import torch.nn.functional as F
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai.schemas.base import TaskStatus
from backend.database.database import get_db
from backend.database.repositories import (
    WSIRepository,
    AITaskRepository,
    TrainedModelRepository,
    AIResultRepository,
)
from backend.ai.extractors import get_extractor
from backend.ai.result_store import AIResultStore, ATTENTION_ARTIFACT
from backend.ai.tasks.wsi_classification.trainer import WSIClassificationTrainer
from backend.ai.tasks.feature_cache import (
    find_cached_features,
    get_cache_save_path,
    read_params_from_coords_h5,
    safe_load_features,
    save_features,
)
from backend.ai.tasks.patch_cache import find_any_cached_coords_for_wsi
from backend.ai.schemas import (
    InferenceResponse,
    TaskType,
)
from backend.ai.schemas.requests import (
    InferenceRequest,
    SyncInferenceRequest,
    WSIClassificationInferRequest,
)
from backend.common.config import Config
from backend.common.gpu_utils import get_device_string
logger = logging.getLogger("inference_routes")


def _uploads_dir():
    return Config.get_uploads_dir()


router = APIRouter(tags=["inference"])


@router.post("/analyze")
async def analyze_wsi(
    req: InferenceRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Start asynchronous WSI inference task (legacy endpoint).

    Note: For queue-managed execution, use /analyze/sync instead.
    """
    # 1. Validate WSI
    wsi = await WSIRepository.get_by_id(db, req.wsi_id)
    if not wsi:
        raise HTTPException(status_code=404, detail="WSI not found")

    # 2. Get Model (or default)
    if req.model_id:
        model = await TrainedModelRepository.get_by_id(db, req.model_id)
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
    else:
        # TODO: Implement default model lookup logic properly
        # For now, we'll try to find any active ResNet+ABMIL model
        models = await TrainedModelRepository.get_all(db)
        model = next((m for m in models if m.is_active), None)
        if not model:
            # If no trained model, we cannot proceed for now.
            # In a real app, this might fall back to a pretrained system model.
            raise HTTPException(
                status_code=400,
                detail="No trained model available. Please train a model first.",
            )

    # 3. Create Task ID & Record
    task_id = f"inf_{uuid.uuid4().hex[:16]}"

    # 4. Start Background Task
    background_tasks.add_task(
        run_inference_pipeline,
        task_id=task_id,
        wsi_id=req.wsi_id,
        model_id=model.model_id,
        device=get_device_string(),
    )

    return {
        "task_id": task_id,
        "status": TaskStatus.PENDING,
        "message": "Inference started successfully",
    }


@router.post("/analyze/sync")
async def analyze_wsi_sync(
    req: SyncInferenceRequest, db: AsyncSession = Depends(get_db)
):
    """
    Execute WSI inference synchronously (blocking).

    This endpoint is designed to be called by Gateway's task queue.
    The task_id should be pre-created by Gateway.

    Returns the inference result directly instead of starting a background task.
    """
    try:
        # Run the inference pipeline synchronously
        result = await run_inference_pipeline_sync(
            db=db,
            task_id=req.task_id,
            wsi_id=req.wsi_id,
            model_id=req.model_id,
            device=req.device,
        )
        return result
    except Exception as e:
        logger.error(f"Sync inference failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def run_inference_pipeline(task_id: str, wsi_id: str, model_id: str, device: str):
    """Background execution shares the queue-managed prediction implementation."""
    async for db in get_db():
        try:
            await run_inference_pipeline_sync(db, task_id, wsi_id, model_id, device)
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Inference failed: {e}\n{tb}")
            await AITaskRepository.update_status(
                db, task_id, TaskStatus.FAILED, progress=0, error_message=str(e)
            )
            await db.commit()


async def run_inference_pipeline_sync(
    db: AsyncSession, task_id: str, wsi_id: str, model_id: str, device: str
) -> Dict[str, Any]:
    """
    Synchronous inference pipeline for queue-managed execution.

    Unlike run_inference_pipeline, this:
    1. Uses the provided db session (doesn't create a new one)
    2. Returns the result directly
    3. Raises exceptions instead of catching them (let caller handle)

    Returns:
        Dict with inference results
    """

    # Update task status to running
    await AITaskRepository.update_status(db, task_id, TaskStatus.PATCHING, progress=0)
    await db.commit()

    # --- Step 1: Load Model (need to know extractor first) ---
    await AITaskRepository.update_status(db, task_id, TaskStatus.PATCHING, progress=10)
    await db.commit()

    model_record = await TrainedModelRepository.get_by_id(db, model_id)
    if not model_record:
        raise ValueError(f"Model not found: {model_id}")

    extractor_name = model_record.feature_extractor or "resnet50"
    from pathlib import Path
    from backend.services.research_prediction import read_manifest
    prediction_manifest = read_manifest(Path(model_record.model_path).parent) or {}
    if prediction_manifest and prediction_manifest['task_type'] != 'wsi_classification':
        raise ValueError('Select a WSI classification model for single-slide classification')

    # --- Step 2: Feature Extraction (with global cache) ---
    # Check coordinates first (search across all params_hash directories)
    uploads_dir = _uploads_dir()
    coords_h5 = find_any_cached_coords_for_wsi(uploads_dir, wsi_id)
    if coords_h5 is None and not prediction_manifest.get('feature_cache_hash'):
        raise FileNotFoundError(
            f"Coordinates not found for {wsi_id}. Please run preprocessing first."
        )

    params_hash = prediction_manifest.get('feature_cache_hash') or read_params_from_coords_h5(coords_h5)
    if not params_hash:
        logger.warning(f"Could not read params from {coords_h5}, using default hash")
        params_hash = "default0"

    cached_path = find_cached_features(uploads_dir, extractor_name, params_hash, wsi_id)

    features = None
    if cached_path:
        # Cache hit - try to load
        feats, load_error = await asyncio.to_thread(
            safe_load_features, cached_path, delete_if_corrupted=True
        )
        if feats is not None:
            logger.info(f"Cache hit for {wsi_id} with extractor {extractor_name}")
            features = feats if prediction_manifest else feats.to(device)
            await AITaskRepository.update_status(
                db, task_id, TaskStatus.PATCHING, progress=30
            )
            await db.commit()
        else:
            # Cached file was corrupted, will re-extract
            logger.warning(
                f"Corrupted cached features for {wsi_id}, will re-extract: {load_error}"
            )
            cached_path = None  # Treat as cache miss

    if not cached_path:
        if coords_h5 is None:
            raise FileNotFoundError('No saved features or patch coordinates for this slide')
        if prediction_manifest.get('feature_cache_hash') and read_params_from_coords_h5(coords_h5) != params_hash:
            raise ValueError('Slide coordinates do not match the model preprocessing; prepare the required features first')
        await AITaskRepository.update_status(
            db, task_id, TaskStatus.PATCHING, progress=20
        )
        await db.commit()
        logger.info(
            f"Cache miss for {wsi_id}, extracting features with {extractor_name}"
        )

        wsi = await WSIRepository.get_by_id(db, wsi_id)
        trainer = WSIClassificationTrainer(task_id, uploads_dir, device)
        extractor = await asyncio.to_thread(
            lambda: get_extractor(extractor_name, pretrained=True).to(device).eval()
        )

        feats = await asyncio.to_thread(
            trainer._extract_wsi_features,
            extractor=extractor,
            wsi_path=wsi.wsi_path,
            coords_h5=str(coords_h5),
            batch_size=64,
        )

        cache_feat_path = get_cache_save_path(
            uploads_dir, extractor_name, params_hash, wsi_id
        )
        feats_cpu = feats.cpu()
        await asyncio.to_thread(save_features, cache_feat_path, feats_cpu, getattr(extractor,'feature_contract',None))
        logger.info(f"Saved features to cache: {cache_feat_path}")
        from backend.services.feature_inventory import register_manifest
        if cache_feat_path.with_suffix('.feature.json').is_file():
            slide=await WSIRepository.get_by_id(db,wsi_id)
            if slide:await register_manifest(db,slide,cache_feat_path)

        features = feats if prediction_manifest else feats.to(device)
        await AITaskRepository.update_status(
            db, task_id, TaskStatus.PATCHING, progress=30
        )
        await db.commit()

    # --- Step 3: Load Model Checkpoint ---
    await AITaskRepository.update_status(db, task_id, TaskStatus.PATCHING, progress=50)
    await db.commit()


    # --- Step 4: Inference ---
    await AITaskRepository.update_status(db, task_id, TaskStatus.PATCHING, progress=80)
    await db.commit()

    with torch.inference_mode():
        from backend.services.research_prediction import predict_bag
        logits, attention = await asyncio.to_thread(predict_bag, model_record.model_path,
            model_record.aggregator, model_record.classes, features, device)
        probs = F.softmax(logits, dim=1).squeeze().cpu().numpy()

    trained_classes = model_record.classes
    probs_dict = {
        cls: float(prob) for cls, prob in zip(trained_classes, probs.flatten())
    }

    pred_idx = probs.argmax()
    pred_label = trained_classes[pred_idx]

    # --- Step 5: Save Bundle Artifacts ---
    arrays = {}
    if attention is not None:
        attention_np = attention.cpu().numpy()
        arrays[ATTENTION_ARTIFACT] = attention_np
        logger.info(
            f"Prepared attention weights ({len(attention_np)} patches) for bundled storage"
        )

    # --- Step 6: Save Results ---
    result_data = {
        "wsi_id": wsi_id,
        "task_id": task_id,
        "pred": pred_label,
        "probs": probs_dict,
        "extra_metadata": {
            "model_id": model_id,
            "model_name": model_record.model_name,
            "attention_path": None,
        },
    }

    AIResultStore(uploads_dir).write_wsi_result(
        task_id=task_id,
        wsi_id=wsi_id,
        result=result_data,
        arrays=arrays,
    )

    await AIResultRepository.create(db, result_data)
    await AITaskRepository.update_status(
        db, task_id, TaskStatus.COMPLETED, progress=100
    )
    await db.commit()

    return {
        "task_id": task_id,
        "status": TaskStatus.COMPLETED,
        "wsi_id": wsi_id,
        "pred": pred_label,
        "probs": probs_dict,
    }


@router.post("/wsi_classification")
async def infer_wsi_classification(
    req: WSIClassificationInferRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> InferenceResponse:
    """
    WSI classification inference unified entry.

    Returns unified InferenceResponse format.
    """
    # Validate WSI
    wsi = await WSIRepository.get_by_id(db, req.wsi_id)
    if not wsi:
        raise HTTPException(status_code=404, detail="WSI not found")

    # Get Model (or default)
    if req.model_id:
        model = await TrainedModelRepository.get_by_id(db, req.model_id)
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
    else:
        models = await TrainedModelRepository.get_all(db)
        model = next((m for m in models if m.is_active), None)
        if not model:
            raise HTTPException(status_code=400, detail="No trained model available")

    # Create Task ID
    task_id = f"inf_{uuid.uuid4().hex[:16]}"

    # Start Background Task
    background_tasks.add_task(
        run_inference_pipeline,
        task_id=task_id,
        wsi_id=req.wsi_id,
        model_id=model.model_id,
        device=get_device_string(),
    )

    return InferenceResponse.pending(
        task_type=TaskType.WSI_CLASSIFICATION,
        task_id=task_id,
        wsi_id=req.wsi_id,
        message="Inference started successfully",
    )


# =============================================================================
# Patch Classification Inference - TODO
# =============================================================================

# @router.post("/patch_classification")
# async def infer_patch_classification(...) -> InferenceResponse:
#     pass


# =============================================================================
# Patch Segmentation Inference - TODO
# =============================================================================

# @router.post("/patch_segmentation")
# async def infer_patch_segmentation(...) -> InferenceResponse:
#     pass
