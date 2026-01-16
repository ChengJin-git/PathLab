"""
WSI Inference Routes - Handles model inference requests

Unified entry/exit design:
- All inference requests use a unified schema
- All responses return a unified format
- Routed by task_type
"""
from __future__ import annotations

import uuid
import logging
import traceback
from typing import List, Dict, Optional

import torch
import torch.nn.functional as F
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.database import get_db
from backend.database.repositories import (
    WSIRepository,
    AITaskRepository,
    TrainedModelRepository,
    AIResultRepository,
)
from backend.ai.extractors import get_extractor
from backend.ai.aggregators import get_aggregator
from backend.ai.tasks.wsi_classification.trainer import WSIClassificationTrainer
from backend.ai.schemas import (
    InferenceResponse,
    TaskType,
)
from backend.common.config import Config

logger = logging.getLogger("inference_routes")

# Paths
UPLOADS_DIR = Config.get_uploads_dir()

router = APIRouter(tags=["inference"])


# =============================================================================
# Inference Request Models (backward compatible)
# =============================================================================

class InferenceRequest(BaseModel):
    """Inference request - backward compatible"""
    task: str  # "wsi_classification"
    wsi_id: str
    classes: List[str]
    model_id: Optional[str] = None
    params: Optional[Dict] = None


@router.post("/analyze")
async def analyze_wsi(
    req: InferenceRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Start asynchronous WSI inference task.
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
             raise HTTPException(status_code=400, detail="No trained model available. Please train a model first.")

    # 3. Create Task ID & Record
    task_id = f"inf_{uuid.uuid4().hex[:16]}"
    
    # 4. Start Background Task
    background_tasks.add_task(
        run_inference_pipeline,
        task_id=task_id,
        wsi_id=req.wsi_id,
        model_id=model.model_id,
        device="cuda" if torch.cuda.is_available() else "cpu"
    )

    return {
        "task_id": task_id,
        "status": "pending", 
        "message": "Inference started successfully"
    }


async def run_inference_pipeline(
    task_id: str,
    wsi_id: str,
    model_id: str,
    device: str
):
    """
    Background inference pipeline:
    1. Extract features (if needed)
    2. Load model
    3. Run inference
    4. Save results
    """
    # Create a new DB session for the background task
    async for db in get_db():
        try:
            # Update task status to running
            # Note: The Gateway creates the AITask record, so we wait briefly to ensure it exists
            # or we accept that AITask creation race condition might happen.
            # Ideally, we should update status here.
            await AITaskRepository.update_status(db, task_id, "running", progress=0)
            await db.commit()

            # --- Step 1: Feature Extraction ---
            # Check if features exist
            features_dir = UPLOADS_DIR / "features"
            features_dir.mkdir(parents=True, exist_ok=True)
            feat_path = features_dir / f"{wsi_id}.pt"
            
            # --- Step 2: Load Model (need to know extractor first) ---
            await AITaskRepository.update_status(db, task_id, "running", progress=30)

            model_record = await TrainedModelRepository.get_by_id(db, model_id)
            if not model_record:
                raise ValueError(f"Model not found: {model_id}")

            # Get the extractor used during training
            extractor_name = model_record.feature_extractor or "resnet50"

            # Check if features exist for this specific extractor
            # Features are extractor-specific, so we include extractor name in path
            feat_path = features_dir / f"{wsi_id}_{extractor_name}.pt"

            if not feat_path.exists():
                await AITaskRepository.update_status(db, task_id, "running", progress=20)

                # Check coordinates
                coords_h5 = UPLOADS_DIR / "coordinates" / f"{wsi_id}_coords.h5"
                if not coords_h5.exists():
                     raise FileNotFoundError(f"Coordinates not found for {wsi_id}. Please run preprocessing first.")

                # Get WSI path
                wsi = await WSIRepository.get_by_id(db, wsi_id)

                # Use WSIClassificationTrainer's logic (reusing code)
                # We instantiate a temporary trainer just to access the extraction logic
                # Ideally this should be refactored into a standalone functional utility
                trainer = WSIClassificationTrainer(task_id, UPLOADS_DIR, device)
                extractor = get_extractor(extractor_name, pretrained=True).to(device).eval()

                feats = await trainer._extract_wsi_features(
                    extractor=extractor,
                    wsi_path=wsi.wsi_path,
                    coords_h5=str(coords_h5),
                    batch_size=64  # Default batch size
                )

                # Save features with extractor name in filename for reuse
                torch.save(feats.cpu(), feat_path)
                logger.info(f"Saved features for {wsi_id} using {extractor_name} to {feat_path}")
            
            # Load features
            features = torch.load(feat_path, map_location=device)

            # --- Step 3: Load Model Checkpoint ---
            await AITaskRepository.update_status(db, task_id, "running", progress=50)

            checkpoint = torch.load(model_record.model_path, map_location=device)
            
            # Initialize Aggregator
            aggregator = get_aggregator(
                model_record.aggregator or "abmil",
                in_dim=checkpoint["in_dim"],
                num_classes=checkpoint["num_classes"]
            ).to(device)
            aggregator.load_state_dict(checkpoint["state_dict"])
            aggregator.eval()

            # --- Step 4: Inference ---
            await AITaskRepository.update_status(db, task_id, "running", progress=80)

            with torch.inference_mode():
                logits, attention = aggregator(features)
                probs = F.softmax(logits, dim=1).squeeze().cpu().numpy()

            # Get class labels
            # The model was trained with specific classes stored in model_record.classes
            trained_classes = model_record.classes

            # Map probabilities to class names
            probs_dict = {
                cls: float(prob)
                for cls, prob in zip(trained_classes, probs.flatten())
            }

            # Get prediction (max prob)
            pred_idx = probs.argmax()
            pred_label = trained_classes[pred_idx]

            # --- Step 5: Save Attention for Heatmap ---
            attention_path = None
            if attention is not None:
                import numpy as np
                # Save attention weights to file
                ai_results_dir = UPLOADS_DIR / "ai_results" / wsi_id
                ai_results_dir.mkdir(parents=True, exist_ok=True)
                attention_file = ai_results_dir / f"{task_id}_attention.npy"
                attention_np = attention.cpu().numpy()
                np.save(attention_file, attention_np)
                attention_path = str(attention_file)
                logger.info(f"Saved attention weights ({len(attention_np)} patches) to {attention_path}")

            # --- Step 6: Save Results ---
            result_data = {
                "wsi_id": wsi_id,
                "task_id": task_id,
                "pred": pred_label,
                "probs": probs_dict,
                "extra_metadata": {
                    "model_id": model_id,
                    "model_name": model_record.model_name,
                    "attention_path": attention_path,
                }
            }

            # Save to AIResult
            await AIResultRepository.create(db, result_data)
            
            # Mark task complete
            await AITaskRepository.update_status(db, task_id, "completed", progress=100)
            await db.commit()
            
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Inference failed: {e}\n{tb}")
            await AITaskRepository.update_status(
                db, task_id, "failed",
                progress=0,
                error_message=str(e)
            )
            await db.commit()
        # Note: db session is automatically closed by get_db() context manager
        # The async for loop naturally ends after one iteration since we don't use 'continue'


# =============================================================================
# WSI Classification Inference (Unified Entry)
# =============================================================================

class WSIClassificationInferRequest(BaseModel):
    """WSI classification inference request"""
    wsi_id: str
    model_id: Optional[str] = None
    classes: List[str] = []


@router.post("/wsi_classification")
async def infer_wsi_classification(
    req: WSIClassificationInferRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
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
        device="cuda" if torch.cuda.is_available() else "cpu"
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
