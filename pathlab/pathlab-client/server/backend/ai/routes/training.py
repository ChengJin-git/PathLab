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
from typing import List, Optional, Dict

import torch
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.database.database import AsyncSession
from backend.database.repositories import (
    TrainingTaskRepository,
    TrainedModelRepository,
)
from backend.database.utils.training_logger import TrainingLogger
from backend.database.utils.json_utils import sanitize_for_json
from backend.ai.utils.scoped_session import ScopedSession, ScopedTrainingLogger
from backend.ai.tasks import WSIClassificationTrainer, WSISurvivalTrainer
from backend.ai.extractors.registry import get_available_extractors
from backend.ai.schemas import (
    TrainResponse,
    TrainMetrics,
    TaskType,
)
from backend.ai.schemas.base import TaskStatus
from backend.common.config import Config

logger = logging.getLogger("training_routes")

# Paths
UPLOADS_DIR = Config.get_uploads_dir()

# =============================================================================
# Cancellation Mechanism (imported from separate module to avoid circular imports)
# =============================================================================
from backend.ai.cancellation import (
    request_cancellation,
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
    PermissionRevokedException,
)

router = APIRouter(prefix="/training", tags=["training"])


@router.delete("/{task_id}")
async def cancel_training_task(task_id: str):
    """
    Request cancellation of a running training task.

    The training will stop at the next checkpoint (typically after current epoch).
    GPU memory will be released after cancellation.

    Returns:
        {"cancelled": True, "message": str}
    """
    request_cancellation(task_id)
    return {
        "cancelled": True,
        "message": f"Cancellation requested for task {task_id}. Training will stop at next checkpoint."
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
        "message": f"Permission revoked for task {task_id}. Training will stop at next iteration."
    }


