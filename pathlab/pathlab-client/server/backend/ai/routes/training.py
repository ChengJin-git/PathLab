"""
Refactored training routes using task-specific trainers and registries.

Unified entry/exit design:
- All training requests use a unified Schema
- All responses return a unified format
- Routed by task_type
"""
from __future__ import annotations

import gc
import logging
import traceback
from pathlib import Path
from typing import List, Optional

import torch
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.database.database import get_db, AsyncSession
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

router = APIRouter(prefix="/training", tags=["training"])


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
        await TrainingTaskRepository.update_status(db, req.task_id, "failed", progress=0, error_message=str(e))
        await db.commit()
        raise HTTPException(status_code=404, detail=f"File not found: {e}")

    except ValueError as e:
        tb = traceback.format_exc()
        await logger.error("Feature extraction failed - Invalid data", {"error": str(e), "traceback": tb})
        await TrainingTaskRepository.update_status(db, req.task_id, "failed", progress=0, error_message=str(e))
        await db.commit()
        raise HTTPException(status_code=400, detail=f"Invalid data: {e}")

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Feature extraction failed: {e}\n{tb}")
        await logger.error("Feature extraction failed", {"error": str(e), "traceback": tb})
        await TrainingTaskRepository.update_status(db, req.task_id, "failed", progress=0, error_message=str(e))
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


@router.post("/wsi_classification")
async def train_wsi_classification(
    req: WSIClassificationTrainRequest,
    db: AsyncSession = Depends(get_db)
) -> TrainResponse:
    """
    WSI Classification Training Unified Entry.

    Returns unified format TrainResponse.
    """
    logger = TrainingLogger(req.task_id, db)
    try:
        # Validate training task exists
        task = await TrainingTaskRepository.get_by_id(db, req.task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Training task not found: {req.task_id}")

        classes: List[str] = task.classes or []
        if not classes:
            raise HTTPException(status_code=400, detail="Training task has no classes")
        num_classes = len(classes)

        # Get WSI IDs for this task
        wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, req.task_id)

        # Mark task as training
        await TrainingTaskRepository.update_status(db, req.task_id, "training", progress=66)
        await db.commit()

        await logger.info(
            f"[Training] Starting {req.aggregator.upper()} training",
            {"epochs": req.epochs, "lr": req.lr, "num_classes": num_classes}
        )
        await db.commit()

        # Use WSI Classification Trainer
        trainer = WSIClassificationTrainer(
            task_id=req.task_id,
            uploads_root=UPLOADS_DIR,
            device="cuda"
        )

        result = await trainer.train_model(
            wsi_ids=wsi_ids,
            aggregator_name=req.aggregator,
            num_classes=num_classes,
            epochs=req.epochs,
            lr=req.lr,
            logger=logger,
            db=db,
        )

        # Record model in database
        await TrainedModelRepository.create(db, {
            "model_id": result.model_id,
            "task_id": req.task_id,
            "model_name": f"{req.feature_extractor}+{req.aggregator}",
            "model_path": result.checkpoint_path,
            "config_path": str(Path(result.checkpoint_path).parent / "config.json"),
            "classes": classes,
            "feature_extractor": req.feature_extractor,
            "aggregator": req.aggregator,
            "train_metrics": {"loss": result.metrics.loss_history} if result.metrics else {},
            "val_metrics": result.metrics.val_metrics if result.metrics else None,
            "is_default": False,
            "is_active": True,
        })

        await logger.info("Training completed. Model saved.", {"model_id": result.model_id})

        # Mark task completed
        await TrainingTaskRepository.update_status(db, req.task_id, "completed", progress=100)
        await db.commit()

        return result

    except FileNotFoundError as e:
        tb = traceback.format_exc()
        logger.error(f"WSI Classification training failed - File not found: {e}\n{tb}")
        await logger.error("WSI Classification training failed - File not found", {"error": str(e), "traceback": tb})
        await TrainingTaskRepository.update_status(db, req.task_id, "failed", progress=0, error_message=str(e))
        await db.commit()
        return TrainResponse.failed(task_id=req.task_id, task_type=TaskType.WSI_CLASSIFICATION, error_message=f"File not found: {e}")

    except ValueError as e:
        tb = traceback.format_exc()
        logger.error(f"WSI Classification training failed - Invalid data: {e}\n{tb}")
        await logger.error("WSI Classification training failed - Invalid data", {"error": str(e), "traceback": tb})
        await TrainingTaskRepository.update_status(db, req.task_id, "failed", progress=0, error_message=str(e))
        await db.commit()
        return TrainResponse.failed(task_id=req.task_id, task_type=TaskType.WSI_CLASSIFICATION, error_message=f"Invalid data: {e}")

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"WSI Classification training failed: {e}\n{tb}")
        await logger.error("WSI Classification training failed", {"error": str(e), "traceback": tb})
        await TrainingTaskRepository.update_status(db, req.task_id, "failed", progress=0, error_message=str(e))
        await db.commit()
        return TrainResponse.failed(task_id=req.task_id, task_type=TaskType.WSI_CLASSIFICATION, error_message=str(e))

    finally:
        cleanup_gpu_memory()
        await logger.close()



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


