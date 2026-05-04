"""Collecting stage scaffold.

M2 replaces this module with real PathLab task/artifact collection while keeping
its `run(paths, manifest)` boundary stable for the pipeline orchestrator.
"""

from __future__ import annotations

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from .common import load_config, register_artifact, write_json, write_text


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = load_config(paths)
    source_tasks = [task.model_dump(mode="json") for task in config.source_tasks]
    write_json(paths.source_tasks, source_tasks)
    write_json(
        paths.source_analyses,
        {
            "selection": "latest",
            "note": "Deterministic scaffold; real analysis resolution lands in collector milestones.",
        },
    )
    write_text(
        paths.idea,
        (config.user_idea or "PathLab paper-generation scaffold run.").strip() + "\n",
    )
    register_artifact(
        manifest,
        "inputs/source_tasks.json",
        visibility="private_backend_only",
        downloadable=False,
        label="Source task mapping",
        content_type="application/json",
    )
    register_artifact(
        manifest,
        "inputs/source_analyses.json",
        visibility="private_backend_only",
        downloadable=False,
        label="Source analysis mapping",
        content_type="application/json",
    )
    register_artifact(
        manifest,
        "inputs/idea.md",
        visibility="private_backend_only",
        downloadable=False,
        label="User idea",
        content_type="text/markdown",
    )
