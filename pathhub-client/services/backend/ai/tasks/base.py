"""Base classes for task-specific trainers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Any
from pathlib import Path


class BaseTrainer(ABC):
    """
    Abstract base class for task-specific trainers.
    
    Each trainer is responsible for:
    1. Feature extraction (if applicable)
    2. Model training
    3. Checkpoint saving
    4. Logging and progress tracking
    """
    
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
    ) -> List[Dict]:
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
            List of dicts with extraction results (wsi_id, shape, path)
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
    ) -> Dict:
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
            Dict with training results (model_id, checkpoint, history)
        """
        pass

