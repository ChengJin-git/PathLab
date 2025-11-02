"""
Refactored training routes using task-specific trainers and registries.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from smartresearch.services.backend.database.database import get_db, AsyncSession
from smartresearch.services.backend.database.repositories import (
    TrainingTaskRepository,
    TrainedModelRepository,
)
from smartresearch.services.backend.database.utils.training_logger import TrainingLogger
from smartresearch.services.backend.ai.tasks import WSIClassificationTrainer

# Paths
ROOT = Path(__file__).resolve().parents[4]  # smartresearch/
UPLOADS_DIR = ROOT / "uploads"

router = APIRouter(prefix="/training", tags=["training"])


class FeatureExtractionRequest(BaseModel):
    task_id: str
    wsi_ids: List[str]
    feature_extractor: str = "resnet50"
    batch_size: int = 256
    force_recompute: bool = False


@router.post("/extract_features")
async def extract_features(req: FeatureExtractionRequest, db: AsyncSession = Depends(get_db)):
    """Extract features using WSI Classification Trainer."""
    logger = TrainingLogger(req.task_id, db)
    try:
        # Validate training task exists
        task = await TrainingTaskRepository.get_by_id(db, req.task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Training task not found: {req.task_id}")

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
        )

        await logger.info(f"Feature extraction completed for all {len(req.wsi_ids)} WSI")
        await db.commit()

        return {"status": "success", "results": results}

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        await logger.error(
            "Feature extraction failed",
            {"error": str(e), "traceback": tb}
        )
        await TrainingTaskRepository.update_status(
            db, req.task_id, "failed", progress=0, error_message=str(e)
        )
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        await logger.close()


class TrainABMILRequest(BaseModel):
    task_id: str
    epochs: int = 10
    lr: float = 1e-4


@router.post("/train_abmil")
async def train_abmil_endpoint(req: TrainABMILRequest, db: AsyncSession = Depends(get_db)):
    """Train ABMIL model using WSI Classification Trainer."""
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
            f"[Step 3/3] Starting ABMIL training",
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
            aggregator_name="abmil",
            num_classes=num_classes,
            epochs=req.epochs,
            lr=req.lr,
            logger=logger,
            db=db,
        )

        # Record model in database
        await TrainedModelRepository.create(db, {
            "model_id": result["model_id"],
            "task_id": req.task_id,
            "model_name": "resnet50+abmil",
            "model_path": result["checkpoint"],
            "config_path": str(Path(result["checkpoint"]).parent / "config.json"),
            "classes": classes,
            "feature_extractor": "resnet50",
            "aggregator": "abmil",
            "train_metrics": {"loss": result["history"]["loss"]},
            "val_metrics": None,
            "is_default": False,
            "is_active": True,
        })

        await logger.info("Training completed. Model saved.", {"model_id": result["model_id"], "ckpt": result["checkpoint"]})

        # Mark task completed
        await TrainingTaskRepository.update_status(db, req.task_id, "completed", progress=100)
        await db.commit()

        return {
            "task_id": req.task_id,
            "model_id": result["model_id"],
            "checkpoint": result["checkpoint"],
            "history": result["history"],
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        await logger.error(
            "ABMIL training failed",
            {"error": str(e), "traceback": tb}
        )
        await TrainingTaskRepository.update_status(
            db, req.task_id, "failed", progress=0, error_message=str(e)
        )
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        await logger.close()
