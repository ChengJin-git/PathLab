"""Deterministic plotting stage for empirical paper figures."""

from __future__ import annotations

from typing import Any

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from ..plotting import generate_figure
from .common import read_json, register_artifact, write_json


def _default_plan() -> list[dict[str, Any]]:
    return [
        {
            "figure_id": "fig:overview",
            "kind": "conceptual",
            "source": "scaffold",
            "caption": "Overview figure placeholder; PaperBanana-style generation lands in M6c.",
        }
    ]


def _load_plotting_plan(paths: PaperRunPaths) -> list[dict[str, Any]]:
    if not paths.outline_json.exists():
        return _default_plan()
    outline = read_json(paths.outline_json)
    plan = outline.get("plotting_plan")
    if not isinstance(plan, list) or not plan:
        return _default_plan()
    return [item for item in plan if isinstance(item, dict)] or _default_plan()


def _conceptual_entry(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "figure_id": str(spec.get("figure_id", "fig:overview")),
        "path": spec.get("path"),
        "status": str(spec.get("status", "requires_user_revision")),
        "source": str(spec.get("source", "scaffold")),
        "generator": str(spec.get("backend", "user_provided_or_paperbanana_m6c")),
        "caption": str(
            spec.get(
                "caption",
                "Conceptual overview figure requires user revision or M6c generation.",
            )
        ),
    }


def _pending_entry(spec: dict[str, Any], error: Exception) -> dict[str, Any]:
    plot_spec = spec.get("plot_spec") if isinstance(spec.get("plot_spec"), dict) else {}
    return {
        "figure_id": str(spec.get("figure_id", "fig:empirical_pending")),
        "path": None,
        "status": "pending_generation",
        "source": str(spec.get("source", "mock_or_evidence")),
        "generator": str(
            spec.get("generator")
            or spec.get("plot_type")
            or plot_spec.get("generator")
            or plot_spec.get("plot_type")
            or "unknown"
        ),
        "caption": str(spec.get("caption", "Empirical figure pending generation.")),
        "error": str(error)[:1000],
    }


def _is_empirical(spec: dict[str, Any]) -> bool:
    if str(spec.get("kind", "")).lower() == "empirical":
        return True
    plot_spec = spec.get("plot_spec") if isinstance(spec.get("plot_spec"), dict) else {}
    return bool(
        spec.get("generator")
        or spec.get("plot_type")
        or plot_spec.get("generator")
        or plot_spec.get("plot_type")
    )


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    for spec in _load_plotting_plan(paths):
        if not _is_empirical(spec):
            entries.append(_conceptual_entry(spec))
            continue
        try:
            result = generate_figure(paths.figures_dir, spec)
        except Exception as exc:
            entries.append(_pending_entry(spec, exc))
            figure_id = str(spec.get("figure_id", "fig:empirical_pending"))
            errors.append(f"{figure_id}: {exc}")
            continue
        entry = result.to_manifest_entry()
        entries.append(entry)
        register_artifact(
            manifest,
            result.path,
            label=result.figure_id,
            content_type=result.content_type,
        )

    write_json(paths.figures_manifest, {"figures": entries})
    register_artifact(
        manifest,
        "figures/manifest.json",
        label="Figures manifest",
        content_type="application/json",
    )
    if errors:
        first = errors[0]
        more = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
        raise RuntimeError(f"Empirical figure generation failed: {first}{more}")
