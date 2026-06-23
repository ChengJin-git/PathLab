"""API routes for AI service.

Unified entry/exit design:
- training.py: Training-related routes (extract_features, train_abmil, wsi_classification, etc.)
- inference.py: Inference-related routes (analyze, etc.)
"""
from .training import router as training_router
from .inference import router as inference_router

__all__ = ["training_router", "inference_router"]

