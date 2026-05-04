"""Plotting stage scaffold."""

from __future__ import annotations

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from .common import register_artifact, write_json


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    figures_manifest = {
        "figures": [
            {
                "figure_id": "fig:overview",
                "path": None,
                "status": "requires_user_revision",
                "source": "scaffold",
                "caption": "Overview figure placeholder; PaperBanana-style generation lands in M6c.",
            }
        ]
    }
    write_json(paths.figures_manifest, figures_manifest)
    register_artifact(
        manifest,
        "figures/manifest.json",
        label="Figures manifest",
        content_type="application/json",
    )
