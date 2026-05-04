"""Patch Grad-CAM example grid generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import ImageDraw

from .types import FigureOutput
from .utils import (
    font,
    heatmap_overlay,
    new_canvas,
    output,
    require_array,
    require_image,
    require_records,
    save_png,
    slugify,
)

GENERATOR = "grad_cam_examples"


def generate(output_dir: Path, spec: dict[str, Any]) -> FigureOutput:
    figure_id = str(spec.get("figure_id", "fig:grad_cam_examples"))
    data = spec.get("data") or spec.get("plot_spec", {}).get("data") or spec
    examples = require_records(data.get("examples"), field="examples")[:6]

    image = new_canvas((980, 690))
    draw = ImageDraw.Draw(image)
    draw.text((42, 30), spec.get("title", "Patch Grad-CAM examples"), fill="#111827", font=font(25, True))
    for idx, example in enumerate(examples):
        x = 42 + (idx % 3) * 310
        y = 88 + (idx // 3) * 280
        base = require_image(
            example.get("image_path") or example.get("image"),
            field=f"examples[{idx}].image",
            size=(270, 190),
        )
        heatmap = require_array(example.get("heatmap"), field=f"examples[{idx}].heatmap")
        overlay = heatmap_overlay(base, heatmap, alpha=0.4)
        image.paste(overlay, (x, y))
        draw.rectangle((x, y, x + 270, y + 190), outline="#111827", width=2)
        draw.text((x, y + 204), str(example.get("patch_id", f"patch_{idx + 1:03d}")), fill="#111827", font=font(15, True))
        draw.text((x, y + 228), str(example.get("label", "Grad-CAM overlay")), fill="#374151", font=font(14))

    filename = f"{slugify(figure_id)}.png"
    path = output_dir / filename
    save_png(image, path)
    return output(
        figure_id=figure_id,
        rel_path=f"figures/{filename}",
        source=str(spec.get("source", "mock_or_evidence")),
        generator=GENERATOR,
        caption=str(spec.get("caption", "Grad-CAM examples generated deterministically.")),
    )
