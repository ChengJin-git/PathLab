"""
Refactored training routes using task-specific trainers and registries.

Unified entry/exit design:
- All training requests use a unified Schema
- All responses return a unified format
- Routed by task_type

Synchronous HTTP Architecture:
- Gateway sends HTTP request and waits for training to complete
- Training endpoints run synchronously and return result when done
- Timeout is set to 3 days in Gateway to allow long-running training

Cancellation Mechanism:
- Gateway can call DELETE /training/{task_id} to request cancellation
- Trainers check is_task_cancelled() in their training loops
- When cancelled, trainers raise TrainingCancelledException and cleanup GPU
"""

from __future__ import annotations

import gc
import json
import logging
import traceback
from pathlib import Path
from typing import List, Dict, Any

import torch
from fastapi import APIRouter, HTTPException

from backend.database.repositories import (
    TrainingTaskRepository,
    TrainedModelRepository,
)
from backend.database.utils.json_utils import sanitize_for_json
from backend.ai.utils.scoped_session import ScopedSession, ScopedTrainingLogger
from backend.ai.tasks import WSIClassificationTrainer, WSISurvivalTrainer
from backend.ai.extractors.registry import get_available_extractors
from backend.ai.schemas import (
    TrainResponse,
    TrainMetrics,
    TaskType,
)
from backend.ai.schemas.requests import (
    FeatureExtractionRequest,
    WSIClassificationTrainRequest,
    WSISurvivalTrainRequest,
    PatchClassificationTrainRequest,
    PatchSegmentationTrainRequest,
    PatchDetectionTrainRequest,
)
from backend.ai.schemas.base import TaskStatus
from backend.common.config import Config
from backend.ai.utils.vram_guard import (
    check_vram_before_model_load,
)

logger = logging.getLogger("training_routes")

_UNSUPPORTED_PATCH_SEGMENTATION_LOSS_TOKENS = frozenset(
    {
        "ce",
        "softcrossentropyloss",
        "crossentropy",
        "crossentropyloss",
    }
)


def _normalize_patch_segmentation_loss_name(loss_name: str) -> str:
    return "".join(ch for ch in str(loss_name).lower() if ch.isalnum())


def _validate_patch_segmentation_loss_names(loss_names: List[str]) -> None:
    unsupported_losses = [
        loss_name
        for loss_name in loss_names
        if _normalize_patch_segmentation_loss_name(loss_name)
        in _UNSUPPORTED_PATCH_SEGMENTATION_LOSS_TOKENS
    ]
    if unsupported_losses:
        unsupported_display = ", ".join(sorted(set(unsupported_losses)))
        raise HTTPException(
            status_code=400,
            detail=(
                "Patch segmentation does not support Cross Entropy losses "
                f"({unsupported_display}). This training path uses multi-channel float masks; "
                "please use Dice/Jaccard/Tversky/Focal/Lovasz/BCE/MCC losses instead."
            ),
        )


def _uploads_dir() -> Path:
    return Config.get_uploads_dir()


# =============================================================================
# Cancellation Mechanism (imported from separate module to avoid circular imports)
# =============================================================================
from backend.ai.cancellation import (
    request_cancellation,
    is_restart_requested,
    clear_cancellation,
    TrainingCancelledException,
)
from backend.common.progress_store import clear_progress
from backend.ai.utils.feature_dataset import clear_feature_cache

# =============================================================================
# Permission Revocation Mechanism
# =============================================================================
from backend.ai.permission_revocation import (
    revoke_task_permission,
    clear_revocation,
)

router = APIRouter(prefix="/training", tags=["training"])


@router.delete("/{task_id}")
async def cancel_training_task(task_id: str, for_restart: bool = False):
    """
    Request cancellation of a running training task.

    The training will stop at the next checkpoint (typically after current epoch).
    GPU memory will be released after cancellation.

    Returns:
        {"cancelled": True, "message": str}
    """
    request_cancellation(task_id, for_restart=for_restart)
    return {
        "cancelled": True,
        "message": f"Cancellation requested for task {task_id}. Training will stop at next checkpoint.",
    }


@router.post("/{task_id}/revoke-permission")
async def revoke_training_permission(task_id: str):
    """
    Mark a training task as having its permission revoked.

    Called by Gateway when admin revokes a user's temporary elevated permission
    for a dataset, and there are running tasks that depend on that permission.

    The training will stop at the next iteration checkpoint with a
    PermissionRevokedException error.

    Returns:
        {"revoked": True, "message": str}
    """
    revoke_task_permission(task_id)
    return {
        "revoked": True,
        "message": f"Permission revoked for task {task_id}. Training will stop at next iteration.",
    }


async def _safe_update_status(
    db, task_id: str, new_status: str, progress: int = None, error_message: str = None
) -> bool:
    """
    Safely update task status, but only if the task has not been cancelled.

    This prevents a completed/failed status from overwriting a 'cancelled' status
    that was set by the user through the cancel API.

    Returns:
        True if status was updated, False if task was cancelled (status not updated)
    """
    # Check current status first
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if task is None:
        return False

    # If task is cancelled, do not overwrite the status
    if task.status == TaskStatus.CANCELLED:
        return False

    if new_status == TaskStatus.CANCELLED and is_restart_requested(task_id):
        new_status = TaskStatus.RESUMING
        error_message = None

    # Update status
    await TrainingTaskRepository.update_status(
        db, task_id, new_status, progress=progress, error_message=error_message
    )
    return True


