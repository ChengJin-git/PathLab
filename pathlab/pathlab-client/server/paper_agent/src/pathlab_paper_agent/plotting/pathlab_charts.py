"""Bridge existing PathLab analysis charts into the paper plotting stage."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pathlab_paper_agent.storage import PaperRunPaths

from .utils import slugify

AUTO_PLAN_REL_PATH = "evidence/plot_data/pathlab_charts.auto_plan.json"
CHARTS_MANIFEST_REL_PATH = "evidence/plot_data/pathlab_charts_manifest.json"

_ALLOWED_CHART_SUFFIXES = {".png", ".jpg", ".jpeg", ".pdf"}
_CHART_KIND_ALIASES = {
    "auc": "roc_curve",
    "auroc": "roc_curve",
    "kaplan_meier": "km_curve",
    "km": "km_curve",
    "roc": "roc_curve",
    "survival": "km_curve",
}
_GENERATOR_TO_CHART_KIND = {
    "calibration": "calibration",
    "calibration_plot": "calibration",
    "confusion": "confusion_matrix",
    "confusion_matrix": "confusion_matrix",
    "kaplan_meier": "km_curve",
    "km": "km_curve",
    "km_stratified": "km_curve",
    "loss": "loss_curve",
    "loss_curve": "loss_curve",
    "per_fold_roc": "roc_curve",
    "roc": "roc_curve",
    "roc_curve": "roc_curve",
    "survival": "km_curve",
}


@dataclass(frozen=True)
class PreparedPathLabChart:
    """Safe run-local chart reference prepared for chart_passthrough."""

    chart_kind: str
    source_path: str
    data_ref: str
    figure_id: str


@dataclass(frozen=True)
class PathLabChartPreparation:
    """Output of preparing existing PathLab charts for paper figures."""

    charts: tuple[PreparedPathLabChart, ...]
    auto_plan_path: str = AUTO_PLAN_REL_PATH
    manifest_path: str = CHARTS_MANIFEST_REL_PATH


def prepare_pathlab_chart_passthroughs(paths: PaperRunPaths) -> PathLabChartPreparation:
    """Stage existing PathLab analysis charts for deterministic passthrough.

    The source paths in PathLab analysis summaries may point outside the paper
    run. We copy them into `figures/source_charts/` first so the regular
    chart_passthrough generator can enforce a single safe allowlist.
    """
    charts: list[PreparedPathLabChart] = []
    manifest_items: list[dict[str, Any]] = []
    plan_items: list[dict[str, Any]] = []
    for index, item in enumerate(_iter_existing_chart_sources(paths), start=1):
        chart_kind = _normalize_chart_kind(item["chart_kind"])
        source_path = item["source_path"]
        rel_source = _copy_source_chart(paths, source_path, chart_kind, index)
        data_ref = _write_chart_data_ref(paths, rel_source, chart_kind, index)
        figure_id = _default_figure_id(item, chart_kind)
        prepared = PreparedPathLabChart(
            chart_kind=chart_kind,
            source_path=rel_source,
            data_ref=data_ref,
            figure_id=figure_id,
        )
        charts.append(prepared)
        manifest_items.append(
            {
                "chart_kind": chart_kind,
                "source_path": rel_source,
                "data_ref": data_ref,
                "figure_id": figure_id,
                "source": "pathlab_analysis_chart",
            }
        )
        plan_items.append(_auto_plan_item(prepared))

    _write_json(paths.root / CHARTS_MANIFEST_REL_PATH, {"charts": manifest_items})
    _write_json(paths.root / AUTO_PLAN_REL_PATH, {"plotting_plan": plan_items})
    return PathLabChartPreparation(charts=tuple(charts))


def load_pathlab_chart_plotting_plan(paths: PaperRunPaths) -> list[dict[str, Any]]:
    """Load the auto passthrough plan prepared by the plotting stage."""
    payload = _read_json(paths.root / AUTO_PLAN_REL_PATH)
    if not isinstance(payload, Mapping):
        return []
    raw_plan = payload.get("plotting_plan")
    if not isinstance(raw_plan, list):
        return []
    return [dict(item) for item in raw_plan if isinstance(item, Mapping)]


def merge_plotting_plan_with_pathlab_charts(
    outline_plan: Sequence[Mapping[str, Any]],
    chart_plan: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Prefer prepared PathLab charts over redrawing equivalent figures."""
    auto_items = [dict(item) for item in chart_plan if isinstance(item, Mapping)]
    if not auto_items:
        return [dict(item) for item in outline_plan]

    auto_by_kind: dict[str, list[dict[str, Any]]] = {}
    for item in auto_items:
        kind = _item_chart_kind(item)
        if kind is not None:
            auto_by_kind.setdefault(kind, []).append(item)
    used_data_refs: set[str] = set()
    merged: list[dict[str, Any]] = []

    for raw_item in outline_plan:
        item = dict(raw_item)
        kind = _item_chart_kind(item)
        if kind and auto_by_kind.get(kind):
            replacement = _merge_outline_metadata(item, auto_by_kind[kind].pop(0))
            merged.append(replacement)
            if data_ref := _item_data_ref(replacement):
                used_data_refs.add(data_ref)
        else:
            merged.append(item)
            if data_ref := _item_data_ref(item):
                used_data_refs.add(data_ref)

    for item in auto_items:
        data_ref = _item_data_ref(item)
        if data_ref and data_ref in used_data_refs:
            continue
        merged.append(dict(item))
        if data_ref:
            used_data_refs.add(data_ref)
    return merged


