"""Calibration / reliability diagram generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import ImageDraw

from .types import FigureGenerationError, FigureOutput
from .utils import (
    PALETTE,
    draw_plot_frame,
    draw_polyline,
    draw_title,
    ensure_path,
    new_canvas,
    output,
    require_numeric_list,
    require_records,
    require_same_length,
    save_png,
    to_plot_point,
)

GENERATOR = "calibration_plot"


def _first(record: dict[str, Any], *names: str, field: str) -> Any:
    for name in names:
        if name in record:
            return record[name]
    raise FigureGenerationError(f"missing required calibration field: {field}")


def _points(data: dict[str, Any]) -> tuple[list[float], list[float], list[float]]:
    if data.get("bins") is not None:
        bins = require_records(data.get("bins"), field="bins")
        x = require_numeric_list(
            [_first(item, "confidence", "predicted", field="confidence") for item in bins],
            field="bins.confidence",
        )
        y = require_numeric_list(
            [_first(item, "accuracy", "observed", field="accuracy") for item in bins],
            field="bins.accuracy",
        )
        counts = require_numeric_list(
            [item.get("count", 1.0) for item in bins],
            field="bins.count",
        )
        require_same_length(("confidence", x), ("accuracy", y), ("counts", counts))
        return x, y, counts
    x = require_numeric_list(
        data.get("confidence") or data.get("mean_predicted"),
        field="confidence",
    )
    y = require_numeric_list(
        data.get("accuracy") or data.get("fraction_positive"),
        field="accuracy",
    )
    counts = (
        require_numeric_list(data.get("counts"), field="counts")
        if data.get("counts") is not None
        else [1.0] * len(x)
    )
    require_same_length(("confidence", x), ("accuracy", y), ("counts", counts))
    return x, y, counts


def generate(output_dir: Path, spec: dict[str, Any]) -> FigureOutput:
    figure_id = str(spec.get("figure_id", "fig:calibration"))
    data = spec.get("data") or spec.get("plot_spec", {}).get("data") or spec
    x, y, counts = _points(data)

    image = new_canvas()
    draw = ImageDraw.Draw(image)
    draw_title(draw, spec.get("title", "Calibration curve"))
    draw_plot_frame(draw, "Mean predicted probability", "Observed frequency")
    diagonal = [to_plot_point(0, 0), to_plot_point(1, 1)]
    draw_polyline(draw, diagonal, color="#9ca3af", width=2)
    points = [to_plot_point(a, b) for a, b in zip(x, y)]
    draw_polyline(draw, points, color=PALETTE[0], width=5)
    max_count = max(max(counts), 1.0) if counts else 1.0
    for idx, point in enumerate(points):
        radius = 5 + int(10 * (counts[idx] / max_count))
        draw.ellipse(
            (point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius),
            fill=PALETTE[0],
            outline="white",
            width=2,
        )

    path, rel_path = ensure_path(output_dir, figure_id)
    save_png(image, path)
    return output(
        figure_id=figure_id,
        rel_path=rel_path,
        source=str(spec.get("source", "mock_or_evidence")),
        generator=GENERATOR,
        caption=str(spec.get("caption", "Calibration curve generated deterministically.")),
    )
