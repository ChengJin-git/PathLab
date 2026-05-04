"""Dataset and cohort collection helpers."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Any, Iterable

from .schemas import (
    CollectorStatus,
    DatasetCohortSummary,
    DatasetSummary,
    MissingEvidence,
    NumericSummary,
    SourceTaskDescriptor,
)


@dataclass(frozen=True)
class SlideRecord:
    wsi_id: str
    split: str | None = None
    dataset_id: str | None = None
    dataset_name: str | None = None
    group_id: str | None = None
    data_type: str | None = None
    aggregation_level: str | None = None
    task_type: str | None = None
    source_organ: str | None = None
    is_public: bool | None = None
    case_id: str | None = None
    label: str | None = None
    age: int | None = None
    gender: str | None = None
    source: str | None = None
    event_time: float | None = None
    event_status: int | None = None
    mpp: float | None = None
    vendor: str | None = None
    magnification: int | None = None
    file_size: int | None = None
    feature_extracted: bool = False


def _distribution(values: Iterable[Any]) -> dict[str, int]:
    counter = Counter(str(v) for v in values if v not in (None, ""))
    return dict(sorted(counter.items()))


def _numeric(values: Iterable[Any]) -> NumericSummary:
    numbers = sorted(float(v) for v in values if v is not None)
    if not numbers:
        return NumericSummary()
    return NumericSummary(
        count=len(numbers),
        min=numbers[0],
        median=float(median(numbers)),
        max=numbers[-1],
    )


def build_dataset_summary(
    descriptor: SourceTaskDescriptor,
    slides: list[SlideRecord],
) -> DatasetSummary:
    if not slides:
        return DatasetSummary(
            task_id=descriptor.task_id,
            role=descriptor.role,
            label=descriptor.label,
            status=CollectorStatus.missing,
            missing_evidence=[
                MissingEvidence(
                    item="dataset_wsi_slides",
                    task_id=descriptor.task_id,
                    reason="No WSI/patch records could be resolved for this task.",
                )
            ],
        )

    by_dataset: dict[str | None, list[SlideRecord]] = defaultdict(list)
    for slide in slides:
        by_dataset[slide.dataset_id].append(slide)

    cohorts: list[DatasetCohortSummary] = []
    for dataset_id, dataset_slides in sorted(by_dataset.items(), key=lambda kv: str(kv[0])):
        first = dataset_slides[0]
        case_ids = {slide.case_id or slide.wsi_id for slide in dataset_slides}
        cohorts.append(
            DatasetCohortSummary(
                dataset_id=dataset_id,
                name=first.dataset_name,
                group_id=first.group_id,
                data_type=first.data_type,
                aggregation_level=first.aggregation_level,
                task_type=first.task_type,
                source_organ=first.source_organ,
                is_public=first.is_public,
                wsi_count=len(dataset_slides),
                case_count=len(case_ids),
                label_distribution=_distribution(slide.label for slide in dataset_slides),
                split_distribution=_distribution(slide.split for slide in dataset_slides),
                gender_distribution=_distribution(slide.gender for slide in dataset_slides),
                source_distribution=_distribution(slide.source for slide in dataset_slides),
                survival_event_distribution=_distribution(
                    slide.event_status for slide in dataset_slides
                ),
                age=_numeric(slide.age for slide in dataset_slides),
                mpp=_numeric(slide.mpp for slide in dataset_slides),
                file_size_bytes_total=sum(
                    int(slide.file_size or 0) for slide in dataset_slides
                ),
                vendors=sorted({slide.vendor for slide in dataset_slides if slide.vendor}),
                magnifications=sorted(
                    {int(slide.magnification) for slide in dataset_slides if slide.magnification}
                ),
                feature_extracted_count=sum(
                    1 for slide in dataset_slides if slide.feature_extracted
                ),
            )
        )

    return DatasetSummary(
        task_id=descriptor.task_id,
        role=descriptor.role,
        label=descriptor.label,
        status=CollectorStatus.ready,
        datasets=cohorts,
    )
