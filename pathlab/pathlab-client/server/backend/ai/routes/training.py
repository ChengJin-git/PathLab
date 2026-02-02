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
import logging
import traceback
from pathlib import Path
from typing import List, Optional, Dict

import torch
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.database.database import get_db, AsyncSession
from backend.database.repositories import (
    TrainingTaskRepository,
    TrainedModelRepository,
)
from backend.database.utils.training_logger import TrainingLogger
from backend.database.utils.json_utils import sanitize_for_json
from backend.ai.tasks import WSIClassificationTrainer, WSISurvivalTrainer
from backend.ai.extractors.registry import get_available_extractors
from backend.ai.schemas import (
    TrainResponse,
    TaskType,
)
from backend.common.config import Config

logger = logging.getLogger("training_routes")

# Paths
UPLOADS_DIR = Config.get_uploads_dir()

# =============================================================================
# Cancellation Mechanism (imported from separate module to avoid circular imports)
# =============================================================================
from backend.ai.cancellation import (
    request_cancellation,
    is_task_cancelled,
    clear_cancellation,
    TrainingCancelledException,
)

# =============================================================================
# Permission Revocation Mechanism
# =============================================================================
from backend.ai.permission_revocation import (
    revoke_task_permission,
    is_permission_revoked,
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
    if task.status == "cancelled":
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


async def handle_training_error(
    e: Exception,
    task_id: str,
    db: AsyncSession,
    training_logger: TrainingLogger,
    operation_name: str = "Training"
) -> None:
    """
    Handle training errors with consistent logging and status updates.

    This helper handles the common error cases (FileNotFoundError, ValueError, generic Exception)
    and should be called from except blocks. It logs the error, updates the task status,
    and raises the appropriate HTTPException.

    TrainingCancelledException and PermissionRevokedException should be handled separately
    by the caller since they require returning a TrainResponse.cancelled()/failed() instead
    of raising an exception.

    Usage:
        try:
            # training logic
        except TrainingCancelledException as e:
            # Handle cancellation specially - return cancelled response
            await training_logger.info(f"Training cancelled: {e}")
            await _safe_update_status(db, task_id, "cancelled", error_message=str(e))
            await db.commit()
            return TrainResponse.cancelled(task_id, task_type, message=str(e))
        except PermissionRevokedException as e:
            # Handle permission revocation - return failed response
            await training_logger.error(f"Permission revoked: {e}")
            await _safe_update_status(db, task_id, "failed", error_message=str(e))
            await db.commit()
            return TrainResponse.failed(task_id, task_type, message=str(e))
        except Exception as e:
            await handle_training_error(e, task_id, db, training_logger, "WSI Classification")
        finally:
            await cleanup_training(task_id, training_logger)

    Args:
        e: The caught exception
        task_id: Training task ID
        db: Database session
        training_logger: Training logger instance
        operation_name: Name of the operation for logging (e.g., "WSI Classification")

    Raises:
        HTTPException: Always raises with appropriate status code (404, 400, or 500)
    """
    tb = traceback.format_exc()

    if isinstance(e, FileNotFoundError):
        logger.error(f"{operation_name} failed - File not found: {e}\n{tb}")
        await training_logger.error(f"{operation_name} failed - File not found", {"error": str(e), "traceback": tb})
        await _safe_update_status(db, task_id, "failed", progress=0, error_message=str(e))
        await db.commit()
        raise HTTPException(status_code=404, detail=f"File not found: {e}")

    elif isinstance(e, ValueError):
        logger.error(f"{operation_name} failed - Invalid data: {e}\n{tb}")
        await training_logger.error(f"{operation_name} failed - Invalid data", {"error": str(e), "traceback": tb})
        await _safe_update_status(db, task_id, "failed", progress=0, error_message=str(e))
        await db.commit()
        raise HTTPException(status_code=400, detail=f"Invalid data: {e}")

    elif isinstance(e, HTTPException):
        # Re-raise HTTP exceptions as-is
        raise e

    else:
        logger.error(f"{operation_name} failed: {e}\n{tb}")
        await training_logger.error(f"{operation_name} failed", {"error": str(e), "traceback": tb})
        await _safe_update_status(db, task_id, "failed", progress=0, error_message=str(e))
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))


async def cleanup_training(task_id: str, training_logger: TrainingLogger) -> None:
    """
    Cleanup resources after training operation (success, failure, or cancellation/revocation).

    Should be called in the finally block of training operations.

    Args:
        task_id: Training task ID for cancellation/revocation cleanup
        training_logger: Training logger to close
    """
    cleanup_gpu_memory()
    clear_cancellation(task_id)
    clear_revocation(task_id)
    await training_logger.close()


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


