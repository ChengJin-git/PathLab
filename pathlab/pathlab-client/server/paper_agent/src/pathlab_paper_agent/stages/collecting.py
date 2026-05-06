"""Collecting stage for PathLab paper evidence.

M2 replaces the Phase 01 placeholder with a deterministic collector that writes
private raw evidence files. Phase 03 consumes these files for PHI scrub and
public/private evidence-lock construction.
"""

from __future__ import annotations

from backend.common.config import Config  # noqa: E402
from pathlab_paper_agent.schemas import PaperManifest  # noqa: E402
from pathlab_paper_agent.storage import PaperRunPaths  # noqa: E402

from ..collector import collect_pathlab_evidence
from .common import load_config, register_artifact, write_json, write_text

_RAW_COLLECTED_FILES = (
    "collector_bundle.json",
    "task_summary.json",
    "dataset_summary.json",
    "split_summary.json",
    "model_summary.json",
    "analysis_summary.json",
    "external_validation_summary.json",
    "qualitative_summary.json",
)


def _write_raw_collected(paths: PaperRunPaths, bundle) -> None:
    raw_dir = paths.evidence_dir / "raw_collected"
    write_json(raw_dir / "collector_bundle.json", bundle.model_dump(mode="json", by_alias=True))
    write_json(
        raw_dir / "task_summary.json",
        {"items": [item.model_dump(mode="json", by_alias=True) for item in bundle.task_summaries]},
    )
    write_json(
        raw_dir / "dataset_summary.json",
        {"items": [item.model_dump(mode="json", by_alias=True) for item in bundle.dataset_summaries]},
    )
    write_json(
        raw_dir / "split_summary.json",
        {"items": [item.model_dump(mode="json", by_alias=True) for item in bundle.split_summaries]},
    )
    write_json(
        raw_dir / "model_summary.json",
        {"items": [item.model_dump(mode="json", by_alias=True) for item in bundle.model_summaries]},
    )
    write_json(
        raw_dir / "analysis_summary.json",
        {"items": [item.model_dump(mode="json", by_alias=True) for item in bundle.analysis_summaries]},
    )
    write_json(
        raw_dir / "external_validation_summary.json",
        bundle.external_validation_summary.model_dump(mode="json", by_alias=True),
    )
    write_json(
        raw_dir / "qualitative_summary.json",
        {"items": [item.model_dump(mode="json", by_alias=True) for item in bundle.qualitative_summaries]},
    )


def _source_analysis_map(bundle) -> dict:
    return {
        "selection": "latest",
        "collector_mode": bundle.mode,
        "status": bundle.status.value,
        "items": [
            {
                "task_id": item.task_id,
                "role": item.role,
                "label": item.label,
                "status": item.status.value,
                "selected_analysis_id": item.selected_analysis_id,
                "available_analysis_ids": [record.analysis_id for record in item.analyses],
                "missing_evidence": [m.model_dump(mode="json", by_alias=True) for m in item.missing_evidence],
            }
            for item in bundle.analysis_summaries
        ],
    }


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = load_config(paths)
    source_tasks = [task.model_dump(mode="json", by_alias=True) for task in config.source_tasks]
    write_json(paths.source_tasks, source_tasks)
    write_text(
        paths.idea,
        (config.user_idea or "PathLab paper-generation scaffold run.").strip() + "\n",
    )

    bundle = collect_pathlab_evidence(config, uploads_dir=Config.get_uploads_dir())
    write_json(paths.source_analyses, _source_analysis_map(bundle))
    _write_raw_collected(paths, bundle)

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
    for name in _RAW_COLLECTED_FILES:
        register_artifact(
            manifest,
            f"evidence/raw_collected/{name}",
            visibility="private_backend_only",
            downloadable=False,
            label=f"Raw collected evidence: {name}",
            content_type="application/json",
        )