@router.post("/wsi_survival")
async def train_wsi_survival(
    req: WSISurvivalTrainRequest,
    db: AsyncSession = Depends(get_db)
) -> TrainResponse:
    """
    WSI Survival Training Unified Entry.
    
    Uses standard WSIClassificationTrainer for feature extraction, 
    then uses WSISurvivalTrainer for training discrete time survival model.
    """
    logger = TrainingLogger(req.task_id, db)
    try:
        # Validate training task exists
        task = await TrainingTaskRepository.get_by_id(db, req.task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Training task not found: {req.task_id}")

        # Get WSI IDs for this task
        wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, req.task_id)

        # Mark task as training
        await TrainingTaskRepository.update_status(db, req.task_id, "training", progress=66)
        await db.commit()
        
        # Log start
        await logger.info(
            f"[Training] Starting Survival Analysis ({req.aggregator.upper()})",
            {"epochs": req.epochs, "lr": req.lr, "num_bins": req.num_bins}
        )
        await db.commit()

        # Use WSI Survival Trainer
        trainer = WSISurvivalTrainer(
            task_id=req.task_id,
            uploads_root=UPLOADS_DIR,
            device="cuda"
        )
        
        # Note: num_classes corresponds to num_bins in survival trainer
        result = await trainer.train_model(
            wsi_ids=wsi_ids,
            aggregator_name=req.aggregator,
            num_classes=req.num_bins,
            epochs=req.epochs,
            lr=req.lr,
            logger=logger,
            db=db,
        )

        # Record model in database
        await TrainedModelRepository.create(db, {
            "model_id": result.model_id,
            "task_id": req.task_id,
            "model_name": f"{req.feature_extractor}+{req.aggregator}_survival",
            "model_path": result.checkpoint_path,
            "config_path": str(Path(result.checkpoint_path).parent / "config.json"),
            "classes": [f"Bin {i}" for i in range(req.num_bins)], # Dummy classes for storage
            "feature_extractor": req.feature_extractor,
            "aggregator": req.aggregator,
            "train_metrics": {"loss": result.metrics.loss_history} if result.metrics else {},
            "val_metrics": result.metrics.val_metrics if result.metrics else None,
            "is_default": False,
            "is_active": True,
        })
        
        await logger.info("Training completed. Model saved.", {"model_id": result.model_id})

        # Mark task completed
        await TrainingTaskRepository.update_status(db, req.task_id, "completed", progress=100)
        await db.commit()

        return result

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"WSI Survival training failed: {e}\n{tb}")
        await logger.error("WSI Survival training failed", {"error": str(e), "traceback": tb})
        await TrainingTaskRepository.update_status(db, req.task_id, "failed", progress=0, error_message=str(e))
        await db.commit()
        return TrainResponse.failed(task_id=req.task_id, task_type=TaskType.WSI_SURVIVAL, error_message=str(e))

    finally:
        cleanup_gpu_memory()
        await logger.close()


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