def _iter_existing_chart_sources(paths: PaperRunPaths) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for summary in _load_analysis_summaries(paths):
        selected_id = summary.get("selected_analysis_id")
        analyses = summary.get("analyses") if isinstance(summary.get("analyses"), list) else []
        selected = [
            analysis
            for analysis in analyses
            if isinstance(analysis, Mapping)
            and (not selected_id or analysis.get("analysis_id") == selected_id)
        ]
        for analysis in selected:
            chart_paths = analysis.get("chart_paths")
            if not isinstance(chart_paths, Mapping):
                continue
            for raw_kind, raw_path in sorted(chart_paths.items()):
                source_path = _resolve_chart_source(paths, raw_path, analysis)
                if source_path is None:
                    continue
                items.append(
                    {
                        "chart_kind": str(raw_kind),
                        "source_path": source_path,
                        "role": str(summary.get("role") or "main"),
                    }
                )
    return items


def _load_analysis_summaries(paths: PaperRunPaths) -> list[dict[str, Any]]:
    raw_dir = paths.evidence_dir / "raw_collected"
    summary_payload = _read_json(raw_dir / "analysis_summary.json")
    if isinstance(summary_payload, Mapping):
        items = summary_payload.get("items")
        if isinstance(items, list):
            return [dict(item) for item in items if isinstance(item, Mapping)]

    bundle_payload = _read_json(raw_dir / "collector_bundle.json")
    if isinstance(bundle_payload, Mapping):
        items = bundle_payload.get("analysis_summaries")
        if isinstance(items, list):
            return [dict(item) for item in items if isinstance(item, Mapping)]
    return []


def _resolve_chart_source(
    paths: PaperRunPaths,
    raw_path: Any,
    analysis: Mapping[str, Any],
) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    raw = Path(raw_path).expanduser()
    for candidate in _chart_source_candidates(paths, raw, analysis):
        try:
            source_path = candidate.resolve()
        except OSError:
            continue
        if not source_path.is_file():
            continue
        if source_path.suffix.lower() not in _ALLOWED_CHART_SUFFIXES:
            continue
        return source_path
    return None


def _chart_source_candidates(
    paths: PaperRunPaths,
    raw_path: Path,
    analysis: Mapping[str, Any],
) -> list[Path]:
    if raw_path.is_absolute():
        return [raw_path]

    candidates = [paths.root / raw_path]
    analysis_dir = analysis.get("analysis_dir")
    if isinstance(analysis_dir, str) and analysis_dir.strip():
        base = Path(analysis_dir).expanduser()
        if base.is_absolute():
            candidates.append(base / raw_path)
        else:
            candidates.append(paths.root / base / raw_path)
    return candidates


