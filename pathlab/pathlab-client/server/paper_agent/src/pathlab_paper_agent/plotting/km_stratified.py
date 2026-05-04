"""Kaplan-Meier style stratified survival curve generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import ImageDraw

from .types import FigureOutput
from .utils import (
    PALETTE,
    PLOT_BOX,
    draw_plot_frame,
    draw_title,
    ensure_path,
    new_canvas,
    output,
    require_numeric_list,
    require_records,
    require_same_length,
    save_png,
)

GENERATOR = "km_stratified"


def _scale_point(time_value: float, surv_value: float, max_time: float) -> tuple[float, float]:
    left, top, right, bottom = PLOT_BOX
    x = left + (right - left) * (time_value / max_time if max_time else 0.0)
    y = bottom - (bottom - top) * max(0.0, min(1.0, surv_value))
    return x, y


def _step_points(times: list[float], survival: list[float], max_time: float) -> list[tuple[float, float]]:
    if not times:
        return []
    points = [_scale_point(0.0, 1.0, max_time)]
    last_y = 1.0
    for t, s in zip(times, survival):
        points.append(_scale_point(t, last_y, max_time))
        points.append(_scale_point(t, s, max_time))
        last_y = s
    points.append(_scale_point(max_time, last_y, max_time))
    return points


def _groups(data: dict[str, Any]) -> list[dict[str, Any]]:
    return require_records(data.get("groups"), field="groups")


def generate(output_dir: Path, spec: dict[str, Any]) -> FigureOutput:
    figure_id = str(spec.get("figure_id", "fig:km_stratified"))
    data = spec.get("data") or spec.get("plot_spec", {}).get("data") or spec
    groups = _groups(data)
    group_series: list[tuple[dict[str, Any], list[float], list[float]]] = []
    for idx, group in enumerate(groups):
        times = require_numeric_list(group.get("times"), field=f"groups[{idx}].times")
        survival = require_numeric_list(
            group.get("survival"),
            field=f"groups[{idx}].survival",
        )
        require_same_length((f"groups[{idx}].times", times), (f"groups[{idx}].survival", survival))
        group_series.append((group, times, survival))
    max_time = max((max(times) for _, times, _ in group_series), default=1.0)

    image = new_canvas()
    draw = ImageDraw.Draw(image)
    draw_title(draw, spec.get("title", "Stratified survival curves"))
    draw_plot_frame(draw, "Time", "Survival probability")
    for idx, (group, times, survival) in enumerate(group_series):
        points = _step_points(times, survival, max_time)
        color = PALETTE[idx % len(PALETTE)]
        if len(points) >= 2:
            draw.line(points, fill=color, width=4)
        legend_y = 108 + idx * 24
        draw.rectangle((700, legend_y, 718, legend_y + 12), fill=color)
        draw.text((724, legend_y - 3), str(group.get("label", f"group_{idx + 1}")), fill="#111827")

    path, rel_path = ensure_path(output_dir, figure_id)
    save_png(image, path)
    return output(
        figure_id=figure_id,
        rel_path=rel_path,
        source=str(spec.get("source", "mock_or_evidence")),
        generator=GENERATOR,
        caption=str(spec.get("caption", "Stratified survival curves generated deterministically.")),
    )
