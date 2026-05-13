"""
Paper-generation API endpoints.

M1 surface (just enough to satisfy the M1 exit criteria):

  POST   /papers                              create a run
  GET    /papers                              list runs visible to user
  GET    /papers/{paper_id}                   get run summary
  DELETE /papers/{paper_id}                   delete a run + on-disk artifacts
  GET    /papers/{paper_id}/files/{path}      download artifact (allowlist + path safety)

Subsequent milestones add `/sections/...` regenerate, `/export?template=...`,
SSE progress, etc.

The route file deliberately keeps business logic thin — DB access goes through
`PaperGenerationRunRepository`, filesystem through `PaperRunPaths`, and the
worker queue through `task_dispatch.enqueue_task_descriptor`.
"""

from __future__ import annotations

import hashlib
import logging
import json
import shutil
import uuid
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pathlab_paper_agent.bootstrap import ensure_server_on_path

ensure_server_on_path()

from backend.auth import current_active_user, User  # noqa: E402
from backend.database import get_db  # noqa: E402
from backend.database.repositories import PaperGenerationRunRepository  # noqa: E402

from pathlab_paper_agent.schemas import (  # noqa: E402
    CreatePaperRequest,
    OutlineApprovalRequest,
    PaperConfig,
    PaperManifest,
    PaperRunArtifact,
    PaperRunCreateResponse,
    PaperRunDetail,
    PaperRunListResponse,
    PaperRunStage,
    PaperRunStatus,
    PaperRunSummary,
    PaperSectionRegenerateAcceptedResponse,
    PaperSection,
    PaperSectionListResponse,
    PaperSectionRegenerateResponse,
    RegenerateJobEntry,
    RegenerateRejectRequest,
    RegenerateRejectResponse,
    RegenerateSectionRequest,
    GuardIssueSummary,
    GuardResultSummary,
    RefinementSummary,
    ValidationSummary,
)
from pathlab_paper_agent.regenerate import (  # noqa: E402
    MissingSectionDraftError,
    RegenerateJobNotFoundError,
    RegenerateStateError,
    SelectionLocatorError,
    UnknownSectionError,
    cancel_regenerate,
    get_regenerate_job,
    latest_regenerate_log_summary,
    reject_regenerate,
    regenerate_section,
)
from pathlab_paper_agent.scaffold import initialize_paper_run  # noqa: E402
from pathlab_paper_agent.storage import (  # noqa: E402
    PaperRunPaths,
    is_path_allowed_for_download,
    safe_resolve,
    validate_paper_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/papers", tags=["Paper Generation"])

_SECTION_ORDER = {
    "abstract": 0,
    "introduction": 1,
    "related_work": 2,
    "methods": 3,
    "experiments": 4,
    "results": 5,
    "discussion": 6,
    "conclusion": 7,
}
_VALIDATION_GUARD_REPORT_PATHS = {
    "metric_guard": "validation/metric_guard.json",
    "identifier_guard": "validation/identifier_guard.json",
    "latex_guard": "validation/latex_guard.json",
    "citation_guard": "validation/citation_guard.json",
    "claim_guard": "validation/claim_guard.json",
    "consistency_guard": "validation/consistency_guard.json",
}
_VALIDATION_WARNINGS_PATH = "validation/warnings.md"
_REFINEMENT_LOG_PATH = "validation/refinement_log.json"
_MAX_SAMPLE_ISSUES = 3
_RUN_UNTIL_OUTLINE_HANDLER = "paper_generation.run_until_outline"
_RUN_AFTER_OUTLINE_HANDLER = "paper_generation.run_after_outline"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_paper_id() -> str:
    """Short, file-system-safe id."""
    return f"paper_{uuid.uuid4().hex[:16]}"


def _row_to_summary(row, manifest: Optional[PaperManifest] = None) -> PaperRunSummary:
    row_status = PaperRunStatus(row.status)
    manifest_is_initial = (
        manifest is not None
        and manifest.status == PaperRunStatus.pending
        and manifest.current_stage == PaperRunStage.created
    )
    use_manifest_state = manifest is not None and not (
        row_status
        in {PaperRunStatus.completed, PaperRunStatus.failed, PaperRunStatus.cancelled}
        and manifest.status == PaperRunStatus.running
    ) and not (
        row_status == PaperRunStatus.running and manifest_is_initial
    )
    status = manifest.status if use_manifest_state and manifest is not None else row_status
    current_stage = (
        manifest.current_stage
        if use_manifest_state and manifest is not None
        else PaperRunStage(row.current_stage)
    )
    finished_at = (
        manifest.finished_at
        if use_manifest_state and manifest is not None
        else row.finished_at
    )
    error_message = (
        manifest.error_message
        if use_manifest_state and manifest is not None
        else row.error_message
    )

    return PaperRunSummary(
        paper_id=row.paper_id,
        status=status,
        current_stage=current_stage,
        title=row.title,
        selected_templates=row.selected_templates or [],
        source_task_ids=row.source_task_ids or [],
        created_at=row.created_at,
        finished_at=finished_at,
        error_message=error_message,
    )


def _load_manifest(paths: PaperRunPaths) -> Optional[PaperManifest]:
    if not paths.manifest.exists():
        return None
    try:
        return PaperManifest.model_validate(
            json.loads(paths.manifest.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        logger.warning(
            "paper_generation: failed to parse manifest for %s: %s",
            paths.paper_id,
            exc,
        )
        return None


def _save_manifest(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    manifest.updated_at = datetime.now(UTC)
    paths.manifest.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


async def _enqueue_regenerate_descriptor(
    *,
    paper_id: str,
    regen_id: str,
    section_name: str,
    body: RegenerateSectionRequest,
) -> None:
    from gateway.task_dispatch import build_task_descriptor, enqueue_task_descriptor

    descriptor = build_task_descriptor(
        job_id=regen_id,
        job_kind="paper_generation",
        handler="paper_generation.regenerate_section",
        payload={
            "paper_id": paper_id,
            "regen_id": regen_id,
            "section_name": section_name,
            **body.model_dump(mode="json", exclude_none=True),
        },
    )
    await enqueue_task_descriptor(descriptor)


async def _enqueue_paper_generation_job(paper_id: str, handler: str):
    from gateway.task_dispatch import build_task_descriptor, enqueue_task_descriptor

    descriptor = build_task_descriptor(
        job_id=paper_id,
        job_kind="paper_generation",
        handler=handler,
        payload={"paper_id": paper_id},
    )
    await enqueue_task_descriptor(descriptor)
    return descriptor


def _artifact_from_index(rel_path: str, raw) -> PaperRunArtifact:
    if isinstance(raw, dict):
        payload = {"path": rel_path, **raw}
    else:
        payload = {"path": rel_path, "status": str(raw)}
    return PaperRunArtifact.model_validate(payload)


def _public_artifacts(manifest: Optional[PaperManifest]) -> list[PaperRunArtifact]:
    if manifest is None:
        return []
    artifacts: list[PaperRunArtifact] = []
    for rel_path, raw in manifest.artifact_index.items():
        artifact = _artifact_from_index(rel_path, raw)
        if (
            artifact.visibility == "public"
            and artifact.downloadable
            and is_path_allowed_for_download(artifact.path)
        ):
            artifacts.append(artifact)
    return artifacts


def _load_json_file(path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("paper_generation: failed to read JSON %s: %s", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _guard_result_summary(paths: PaperRunPaths, guard: str, rel_path: str) -> GuardResultSummary | None:
    report = _load_json_file(paths.root / rel_path)
    if not report:
        return None
    raw_issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    issues = [issue for issue in raw_issues if isinstance(issue, dict)]
    error_count = sum(1 for issue in issues if str(issue.get("severity") or "error") == "error")
    warning_count = sum(1 for issue in issues if str(issue.get("severity") or "") == "warning")
    sample_issues: list[GuardIssueSummary] = []
    for issue in issues[:_MAX_SAMPLE_ISSUES]:
        sample_issues.append(
            GuardIssueSummary(
                code=str(issue.get("code") or "unknown"),
                message=str(issue.get("message") or ""),
                severity=str(issue.get("severity") or "error"),
                path=issue.get("path") if isinstance(issue.get("path"), str) else None,
                context=issue.get("context") if isinstance(issue.get("context"), str) else None,
            )
        )
    return GuardResultSummary(
        guard=str(report.get("guard") or guard),
        status=str(report.get("status") or ("fail" if error_count else "pass")),
        issue_count=len(issues),
        error_count=error_count,
        warning_count=warning_count,
        path=rel_path,
        sample_issues=sample_issues,
    )


def _score_total(score: object) -> float | None:
    if not isinstance(score, dict):
        return None
    value = score.get("total")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _refinement_summary(paths: PaperRunPaths) -> RefinementSummary | None:
    payload = _load_json_file(paths.root / _REFINEMENT_LOG_PATH)
    if not payload:
        return None
    iterations = payload.get("iterations") if isinstance(payload.get("iterations"), list) else []
    score_candidates = [
        item.get("score")
        for item in iterations
        if isinstance(item, dict) and isinstance(item.get("score"), dict)
    ]
    final_score = score_candidates[-1] if score_candidates else payload.get("initial_score")
    accepted = payload.get("accepted_iterations") if isinstance(payload.get("accepted_iterations"), list) else []
    accepted_iterations = []
    for item in accepted:
        try:
            accepted_iterations.append(int(item))
        except (TypeError, ValueError):
            continue
    return RefinementSummary(
        final_status=payload.get("final_status") if isinstance(payload.get("final_status"), str) else None,
        max_iterations=payload.get("max_iterations") if isinstance(payload.get("max_iterations"), int) else None,
        accepted_iterations=accepted_iterations,
        iteration_count=len(iterations),
        initial_score=payload.get("initial_score") if isinstance(payload.get("initial_score"), dict) else None,
        final_score=final_score if isinstance(final_score, dict) else None,
        log_path=_REFINEMENT_LOG_PATH,
    )


def _validation_summary(paths: PaperRunPaths) -> ValidationSummary:
    guards = [
        summary
        for guard, rel_path in _VALIDATION_GUARD_REPORT_PATHS.items()
        if (summary := _guard_result_summary(paths, guard, rel_path)) is not None
    ]
    refinement = _refinement_summary(paths)
    hybrid_score = _score_total(refinement.final_score) if refinement is not None else None
    warnings_path = _VALIDATION_WARNINGS_PATH if (paths.root / _VALIDATION_WARNINGS_PATH).is_file() else None
    return ValidationSummary(
        m10_guards=guards,
        refinement=refinement,
        hybrid_score=hybrid_score,
        warnings_md_path=warnings_path,
    )


def _is_registered_public_artifact(
    manifest: Optional[PaperManifest], rel_path: str
) -> bool:
    if manifest is None:
        return False
    raw = manifest.artifact_index.get(rel_path)
    if raw is None:
        return False
    artifact = _artifact_from_index(rel_path, raw)
    return (
        artifact.visibility == "public"
        and artifact.downloadable
        and artifact.status in {"ready", "generated", "completed"}
    )


async def _load_or_404(db: AsyncSession, paper_id: str, user: User):
    validate_paper_id(paper_id)
    row = await PaperGenerationRunRepository.get_by_id(db, paper_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
    if row.user_id and not _is_owner_or_admin(row, user):
        raise HTTPException(status_code=403, detail="Forbidden")
    return row


def _is_owner_or_admin(row, user: User) -> bool:
    if getattr(user, "is_superuser", False) or getattr(user, "role", "") == "admin":
        return True
    return row.user_id == str(user.id)


def _section_sort_key(section: PaperSection) -> tuple[int, str]:
    return (_SECTION_ORDER.get(section.section_name, 999), section.section_name)


def _section_from_file(paths: PaperRunPaths, path) -> PaperSection:
    text = path.read_text(encoding="utf-8")
    rel_path = path.relative_to(paths.root).as_posix()
    stat = path.stat()
    return PaperSection(
        section_name=path.stem,
        path=rel_path,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
        editable=True,
        updated_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
    )


def _public_sections(paths: PaperRunPaths, manifest: Optional[PaperManifest]) -> list[PaperSection]:
    if manifest is None or not paths.sections_dir.is_dir():
        return []
    sections: list[PaperSection] = []
    for path in sorted(paths.sections_dir.glob("*.tex")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(paths.root).as_posix()
        if not is_path_allowed_for_download(rel_path):
            continue
        if not _is_registered_public_artifact(manifest, rel_path):
            continue
        sections.append(_section_from_file(paths, path))
    return sorted(sections, key=_section_sort_key)


# ---------------------------------------------------------------------------
# POST /papers — create a run
# ---------------------------------------------------------------------------

@router.post("", response_model=PaperRunCreateResponse)
async def create_paper_run(
    body: CreatePaperRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PaperRunCreateResponse:
    """Create a paper run row, scaffold its filesystem, and (M2+) enqueue the
    worker job. M1 only does the first two steps; the worker hook is a stub.
    """
    if not body.source_tasks:
        raise HTTPException(
            status_code=400,
            detail="source_tasks must contain at least one task_id.",
        )
    if not body.selected_templates:
        raise HTTPException(
            status_code=400,
            detail="selected_templates must contain at least one template.",
        )
    if len(body.selected_templates) != 1:
        raise HTTPException(
            status_code=400,
            detail="selected_templates must contain exactly one target template.",
        )

    paper_id = _new_paper_id()
    config = PaperConfig(
        paper_id=paper_id,
        title=body.title,
        paper_type=body.paper_type,
        language=body.language,
        source_tasks=body.source_tasks,
        selected_templates=body.selected_templates,
        include_external_validation=body.include_external_validation,
        user_idea=body.user_idea,
    )

    # 1. Insert DB row
    await PaperGenerationRunRepository.create(
        db,
        paper_id=paper_id,
        user_id=str(user.id),
        title=body.title,
        status=PaperRunStatus.pending.value,
        current_stage=PaperRunStage.created.value,
        config_json=body.model_dump(mode="json"),
        source_task_ids=[t.task_id for t in body.source_tasks],
        selected_templates=[t.value for t in body.selected_templates],
    )
    await db.commit()

    # 2. Scaffold on-disk run directory + manifest + config
    try:
        await initialize_paper_run(db, config)
    except Exception as exc:
        # Don't leave a half-created run around: mark failed.
        await PaperGenerationRunRepository.mark_failed(
            db, paper_id, f"scaffold failed: {exc}"
        )
        await db.commit()
        logger.exception("paper_generation: scaffold failed for %s", paper_id)
        raise HTTPException(
            status_code=500, detail=f"Failed to scaffold paper run: {exc}"
        )

    # 3. Enqueue the pre-approval worker job. It pauses after outlining.
    enqueued = False
    try:
        await _enqueue_paper_generation_job(paper_id, _RUN_UNTIL_OUTLINE_HANDLER)
        enqueued = True
        logger.info("paper_generation: enqueued outline-gated run %s", paper_id)
    except Exception as exc:
        # Keep local/dev setups robust when Redis is not running yet.
        logger.warning(
            "paper_generation: created %s but could not enqueue worker descriptor: %s",
            paper_id,
            exc,
        )

    logger.info(
        "paper_generation: created run %s for user %s",
        paper_id, user.id,
    )

    return PaperRunCreateResponse(
        paper_id=paper_id,
        message=(
            "Paper run accepted; processing in background."
            if enqueued
            else "Paper run created; worker enqueue was skipped or unavailable."
        ),
    )


# ---------------------------------------------------------------------------
# GET /papers — list runs
# ---------------------------------------------------------------------------

@router.get("", response_model=PaperRunListResponse)
async def list_paper_runs(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> PaperRunListResponse:
    user_filter = None if _is_admin(user) else str(user.id)
    rows, total = await PaperGenerationRunRepository.list_for_user(
        db, user_filter, limit=limit, offset=offset
    )
    items = []
    for row in rows:
        manifest = _load_manifest(PaperRunPaths.for_paper(row.paper_id))
        items.append(_row_to_summary(row, manifest))
    return PaperRunListResponse(
        items=items,
        total=total,
    )


def _is_admin(user: User) -> bool:
    return bool(
        getattr(user, "is_superuser", False)
        or getattr(user, "role", "") == "admin"
    )


# ---------------------------------------------------------------------------
# GET /papers/{paper_id} — detail
# ---------------------------------------------------------------------------

@router.get("/{paper_id}", response_model=PaperRunDetail)
async def get_paper_run(
    paper_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PaperRunDetail:
    row = await _load_or_404(db, paper_id, user)
    paths = PaperRunPaths.for_paper(paper_id)
    manifest = _load_manifest(paths)
    summary = _row_to_summary(row, manifest)
    return PaperRunDetail(
        **summary.model_dump(),
        artifacts=_public_artifacts(manifest),
        stage_log=manifest.stage_log if manifest is not None else [],
        validation_summary=_validation_summary(paths),
    )


# ---------------------------------------------------------------------------
# PUT /papers/{paper_id}/outline — save/approve editable outline
# ---------------------------------------------------------------------------

@router.put("/{paper_id}/outline")
async def update_paper_outline(
    paper_id: str,
    body: OutlineApprovalRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    row = await _load_or_404(db, paper_id, user)
    if row.status != PaperRunStatus.awaiting_outline_approval.value:
        raise HTTPException(
            status_code=422,
            detail=f"outline cannot be edited at status {row.status}",
        )

    paths = PaperRunPaths.for_paper(paper_id)
    manifest = _load_manifest(paths)
    if manifest is None:
        raise HTTPException(
            status_code=500,
            detail=f"manifest.json not found for paper {paper_id}",
        )

    paths.outline_json.parent.mkdir(parents=True, exist_ok=True)
    paths.outline_json.write_text(
        json.dumps(body.outline.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if not body.approve:
        manifest.status = PaperRunStatus.awaiting_outline_approval
        manifest.current_stage = PaperRunStage.outlining
        manifest.error_message = None
        _save_manifest(paths, manifest)
        await PaperGenerationRunRepository.update(
            db,
            paper_id,
            status=PaperRunStatus.awaiting_outline_approval.value,
            current_stage=PaperRunStage.outlining.value,
            error_message=None,
            finished_at=None,
        )
        await db.commit()
        return {
            "paper_id": paper_id,
            "approved": False,
            "current_stage": PaperRunStage.outlining.value,
        }

    now = datetime.now(UTC)
    manifest.status = PaperRunStatus.running
    manifest.current_stage = PaperRunStage.plotting
    manifest.error_message = None
    manifest.finished_at = None
    manifest.stage_log.append(
        {
            "stage": PaperRunStage.outlining.value,
            "status": "approved",
            "ts": now.isoformat(),
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "duration_ms": 0,
            "message": "Outline approved by user.",
        }
    )
    _save_manifest(paths, manifest)
    await PaperGenerationRunRepository.update(
        db,
        paper_id,
        status=PaperRunStatus.running.value,
        current_stage=PaperRunStage.plotting.value,
        error_message=None,
        finished_at=None,
    )
    await db.commit()

    try:
        await _enqueue_paper_generation_job(paper_id, _RUN_AFTER_OUTLINE_HANDLER)
    except Exception as exc:
        logger.exception("paper_generation: failed to enqueue post-outline job for %s", paper_id)
        if (
            manifest.stage_log
            and manifest.stage_log[-1].get("status") == "approved"
            and manifest.stage_log[-1].get("message") == "Outline approved by user."
        ):
            manifest.stage_log.pop()
        manifest.status = PaperRunStatus.awaiting_outline_approval
        manifest.current_stage = PaperRunStage.outlining
        manifest.error_message = f"post-outline enqueue failed: {exc}"
        _save_manifest(paths, manifest)
        await PaperGenerationRunRepository.update(
            db,
            paper_id,
            status=PaperRunStatus.awaiting_outline_approval.value,
            current_stage=PaperRunStage.outlining.value,
            error_message=manifest.error_message,
            finished_at=None,
        )
        await db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to enqueue post-outline paper job: {exc}",
        ) from exc

    return {
        "paper_id": paper_id,
        "approved": True,
        "current_stage": PaperRunStage.plotting.value,
    }


# ---------------------------------------------------------------------------
# GET /papers/{paper_id}/sections — editable public section text
# ---------------------------------------------------------------------------

@router.get("/{paper_id}/sections", response_model=PaperSectionListResponse)
async def get_paper_sections(
    paper_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PaperSectionListResponse:
    await _load_or_404(db, paper_id, user)
    paths = PaperRunPaths.for_paper(paper_id)
    manifest = _load_manifest(paths)
    return PaperSectionListResponse(sections=_public_sections(paths, manifest))


# ---------------------------------------------------------------------------
# POST /papers/{paper_id}/sections/{section_name}/regenerate
# ---------------------------------------------------------------------------

@router.post(
    "/{paper_id}/sections/{section_name}/regenerate",
    response_model=None,
)
async def regenerate_paper_section(
    paper_id: str,
    section_name: str,
    body: RegenerateSectionRequest | None = None,
    sync: bool = Query(False),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PaperSectionRegenerateResponse | JSONResponse:
    await _load_or_404(db, paper_id, user)
    request = body or RegenerateSectionRequest()
    # TODO(deprecate 2026-06-05): keep sync=true for one frontend transition window.
    if not sync:
        paths = PaperRunPaths.for_paper(paper_id)
        manifest = _load_manifest(paths)
        if manifest is None:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        regen_id = f"reg_{uuid.uuid4().hex[:12]}"
        enqueued_at = datetime.now(UTC)
        manifest.regenerate_jobs.append(
            {
                "regen_id": regen_id,
                "mode": request.mode,
                "section_name": request.target_section or section_name,
                "target_paragraph": request.target_paragraph,
                "target_sentence": request.target_sentence,
                "selected_text": request.selected_text,
                "source_hash": request.source_hash,
                "user_note": request.user_note,
                "template_id": request.template_id.value if request.template_id else None,
                "status": "queued",
                "enqueued_at": enqueued_at.isoformat(),
                "error_code": None,
                "error_message": None,
                "progress": {
                    "step": "queued",
                    "detail": "Regenerate job queued.",
                    "percent": 0,
                    "updated_at": enqueued_at.isoformat(),
                },
            }
        )
        _save_manifest(paths, manifest)
        try:
            await _enqueue_regenerate_descriptor(
                paper_id=paper_id,
                regen_id=regen_id,
                section_name=section_name,
                body=request,
            )
        except Exception as exc:
            manifest = _load_manifest(paths) or manifest
            for entry in manifest.regenerate_jobs:
                if entry.get("regen_id") == regen_id:
                    entry["status"] = "failed"
                    entry["finished_at"] = datetime.now(UTC).isoformat()
                    entry["error_code"] = "enqueue_failed"
                    entry["error_message"] = str(exc)
                    break
            _save_manifest(paths, manifest)
            raise HTTPException(status_code=503, detail=f"Failed to enqueue regenerate job: {exc}") from exc
        accepted = PaperSectionRegenerateAcceptedResponse(
            paper_id=paper_id,
            regen_id=regen_id,
            enqueued_at=enqueued_at,
        )
        return JSONResponse(status_code=202, content=accepted.model_dump(mode="json"))

    try:
        manifest = regenerate_section(
            paper_id,
            section_name,
            regen_id=f"reg_{uuid.uuid4().hex[:12]}",
            mode=request.mode,
            target_section=request.target_section,
            target_paragraph=request.target_paragraph,
            target_sentence=request.target_sentence,
            selected_text=request.selected_text,
            source_hash=request.source_hash,
            char_start=request.char_start,
            char_end=request.char_end,
            user_note=request.user_note,
            template_id=request.template_id,
        )
        summary = latest_regenerate_log_summary(paper_id)
    except SelectionLocatorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail())
    except MissingSectionDraftError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
    except UnknownSectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PaperSectionRegenerateResponse(
        paper_id=paper_id,
        status=manifest.status,
        current_stage=manifest.current_stage,
        regen_id=summary.get("regen_id"),
        regenerated_sections=summary.get("regenerated_sections", []),
        refinement_log_summary=summary.get("refinement_log_summary", {}),
    )


@router.get("/{paper_id}/regen/{regen_id}", response_model=RegenerateJobEntry)
async def get_regenerate_job_status(
    paper_id: str,
    regen_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> RegenerateJobEntry:
    await _load_or_404(db, paper_id, user)
    try:
        return get_regenerate_job(paper_id, regen_id)
    except RegenerateJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{paper_id}/regen/{regen_id}:reject", response_model=RegenerateRejectResponse)
async def reject_regenerate_job(
    paper_id: str,
    regen_id: str,
    body: RegenerateRejectRequest | None = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> RegenerateRejectResponse:
    await _load_or_404(db, paper_id, user)
    try:
        _manifest, payload = reject_regenerate(
            paper_id,
            regen_id,
            reason=(body.reason if body else None),
            template_id=(body.template_id if body else None),
        )
    except RegenerateJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RegenerateStateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail())
    return RegenerateRejectResponse.model_validate(payload)


@router.post("/{paper_id}/regen/{regen_id}:cancel")
async def cancel_regenerate_job(
    paper_id: str,
    regen_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await _load_or_404(db, paper_id, user)
    try:
        return cancel_regenerate(paper_id, regen_id)
    except RegenerateJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RegenerateStateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail())


# ---------------------------------------------------------------------------
# DELETE /papers/{paper_id}
# ---------------------------------------------------------------------------

@router.delete("/{paper_id}")
async def delete_paper_run(
    paper_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _load_or_404(db, paper_id, user)

    # 1. Remove DB row first (idempotent on rerun if FS removal fails)
    await PaperGenerationRunRepository.delete_by_id(db, paper_id)
    await db.commit()

    # 2. Remove on-disk artifacts. Failure here is logged but not surfaced.
    try:
        paths = PaperRunPaths.for_paper(paper_id)
        if paths.root.exists():
            shutil.rmtree(paths.root)
    except Exception as exc:
        logger.warning(
            "paper_generation: failed to remove artifacts for %s: %s",
            paper_id, exc,
        )

    return {"paper_id": paper_id, "deleted": True}


# ---------------------------------------------------------------------------
# GET /papers/{paper_id}/files/{path:path} — allowlisted download
# ---------------------------------------------------------------------------

@router.get("/{paper_id}/files")
async def download_paper_file_by_query(
    paper_id: str,
    path: str = Query(...),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await _download_paper_file_impl(paper_id, path, user, db)


@router.get("/{paper_id}/files/{path:path}")
async def download_paper_file(
    paper_id: str,
    path: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await _download_paper_file_impl(paper_id, path, user, db)


async def _download_paper_file_impl(
    paper_id: str,
    path: str,
    user: User,
    db: AsyncSession,
):
    """Serve a single artifact under `uploads/paper_generation/{paper_id}/{path}`.

    §3.7 enforcement (in order):
      1. paper_id valid
      2. user owns this paper or is admin
      3. relative path is on the allowlist (no `evidence_lock.private.json`,
         no `inputs/source_tasks.json`, no `drafts/intro_rw_draft/...`, etc.)
      4. resolved filesystem path is inside the run root (no symlink escape,
         no `..`, no hidden files)
      5. file actually exists
    """
    await _load_or_404(db, paper_id, user)
    paths = PaperRunPaths.for_paper(paper_id)
    manifest = _load_manifest(paths)

    # Step 3: allowlist lives in `storage.is_path_allowed_for_download`.
    if not is_path_allowed_for_download(path):
        raise HTTPException(status_code=403, detail="Path not in download allowlist.")

    # Step 4: resolve safely.
    try:
        target = safe_resolve(paths, path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not _is_registered_public_artifact(manifest, path):
        raise HTTPException(status_code=403, detail="Artifact is not registered public.")

    # Step 5: file must exist and be a regular file.
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory.")

    return FileResponse(target)