def _get_split_strategy_description(
    splits_map: dict[str, Any], preprocessing_config: dict[str, Any] = None
) -> str:
    """
    Generate a human-readable description of the split strategy.

    Returns a string like:
    - "Random 7:1:2"
    - "5-Fold Cross-Validation"
    - "Manual Split"
    """
    # Check if this is k-fold (keys like 'fold_0', 'fold_1', etc.)
    fold_keys = [k for k in splits_map.keys() if k.startswith("fold_")]
    if fold_keys:
        num_folds = len(fold_keys)
        return f"{num_folds}-Fold Cross-Validation"

    # Check split_config from preprocessing_config
    if preprocessing_config:
        split_config = preprocessing_config.get("split_config", {})
        strategy = split_config.get("strategy", "random")

        if strategy == "manual":
            return "Manual Split"
        elif strategy == "k_fold":
            n_splits = split_config.get("n_splits", 5)
            return f"{n_splits}-Fold Cross-Validation"
        else:
            ratios = split_config.get("ratios", {"train": 0.7, "val": 0.1, "test": 0.2})
            train_pct = int(ratios.get("train", 0.7) * 10)
            val_pct = int(ratios.get("val", 0.1) * 10)
            test_pct = int(ratios.get("test", 0.2) * 10)
            return f"Random {train_pct}:{val_pct}:{test_pct}"

    # Default: analyze from splits_map
    train_count = len(splits_map.get("train", []))
    val_count = len(splits_map.get("val", []))
    test_count = len(splits_map.get("test", []))

    if train_count > 0 and val_count > 0 and test_count > 0:
        return "Random 7:1:2"
    elif train_count > 0 and test_count > 0:
        return "Train/Test Split"
    else:
        return "Unknown Split Strategy"


def _format_splits_count(splits_map: dict[str, Any]) -> str:
    """
    Format splits count for logging.

    Returns a string like:
    - "Train: 70, Val: 10, Test: 20"
    - "3 Folds | Each fold: Train: 1798, Val: 899"
    """
    # Check if this is k-fold
    fold_keys = sorted([k for k in splits_map.keys() if k.startswith("fold_")])
    if fold_keys:
        num_folds = len(fold_keys)
        # Calculate samples per fold (assume roughly equal distribution)
        total_samples = sum(len(splits_map[k]) for k in fold_keys)
        samples_per_fold = total_samples // num_folds
        # In k-fold CV: 1 fold is val, rest are train
        val_count = samples_per_fold
        train_count = total_samples - samples_per_fold
        return f"{num_folds} Folds | Each fold: Train: {train_count}, Val: {val_count}"

    # Standard train/val/test split
    parts = []
    for split_name in ["train", "val", "test"]:
        if split_name in splits_map:
            display_name = split_name.capitalize()
            parts.append(f"{display_name}: {len(splits_map[split_name])}")

    return ", ".join(parts) if parts else "No splits"


def cleanup_gpu_memory():
    """
    Clean up GPU memory after training/inference.

    Based on PyTorch best practices:
    1. Run garbage collection to release Python references
    2. Call torch.cuda.empty_cache() to release cached memory back to device
    3. Synchronize to ensure all operations are complete

    Note: For complete cleanup, all references to models/tensors should be
    deleted (del model, del optimizer, etc.) before calling this function.
    This is typically handled by Python's garbage collector when variables
    go out of scope after an exception or function return.
    """
    if torch.cuda.is_available():
        # Get memory before cleanup for logging
        try:
            device_idx = torch.cuda.current_device()
            mem_before = torch.cuda.memory_allocated(device_idx) / (1024**2)
        except Exception:
            mem_before = 0

        # Run GC multiple times to ensure all cyclic references are collected
        # This is important for complex object graphs like PyTorch models
        gc.collect()
        gc.collect()  # Second pass for cyclic references

        # Release cached memory back to the device
        torch.cuda.empty_cache()

        # Synchronize to ensure all CUDA operations are complete
        torch.cuda.synchronize()

        # Log memory status
        try:
            mem_after = torch.cuda.memory_allocated(device_idx) / (1024**2)
            logger.info(
                f"GPU memory cleaned up: {mem_before:.1f} MB -> {mem_after:.1f} MB"
            )
        except Exception:
            logger.info("GPU memory cleaned up")
    else:
        gc.collect()
        from backend.common.accelerator import mps_available
        if mps_available():
            torch.mps.synchronize()
            torch.mps.empty_cache()
            logger.info('MPS memory cache released')
        else:
            logger.info("GPU not available, only ran gc.collect()")


