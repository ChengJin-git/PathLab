"""Explicit reusable prediction artifacts, never guessed from arbitrary experiment files."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat


class PredictionArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1000)
    task_type: Literal[
        "wsi_classification",
        "patch_classification",
        "wsi_survival",
        "patch_segmentation",
        "patch_detection",
    ]
    classes: list[str] = Field(default_factory=list, max_length=1024)
    unit: Literal["file", "case"] = "file"


class PredictionRow(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    sample_id: str = Field(min_length=1, max_length=255)
    dataset_id: str | None = Field(None, max_length=255)
    wsi_id: str | None = Field(None, max_length=255)
    case_id: str | None = Field(None, max_length=255)
    split: str = Field(min_length=1, max_length=80)
    label: str | None = Field(None, max_length=200)
    pred: str | None = Field(None, max_length=200)
    probs: dict[str, FiniteFloat] | None = None
    risk_score: FiniteFloat | None = None
    event_time: FiniteFloat | None = Field(None, ge=0)
    event_status: Literal[0, 1] | None = None
    surv_probs: list[FiniteFloat] | None = None
    bin_edges: list[FiniteFloat] | None = None
    metrics: dict[str, FiniteFloat | list[FiniteFloat]] = Field(default_factory=dict)
    detection: dict | None = None
    threshold_counts: dict | None = None
    image_size: tuple[int, int] | None = None
    age: FiniteFloat | None = Field(None, ge=0, le=150)
    gender: str | None = Field(None, max_length=80)
    source: str | None = Field(None, max_length=200)


def read_predictions(root: Path, spec: dict, *, config=None, inspect_only=False):
    from backend.autoresearch.engine.jobs import contained

    artifact = PredictionArtifact.model_validate(spec)
    path = contained(root, artifact.path)
    if not path.is_file() or path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError(
            "Prediction artifact must be an existing JSONL file of at most 256 MiB"
        )
    if len(set(artifact.classes)) != len(artifact.classes):
        raise ValueError("Prediction class labels must be unique")
    count, gt, probabilities = 0, 0, 0
    splits, dataset_ids, identities, rows = {}, set(), set(), []
    has_metrics, has_survival, has_thresholds = False, False, False
    sha = hashlib.sha256()
    with path.open("rb") as file:
        for raw in file:
            sha.update(raw)
            if not raw.strip():
                continue
            if len(raw) > 1024 * 1024:
                raise ValueError("Prediction row exceeds 1 MiB")
            item = PredictionRow.model_validate_json(raw)
            identity = (item.dataset_id, item.split, item.sample_id)
            if identity in identities:
                raise ValueError(
                    "Prediction samples must be unique within dataset/split"
                )
            identities.add(identity)
            if item.threshold_counts is not None:
                from .segmentation_thresholds import metrics_at_threshold
                metrics_at_threshold({"threshold_counts": item.threshold_counts}, 0.5)
                has_thresholds = True
            if artifact.task_type == "patch_detection":
                from .detection_metrics import validate_boxes
                if artifact.unit != "file" or not item.detection or set(item.detection) != {"prediction", "target"}:
                    raise ValueError("Patch detection requires file-level prediction and target fields")
                validate_boxes(item.detection["prediction"], artifact.classes, prediction=True)
                if item.detection["target"] is not None:
                    validate_boxes(item.detection["target"], artifact.classes)
            if item.probs is not None:
                if (
                    set(item.probs) != set(artifact.classes)
                    or any(not 0 <= value <= 1 for value in item.probs.values())
                    or abs(sum(item.probs.values()) - 1) > 1e-3
                ):
                    raise ValueError(
                        "Prediction probabilities must match the ordered classes and sum to one"
                    )
            if (
                item.label is not None
                and "classification" in artifact.task_type
                and item.label not in artifact.classes
            ):
                raise ValueError("Ground truth is outside the declared class set")
            count += 1
            if count > 500_000:
                raise ValueError("Prediction artifact exceeds 500,000 samples")
            gt += int(
                item.label is not None
                if "classification" in artifact.task_type
                else bool(item.metrics) or item.threshold_counts is not None
                if "segmentation" in artifact.task_type
                else item.detection["target"] is not None
                if artifact.task_type == "patch_detection"
                else item.event_time is not None and item.event_status is not None
            )
            probabilities += int(bool(item.probs))
            has_metrics = has_metrics or bool(item.metrics) or item.threshold_counts is not None
            has_survival = has_survival or bool(item.surv_probs)
            splits[item.split] = splits.get(item.split, 0) + 1
            if item.dataset_id:
                dataset_ids.add(item.dataset_id)
            if inspect_only:
                continue
            if config:
                f = config.filters
                if (
                    (
                        not item.split.startswith("fold_")
                        if config.split == "oof"
                        else item.split != config.split
                    )
                    or (f.source and f.source != item.source)
                    or (f.gender and f.gender != item.gender)
                ):
                    continue
                if f.age_min is not None and (item.age is None or item.age < f.age_min):
                    continue
                if f.age_max is not None and (item.age is None or item.age > f.age_max):
                    continue
            rows.append(
                {
                    "result_id": count,
                    "sample_id": item.sample_id,
                    "wsi_id": item.wsi_id,
                    "case_id": item.case_id
                    or (item.sample_id if artifact.unit == "case" else None),
                    "dataset_id": item.dataset_id or "artifact",
                    "split": item.split,
                    "label": item.label,
                    "pred": item.pred,
                    "probs": item.probs,
                    "age": item.age,
                    "gender": item.gender,
                    "source": item.source,
                    "event_time": item.event_time,
                    "event_status": item.event_status,
                    "filename": item.sample_id,
                    "metadata": {
                        "risk_score": item.risk_score,
                        "surv_probs": item.surv_probs,
                        "bin_edges": item.bin_edges,
                        "metrics": item.metrics,
                        "detection": item.detection,
                        "threshold_counts": item.threshold_counts,
                        "has_ground_truth": bool(item.metrics) or item.threshold_counts is not None,
                        "image_size": item.image_size,
                    },
                }
            )
    if not count:
        raise ValueError("Prediction artifact is empty")
    if any(split.startswith("fold_") for split in splits):
        splits = {
            "oof": sum(
                count for split, count in splits.items() if split.startswith("fold_")
            ),
            **splits,
        }
    return {
        "prediction_count": count,
        "gt_count": gt,
        "probability_count": probabilities,
        "splits": list(splits),
        "split_counts": splits,
        "dataset_ids": sorted(dataset_ids),
        "classes": artifact.classes,
        "unit": artifact.unit,
        "segmentation_metrics": has_metrics,
        "segmentation_thresholds": has_thresholds,
        "detection_boxes": artifact.task_type == "patch_detection",
        "survival": has_survival,
        "prediction_sha256": sha.hexdigest(),
        "rows": rows,
    }
