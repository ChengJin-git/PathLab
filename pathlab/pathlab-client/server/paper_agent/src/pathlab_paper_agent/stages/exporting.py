"""Submission bundle export stage."""

from __future__ import annotations

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from ..renderers.zip_exporter import export_bundle
from .common import load_config, register_artifact


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = load_config(paths)
    for template in config.selected_templates:
        template_id = template.value
        bundle_name = f"{template_id}_bundle.zip"
        export_bundle(
            paths.final_for_template(template_id),
            paths.exports_dir / bundle_name,
            config,
            template_id,
        )
        register_artifact(
            manifest,
            f"exports/{bundle_name}",
            label=f"{template_id} submission bundle",
            content_type="application/zip",
        )
