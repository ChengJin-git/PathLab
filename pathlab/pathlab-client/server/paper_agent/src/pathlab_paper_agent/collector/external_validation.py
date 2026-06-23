"""External validation collection helpers."""

from __future__ import annotations

from .json_utils import as_dict
from .role_dispatcher import is_external_validation
from .schemas import (
    CollectorStatus,
    ExternalValidationRecord,
    ExternalValidationSummary,
    MissingEvidence,
    SourceTaskDescriptor,
    TaskSummary,
)


def build_external_validation_summary(
    descriptors: list[SourceTaskDescriptor],
    task_summaries: list[TaskSummary],
    analysis_status_by_task: dict[str, CollectorStatus],
) -> ExternalValidationSummary:
    task_by_id = {item.task_id: item for item in task_summaries}
    items: list[ExternalValidationRecord] = []
    for descriptor in descriptors:
        if not is_external_validation(descriptor):
            continue
        task_summary = task_by_id.get(descriptor.task_id)
        model_config = as_dict(task_summary.model_config_payload if task_summary else {})
        missing: list[MissingEvidence] = []
        if task_summary is None or not task_summary.exists:
            missing.append(
                MissingEvidence(
                    item="external_validation_task",
                    task_id=descriptor.task_id,
                    reason="External validation task was not found in PathLab DB.",
                )
            )
        analysis_status = analysis_status_by_task.get(
            descriptor.task_id, CollectorStatus.missing
        )
        if analysis_status == CollectorStatus.missing:
            missing.append(
                MissingEvidence(
                    item="external_validation_analysis",
                    task_id=descriptor.task_id,
                    reason="External validation analysis summary is missing.",
                )
            )
        items.append(
            ExternalValidationRecord(
                task_id=descriptor.task_id,
                label=descriptor.label,
                status=CollectorStatus.partial if missing else CollectorStatus.ready,
                source_model_id=model_config.get("model_id"),
                source_model_task_id=model_config.get("model_task_id"),
                target_dataset_id=model_config.get("dataset_id"),
                total_wsi=model_config.get("total_wsi"),
                analysis_status=analysis_status,
                missing_evidence=missing,
            )
        )

    all_missing = [missing for item in items for missing in item.missing_evidence]
    if not items:
        return ExternalValidationSummary(
            status=CollectorStatus.missing,
            missing_evidence=[
                MissingEvidence(
                    item="external_validation_task",
                    reason="No source task was tagged as external_validation.",
                    severity="warning",
                )
            ],
        )
    return ExternalValidationSummary(
        status=CollectorStatus.partial if all_missing else CollectorStatus.ready,
        items=items,
        missing_evidence=all_missing,
    )
