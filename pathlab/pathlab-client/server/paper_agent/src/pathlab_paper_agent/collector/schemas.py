"""Pydantic schemas for the deterministic PathLab evidence collector."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

SUPPORTED_TASK_TYPES = {
    "wsi_classification",
    "wsi_survival",
    "patch_classification",
    "patch_segmentation",
}


class CollectorStatus(str, Enum):
    ready = "ready"
    partial = "partial"
    missing = "missing"
    error = "error"


class MissingEvidence(BaseModel):
    item: str
    reason: str
    task_id: Optional[str] = None
    severity: str = "blocking"


class SourceTaskDescriptor(BaseModel):
    task_id: str
    role: str = "main"
    label: Optional[str] = None


class TaskSummary(BaseModel):
    task_id: str
    role: str = "main"
    label: Optional[str] = None
    exists: bool = False
    status: CollectorStatus = CollectorStatus.missing
    task_name: Optional[str] = None
    task_description: Optional[str] = None
    user_id: Optional[str] = None
    training_status: Optional[str] = None
    progress: Optional[int] = None
    group_id: Optional[str] = None
    data_type: Optional[str] = None
    aggregation_level: Optional[str] = None
    task_type: Optional[str] = None
    supported_task_type: bool = False
    preprocessing_config: dict[str, Any] = Field(default_factory=dict)
    model_config = ConfigDict(populate_by_name=True)
    model_config_payload: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    classes: list[Any] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)


class NumericSummary(BaseModel):
    count: int = 0
    min: Optional[float] = None
    median: Optional[float] = None
    max: Optional[float] = None


class DatasetCohortSummary(BaseModel):
    dataset_id: Optional[str] = None
    name: Optional[str] = None
    group_id: Optional[str] = None
    data_type: Optional[str] = None
    aggregation_level: Optional[str] = None
    task_type: Optional[str] = None
    source_organ: Optional[str] = None
    is_public: Optional[bool] = None
    wsi_count: int = 0
    case_count: int = 0
    label_distribution: dict[str, int] = Field(default_factory=dict)
    split_distribution: dict[str, int] = Field(default_factory=dict)
    gender_distribution: dict[str, int] = Field(default_factory=dict)
    source_distribution: dict[str, int] = Field(default_factory=dict)
    survival_event_distribution: dict[str, int] = Field(default_factory=dict)
    age: NumericSummary = Field(default_factory=NumericSummary)
    mpp: NumericSummary = Field(default_factory=NumericSummary)
    file_size_bytes_total: int = 0
    vendors: list[str] = Field(default_factory=list)
    magnifications: list[int] = Field(default_factory=list)
    feature_extracted_count: int = 0


class DatasetSummary(BaseModel):
    task_id: str
    role: str = "main"
    label: Optional[str] = None
    status: CollectorStatus = CollectorStatus.missing
    datasets: list[DatasetCohortSummary] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)


class SplitBucket(BaseModel):
    split: str
    wsi_count: int = 0
    case_count: int = 0
    label_distribution: dict[str, int] = Field(default_factory=dict)
    survival_event_distribution: dict[str, int] = Field(default_factory=dict)


class SplitSummary(BaseModel):
    task_id: str
    role: str = "main"
    label: Optional[str] = None
    status: CollectorStatus = CollectorStatus.missing
    buckets: list[SplitBucket] = Field(default_factory=list)
    has_test_split: bool = False
    fold_splits: list[str] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)


class ModelRecord(BaseModel):
    model_id: Optional[str] = None
    task_id: Optional[str] = None
    model_name: Optional[str] = None
    user_id: Optional[str] = None
    model_path: Optional[str] = None
    config_path: Optional[str] = None
    classes: list[Any] = Field(default_factory=list)
    feature_extractor: Optional[str] = None
    aggregator: Optional[str] = None
    train_metrics: Optional[dict[str, Any]] = None
    val_metrics: Optional[dict[str, Any]] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None
    source: str = "trained_models"


class ModelSummary(BaseModel):
    task_id: str
    role: str = "main"
    label: Optional[str] = None
    status: CollectorStatus = CollectorStatus.missing
    models: list[ModelRecord] = Field(default_factory=list)
    referenced_source_model: Optional[ModelRecord] = None
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)


class AnalysisArtifact(BaseModel):
    kind: str
    path: str
    exists: bool = True


class AnalysisRecord(BaseModel):
    analysis_id: str
    analysis_dir: str
    source: str = "filesystem"
    created_at: Optional[datetime] = None
    summary_path: Optional[str] = None
    results_path: Optional[str] = None
    summary: dict[str, Any] = Field(default_factory=dict)
    results_count: Optional[int] = None
    chart_paths: dict[str, str] = Field(default_factory=dict)
    artifacts: list[AnalysisArtifact] = Field(default_factory=list)


class AnalysisSummary(BaseModel):
    task_id: str
    role: str = "main"
    label: Optional[str] = None
    status: CollectorStatus = CollectorStatus.missing
    selection: str = "latest"
    selected_analysis_id: Optional[str] = None
    analyses: list[AnalysisRecord] = Field(default_factory=list)
    db_analysis_runs: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)


class ExternalValidationRecord(BaseModel):
    task_id: str
    role: str = "external_validation"
    label: Optional[str] = None
    status: CollectorStatus = CollectorStatus.missing
    source_model_id: Optional[str] = None
    source_model_task_id: Optional[str] = None
    target_dataset_id: Optional[str] = None
    total_wsi: Optional[int] = None
    analysis_status: CollectorStatus = CollectorStatus.missing
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)


class ExternalValidationSummary(BaseModel):
    status: CollectorStatus = CollectorStatus.missing
    items: list[ExternalValidationRecord] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)


class QualitativeSummary(BaseModel):
    task_id: str
    role: str = "main"
    label: Optional[str] = None
    status: CollectorStatus = CollectorStatus.missing
    ai_result_bundle: Optional[str] = None
    bundle_exists: bool = False
    result_count: int = 0
    available_artifacts: list[str] = Field(default_factory=list)
    chart_artifacts: list[AnalysisArtifact] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)


class CollectorBundle(BaseModel):
    paper_id: str
    mode: str
    status: CollectorStatus = CollectorStatus.missing
    collected_at: datetime
    source_tasks: list[SourceTaskDescriptor] = Field(default_factory=list)
    task_summaries: list[TaskSummary] = Field(default_factory=list)
    dataset_summaries: list[DatasetSummary] = Field(default_factory=list)
    split_summaries: list[SplitSummary] = Field(default_factory=list)
    model_summaries: list[ModelSummary] = Field(default_factory=list)
    analysis_summaries: list[AnalysisSummary] = Field(default_factory=list)
    external_validation_summary: ExternalValidationSummary = Field(
        default_factory=ExternalValidationSummary
    )
    qualitative_summaries: list[QualitativeSummary] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)
    collector_errors: list[str] = Field(default_factory=list)
