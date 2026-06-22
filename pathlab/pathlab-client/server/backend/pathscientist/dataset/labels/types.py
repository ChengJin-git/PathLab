"""Shared label-resolution dataclasses."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class LabelSpec:
    task_name: str
    label_type: str
    granularity: str = "slide"
    fields: list[str] = field(default_factory=list)
    class_mapping: dict[str, str] = field(default_factory=dict)
    source_priority: list[str] = field(default_factory=list)
    target_gene: str = ""
    join_key: str = "case_submitter_id"
    missing_policy: str = "drop_unlabeled"
    split_group: str = "case_submitter_id"
    min_coverage: float = 0.95

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LabelResolutionResult:
    status: str
    label_type: str
    label_semantics: str
    wsi_dir: str
    labels_file: str
    splits_file: str
    provenance_file: str
    patient_groups_file: str
    n_slides: int
    n_labeled: int
    label_coverage: float
    class_counts: dict[str, int]
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
