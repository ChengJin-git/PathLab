"""Role handling for paper source tasks."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from ..schemas import PaperConfig
from .schemas import SourceTaskDescriptor


def descriptors_from_config(config: PaperConfig) -> list[SourceTaskDescriptor]:
    return [
        SourceTaskDescriptor(
            task_id=item.task_id,
            role=getattr(item.role, "value", str(item.role)),
            label=item.label,
        )
        for item in config.source_tasks
    ]


def group_by_role(
    descriptors: Iterable[SourceTaskDescriptor],
) -> dict[str, list[SourceTaskDescriptor]]:
    grouped: dict[str, list[SourceTaskDescriptor]] = defaultdict(list)
    for descriptor in descriptors:
        grouped[descriptor.role].append(descriptor)
    return dict(grouped)


def is_external_validation(descriptor: SourceTaskDescriptor) -> bool:
    return descriptor.role == "external_validation" or descriptor.task_id.startswith("extval_")