async def handle_training_error_scoped(
    e: Exception,
    task_id: str,
    scoped_session: ScopedSession,
    operation_name: str = "Training",
) -> None:
    """
    Handle training errors with consistent logging and status updates.
    Uses ScopedSession for short-lived database connections.

    This helper handles the common error cases (FileNotFoundError, ValueError, generic Exception)
    and should be called from except blocks. It logs the error, updates the task status,
    and raises the appropriate HTTPException.

    TrainingCancelledException and PermissionRevokedException should be handled separately
    by the caller since they require returning a TrainResponse.cancelled()/failed() instead
    of raising an exception.

    Args:
        e: The caught exception
        task_id: Training task ID
        scoped_session: ScopedSession instance for creating short-lived DB sessions
        operation_name: Name of the operation for logging (e.g., "WSI Classification")

    Raises:
        HTTPException: Always raises with appropriate status code (404, 400, or 500)
    """
    tb = traceback.format_exc()

    if isinstance(e, FileNotFoundError):
        logger.error(f"{operation_name} failed - File not found: {e}\n{tb}")
        async with scoped_session.session() as (training_logger, db):
            await training_logger.error(
                f"{operation_name} failed - File not found",
                {"error": str(e), "traceback": tb},
            )
            await _safe_update_status(
                db, task_id, TaskStatus.FAILED, progress=0, error_message=str(e)
            )
        raise HTTPException(status_code=404, detail=f"File not found: {e}")

    elif isinstance(e, ValueError):
        logger.error(f"{operation_name} failed - Invalid data: {e}\n{tb}")
        async with scoped_session.session() as (training_logger, db):
            await training_logger.error(
                f"{operation_name} failed - Invalid data",
                {"error": str(e), "traceback": tb},
            )
            await _safe_update_status(
                db, task_id, TaskStatus.FAILED, progress=0, error_message=str(e)
            )
        raise HTTPException(status_code=400, detail=f"Invalid data: {e}")

    elif isinstance(e, HTTPException):
        # Re-raise HTTP exceptions as-is
        raise e

    elif isinstance(e, torch.cuda.OutOfMemoryError):
        # Handle CUDA OOM with full traceback in the error message
        error_detail = f"CUDA out of memory. {str(e)}"
        full_error = f"{error_detail}\n\nTraceback:\n{tb}"
        logger.error(f"{operation_name} failed - CUDA OOM: {e}\n{tb}")
        async with scoped_session.session() as (training_logger, db):
            await training_logger.error(
                f"{operation_name} failed - CUDA out of memory",
                {"error": error_detail, "traceback": tb},
            )
            await _safe_update_status(
                db, task_id, TaskStatus.FAILED, progress=0, error_message=full_error
            )
        raise HTTPException(status_code=500, detail=full_error)

    else:
        logger.error(f"{operation_name} failed: {e}\n{tb}")
        async with scoped_session.session() as (training_logger, db):
            await training_logger.error(
                f"{operation_name} failed", {"error": str(e), "traceback": tb}
            )
            await _safe_update_status(
                db, task_id, TaskStatus.FAILED, progress=0, error_message=str(e)
            )
        raise HTTPException(status_code=500, detail=str(e))


async def cleanup_training_scoped(task_id: str) -> None:
    """
    Cleanup resources after training operation (success, failure, or cancellation/revocation).
    Version for ScopedSession pattern - no logger to close since sessions are short-lived.

    Should be called in the finally block of training operations.

    Args:
        task_id: Training task ID for cancellation/revocation cleanup
    """
    cleanup_gpu_memory()
    clear_feature_cache()
    clear_cancellation(task_id)
    clear_revocation(task_id)
    await clear_progress(task_id)


@router.get("/extractors")
async def list_ai_extractors():
    """List all available feature extractors."""
    return get_available_extractors()


# =============================================================================
# Feature Extraction (Unified Entry)
# =============================================================================


@router.post("/extract_features")
async def extract_features(req: FeatureExtractionRequest):
    """Extract features using WSI Classification Trainer.

    Uses ScopedSession pattern - creates short-lived DB sessions for each operation
    to prevent connection pool exhaustion during long-running feature extraction.
    """
    scoped_session = ScopedSession(req.task_id)
    scoped_logger = ScopedTrainingLogger(req.task_id)

    try:
        # Validate training task exists - short-lived session
        async with scoped_session.session() as (training_logger, db):
            task = await TrainingTaskRepository.get_by_id(db, req.task_id)
            if not task:
                raise HTTPException(
                    status_code=404, detail=f"Training task not found: {req.task_id}"
                )
            preprocessing_config = task.preprocessing_config or {}
            await training_logger.info(
                f"[Step 2/3] Starting feature extraction for {len(req.wsi_ids)} WSI",
                {
                    "feature_extractor": req.feature_extractor,
                    "batch_size": req.batch_size,
                },
            )
            await TrainingTaskRepository.update_status(
                db, req.task_id, TaskStatus.EXTRACTING, progress=33
            )
        # Session closed here - connection released

        # Use WSI Classification Trainer with session_maker
        trainer = WSIClassificationTrainer(
            task_id=req.task_id,
            uploads_root=_uploads_dir(),
            device=req.device,
        )

        results = await trainer.extract_features(
            wsi_ids=req.wsi_ids,
            extractor_name=req.feature_extractor,
            batch_size=req.batch_size,
            force_recompute=req.force_recompute,
            logger=scoped_logger,
            session_maker=scoped_session.get_session_maker(),
            hf_token=req.huggingface_token,
            preprocessing_config=preprocessing_config,
        )

        await scoped_logger.info(
            f"Feature extraction completed for all {len(req.wsi_ids)} WSI"
        )

        # Prepare response data before any cleanup
        response_data = results.model_dump()
        cleanup_gpu_memory()
        return response_data

    except TrainingCancelledException as e:
        await scoped_logger.info(f"Feature extraction cancelled: {e}")
        async with scoped_session.session() as (training_logger, db):
            await _safe_update_status(
                db, req.task_id, TaskStatus.CANCELLED, error_message=str(e)
            )
        cleanup_gpu_memory()
        return {"status": TaskStatus.CANCELLED, "results": [], "error_message": str(e)}

    except Exception as e:
        await handle_training_error_scoped(
            e, req.task_id, scoped_session, "Feature extraction"
        )
        cleanup_gpu_memory()
        raise
    finally:
        clear_cancellation(req.task_id)
        await scoped_logger.close()


# =============================================================================
# WSI Classification Training (Unified Entry)
# =============================================================================


