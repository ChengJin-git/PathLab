"""Standalone filesystem pipeline helpers for Phase 01.

The standalone agent intentionally starts with deterministic, no-LLM stages.
Each stage writes the paper-run artifact shape promised by the design doc so
Gateway, TaskWorker, and the front-end can integrate against a stable contract
while later milestones replace scaffold content with real collectors/agents.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from .bootstrap import configure_uploads_dir, ensure_server_on_path

ensure_server_on_path()

from backend.database.models import utc_now  # noqa: E402
from pathlab_paper_agent.schemas import (  # noqa: E402
    CreatePaperRequest,
    PaperConfig,
    PaperManifest,
    PaperRunArtifact,
    PaperRunStage,
    PaperRunStatus,
    PaperRunSummary,
    SourceTaskRef,
)
from pathlab_paper_agent.storage import PaperRunPaths, validate_paper_id  # noqa: E402

from .stages import (  # noqa: E402
    run_building_evidence,
    run_collecting,
    run_exporting,
    run_literature_review,
    run_outlining,
    run_plotting,
    run_refining,
    run_rendering,
    run_section_writing,
    run_validating,
)
from .scaffold import initialize_paper_run  # noqa: E402,F401
from .stages.common import artifact, read_json, write_json  # noqa: E402

_STAGE_ORDER: tuple[PaperRunStage, ...] = (
    PaperRunStage.collecting,
    PaperRunStage.building_evidence,
    PaperRunStage.outlining,
    PaperRunStage.plotting,
    PaperRunStage.literature_review,
    PaperRunStage.section_writing,
    PaperRunStage.validating,
    PaperRunStage.refining,
    PaperRunStage.rendering,
    PaperRunStage.exporting,
)

_STAGES_UNTIL_OUTLINE: tuple[PaperRunStage, ...] = (
    PaperRunStage.collecting,
    PaperRunStage.building_evidence,
    PaperRunStage.outlining,
)

_STAGES_AFTER_OUTLINE: tuple[PaperRunStage, ...] = (
    PaperRunStage.plotting,
    PaperRunStage.literature_review,
    PaperRunStage.section_writing,
    PaperRunStage.validating,
    PaperRunStage.refining,
    PaperRunStage.rendering,
    PaperRunStage.exporting,
)


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def load_manifest(paper_id: str, uploads_dir: Optional[str | Path] = None) -> PaperManifest:
    configure_uploads_dir(uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    if not paths.manifest.exists():
        raise FileNotFoundError(f"manifest.json not found for {paper_id}")
    return PaperManifest.model_validate(read_json(paths.manifest))


def save_manifest(manifest: PaperManifest, uploads_dir: Optional[str | Path] = None) -> PaperRunPaths:
    configure_uploads_dir(uploads_dir)
    paths = PaperRunPaths.for_paper(manifest.paper_id)
    manifest.updated_at = utc_now()
    write_json(paths.manifest, manifest.model_dump(mode="json"))
    return paths


def _default_request() -> CreatePaperRequest:
    return CreatePaperRequest(
        title="PathLab Paper Dev Run",
        source_tasks=[SourceTaskRef(task_id="paper_dev_source")],
    )


async def create_dev_run(
    body: Optional[CreatePaperRequest] = None,
    *,
    paper_id: Optional[str] = None,
    uploads_dir: Optional[str | Path] = None,
) -> tuple[str, PaperRunPaths]:
    """Create a filesystem-only paper run for standalone testing."""
    configure_uploads_dir(uploads_dir)
    request = body or _default_request()
    if not request.source_tasks:
        request.source_tasks = [SourceTaskRef(task_id="paper_dev_source")]
    if paper_id is None:
        import uuid

        paper_id = f"paper_{uuid.uuid4().hex[:16]}"
    validate_paper_id(paper_id)

    config = PaperConfig(
        paper_id=paper_id,
        title=request.title,
        paper_type=request.paper_type,
        language=request.language,
        source_tasks=request.source_tasks,
        selected_templates=request.selected_templates,
        include_external_validation=request.include_external_validation,
        user_idea=request.user_idea,
    )
    paths = await initialize_paper_run(None, config)  # type: ignore[arg-type]
    return paper_id, paths


def _ensure_run_from_config(
    paper_id: str,
    config_path: Optional[str | Path],
    *,
    uploads_dir: Optional[str | Path] = None,
) -> None:
    """Bootstrap a run directory from config.json if the manifest is missing.

    Gateway creates the manifest before invoking the worker, but the CLI also
    accepts `--config` so developers can reproduce worker runs from only a
    saved config file.
    """
    configure_uploads_dir(uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    if paths.manifest.exists():
        return
    if config_path is None:
        return

    src = Path(config_path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"config file not found: {src}")
    config = PaperConfig.model_validate(read_json(src))
    if config.paper_id != paper_id:
        raise ValueError(
            f"config paper_id {config.paper_id!r} does not match CLI paper_id {paper_id!r}"
        )

    _initialize_paper_run_sync(config)


def _initialize_paper_run_sync(config: PaperConfig) -> PaperRunPaths:
    """Sync twin of Gateway's M1 initializer for CLI config replay.

    `run_stage()` is intentionally synchronous and is also called inside the
    dev FastAPI app, so it cannot depend on `asyncio.run()`.
    """
    paths = PaperRunPaths.for_paper(config.paper_id)
    paths.ensure_dirs()
    write_json(paths.config, config.model_dump(mode="json"))
    now = utc_now()
    manifest = PaperManifest(
        paper_id=config.paper_id,
        status=PaperRunStatus.pending,
        current_stage=PaperRunStage.created,
        stage_log=[
            {
                "stage": PaperRunStage.created.value,
                "status": "completed",
                "ts": now.isoformat(),
                "started_at": now.isoformat(),
                "finished_at": now.isoformat(),
                "duration_ms": 0,
                "message": "Paper run scaffold created from config.",
            }
        ],
        artifact_index={
            "config.json": artifact(
                label="Run config",
                content_type="application/json",
            ),
            "manifest.json": artifact(
                label="Run manifest",
                content_type="application/json",
            ),
        },
        created_at=now,
        updated_at=now,
    )
    write_json(paths.manifest, manifest.model_dump(mode="json"))
    return paths


# ---------------------------------------------------------------------------
# Stage dispatch
# ---------------------------------------------------------------------------


def _execute_stage(paths: PaperRunPaths, manifest: PaperManifest, stage: PaperRunStage) -> None:
    if stage == PaperRunStage.collecting:
        run_collecting(paths, manifest)
    elif stage == PaperRunStage.building_evidence:
        run_building_evidence(paths, manifest)
    elif stage == PaperRunStage.outlining:
        run_outlining(paths, manifest)
    elif stage == PaperRunStage.plotting:
        run_plotting(paths, manifest)
    elif stage == PaperRunStage.literature_review:
        run_literature_review(paths, manifest)
    elif stage == PaperRunStage.section_writing:
        run_section_writing(paths, manifest)
    elif stage == PaperRunStage.validating:
        run_validating(paths, manifest)
    elif stage == PaperRunStage.refining:
        run_refining(paths, manifest)
    elif stage == PaperRunStage.rendering:
        run_rendering(paths, manifest)
    elif stage == PaperRunStage.exporting:
        run_exporting(paths, manifest)
    elif stage in (PaperRunStage.completed, PaperRunStage.failed, PaperRunStage.cancelled):
        return
    else:
        raise ValueError(f"Stage {stage.value!r} is not executable in the standalone scaffold")


def _assert_not_fixture_completion(paths: PaperRunPaths) -> None:
    """Prevent no-network/scaffold writing artifacts from being reported as final."""
    if os.environ.get("PAPER_GEN_ALLOW_FIXTURE_COMPLETION") == "1":
        return
    if "PYTEST_CURRENT_TEST" in os.environ:
        return

    markers: list[str] = []
    outline = _read_json_default(paths.outline_json)
    if isinstance(outline, dict):
        extensions = outline.get("pathlab_extensions")
        if isinstance(extensions, dict) and extensions.get("llm_mode") == "ci_no_network_fixture":
            markers.append("drafts/outline.json: ci_no_network_fixture")

    coverage = _read_json_default(paths.citations_dir / "coverage_report.json")
    if isinstance(coverage, dict) and str(coverage.get("mode", "")).startswith("ci_no_network"):
        markers.append("citations/coverage_report.json: ci_no_network mode")

    refinement_log = paths.validation_dir / "refinement_log.json"
    if refinement_log.exists() and "No-network fixture" in refinement_log.read_text(encoding="utf-8"):
        markers.append("validation/refinement_log.json: no-network critic")

    scaffold_phrases = (
        "PathLab produces a manuscript draft",
        "The prose in this section frames",
        "PathLab assembles the final manuscript around deterministic artifacts",
    )
    for section_path in sorted(paths.sections_dir.glob("*.tex")):
        text = section_path.read_text(encoding="utf-8")
        if any(phrase in text for phrase in scaffold_phrases):
            markers.append(f"drafts/sections/{section_path.name}: scaffold prose")
            break

    if markers:
        marker_text = "; ".join(markers)
        raise RuntimeError(
            "Refusing to mark paper run completed because fixture/scaffold writing artifacts "
            f"were detected: {marker_text}. Set PAPER_GEN_ALLOW_FIXTURE_COMPLETION=1 only for "
            "explicit scaffold-only development runs."
        )


def _read_json_default(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = read_json(path)
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Public stage API
# ---------------------------------------------------------------------------


def run_stage(
    paper_id: str,
    stage: str | PaperRunStage,
    *,
    uploads_dir: Optional[str | Path] = None,
    config_path: Optional[str | Path] = None,
    message: Optional[str] = None,
) -> PaperManifest:
    """Execute one deterministic stage and update `manifest.json`.

    Later milestones can replace individual `stages/*` modules without changing
    the CLI, dev server, TaskWorker subprocess boundary, or front-end polling
    contract.
    """
    configure_uploads_dir(uploads_dir)
    _ensure_run_from_config(paper_id, config_path, uploads_dir=uploads_dir)
    stage_value = stage.value if isinstance(stage, PaperRunStage) else str(stage)
    try:
        stage_enum = PaperRunStage(stage_value)
    except ValueError as exc:
        allowed = ", ".join(s.value for s in PaperRunStage)
        raise ValueError(f"Unknown paper stage {stage_value!r}. Allowed: {allowed}") from exc

    manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    started_at = utc_now()

    try:
        manifest.status = PaperRunStatus.running
        manifest.current_stage = stage_enum
        manifest.error_message = None
        manifest.finished_at = None
        manifest.updated_at = started_at
        if stage_enum not in (
            PaperRunStage.completed,
            PaperRunStage.failed,
            PaperRunStage.cancelled,
        ):
            manifest.stage_log.append(
                {
                    "stage": stage_enum.value,
                    "status": "running",
                    "ts": started_at.isoformat(),
                    "started_at": started_at.isoformat(),
                    "finished_at": None,
                    "duration_ms": None,
                    "message": f"Stage {stage_enum.value} started.",
                }
            )
            save_manifest(manifest, uploads_dir=uploads_dir)
        _execute_stage(paths, manifest, stage_enum)
        manifest.error_message = None
        finished_at = utc_now()
        if stage_enum == PaperRunStage.completed:
            _assert_not_fixture_completion(paths)
            manifest.status = PaperRunStatus.completed
            manifest.finished_at = finished_at
        elif stage_enum == PaperRunStage.failed:
            manifest.status = PaperRunStatus.failed
            manifest.finished_at = finished_at
        elif stage_enum == PaperRunStage.cancelled:
            manifest.status = PaperRunStatus.cancelled
            manifest.finished_at = finished_at
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        manifest.stage_log.append(
            {
                "stage": stage_enum.value,
                "status": "completed",
                "ts": finished_at.isoformat(),
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "duration_ms": duration_ms,
                "message": message or f"Stage {stage_enum.value} completed.",
            }
        )
    except Exception as exc:
        failed_at = utc_now()
        duration_ms = max(0, int((failed_at - started_at).total_seconds() * 1000))
        manifest.status = PaperRunStatus.failed
        manifest.current_stage = PaperRunStage.failed
        manifest.error_message = str(exc)[:4000]
        manifest.finished_at = failed_at
        manifest.stage_log.append(
            {
                "stage": stage_enum.value,
                "status": "failed",
                "ts": failed_at.isoformat(),
                "started_at": started_at.isoformat(),
                "finished_at": failed_at.isoformat(),
                "duration_ms": duration_ms,
                "message": f"Stage {stage_enum.value} failed: {exc}",
                "error_message": str(exc)[:4000],
            }
        )
        save_manifest(manifest, uploads_dir=uploads_dir)
        raise

    save_manifest(manifest, uploads_dir=uploads_dir)
    return manifest


def complete_run(
    paper_id: str,
    *,
    uploads_dir: Optional[str | Path] = None,
    config_path: Optional[str | Path] = None,
    bypass_approval: bool = False,
) -> PaperManifest:
    """Run the interactive pipeline up to the outline approval gate.

    Set ``bypass_approval=True`` or ``PATHLAB_PAPER_AGENT_NO_APPROVAL_GATE=1``
    for non-interactive smoke tests that must keep the pre-gate full run.
    """
    if bypass_approval or os.environ.get("PATHLAB_PAPER_AGENT_NO_APPROVAL_GATE") == "1":
        return complete_run_full(
            paper_id,
            uploads_dir=uploads_dir,
            config_path=config_path,
        )
    return run_until_outline(
        paper_id,
        uploads_dir=uploads_dir,
        config_path=config_path,
    )


def complete_run_full(
    paper_id: str,
    *,
    uploads_dir: Optional[str | Path] = None,
    config_path: Optional[str | Path] = None,
) -> PaperManifest:
    """Run all deterministic scaffold stages and mark the paper completed."""
    for stage in _STAGE_ORDER:
        run_stage(
            paper_id,
            stage,
            uploads_dir=uploads_dir,
            config_path=config_path,
        )
    return run_stage(
        paper_id,
        PaperRunStage.completed,
        uploads_dir=uploads_dir,
        config_path=config_path,
        message="Standalone paper-agent scaffold completed.",
    )


def run_until_outline(
    paper_id: str,
    *,
    uploads_dir: Optional[str | Path] = None,
    config_path: Optional[str | Path] = None,
) -> PaperManifest:
    """Run Job A: collect evidence and produce an editable outline."""
    for stage in _STAGES_UNTIL_OUTLINE:
        run_stage(
            paper_id,
            stage,
            uploads_dir=uploads_dir,
            config_path=config_path,
        )

    manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
    now = utc_now()
    manifest.status = PaperRunStatus.awaiting_outline_approval
    manifest.current_stage = PaperRunStage.outlining
    manifest.error_message = None
    manifest.finished_at = None
    manifest.stage_log.append(
        {
            "stage": PaperRunStage.outlining.value,
            "status": PaperRunStatus.awaiting_outline_approval.value,
            "ts": now.isoformat(),
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "duration_ms": 0,
            "message": "Outline generated; awaiting user approval.",
        }
    )
    save_manifest(manifest, uploads_dir=uploads_dir)
    return manifest


def run_after_outline(
    paper_id: str,
    *,
    uploads_dir: Optional[str | Path] = None,
    config_path: Optional[str | Path] = None,
) -> PaperManifest:
    """Run Job B: continue after the user-approved outline."""
    for stage in _STAGES_AFTER_OUTLINE:
        run_stage(
            paper_id,
            stage,
            uploads_dir=uploads_dir,
            config_path=config_path,
        )
    return run_stage(
        paper_id,
        PaperRunStage.completed,
        uploads_dir=uploads_dir,
        config_path=config_path,
        message="Standalone paper-agent scaffold completed.",
    )


def manifest_artifacts(manifest: PaperManifest) -> list[PaperRunArtifact]:
    artifacts: list[PaperRunArtifact] = []
    for rel_path, raw in manifest.artifact_index.items():
        if isinstance(raw, dict):
            data = {"path": rel_path, **raw}
        else:
            data = {"path": rel_path, "status": str(raw)}
        artifacts.append(PaperRunArtifact.model_validate(data))
    return artifacts


def summarize_manifest(paper_id: str, *, uploads_dir: Optional[str | Path] = None) -> PaperRunSummary:
    manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    config_data: dict[str, Any] = {}
    if paths.config.exists():
        config_data = read_json(paths.config)
    return PaperRunSummary(
        paper_id=paper_id,
        status=manifest.status,
        current_stage=manifest.current_stage,
        title=config_data.get("title"),
        selected_templates=config_data.get("selected_templates", []),
        source_task_ids=[item.get("task_id", "") for item in config_data.get("source_tasks", [])],
        created_at=manifest.created_at,
        finished_at=manifest.finished_at,
        error_message=manifest.error_message,
    )
