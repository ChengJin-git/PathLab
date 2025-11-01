import json
import os
import time
import sys
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, List
from sqlalchemy.ext.asyncio import AsyncSession

# AI service: WSI classification with ABMIL inference
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))  # smartresearch/
sys.path.insert(0, ROOT)

from smartresearch.services.backend.database import get_db
from smartresearch.services.backend.ai.services import (
    InferenceService,
    ModelService,
    FeatureService,
    TrainingService,
)

UPLOADS_DIR = os.path.join(ROOT, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

app = FastAPI(title="SmartResearch AI Service")

# Enable CORS for dev and on-prem SPA
try:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
except Exception:
    pass

class AnalyzeRequest(BaseModel):
    """Request for AI inference"""
    task: str
    wsi_id: str
    classes: List[str]  # Classes from request parameter (required)
    model_id: Optional[str] = None  # Optional: use specific model, otherwise use default
    params: Optional[Dict] = None

@app.get("/health")
def health():
    return {"status": "ok", "service": "ai"}

@app.post("/api/ai/analyze")
async def analyze(req: AnalyzeRequest, db: AsyncSession = Depends(get_db)):
    """
    Analyze a WSI using AI classification.

    Uses InferenceService to:
    1. Load user-trained model (or default model)
    2. Extract features using built-in feature extractor
    3. Run inference using trained aggregator
    4. Save results to database (not files)
    """
    if req.task != "wsi_classification":
        raise HTTPException(status_code=400, detail="Unsupported task")

    try:
        # Run inference using service layer
        result = await InferenceService.run_inference(
            db=db,
            wsi_id=req.wsi_id,
            classes=req.classes,
            model_id=req.model_id,
            params=req.params
        )

        return {
            "task_id": result["task_id"],
            "status": "completed",
            "result": {
                "pred": result["pred"],
                "probs": result["probs"],
                "model_id": result.get("model_id"),
            }
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference failed: {str(e)}")

@app.get("/api/ai/results/{wsi_id}")
async def get_results(
    wsi_id: str,
    include_attention: bool = False,
    db: AsyncSession = Depends(get_db)
):
    """
    Get inference result for a WSI

    Args:
        wsi_id: WSI ID
        include_attention: Whether to load attention weights from file
    """
    try:
        result = await InferenceService.get_result(
            db=db,
            wsi_id=wsi_id,
            include_attention=include_attention
        )

        if not result:
            return {"wsi_id": wsi_id, "pred": None, "probs": None}

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get result: {str(e)}")


# ============================================================================
# Model Management APIs
# ============================================================================

@app.get("/api/ai/models")
async def list_models(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """List user-trained models"""
    try:
        if active_only:
            models = await ModelService.list_active_models(db)
        else:
            models = await ModelService.list_all_models(db)

        return {
            "models": [model.to_dict() for model in models]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list models: {str(e)}")


@app.get("/api/ai/models/{model_id}")
async def get_model(model_id: str, db: AsyncSession = Depends(get_db)):
    """Get model details"""
    try:
        model = await ModelService.get_model(db, model_id)
        if not model:
            raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")

        return model.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get model: {str(e)}")


@app.delete("/api/ai/models/{model_id}")
async def delete_model(
    model_id: str,
    delete_files: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """Delete a user-trained model"""
    try:
        deleted = await ModelService.delete_model(db, model_id, delete_files)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")

        await db.commit()
        return {"message": "Model deleted successfully", "model_id": model_id}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete model: {str(e)}")


@app.put("/api/ai/models/{model_id}/set-default")
async def set_default_model(model_id: str, db: AsyncSession = Depends(get_db)):
    """Set a model as default for inference"""
    try:
        model = await ModelService.set_default_model(db, model_id)
        await db.commit()
        return {"message": "Default model set", "model": model.to_dict()}

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to set default model: {str(e)}")


@app.put("/api/ai/models/{model_id}/activate")
async def activate_model(model_id: str, db: AsyncSession = Depends(get_db)):
    """Activate a model"""
    try:
        model = await ModelService.activate_model(db, model_id)
        await db.commit()
        return {"message": "Model activated", "model": model.to_dict()}

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to activate model: {str(e)}")


@app.put("/api/ai/models/{model_id}/deactivate")
async def deactivate_model(model_id: str, db: AsyncSession = Depends(get_db)):
    """Deactivate a model"""
    try:
        model = await ModelService.deactivate_model(db, model_id)
        await db.commit()
        return {"message": "Model deactivated", "model": model.to_dict()}

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to deactivate model: {str(e)}")


# ============================================================================
# Built-in Model Library APIs (Read-only)
# ============================================================================

@app.get("/api/ai/builtin/extractors")
def get_builtin_extractors():
    """Get list of built-in feature extractors"""
    try:
        extractors = ModelService.get_builtin_extractors()
        return {"extractors": extractors}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get extractors: {str(e)}")


@app.get("/api/ai/builtin/aggregators")
def get_builtin_aggregators():
    """Get list of built-in aggregators"""
    try:
        aggregators = ModelService.get_builtin_aggregators()
        return {"aggregators": aggregators}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get aggregators: {str(e)}")


# ============================================================================
# Training APIs
# ============================================================================

class FeatureExtractionRequest(BaseModel):
    """Request for feature extraction"""
    task_id: str
    wsi_ids: List[str]
    feature_extractor: str = "resnet50"
    batch_size: int = 64
    device: str = "cuda"


class TrainingRequest(BaseModel):
    """Request for model training"""
    task_id: str
    feature_paths: Dict[str, str]  # {wsi_id: feature_path}
    wsi_labels: Dict[str, str]     # {wsi_id: label}
    classes: List[str]
    config: Dict


@app.post("/api/ai/extract_features")
async def extract_features(req: FeatureExtractionRequest):
    """
    Extract features for training

    This is Step 2 of the training pipeline.
    Extracts features from WSI patches using built-in feature extractors.
    """
    try:
        print(f"[AI Service] Starting feature extraction for task {req.task_id}")
        print(f"[AI Service]   - WSI IDs: {req.wsi_ids}")
        print(f"[AI Service]   - Feature extractor: {req.feature_extractor}")
        print(f"[AI Service]   - Batch size: {req.batch_size}")
        print(f"[AI Service]   - Device: {req.device}")

        feature_paths = await FeatureService.extract_features_for_training(
            task_id=req.task_id,
            wsi_ids=req.wsi_ids,
            feature_extractor=req.feature_extractor,
            batch_size=req.batch_size,
            device=req.device
        )

        print(f"[AI Service] ✓ Feature extraction completed: {len(feature_paths)} WSIs")

        return {
            "task_id": req.task_id,
            "feature_paths": feature_paths,
            "num_wsi": len(feature_paths)
        }

    except Exception as e:
        import traceback
        print(f"[AI Service] ✗ Feature extraction failed: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Feature extraction failed: {str(e)}")


@app.post("/api/ai/train")
async def train_model(req: TrainingRequest, db: AsyncSession = Depends(get_db)):
    """
    Train a model

    This is Step 3 of the training pipeline.
    Trains an aggregator model using extracted features.
    """
    try:
        # Train model
        result = await TrainingService.train_model(
            task_id=req.task_id,
            wsi_features=req.feature_paths,
            wsi_labels=req.wsi_labels,
            classes=req.classes,
            config=req.config
        )

        # Register model in database
        model_data = {
            "model_id": result["model_id"],
            "task_id": req.task_id,
            "model_name": f"Model for {req.task_id}",
            "model_path": result["model_path"],
            "config_path": result["config_path"],
            "classes": req.classes,
            "feature_extractor": req.config.get("feature_extractor"),
            "aggregator": req.config.get("aggregator"),
            "train_metrics": result["train_metrics"],
            "val_metrics": result["val_metrics"],
            "is_default": False,
            "is_active": True,
        }

        model = await ModelService.register_model(db, model_data)
        await db.commit()

        return {
            "task_id": req.task_id,
            "model_id": result["model_id"],
            "train_metrics": result["train_metrics"],
            "val_metrics": result["val_metrics"],
        }

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Training failed: {str(e)}")