@router.post("/extract_features")
async def extract_features(req: FeatureExtractionRequest, db: AsyncSession = Depends(get_db)):
    """Extract features using WSI Classification Trainer."""
    logger = TrainingLogger(req.task_id, db)
    try:
        # Validate training task exists
        task = await TrainingTaskRepository.get_by_id(db, req.task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Training task not found: {req.task_id}")

        # Get preprocessing config for cache key calculation from task
        preprocessing_config = task.preprocessing_config or {}

        await logger.info(
            f"[Step 2/3] Starting feature extraction for {len(req.wsi_ids)} WSI",
            {"feature_extractor": req.feature_extractor, "batch_size": req.batch_size}
        )
        await db.commit()

        # Mark task status as extracting
        await TrainingTaskRepository.update_status(db, req.task_id, "extracting", progress=33)
        await db.commit()

        # Use WSI Classification Trainer
        trainer = WSIClassificationTrainer(
            task_id=req.task_id,
            uploads_root=UPLOADS_DIR,
        )

        results = await trainer.extract_features(
            wsi_ids=req.wsi_ids,
            extractor_name=req.feature_extractor,
            batch_size=req.batch_size,
            force_recompute=req.force_recompute,
            logger=logger,
            db=db,
            hf_token=req.huggingface_token,
            preprocessing_config=preprocessing_config,  # Pass for cache key
        )

        await logger.info(f"Feature extraction completed for all {len(req.wsi_ids)} WSI")
        await db.commit()

        return results.model_dump()

    except TrainingCancelledException as e:
        await logger.info(f"Feature extraction cancelled: {e}")
        # Note: status might already be set to cancelled by gateway, but we ensure it here
        await _safe_update_status(db, req.task_id, "cancelled", error_message=str(e))
        await db.commit()
        # Return empty results with error message for feature extraction
        return {"status": "cancelled", "results": [], "error_message": str(e)}

    except Exception as e:
        await handle_training_error(e, req.task_id, db, logger, "Feature extraction")

    finally:
        cleanup_gpu_memory()
        # Note: No clear_cancellation for feature extraction - it doesn't set cancellation flag
        await logger.close()


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
    early_stopping_patience: int = 10  # Epochs to wait before early stopping


@router.post("/wsi_classification")
async def train_wsi_classification(
    req: WSIClassificationTrainRequest,
    db: AsyncSession = Depends(get_db)
) -> TrainResponse:
    """
    WSI Classification Training Unified Entry.

    Runs training synchronously and returns result when complete.
    """
    # Validate training task exists
    task = await TrainingTaskRepository.get_by_id(db, req.task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Training task not found: {req.task_id}")

    classes: List[str] = task.classes or []
    if not classes:
        raise HTTPException(status_code=400, detail="Training task has no classes")

    # Get WSI IDs grouped by split
    splits_map = await TrainingTaskRepository.get_wsi_ids_by_split(db, req.task_id)
    if not splits_map:
        raise HTTPException(status_code=400, detail="No WSI data associated with this task")

    # K-Fold validation: ensure each class has at least k samples
    fold_keys = [k for k in splits_map.keys() if k.startswith("fold_")]
    if fold_keys:
        num_folds = len(fold_keys)
        # Get all WSI with labels for this task
        wsi_with_labels = await TrainingTaskRepository.get_wsi_with_labels(db, req.task_id)

        # Calculate class distribution
        class_distribution: Dict[str, int] = {}
        for wsi in wsi_with_labels:
            label = wsi.get("label")
            if label:
                class_distribution[label] = class_distribution.get(label, 0) + 1

        if len(class_distribution) < 2:
            raise HTTPException(
                status_code=400,
                detail=f"K-Fold cross-validation requires at least 2 classes. Found: {len(class_distribution)} class(es). "
                       f"Please ensure your slides have labels from at least 2 different classes."
            )

        # Check if each class has enough samples
        min_class_name = min(class_distribution, key=class_distribution.get)
        min_class_count = class_distribution[min_class_name]

        if min_class_count < num_folds:
            class_info = ", ".join([f"{label}: {count}" for label, count in sorted(class_distribution.items())])
            raise HTTPException(
                status_code=400,
                detail=f"{num_folds}-Fold cross-validation requires at least {num_folds} samples per class. "
                       f"Class '{min_class_name}' only has {min_class_count} sample(s). "
                       f"Current distribution: [{class_info}]. "
                       f"Please reduce k to {min_class_count} or add more samples."
            )
    else:
        # Random split validation: for 7:1:2 split, need at least 10 samples per class
        # to ensure each class has at least 1 sample in val set (10%)
        wsi_with_labels = await TrainingTaskRepository.get_wsi_with_labels(db, req.task_id)

        class_distribution: Dict[str, int] = {}
        for wsi in wsi_with_labels:
            label = wsi.get("label")
            if label:
                class_distribution[label] = class_distribution.get(label, 0) + 1

        if len(class_distribution) < 2:
            raise HTTPException(
                status_code=400,
                detail=f"Classification training requires at least 2 classes. Found: {len(class_distribution)} class(es). "
                       f"Please ensure your slides have labels from at least 2 different classes."
            )

        min_class_name = min(class_distribution, key=class_distribution.get)
        min_class_count = class_distribution[min_class_name]
        min_required_per_class = 10  # For 7:1:2 split, val is 10%

        if min_class_count < min_required_per_class:
            class_info = ", ".join([f"{label}: {count}" for label, count in sorted(class_distribution.items())])
            raise HTTPException(
                status_code=400,
                detail=f"Random 7:1:2 split requires at least {min_required_per_class} samples per class. "
                       f"Class '{min_class_name}' only has {min_class_count} sample(s). "
                       f"Current distribution: [{class_info}]. "
                       f"Please add more samples or use K-Fold cross-validation with smaller k."
            )

    num_classes = len(classes)
    training_logger = TrainingLogger(req.task_id, db)

    try:
        # Mark task as training
        await TrainingTaskRepository.update_status(db, req.task_id, "training", progress=66)
        await db.commit()

        # Log training start with split strategy
        split_strategy_desc = _get_split_strategy_description(splits_map, task.preprocessing_config)
        splits_count_desc = _format_splits_count(splits_map)
        await training_logger.info(
            f"[Training] Starting WSI Classification ({req.aggregator.upper()})",
            {"task_type": "wsi_classification", "aggregator": req.aggregator, "epochs": req.epochs, "lr": req.lr, "num_classes": num_classes}
        )
        await training_logger.info(
            f"[Data Split] {split_strategy_desc} | {splits_count_desc}",
            {"strategy": split_strategy_desc, "splits": {k: len(v) for k, v in splits_map.items()}}
        )
        await db.commit()

        # Use WSI Classification Trainer
        trainer = WSIClassificationTrainer(
            task_id=req.task_id,
            uploads_root=UPLOADS_DIR,
        )

        result = await trainer.train_model(
            splits_map=splits_map,
            aggregator_name=req.aggregator,
            num_classes=num_classes,
            epochs=req.epochs,
            lr=req.lr,
            logger=training_logger,
            db=db,
            optimizer=req.optimizer,
            auto_balance=req.auto_balance,
            early_stopping_patience=req.early_stopping_patience,
        )

        # Record model in database (inherit user_id from training task)
        # Sanitize metrics to handle nan/inf values that would break JSON serialization
        await TrainedModelRepository.create(db, {
            "model_id": result.model_id,
            "task_id": req.task_id,
            "user_id": task.user_id,  # Inherit owner from training task
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

        # Mark task completed (only if not cancelled)
        await _safe_update_status(db, req.task_id, "completed", progress=100)
        await db.commit()

        return result

    except TrainingCancelledException as e:
        await training_logger.info(f"WSI Classification training cancelled: {e}")
        await _safe_update_status(db, req.task_id, "cancelled", error_message=str(e))
        await db.commit()
        return TrainResponse.cancelled(req.task_id, TaskType.WSI_CLASSIFICATION, message=str(e))

    except Exception as e:
        await handle_training_error(e, req.task_id, db, training_logger, "WSI Classification")

    finally:
        await cleanup_training(req.task_id, training_logger)



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
    early_stopping_patience: int = 10  # Epochs to wait before early stopping


@router.post("/wsi_survival")
async def train_wsi_survival(
    req: WSISurvivalTrainRequest,
    db: AsyncSession = Depends(get_db)
) -> TrainResponse:
    """
    WSI Survival Training Unified Entry.

    Runs training synchronously and returns result when complete.
    """
    # Validate training task exists
    task = await TrainingTaskRepository.get_by_id(db, req.task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Training task not found: {req.task_id}")

    # Get WSI IDs grouped by split
    splits_map = await TrainingTaskRepository.get_wsi_ids_by_split(db, req.task_id)
    if not splits_map:
        raise HTTPException(status_code=400, detail="No WSI data associated with this task")

    training_logger = TrainingLogger(req.task_id, db)

    try:
        # Mark task as training
        await TrainingTaskRepository.update_status(db, req.task_id, "training", progress=66)
        await db.commit()

        # Log training start with split strategy
        split_strategy_desc = _get_split_strategy_description(splits_map, task.preprocessing_config)
        splits_count_desc = _format_splits_count(splits_map)
        await training_logger.info(
            f"[Training] Starting WSI Survival ({req.aggregator.upper()})",
            {"task_type": "wsi_survival", "aggregator": req.aggregator, "epochs": req.epochs, "lr": req.lr, "num_bins": req.num_bins}
        )
        await training_logger.info(
            f"[Data Split] {split_strategy_desc} | {splits_count_desc}",
            {"strategy": split_strategy_desc, "splits": {k: len(v) for k, v in splits_map.items()}}
        )
        await db.commit()

        # Use WSI Survival Trainer
        trainer = WSISurvivalTrainer(
            task_id=req.task_id,
            uploads_root=UPLOADS_DIR,
        )

        # Note: num_classes corresponds to num_bins in survival trainer
        result = await trainer.train_model(
            splits_map=splits_map,
            aggregator_name=req.aggregator,
            num_classes=req.num_bins,
            epochs=req.epochs,
            lr=req.lr,
            logger=training_logger,
            db=db,
            optimizer=req.optimizer,
            early_stopping_patience=req.early_stopping_patience,
        )

        # Record model in database (inherit user_id from training task)
        # Sanitize metrics to handle nan/inf values that would break JSON serialization
        await TrainedModelRepository.create(db, {
            "model_id": result.model_id,
            "task_id": req.task_id,
            "user_id": task.user_id,  # Inherit owner from training task
            "model_name": f"{req.feature_extractor}+{req.aggregator}_survival",
            "model_path": result.checkpoint_path,
            "config_path": str(Path(result.checkpoint_path).parent / "config.json"),
            "classes": [f"Bin {i}" for i in range(req.num_bins)],  # Dummy classes for storage
            "feature_extractor": req.feature_extractor,
            "aggregator": req.aggregator,
            "train_metrics": sanitize_for_json({"loss": result.metrics.loss_history}) if result.metrics else {},
            "val_metrics": sanitize_for_json(result.metrics.val_metrics) if result.metrics else None,
            "is_default": False,
            "is_active": True,
        })

        await training_logger.info("Training completed. Model saved.", {"model_id": result.model_id})

        # Mark task completed (only if not cancelled)
        await _safe_update_status(db, req.task_id, "completed", progress=100)
        await db.commit()

        return result

    except TrainingCancelledException as e:
        await training_logger.info(f"WSI Survival training cancelled: {e}")
        await _safe_update_status(db, req.task_id, "cancelled", error_message=str(e))
        await db.commit()
        return TrainResponse.cancelled(req.task_id, TaskType.WSI_SURVIVAL, message=str(e))

    except Exception as e:
        await handle_training_error(e, req.task_id, db, training_logger, "WSI Survival")

    finally:
        await cleanup_training(req.task_id, training_logger)


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
    optimizer: str = "adam"  # adam, sgd, adamw
    auto_balance: bool = False  # Auto-balance class weights
    early_stopping_patience: int = 10  # Epochs to wait before early stopping


@router.post("/patch_classification")
async def train_patch_classification(
    req: PatchClassificationTrainRequest,
    db: AsyncSession = Depends(get_db)
) -> TrainResponse:
    """
    Patch Classification Training Unified Entry.

    Runs training synchronously and returns result when complete.
    """
    from backend.ai.tasks import PatchClassificationTrainer

    # Validate training task exists
    task = await TrainingTaskRepository.get_by_id(db, req.task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Training task not found: {req.task_id}")

    # Get classes from task
    classes: List[str] = task.classes or []
    if not classes:
        raise HTTPException(status_code=400, detail="No classes found for training task. Please ensure WSI slides have labels.")

    # Get WSI IDs grouped by split
    splits_map = await TrainingTaskRepository.get_wsi_ids_by_split(db, req.task_id)
    if not splits_map:
        raise HTTPException(status_code=400, detail="No data associated with this task")

    num_classes = len(classes)
    training_logger = TrainingLogger(req.task_id, db)

    try:
        # Mark task as training
        await TrainingTaskRepository.update_status(db, req.task_id, "training", progress=66)
        await db.commit()

        # Log training start with split strategy
        split_strategy_desc = _get_split_strategy_description(splits_map, task.preprocessing_config)
        splits_count_desc = _format_splits_count(splits_map)
        await training_logger.info(
            f"[Training] Starting Patch Classification ({req.feature_extractor.upper()})",
            {"task_type": "patch_classification", "feature_extractor": req.feature_extractor, "epochs": req.epochs, "lr": req.lr, "num_classes": num_classes}
        )
        await training_logger.info(
            f"[Data Split] {split_strategy_desc} | {splits_count_desc}",
            {"strategy": split_strategy_desc, "splits": {k: len(v) for k, v in splits_map.items()}}
        )
        await db.commit()

        # Create trainer (aligned with WSI classification)
        trainer = PatchClassificationTrainer(
            task_id=req.task_id,
            uploads_root=UPLOADS_DIR,
            batch_size=req.batch_size,
            hf_token=req.huggingface_token,
        )

        # Train model (aligned with WSI classification's train_model interface)
        result = await trainer.train_model(
            splits_map=splits_map,
            aggregator_name=req.feature_extractor,  # Reused as extractor name
            num_classes=num_classes,
            epochs=req.epochs,
            lr=req.lr,
            logger=training_logger,
            db=db,
            optimizer=req.optimizer,
            auto_balance=req.auto_balance,
            early_stopping_patience=req.early_stopping_patience,
        )

        # Record model in database (inherit user_id from training task)
        # Sanitize metrics to handle nan/inf values that would break JSON serialization
        if result.status == "success" and result.model_id:
            await TrainedModelRepository.create(db, {
                "model_id": result.model_id,
                "task_id": req.task_id,
                "user_id": task.user_id,  # Inherit owner from training task
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
            await db.commit()

        # Mark task as completed (only if not cancelled)
        await _safe_update_status(db, req.task_id, "completed", progress=100)
        await db.commit()

        return result

    except TrainingCancelledException as e:
        await training_logger.info(f"Patch Classification training cancelled: {e}")
        await _safe_update_status(db, req.task_id, "cancelled", error_message=str(e))
        await db.commit()
        return TrainResponse.cancelled(req.task_id, TaskType.PATCH_CLASSIFICATION, message=str(e))

    except Exception as e:
        await handle_training_error(e, req.task_id, db, training_logger, "Patch Classification")

    finally:
        await cleanup_training(req.task_id, training_logger)


# =============================================================================
# Patch Segmentation Training
# =============================================================================

class PatchSegmentationTrainRequest(BaseModel):
    """Patch segmentation training request"""
    task_id: str
    config: dict  # Full OmegaConf-compatible config


def _run_patch_segmentation_training_sync(task_id: str, config: dict) -> TrainResponse:
    """
    Synchronous function to run patch segmentation training.
    Called from a thread pool to avoid blocking the event loop.
    """
    from backend.ai.tasks import SegmentationTrainer

    try:
        # Ensure task_id is in config
        config = config.copy()
        config["task_id"] = task_id

        trainer = SegmentationTrainer(config=config)
        result = trainer.train_model(db=None)  # db not used in current implementation

        return result

    except TrainingCancelledException as e:
        # Note: sync wrapper, use standard logger
        logger.info(f"Patch Segmentation training cancelled: {e}")
        return TrainResponse.cancelled(task_id, TaskType.PATCH_SEGMENTATION, message=str(e))

    except FileNotFoundError as e:
        tb = traceback.format_exc()
        logger.error(f"Patch Segmentation training failed - File not found: {e}\n{tb}")
        return TrainResponse.failed(task_id=task_id, task_type=TaskType.PATCH_SEGMENTATION, error_message=f"File not found: {e}")

    except ValueError as e:
        tb = traceback.format_exc()
        logger.error(f"Patch Segmentation training failed - Invalid config: {e}\n{tb}")
        return TrainResponse.failed(task_id=task_id, task_type=TaskType.PATCH_SEGMENTATION, error_message=f"Invalid config: {e}")

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Patch Segmentation training failed: {e}\n{tb}")
        return TrainResponse.failed(task_id=task_id, task_type=TaskType.PATCH_SEGMENTATION, error_message=str(e))

    finally:
        cleanup_gpu_memory()
        clear_cancellation(task_id)


@router.post("/patch_segmentation")
async def train_patch_segmentation(
    req: PatchSegmentationTrainRequest,
) -> TrainResponse:
    """
    Patch segmentation training endpoint.

    Runs training synchronously (via thread pool) and returns result when complete.
    """
    import asyncio
    # Run sync training in thread pool to avoid blocking event loop
    result = await asyncio.to_thread(_run_patch_segmentation_training_sync, req.task_id, req.config)
    return result