async def _safe_update_status(
    db,
    task_id: str,
    new_status: str,
    progress: int = None,
    error_message: str = None
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

    # Update status
    await TrainingTaskRepository.update_status(db, task_id, new_status, progress=progress, error_message=error_message)
    return True


def _get_split_strategy_description(splits_map: dict, preprocessing_config: dict = None) -> str:
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


def _format_splits_count(splits_map: dict) -> str:
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
            mem_before = torch.cuda.memory_allocated(device_idx) / (1024 ** 2)
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
            mem_after = torch.cuda.memory_allocated(device_idx) / (1024 ** 2)
            logger.info(f"GPU memory cleaned up: {mem_before:.1f} MB -> {mem_after:.1f} MB")
        except Exception:
            logger.info("GPU memory cleaned up")
    else:
        gc.collect()
        logger.info("GPU not available, only ran gc.collect()")


async def handle_training_error_scoped(
    e: Exception,
    task_id: str,
    scoped_session: ScopedSession,
    operation_name: str = "Training"
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
            await training_logger.error(f"{operation_name} failed - File not found", {"error": str(e), "traceback": tb})
            await _safe_update_status(db, task_id, TaskStatus.FAILED, progress=0, error_message=str(e))
        raise HTTPException(status_code=404, detail=f"File not found: {e}")

    elif isinstance(e, ValueError):
        logger.error(f"{operation_name} failed - Invalid data: {e}\n{tb}")
        async with scoped_session.session() as (training_logger, db):
            await training_logger.error(f"{operation_name} failed - Invalid data", {"error": str(e), "traceback": tb})
            await _safe_update_status(db, task_id, TaskStatus.FAILED, progress=0, error_message=str(e))
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
            await training_logger.error(f"{operation_name} failed - CUDA out of memory", {"error": error_detail, "traceback": tb})
            await _safe_update_status(db, task_id, TaskStatus.FAILED, progress=0, error_message=full_error)
        raise HTTPException(status_code=500, detail=full_error)

    else:
        logger.error(f"{operation_name} failed: {e}\n{tb}")
        async with scoped_session.session() as (training_logger, db):
            await training_logger.error(f"{operation_name} failed", {"error": str(e), "traceback": tb})
            await _safe_update_status(db, task_id, TaskStatus.FAILED, progress=0, error_message=str(e))
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

class FeatureExtractionRequest(BaseModel):
    """Feature extraction request"""
    task_id: str
    wsi_ids: List[str]
    feature_extractor: str = "resnet50"
    batch_size: int = 64  # Default batch size
    force_recompute: bool = False
    huggingface_token: Optional[str] = None
    device: Optional[str] = None  # GPU device (e.g., "cuda:0") - auto-selected if None


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
                raise HTTPException(status_code=404, detail=f"Training task not found: {req.task_id}")
            preprocessing_config = task.preprocessing_config or {}
            await training_logger.info(
                f"[Step 2/3] Starting feature extraction for {len(req.wsi_ids)} WSI",
                {"feature_extractor": req.feature_extractor, "batch_size": req.batch_size}
            )
            await TrainingTaskRepository.update_status(db, req.task_id, TaskStatus.EXTRACTING, progress=33)
        # Session closed here - connection released

        # Use WSI Classification Trainer with session_maker
        trainer = WSIClassificationTrainer(
            task_id=req.task_id,
            uploads_root=UPLOADS_DIR,
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

        await scoped_logger.info(f"Feature extraction completed for all {len(req.wsi_ids)} WSI")

        # Prepare response data before any cleanup
        response_data = results.model_dump()
        cleanup_gpu_memory()
        return response_data

    except TrainingCancelledException as e:
        await scoped_logger.info(f"Feature extraction cancelled: {e}")
        async with scoped_session.session() as (training_logger, db):
            await _safe_update_status(db, req.task_id, TaskStatus.CANCELLED, error_message=str(e))
        cleanup_gpu_memory()
        return {"status": TaskStatus.CANCELLED, "results": [], "error_message": str(e)}

    except Exception as e:
        await handle_training_error_scoped(e, req.task_id, scoped_session, "Feature extraction")
        cleanup_gpu_memory()
        raise


# =============================================================================
# WSI Classification Training (Unified Entry)
# =============================================================================

class WSIClassificationTrainRequest(BaseModel):
    """WSI classification training request"""
    task_id: str
    epochs: int = 50
    lr: float = 2e-4
    aggregator: str = "abmil"
    feature_extractor: str = "resnet50"
    optimizer: str = "adam"  # adam, sgd, adamw
    auto_balance: bool = False  # Auto-balance class weights
    early_stopping_patience: int = 20  # Epochs to wait before early stopping
    device: Optional[str] = None  # GPU device (e.g., "cuda:0") - auto-selected if None
    seed: Optional[int] = 42  # Random seed for reproducibility


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
            raise HTTPException(status_code=404, detail=f"Training task not found: {req.task_id}")

        classes: List[str] = task.classes or []
        if not classes:
            raise HTTPException(status_code=400, detail="Training task has no classes")

        splits_map = await TrainingTaskRepository.get_wsi_ids_by_split(db, req.task_id)
        if not splits_map:
            raise HTTPException(status_code=400, detail="No WSI data associated with this task")

        # K-Fold validation
        fold_keys = [k for k in splits_map.keys() if k.startswith("fold_")]
        if fold_keys:
            num_folds = len(fold_keys)
            wsi_with_labels = await TrainingTaskRepository.get_wsi_with_labels(db, req.task_id)
            class_distribution: Dict[str, int] = {}
            for wsi in wsi_with_labels:
                label = wsi.get("label")
                if label:
                    class_distribution[label] = class_distribution.get(label, 0) + 1

            if len(class_distribution) < 2:
                raise HTTPException(
                    status_code=400,
                    detail=f"K-Fold cross-validation requires at least 2 classes. Found: {len(class_distribution)} class(es)."
                )

            min_class_name = min(class_distribution, key=class_distribution.get)
            min_class_count = class_distribution[min_class_name]
            if min_class_count < num_folds:
                class_info = ", ".join([f"{label}: {count}" for label, count in sorted(class_distribution.items())])
                raise HTTPException(
                    status_code=400,
                    detail=f"{num_folds}-Fold requires at least {num_folds} samples per class. Class '{min_class_name}' has {min_class_count}. [{class_info}]"
                )
        else:
            # Random split validation
            wsi_with_labels = await TrainingTaskRepository.get_wsi_with_labels(db, req.task_id)
            class_distribution: Dict[str, int] = {}
            for wsi in wsi_with_labels:
                label = wsi.get("label")
                if label:
                    class_distribution[label] = class_distribution.get(label, 0) + 1

            if len(class_distribution) < 2:
                raise HTTPException(status_code=400, detail=f"Classification requires at least 2 classes. Found: {len(class_distribution)}.")

            min_class_name = min(class_distribution, key=class_distribution.get)
            min_class_count = class_distribution[min_class_name]
            if min_class_count < 10:
                class_info = ", ".join([f"{label}: {count}" for label, count in sorted(class_distribution.items())])
                raise HTTPException(
                    status_code=400,
                    detail=f"Random 7:1:2 split requires at least 10 samples per class. Class '{min_class_name}' has {min_class_count}. [{class_info}]"
                )

        num_classes = len(classes)
        preprocessing_config = task.preprocessing_config
        user_id = task.user_id

        # Mark task as training and log start
        await TrainingTaskRepository.update_status(db, req.task_id, TaskStatus.TRAINING, progress=66)
        split_strategy_desc = _get_split_strategy_description(splits_map, preprocessing_config)
        splits_count_desc = _format_splits_count(splits_map)
        await training_logger.info(
            f"[Training] Starting WSI Classification ({req.aggregator.upper()})",
            {"task_type": "wsi_classification", "aggregator": req.aggregator, "epochs": req.epochs, "lr": req.lr, "num_classes": num_classes}
        )
        await training_logger.info(
            f"[Data Split] {split_strategy_desc} | {splits_count_desc}",
            {"strategy": split_strategy_desc, "splits": {k: len(v) for k, v in splits_map.items()}}
        )
    # Session closed here - connection released before training starts

    try:
        # Phase 2: Training - pass session_maker, not long-lived session
        trainer = WSIClassificationTrainer(
            task_id=req.task_id,
            uploads_root=UPLOADS_DIR,
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
            await TrainedModelRepository.create(db, {
                "model_id": result.model_id,
                "task_id": req.task_id,
                "user_id": user_id,
                "model_name": f"{req.feature_extractor}+{req.aggregator}",
                "model_path": result.checkpoint_path,
                "config_path": str(Path(result.checkpoint_path).parent / "config.json"),
                "classes": classes,
                "feature_extractor": req.feature_extractor,
                "aggregator": req.aggregator,
                "train_metrics": sanitize_for_json({"loss": result.metrics.loss_history}) if result.metrics else {},
                "val_metrics": sanitize_for_json(result.metrics.val_metrics) if result.metrics else None,
                "is_default": False,
                "is_active": True,
            })
            await training_logger.info("Training completed. Model saved.", {"model_id": result.model_id})
            await _safe_update_status(db, req.task_id, TaskStatus.COMPLETED, progress=100)

        return result

    except TrainingCancelledException as e:
        await scoped_logger.info(f"WSI Classification training cancelled: {e}")
        async with scoped_session.session() as (training_logger, db):
            await _safe_update_status(db, req.task_id, TaskStatus.CANCELLED, error_message=str(e))
        return TrainResponse.cancelled(req.task_id, TaskType.WSI_CLASSIFICATION, message=str(e))

    except Exception as e:
        await handle_training_error_scoped(e, req.task_id, scoped_session, "WSI Classification")

    finally:
        await cleanup_training_scoped(req.task_id)


# =============================================================================
# WSI Survival Training
# =============================================================================

class WSISurvivalTrainRequest(BaseModel):
    """WSI survival training request"""
    task_id: str
    epochs: int = 30
    lr: float = 0.0002
    aggregator: str = "abmil"
    feature_extractor: str = "resnet50"
    num_bins: int = 4  # Number of discrete time bins
    optimizer: str = "adam"  # adam, sgd, adamw
    early_stopping_patience: int = 20  # Epochs to wait before early stopping
    device: Optional[str] = None  # GPU device (e.g., "cuda:0") - auto-selected if None
    seed: Optional[int] = 42  # Random seed for reproducibility


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
            raise HTTPException(status_code=404, detail=f"Training task not found: {req.task_id}")

        splits_map = await TrainingTaskRepository.get_wsi_ids_by_split(db, req.task_id)
        if not splits_map:
            raise HTTPException(status_code=400, detail="No WSI data associated with this task")

        user_id = task.user_id
        preprocessing_config = task.preprocessing_config

        # Mark task as training and log start
        await TrainingTaskRepository.update_status(db, req.task_id, TaskStatus.TRAINING, progress=66)
        split_strategy_desc = _get_split_strategy_description(splits_map, preprocessing_config)
        splits_count_desc = _format_splits_count(splits_map)
        await training_logger.info(
            f"[Training] Starting WSI Survival ({req.aggregator.upper()})",
            {"task_type": "wsi_survival", "aggregator": req.aggregator, "epochs": req.epochs, "lr": req.lr, "num_bins": req.num_bins}
        )
        await training_logger.info(
            f"[Data Split] {split_strategy_desc} | {splits_count_desc}",
            {"strategy": split_strategy_desc, "splits": {k: len(v) for k, v in splits_map.items()}}
        )
    # Session closed here - connection released before training starts

    try:
        # Phase 2: Training - pass session_maker, not long-lived session
        trainer = WSISurvivalTrainer(
            task_id=req.task_id,
            uploads_root=UPLOADS_DIR,
            device=req.device,
        )

        result = await trainer.train_model(
            splits_map=splits_map,
            aggregator_name=req.aggregator,
            num_classes=req.num_bins,
            epochs=req.epochs,
            lr=req.lr,
            logger=scoped_logger,
            session_maker=scoped_session.get_session_maker(),
            optimizer=req.optimizer,
            early_stopping_patience=req.early_stopping_patience,
            feature_extractor=req.feature_extractor,
            seed=req.seed,
        )

        # Phase 3: Save results - short-lived session
        async with scoped_session.session() as (training_logger, db):
            await TrainedModelRepository.create(db, {
                "model_id": result.model_id,
                "task_id": req.task_id,
                "user_id": user_id,
                "model_name": f"{req.feature_extractor}+{req.aggregator}_survival",
                "model_path": result.checkpoint_path,
                "config_path": str(Path(result.checkpoint_path).parent / "config.json"),
                "classes": [f"Bin {i}" for i in range(req.num_bins)],
                "feature_extractor": req.feature_extractor,
                "aggregator": req.aggregator,
                "train_metrics": sanitize_for_json({"loss": result.metrics.loss_history}) if result.metrics else {},
                "val_metrics": sanitize_for_json(result.metrics.val_metrics) if result.metrics else None,
                "is_default": False,
                "is_active": True,
            })
            await training_logger.info("Training completed. Model saved.", {"model_id": result.model_id})
            await _safe_update_status(db, req.task_id, TaskStatus.COMPLETED, progress=100)

        return result

    except TrainingCancelledException as e:
        await scoped_logger.info(f"WSI Survival training cancelled: {e}")
        async with scoped_session.session() as (training_logger, db):
            await _safe_update_status(db, req.task_id, TaskStatus.CANCELLED, error_message=str(e))
        return TrainResponse.cancelled(req.task_id, TaskType.WSI_SURVIVAL, message=str(e))

    except Exception as e:
        await handle_training_error_scoped(e, req.task_id, scoped_session, "WSI Survival")

    finally:
        await cleanup_training_scoped(req.task_id)


# =============================================================================
# Patch Classification Training
# =============================================================================

class PatchClassificationTrainRequest(BaseModel):
    """Patch classification training request - aligned with WSI classification style"""
    task_id: str
    epochs: int = 50
    lr: float = 0.0002
    feature_extractor: str = "resnet50"
    batch_size: int = 64
    huggingface_token: Optional[str] = None
    classifier: str = "linear"  # Classifier head: linear, mlp, attention
    optimizer: str = "adam"  # adam, sgd, adamw
    auto_balance: bool = False  # Auto-balance class weights
    early_stopping_patience: int = 20  # Epochs to wait before early stopping
    device: Optional[str] = None  # GPU device (e.g., "cuda:0") - auto-selected if None
    seed: Optional[int] = 42  # Random seed for reproducibility


@router.post("/patch_classification")
async def train_patch_classification(req: PatchClassificationTrainRequest) -> TrainResponse:
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
            raise HTTPException(status_code=404, detail=f"Training task not found: {req.task_id}")

        classes: List[str] = task.classes or []
        if not classes:
            raise HTTPException(status_code=400, detail="No classes found for training task. Please ensure WSI slides have labels.")

        splits_map = await TrainingTaskRepository.get_wsi_ids_by_split(db, req.task_id)
        if not splits_map:
            raise HTTPException(status_code=400, detail="No data associated with this task")

        num_classes = len(classes)
        user_id = task.user_id
        preprocessing_config = task.preprocessing_config

        # Mark task as training and log start
        await TrainingTaskRepository.update_status(db, req.task_id, TaskStatus.TRAINING, progress=66)
        split_strategy_desc = _get_split_strategy_description(splits_map, preprocessing_config)
        splits_count_desc = _format_splits_count(splits_map)
        await training_logger.info(
            f"[Training] Starting Patch Classification ({req.feature_extractor.upper()}, classifier={req.classifier})",
            {"task_type": "patch_classification", "feature_extractor": req.feature_extractor, "classifier": req.classifier, "epochs": req.epochs, "lr": req.lr, "num_classes": num_classes}
        )
        await training_logger.info(
            f"[Data Split] {split_strategy_desc} | {splits_count_desc}",
            {"strategy": split_strategy_desc, "splits": {k: len(v) for k, v in splits_map.items()}}
        )
    # Session closed here - connection released before training starts

    try:
        # Phase 2: Training - pass session_maker, not long-lived session
        trainer = PatchClassificationTrainer(
            task_id=req.task_id,
            uploads_root=UPLOADS_DIR,
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
                await TrainedModelRepository.create(db, {
                    "model_id": result.model_id,
                    "task_id": req.task_id,
                    "user_id": user_id,
                    "model_name": f"{req.feature_extractor}+linear_probe",
                    "model_path": result.checkpoint_path or "",
                    "config_path": str(Path(result.checkpoint_path).parent / "config.json") if result.checkpoint_path else "",
                    "classes": classes,
                    "feature_extractor": req.feature_extractor,
                    "aggregator": "linear_probe",
                    "train_metrics": sanitize_for_json({"loss": result.metrics.loss_history}) if result.metrics else {},
                    "val_metrics": sanitize_for_json(result.metrics.val_metrics) if result.metrics else None,
                    "is_default": False,
                    "is_active": True,
                })

        async with scoped_session.session() as (training_logger, db):
            await _safe_update_status(db, req.task_id, TaskStatus.COMPLETED, progress=100)

        return result

    except TrainingCancelledException as e:
        await scoped_logger.info(f"Patch Classification training cancelled: {e}")
        async with scoped_session.session() as (training_logger, db):
            await _safe_update_status(db, req.task_id, TaskStatus.CANCELLED, error_message=str(e))
        return TrainResponse.cancelled(req.task_id, TaskType.PATCH_CLASSIFICATION, message=str(e))

    except Exception as e:
        await handle_training_error_scoped(e, req.task_id, scoped_session, "Patch Classification")

    finally:
        await cleanup_training_scoped(req.task_id)


# =============================================================================
# Patch Segmentation Training
# =============================================================================

class PatchSegmentationTrainRequest(BaseModel):
    """Patch segmentation training request - aligned with other training endpoints"""
    task_id: str
    architecture: str = "unet"
    backbone: str = "resnet50"
    loss_names: List[str] = ["DiceLoss", "JaccardLoss"]
    loss_weights: List[float] = [0.5, 0.5]
    epochs: int = 100
    lr: float = 0.0001
    batch_size: int = 16
    optimizer: str = "adamw"
    early_stopping_patience: int = 15
    device: Optional[str] = None
    seed: Optional[int] = 42
    num_classes: int = 1


@router.post("/patch_segmentation")
async def train_patch_segmentation(req: PatchSegmentationTrainRequest) -> TrainResponse:
    """
    Patch Segmentation Training.

    Uses ScopedSession pattern - creates short-lived DB sessions for each operation
    to prevent connection pool exhaustion during long-running training.
    The SegmentationTrainer is synchronous, so it runs in a thread pool.
    """
    import asyncio
    import uuid as uuid_mod
    from backend.ai.tasks import SegmentationTrainer

    scoped_session = ScopedSession(req.task_id)
    scoped_logger = ScopedTrainingLogger(req.task_id)

    # Phase 1: Validation - short-lived session
    async with scoped_session.session() as (training_logger, db):
        task = await TrainingTaskRepository.get_by_id(db, req.task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Training task not found: {req.task_id}")

        user_id = task.user_id
        preprocessing_config = task.preprocessing_config or {}

        # Mark task as training
        await TrainingTaskRepository.update_status(db, req.task_id, TaskStatus.TRAINING, progress=50)
        await training_logger.info(
            f"[Training] Starting Patch Segmentation ({req.architecture}/{req.backbone})",
            {"task_type": "patch_segmentation", "architecture": req.architecture,
             "backbone": req.backbone, "epochs": req.epochs, "lr": req.lr}
        )
    # Session closed here - connection released before training starts

    try:
        # Phase 2: Build config and run training in thread pool
        save_dir = str(UPLOADS_DIR / req.task_id / "checkpoints")
        config = {
            "architecture": req.architecture,
            "backbone": req.backbone,
            "loss": {"names": req.loss_names, "weights": req.loss_weights},
            "training": {
                "epochs": req.epochs,
                "lr": req.lr,
                "optimizer": req.optimizer,
                "early_stopping_patience": req.early_stopping_patience,
            },
            "save_dir": save_dir,
        }
        # Merge dataset paths from preprocessing_config (set by gateway pipeline)
        if preprocessing_config.get("segmentation_dataset"):
            config["dataset"] = preprocessing_config["segmentation_dataset"]
        # Always apply num_classes from request (overrides default of 1)
        config.setdefault("dataset", {})["classes"] = req.num_classes

        trainer = SegmentationTrainer(
            task_id=req.task_id,
            uploads_root=UPLOADS_DIR,
            device=req.device,
            batch_size=req.batch_size,
            config=config,
        )

        # Run sync training in thread pool to avoid blocking event loop
        results = await asyncio.to_thread(
            trainer.train_model, req.epochs, req.lr, req.early_stopping_patience
        )

        # Build TrainResponse from results dict
        model_id = str(uuid_mod.uuid4())
        checkpoint_path = str(Path(save_dir) / "best_model.pth")

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

        # Save full training history to metrics.json for analysis module
        # This follows the same pattern as patch_classification's _save_final_metrics
        history = results.get("history", {})
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
            "config": {
                "architecture": req.architecture,
                "backbone": req.backbone,
                "task_id": req.task_id,
            },
        }
        metrics_json_path = Path(save_dir) / "metrics.json"
        metrics_json_path.write_text(json.dumps(metrics_data, ensure_ascii=False, indent=2))

        # Phase 3: Save model - short-lived session
        async with scoped_session.session() as (training_logger, db):
            await TrainedModelRepository.create(db, {
                "model_id": model_id,
                "task_id": req.task_id,
                "user_id": user_id,
                "model_name": f"{req.architecture}+{req.backbone}",
                "model_path": checkpoint_path,
                "config_path": str(Path(checkpoint_path).parent / "config.json"),
                "classes": [],  # segmentation categories stored in config
                "feature_extractor": req.backbone,
                "aggregator": req.architecture,
                "train_metrics": sanitize_for_json({"loss": history.get("train_loss", [])}),
                "val_metrics": sanitize_for_json(results.get("best_val_metrics", {})),
                "is_default": False,
                "is_active": True,
            })
            await training_logger.info("Training completed. Model saved.", {"model_id": model_id})
            await _safe_update_status(db, req.task_id, TaskStatus.COMPLETED, progress=100)

        return result

    except TrainingCancelledException as e:
        await scoped_logger.info(f"Patch Segmentation training cancelled: {e}")
        async with scoped_session.session() as (training_logger, db):
            await _safe_update_status(db, req.task_id, TaskStatus.CANCELLED, error_message=str(e))
        return TrainResponse.cancelled(req.task_id, TaskType.PATCH_SEGMENTATION, message=str(e))

    except Exception as e:
        await handle_training_error_scoped(e, req.task_id, scoped_session, "Patch Segmentation")

    finally:
        await cleanup_training_scoped(req.task_id)