@router.post("/wsi_classification")
async def train_wsi_classification(req: WSIClassificationTrainRequest) -> TrainResponse:
    """
    WSI Classification Training Unified Entry.

    Uses ScopedSession pattern - creates short-lived DB sessions for each operation
    to prevent connection pool exhaustion during long-running training.
    """
    scoped_session = ScopedSession(req.task_id)
    scoped_logger = ScopedTrainingLogger(req.task_id)

    # Phase 1: Validation - short-lived session
    async with scoped_session.session() as (training_logger, db):
        task = await TrainingTaskRepository.get_by_id(db, req.task_id)
        if not task:
            raise HTTPException(
                status_code=404, detail=f"Training task not found: {req.task_id}"
            )

        classes: List[str] = task.classes or []
        if not classes:
            raise HTTPException(status_code=400, detail="Training task has no classes")

        splits_map = await TrainingTaskRepository.get_wsi_ids_by_split(db, req.task_id)
        if not splits_map:
            raise HTTPException(
                status_code=400, detail="No WSI data associated with this task"
            )

        # K-Fold validation
        fold_keys = [k for k in splits_map.keys() if k.startswith("fold_")]
        if fold_keys:
            num_folds = len(fold_keys)
            wsi_with_labels = await TrainingTaskRepository.get_wsi_with_labels(
                db, req.task_id
            )
            class_distribution: Dict[str, int] = {}
            for wsi in wsi_with_labels:
                label = wsi.get("label")
                if label:
                    class_distribution[label] = class_distribution.get(label, 0) + 1

            if len(class_distribution) < 2:
                raise HTTPException(
                    status_code=400,
                    detail=f"K-Fold cross-validation requires at least 2 classes. Found: {len(class_distribution)} class(es).",
                )

            min_class_name = min(class_distribution, key=class_distribution.get)
            min_class_count = class_distribution[min_class_name]
            if min_class_count < num_folds:
                class_info = ", ".join(
                    [
                        f"{label}: {count}"
                        for label, count in sorted(class_distribution.items())
                    ]
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"{num_folds}-Fold requires at least {num_folds} samples per class. Class '{min_class_name}' has {min_class_count}. [{class_info}]",
                )
        else:
            # Random split validation
            wsi_with_labels = await TrainingTaskRepository.get_wsi_with_labels(
                db, req.task_id
            )
            class_distribution: Dict[str, int] = {}
            for wsi in wsi_with_labels:
                label = wsi.get("label")
                if label:
                    class_distribution[label] = class_distribution.get(label, 0) + 1

            if len(class_distribution) < 2:
                raise HTTPException(
                    status_code=400,
                    detail=f"Classification requires at least 2 classes. Found: {len(class_distribution)}.",
                )

            min_class_name = min(class_distribution, key=class_distribution.get)
            min_class_count = class_distribution[min_class_name]
            if min_class_count < 10:
                class_info = ", ".join(
                    [
                        f"{label}: {count}"
                        for label, count in sorted(class_distribution.items())
                    ]
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"Random 7:1:2 split requires at least 10 samples per class. Class '{min_class_name}' has {min_class_count}. [{class_info}]",
                )

        num_classes = len(classes)
        preprocessing_config = task.preprocessing_config
        user_id = task.user_id

        # Mark task as training; preserve progress if resuming from checkpoint
        _training_start_progress = (
            task.progress if task.status == TaskStatus.RESUMING else 66
        )
        await TrainingTaskRepository.update_status(
            db, req.task_id, TaskStatus.TRAINING, progress=_training_start_progress
        )
        split_strategy_desc = _get_split_strategy_description(
            splits_map, preprocessing_config
        )
        splits_count_desc = _format_splits_count(splits_map)
        await training_logger.info(
            f"[Training] Starting WSI Classification ({req.aggregator.upper()})",
            {
                "task_type": "wsi_classification",
                "aggregator": req.aggregator,
                "epochs": req.epochs,
                "lr": req.lr,
                "num_classes": num_classes,
            },
        )
        await training_logger.info(
            f"[Data Split] {split_strategy_desc} | {splits_count_desc}",
            {
                "strategy": split_strategy_desc,
                "splits": {k: len(v) for k, v in splits_map.items()},
            },
        )
    # Session closed here - connection released before training starts

    try:
        # Phase 2: Training - pass session_maker, not long-lived session
        trainer = WSIClassificationTrainer(
            task_id=req.task_id,
            uploads_root=_uploads_dir(),
            device=req.device,
        )

        result = await trainer.train_model(
            splits_map=splits_map,
            aggregator_name=req.aggregator,
            num_classes=num_classes,
            epochs=req.epochs,
            lr=req.lr,
            logger=scoped_logger,
            session_maker=scoped_session.get_session_maker(),
            optimizer=req.optimizer,
            auto_balance=req.auto_balance,
            early_stopping_patience=req.early_stopping_patience,
            feature_extractor=req.feature_extractor,
            seed=req.seed,
        )

        # Phase 3: Save results - short-lived session
        async with scoped_session.session() as (training_logger, db):
            await TrainedModelRepository.create(
                db,
                {
                    "model_id": result.model_id,
                    "task_id": req.task_id,
                    "user_id": user_id,
                    "model_name": f"{req.feature_extractor}+{req.aggregator}",
                    "model_path": result.checkpoint_path,
                    "config_path": str(
                        Path(result.checkpoint_path).parent / "config.json"
                    ),
                    "classes": classes,
                    "feature_extractor": req.feature_extractor,
                    "aggregator": req.aggregator,
                    "train_metrics": sanitize_for_json(
                        {"loss": result.metrics.loss_history}
                    )
                    if result.metrics
                    else {},
                    "val_metrics": sanitize_for_json(result.metrics.val_metrics)
                    if result.metrics
                    else None,
                    "is_default": False,
                    "is_active": True,
                },
            )
            await training_logger.info(
                "Training completed. Model saved.", {"model_id": result.model_id}
            )
            await _safe_update_status(
                db, req.task_id, TaskStatus.COMPLETED, progress=100
            )

        return result

    except TrainingCancelledException as e:
        await scoped_logger.info(f"WSI Classification training cancelled: {e}")
        async with scoped_session.session() as (training_logger, db):
            await _safe_update_status(
                db, req.task_id, TaskStatus.CANCELLED, error_message=str(e)
            )
        return TrainResponse.cancelled(
            req.task_id, TaskType.WSI_CLASSIFICATION, message=str(e)
        )

    except Exception as e:
        await handle_training_error_scoped(
            e, req.task_id, scoped_session, "WSI Classification"
        )

    finally:
        await scoped_logger.close()
        await cleanup_training_scoped(req.task_id)


