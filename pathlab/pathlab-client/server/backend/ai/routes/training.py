"""
Refactored training routes using task-specific trainers and registries.

Unified entry/exit design:
- All training requests use a unified Schema
- All responses return a unified format
- Routed by task_type

Background Task Design:
- Training endpoints return immediately with {"status": "accepted"}
- Actual training runs in background via asyncio.create_task
- Gateway polls database for status updates instead of waiting for HTTP response
- This allows training to run for days without HTTP timeout issues
"""
from __future__ import annotations

import asyncio
import gc
import logging
import traceback
from pathlib import Path
from typing import List, Optional, Dict

import torch
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.database.database import get_db, async_session, AsyncSession
from backend.database.repositories import (
    TrainingTaskRepository,
    TrainedModelRepository,
)
from backend.database.utils.training_logger import TrainingLogger
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

# Track running background tasks to prevent duplicate submissions
_running_training_tasks: Dict[str, asyncio.Task] = {}

router = APIRouter(prefix="/training", tags=["training"])


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
    - "Fold 1: 20, Fold 2: 20, Fold 3: 20, Fold 4: 20, Fold 5: 20"
    """
    # Check if this is k-fold
    fold_keys = sorted([k for k in splits_map.keys() if k.startswith("fold_")])
    if fold_keys:
        parts = []
        for k in fold_keys:
            fold_num = k.replace("fold_", "")
            parts.append(f"Fold {int(fold_num) + 1}: {len(splits_map[k])}")
        return ", ".join(parts)

    # Standard train/val/test split
    parts = []
    for split_name in ["train", "val", "test"]:
        if split_name in splits_map:
            display_name = split_name.capitalize()
            parts.append(f"{display_name}: {len(splits_map[split_name])}")

    return ", ".join(parts) if parts else "No splits"


def cleanup_gpu_memory():
    """Clean up GPU memory after training/inference."""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        logger.info("GPU memory cleaned up")


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
            device="cuda"
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

    except FileNotFoundError as e:
        tb = traceback.format_exc()
        await logger.error("Feature extraction failed - File not found", {"error": str(e), "traceback": tb})
        await _safe_update_status(db, req.task_id, "failed", progress=0, error_message=str(e))
        await db.commit()
        raise HTTPException(status_code=404, detail=f"File not found: {e}")

    except ValueError as e:
        tb = traceback.format_exc()
        await logger.error("Feature extraction failed - Invalid data", {"error": str(e), "traceback": tb})
        await _safe_update_status(db, req.task_id, "failed", progress=0, error_message=str(e))
        await db.commit()
        raise HTTPException(status_code=400, detail=f"Invalid data: {e}")

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Feature extraction failed: {e}\n{tb}")
        await logger.error("Feature extraction failed", {"error": str(e), "traceback": tb})
        await _safe_update_status(db, req.task_id, "failed", progress=0, error_message=str(e))
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cleanup_gpu_memory()
        await logger.close()


# =============================================================================
# WSI Classification Training (Unified Entry)
# =============================================================================

class WSIClassificationTrainRequest(BaseModel):
    """WSI classification training request"""
    task_id: str
    epochs: int = 10
    lr: float = 1e-4
    aggregator: str = "abmil"
    feature_extractor: str = "resnet50"
    optimizer: str = "adam"  # adam, sgd, adamw
    auto_balance: bool = False  # Auto-balance class weights
    early_stopping_patience: int = 10  # Epochs to wait before early stopping


async def _run_wsi_classification_training(
    task_id: str,
    classes: List[str],
    splits_map: Dict[str, List[str]],
    preprocessing_config: Optional[Dict],
    aggregator: str,
    feature_extractor: str,
    epochs: int,
    lr: float,
    optimizer: str,
    auto_balance: bool,
    early_stopping_patience: int,
):
    """
    Background task to run WSI classification training.
    Uses its own database session to avoid connection issues.
    """
    num_classes = len(classes)

    async with async_session() as db:
        training_logger = TrainingLogger(task_id, db)
        try:
            # Log training start with split strategy
            split_strategy_desc = _get_split_strategy_description(splits_map, preprocessing_config)
            splits_count_desc = _format_splits_count(splits_map)
            await training_logger.info(
                f"[Training] Starting WSI Classification ({aggregator.upper()})",
                {"task_type": "wsi_classification", "aggregator": aggregator, "epochs": epochs, "lr": lr, "num_classes": num_classes}
            )
            await training_logger.info(
                f"[Data Split] {split_strategy_desc} | {splits_count_desc}",
                {"strategy": split_strategy_desc, "splits": {k: len(v) for k, v in splits_map.items()}}
            )
            await db.commit()

            # Use WSI Classification Trainer
            trainer = WSIClassificationTrainer(
                task_id=task_id,
                uploads_root=UPLOADS_DIR,
                device="cuda"
            )

            result = await trainer.train_model(
                splits_map=splits_map,
                aggregator_name=aggregator,
                num_classes=num_classes,
                epochs=epochs,
                lr=lr,
                logger=training_logger,
                db=db,
                optimizer=optimizer,
                auto_balance=auto_balance,
                early_stopping_patience=early_stopping_patience,
            )

            # Record model in database
            await TrainedModelRepository.create(db, {
                "model_id": result.model_id,
                "task_id": task_id,
                "model_name": f"{feature_extractor}+{aggregator}",
                "model_path": result.checkpoint_path,
                "config_path": str(Path(result.checkpoint_path).parent / "config.json"),
                "classes": classes,
                "feature_extractor": feature_extractor,
                "aggregator": aggregator,
                "train_metrics": {"loss": result.metrics.loss_history} if result.metrics else {},
                "val_metrics": result.metrics.val_metrics if result.metrics else None,
                "is_default": False,
                "is_active": True,
            })

            await training_logger.info("Training completed. Model saved.", {"model_id": result.model_id})

            # Mark task completed (only if not cancelled)
            await _safe_update_status(db, task_id, "completed", progress=100)
            await db.commit()

        except FileNotFoundError as e:
            tb = traceback.format_exc()
            logger.error(f"WSI Classification training failed - File not found: {e}\n{tb}")
            await training_logger.error("WSI Classification training failed - File not found", {"error": str(e), "traceback": tb})
            await _safe_update_status(db, task_id, "failed", progress=0, error_message=str(e))
            await db.commit()

        except ValueError as e:
            tb = traceback.format_exc()
            logger.error(f"WSI Classification training failed - Invalid data: {e}\n{tb}")
            await training_logger.error("WSI Classification training failed - Invalid data", {"error": str(e), "traceback": tb})
            await _safe_update_status(db, task_id, "failed", progress=0, error_message=str(e))
            await db.commit()

        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"WSI Classification training failed: {e}\n{tb}")
            await training_logger.error("WSI Classification training failed", {"error": str(e), "traceback": tb})
            await _safe_update_status(db, task_id, "failed", progress=0, error_message=str(e))
            await db.commit()

        finally:
            cleanup_gpu_memory()
            await training_logger.close()
            # Remove from running tasks
            _running_training_tasks.pop(task_id, None)


class TrainingAcceptedResponse(BaseModel):
    """Response for accepted training request"""
    status: str = "accepted"
    task_id: str
    message: str = "Training started in background. Poll task status for progress."


@router.post("/wsi_classification")
async def train_wsi_classification(
    req: WSIClassificationTrainRequest,
    db: AsyncSession = Depends(get_db)
) -> TrainingAcceptedResponse:
    """
    WSI Classification Training Unified Entry.

    Starts training in background and returns immediately.
    Poll the task status endpoint to track progress.
    """
    # Check if task is already running
    if req.task_id in _running_training_tasks:
        raise HTTPException(status_code=409, detail=f"Training task {req.task_id} is already running")

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

    # Mark task as training
    await TrainingTaskRepository.update_status(db, req.task_id, "training", progress=66)
    await db.commit()

    # Start background training task
    background_task = asyncio.create_task(
        _run_wsi_classification_training(
            task_id=req.task_id,
            classes=classes,
            splits_map=splits_map,
            preprocessing_config=task.preprocessing_config,
            aggregator=req.aggregator,
            feature_extractor=req.feature_extractor,
            epochs=req.epochs,
            lr=req.lr,
            optimizer=req.optimizer,
            auto_balance=req.auto_balance,
            early_stopping_patience=req.early_stopping_patience,
        )
    )
    _running_training_tasks[req.task_id] = background_task

    return TrainingAcceptedResponse(
        task_id=req.task_id,
        message=f"WSI Classification training started. Epochs: {req.epochs}, Aggregator: {req.aggregator}"
    )



# =============================================================================
# WSI Survival Training
# =============================================================================

class WSISurvivalTrainRequest(BaseModel):
    """WSI survival training request"""
    task_id: str
    epochs: int = 10
    lr: float = 1e-4
    aggregator: str = "abmil"
    feature_extractor: str = "resnet50"
    num_bins: int = 4  # Number of discrete time bins
    optimizer: str = "adam"  # adam, sgd, adamw
    early_stopping_patience: int = 10  # Epochs to wait before early stopping


async def _run_wsi_survival_training(
    task_id: str,
    splits_map: Dict[str, List[str]],
    preprocessing_config: Optional[Dict],
    aggregator: str,
    feature_extractor: str,
    num_bins: int,
    epochs: int,
    lr: float,
    optimizer: str,
    early_stopping_patience: int,
):
    """
    Background task to run WSI survival training.
    Uses its own database session to avoid connection issues.
    """
    async with async_session() as db:
        training_logger = TrainingLogger(task_id, db)
        try:
            # Log training start with split strategy
            split_strategy_desc = _get_split_strategy_description(splits_map, preprocessing_config)
            splits_count_desc = _format_splits_count(splits_map)
            await training_logger.info(
                f"[Training] Starting WSI Survival ({aggregator.upper()})",
                {"task_type": "wsi_survival", "aggregator": aggregator, "epochs": epochs, "lr": lr, "num_bins": num_bins}
            )
            await training_logger.info(
                f"[Data Split] {split_strategy_desc} | {splits_count_desc}",
                {"strategy": split_strategy_desc, "splits": {k: len(v) for k, v in splits_map.items()}}
            )
            await db.commit()

            # Use WSI Survival Trainer
            trainer = WSISurvivalTrainer(
                task_id=task_id,
                uploads_root=UPLOADS_DIR,
                device="cuda"
            )

            # Note: num_classes corresponds to num_bins in survival trainer
            result = await trainer.train_model(
                splits_map=splits_map,
                aggregator_name=aggregator,
                num_classes=num_bins,
                epochs=epochs,
                lr=lr,
                logger=training_logger,
                db=db,
                optimizer=optimizer,
                early_stopping_patience=early_stopping_patience,
            )

            # Record model in database
            await TrainedModelRepository.create(db, {
                "model_id": result.model_id,
                "task_id": task_id,
                "model_name": f"{feature_extractor}+{aggregator}_survival",
                "model_path": result.checkpoint_path,
                "config_path": str(Path(result.checkpoint_path).parent / "config.json"),
                "classes": [f"Bin {i}" for i in range(num_bins)],  # Dummy classes for storage
                "feature_extractor": feature_extractor,
                "aggregator": aggregator,
                "train_metrics": {"loss": result.metrics.loss_history} if result.metrics else {},
                "val_metrics": result.metrics.val_metrics if result.metrics else None,
                "is_default": False,
                "is_active": True,
            })

            await training_logger.info("Training completed. Model saved.", {"model_id": result.model_id})

            # Mark task completed (only if not cancelled)
            await _safe_update_status(db, task_id, "completed", progress=100)
            await db.commit()

        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"WSI Survival training failed: {e}\n{tb}")
            await training_logger.error("WSI Survival training failed", {"error": str(e), "traceback": tb})
            await _safe_update_status(db, task_id, "failed", progress=0, error_message=str(e))
            await db.commit()

        finally:
            cleanup_gpu_memory()
            await training_logger.close()
            # Remove from running tasks
            _running_training_tasks.pop(task_id, None)


@router.post("/wsi_survival")
async def train_wsi_survival(
    req: WSISurvivalTrainRequest,
    db: AsyncSession = Depends(get_db)
) -> TrainingAcceptedResponse:
    """
    WSI Survival Training Unified Entry.

    Starts training in background and returns immediately.
    Poll the task status endpoint to track progress.
    """
    # Check if task is already running
    if req.task_id in _running_training_tasks:
        raise HTTPException(status_code=409, detail=f"Training task {req.task_id} is already running")

    # Validate training task exists
    task = await TrainingTaskRepository.get_by_id(db, req.task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Training task not found: {req.task_id}")

    # Get WSI IDs grouped by split
    splits_map = await TrainingTaskRepository.get_wsi_ids_by_split(db, req.task_id)
    if not splits_map:
        raise HTTPException(status_code=400, detail="No WSI data associated with this task")

    # Mark task as training
    await TrainingTaskRepository.update_status(db, req.task_id, "training", progress=66)
    await db.commit()

    # Start background training task
    background_task = asyncio.create_task(
        _run_wsi_survival_training(
            task_id=req.task_id,
            splits_map=splits_map,
            preprocessing_config=task.preprocessing_config,
            aggregator=req.aggregator,
            feature_extractor=req.feature_extractor,
            num_bins=req.num_bins,
            epochs=req.epochs,
            lr=req.lr,
            optimizer=req.optimizer,
            early_stopping_patience=req.early_stopping_patience,
        )
    )
    _running_training_tasks[req.task_id] = background_task

    return TrainingAcceptedResponse(
        task_id=req.task_id,
        message=f"WSI Survival training started. Epochs: {req.epochs}, Bins: {req.num_bins}"
    )


# =============================================================================
# Patch Classification Training
# =============================================================================

class PatchClassificationTrainRequest(BaseModel):
    """Patch classification training request - aligned with WSI classification style"""
    task_id: str
    epochs: int = 10
    lr: float = 1e-4
    feature_extractor: str = "resnet50"
    batch_size: int = 64
    huggingface_token: Optional[str] = None
    optimizer: str = "adam"  # adam, sgd, adamw
    auto_balance: bool = False  # Auto-balance class weights
    early_stopping_patience: int = 10  # Epochs to wait before early stopping


async def _run_patch_classification_training(
    task_id: str,
    classes: List[str],
    splits_map: Dict[str, List[str]],
    preprocessing_config: Optional[Dict],
    feature_extractor: str,
    batch_size: int,
    huggingface_token: str,
    epochs: int,
    lr: float,
    optimizer: str,
    auto_balance: bool,
    early_stopping_patience: int,
):
    """
    Background task to run patch classification training.
    Uses its own database session to avoid connection issues.
    """
    from backend.ai.tasks import PatchClassificationTrainer

    num_classes = len(classes)

    async with async_session() as db:
        training_logger = TrainingLogger(task_id, db)
        try:
            # Log training start with split strategy
            split_strategy_desc = _get_split_strategy_description(splits_map, preprocessing_config)
            splits_count_desc = _format_splits_count(splits_map)
            await training_logger.info(
                f"[Training] Starting Patch Classification ({feature_extractor.upper()})",
                {"task_type": "patch_classification", "feature_extractor": feature_extractor, "epochs": epochs, "lr": lr, "num_classes": num_classes}
            )
            await training_logger.info(
                f"[Data Split] {split_strategy_desc} | {splits_count_desc}",
                {"strategy": split_strategy_desc, "splits": {k: len(v) for k, v in splits_map.items()}}
            )
            await db.commit()

            # Create trainer (aligned with WSI classification)
            trainer = PatchClassificationTrainer(
                task_id=task_id,
                uploads_root=UPLOADS_DIR,
                device="cuda",
                batch_size=batch_size,
                hf_token=huggingface_token,
            )

            # Train model (aligned with WSI classification's train_model interface)
            result = await trainer.train_model(
                splits_map=splits_map,
                aggregator_name=feature_extractor,  # Reused as extractor name
                num_classes=num_classes,
                epochs=epochs,
                lr=lr,
                logger=training_logger,
                db=db,
                optimizer=optimizer,
                auto_balance=auto_balance,
                early_stopping_patience=early_stopping_patience,
            )

            # Record model in database
            if result.status == "success" and result.model_id:
                await TrainedModelRepository.create(db, {
                    "model_id": result.model_id,
                    "task_id": task_id,
                    "model_name": f"{feature_extractor}+linear_probe",
                    "model_path": result.checkpoint_path or "",
                    "config_path": str(Path(result.checkpoint_path).parent / "config.json") if result.checkpoint_path else "",
                    "classes": classes,
                    "feature_extractor": feature_extractor,
                    "aggregator": "linear_probe",
                    "train_metrics": {"loss": result.metrics.loss_history} if result.metrics else {},
                    "val_metrics": result.metrics.val_metrics if result.metrics else None,
                    "is_default": False,
                    "is_active": True,
                })
                await db.commit()

            # Mark task as completed (only if not cancelled)
            await _safe_update_status(db, task_id, "completed", progress=100)
            await db.commit()

        except FileNotFoundError as e:
            tb = traceback.format_exc()
            logger.error(f"Patch Classification training failed - File not found: {e}\n{tb}")
            await training_logger.error("Patch Classification training failed - File not found", {"error": str(e), "traceback": tb})
            await _safe_update_status(db, task_id, "failed", progress=0, error_message=str(e))
            await db.commit()

        except ValueError as e:
            tb = traceback.format_exc()
            logger.error(f"Patch Classification training failed - Invalid config: {e}\n{tb}")
            await training_logger.error("Patch Classification training failed - Invalid config", {"error": str(e), "traceback": tb})
            await _safe_update_status(db, task_id, "failed", progress=0, error_message=str(e))
            await db.commit()

        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Patch Classification training failed: {e}\n{tb}")
            await training_logger.error("Patch Classification training failed", {"error": str(e), "traceback": tb})
            await _safe_update_status(db, task_id, "failed", progress=0, error_message=str(e))
            await db.commit()

        finally:
            cleanup_gpu_memory()
            await training_logger.close()
            # Remove from running tasks
            _running_training_tasks.pop(task_id, None)


@router.post("/patch_classification")
async def train_patch_classification(
    req: PatchClassificationTrainRequest,
    db: AsyncSession = Depends(get_db)
) -> TrainingAcceptedResponse:
    """
    Patch Classification Training Unified Entry.

    Starts training in background and returns immediately.
    Poll the task status endpoint to track progress.
    """
    # Check if task is already running
    if req.task_id in _running_training_tasks:
        raise HTTPException(status_code=409, detail=f"Training task {req.task_id} is already running")

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

    # Mark task as training
    await TrainingTaskRepository.update_status(db, req.task_id, "training", progress=66)
    await db.commit()

    # Start background training task
    background_task = asyncio.create_task(
        _run_patch_classification_training(
            task_id=req.task_id,
            classes=classes,
            splits_map=splits_map,
            preprocessing_config=task.preprocessing_config,
            feature_extractor=req.feature_extractor,
            batch_size=req.batch_size,
            huggingface_token=req.huggingface_token or "",
            epochs=req.epochs,
            lr=req.lr,
            optimizer=req.optimizer,
            auto_balance=req.auto_balance,
            early_stopping_patience=req.early_stopping_patience,
        )
    )
    _running_training_tasks[req.task_id] = background_task

    return TrainingAcceptedResponse(
        task_id=req.task_id,
        message=f"Patch Classification training started. Epochs: {req.epochs}, Extractor: {req.feature_extractor}"
    )


# =============================================================================
# Patch Segmentation Training
# =============================================================================

class PatchSegmentationTrainRequest(BaseModel):
    """Patch segmentation training request"""
    task_id: str
    config: dict  # Full OmegaConf-compatible config


def _run_patch_segmentation_training_sync(task_id: str, config: dict):
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


async def _run_patch_segmentation_training(task_id: str, config: dict):
    """
    Background task to run patch segmentation training.
    Uses asyncio.to_thread since SegmentationTrainer.train_model is synchronous.
    """
    try:
        # Run sync training in thread pool
        await asyncio.to_thread(_run_patch_segmentation_training_sync, task_id, config)
    finally:
        # Remove from running tasks
        _running_training_tasks.pop(task_id, None)


@router.post("/patch_segmentation")
async def train_patch_segmentation(
    req: PatchSegmentationTrainRequest,
) -> TrainingAcceptedResponse:
    """
    Patch segmentation training endpoint.

    Starts training in background and returns immediately.
    Poll the task status endpoint to track progress.
    """
    # Check if task is already running
    if req.task_id in _running_training_tasks:
        raise HTTPException(status_code=409, detail=f"Training task {req.task_id} is already running")

    # Start background training task
    background_task = asyncio.create_task(
        _run_patch_segmentation_training(
            task_id=req.task_id,
            config=req.config,
        )
    )
    _running_training_tasks[req.task_id] = background_task

    return TrainingAcceptedResponse(
        task_id=req.task_id,
        message="Patch Segmentation training started in background."
    )
