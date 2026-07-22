"""Standalone filesystem pipeline helpers for Phase 01.

The standalone agent intentionally starts with deterministic, no-LLM stages.
Each stage writes the paper-run artifact shape promised by the design doc so
Gateway, TaskWorker, and the front-end can integrate against a stable contract
while later milestones replace scaffold content with real collectors/agents.
"""

from __future__ import annotations

import hashlib
import os
import shutil
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
from .process_logging import append_pipeline_event  # noqa: E402
from .stages.common import artifact, read_json, write_json  # noqa: E402
from .diagnostics import assert_stage_artifacts_ready, inspect_paper_run  # noqa: E402
from .errors import error_code, error_payload  # noqa: E402


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

_STAGES_RENDER_EXPORT: tuple[PaperRunStage, ...] = (
    PaperRunStage.rendering,
    PaperRunStage.exporting,
)

_EXECUTABLE_STAGES: tuple[PaperRunStage, ...] = _STAGE_ORDER
_RERUN_TO_APPROVAL_STAGES = {
    PaperRunStage.collecting,
    PaperRunStage.building_evidence,
    PaperRunStage.outlining,
}
_STAGE_OUTPUT_PREFIXES: dict[PaperRunStage, tuple[str, ...]] = {
    PaperRunStage.collecting: ("inputs/", "evidence/raw_collected/"),
    PaperRunStage.building_evidence: ("evidence/", "tables/", "locked_blocks/"),
    PaperRunStage.outlining: ("drafts/outline.json", "logs/outlining_log.private.json"),
    PaperRunStage.plotting: ("figures/",),
    PaperRunStage.literature_review: ("citations/", "drafts/intro_rw_draft/"),
    PaperRunStage.section_writing: ("drafts/sections/", "logs/section_writing_log.private.json"),
    PaperRunStage.validating: ("validation/",),
    PaperRunStage.refining: ("drafts/sections/", "drafts/snapshots/", "validation/", "logs/refinement_llm_log.private.json"),
    PaperRunStage.rendering: ("final/",),
    PaperRunStage.exporting: ("exports/", "final/", "validation/warnings.md"),
}



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


def _pause_requested(paths: PaperRunPaths) -> bool:
    return paths.pause_request.exists()


def _clear_pause_request(paths: PaperRunPaths) -> None:
    try:
        paths.pause_request.unlink()
    except FileNotFoundError:
        pass


def _append_pause_log(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    *,
    stage: PaperRunStage,
    status: str,
    event: str,
    message: str,
) -> None:
    now = utc_now()
    manifest.stage_log.append(
        {
            "stage": stage.value,
            "status": status,
            "ts": now.isoformat(),
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "duration_ms": 0,
            "message": message,
        }
    )
    append_pipeline_event(
        paths,
        manifest,
        event,
        stage=stage.value,
        status=status,
        started_at=now.isoformat(),
        finished_at=now.isoformat(),
        duration_ms=0,
        message=message,
    )


def request_pause(paper_id: str, uploads_dir: Optional[str | Path] = None) -> PaperManifest:
    configure_uploads_dir(uploads_dir)
    manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    paths.pause_request.write_text(utc_now().isoformat(), encoding="utf-8")
    manifest.status = PaperRunStatus.paused
    manifest.error_message = None
    manifest.finished_at = None
    _append_pause_log(
        paths,
        manifest,
        stage=manifest.current_stage,
        status="pause_requested",
        event="pause_requested",
        message="Pause requested by user; the pipeline will stop at the next stage boundary.",
    )
    save_manifest(manifest, uploads_dir=uploads_dir)
    return manifest


def _mark_paused(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    stage: PaperRunStage,
    *,
    uploads_dir: Optional[str | Path],
    message: str,
) -> PaperManifest:
    _clear_pause_request(paths)
    manifest.status = PaperRunStatus.paused
    manifest.current_stage = stage
    manifest.error_message = None
    manifest.finished_at = None
    _append_pause_log(
        paths,
        manifest,
        stage=stage,
        status=PaperRunStatus.paused.value,
        event="pipeline_paused",
        message=message,
    )
    save_manifest(manifest, uploads_dir=uploads_dir)
    return manifest


