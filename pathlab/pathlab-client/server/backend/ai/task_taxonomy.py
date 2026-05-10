"""Canonical task taxonomy helpers with explicit task axes."""

from __future__ import annotations

from dataclasses import dataclass

from .schemas.base import TaskType

VALID_DATA_TYPES: tuple[str, ...] = ("wsi", "patch")
VALID_AGGREGATION_LEVELS: tuple[str, ...] = ("file", "case")
@dataclass(frozen=True)
class TaskMetadata:
    task_family: str
    data_type: str
    allowed_aggregation_levels: tuple[str, ...]
    label: str

CANONICAL_TASK_IDS: tuple[str, ...] = (
    TaskType.WSI_CLASSIFICATION.value,
    TaskType.PATCH_CLASSIFICATION.value,
    TaskType.WSI_SURVIVAL.value,
    TaskType.PATCH_SEGMENTATION.value,
)

TASK_METADATA_BY_ID: dict[str, TaskMetadata] = {
    TaskType.WSI_CLASSIFICATION.value: TaskMetadata(
        task_family="classification",
        data_type="wsi",
        allowed_aggregation_levels=("file", "case"),
        label="WSI Classification",
    ),
    TaskType.PATCH_CLASSIFICATION.value: TaskMetadata(
        task_family="classification",
        data_type="patch",
        allowed_aggregation_levels=("file",),
        label="Patch Classification",
    ),
    TaskType.WSI_SURVIVAL.value: TaskMetadata(
        task_family="survival",
        data_type="wsi",
        allowed_aggregation_levels=("file", "case"),
        label="WSI Survival",
    ),
    TaskType.PATCH_SEGMENTATION.value: TaskMetadata(
        task_family="segmentation",
        data_type="patch",
        allowed_aggregation_levels=("file",),
        label="Patch Segmentation",
    ),
}

def _normalize_axis(value: str | None, *, name: str) -> str:
    if value is None:
        raise ValueError(f"{name} is required")
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _coerce_task_id(value: str | TaskType) -> str:
    if isinstance(value, TaskType):
        return value.value
    return _normalize_axis(value, name="task_type")


def is_canonical_task_type(task_type: str | TaskType | None) -> bool:
    if task_type is None:
        return False
    try:
        return _coerce_task_id(task_type) in CANONICAL_TASK_IDS
    except ValueError:
        return False


def get_task_metadata(task_id: str | TaskType) -> TaskMetadata:
    canonical = _coerce_task_id(task_id)
    if canonical not in TASK_METADATA_BY_ID:
        raise ValueError(f"unknown canonical task id: {task_id}")
    return TASK_METADATA_BY_ID[canonical]


def _resolve_to_canonical_id(task_type: str | TaskType, data_type: str) -> str:
    task_raw = _coerce_task_id(task_type)
    data = _normalize_axis(data_type, name="data_type")

    if not is_canonical_task_type(task_raw):
        raise ValueError(f"task_type must be one of {CANONICAL_TASK_IDS}, got: {task_raw}")

    metadata = get_task_metadata(task_raw)
    if metadata.data_type != data:
        raise ValueError(
            f"unsupported task/data_type combination: task_family={metadata.task_family}, data_type={data}"
        )
    return task_raw


def validate_task_axes(
    *,
    task_type: str | TaskType,
    data_type: str,
    aggregation_level: str = "file",
) -> None:
    data = _normalize_axis(data_type, name="data_type")
    aggregation = _normalize_axis(aggregation_level, name="aggregation_level")

    if data not in VALID_DATA_TYPES:
        raise ValueError(f"data_type must be one of {VALID_DATA_TYPES}, got: {data}")
    if aggregation not in VALID_AGGREGATION_LEVELS:
        raise ValueError(
            f"aggregation_level must be one of {VALID_AGGREGATION_LEVELS}, got: {aggregation}"
        )

    canonical_id = _resolve_to_canonical_id(task_type=task_type, data_type=data)
    metadata = get_task_metadata(canonical_id)
    allowed_aggregation_levels = metadata.allowed_aggregation_levels
    if aggregation not in allowed_aggregation_levels:
        raise ValueError(
            f"unsupported aggregation_level for task/data_type combination: task_family={metadata.task_family}, data_type={metadata.data_type}, aggregation_level={aggregation}"
        )


def normalize_task_type(
    *,
    task_type: str | TaskType,
    data_type: str | None = None,
    aggregation_level: str = "file",
) -> str:
    task_raw = _coerce_task_id(task_type)
    if not is_canonical_task_type(task_raw):
        raise ValueError(f"task_type must be one of {CANONICAL_TASK_IDS}, got: {task_raw}")

    if data_type is None:
        data = _normalize_axis(get_task_metadata(task_raw).data_type, name="data_type")
    else:
        data = _normalize_axis(data_type, name="data_type")

    canonical_id = _resolve_to_canonical_id(task_type=task_raw, data_type=data)
    validate_task_axes(
        task_type=canonical_id,
        data_type=data,
        aggregation_level=aggregation_level,
    )
    return canonical_id


def get_canonical_id_tuple(
    *,
    task_type: str | TaskType,
    data_type: str | None = None,
    aggregation_level: str = "file",
) -> tuple[str, TaskMetadata]:
    canonical_id = normalize_task_type(
        task_type=task_type,
        data_type=data_type,
        aggregation_level=aggregation_level,
    )
    return canonical_id, get_task_metadata(canonical_id)


def is_classification_task(task_id: str | TaskType) -> bool:
    return get_task_metadata(task_id).task_family == "classification"


def is_survival_task(task_id: str | TaskType) -> bool:
    return get_task_metadata(task_id).task_family == "survival"


def is_segmentation_task(task_id: str | TaskType) -> bool:
    return get_task_metadata(task_id).task_family == "segmentation"


__all__ = [
    "CANONICAL_TASK_IDS",
    "TASK_METADATA_BY_ID",
    "VALID_AGGREGATION_LEVELS",
    "VALID_DATA_TYPES",
    "get_canonical_id_tuple",
    "get_task_metadata",
    "is_canonical_task_type",
    "is_classification_task",
    "is_segmentation_task",
    "is_survival_task",
    "normalize_task_type",
    "validate_task_axes",
]
