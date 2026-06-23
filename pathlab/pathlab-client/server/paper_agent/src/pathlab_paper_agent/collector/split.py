"""Train/validation/test split summaries."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from .dataset import SlideRecord
from .schemas import (
    CollectorStatus,
    MissingEvidence,
    SourceTaskDescriptor,
    SplitBucket,
    SplitSummary,
)


def _distribution(values: Iterable[Any]) -> dict[str, int]:
    counter = Counter(str(v) for v in values if v not in (None, ""))
    return dict(sorted(counter.items()))


def build_split_summary(
    descriptor: SourceTaskDescriptor,
    slides: list[SlideRecord],
) -> SplitSummary:
    if not slides:
        return SplitSummary(
            task_id=descriptor.task_id,
            role=descriptor.role,
            label=descriptor.label,
            status=CollectorStatus.missing,
            missing_evidence=[
                MissingEvidence(
                    item="training_task_wsi_split",
                    task_id=descriptor.task_id,
                    reason="No split assignments were resolved for this task.",
                )
            ],
        )

    by_split: dict[str, list[SlideRecord]] = defaultdict(list)
    for slide in slides:
        split = slide.split or "unassigned"
        by_split[split].append(slide)

    buckets = [
        SplitBucket(
            split=split,
            wsi_count=len(split_slides),
            case_count=len({slide.case_id or slide.wsi_id for slide in split_slides}),
            label_distribution=_distribution(slide.label for slide in split_slides),
            survival_event_distribution=_distribution(
                slide.event_status for slide in split_slides
            ),
        )
        for split, split_slides in sorted(by_split.items())
    ]
    split_names = [bucket.split for bucket in buckets]
    missing: list[MissingEvidence] = []
    if "test" not in split_names and not any(name.startswith("fold_") for name in split_names):
        missing.append(
            MissingEvidence(
                item="test_or_fold_split",
                task_id=descriptor.task_id,
                reason="No test split or fold_* split was found.",
                severity="warning",
            )
        )

    return SplitSummary(
        task_id=descriptor.task_id,
        role=descriptor.role,
        label=descriptor.label,
        status=CollectorStatus.partial if missing else CollectorStatus.ready,
        buckets=buckets,
        has_test_split="test" in split_names,
        fold_splits=sorted(name for name in split_names if name.startswith("fold_")),
        missing_evidence=missing,
    )
