"""One parameter contract for manual controls, saved recipes and LLM actions."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ChartSpec(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field("", max_length=200)
    color: str = Field("#2563eb", pattern=r"^#[0-9a-fA-F]{6}$")
    visible: bool = True
    x_min: float | None = None
    x_max: float | None = None

    @model_validator(mode="after")
    def ordered(self):
        if (
            self.x_min is not None
            and self.x_max is not None
            and self.x_min >= self.x_max
        ):
            raise ValueError("Chart minimum must be below maximum")
        return self


class Filters(StrictModel):
    source: str = Field("", max_length=200)
    gender: str = Field("", max_length=80)
    age_min: float | None = Field(None, ge=0, le=150)
    age_max: float | None = Field(None, ge=0, le=150)
    confidence_max: float | None = Field(None, ge=0, le=1)
    errors_only: bool = False

    @model_validator(mode="after")
    def age_range(self):
        if (
            self.age_min is not None
            and self.age_max is not None
            and self.age_min > self.age_max
        ):
            raise ValueError("Minimum age exceeds maximum age")
        return self


class IntervalSpec(StrictModel):
    enabled: bool = False
    level: float = Field(0.95, ge=0.8, le=0.99)
    samples: int = Field(200, ge=50, le=2000)
    unit: Literal["case", "sample"] = "case"
    seed: int = Field(42, ge=0, le=2147483647)


class AnalysisConfig(StrictModel):
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    facet_id: str = Field("", max_length=100)
    split: str = Field("test", min_length=1, max_length=80)
    unit: Literal["file", "case"] = "file"
    positive_class: str = Field("", max_length=200)
    average: Literal["binary", "macro", "micro", "weighted"] = "macro"
    threshold: float = Field(0.5, ge=0, le=1)
    detection_iou: float = Field(0.5, ge=0.1, le=0.95)
    metrics: list[str] = Field(
        default_factory=lambda: ["accuracy", "auc", "f1"], max_length=100
    )
    charts: list[ChartSpec] = Field(
        default_factory=lambda: [ChartSpec(id="roc"), ChartSpec(id="confusion")],
        max_length=16,
    )
    filters: Filters = Field(default_factory=Filters)
    group_by: Literal["", "source", "gender", "age_band", "dataset_id"] = ""
    interval: IntervalSpec = Field(default_factory=IntervalSpec)

    @model_validator(mode="after")
    def unique_fields(self):
        for values in (self.source_ids, self.metrics, [c.id for c in self.charts]):
            if len(values) != len(set(values)):
                raise ValueError("Duplicate selection")
        if any(not item or len(item) > 300 for item in self.source_ids):
            raise ValueError("Invalid result source ID")
        if any(not item or len(item) > 200 for item in self.metrics):
            raise ValueError("Invalid metric ID")
        return self


METRICS = [
    *[(key, label, "detection", "gt", "ratio", "max") for key, label in [
        ("map", "mAP @ IoU 0.50:0.95"), ("map_50", "AP @ IoU 0.50"),
        ("map_75", "AP @ IoU 0.75"), ("mar", "Mean average recall (100 detections)"),
        ("detection_precision", "Detection precision"), ("detection_recall", "Detection recall"),
        ("detection_f1", "Detection F1"),
    ]],
    *[(key, label, "detection", "gt", "", "") for key, label in [
        ("detection_tp", "Matched objects"), ("detection_fp", "False positives"), ("detection_fn", "Missed objects"),
    ]],
    ("detection_count", "Detected objects", "detection", "predictions", "", ""),
    ("sample_count", "Sample count", "any", "predictions", "", ""),
    ("accuracy", "Accuracy", "classification", "gt", "ratio", "max"),
    ("balanced_accuracy", "Balanced accuracy", "classification", "gt", "ratio", "max"),
    ("precision", "Precision", "classification", "gt", "ratio", "max"),
    ("sensitivity", "Sensitivity / Recall", "classification", "gt", "ratio", "max"),
    ("specificity", "Specificity", "classification", "gt", "ratio", "max"),
    ("f1", "F1", "classification", "gt", "ratio", "max"),
    ("mcc", "MCC", "classification", "gt", "", "max"),
    ("weighted_kappa", "Quadratic weighted kappa", "classification", "gt", "", "max"),
    ("auc", "ROC AUC", "classification", "gt_probs", "ratio", "max"),
    (
        "average_precision",
        "Average precision (AP)",
        "classification",
        "gt_probs",
        "ratio",
        "max",
    ),
    ("brier", "Brier score", "classification", "gt_probs", "", "min"),
    ("log_loss", "Log loss", "classification", "gt_probs", "", "min"),
    ("mean_confidence", "Mean confidence", "classification", "probs", "ratio", ""),
    ("entropy", "Predictive entropy", "classification", "probs", "nats", ""),
    ("c_index", "Concordance index", "survival", "gt", "", "max"),
    (
        "integrated_brier_score",
        "Integrated Brier score",
        "survival",
        "survival",
        "",
        "min",
    ),
    ("mean_risk", "Mean risk score", "survival", "predictions", "", ""),
    *[
        (key, label, "segmentation", "segmentation_metrics", "ratio", "max")
        for key, label in [
            ("iou", "IoU"),
            ("miou", "mIoU"),
            ("dice", "Dice"),
            ("pixel_accuracy", "Pixel accuracy"),
            ("pixel_precision", "Pixel precision"),
            ("pixel_recall", "Pixel recall"),
            ("pixel_f1", "Pixel F1"),
        ]
    ],
]
CHARTS = [
    ("detection_pr", "Detection precision–recall", "detection", "gt"),
    ("roc", "ROC", "classification", "gt_probs"),
    ("pr", "Precision–recall", "classification", "gt_probs"),
    ("confusion", "Confusion matrix", "classification", "gt"),
    ("calibration", "Calibration", "classification", "gt_probs"),
    ("threshold", "Threshold analysis", "classification", "gt_probs"),
    ("confidence", "Confidence distribution", "classification", "probs"),
    ("distribution", "Prediction distribution", "classification", "predictions"),
    ("km", "Kaplan–Meier", "survival", "gt"),
    ("risk", "Risk distribution", "survival", "predictions"),
    (
        "segmentation",
        "Per-image segmentation metrics",
        "segmentation",
        "segmentation_metrics",
    ),
    ("comparison", "Metric comparison", "any", "metrics"),
    ("disagreement", "Prediction disagreement", "classification", "predictions"),
    ("loss", "Training curves", "any", "training_history"),
]
METRIC_BY_ID = {
    row[0]: dict(zip(("id", "label", "family", "requires", "unit", "direction"), row))
    for row in METRICS
}
CHART_BY_ID = {
    row[0]: dict(zip(("id", "label", "family", "requires"), row)) for row in CHARTS
}


def family(task_type: str) -> str:
    return (
        "survival"
        if "survival" in task_type
        else "segmentation"
        if "segmentation" in task_type
        else "classification"
        if "classification" in task_type
        else "detection"
        if task_type == "patch_detection"
        else "custom"
    )


def catalog():
    return {
        "version": "1",
        "metrics": list(METRIC_BY_ID.values()),
        "charts": list(CHART_BY_ID.values()),
    }


def validate_selection(config: AnalysisConfig, sources):
    recorded = {
        key for source in sources for key in (source.details or {}).get("metrics", {})
    }
    unknown = set(config.metrics) - METRIC_BY_ID.keys() - recorded
    charts = {chart.id for chart in config.charts} - CHART_BY_ID.keys()
    if unknown or charts:
        raise ValueError(
            f"Unknown metrics/charts: {', '.join(sorted(unknown | charts))}"
        )
    if not sources:
        raise ValueError("Select at least one result source")
    prediction_families = {
        family(source.task_type)
        for source in sources
        if source.details.get("prediction_count")
    }
    if len(prediction_families) > 1:
        raise ValueError("Choose the same task type for sample-level comparison")
    for source in sources:
        details = source.details or {}
        if family(source.task_type) in {"segmentation", "detection"} and config.unit != "file":
            raise ValueError("Segmentation and detection use image-level evaluation")
        if family(source.task_type) in {"segmentation", "detection"} and (config.filters.errors_only or config.filters.confidence_max is not None):
            raise ValueError("Image-level classification error/confidence filters do not apply to segmentation or detection")
        if family(source.task_type) == "segmentation" and abs(config.threshold * 100 - round(config.threshold * 100)) > 1e-6:
            raise ValueError("Segmentation thresholds use increments of 0.01")
        if family(source.task_type) == "segmentation" and config.threshold != 0.5 and not details.get("segmentation_thresholds"):
            raise ValueError("Generate predictions with threshold statistics before adjusting segmentation thresholds")
        if config.facet_id and config.facet_id not in {
            task.get("id") for task in details.get("facets", [])
        }:
            raise ValueError(f"{source.title}: analysis subtask is unavailable")
        facet = next(
            (
                task
                for task in details.get("facets", [])
                if task.get("id") == config.facet_id
            ),
            None,
        )
        if facet and facet["task_type"] != source.task_type:
            if set(config.metrics) - set(facet["metric_keys"]):
                raise ValueError(
                    "This subtask has only its recorded metrics; sample predictions belong to a different task"
                )
            continue
        if details.get("prediction_count") and family(source.task_type) == "custom":
            raise ValueError(
                "Custom predictions require an explicit supported task contract"
            )
        if (
            details.get("prediction_artifact")
            and details.get("unit") == "case"
            and config.unit != "case"
        ):
            raise ValueError(
                "These predictions are already case-level; image-level data are unavailable"
            )
        if details.get("prediction_count") and config.split not in details.get(
            "splits", []
        ):
            raise ValueError(f"{source.title}: split '{config.split}' is unavailable")
        if (
            family(source.task_type) == "classification"
            and config.average == "binary"
            and len(details.get("classes", [])) != 2
            and details.get("prediction_count")
        ):
            raise ValueError("Binary averaging requires exactly two classes")
        if (
            family(source.task_type) == "classification"
            and config.positive_class
            and config.positive_class not in details.get("classes", [])
            and details.get("prediction_count")
        ):
            raise ValueError(f"{source.title}: unknown positive class")