@router.post("/patch_classification")
async def train_patch_classification(
    req: PatchClassificationTrainRequest,
    db: AsyncSession = Depends(get_db)
) -> TrainResponse:
    """
    Patch Classification Training Unified Entry.

    Uses Feature Extractor (frozen) + Linear Probe, consistent with WSI classification style.
    Data is loaded from database (WSI slides with labels and splits).
    Returns unified format TrainResponse.
    """
    from backend.ai.tasks import PatchClassificationTrainer

    training_logger = TrainingLogger(req.task_id, db)

    try:
        # Validate training task exists
        task = await TrainingTaskRepository.get_by_id(db, req.task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Training task not found: {req.task_id}")

        # Get classes from task
        classes: List[str] = task.classes or []
        if not classes:
            raise ValueError("No classes found for training task. Please ensure WSI slides have labels.")

        num_classes = len(classes)

        # Get WSI IDs for this task
        wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, req.task_id)

        # Mark task as training
        await TrainingTaskRepository.update_status(db, req.task_id, "training", progress=66)
        await db.commit()

        await training_logger.info(
            f"[Training] Starting Patch Classification with {req.feature_extractor}",
            {"epochs": req.epochs, "lr": req.lr, "num_classes": num_classes}
        )
        await db.commit()

        # Create trainer (aligned with WSI classification)
        trainer = PatchClassificationTrainer(
            task_id=req.task_id,
            uploads_root=UPLOADS_DIR,
            device="cuda",
            batch_size=req.batch_size,
            hf_token=req.huggingface_token or "",
        )

        # Train model (aligned with WSI classification's train_model interface)
        # aggregator_name is reused as feature_extractor for API compatibility
        result = await trainer.train_model(
            wsi_ids=wsi_ids,
            aggregator_name=req.feature_extractor,  # Reused as extractor name
            num_classes=num_classes,
            epochs=req.epochs,
            lr=req.lr,
            logger=training_logger,
            db=db,
        )

        # Record model in database
        if result.status == "success" and result.model_id:
            await TrainedModelRepository.create(db, {
                "model_id": result.model_id,
                "task_id": req.task_id,
                "model_name": f"{req.feature_extractor}+linear_probe",
                "model_path": result.checkpoint_path or "",
                "config_path": str(Path(result.checkpoint_path).parent / "config.json") if result.checkpoint_path else "",
                "classes": classes,
                "feature_extractor": req.feature_extractor,
                "aggregator": "linear_probe",
                "train_metrics": {"loss": result.metrics.loss_history} if result.metrics else {},
                "val_metrics": result.metrics.val_metrics if result.metrics else None,
                "is_default": False,
                "is_active": True,
            })
            await db.commit()

        # Mark task as completed
        await TrainingTaskRepository.update_status(db, req.task_id, "completed", progress=100)
        await db.commit()

        return result

    except FileNotFoundError as e:
        tb = traceback.format_exc()
        logger.error(f"Patch Classification training failed - File not found: {e}\n{tb}")
        await TrainingTaskRepository.update_status(
            db, req.task_id, "failed", progress=0, error_message=str(e)
        )
        await db.commit()
        return TrainResponse.failed(
            task_id=req.task_id,
            task_type=TaskType.PATCH_CLASSIFICATION,
            error_message=f"File not found: {e}"
        )

    except ValueError as e:
        tb = traceback.format_exc()
        logger.error(f"Patch Classification training failed - Invalid config: {e}\n{tb}")
        await TrainingTaskRepository.update_status(
            db, req.task_id, "failed", progress=0, error_message=str(e)
        )
        await db.commit()
        return TrainResponse.failed(
            task_id=req.task_id,
            task_type=TaskType.PATCH_CLASSIFICATION,
            error_message=f"Invalid config: {e}"
        )

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Patch Classification training failed: {e}\n{tb}")
        await TrainingTaskRepository.update_status(
            db, req.task_id, "failed", progress=0, error_message=str(e)
        )
        await db.commit()
        return TrainResponse.failed(
            task_id=req.task_id,
            task_type=TaskType.PATCH_CLASSIFICATION,
            error_message=str(e)
        )

    finally:
        cleanup_gpu_memory()
        await training_logger.close()


# =============================================================================
# Patch Segmentation Training
# =============================================================================

class PatchSegmentationTrainRequest(BaseModel):
    """Patch segmentation training request"""
    task_id: str
    config: dict  # Full OmegaConf-compatible config


@router.post("/patch_segmentation")
def train_patch_segmentation(
    req: PatchSegmentationTrainRequest,
) -> TrainResponse:
    """
    Patch segmentation training endpoint.

    Note: This is a sync endpoint because SegmentationTrainer uses sync methods.
    Returns unified TrainResponse format.
    """
    from backend.ai.tasks import SegmentationTrainer

    try:
        # Ensure task_id is in config
        config = req.config.copy()
        config["task_id"] = req.task_id

        trainer = SegmentationTrainer(config=config)
        result = trainer.train_model(db=None)  # db not used in current implementation

        return result

    except FileNotFoundError as e:
        tb = traceback.format_exc()
        logger.error(f"Patch Segmentation training failed - File not found: {e}\n{tb}")
        return TrainResponse.failed(task_id=req.task_id, task_type=TaskType.PATCH_SEGMENTATION, error_message=f"File not found: {e}")

    except ValueError as e:
        tb = traceback.format_exc()
        logger.error(f"Patch Segmentation training failed - Invalid config: {e}\n{tb}")
        return TrainResponse.failed(task_id=req.task_id, task_type=TaskType.PATCH_SEGMENTATION, error_message=f"Invalid config: {e}")

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Patch Segmentation training failed: {e}\n{tb}")
        return TrainResponse.failed(task_id=req.task_id, task_type=TaskType.PATCH_SEGMENTATION, error_message=str(e))

    finally:
        cleanup_gpu_memory()