# =============================================================================
# WSI Survival Training
# =============================================================================


@router.post("/wsi_survival")
async def train_wsi_survival(req: WSISurvivalTrainRequest) -> TrainResponse:
    """
    WSI Survival Training Unified Entry.

    Uses ScopedSession pattern - creates short-lived DB sessions for each operation
    to prevent connection pool exhaustion during long-running training.
    """
    scoped_session = ScopedSession(req.task_id)
    scoped_logger = ScopedTrainingLogger(req.task_id)

    # Phase 1: Validation - short-lived session
    async with scoped_session.session() as (training_logger, db):
        task = await TrainingTaskRepository.get_by_id(db, req.task_id)
        if not task:
            raise HTTPException(
                status_code=404, detail=f"Training task not found: {req.task_id}"
            )

        splits_map = await TrainingTaskRepository.get_wsi_ids_by_split(db, req.task_id)
        if not splits_map:
            raise HTTPException(
                status_code=400, detail="No WSI data associated with this task"
            )

        user_id = task.user_id
        preprocessing_config = task.preprocessing_config

        # Mark task as training; preserve progress if resuming from checkpoint
        _training_start_progress = (
            task.progress if task.status == TaskStatus.RESUMING else 66
        )
        await TrainingTaskRepository.update_status(
            db, req.task_id, TaskStatus.TRAINING, progress=_training_start_progress
        )
        split_strategy_desc = _get_split_strategy_description(
            splits_map, preprocessing_config
        )
        splits_count_desc = _format_splits_count(splits_map)
        await training_logger.info(
            f"[Training] Starting WSI Survival ({req.aggregator.upper()})",
            {
                "task_type": "wsi_survival",
                "aggregator": req.aggregator,
                "epochs": req.epochs,
                "lr": req.lr,
                "weight_decay": req.weight_decay,
                "num_bins": req.num_bins,
            },
        )
        await training_logger.info(
            f"[Data Split] {split_strategy_desc} | {splits_count_desc}",
            {
                "strategy": split_strategy_desc,
                "splits": {k: len(v) for k, v in splits_map.items()},
            },
        )
    # Session closed here - connection released before training starts

    try:
        # Phase 2: Training - pass session_maker, not long-lived session
        trainer = WSISurvivalTrainer(
            task_id=req.task_id,
            uploads_root=_uploads_dir(),
            device=req.device,
        )

        result = await trainer.train_model(
            splits_map=splits_map,
            aggregator_name=req.aggregator,
            num_classes=req.num_bins,
            epochs=req.epochs,
            lr=req.lr,
            weight_decay=req.weight_decay,
            logger=scoped_logger,
            session_maker=scoped_session.get_session_maker(),
            optimizer=req.optimizer,
            early_stopping_patience=req.early_stopping_patience,
            feature_extractor=req.feature_extractor,
            seed=req.seed,
        )

        # Phase 3: Save results - short-lived session
        async with scoped_session.session() as (training_logger, db):
            await TrainedModelRepository.create(
                db,
                {
                    "model_id": result.model_id,
                    "task_id": req.task_id,
                    "user_id": user_id,
                    "model_name": f"{req.feature_extractor}+{req.aggregator}_survival",
                    "model_path": result.checkpoint_path,
                    "config_path": str(
                        Path(result.checkpoint_path).parent / "config.json"
                    ),
                    "classes": [f"Bin {i}" for i in range(req.num_bins)],
                    "feature_extractor": req.feature_extractor,
                    "aggregator": req.aggregator,
                    "train_metrics": sanitize_for_json(
                        {"loss": result.metrics.loss_history}
                    )
                    if result.metrics
                    else {},
                    "val_metrics": sanitize_for_json(result.metrics.val_metrics)
                    if result.metrics
                    else None,
                    "is_default": False,
                    "is_active": True,
                },
            )
            await training_logger.info(
                "Training completed. Model saved.", {"model_id": result.model_id}
            )
            await _safe_update_status(
                db, req.task_id, TaskStatus.COMPLETED, progress=100
            )

        return result

    except TrainingCancelledException as e:
        await scoped_logger.info(f"WSI Survival training cancelled: {e}")
        async with scoped_session.session() as (training_logger, db):
            await _safe_update_status(
                db, req.task_id, TaskStatus.CANCELLED, error_message=str(e)
            )
        return TrainResponse.cancelled(
            req.task_id, TaskType.WSI_SURVIVAL, message=str(e)
        )

    except Exception as e:
        await handle_training_error_scoped(
            e, req.task_id, scoped_session, "WSI Survival"
        )

    finally:
        await scoped_logger.close()
        await cleanup_training_scoped(req.task_id)


