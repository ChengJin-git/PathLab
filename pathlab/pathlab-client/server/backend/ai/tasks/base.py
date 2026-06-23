"""Base classes for task-specific trainers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from pathlib import Path

from backend.ai.schemas import (
    TrainResponse,
    TrainMetrics,
    FeatureExtractionResponse,
    TaskType,
)
from backend.common.gpu_utils import get_device_string


class BaseTrainer(ABC):
    """
    Abstract base class for task-specific trainers.

    Each trainer is responsible for:
    1. Feature extraction (if applicable)
    2. Model training
    3. Checkpoint saving
    4. Logging and progress tracking

    All Trainer subclasses must return a unified response (TrainResponse/FeatureExtractionResponse).
    """

    # Subclasses must define the task type
    task_type: TaskType = TaskType.WSI_CLASSIFICATION

    def __init__(
        self,
        task_id: str,
        uploads_root: Path,
        device: str | None = None
    ):
        self.task_id = task_id
        self.uploads_root = Path(uploads_root)
        # Auto-select optimal GPU if device not specified
        self.device = device or get_device_string()

    @abstractmethod
    async def extract_features(
        self,
        wsi_ids: List[str],
        extractor_name: str,
        batch_size: int,
        force_recompute: bool,
        logger: Any,
        db: Any,
        hf_token: str = "",
        preprocessing_config: Optional[Dict[str, Any]] = None,
    ) -> FeatureExtractionResponse:
        """
        Extract features for all WSI slides.

        Args:
            wsi_ids: List of WSI IDs to process
            extractor_name: Name of the feature extractor (e.g., "resnet50")
            batch_size: Batch size for feature extraction
            force_recompute: Whether to recompute existing features
            logger: TrainingLogger instance for logging
            db: Database session
            hf_token: HuggingFace token for gated models
            preprocessing_config: Preprocessing config for cache key computation

        Returns:
            FeatureExtractionResponse with extraction results
        """
        pass

    @abstractmethod
    async def train_model(
        self,
        wsi_ids: List[str],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        db: Any,
    ) -> TrainResponse:
        """
        Train the model.

        Args:
            wsi_ids: List of WSI IDs for training
            aggregator_name: Name of the aggregator/model (e.g., "abmil")
            num_classes: Number of output classes
            epochs: Number of training epochs
            lr: Learning rate
            logger: TrainingLogger instance for logging
            db: Database session

        Returns:
            TrainResponse with training results
        """
        pass

    @staticmethod
    def _set_seed(seed: int):
        """Set all random seeds for reproducibility."""
        import random
        import numpy as np
        import torch

        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False

    def _build_train_response(
        self,
        model_id: str,
        checkpoint_path: str,
        loss_history: List[float],
        val_metrics: Optional[Dict[str, float]] = None,
        test_metrics: Optional[Dict[str, float]] = None,
        best_epoch: Optional[int] = None,
        kfold_aggregated: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> TrainResponse:
        """Auxiliary method to build a unified training response."""
        metrics = TrainMetrics(
            loss_history=loss_history,
            val_metrics=val_metrics,
            test_metrics=test_metrics,
            best_epoch=best_epoch,
            kfold_aggregated=kfold_aggregated,
        )
        return TrainResponse.success(
            task_id=self.task_id,
            task_type=self.task_type,
            model_id=model_id,
            checkpoint_path=checkpoint_path,
            metrics=metrics,
        )

    def _build_feature_response(
        self,
        results: List[Dict[str, Any]],
    ) -> FeatureExtractionResponse:
        """Auxiliary method to build a unified feature extraction response."""
        return FeatureExtractionResponse(
            status="success",
            results=results,
        )