def _copy_source_chart(paths: PaperRunPaths, source_path: Path, chart_kind: str, index: int) -> str:
    suffix = source_path.suffix.lower()
    filename = f"chart_{index:02d}_{slugify(chart_kind)}{suffix}"
    target = paths.figures_dir / "source_charts" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if source_path.resolve() != target.resolve():
        shutil.copy2(source_path, target)
    return f"figures/source_charts/{filename}"


def _write_chart_data_ref(paths: PaperRunPaths, rel_source: str, chart_kind: str, index: int) -> str:
    filename = f"pathlab_chart_{index:02d}_{slugify(chart_kind)}.json"
    rel_path = f"evidence/plot_data/{filename}"
    _write_json(
        paths.root / rel_path,
        {
            "source_path": rel_source,
            "chart_kind": chart_kind,
            "source": "pathlab_analysis_chart",
        },
    )
    return rel_path


def _auto_plan_item(chart: PreparedPathLabChart) -> dict[str, Any]:
    return {
        "figure_id": chart.figure_id,
        "kind": "empirical",
        "source": f"pathlab_analysis:{chart.chart_kind}",
        "design_objective": f"reuse the existing PathLab {chart.chart_kind} chart",
        "backend": "deterministic_plotting",
        "plot_spec": {
            "generator": "chart_passthrough",
            "chart_kind": chart.chart_kind,
            "data_ref": chart.data_ref,
        },
    }


def _default_figure_id(item: Mapping[str, Any], chart_kind: str) -> str:
    role = slugify(str(item.get("role") or "main"))
    prefix = "pathlab" if role in {"main", ""} else f"pathlab_{role}"
    return f"fig:{prefix}_{slugify(chart_kind)}"


def _merge_outline_metadata(
    outline_item: Mapping[str, Any],
    auto_item: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(auto_item)
    for key in ("figure_id", "title", "design_objective"):
        value = outline_item.get(key)
        if value:
            merged[key] = value
    merged["kind"] = "empirical"
    return merged


def _item_chart_kind(item: Mapping[str, Any]) -> str | None:
    plot_spec = item.get("plot_spec") if isinstance(item.get("plot_spec"), Mapping) else {}
    for value in (
        item.get("chart_kind"),
        plot_spec.get("chart_kind"),
        item.get("chart"),
        plot_spec.get("chart"),
    ):
        if value:
            return _normalize_chart_kind(value)

    generator = _item_generator(item)
    if generator in _GENERATOR_TO_CHART_KIND:
        return _GENERATOR_TO_CHART_KIND[generator]
    if generator == "chart_passthrough":
        return None

    text = " ".join(
        str(value)
        for value in (
            item.get("figure_id"),
            item.get("title"),
            item.get("design_objective"),
        )
        if value
    ).lower()
    if "confusion" in text:
        return "confusion_matrix"
    if "roc" in text or "auroc" in text or "auc" in text:
        return "roc_curve"
    if "kaplan" in text or "survival" in text or "km" in text:
        return "km_curve"
    if "loss" in text:
        return "loss_curve"
    if "calibration" in text:
        return "calibration"
    return None


def _item_generator(item: Mapping[str, Any]) -> str:
    plot_spec = item.get("plot_spec") if isinstance(item.get("plot_spec"), Mapping) else {}
    value = (
        item.get("generator")
        or item.get("plot_type")
        or plot_spec.get("generator")
        or plot_spec.get("plot_type")
        or plot_spec.get("kind")
        or ""
    )
    return _normalize_chart_kind(value)


def _item_data_ref(item: Mapping[str, Any]) -> str | None:
    plot_spec = item.get("plot_spec") if isinstance(item.get("plot_spec"), Mapping) else {}
    value = plot_spec.get("data_ref") or plot_spec.get("data_path") or item.get("data_ref")
    return str(value) if value else None


def _normalize_chart_kind(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    normalized = slugify(raw)
    return _CHART_KIND_ALIASES.get(normalized, normalized)


def _read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
