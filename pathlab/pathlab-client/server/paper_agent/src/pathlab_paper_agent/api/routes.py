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
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pathlab_paper_agent.bootstrap import ensure_server_on_path

ensure_server_on_path()

from backend.auth import current_active_user, User  # noqa: E402
from backend.database import get_db  # noqa: E402
from backend.database.repositories import PaperGenerationRunRepository  # noqa: E402

from pathlab_paper_agent.schemas import (  # noqa: E402
    CreatePaperRequest,
    PaperConfig,
    PaperManifest,
    PaperRunArtifact,
    PaperRunCreateResponse,
    PaperRunDetail,
    PaperRunListResponse,
    PaperRunStage,
    PaperRunStatus,
    PaperRunSummary,
    PaperSection,
    PaperSectionListResponse,
    PaperSectionRegenerateResponse,
)
from pathlab_paper_agent.regenerate import (  # noqa: E402
    MissingSectionDraftError,
    UnknownSectionError,
    latest_regenerate_log_summary,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_paper_id() -> str:
    """Short, file-system-safe id."""
    return f"paper_{uuid.uuid4().hex[:16]}"


def _row_to_summary(row) -> PaperRunSummary:
    return PaperRunSummary(
        paper_id=row.paper_id,
        status=PaperRunStatus(row.status),
        current_stage=PaperRunStage(row.current_stage),
        title=row.title,
        selected_templates=row.selected_templates or [],
        source_task_ids=row.source_task_ids or [],
        created_at=row.created_at,
        finished_at=row.finished_at,
        error_message=row.error_message,
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

    # 3. M2+ will enqueue worker here. M1 stops at scaffold.
    enqueued = False
    try:
        from gateway.task_dispatch import build_task_descriptor, enqueue_task_descriptor

        descriptor = build_task_descriptor(
            job_id=paper_id,
            job_kind="paper_generation",
            handler="paper_generation.run",
            payload={"paper_id": paper_id},
        )
        await enqueue_task_descriptor(descriptor)
        enqueued = True
        logger.info("paper_generation: enqueued run %s", paper_id)
    except Exception as exc:
        # Keep M1 robust in local/dev setups that do not have Redis running yet.
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
    return PaperRunListResponse(
        items=[_row_to_summary(r) for r in rows],
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
    summary = _row_to_summary(row)
    manifest = _load_manifest(PaperRunPaths.for_paper(paper_id))
    return PaperRunDetail(
        **summary.model_dump(),
        artifacts=_public_artifacts(manifest),
        stage_log=manifest.stage_log if manifest is not None else [],
        validation_summary=None,
    )

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
    response_model=PaperSectionRegenerateResponse,
)
async def regenerate_paper_section(
    paper_id: str,
    section_name: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PaperSectionRegenerateResponse:
    await _load_or_404(db, paper_id, user)
    try:
        manifest = regenerate_section(paper_id, section_name)
        summary = latest_regenerate_log_summary(paper_id)
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
        regenerated_sections=summary.get("regenerated_sections", []),
        refinement_log_summary=summary.get("refinement_log_summary", {}),
    )


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
