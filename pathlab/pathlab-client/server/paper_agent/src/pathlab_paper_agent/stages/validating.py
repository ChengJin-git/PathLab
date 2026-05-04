"""Validation stage scaffold."""

from __future__ import annotations

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from .common import register_artifact, write_json, write_text


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    warnings = """# Validation Warnings

This standalone scaffold completed without LLM calls. Deterministic guards are
not yet enforcing real metrics/citations; M10 adds hard gates.
"""
    write_text(paths.validation_dir / "warnings.md", warnings)
    write_json(
        paths.validation_dir / "scaffold_guard.json",
        {"status": "pass", "mode": "standalone_scaffold"},
    )
    register_artifact(
        manifest,
        "validation/warnings.md",
        label="Validation warnings",
        content_type="text/markdown",
    )
    register_artifact(
        manifest,
        "validation/scaffold_guard.json",
        visibility="private_backend_only",
        downloadable=False,
        label="Scaffold guard report",
        content_type="application/json",
    )
