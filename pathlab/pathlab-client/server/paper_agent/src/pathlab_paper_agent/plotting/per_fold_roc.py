"""Per-fold ROC curve generator."""

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

GENERATOR = "per_fold_roc"


def _folds(data: dict[str, Any]) -> list[dict[str, Any]]:
    if data.get("folds") is not None:
        return require_records(data.get("folds"), field="folds")
    if data.get("fpr") is None or data.get("tpr") is None:
        raise FigureGenerationError("ROC plot requires folds or fpr/tpr arrays")
    return [
        {
            "label": "fold_1",
            "fpr": data.get("fpr"),
            "tpr": data.get("tpr"),
            "auc": data.get("auc"),
        }
    ]


def generate(output_dir: Path, spec: dict[str, Any]) -> FigureOutput:
    figure_id = str(spec.get("figure_id", "fig:per_fold_roc"))
    data = spec.get("data") or spec.get("plot_spec", {}).get("data") or spec
    image = new_canvas()
    draw = ImageDraw.Draw(image)
    draw_title(draw, spec.get("title", "ROC curves by fold"))
    draw_plot_frame(draw, "False positive rate", "True positive rate")
    draw_polyline(draw, [to_plot_point(0, 0), to_plot_point(1, 1)], color="#d1d5db", width=2)

    legend_y = 104
    for idx, fold in enumerate(_folds(data)):
        fpr = require_numeric_list(fold.get("fpr"), field=f"folds[{idx}].fpr", min_length=2)
        tpr = require_numeric_list(fold.get("tpr"), field=f"folds[{idx}].tpr", min_length=2)
        require_same_length((f"folds[{idx}].fpr", fpr), (f"folds[{idx}].tpr", tpr))
        points = [to_plot_point(x, y) for x, y in zip(fpr, tpr)]
        color = PALETTE[idx % len(PALETTE)]
        draw_polyline(draw, points, color=color, width=4)
        label = str(fold.get("label", f"fold_{idx + 1}"))
        auc = fold.get("auc")
        legend = f"{label} AUC={float(auc):.3f}" if auc is not None else label
        draw.rectangle((700, legend_y + idx * 24, 718, legend_y + idx * 24 + 12), fill=color)
        draw.text((724, legend_y + idx * 24 - 3), legend, fill="#111827")

    path, rel_path = ensure_path(output_dir, figure_id)
    save_png(image, path)
    return output(
        figure_id=figure_id,
        rel_path=rel_path,
        source=str(spec.get("source", "mock_or_evidence")),
        generator=GENERATOR,
        caption=str(spec.get("caption", "Per-fold ROC curves generated deterministically.")),
    )
