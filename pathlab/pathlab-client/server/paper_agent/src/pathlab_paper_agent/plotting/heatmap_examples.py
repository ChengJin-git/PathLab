"""Attention / heatmap example panel generator."""

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

GENERATOR = "heatmap_examples"


def generate(output_dir: Path, spec: dict[str, Any]) -> FigureOutput:
    figure_id = str(spec.get("figure_id", "fig:heatmap_examples"))
    data = spec.get("data") or spec.get("plot_spec", {}).get("data") or spec
    examples = require_records(data.get("examples"), field="examples")[:4]

    image = new_canvas((980, 620))
    draw = ImageDraw.Draw(image)
    draw.text((42, 30), spec.get("title", "Attention heatmap examples"), fill="#111827", font=font(25, True))
    for idx, example in enumerate(examples):
        x = 42 + (idx % 2) * 470
        y = 86 + (idx // 2) * 255
        base = require_image(
            example.get("image_path") or example.get("image"),
            field=f"examples[{idx}].image",
            size=(420, 190),
        )
        heatmap = require_array(example.get("heatmap"), field=f"examples[{idx}].heatmap")
        overlay = heatmap_overlay(base, heatmap)
        image.paste(overlay, (x, y))
        draw.rectangle((x, y, x + 420, y + 190), outline="#111827", width=2)
        draw.text((x, y + 202), str(example.get("case_id", f"case_{idx + 1:03d}")), fill="#111827", font=font(15, True))
        draw.text((x + 120, y + 202), str(example.get("label", "attention overlay")), fill="#374151", font=font(15))

    filename = f"{slugify(figure_id)}.png"
    path = output_dir / filename
    save_png(image, path)
    return output(
        figure_id=figure_id,
        rel_path=f"figures/{filename}",
        source=str(spec.get("source", "mock_or_evidence")),
        generator=GENERATOR,
        caption=str(spec.get("caption", "Heatmap examples generated deterministically.")),
    )