# =============================================================================
# Patch Classification Training
# =============================================================================


@router.post("/patch_classification")
async def train_patch_classification(
    req: PatchClassificationTrainRequest,
) -> TrainResponse:
    """
    Patch Classification Training Unified Entry.

    Uses ScopedSession pattern - creates short-lived DB sessions for each operation
    to prevent connection pool exhaustion during long-running training.
    """
    from backend.ai.tasks import PatchClassificationTrainer

    scoped_session = ScopedSession(req.task_id)
    scoped_logger = ScopedTrainingLogger(req.task_id)

    # Phase 1: Validation - short-lived session
    async with scoped_session.session() as (training_logger, db):
        task = await TrainingTaskRepository.get_by_id(db, req.task_id)
        if not task:
            raise HTTPException(
                status_code=404, detail=f"Training task not found: {req.task_id}"
            )

        classes: List[str] = task.classes or []
        if not classes:
            raise HTTPException(
                status_code=400,
                detail="No classes found for training task. Please ensure WSI slides have labels.",
            )

        splits_map = await TrainingTaskRepository.get_wsi_ids_by_split(db, req.task_id)
        if not splits_map:
            raise HTTPException(
                status_code=400, detail="No data associated with this task"
            )

        num_classes = len(classes)
        user_id = task.user_id
        preprocessing_config = task.preprocessing_config

        # Mark task as training from 0% and let the trainer advance it to 100%.
        _training_start_progress = (
            task.progress if task.status == TaskStatus.RESUMING else 0
        )
        await TrainingTaskRepository.update_status(
            db, req.task_id, TaskStatus.TRAINING, progress=_training_start_progress
        )
        split_strategy_desc = _get_split_strategy_description(
            splits_map, preprocessing_config
        )
        splits_count_desc = _format_splits_count(splits_map)
        await training_logger.info(
            f"[Training] Starting Patch Classification ({req.feature_extractor.upper()}, classifier={req.classifier})",
            {
                "task_type": "patch_classification",
                "feature_extractor": req.feature_extractor,
                "classifier": req.classifier,
                "epochs": req.epochs,
                "lr": req.lr,
                "num_classes": num_classes,
            },
        )
        await training_logger.info(
            f"[Data Split] {split_strategy_desc} | {splits_count_desc}",
            {
                "strategy": split_strategy_desc,
                "splits": {k: len(v) for k, v in splits_map.items()},
            },
        )
    # Session closed here - connection released before training starts

    try:
        # Phase 2: Training - pass session_maker, not long-lived session
        trainer = PatchClassificationTrainer(
            task_id=req.task_id,
            uploads_root=_uploads_dir(),
            device=req.device,
            batch_size=req.batch_size,
            hf_token=req.huggingface_token,
        )

        result = await trainer.train_model(
            splits_map=splits_map,
            aggregator_name=req.feature_extractor,
            num_classes=num_classes,
            epochs=req.epochs,
            lr=req.lr,
            logger=scoped_logger,
            session_maker=scoped_session.get_session_maker(),
            optimizer=req.optimizer,
            auto_balance=req.auto_balance,
            early_stopping_patience=req.early_stopping_patience,
            seed=req.seed,
            classifier_name=req.classifier,
        )

        # Phase 3: Save results - short-lived session
        if result.status == "success" and result.model_id:
            async with scoped_session.session() as (training_logger, db):
                await TrainedModelRepository.create(
                    db,
                    {
                        "model_id": result.model_id,
                        "task_id": req.task_id,
                        "user_id": user_id,
                        "model_name": f"{req.feature_extractor}+linear_probe",
                        "model_path": result.checkpoint_path or "",
                        "config_path": str(
                            Path(result.checkpoint_path).parent / "config.json"
                        )
                        if result.checkpoint_path
                        else "",
                        "classes": classes,
                        "feature_extractor": req.feature_extractor,
                        "aggregator": "linear_probe",
                        "train_metrics": sanitize_for_json(
                            {"loss": result.metrics.loss_history}
                        )
                        if result.metrics
                        else {},
                        "val_metrics": sanitize_for_json(result.metrics.val_metrics)
                        if result.metrics
                        else None,
                        "is_default": False,
                        "is_active": True,
                    },
                )

        async with scoped_session.session() as (training_logger, db):
            await _safe_update_status(
                db, req.task_id, TaskStatus.COMPLETED, progress=100
            )

        return result

    except TrainingCancelledException as e:
        await scoped_logger.info(f"Patch Classification training cancelled: {e}")
        async with scoped_session.session() as (training_logger, db):
            await _safe_update_status(
                db, req.task_id, TaskStatus.CANCELLED, error_message=str(e)
            )
        return TrainResponse.cancelled(
            req.task_id, TaskType.PATCH_CLASSIFICATION, message=str(e)
        )

    except Exception as e:
        await handle_training_error_scoped(
            e, req.task_id, scoped_session, "Patch Classification"
        )

    finally:
        await scoped_logger.close()
        await cleanup_training_scoped(req.task_id)


# =============================================================================
# Patch Segmentation Training
# =============================================================================


