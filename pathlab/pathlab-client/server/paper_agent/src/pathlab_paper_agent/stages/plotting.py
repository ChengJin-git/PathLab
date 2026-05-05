"""Plotting Agent stage for empirical and conceptual paper figures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from ..agents.plotting_agent import PlottingAgent, PlottingAgentResult
from .common import register_artifact, write_json

_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
}


def run(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    *,
    agent: PlottingAgent | None = None,
) -> None:
    plotting_agent = agent or PlottingAgent()
    result = plotting_agent.generate(paths)
    write_json(paths.figures_manifest, result.figures_manifest)
    _register_artifacts(paths, manifest, result)
    if result.errors:
        first = result.errors[0]
        more = f" (+{len(result.errors) - 1} more)" if len(result.errors) > 1 else ""
        raise RuntimeError(f"Empirical figure generation failed: {first}{more}")


def _register_artifacts(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    result: PlottingAgentResult,
) -> None:
    register_artifact(
        manifest,
        "figures/manifest.json",
        label="Figures manifest",
        content_type="application/json",
    )
    for output in result.generated_figures:
        register_artifact(
            manifest,
            output.path,
            label=output.figure_id,
            content_type=output.content_type,
        )
    registered = {output.path for output in result.generated_figures}
    for entry in result.figures_manifest.get("figures", []):
        if not isinstance(entry, dict):
            continue
        rel_path = entry.get("path")
        if not _is_registerable_user_figure(paths, rel_path) or rel_path in registered:
            continue
        register_artifact(
            manifest,
            str(rel_path),
            label=str(entry.get("figure_id") or rel_path),
            content_type=_content_type_for_path(str(rel_path)),
        )


def _is_registerable_user_figure(paths: PaperRunPaths, rel_path: Any) -> bool:
    if not isinstance(rel_path, str) or not rel_path.startswith("figures/"):
        return False
    path = paths.root / rel_path
    try:
        path.resolve().relative_to(paths.figures_dir.resolve())
    except ValueError:
        return False
    return path.is_file()


def _content_type_for_path(rel_path: str) -> str:
    suffix = Path(rel_path).suffix.lower()
    return _CONTENT_TYPES.get(suffix, "application/octet-stream")
