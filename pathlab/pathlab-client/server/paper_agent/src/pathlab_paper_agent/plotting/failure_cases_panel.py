"""Failure-case panel generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import ImageDraw

from .types import FigureGenerationError, FigureOutput
from .utils import font, new_canvas, output, require_image, require_records, save_png, slugify

GENERATOR = "failure_cases_panel"


def generate(output_dir: Path, spec: dict[str, Any]) -> FigureOutput:
    figure_id = str(spec.get("figure_id", "fig:failure_cases"))
    data = spec.get("data") or spec.get("plot_spec", {}).get("data") or spec
    cases = require_records(data.get("cases"), field="cases")[:6]

    image = new_canvas((1020, 700))
    draw = ImageDraw.Draw(image)
    draw.text((44, 32), spec.get("title", "Representative failure cases"), fill="#111827", font=font(25, True))
    card_w, card_h = 300, 270
    for idx, case in enumerate(cases):
        col = idx % 3
        row = idx // 3
        x = 44 + col * 322
        y = 88 + row * 292
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=18, fill="#f9fafb", outline="#d1d5db")
        thumb = require_image(
            case.get("image_path") or case.get("image"),
            field=f"cases[{idx}].image",
            size=(260, 150),
        )
        image.paste(thumb, (x + 20, y + 18))
        if case.get("true_label") is None:
            raise FigureGenerationError(f"cases[{idx}].true_label is required")
        if case.get("predicted_label", case.get("prediction")) is None:
            raise FigureGenerationError(f"cases[{idx}].predicted_label is required")
        true_label = case["true_label"]
        pred = case.get("predicted_label", case.get("prediction"))
        confidence = case.get("confidence")
        confidence_text = f" confidence={float(confidence):.2f}" if confidence is not None else ""
        draw.text((x + 20, y + 184), str(case.get("case_id", f"case_{idx + 1:03d}")), fill="#111827", font=font(16, True))
        draw.text((x + 20, y + 212), f"true: {true_label}", fill="#374151", font=font(15))
        draw.text((x + 20, y + 238), f"pred: {pred}{confidence_text}", fill="#b91c1c", font=font(15))

    filename = f"{slugify(figure_id)}.png"
    path = output_dir / filename
    save_png(image, path)
    return output(
        figure_id=figure_id,
        rel_path=f"figures/{filename}",
        source=str(spec.get("source", "mock_or_evidence")),
        generator=GENERATOR,
        caption=str(spec.get("caption", "Representative failure cases generated deterministically.")),
    )