@router.post("/patch_detection")
async def train_patch_detection(req: PatchDetectionTrainRequest) -> TrainResponse:
    import asyncio
    from backend.ai.tasks.patch_detection import DetectionTrainer

    scoped = ScopedSession(req.task_id)
    trainer = None
    model_id = f"det_{req.task_id}"
    directory = _uploads_dir() / "models" / model_id
    try:
        async with scoped.session() as (log, db):
            task = await TrainingTaskRepository.get_by_id(db, req.task_id)
            if task is None or task.task_type != "patch_detection":
                raise ValueError("Patch detection training task not found")
            config = dict(task.model_config)
            dataset = task.preprocessing_config["detection_dataset"]
            classes, user_id = list(task.classes), task.user_id
            seed = task.preprocessing_config.get("split_config", {}).get("seed", 42)
            await _safe_update_status(db, req.task_id, TaskStatus.TRAINING, progress=5)
        loop = asyncio.get_running_loop()

        async def report(epoch, loss, metrics):
            async with scoped.session() as (log, db):
                await log.info(f"Detection epoch {epoch}/{config['epochs']}", {"loss": loss, **metrics})
                await _safe_update_status(db, req.task_id, TaskStatus.TRAINING,
                                          progress=5 + int(85 * epoch / config["epochs"]))

        def progress(epoch, loss, metrics):
            asyncio.run_coroutine_threadsafe(report(epoch, loss, metrics), loop).result()

        trainer = await asyncio.to_thread(DetectionTrainer, req.task_id, config, dataset,
                                          classes, directory, req.device, seed, req.huggingface_token)
        results = await asyncio.to_thread(trainer.train, progress)
        checkpoint = str(directory / "best_model.pth")
        async with scoped.session() as (log, db):
            await TrainedModelRepository.create(db, {
                "model_id": model_id, "task_id": req.task_id, "user_id": user_id,
                "model_name": f"{config['architecture']}+{config['backbone']}",
                "model_path": checkpoint, "config_path": str(directory / "config.json"),
                "classes": classes, "feature_extractor": config["backbone"],
                "aggregator": config["architecture"], "train_metrics": {"loss": results["history"]["train_loss"]},
                "val_metrics": results["best_val_metrics"], "is_default": False, "is_active": True,
            })
        return TrainResponse.success(task_id=req.task_id, task_type=TaskType.PATCH_DETECTION,
                                     model_id=model_id, checkpoint_path=checkpoint,
                                     metrics=TrainMetrics(loss_history=results["history"]["train_loss"],
                                                          val_metrics={k: v for k, v in results["best_val_metrics"].items() if v is not None},
                                                          test_metrics={k: v for k, v in (results["test_metrics"] or {}).items() if v is not None}, best_epoch=results["best_epoch"]))
    except TrainingCancelledException as exc:
        return TrainResponse.cancelled(req.task_id, TaskType.PATCH_DETECTION, message=str(exc))
    except Exception as exc:
        await handle_training_error_scoped(exc, req.task_id, scoped, "Patch Detection")
    finally:
        if trainer is not None:
            trainer.release_resources()
        await cleanup_training_scoped(req.task_id)


