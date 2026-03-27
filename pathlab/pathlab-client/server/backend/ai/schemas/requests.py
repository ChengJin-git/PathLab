"""
Unified Request Schemas for AI Service.

Definitions of request schemas for various AI tasks such as training, inference, and feature extraction.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field

from .base import TaskType, DataLevel


# =============================================================================
# Base Config
# =============================================================================


class BaseTrainConfig(BaseModel):
    """Base training configuration - shared parameters for all task types"""

    epochs: int = Field(default=10, ge=1, description="Number of epochs")
    lr: float = Field(default=1e-4, gt=0, description="Learning rate")
    batch_size: int = Field(default=64, ge=1, description="Batch size")
    device: str = Field(default="cuda", description="Compute device")


# =============================================================================
# Task-Specific Configs
# =============================================================================


class WSIClassificationConfig(BaseTrainConfig):
    """WSI classification task configuration"""

    feature_extractor: str = Field(default="resnet50", description="Feature extractor")
    aggregator: str = Field(default="abmil", description="Aggregator")
    feature_batch_size: int = Field(
        default=64, description="Feature extraction batch size"
    )


class PatchClassificationConfig(BaseTrainConfig):
    """Patch classification task configuration"""

    backbone: str = Field(default="resnet50", description="Backbone network")
    model_type: str = Field(
        default="linear", description="Model type: linear | finetune"
    )
    dropout_p: float = Field(default=0.0, ge=0, le=1, description="Dropout probability")

    # Optimizer
    weight_decay: float = Field(default=0.01, description="Weight decay")
    gradient_clip: float = Field(default=1.0, description="Gradient clip")

    # Scheduler
    scheduler_type: str = Field(default="cosine", description="Learning rate scheduler")


class PatchSegmentationConfig(BaseTrainConfig):
    """Patch segmentation task configuration"""

    batch_size: int = Field(default=8, ge=1, description="Batch size")
    backbone: str = Field(default="dinov2_vitl14", description="Backbone network")
    backbone_out_layers: List[int] = Field(
        default=[8, 11, 14, 17], description="Output layer indices"
    )

    # Loss weights
    diceloss_weight: float = Field(default=1.0, description="Dice loss weight")

    # Eval
    eval_crop_size: int = Field(default=518, description="Evaluation crop size")
    eval_stride: int = Field(default=518, description="Evaluation stride")
    eval_mode: str = Field(
        default="slide", description="Evaluation mode: whole | slide"
    )
    metric_to_save: str = Field(default="mIoU", description="Metric to save")


# =============================================================================
# Unified Request
# =============================================================================

# Config union type
TaskConfig = Union[
    WSIClassificationConfig,
    PatchClassificationConfig,
    PatchSegmentationConfig,
]


class TrainRequest(BaseModel):
    """Unified training request"""

    task_id: str = Field(..., description="Task ID")
    task_type: TaskType = Field(..., description="Task type")
    wsi_ids: List[str] = Field(..., min_length=1, description="List of WSI IDs")
    classes: List[str] = Field(default=[], description="List of classes")
    config: Dict[str, Any] = Field(
        default_factory=dict, description="Task-specific configuration"
    )

    def get_typed_config(self) -> TaskConfig:
        """Return the typed configuration based on task_type"""
        config_map = {
            TaskType.WSI_CLASSIFICATION: WSIClassificationConfig,
            TaskType.PATCH_CLASSIFICATION: PatchClassificationConfig,
            TaskType.WSI_SURVIVAL: PatchSegmentationConfig,  # Reuse
            TaskType.PATCH_SEGMENTATION: PatchSegmentationConfig,
        }
        config_class = config_map.get(self.task_type, BaseTrainConfig)
        return config_class(**self.config)


class InferenceRequest(BaseModel):
    task: str
    wsi_id: str
    classes: List[str]
    model_id: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


class FeatureExtractionRequest(BaseModel):
    task_id: str
    wsi_ids: List[str]
    feature_extractor: str = "resnet50"
    batch_size: int = 64
    force_recompute: bool = False
    huggingface_token: Optional[str] = None
    device: Optional[str] = None


class WSIClassificationTrainRequest(BaseModel):
    task_id: str
    epochs: int = 50
    lr: float = 2e-4
    aggregator: str = "abmil"
    feature_extractor: str = "resnet50"
    optimizer: str = "adam"
    auto_balance: bool = False
    early_stopping_patience: int = 20
    device: Optional[str] = None
    seed: Optional[int] = 42


class WSISurvivalTrainRequest(BaseModel):
    task_id: str
    epochs: int = 30
    lr: float = 0.0002
    aggregator: str = "abmil"
    feature_extractor: str = "resnet50"
    num_bins: int = 4
    optimizer: str = "adam"
    early_stopping_patience: int = 20
    device: Optional[str] = None
    seed: Optional[int] = 42


class PatchClassificationTrainRequest(BaseModel):
    task_id: str
    epochs: int = 50
    lr: float = 0.0002
    feature_extractor: str = "resnet50"
    batch_size: int = 64
    huggingface_token: Optional[str] = None
    classifier: str = "linear"
    optimizer: str = "adam"
    auto_balance: bool = False
    early_stopping_patience: int = 20
    device: Optional[str] = None
    seed: Optional[int] = 42


class PatchSegmentationTrainRequest(BaseModel):
    task_id: str
    architecture: str = "unet"
    backbone: str = "resnet50"
    decoder_type: Optional[str] = None
    loss_names: List[str] = ["DiceLoss", "JaccardLoss"]
    loss_weights: List[float] = [0.5, 0.5]
    epochs: int = 50
    lr: float = 0.0001
    batch_size: int = 8
    optimizer: str = "adamw"
    early_stopping_patience: int = 15
    device: Optional[str] = None
    seed: Optional[int] = 42
    num_classes: int = 1


class SyncInferenceRequest(BaseModel):
    task_id: str
    wsi_id: str
    model_id: str


class WSIClassificationInferRequest(BaseModel):
    wsi_id: str
    model_id: Optional[str] = None
    classes: List[str] = []
