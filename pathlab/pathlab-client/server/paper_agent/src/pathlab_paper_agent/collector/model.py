"""Trained model summaries."""

from __future__ import annotations

from typing import Any

from .json_utils import as_dict, as_list
from .schemas import CollectorStatus, MissingEvidence, ModelRecord, ModelSummary, SourceTaskDescriptor


def model_to_record(model: Any, source: str = "trained_models") -> ModelRecord:
    return ModelRecord(
        model_id=getattr(model, "model_id", None),
        task_id=getattr(model, "task_id", None),
        model_name=getattr(model, "model_name", None),
        user_id=getattr(model, "user_id", None),
        model_path=getattr(model, "model_path", None),
        config_path=getattr(model, "config_path", None),
        classes=as_list(getattr(model, "classes", None)),
        feature_extractor=getattr(model, "feature_extractor", None),
        aggregator=getattr(model, "aggregator", None),
        train_metrics=as_dict(getattr(model, "train_metrics", None)) or None,
        val_metrics=as_dict(getattr(model, "val_metrics", None)) or None,
        is_default=getattr(model, "is_default", None),
        is_active=getattr(model, "is_active", None),
        created_at=getattr(model, "created_at", None),
        source=source,
    )


def build_model_summary(
    descriptor: SourceTaskDescriptor,
    models: list[Any],
    referenced_source_model: Any | None = None,
) -> ModelSummary:
    records = [model_to_record(model) for model in models]
    missing: list[MissingEvidence] = []
    if not records and referenced_source_model is None:
        missing.append(
            MissingEvidence(
                item="trained_model",
                task_id=descriptor.task_id,
                reason="No trained model row was found for this task.",
            )
        )

    source_record = (
        model_to_record(referenced_source_model, source="external_validation_source_model")
        if referenced_source_model is not None
        else None
    )
    return ModelSummary(
        task_id=descriptor.task_id,
        role=descriptor.role,
        label=descriptor.label,
        status=CollectorStatus.ready if records or source_record else CollectorStatus.missing,
        models=records,
        referenced_source_model=source_record,
        missing_evidence=missing,
    )
