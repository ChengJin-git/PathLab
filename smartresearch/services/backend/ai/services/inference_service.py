"""
Inference Service

Handles AI inference for WSI classification.
Coordinates between model loading, feature extraction, and prediction.
"""

import os
import json
import time
import numpy as np
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from smartresearch.services.backend.database.repositories import (
    WSIRepository,
    AITaskRepository,
    AIResultRepository,
)
from .model_service import ModelService

# Get uploads directory (same as AI service main.py)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
UPLOADS_DIR = os.path.join(ROOT, "uploads")


class InferenceService:
    """Service for AI inference"""

    @staticmethod
    async def run_inference(
        db: AsyncSession,
        wsi_id: str,
        classes: List[str],
        model_id: Optional[str] = None,
        params: Optional[Dict] = None
    ) -> Dict:
        """
        Run inference on a WSI
        
        Args:
            db: Database session
            wsi_id: WSI ID to analyze
            classes: List of class names (from request parameter)
            model_id: Model ID to use (optional, uses default if not provided)
            params: Inference parameters
        
        Returns:
            Inference result dictionary
        """
        params = params or {}
        
        # 1. Get WSI information
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if not wsi:
            raise ValueError(f"WSI not found: {wsi_id}")
        
        wsi_path = wsi.wsi_path
        if not wsi_path or not os.path.exists(wsi_path):
            raise ValueError(f"WSI file not found: {wsi_path}")
        
        # 2. Get model (use default if not specified)
        if model_id:
            model = await ModelService.get_model(db, model_id)
            if not model:
                raise ValueError(f"Model not found: {model_id}")
            if not model.is_active:
                raise ValueError(f"Model is not active: {model_id}")
        else:
            model = await ModelService.get_default_model(db)
            if not model:
                raise ValueError("No default model available. Please train a model first.")
            model_id = model.model_id
        
        # 3. Validate classes
        if len(classes) != len(model.classes):
            raise ValueError(
                f"Classes count mismatch: provided {len(classes)} classes, "
                f"but model expects {len(model.classes)} classes"
            )
        
        # 4. Create task ID
        task_id = f"ai-{wsi_id}-{int(time.time())}"
        
        # 5. Try to load custom inference implementation
        inference_func = InferenceService._load_custom_inference()
        
        if inference_func:
            # Use custom inference implementation
            try:
                # Set default parameters
                params.setdefault("tile_size", 256)
                params.setdefault("stride", 256)
                params.setdefault("feature_model", model.feature_extractor or "resnet50")
                params.setdefault("aggregator", model.aggregator or "abmil")
                params.setdefault("batch_size", 64)
                params.setdefault("device", "cuda")
                params.setdefault("checkpoint", model.model_path)  # User-trained aggregator weights
                
                # Run inference
                inference_result = inference_func(
                    wsi_path=wsi_path,
                    params=params,
                    classes=classes
                )
                
                result = {
                    "task_id": task_id,
                    "wsi_id": wsi_id,
                    "model_id": model_id,
                    "pred": inference_result["pred"],
                    "probs": inference_result["probs"],
                    "params": params,
                    "num_tiles": inference_result.get("num_tiles", 0),
                    "finished_at": int(time.time())
                }
                
                # Save attention weights if available
                attention_weights = inference_result.get("attention_weights")
                if attention_weights is not None:
                    attention_path = await InferenceService._save_attention_weights(
                        wsi_id, task_id, attention_weights
                    )
                    result["attention_path"] = attention_path
                
            except Exception as e:
                # Fallback to stub if inference fails
                print(f"Custom inference failed: {e}, falling back to stub")
                result = InferenceService._stub_classification(
                    task_id, wsi_id, model_id, wsi.label, params
                )
        else:
            # Stub classification: use WSI label from database
            result = InferenceService._stub_classification(
                task_id, wsi_id, model_id, wsi.label, params
            )
        
        # 6. Save result to database
        await InferenceService._save_result_to_db(db, result)
        
        return result

    @staticmethod
    def _load_custom_inference():
        """Load custom inference implementation from models/run_inference.py"""
        inference_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "models"
        )
        impl_path = os.path.join(inference_dir, "run_inference.py")
        
        if not os.path.exists(impl_path):
            return None
        
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("custom_inference", impl_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return getattr(module, "run_inference", None)
        except Exception as e:
            print(f"Failed to load custom inference: {e}")
            return None

    @staticmethod
    def _stub_classification(
        task_id: str,
        wsi_id: str,
        model_id: str,
        label: str,
        params: Optional[Dict]
    ) -> Dict:
        """Stub classification using WSI label"""
        if not label:
            raise ValueError("WSI label missing for stub classification")
        
        return {
            "task_id": task_id,
            "wsi_id": wsi_id,
            "model_id": model_id,
            "pred": label,
            "probs": {label: 1.0},
            "params": params or {},
            "mode": "stub",
            "finished_at": int(time.time())
        }

    @staticmethod
    async def _save_attention_weights(
        wsi_id: str,
        task_id: str,
        attention_weights: np.ndarray
    ) -> str:
        """
        Save attention weights to file

        Returns:
            File path (relative to uploads/)
        """
        # Create directory
        result_dir = os.path.join(UPLOADS_DIR, "ai_results", wsi_id)
        os.makedirs(result_dir, exist_ok=True)

        # Save attention weights
        attention_filename = f"{task_id}_attention.npy"
        attention_path = os.path.join(result_dir, attention_filename)
        np.save(attention_path, attention_weights)

        # Return relative path
        return f"ai_results/{wsi_id}/{attention_filename}"

    @staticmethod
    async def _save_result_to_db(db: AsyncSession, result: Dict):
        """Save inference result to database"""
        # Prepare result data for database
        result_data = {
            "wsi_id": result["wsi_id"],
            "task_id": result["task_id"],
            "pred": result["pred"],
            "probs": result["probs"],
            "extra_metadata": {
                "model_id": result.get("model_id"),
                "num_tiles": result.get("num_tiles", 0),
                "mode": result.get("mode"),
                "attention_path": result.get("attention_path"),
            }
        }
        
        # Save to database
        await AIResultRepository.create(db, result_data)
        await db.commit()

    @staticmethod
    async def get_result(
        db: AsyncSession,
        wsi_id: str,
        include_attention: bool = False
    ) -> Optional[Dict]:
        """
        Get inference result for a WSI
        
        Args:
            db: Database session
            wsi_id: WSI ID
            include_attention: Whether to load attention weights from file
        
        Returns:
            Result dictionary or None if not found
        """
        # Get result from database
        db_result = await AIResultRepository.get_by_wsi_id(db, wsi_id)
        if not db_result:
            return None
        
        # Convert to dict
        result = db_result.to_dict()
        
        # Load attention weights if requested
        if include_attention and result.get("metadata", {}).get("attention_path"):
            attention_path = result["metadata"]["attention_path"]
            full_path = os.path.join("uploads", attention_path)
            
            if os.path.exists(full_path):
                try:
                    attention_weights = np.load(full_path)
                    result["attention_weights"] = attention_weights.tolist()
                except Exception as e:
                    print(f"Failed to load attention weights: {e}")
        
        return result

