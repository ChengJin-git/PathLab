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


class BaseTrainer(ABC):
    """
    Abstract base class for task-specific trainers.

    Each trainer is responsible for:
    1. Feature extraction (if applicable)
    2. Model training
    3. Checkpoint saving
    4. Logging and progress tracking

    所有 Trainer 子类必须返回统一格式的响应 (TrainResponse/FeatureExtractionResponse)。
    """

    # 子类需要定义任务类型
    task_type: TaskType = TaskType.WSI_CLASSIFICATION

    def __init__(
        self,
        task_id: str,
        uploads_root: Path,
        device: str | None = None
    ):
        self.task_id = task_id
        self.uploads_root = Path(uploads_root)
        self.device = device or "cuda"

    @abstractmethod
    async def extract_features(
        self,
        wsi_ids: List[str],
        extractor_name: str,
        batch_size: int,
        force_recompute: bool,
        logger: Any,
        db: Any,
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

    def _build_train_response(
        self,
        model_id: str,
        checkpoint_path: str,
        loss_history: List[float],
        val_metrics: Optional[Dict[str, float]] = None,
        test_metrics: Optional[Dict[str, float]] = None,
        best_epoch: Optional[int] = None,
    ) -> TrainResponse:
        """辅助方法：构建统一的训练响应"""
        metrics = TrainMetrics(
            loss_history=loss_history,
            val_metrics=val_metrics,
            test_metrics=test_metrics,
            best_epoch=best_epoch,
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
        """辅助方法：构建统一的特征提取响应"""
        return FeatureExtractionResponse(
            status="success",
            results=results,
        )

