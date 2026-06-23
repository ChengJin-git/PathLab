"""Segmentation qualitative four-panel generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import ImageDraw

from .types import FigureOutput
from .utils import (
    font,
    mask_to_rgb,
    new_canvas,
    output,
    require_array,
    require_image,
    require_records,
    save_png,
    slugify,
)

GENERATOR = "seg_qualitative_4panel"


def _panel_image(example: dict[str, Any], key: str, size: tuple[int, int]):
    value = example.get(key) or example.get(f"{key}_path")
    if key in {"mask", "prediction"}:
        return mask_to_rgb(require_array(value, field=key), size=size)
    return require_image(value, field=key, size=size)


def generate(output_dir: Path, spec: dict[str, Any]) -> FigureOutput:
    figure_id = str(spec.get("figure_id", "fig:seg_qualitative"))
    data = spec.get("data") or spec.get("plot_spec", {}).get("data") or spec
    example = require_records(data.get("examples"), field="examples")[0]
    panels = [
        ("Image", _panel_image(example, "image", (210, 170))),
        ("Ground truth", _panel_image(example, "mask", (210, 170))),
        ("Prediction", _panel_image(example, "prediction", (210, 170))),
        ("Overlay", _panel_image(example, "overlay", (210, 170))),
    ]

    image = new_canvas((990, 310))
    draw = ImageDraw.Draw(image)
    draw.text((38, 28), spec.get("title", "Segmentation qualitative example"), fill="#111827", font=font(24, True))
    for idx, (label, panel) in enumerate(panels):
        x = 38 + idx * 238
        y = 86
        image.paste(panel, (x, y))
        draw.rectangle((x, y, x + 210, y + 170), outline="#111827", width=2)
        draw.text((x, y + 184), label, fill="#111827", font=font(15, True))

    filename = f"{slugify(figure_id)}.png"
    path = output_dir / filename
    save_png(image, path)
    return output(
        figure_id=figure_id,
        rel_path=f"figures/{filename}",
        source=str(spec.get("source", "mock_or_evidence")),
        generator=GENERATOR,
        caption=str(spec.get("caption", "Segmentation four-panel generated deterministically.")),
    )
