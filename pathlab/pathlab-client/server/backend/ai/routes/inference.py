"""
WSI Inference Routes - Handles model inference requests.
"""
from __future__ import annotations

import json
import uuid
import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Any

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
from backend.ai.utils.dataset import build_dataloader
from backend.ai.tasks.wsi_classification.trainer import WSIClassificationTrainer
from backend.common.config import Config

# Paths
UPLOADS_DIR = Config.get_uploads_dir()

router = APIRouter(tags=["inference"])


class InferenceRequest(BaseModel):
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
        classes=req.classes,
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
    classes: List[str],
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
                extractor = get_extractor("resnet50", pretrained=True).to(device).eval()
                
                feats = await trainer._extract_wsi_features(
                    extractor=extractor,
                    wsi_path=wsi.wsi_path,
                    coords_h5=str(coords_h5),
                    batch_size=256
                )
                
                # Save shared features (not tasked-scoped, but global for WSI)
                # Note: The trainer saves to task/features, here we save to global/features for reuse?
                # For now let's stick to the path we checked above
                torch.save(feats.cpu(), feat_path)
            
            # Load features
            features = torch.load(feat_path, map_location=device)
            
            # --- Step 2: Load Model ---
            await AITaskRepository.update_status(db, task_id, "running", progress=50)
            
            model_record = await TrainedModelRepository.get_by_id(db, model_id)
            checkpoint = torch.load(model_record.model_path, map_location=device)
            
            # Initialize Aggregator
            aggregator = get_aggregator(
                model_record.aggregator or "abmil",
                in_dim=checkpoint["in_dim"],
                num_classes=checkpoint["num_classes"]
            ).to(device)
            aggregator.load_state_dict(checkpoint["state_dict"])
            aggregator.eval()
            
            # --- Step 3: Inference ---
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
            
            # --- Step 4: Save Results ---
            result_data = {
                "wsi_id": wsi_id,
                "task_id": task_id,
                "pred": pred_label,
                "probs": probs_dict,
                "extra_metadata": {
                    "model_id": model_id,
                    "model_name": model_record.model_name
                }
            }
            
            # Save to AIResult
            await AIResultRepository.create(db, result_data)
            
            # Mark task complete
            await AITaskRepository.update_status(db, task_id, "completed", progress=100)
            await db.commit()
            
        except Exception as e:
            import traceback
            logger.error(f"Inference failed: {e}")
            await AITaskRepository.update_status(
                db, task_id, "failed", 
                progress=0, 
                error_message=str(e)
            )
            await db.commit()
        finally:
            await db.close()
            # Stop the async generator
            break