def _pause_before_stage_if_requested(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    stage: PaperRunStage,
    *,
    uploads_dir: Optional[str | Path],
) -> PaperManifest | None:
    if not _pause_requested(paths):
        return None
    return _mark_paused(
        paths,
        manifest,
        stage,
        uploads_dir=uploads_dir,
        message=f"Pause requested; stopped before stage {stage.value} started.",
    )


def _pause_after_stage_if_requested(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    stage: PaperRunStage,
    *,
    uploads_dir: Optional[str | Path],
) -> PaperManifest | None:
    if not _pause_requested(paths):
        return None
    return _mark_paused(
        paths,
        manifest,
        stage,
        uploads_dir=uploads_dir,
        message=f"Pause requested; paused after stage {stage.value} completed.",
    )


def _stage_index(stage: PaperRunStage) -> int:
    try:
        return _STAGE_ORDER.index(stage)
    except ValueError:
        return -1


def _coerce_stage(stage: str | PaperRunStage) -> PaperRunStage:
    stage_value = stage.value if isinstance(stage, PaperRunStage) else str(stage)
    if stage_value == PaperRunStage.created.value:
        return PaperRunStage.collecting
    if stage_value == PaperRunStage.failed.value:
        raise ValueError("failed is a terminal status, not an executable stage")
    try:
        stage_enum = PaperRunStage(stage_value)
    except ValueError as exc:
        allowed = ", ".join(s.value for s in _EXECUTABLE_STAGES)
        raise ValueError(f"Unknown paper stage {stage_value!r}. Allowed: {allowed}") from exc
    if stage_enum not in _EXECUTABLE_STAGES:
        allowed = ", ".join(s.value for s in _EXECUTABLE_STAGES)
        raise ValueError(f"Paper stage {stage_enum.value!r} cannot be rerun. Allowed: {allowed}")
    return stage_enum


def latest_failed_stage(manifest: PaperManifest) -> PaperRunStage | None:
    for entry in reversed(manifest.stage_log):
        if str(entry.get("status")) != "failed":
            continue
        try:
            stage = PaperRunStage(str(entry.get("stage")))
        except ValueError:
            continue
        if stage in _EXECUTABLE_STAGES:
            return stage
    return manifest.current_stage if manifest.current_stage in _EXECUTABLE_STAGES else None


def resolve_rerun_stage(manifest: PaperManifest, stage: str | PaperRunStage | None = None) -> PaperRunStage:
    if stage is not None:
        return _coerce_stage(stage)
    if manifest.current_stage == PaperRunStage.failed:
        failed_stage = latest_failed_stage(manifest)
        if failed_stage is not None:
            return failed_stage
    return _coerce_stage(manifest.current_stage)


def _artifact_belongs_to_stage(rel_path: str, stage: PaperRunStage) -> bool:
    prefixes = _STAGE_OUTPUT_PREFIXES.get(stage, ())
    return any(rel_path == prefix or rel_path.startswith(prefix) for prefix in prefixes)