@router.post("/patch_segmentation")
async def train_patch_segmentation(req: PatchSegmentationTrainRequest) -> TrainResponse:
    """
    Patch Segmentation Training.

    Uses ScopedSession pattern - creates short-lived DB sessions for each operation
    to prevent connection pool exhaustion during long-running training.
    The SegmentationTrainer is synchronous, so it runs in a thread pool.
    """
    import asyncio
    from backend.ai.tasks import SegmentationTrainer

    _validate_patch_segmentation_loss_names(req.loss_names)

    scoped_session = ScopedSession(req.task_id)

    # Phase 1: Validation - short-lived session
    async with scoped_session.session() as (training_logger, db):
        task = await TrainingTaskRepository.get_by_id(db, req.task_id)
        if not task:
            raise HTTPException(
                status_code=404, detail=f"Training task not found: {req.task_id}"
            )

        user_id = task.user_id
        preprocessing_config = task.preprocessing_config or {}

        # Mark task as training from 0% and let the trainer advance it through the training phase.
        _training_start_progress = (
            task.progress if task.status == TaskStatus.RESUMING else 0
        )
        await TrainingTaskRepository.update_status(
            db, req.task_id, TaskStatus.TRAINING, progress=_training_start_progress
        )
        await training_logger.info(
            f"[Training] Starting Patch Segmentation ({req.architecture}/{req.backbone})",
            {
                "task_type": "patch_segmentation",
                "architecture": req.architecture,
                "backbone": req.backbone,
                "epochs": req.epochs,
                "lr": req.lr,
            },
        )
    # Session closed here - connection released before training starts

    trainer = None

    try:
        # Phase 2: Build config and run training in thread pool
        # Use a deterministic model_id derived from task_id so that
        # resume_checkpoint.pth written in a previous run can be found
        # when the task is restarted after a crash/disconnect.
        model_id = f"seg_{req.task_id}"
        model_dir = _uploads_dir() / "models" / model_id
        model_dir.mkdir(parents=True, exist_ok=True)
        save_dir = str(model_dir)
        _decoder_type = req.decoder_type or req.architecture.replace("_decoder", "")
        config = {
            "architecture": req.architecture,
            "backbone": req.backbone,
            "decoder_type": _decoder_type,
            "loss": {"names": req.loss_names, "weights": req.loss_weights},
            "training": {
                "epochs": req.epochs,
                "lr": req.lr,
                "optimizer": req.optimizer,
                "early_stopping_patience": req.early_stopping_patience,
                "seed": req.seed,
            },
            "monitor_metric": "miou" if req.num_classes > 1 else "iou",
            "save_dir": save_dir,
        }
        segmentation_dataset = preprocessing_config.get("segmentation_dataset")
        if not segmentation_dataset:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Missing segmentation_dataset in preprocessing_config. "
                    "The gateway pipeline must prepare train/val/test COCO split files before "
                    "starting patch segmentation training."
                ),
            )

        for split_name in ("train", "val", "test"):
            split_cfg = segmentation_dataset.get(split_name) or {}
            if not split_cfg.get("image_dir") or not split_cfg.get("annotations_path"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Incomplete segmentation_dataset config for split '{split_name}'",
                )

        config["dataset"] = segmentation_dataset
        # Always apply num_classes from request (overrides default of 1)
        config.setdefault("dataset", {})["classes"] = req.num_classes
        segmentation_class_names = list(
            dict.fromkeys(
                str(label).strip()
                for label in (task.classes or [])
                if str(label).strip()
            )
        )
        if segmentation_class_names:
            config.setdefault("dataset", {})["class_names"] = segmentation_class_names

        device_str = req.device
        device_obj = torch.device(device_str) if device_str else None
        if device_obj and device_obj.type == "cuda":
            await asyncio.to_thread(check_vram_before_model_load,
                                    model_name=req.backbone, device=device_obj,
                                    batch_size=req.batch_size, operation='segmentation',
                                    trainable=req.backbone.lower().startswith(('resnet', 'efficientnet', 'vgg', 'mobilenet', 'densenet')))

        trainer = SegmentationTrainer(
            task_id=req.task_id,
            uploads_root=_uploads_dir(),
            device=device_str,
            batch_size=req.batch_size,
            config=config,
        )

        # Run sync training in thread pool to avoid blocking event loop
        results = await asyncio.to_thread(
            trainer.train_model, req.epochs, req.lr, req.early_stopping_patience
        )

        # Build TrainResponse from results dict
        checkpoint_path = str(model_dir / "best_model.pth")

        metrics = TrainMetrics(
            loss_history=results.get("history", {}).get("train_loss", []),
            lr_history=results.get("history", {}).get("learning_rates", []),
            val_metrics=sanitize_for_json(results.get("best_val_metrics", {})),
            test_metrics=sanitize_for_json(results.get("test_metrics")),
            best_epoch=results.get("best_epoch"),
        )

        result = TrainResponse.success(
            task_id=req.task_id,
            task_type=TaskType.PATCH_SEGMENTATION,
            model_id=model_id,
            checkpoint_path=checkpoint_path,
            metrics=metrics,
        )

        history = results.get("history", {})
        training_config_info = {
            "architecture": req.architecture,
            "backbone": req.backbone,
            "task_id": req.task_id,
            "classes": segmentation_class_names,
            "num_classes": req.num_classes,
        }
        (model_dir / "config.json").write_text(
            json.dumps(training_config_info, ensure_ascii=False, indent=2)
        )
        metrics_data = {
            "history": {
                "train_loss": history.get("train_loss", []),
                "val_loss": history.get("val_loss", []),
                "train_metrics": sanitize_for_json(history.get("train_metrics", [])),
                "val_metrics": sanitize_for_json(history.get("val_metrics", [])),
                "learning_rates": history.get("learning_rates", []),
            },
            "best_epoch": results.get("best_epoch"),
            "best_val_metrics": sanitize_for_json(results.get("best_val_metrics", {})),
            "test_metrics": sanitize_for_json(results.get("test_metrics")),
            "config": training_config_info,
        }
        (model_dir / "metrics.json").write_text(
            json.dumps(metrics_data, ensure_ascii=False, indent=2)
        )
        for _epoch_ckpt in model_dir.glob("checkpoint_epoch_*.pth"):
            _epoch_ckpt.unlink(missing_ok=True)
        _regular_ckpt = model_dir / "checkpoint.pth"
        if _regular_ckpt.exists():
            _regular_ckpt.unlink()

        # Phase 3: Save model - short-lived session
        async with scoped_session.session() as (training_logger, db):
            await TrainedModelRepository.create(
                db,
                {
                    "model_id": model_id,
                    "task_id": req.task_id,
                    "user_id": user_id,
                    "model_name": f"{req.architecture}+{req.backbone}",
                    "model_path": checkpoint_path,
                    "config_path": str(Path(checkpoint_path).parent / "config.json"),
                    "classes": segmentation_class_names,
                    "feature_extractor": req.backbone,
                    "aggregator": req.architecture,
                    "train_metrics": sanitize_for_json(
                        {"loss": history.get("train_loss", [])}
                    ),
                    "val_metrics": sanitize_for_json(
                        results.get("best_val_metrics", {})
                    ),
                    "is_default": False,
                    "is_active": True,
                },
            )
            await training_logger.info(
                "Training completed. Model saved.", {"model_id": model_id}
            )
            await _safe_update_status(
                db, req.task_id, TaskStatus.COMPLETED, progress=100
            )

        return result

    except TrainingCancelledException as e:
        async with scoped_session.session() as (training_logger, db):
            await training_logger.info(f"Patch Segmentation training cancelled: {e}")
            await _safe_update_status(
                db, req.task_id, TaskStatus.CANCELLED, error_message=str(e)
            )
        return TrainResponse.cancelled(
            req.task_id, TaskType.PATCH_SEGMENTATION, message=str(e)
        )

    except Exception as e:
        await handle_training_error_scoped(
            e, req.task_id, scoped_session, "Patch Segmentation"
        )

    finally:
        if trainer is not None:
            trainer.release_resources()
        await cleanup_training_scoped(req.task_id)
