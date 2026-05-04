"""PaperOrchestra-style Outline Agent stage."""

from __future__ import annotations

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from ..agents import OutlineAgent, OutlineInputs
from .common import load_config, register_artifact, write_json


def run(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    *,
    agent: OutlineAgent | None = None,
) -> None:
    config = load_config(paths)
    outline_agent = agent or OutlineAgent()
    outline = outline_agent.generate(OutlineInputs.from_paths(paths, config))
    write_json(paths.outline_json, outline)
    register_artifact(
        manifest,
        "drafts/outline.json",
        label="Outline",
        content_type="application/json",
    )
