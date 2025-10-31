"""
Model Service

Manages user-trained models (not built-in models).
Handles model registration, activation, and deletion.
"""

import os
import shutil
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from smartresearch.services.backend.database.models import TrainedModel
from smartresearch.services.backend.database.repositories import TrainedModelRepository


class ModelService:
    """Service for managing user-trained models"""

    @staticmethod
    async def get_model(db: AsyncSession, model_id: str) -> Optional[TrainedModel]:
        """Get a trained model by ID"""
        return await TrainedModelRepository.get_by_id(db, model_id)

    @staticmethod
    async def get_default_model(db: AsyncSession) -> Optional[TrainedModel]:
        """Get the default model for inference"""
        return await TrainedModelRepository.get_default(db)

    @staticmethod
    async def list_active_models(db: AsyncSession) -> List[TrainedModel]:
        """List all active models"""
        return await TrainedModelRepository.get_active_models(db)

    @staticmethod
    async def list_all_models(
        db: AsyncSession,
        limit: int = 100,
        offset: int = 0
    ) -> List[TrainedModel]:
        """List all models (active and inactive)"""
        return await TrainedModelRepository.get_all(db, limit, offset)

    @staticmethod
    async def set_default_model(db: AsyncSession, model_id: str) -> TrainedModel:
        """Set a model as the default for inference"""
        model = await TrainedModelRepository.set_default(db, model_id)
        if not model:
            raise ValueError(f"Model not found: {model_id}")
        return model

    @staticmethod
    async def activate_model(db: AsyncSession, model_id: str) -> TrainedModel:
        """Activate a model"""
        model = await TrainedModelRepository.set_active(db, model_id, True)
        if not model:
            raise ValueError(f"Model not found: {model_id}")
        return model

    @staticmethod
    async def deactivate_model(db: AsyncSession, model_id: str) -> TrainedModel:
        """Deactivate a model"""
        model = await TrainedModelRepository.set_active(db, model_id, False)
        if not model:
            raise ValueError(f"Model not found: {model_id}")
        return model

    @staticmethod
    async def delete_model(db: AsyncSession, model_id: str, delete_files: bool = True) -> bool:
        """
        Delete a trained model
        
        Args:
            db: Database session
            model_id: Model ID to delete
            delete_files: Whether to delete model files from disk
        
        Returns:
            True if deleted successfully
        """
        # Get model info before deletion
        model = await TrainedModelRepository.get_by_id(db, model_id)
        if not model:
            return False

        # Delete from database
        deleted = await TrainedModelRepository.delete(db, model_id)
        
        if deleted and delete_files:
            # Delete model files
            model_dir = os.path.dirname(model.model_path)
            if os.path.exists(model_dir):
                try:
                    shutil.rmtree(model_dir)
                except Exception as e:
                    print(f"Warning: Failed to delete model files at {model_dir}: {e}")
        
        return deleted

    @staticmethod
    async def register_model(
        db: AsyncSession,
        model_data: Dict
    ) -> TrainedModel:
        """
        Register a new trained model
        
        Args:
            db: Database session
            model_data: Model metadata
                {
                    "model_id": str,
                    "task_id": str,
                    "model_name": str,
                    "model_path": str,
                    "config_path": str,
                    "classes": List[str],
                    "feature_extractor": str,
                    "aggregator": str,
                    "train_metrics": Dict,
                    "val_metrics": Dict,
                    "is_default": bool (optional),
                    "is_active": bool (optional)
                }
        
        Returns:
            Created TrainedModel instance
        """
        # Set defaults
        model_data.setdefault("is_default", False)
        model_data.setdefault("is_active", True)
        
        # Create model record
        model = await TrainedModelRepository.create(db, model_data)
        
        return model

    @staticmethod
    def get_builtin_extractors() -> List[Dict]:
        """
        Get list of built-in feature extractors
        
        This queries the built-in model library (not user-trained models)
        """
        try:
            from smartresearch.services.backend.ai.models.lib import EXTRACTORS
            
            extractors = []
            for name, info in EXTRACTORS.registry.items():
                extractors.append({
                    "name": name,
                    "feature_dim": info.get("feature_dim"),
                    "family": info.get("family", "unknown")
                })
            return extractors
        except Exception as e:
            print(f"Warning: Failed to load built-in extractors: {e}")
            # Return default list if built-in library not ready
            return [
                {"name": "resnet50", "feature_dim": 2048, "family": "resnet"},
                {"name": "vit_large", "feature_dim": 1024, "family": "vit"},
            ]

    @staticmethod
    def get_builtin_aggregators() -> List[Dict]:
        """
        Get list of built-in aggregators
        
        This queries the built-in model library (not user-trained models)
        """
        try:
            from smartresearch.services.backend.ai.models.lib import AGGREGATORS
            
            aggregators = []
            for name, info in AGGREGATORS.registry.items():
                aggregators.append({
                    "name": name,
                    "description": info.get("description", "")
                })
            return aggregators
        except Exception as e:
            print(f"Warning: Failed to load built-in aggregators: {e}")
            # Return default list if built-in library not ready
            return [
                {"name": "abmil", "description": "Attention-based MIL"},
                {"name": "mean", "description": "Mean pooling"},
            ]

