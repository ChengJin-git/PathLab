"""
Unified Response Schemas for AI Service

Definitions of response schemas for various AI tasks such as training, inference, and feature extraction.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field

from .base import TaskType, TaskStatus


MetricScalarOrList = Union[float, List[float]]


# =============================================================================
# Result Types
# =============================================================================

class ClassificationResult(BaseModel):
    """Classification result - applicable to wsi_classification and patch_classification"""
    pred: str = Field(..., description="Predicted class")
    probs: Dict[str, float] = Field(..., description="Probabilities for each class")
    label: Optional[str] = Field(None, description="True label (if available)")
    attention: Optional[List[float]] = Field(None, description="Attention weights (WSI classification)")
    confidence: Optional[float] = Field(None, description="Confidence score")
    
    @classmethod
    def from_raw(
        cls,
        pred_idx: int,
        probs: List[float],
        classes: List[str],
        attention: Optional[List[float]] = None,
        label: Optional[str] = None,
    ) -> "ClassificationResult":
        """Convert from raw output to unified format"""
        pred = classes[pred_idx] if pred_idx < len(classes) else str(pred_idx)
        probs_dict = {c: float(p) for c, p in zip(classes, probs)}
        confidence = float(probs[pred_idx]) if pred_idx < len(probs) else None
        return cls(
            pred=pred,
            probs=probs_dict,
            label=label,
            attention=attention,
            confidence=confidence,
        )


class SegmentationResult(BaseModel):
    """Segmentation result - applicable to segmentation tasks"""
    mask_path: str = Field(..., description="Segmentation mask file path")
    num_classes: int = Field(..., description="Number of classes")
    class_names: List[str] = Field(default=[], description="List of class names")
    metrics: Optional[Dict[str, Union[float, List[float]]]] = Field(
        None,
        description="Evaluation metrics, including scalar or per-class list metrics",
    )
    
    @classmethod
    def from_raw(
        cls,
        mask_path: str,
        num_classes: int,
        class_names: Optional[List[str]] = None,
        metrics: Optional[Dict[str, Union[float, List[float]]]] = None,
    ) -> "SegmentationResult":
        """Convert from raw output to unified format"""
        return cls(
            mask_path=mask_path,
            num_classes=num_classes,
            class_names=class_names or [],
            metrics=metrics,
        )


# =============================================================================
# Training Metrics
# =============================================================================

class KFoldMetricStats(BaseModel):
    """Statistics for a single metric across k-fold runs"""
    mean: float = Field(..., description="Mean value across folds")
    std: float = Field(..., description="Standard deviation across folds")


class KFoldAggregated(BaseModel):
    """Aggregated metrics from k-fold cross-validation"""
    accuracy: Optional[KFoldMetricStats] = Field(None, description="Accuracy stats")
    loss: Optional[KFoldMetricStats] = Field(None, description="Loss stats")
    auc: Optional[KFoldMetricStats] = Field(None, description="AUC stats")
    c_index: Optional[KFoldMetricStats] = Field(None, description="C-Index stats (for survival analysis)")


class TrainMetrics(BaseModel):
    """Training metrics"""
    loss_history: List[float] = Field(default=[], description="Loss history")
    lr_history: List[float] = Field(default=[], description="Learning rate history")
    val_metrics: Optional[Dict[str, MetricScalarOrList]] = Field(None, description="Validation metrics")
    test_metrics: Optional[Dict[str, MetricScalarOrList]] = Field(None, description="Test metrics")
    best_epoch: Optional[int] = Field(None, description="Best epoch")
    kfold_aggregated: Optional[KFoldAggregated] = Field(None, description="K-Fold aggregated metrics (mean±std)")


class InferenceMetrics(BaseModel):
    """Inference metrics"""
    inference_time: Optional[float] = Field(None, description="Inference time (seconds)")
    num_patches: Optional[int] = Field(None, description="Number of patches")


# =============================================================================
# Unified Responses
# =============================================================================

# Result union type
TaskResult = Union[ClassificationResult, SegmentationResult]


class TrainResponse(BaseModel):
    """Training response"""
    status: str = Field(..., description="Status: success | failed")
    task_id: str = Field(..., description="Task ID")
    task_type: TaskType = Field(..., description="Task type")
    model_id: Optional[str] = Field(None, description="Model ID after training")
    checkpoint_path: Optional[str] = Field(None, description="Checkpoint path")
    metrics: Optional[TrainMetrics] = Field(None, description="Training metrics")
    error_message: Optional[str] = Field(None, description="Error message")
    
    @classmethod
    def success(
        cls,
        task_id: str,
        task_type: TaskType,
        model_id: str,
        checkpoint_path: str,
        metrics: Optional[TrainMetrics] = None,
    ) -> "TrainResponse":
        """Create a successful response"""
        return cls(
            status="success",
            task_id=task_id,
            task_type=task_type,
            model_id=model_id,
            checkpoint_path=checkpoint_path,
            metrics=metrics,
        )
    
    @classmethod
    def failed(
        cls,
        task_id: str,
        task_type: TaskType,
        error_message: str,
    ) -> "TrainResponse":
        """Create a failed response"""
        return cls(
            status=TaskStatus.FAILED,
            task_id=task_id,
            task_type=task_type,
            error_message=error_message,
        )

    @classmethod
    def cancelled(
        cls,
        task_id: str,
        task_type: TaskType,
        message: str = "Training cancelled by user or timeout",
    ) -> "TrainResponse":
        """Create a cancelled response"""
        return cls(
            status=TaskStatus.CANCELLED,
            task_id=task_id,
            task_type=task_type,
            error_message=message,
        )


class InferenceResponse(BaseModel):
    """Inference response"""
    status: str = Field(..., description="Status: success | pending | failed")
    task_type: TaskType = Field(..., description="Task type")
    task_id: Optional[str] = Field(None, description="Task ID for async inference")
    wsi_id: Optional[str] = Field(None, description="WSI ID")
    result: Optional[TaskResult] = Field(None, description="Inference result")
    metrics: Optional[InferenceMetrics] = Field(None, description="Inference metrics")
    message: Optional[str] = Field(None, description="Status message")
    error_message: Optional[str] = Field(None, description="Error message")

    @classmethod
    def pending(
        cls,
        task_type: TaskType,
        task_id: str,
        wsi_id: str,
        message: str = "Inference started",
    ) -> "InferenceResponse":
        """Create a pending response for async inference"""
        return cls(
            status=TaskStatus.PENDING,
            task_type=task_type,
            task_id=task_id,
            wsi_id=wsi_id,
            message=message,
        )

    @classmethod
    def success(
        cls,
        task_type: TaskType,
        wsi_id: str,
        result: TaskResult,
        metrics: Optional[InferenceMetrics] = None,
    ) -> "InferenceResponse":
        """Create a successful response"""
        return cls(
            status="success",
            task_type=task_type,
            wsi_id=wsi_id,
            result=result,
            metrics=metrics,
        )

    @classmethod
    def failed(
        cls,
        task_type: TaskType,
        wsi_id: str,
        error_message: str,
    ) -> "InferenceResponse":
        """Create a failed response"""
        return cls(
            status=TaskStatus.FAILED,
            task_type=task_type,
            wsi_id=wsi_id,
            error_message=error_message,
        )


class FeatureExtractionResponse(BaseModel):
    """Feature extraction response"""
    status: str = Field(..., description="Status: success | failed")
    results: List[Dict[str, Any]] = Field(default=[], description="List of extracted features")
    error_message: Optional[str] = Field(None, description="Error message")
    skipped_wsi_ids: List[str] = Field(
        default=[],
        description="WSI IDs skipped due to insufficient patches (< MIN_PATCHES_THRESHOLD)"
    )

