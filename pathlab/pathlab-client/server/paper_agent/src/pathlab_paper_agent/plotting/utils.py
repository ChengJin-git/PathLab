"""Small Pillow-based drawing helpers for deterministic paper figures."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .types import FigureGenerationError, FigureOutput

CANVAS = (960, 640)
MARGIN = 88
PLOT_BOX = (MARGIN, 92, CANVAS[0] - 52, CANVAS[1] - 88)
PALETTE = (
    "#1f77b4",
    "#d62728",
    "#2ca02c",
    "#ff7f0e",
    "#9467bd",
    "#17becf",
)


def slugify(value: str) -> str:
    value = value.replace(":", "_").lower()
    value = re.sub(r"[^a-z0-9_\-]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_") or "figure"


def new_canvas(size: tuple[int, int] = CANVAS) -> Image.Image:
    return Image.new("RGB", size, "white")


def font(size: int = 18, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def draw_title(draw: ImageDraw.ImageDraw, title: str) -> None:
    draw.text((MARGIN, 34), title, fill="#111827", font=font(24, bold=True))


def draw_plot_frame(draw: ImageDraw.ImageDraw, x_label: str, y_label: str) -> None:
    left, top, right, bottom = PLOT_BOX
    draw.rectangle(PLOT_BOX, outline="#111827", width=2)
    for i in range(6):
        x = left + (right - left) * i / 5
        y = bottom - (bottom - top) * i / 5
        draw.line((x, top, x, bottom), fill="#e5e7eb", width=1)
        draw.line((left, y, right, y), fill="#e5e7eb", width=1)
        draw.text((x - 10, bottom + 12), f"{i / 5:.1f}", fill="#374151", font=font(13))
        draw.text((left - 42, y - 8), f"{i / 5:.1f}", fill="#374151", font=font(13))
    draw.text(((left + right) / 2 - 48, bottom + 44), x_label, fill="#111827", font=font(16))
    draw.text((18, (top + bottom) / 2 - 18), y_label, fill="#111827", font=font(16))


def to_plot_point(x_value: float, y_value: float) -> tuple[float, float]:
    left, top, right, bottom = PLOT_BOX
    x_clamped = min(1.0, max(0.0, float(x_value)))
    y_clamped = min(1.0, max(0.0, float(y_value)))
    x = left + (right - left) * x_clamped
    y = bottom - (bottom - top) * y_clamped
    return x, y


def draw_polyline(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[float, float]],
    *,
    color: str,
    width: int = 4,
) -> None:
    if len(points) < 2:
        return
    draw.line(points, fill=color, width=width, joint="curve")


def numeric_list(value: Any, *, default: Iterable[float] = ()) -> list[float]:
    if value is None:
        return [float(v) for v in default]
    values = [float(v) for v in value]
    if not all(math.isfinite(v) for v in values):
        raise FigureGenerationError("numeric values must be finite")
    return values


def require_numeric_list(value: Any, *, field: str, min_length: int = 1) -> list[float]:
    if value is None:
        raise FigureGenerationError(f"missing required numeric list: {field}")
    if isinstance(value, (str, bytes)):
        raise FigureGenerationError(f"{field} must be a numeric list, not a string")
    try:
        values = numeric_list(value)
    except TypeError as exc:
        raise FigureGenerationError(f"{field} must be a numeric list") from exc
    if len(values) < min_length:
        raise FigureGenerationError(
            f"{field} must contain at least {min_length} numeric value(s)"
        )
    return values


def require_records(value: Any, *, field: str, min_length: int = 1) -> list[dict[str, Any]]:
    if value is None:
        raise FigureGenerationError(f"missing required records: {field}")
    if not isinstance(value, list):
        raise FigureGenerationError(f"{field} must be a list of objects")
    if any(not isinstance(item, dict) for item in value):
        raise FigureGenerationError(f"{field} must only contain objects")
    records = list(value)
    if len(records) < min_length:
        raise FigureGenerationError(
            f"{field} must contain at least {min_length} object(s)"
        )
    return records


def require_same_length(*items: tuple[str, Sequence[Any]]) -> None:
    lengths = {name: len(values) for name, values in items}
    if len(set(lengths.values())) > 1:
        detail = ", ".join(f"{name}={length}" for name, length in lengths.items())
        raise FigureGenerationError(f"numeric lists must have equal length: {detail}")


def ensure_path(output_dir: Path, figure_id: str, suffix: str = ".png") -> tuple[Path, str]:
    filename = f"{slugify(figure_id)}{suffix}"
    rel_path = f"figures/{filename}"
    path = output_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path, rel_path


def save_png(image: Image.Image, path: Path) -> None:
    image.save(path, format="PNG", optimize=False)


def output(
    *,
    figure_id: str,
    rel_path: str,
    source: str,
    generator: str,
    caption: str,
) -> FigureOutput:
    return FigureOutput(
        figure_id=figure_id,
        path=rel_path,
        status="ready",
        source=source,
        generator=generator,
        caption=caption,
    )


def load_image(value: Any, *, size: tuple[int, int] = (220, 160)) -> Image.Image:
    if isinstance(value, str) and Path(value).exists():
        return Image.open(value).convert("RGB").resize(size)
    if isinstance(value, (list, tuple, np.ndarray)):
        arr = np.asarray(value, dtype=float)
        if arr.ndim == 2:
            arr = np.stack([arr, arr, arr], axis=-1)
        arr = normalize_array(arr)
        return Image.fromarray(arr.astype("uint8"), mode="RGB").resize(size)
    img = Image.new("RGB", size, "#f3f4f6")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, size[0] - 1, size[1] - 1), outline="#d1d5db")
    d.text((18, size[1] // 2 - 8), "image pending", fill="#6b7280", font=font(14))
    return img


def require_image(value: Any, *, field: str, size: tuple[int, int]) -> Image.Image:
    if value is None:
        raise FigureGenerationError(f"missing required image evidence: {field}")
    if isinstance(value, str) and not Path(value).exists():
        raise FigureGenerationError(f"image evidence not found for {field}: {value}")
    return load_image(value, size=size)


def require_array(value: Any, *, field: str) -> Any:
    if value is None:
        raise FigureGenerationError(f"missing required array evidence: {field}")
    return value


def normalize_array(arr: np.ndarray) -> np.ndarray:
    arr = np.nan_to_num(arr.astype(float), copy=False)
    min_v = float(arr.min()) if arr.size else 0.0
    max_v = float(arr.max()) if arr.size else 1.0
    if math.isclose(min_v, max_v):
        return np.zeros_like(arr) + 127
    return (arr - min_v) / (max_v - min_v) * 255


def heatmap_overlay(base: Image.Image, heatmap: Any, alpha: float = 0.45) -> Image.Image:
    hm = np.asarray(heatmap if heatmap is not None else [[0.2, 0.8], [0.4, 0.6]], dtype=float)
    hm = normalize_array(hm)
    hm_img = Image.fromarray(hm.astype("uint8"), mode="L").resize(base.size)
    red = Image.new("RGB", base.size, "#ef4444")
    colored = Image.composite(red, Image.new("RGB", base.size, "white"), hm_img)
    return Image.blend(base.convert("RGB"), colored, alpha)


def mask_to_rgb(mask: Any, *, size: tuple[int, int]) -> Image.Image:
    arr = np.asarray(mask if mask is not None else [[0, 1], [1, 0]], dtype=float)
    arr = normalize_array(arr)
    gray = Image.fromarray(arr.astype("uint8"), mode="L").resize(size)
    return Image.merge("RGB", (gray, Image.new("L", size, 40), Image.new("L", size, 90)))