def _existing_stage_artifacts(paths: PaperRunPaths, manifest: PaperManifest, stage: PaperRunStage) -> list[str]:
    rel_paths: set[str] = {
        rel_path
        for rel_path in manifest.artifact_index
        if _artifact_belongs_to_stage(rel_path, stage) and (paths.root / rel_path).exists()
    }
    if stage in {PaperRunStage.section_writing, PaperRunStage.refining} and paths.sections_dir.exists():
        rel_paths.update(
            path.relative_to(paths.root).as_posix()
            for path in sorted(paths.sections_dir.glob("*.tex"))
            if path.is_file()
        )
    if stage == PaperRunStage.literature_review and paths.refs_bib.exists():
        rel_paths.add(paths.refs_bib.relative_to(paths.root).as_posix())
    return sorted(rel_paths)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_hashes(paths: PaperRunPaths, rel_paths: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for rel_path in rel_paths:
        digest = _sha256(paths.root / rel_path)
        if digest:
            hashes[rel_path] = digest
    return hashes


def _snapshot_stage_outputs(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    stage: PaperRunStage,
    attempt_id: str,
) -> tuple[str | None, list[str], dict[str, str]]:
    rel_paths = _existing_stage_artifacts(paths, manifest, stage)
    hashes = _artifact_hashes(paths, rel_paths)
    if not rel_paths:
        return None, [], hashes

    snapshot_root = paths.drafts_dir / "rerun_snapshots" / attempt_id / stage.value
    for rel_path in rel_paths:
        src = paths.root / rel_path
        if not src.is_file():
            continue
        dst = snapshot_root / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return snapshot_root.relative_to(paths.root).as_posix(), rel_paths, hashes


def _attempts(manifest: PaperManifest) -> list[dict[str, Any]]:
    raw = getattr(manifest, "stage_attempts", None)
    if isinstance(raw, list):
        return raw
    attempts: list[dict[str, Any]] = []
    setattr(manifest, "stage_attempts", attempts)
    return attempts


def _latest_successful_attempt_id(manifest: PaperManifest, stage: PaperRunStage) -> str | None:
    for attempt in reversed(_attempts(manifest)):
        if attempt.get("stage") == stage.value and attempt.get("status") == "completed":
            attempt_id = attempt.get("attempt_id")
            return str(attempt_id) if attempt_id else None
    for entry in reversed(manifest.stage_log):
        if entry.get("stage") == stage.value and entry.get("status") == "completed":
            return f"legacy:{stage.value}:{entry.get('ts') or entry.get('finished_at') or 'unknown'}"
    return None


def _latest_successful_upstream_inputs(manifest: PaperManifest, stage: PaperRunStage) -> dict[str, str]:
    index = _stage_index(stage)
    if index <= 0:
        return {}
    inputs: dict[str, str] = {}
    for upstream in _STAGE_ORDER[:index]:
        attempt_id = _latest_successful_attempt_id(manifest, upstream)
        if attempt_id:
            inputs[upstream.value] = attempt_id
    return inputs


def _new_attempt_id(stage: PaperRunStage) -> str:
    return f"rerun_{stage.value}_{utc_now().strftime('%Y%m%dT%H%M%S%fZ')}"


def _append_attempt(manifest: PaperManifest, attempt: dict[str, Any]) -> None:
    _attempts(manifest).append(attempt)


def _mark_downstream_stale(manifest: PaperManifest, start_stage: PaperRunStage) -> list[str]:
    start = _stage_index(start_stage)
    stale: list[str] = []
    if start < 0:
        return stale
    affected = set(_STAGE_ORDER[start:])
    for rel_path, raw in manifest.artifact_index.items():
        if not isinstance(raw, dict):
            continue
        if any(_artifact_belongs_to_stage(rel_path, stage) for stage in affected):
            raw["stale"] = True
            stale.append(rel_path)
    return sorted(stale)


def _finish_after_rerun(
    paper_id: str,
    start_stage: PaperRunStage,
    *,
    uploads_dir: Optional[str | Path],
    config_path: Optional[str | Path],
) -> PaperManifest:
    if start_stage in _RERUN_TO_APPROVAL_STAGES:
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
                "message": "Rerun reached outline approval gate.",
            }
        )
        append_pipeline_event(
            PaperRunPaths.for_paper(paper_id),
            manifest,
            "rerun_outline_approval_pending",
            stage=PaperRunStage.outlining.value,
            status=PaperRunStatus.awaiting_outline_approval.value,
            started_at=now.isoformat(),
            finished_at=now.isoformat(),
            duration_ms=0,
            message="Rerun reached outline approval gate.",
        )
        save_manifest(manifest, uploads_dir=uploads_dir)
        return manifest

    return run_stage(
        paper_id,
        PaperRunStage.completed,
        uploads_dir=uploads_dir,
        config_path=config_path,
        message="Standalone paper-agent rerun completed.",
    )


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
    paused_manifest = _pause_before_stage_if_requested(
        paths,
        manifest,
        stage_enum,
        uploads_dir=uploads_dir,
    )
    if paused_manifest is not None:
        return paused_manifest

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
        append_pipeline_event(
            paths,
            manifest,
            "stage_started",
            stage=stage_enum.value,
            status="running",
            started_at=started_at.isoformat(),
            message=f"Stage {stage_enum.value} started.",
        )
        save_manifest(manifest, uploads_dir=uploads_dir)
        _execute_stage(paths, manifest, stage_enum)
        if stage_enum in _EXECUTABLE_STAGES:
            assert_stage_artifacts_ready(paths, manifest, stage_enum)
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
        append_pipeline_event(
            paths,
            manifest,
            "stage_completed",
            stage=stage_enum.value,
            status="completed",
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_ms=duration_ms,
            message=message or f"Stage {stage_enum.value} completed.",
        )
        paused_manifest = _pause_after_stage_if_requested(
            paths,
            manifest,
            stage_enum,
            uploads_dir=uploads_dir,
        )
        if paused_manifest is not None:
            return paused_manifest
    except Exception as exc:
        structured_error = error_payload(exc)
        diagnostics = inspect_paper_run(paths, manifest)
        failed_at = utc_now()
        duration_ms = max(0, int((failed_at - started_at).total_seconds() * 1000))
        manifest.status = PaperRunStatus.failed
        manifest.current_stage = stage_enum
        manifest.error_message = structured_error.get("message", str(exc))[:4000]
        manifest.finished_at = failed_at
        manifest.stage_log.append(
            {
                "stage": stage_enum.value,
                "status": "failed",
                "ts": failed_at.isoformat(),
                "started_at": started_at.isoformat(),
                "finished_at": failed_at.isoformat(),
                "duration_ms": duration_ms,
                "message": f"Stage {stage_enum.value} failed: {structured_error.get('message', str(exc))}",
                "error_code": error_code(exc),
                "error_message": structured_error.get("message", str(exc))[:4000],
                "artifact_issues": [issue.model_dump(mode="json") for issue in diagnostics.artifact_issues[:20]],
            }
        )
        append_pipeline_event(
            paths,
            manifest,
            "stage_failed",
            stage=stage_enum.value,
            status="failed",
            started_at=started_at.isoformat(),
            finished_at=failed_at.isoformat(),
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
            error_code=error_code(exc),
            error_message=structured_error.get("message", str(exc))[:4000],
            artifact_issues=[issue.model_dump(mode="json") for issue in diagnostics.artifact_issues[:20]],
            message=f"Stage {stage_enum.value} failed: {structured_error.get('message', str(exc))}",
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
        manifest = run_stage(
            paper_id,
            stage,
            uploads_dir=uploads_dir,
            config_path=config_path,
        )
        if manifest.status == PaperRunStatus.paused:
            return manifest
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
        manifest = run_stage(
            paper_id,
            stage,
            uploads_dir=uploads_dir,
            config_path=config_path,
        )
        if manifest.status == PaperRunStatus.paused:
            if stage == PaperRunStage.outlining and PaperRunPaths.for_paper(paper_id).outline_json.is_file():
                break
            return manifest

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
    append_pipeline_event(
        PaperRunPaths.for_paper(paper_id),
        manifest,
        "outline_approval_pending",
        stage=PaperRunStage.outlining.value,
        status=PaperRunStatus.awaiting_outline_approval.value,
        started_at=now.isoformat(),
        finished_at=now.isoformat(),
        duration_ms=0,
        message="Outline generated; awaiting user approval.",
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
        manifest = run_stage(
            paper_id,
            stage,
            uploads_dir=uploads_dir,
            config_path=config_path,
        )
        if manifest.status == PaperRunStatus.paused:
            return manifest
    return run_stage(
        paper_id,
        PaperRunStage.completed,
        uploads_dir=uploads_dir,
        config_path=config_path,
        message="Standalone paper-agent scaffold completed.",
    )


def run_render_export(
    paper_id: str,
    *,
    uploads_dir: Optional[str | Path] = None,
    config_path: Optional[str | Path] = None,
) -> PaperManifest:
    """Re-render final templates and export bundles from the current sections."""
    for stage in _STAGES_RENDER_EXPORT:
        manifest = run_stage(
            paper_id,
            stage,
            uploads_dir=uploads_dir,
            config_path=config_path,
        )
        if manifest.status == PaperRunStatus.paused:
            return manifest
    return run_stage(
        paper_id,
        PaperRunStage.completed,
        uploads_dir=uploads_dir,
        config_path=config_path,
        message="Standalone paper-agent render/export completed.",
    )


def run_from_stage(
    paper_id: str,
    stage: str | PaperRunStage,
    *,
    uploads_dir: Optional[str | Path] = None,
    config_path: Optional[str | Path] = None,
) -> PaperManifest:
    """Rerun one executable stage with successful upstream history loaded.

    The stage implementation reads its upstream artifacts from the run directory.
    This wrapper records which upstream attempts were treated as inputs, snapshots
    the selected stage outputs before overwriting them, and then reruns all
    downstream stages needed to keep the paper consistent.
    """
    configure_uploads_dir(uploads_dir)
    _ensure_run_from_config(paper_id, config_path, uploads_dir=uploads_dir)
    start_stage = _coerce_stage(stage)
    manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    attempt_id = _new_attempt_id(start_stage)
    started_at = utc_now()
    snapshot_path, snapshotted_artifacts, input_hashes = _snapshot_stage_outputs(
        paths,
        manifest,
        start_stage,
        attempt_id,
    )
    stale_artifacts = _mark_downstream_stale(manifest, start_stage)
    input_attempts = _latest_successful_upstream_inputs(manifest, start_stage)
    supersedes_attempt_id = _latest_successful_attempt_id(manifest, start_stage)

    attempt: dict[str, Any] = {
        "attempt_id": attempt_id,
        "stage": start_stage.value,
        "kind": "rerun",
        "requested_stage": start_stage.value,
        "status": "running",
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "input_attempts": input_attempts,
        "input_artifact_hashes": input_hashes,
        "output_artifacts_before": snapshotted_artifacts,
        "snapshot_path": snapshot_path,
        "supersedes_attempt_id": supersedes_attempt_id,
        "stale_artifacts": stale_artifacts,
        "error_message": None,
    }
    _append_attempt(manifest, attempt)
    manifest.status = PaperRunStatus.running
    manifest.current_stage = start_stage
    manifest.error_message = None
    manifest.finished_at = None
    manifest.stage_log.append(
        {
            "stage": start_stage.value,
            "status": "rerun_started",
            "ts": started_at.isoformat(),
            "started_at": started_at.isoformat(),
            "finished_at": None,
            "duration_ms": None,
            "message": f"Rerun from {start_stage.value} started with successful upstream history loaded.",
            "attempt_id": attempt_id,
            "input_attempts": input_attempts,
            "snapshot_path": snapshot_path,
        }
    )
    append_pipeline_event(
        paths,
        manifest,
        "rerun_started",
        stage=start_stage.value,
        status="running",
        attempt_id=attempt_id,
        input_attempts=input_attempts,
        snapshot_path=snapshot_path,
        stale_artifact_count=len(stale_artifacts),
        message=f"Rerun from {start_stage.value} started with successful upstream history loaded.",
    )
    save_manifest(manifest, uploads_dir=uploads_dir)

    try:
        start_index = _STAGE_ORDER.index(start_stage)
        stages = _STAGE_ORDER[start_index:]
        if start_stage in _RERUN_TO_APPROVAL_STAGES:
            stages = tuple(stage for stage in stages if stage in _STAGES_UNTIL_OUTLINE)
        for stage_enum in stages:
            manifest = run_stage(
                paper_id,
                stage_enum,
                uploads_dir=uploads_dir,
                config_path=config_path,
            )
            if manifest.status == PaperRunStatus.paused:
                break
        else:
            manifest = _finish_after_rerun(
                paper_id,
                start_stage,
                uploads_dir=uploads_dir,
                config_path=config_path,
            )
    except Exception as exc:
        manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
        for item in reversed(_attempts(manifest)):
            if item.get("attempt_id") == attempt_id:
                item["status"] = "failed"
                item["finished_at"] = utc_now().isoformat()
                item["error_message"] = str(exc)[:4000]
                break
        save_manifest(manifest, uploads_dir=uploads_dir)
        raise

    for item in reversed(_attempts(manifest)):
        if item.get("attempt_id") == attempt_id:
            output_artifacts = _existing_stage_artifacts(paths, manifest, start_stage)
            item["status"] = "paused" if manifest.status == PaperRunStatus.paused else "completed"
            item["finished_at"] = utc_now().isoformat()
            item["output_artifacts"] = output_artifacts
            item["output_artifact_hashes"] = _artifact_hashes(paths, output_artifacts)
            item["error_message"] = None
            break
    save_manifest(manifest, uploads_dir=uploads_dir)
    return manifest


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
