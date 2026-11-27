"""Validated analysis outputs reusable by the existing chart components."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator
from backend.services.result_analysis.artifacts import PredictionArtifact

Name = Annotated[str, Field(min_length=1, max_length=200)]
Source = Annotated[str, Field(min_length=1, max_length=1000)]


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: FiniteFloat
    label: str = Field("", max_length=200)
    unit: str = Field("", max_length=40)
    ci_lower: FiniteFloat | None = None
    ci_upper: FiniteFloat | None = None

    @model_validator(mode="after")
    def interval(self):
        if (self.ci_lower is None) != (self.ci_upper is None):
            raise ValueError("Supply both interval bounds")
        if self.ci_lower is not None and self.ci_lower > self.ci_upper:
            raise ValueError("Interval bounds are reversed")
        return self


class Table(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field("", max_length=200)
    columns: list[Name] = Field(min_length=1, max_length=30)
    rows: list[list[str | FiniteFloat | None]] = Field(
        default_factory=list, max_length=200
    )

    @model_validator(mode="after")
    def rows_match(self):
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Table rows must match column count")
        if any(
            isinstance(cell, str) and len(cell) > 2000
            for row in self.rows
            for cell in row
        ):
            raise ValueError("Table cell exceeds preview budget")
        return self


class Figure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1000)
    title: str = Field("", max_length=200)
    caption: str = Field("", max_length=1000)


class AnalysisTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    task_type: Literal[
        "wsi_classification",
        "patch_classification",
        "wsi_survival",
        "patch_segmentation",
        "patch_detection",
        "custom",
    ]
    metric_keys: list[Name] = Field(default_factory=list, max_length=100)
    chart_keys: list[Name] = Field(default_factory=list, max_length=6)
    figure_paths: list[Source] = Field(default_factory=list, max_length=12)
    table_indices: list[int] = Field(default_factory=list, max_length=8)


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["pathlab-analysis-v1"]
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field("", max_length=6000)
    source_files: list[Source] = Field(default_factory=list, max_length=32)
    code_path: str = Field(min_length=1, max_length=1000)
    metrics: dict[Name, FiniteFloat | Metric] = Field(
        default_factory=dict, max_length=100
    )
    chart_data: dict[str, dict] = Field(default_factory=dict, max_length=6)
    figures: list[Figure] = Field(default_factory=list, max_length=12)
    tables: list[Table] = Field(default_factory=list, max_length=8)
    tasks: list[AnalysisTask] = Field(default_factory=list, max_length=16)
    predictions: PredictionArtifact | None = None

    @model_validator(mode="after")
    def task_references(self):
        if len({task.id for task in self.tasks}) != len(self.tasks):
            raise ValueError("Analysis task IDs must be unique")
        for task in self.tasks:
            if (
                set(task.metric_keys) - self.metrics.keys()
                or set(task.chart_keys) - self.chart_data.keys()
            ):
                raise ValueError("Analysis task references missing metrics/charts")
            if set(task.figure_paths) - {figure.path for figure in self.figures} or any(
                index < 0 or index >= len(self.tables) for index in task.table_indices
            ):
                raise ValueError("Analysis task references missing figures/tables")
        return self


def numeric_array(value, name):
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 5000
        or any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            for v in value
        )
    ):
        raise ValueError(f"{name} must be a bounded finite numeric array")
    return value


def labels(value, maximum):
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= maximum
        or any(not isinstance(c, str) or not 1 <= len(c) <= 100 for c in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("Chart classes must be unique bounded labels")
    return value


def aligned(data, names, length, *, probability=False, required=False):
    for name in names:
        if name not in data and not required:
            continue
        values = numeric_array(data.get(name), name)
        if len(values) != length or (
            probability and any(not 0 <= n <= 1 for n in values)
        ):
            raise ValueError(f"Invalid {name} coordinates")


def interval_arrays(data, lower, upper, length):
    if (lower in data) != (upper in data):
        raise ValueError("Supply both chart interval bounds")
    aligned(data, [lower, upper], length, probability=True)
    if lower in data and any(a > b for a, b in zip(data[lower], data[upper])):
        raise ValueError("Chart interval bounds are reversed")


def validate_charts(charts):
    """Existing components consume exact data contracts, never arbitrary JS/options."""
    for kind, data in charts.items():
        if kind == "confusion_matrix":
            classes = labels(data.get("classes"), 50)
            cells = data.get("data")
            if not isinstance(cells, list) or len(cells) > 2500:
                raise ValueError("Invalid confusion matrix cells")
            for cell in cells:
                numeric_array(cell, "matrix cell")
                if (
                    len(cell) != 3
                    or any(int(i) != i or not 0 <= i < len(classes) for i in cell[:2])
                    or cell[2] < 0
                ):
                    raise ValueError("Invalid confusion matrix coordinates")
        elif kind == "roc_curve":
            classes = labels(data.get("classes"), 20)
            if not isinstance(data.get("data"), dict) or set(data["data"]) != set(
                classes
            ):
                raise ValueError("Invalid ROC classes")
            for label in classes:
                series = data["data"].get(label, {})
                if not isinstance(series, dict):
                    raise ValueError("Invalid ROC series")
                x, y = (
                    numeric_array(series.get("fpr"), "fpr"),
                    numeric_array(series.get("tpr"), "tpr"),
                )
                auc = series.get("auc")
                if (
                    len(x) != len(y)
                    or isinstance(auc, bool)
                    or not isinstance(auc, (int, float))
                    or not 0 <= auc <= 1
                    or any(not 0 <= n <= 1 for n in x + y)
                ):
                    raise ValueError("Invalid ROC coordinates")
                if any(
                    name in series for name in ["fpr_grid", "tpr_lower", "tpr_upper"]
                ):
                    grid = numeric_array(series.get("fpr_grid"), "fpr_grid")
                    aligned(
                        series,
                        ["tpr_lower", "tpr_upper"],
                        len(grid),
                        probability=True,
                        required=True,
                    )
                    interval_arrays(series, "tpr_lower", "tpr_upper", len(grid))
        elif kind == "loss_curve":
            epochs = numeric_array(data.get("epochs"), "epochs")
            loss = numeric_array(data.get("loss"), "loss")
            if len(epochs) != len(loss):
                raise ValueError("Loss curve lengths differ")
            for name in ["val_loss", "accuracy", "val_accuracy"]:
                if name in data and len(numeric_array(data[name], name)) != len(epochs):
                    raise ValueError("Curve lengths differ")
        elif kind == "km_curve":
            for group in ["high_risk", "low_risk"]:
                series = data.get(group, {})
                if not isinstance(series, dict):
                    raise ValueError("Invalid KM series")
                times, probs = (
                    numeric_array(series.get("times"), "times"),
                    numeric_array(series.get("probs"), "probs"),
                )
                if len(times) != len(probs) or any(not 0 <= n <= 1 for n in probs):
                    raise ValueError("Invalid KM coordinates")
                interval_arrays(series, "ci_lower", "ci_upper", len(times))
            numeric_array([data.get("cutoff")], "cutoff")
            if "c_index" in data:
                numeric_array([data["c_index"]], "c_index")
                if not 0 <= data["c_index"] <= 1:
                    raise ValueError("Invalid concordance index")
        else:
            raise ValueError(
                f"Unsupported reusable chart {kind}; provide a generated figure instead"
            )


def read_result(root: Path, relative: str) -> dict:
    from .jobs import contained

    path = contained(root, relative)
    if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Analysis JSON must exist and be at most 2 MiB")

    def invalid_number(value):
        raise ValueError(f"Nonfinite JSON number: {value}")

    raw = json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid_number)
    result = AnalysisResult.model_validate(raw)
    validate_charts(result.chart_data)
    code = contained(root, result.code_path)
    if not code.is_file():
        raise ValueError("Publish the executed analysis source code with its results")
    result.code_path = str(code.relative_to(root.resolve()))
    if result.predictions:
        prediction_path = contained(root, result.predictions.path)
        if not prediction_path.is_file():
            raise ValueError("Prediction artifact does not exist")
        result.predictions.path = str(prediction_path.relative_to(root.resolve()))
    for figure in result.figures:
        image = contained(root, figure.path)
        if not image.is_file() or image.suffix.lower() not in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".svg",
            ".pdf",
        }:
            raise ValueError(
                "Figure must reference an existing image/PDF in the workspace"
            )
        figure.path = str(image.relative_to(root.resolve()))
    return result.model_dump()


async def publish(session, relative: str):
    from . import store
    from .file_catalog import index_tree
    from .jobs import contained

    root = Path(session.workspace_path).resolve()
    relative = str(contained(root, relative).relative_to(root))
    result = await asyncio.to_thread(read_result, root, relative)
    identity = hashlib.sha256(relative.encode()).hexdigest()[:16]
    stat = (root / relative).stat()
    entry = {
        "id": identity,
        "path": relative,
        "title": result["title"],
        "revision": f"{stat.st_mtime_ns}:{stat.st_size}",
    }
    paths = [
        str(contained(root, path).relative_to(root))
        for path in [
            relative,
            result["code_path"],
            *[figure["path"] for figure in result["figures"]],
        ]
    ]
    for directory in {(root / path).parent for path in paths}:
        await index_tree(session, directory)
    if result.get("predictions"):
        paths.append(
            str(contained(root, result["predictions"]["path"]).relative_to(root))
        )
        await index_tree(session, (root / paths[-1]).parent)
    await store.merge_metadata_items(
        session.session_id,
        "artifacts",
        [{"path": path, "name": Path(path).name, "kind": "file"} for path in paths],
        "path",
    )
    await store.merge_metadata_items(
        session.session_id, "analysis_results", [entry], "id", maximum=20
    )
    await store.update(
        session.session_id, event={"kind": "analysis", "analysis": entry}
    )
    from backend.services.result_analysis.sources import index_research

    await index_research(session, entry, result)
    return {"published": True, **entry}
