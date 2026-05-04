"""Copy an existing PathLab chart into the paper figures directory."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .types import FigureGenerationError, FigureOutput
from .utils import output, slugify

GENERATOR = "chart_passthrough"
_ALLOWED_SUFFIXES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
}


def _safe_source_path(output_dir: Path, raw_source: Any) -> tuple[Path, str]:
    if raw_source is None:
        raise FigureGenerationError("chart_passthrough requires source_path")
    source_path = Path(str(raw_source)).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"chart passthrough source not found: {source_path}")
    if source_path.suffix.lower() not in _ALLOWED_SUFFIXES:
        allowed = ", ".join(sorted(_ALLOWED_SUFFIXES))
        raise FigureGenerationError(
            f"chart passthrough only supports {allowed}: {source_path.name}"
        )

    run_root = output_dir.resolve().parent
    allowed_roots = [
        (run_root / "figures" / "source_charts").resolve(),
        (run_root / "figures" / "raw").resolve(),
    ]
    if not any(source_path.is_relative_to(root) for root in allowed_roots):
        raise FigureGenerationError(
            "chart_passthrough source_path must be inside "
            "figures/source_charts or figures/raw for this paper run"
        )
    return source_path, str(source_path.relative_to(run_root))


def generate(output_dir: Path, spec: dict[str, Any]) -> FigureOutput:
    figure_id = str(spec.get("figure_id", "fig:pathlab_chart"))
    data = spec.get("data") or spec.get("plot_spec", {}).get("data") or spec
    source_path, rel_source = _safe_source_path(
        output_dir,
        data.get("source_path") or spec.get("source_path"),
    )
    suffix = source_path.suffix.lower() if source_path.suffix else ".png"
    filename = f"{slugify(figure_id)}{suffix}"
    target = output_dir / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target)
    content_type = _ALLOWED_SUFFIXES[suffix]
    result = output(
        figure_id=figure_id,
        rel_path=f"figures/{filename}",
        source=str(spec.get("source") or rel_source),
        generator=GENERATOR,
        caption=str(spec.get("caption", "PathLab chart copied deterministically.")),
    )
    return FigureOutput(**{**result.to_manifest_entry(), "content_type": content_type})
