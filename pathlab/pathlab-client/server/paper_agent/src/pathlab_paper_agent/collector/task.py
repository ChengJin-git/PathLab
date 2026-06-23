"""Training task collection."""

from __future__ import annotations

from typing import Any

from .json_utils import as_dict, as_list
from .schemas import (
    CollectorStatus,
    MissingEvidence,
    SourceTaskDescriptor,
    SUPPORTED_TASK_TYPES,
    TaskSummary,
)


def _group_value(task: Any, name: str) -> str | None:
    group = getattr(task, "data_group", None)
    return getattr(group, name, None) if group is not None else None


def missing_task_summary(
    descriptor: SourceTaskDescriptor,
    reason: str = "Training task was not found in PathLab DB.",
) -> TaskSummary:
    return TaskSummary(
        task_id=descriptor.task_id,
        role=descriptor.role,
        label=descriptor.label,
        exists=False,
        status=CollectorStatus.missing,
        missing_evidence=[
            MissingEvidence(
                item="training_task",
                task_id=descriptor.task_id,
                reason=reason,
            )
        ],
    )


def summarize_training_task(task: Any, descriptor: SourceTaskDescriptor) -> TaskSummary:
    task_type = _group_value(task, "task_type")
    missing: list[MissingEvidence] = []
    if getattr(task, "status", None) != "completed":
        missing.append(
            MissingEvidence(
                item="completed_training_task",
                task_id=descriptor.task_id,
                reason=f"Task status is {getattr(task, 'status', None)!r}, not 'completed'.",
            )
        )
    if task_type not in SUPPORTED_TASK_TYPES:
        missing.append(
            MissingEvidence(
                item="supported_task_type",
                task_id=descriptor.task_id,
                reason=f"Unsupported or missing task_type: {task_type!r}.",
            )
        )

    return TaskSummary(
        task_id=getattr(task, "task_id", descriptor.task_id),
        role=descriptor.role,
        label=descriptor.label,
        exists=True,
        status=CollectorStatus.partial if missing else CollectorStatus.ready,
        task_name=getattr(task, "task_name", None),
        task_description=getattr(task, "task_description", None),
        user_id=getattr(task, "user_id", None),
        training_status=getattr(task, "status", None),
        progress=getattr(task, "progress", None),
        group_id=getattr(task, "group_id", None),
        data_type=_group_value(task, "data_type"),
        aggregation_level=_group_value(task, "aggregation_level"),
        task_type=task_type,
        supported_task_type=task_type in SUPPORTED_TASK_TYPES,
        preprocessing_config=as_dict(getattr(task, "preprocessing_config", None)),
        model_config_payload=as_dict(getattr(task, "model_config", None)),
        classes=as_list(getattr(task, "classes", None)),
        created_at=getattr(task, "created_at", None),
        updated_at=getattr(task, "updated_at", None),
        started_at=getattr(task, "started_at", None),
        finished_at=getattr(task, "finished_at", None),
        missing_evidence=missing,
    )
