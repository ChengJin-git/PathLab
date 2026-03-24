"""
Unified AI Service Schemas

The definitions for requests and responses used in the AI service.
All trainers and routes should use these schemas for input/output normalization.
"""

from .base import TaskType, DataLevel, TaskStatus
from .requests import (
    BaseTrainConfig,
    TrainRequest,
    InferenceRequest,
    FeatureExtractionRequest,
    WSIClassificationTrainRequest,
    WSISurvivalTrainRequest,
    PatchClassificationTrainRequest,
    PatchSegmentationTrainRequest,
    SyncInferenceRequest,
    WSIClassificationInferRequest,
    WSIClassificationConfig,
    PatchClassificationConfig,
    PatchSegmentationConfig,
)
from .responses import (
    TrainResponse,
    InferenceResponse,
    FeatureExtractionResponse,
    ClassificationResult,
    SegmentationResult,
    TrainMetrics,
    InferenceMetrics,
)

__all__ = [
    # Base
    "TaskType",
    "DataLevel",
    "TaskStatus",
    # Requests
    "BaseTrainConfig",
    "TrainRequest",
    "InferenceRequest",
    "FeatureExtractionRequest",
    "WSIClassificationTrainRequest",
    "WSISurvivalTrainRequest",
    "PatchClassificationTrainRequest",
    "PatchSegmentationTrainRequest",
    "SyncInferenceRequest",
    "WSIClassificationInferRequest",
    "WSIClassificationConfig",
    "PatchClassificationConfig",
    "PatchSegmentationConfig",
    # Responses
    "TrainResponse",
    "InferenceResponse",
    "FeatureExtractionResponse",
    "ClassificationResult",
    "SegmentationResult",
    "TrainMetrics",
    "InferenceMetrics",
]
