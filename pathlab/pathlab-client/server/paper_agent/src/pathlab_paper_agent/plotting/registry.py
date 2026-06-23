"""Generator registry used by the plotting stage."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from . import calibration_plot
from . import chart_passthrough
from . import failure_cases_panel
from . import grad_cam_examples
from . import heatmap_examples
from . import km_stratified
from . import per_fold_roc
from . import seg_qualitative_4panel
from .types import FigureOutput

Generator = Callable[[Path, dict[str, Any]], FigureOutput]

_GENERATORS: dict[str, Generator] = {
    "calibration": calibration_plot.generate,
    "calibration_plot": calibration_plot.generate,
    "reliability_diagram": calibration_plot.generate,
    "roc": per_fold_roc.generate,
    "per_fold_roc": per_fold_roc.generate,
    "km": km_stratified.generate,
    "km_stratified": km_stratified.generate,
    "kaplan_meier": km_stratified.generate,
    "survival": km_stratified.generate,
    "failure_cases": failure_cases_panel.generate,
    "failure_cases_panel": failure_cases_panel.generate,
    "heatmap": heatmap_examples.generate,
    "heatmap_examples": heatmap_examples.generate,
    "segmentation": seg_qualitative_4panel.generate,
    "seg_qualitative_4panel": seg_qualitative_4panel.generate,
    "segmentation_qualitative": seg_qualitative_4panel.generate,
    "grad_cam": grad_cam_examples.generate,
    "grad_cam_examples": grad_cam_examples.generate,
    "chart_passthrough": chart_passthrough.generate,
    "passthrough": chart_passthrough.generate,
}


def _generator_name(spec: dict[str, Any]) -> str:
    plot_spec = spec.get("plot_spec") if isinstance(spec.get("plot_spec"), dict) else {}
    value = (
        spec.get("generator")
        or spec.get("plot_type")
        or plot_spec.get("generator")
        or plot_spec.get("plot_type")
        or plot_spec.get("kind")
        or spec.get("kind")
    )
    return str(value or "").strip().lower()


def supported_generators() -> tuple[str, ...]:
    return tuple(sorted(_GENERATORS))


def generate_figure(output_dir: Path, spec: dict[str, Any]) -> FigureOutput:
    name = _generator_name(spec)
    try:
        generator = _GENERATORS[name]
    except KeyError as exc:
        allowed = ", ".join(supported_generators())
        raise ValueError(f"Unsupported empirical figure generator {name!r}; allowed: {allowed}") from exc
    return generator(output_dir, spec)
