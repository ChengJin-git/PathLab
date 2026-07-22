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
import json
import logging
import os
import re
import shutil
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pathlab_paper_agent.bootstrap import ensure_server_on_path

ensure_server_on_path()

from backend.auth import current_active_user, get_user_from_header_or_param, User  # noqa: E402
from backend.database import get_db  # noqa: E402
from backend.database.repositories import PaperGenerationRunRepository  # noqa: E402

from pathlab_paper_agent.schemas import (  # noqa: E402
    AddCitationPreview,
    AddCitationRequest,
    AddCitationResponse,
    CitationCoverageSummary,
    CitationDeleteResponse,
    CitationReference as CitationReferenceSchema,
    CitationsView,
    CreatePaperRequest,
    OutlineApprovalRequest,
    PaperConfig,
    PaperManifest,
    PaperRunDiagnostics,
    PaperRunArtifact,
    PaperRunCreateResponse,
    PaperRunDetail,
    PaperRunListResponse,
    PaperRunStage,
    PaperRunStatus,
    PaperStageRerunRequest,
    PaperRunSummary,
    PaperSectionRegenerateAcceptedResponse,
    PaperSection,
    PaperSectionListResponse,
    PaperSectionRegenerateResponse,
    PaperSectionUpdateRequest,
    PaperSectionUpdateResponse,
    RegenerateJobEntry,
    RegenerateRejectRequest,
    RegenerateRejectResponse,
    RegenerateSectionRequest,
    GuardResultSummary,
    RefinementSummary,
    ValidationSummary,
    VerifiedPoolRejection,
    VerifiedPoolSummary,
)
from pathlab_paper_agent.citations import generate_bibtex, make_unique_key  # noqa: E402
from pathlab_paper_agent.citations.manual_add import (  # noqa: E402
    ManualCitationError,
    parse_input as parse_manual_citation_input,
)
from pathlab_paper_agent.citations.manual_dedup import duplicate_of  # noqa: E402
from pathlab_paper_agent.citations.models import (  # noqa: E402
    CitationCandidate,
    CitationReference as CitationReferenceModel,
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
from pathlab_paper_agent.guard_summary import build_guard_result_summary  # noqa: E402
from pathlab_paper_agent.process_logging import append_pipeline_event  # noqa: E402
from pathlab_paper_agent.diagnostics import inspect_paper_run  # noqa: E402
from pathlab_paper_agent.outline_markdown import outline_to_markdown  # noqa: E402
from pathlab_paper_agent.validators.identifier_guard import scan_text  # noqa: E402
from pathlab_paper_agent.scaffold import initialize_paper_run  # noqa: E402
from pathlab_paper_agent.pipeline import request_pause  # noqa: E402
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
_MAX_PAPERS_PER_SOURCE_TASK = 20
_RUN_UNTIL_OUTLINE_HANDLER = "paper_generation.run_until_outline"
_RUN_AFTER_OUTLINE_HANDLER = "paper_generation.run_after_outline"
_RENDER_EXPORT_HANDLER = "paper_generation.render_export"
_RERUN_FROM_STAGE_HANDLER = "paper_generation.rerun_from_stage"
_SECTION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,80}$")
_SECTION_EDIT_STALE_PREFIXES = ("final/", "exports/", "validation/")
_EXECUTABLE_RERUN_STAGES = {
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
}
_OUTLINE_RERUN_STAGES = {
    PaperRunStage.collecting,
    PaperRunStage.building_evidence,
    PaperRunStage.outlining,
}
_SECTION_OVERWRITE_STAGES = {
    PaperRunStage.collecting,
    PaperRunStage.building_evidence,
    PaperRunStage.outlining,
    PaperRunStage.plotting,
    PaperRunStage.literature_review,
    PaperRunStage.section_writing,
}
_CITATION_OVERWRITE_STAGES = {
    PaperRunStage.collecting,
    PaperRunStage.building_evidence,
    PaperRunStage.outlining,
    PaperRunStage.plotting,
    PaperRunStage.literature_review,
}


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
        in {PaperRunStatus.completed, PaperRunStatus.failed, PaperRunStatus.cancelled, PaperRunStatus.paused}
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


def _load_config(paths: PaperRunPaths) -> Optional[PaperConfig]:
    if not paths.config.exists():
        return None
    try:
        return PaperConfig.model_validate(
            json.loads(paths.config.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        logger.warning(
            "paper_generation: failed to parse config for %s: %s",
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


async def _enqueue_paper_stage_rerun(paper_id: str, stage: PaperRunStage):
    from gateway.task_dispatch import build_task_descriptor, enqueue_task_descriptor

    descriptor = build_task_descriptor(
        job_id=paper_id,
        job_kind="paper_generation",
        handler=_RERUN_FROM_STAGE_HANDLER,
        payload={"paper_id": paper_id, "stage": stage.value},
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


def _load_json_any(path: Path) -> object:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("paper_generation: failed to read JSON %s: %s", path, exc)
        return None


def _citation_items(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        raw_items = payload.get("items")
    else:
        raw_items = payload
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def _load_selected_refs(paths: PaperRunPaths) -> list[CitationReferenceModel]:
    payload = _load_json_any(paths.citations_dir / "selected_refs.json")
    refs: list[CitationReferenceModel] = []
    for item in _citation_items(payload):
        try:
            refs.append(CitationReferenceModel.from_dict(item))
        except Exception as exc:
            logger.warning("paper_generation: invalid citation reference skipped: %s", exc)
    return refs


def _ref_to_schema(ref: CitationReferenceModel) -> CitationReferenceSchema:
    return CitationReferenceSchema.model_validate(ref.to_dict())


def _string_array(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    keys: list[str] = []
    for item in value:
        if isinstance(item, str):
            key = item
        elif isinstance(item, dict):
            key = str(item.get("paperId") or item.get("paper_id") or item.get("id") or item.get("key") or "")
        else:
            key = ""
        if key:
            keys.append(key)
    return keys


def _collect_required_keys(outline: object) -> list[str]:
    if not isinstance(outline, dict):
        return []
    found: set[str] = set()
    for key in _string_array(outline.get("required_cites")):
        found.add(key)
    extensions = outline.get("pathlab_extensions")
    if isinstance(extensions, dict):
        for key in _string_array(extensions.get("required_cites")):
            found.add(key)
    section_plan = outline.get("section_plan")
    if isinstance(section_plan, list):
        for section in section_plan:
            if not isinstance(section, dict):
                continue
            for key in _string_array(section.get("required_cites")):
                found.add(key)
            for key in _string_array(section.get("citations")):
                found.add(key)
    return sorted(found)


def _coverage_summary(paths: PaperRunPaths, selected_refs: list[CitationReferenceModel]) -> CitationCoverageSummary | None:
    payload = _load_json_file(paths.citations_dir / "coverage_report.json")
    if not payload:
        return None
    selected_keys = payload.get("selected_ref_keys")
    used_keys = payload.get("used_cite_keys")
    if isinstance(selected_keys, list):
        selected_set = {str(key) for key in selected_keys if key}
    else:
        selected_set = {ref.key for ref in selected_refs}
    if isinstance(used_keys, list):
        used_set = {str(key) for key in used_keys if key}
    else:
        used_set = set()
    selected_count = _int_value(payload.get("selected_count"), len(selected_set))
    cited_count = _int_value(payload.get("cited_count"), len(selected_set & used_set))
    coverage_ratio = _float_value(
        payload.get("coverage_ratio"),
        _float_value(payload.get("selected_coverage"), 0.0),
    )
    threshold = _float_value(payload.get("threshold"), _float_value(payload.get("min_selected_coverage"), 0.0))
    status = _coverage_status(payload.get("status"))
    return CitationCoverageSummary(
        selected_count=selected_count,
        cited_count=cited_count,
        coverage_ratio=coverage_ratio,
        threshold=threshold,
        status=status,
    )


def _verified_pool_summary(paths: PaperRunPaths, selected_refs: list[CitationReferenceModel]) -> VerifiedPoolSummary | None:
    discovery = _load_json_any(paths.citations_dir / "discovery_pool.json")
    verified = _load_json_any(paths.citations_dir / "verified_pool.json")
    if discovery is None or verified is None:
        return None
    discovery_items = _citation_items(discovery)
    verified_items = _citation_items(verified.get("verified") if isinstance(verified, dict) else None)
    rejected_items = _citation_items(verified.get("rejected") if isinstance(verified, dict) else None)
    breakdown: Counter[str] = Counter()
    samples: list[VerifiedPoolRejection] = []
    for item in rejected_items:
        reasons = _string_array(item.get("reasons"))
        breakdown.update(reasons)
        if len(samples) >= 10:
            continue
        candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else item
        samples.append(
            VerifiedPoolRejection(
                title=str(candidate.get("title") or ""),
                year=_optional_int(candidate.get("year")),
                source=str(candidate.get("source") or "unknown"),
                reasons=reasons,
            )
        )
    return VerifiedPoolSummary(
        discovery_total=len(discovery_items),
        verified_total=len(verified_items),
        selected_total=len(selected_refs),
        rejection_breakdown=dict(sorted(breakdown.items())),
        sample_rejections=samples,
    )


def _int_value(value: object, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _float_value(value: object, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _coverage_status(value: object) -> str:
    normalized = str(value or "").casefold()
    if normalized in {"pass", "passed"}:
        return "passed"
    if normalized in {"warn", "warning"}:
        return "warning"
    return "failed"


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _error_response(status_code: int, code: str, message: str, **extra: object) -> JSONResponse:
    payload: dict[str, object] = {"code": code, "message": message, **extra}
    # Keep backend error codes available to the existing frontend ApiError parser.
    payload["detail"] = dict(payload)
    return JSONResponse(status_code=status_code, content=payload)


def _http_error(status_code: int, code: str, message: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, **extra})


def _candidate_metadata_text(candidate: CitationCandidate) -> str:
    return "\n".join([candidate.title, *candidate.authors])


def _write_selected_refs(paths: PaperRunPaths, refs: list[CitationReferenceModel]) -> None:
    _atomic_write_json(
        paths.citations_dir / "selected_refs.json",
        {"items": [ref.to_dict() for ref in refs]},
    )
    _atomic_write_text(paths.refs_bib, generate_bibtex(refs))


def _append_required_key(paths: PaperRunPaths, key: str) -> None:
    outline = _load_json_file(paths.outline_json)
    required = _string_array(outline.get("required_cites"))
    if key not in required:
        required.append(key)
    outline["required_cites"] = sorted(required)
    extensions = outline.get("pathlab_extensions")
    if not isinstance(extensions, dict):
        extensions = {}
    extensions["outline_modified_by_user"] = True
    outline["pathlab_extensions"] = extensions
    _atomic_write_json(paths.outline_json, outline)
    _atomic_write_text(paths.outline_markdown, outline_to_markdown(outline))


def _write_outline_artifacts(paths: PaperRunPaths, manifest: PaperManifest, outline: dict[str, object]) -> None:
    _atomic_write_json(paths.outline_json, outline)
    _atomic_write_text(paths.outline_markdown, outline_to_markdown(outline))
    manifest.artifact_index["drafts/outline.json"] = {
        "status": "ready",
        "visibility": "public",
        "downloadable": True,
        "label": "Outline",
        "content_type": "application/json",
    }


def _outline_payload_changed(paths: PaperRunPaths, outline: dict[str, object]) -> bool:
    if not paths.outline_json.is_file():
        return True
    try:
        current = json.loads(paths.outline_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True
    return json.dumps(current, sort_keys=True, ensure_ascii=False) != json.dumps(outline, sort_keys=True, ensure_ascii=False)


def _mark_outline_modified_by_user(outline: dict[str, object]) -> None:
    extensions = outline.get("pathlab_extensions")
    if not isinstance(extensions, dict):
        extensions = {}
    extensions["outline_modified_by_user"] = True
    outline["pathlab_extensions"] = extensions


def _append_outline_edit_stage_log(manifest: PaperManifest, *, approved: bool) -> None:
    now = datetime.now(UTC).isoformat()
    manifest.stage_log.append(
        {
            "stage": PaperRunStage.outlining.value,
            "status": "user_edited",
            "ts": now,
            "started_at": now,
            "finished_at": now,
            "duration_ms": 0,
            "message": "User edited outline and approved it." if approved else "User edited outline.",
        }
    )
    manifest.artifact_index["drafts/大纲.md"] = {
        "status": "ready",
        "visibility": "public",
        "downloadable": True,
        "label": "大纲",
        "content_type": "text/markdown",
    }


_CITE_COMMAND_RE = re.compile(r"(\\cite[a-zA-Z*]*(?:\[[^\]]*\])*)\{([^{}]+)\}")
_BARE_CITATION_KEY_RE = re.compile(r"[A-Z][A-Za-z0-9:-]*\d{4}_[A-Za-z0-9_:-]+")


def _cleanup_citation_spacing(text: str) -> str:
    text = re.sub(r"[（(]\s*[）)]", "", text)
    text = re.sub(r"[ \t]+([,.;:!?])", r"\1", text)
    text = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", text)
    return text


def _remove_citation_key_from_text(text: str, key: str) -> str:
    changed = False

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        prefix = match.group(1)
        raw_keys = [part.strip() for part in match.group(2).split(",") if part.strip()]
        if key not in raw_keys:
            return match.group(0)
        changed = True
        remaining = [part for part in raw_keys if part != key]
        return f"{prefix}{{{','.join(remaining)}}}" if remaining else ""

    next_text = _CITE_COMMAND_RE.sub(repl, text)
    if key in next_text:
        changed = True
        next_text = next_text.replace(key, "")
    if not changed:
        return text
    return _cleanup_citation_spacing(next_text)


def _prune_unselected_citation_keys_from_text(text: str, selected_keys: set[str]) -> str:
    changed = False

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        prefix = match.group(1)
        raw_keys = [part.strip() for part in match.group(2).split(",") if part.strip()]
        if not raw_keys:
            return match.group(0)
        remaining = [part for part in raw_keys if part in selected_keys]
        if len(remaining) == len(raw_keys):
            return match.group(0)
        changed = True
        return f"{prefix}{{{','.join(remaining)}}}" if remaining else ""

    next_text = _CITE_COMMAND_RE.sub(repl, text)

    def bare_repl(match: re.Match[str]) -> str:
        nonlocal changed
        key = match.group(0)
        if key in selected_keys:
            return key
        changed = True
        return ""

    next_text = _BARE_CITATION_KEY_RE.sub(bare_repl, next_text)
    if not changed:
        return text
    return _cleanup_citation_spacing(next_text)


def _remove_citation_key_from_sections(paths: PaperRunPaths, key: str) -> list[str]:
    if not paths.sections_dir.is_dir():
        return []
    changed_sections: list[str] = []
    for path in sorted(paths.sections_dir.glob("*.tex")):
        if not path.is_file():
            continue
        current = path.read_text(encoding="utf-8")
        updated = _remove_citation_key_from_text(current, key)
        if updated == current:
            continue
        _atomic_write_text(path, updated)
        changed_sections.append(path.relative_to(paths.root).as_posix())
    return changed_sections


def _sync_section_citations_to_selected_refs(
    paths: PaperRunPaths,
    selected_refs: list[CitationReferenceModel] | None = None,
) -> list[str]:
    if not (paths.citations_dir / "selected_refs.json").exists() or not paths.sections_dir.is_dir():
        return []
    refs = selected_refs if selected_refs is not None else _load_selected_refs(paths)
    selected_keys = {ref.key for ref in refs}
    changed_sections: list[str] = []
    for path in sorted(paths.sections_dir.glob("*.tex")):
        if not path.is_file():
            continue
        current = path.read_text(encoding="utf-8")
        updated = _prune_unselected_citation_keys_from_text(current, selected_keys)
        if updated == current:
            continue
        _atomic_write_text(path, updated)
        changed_sections.append(path.relative_to(paths.root).as_posix())
    return changed_sections


def _mark_citation_section_sync_stale(paths: PaperRunPaths, changed_sections: list[str]) -> list[str]:
    if not changed_sections:
        return []
    manifest = _load_manifest(paths)
    if manifest is None:
        return []
    for rel_path in changed_sections:
        _register_edited_section(manifest, Path(rel_path).stem, rel_path)
    stale_artifacts = _mark_downstream_artifacts_stale(manifest)
    _save_manifest(paths, manifest)
    return stale_artifacts


def _append_citation_stage_log(paths: PaperRunPaths, *, status: str, message: str) -> None:
    manifest = _load_manifest(paths)
    if manifest is None:
        return
    now = datetime.now(UTC).isoformat()
    manifest.stage_log.append(
        {
            "stage": PaperRunStage.literature_review.value,
            "status": status,
            "ts": now,
            "started_at": now,
            "finished_at": now,
            "duration_ms": 0,
            "message": message,
        }
    )
    _save_manifest(paths, manifest)


def _coerce_rerun_stage(stage: str, manifest: PaperManifest | None = None) -> PaperRunStage:
    if stage == PaperRunStage.failed.value and manifest is not None:
        resolved = _latest_failed_stage(manifest)
        if resolved is not None:
            return resolved
    if stage == PaperRunStage.created.value:
        return PaperRunStage.collecting
    try:
        stage_enum = PaperRunStage(stage)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"unknown paper stage {stage!r}") from exc
    if stage_enum not in _EXECUTABLE_RERUN_STAGES:
        raise HTTPException(status_code=422, detail=f"stage {stage_enum.value} cannot be rerun")
    return stage_enum


def _latest_failed_stage(manifest: PaperManifest) -> PaperRunStage | None:
    for entry in reversed(manifest.stage_log):
        if str(entry.get("status")) != "failed":
            continue
        try:
            stage = PaperRunStage(str(entry.get("stage")))
        except ValueError:
            continue
        if stage in _EXECUTABLE_RERUN_STAGES:
            return stage
    return manifest.current_stage if manifest.current_stage in _EXECUTABLE_RERUN_STAGES else None


def _has_user_section_edits(manifest: PaperManifest) -> bool:
    return any(
        entry.get("stage") == PaperRunStage.section_writing.value
        and str(entry.get("status")) == "user_edited"
        for entry in manifest.stage_log
    )


def _has_user_citation_edits(manifest: PaperManifest) -> bool:
    return any(
        entry.get("stage") == PaperRunStage.literature_review.value
        and str(entry.get("status")) in {"user_added", "user_removed"}
        for entry in manifest.stage_log
    )


def _validate_rerun_request(stage: PaperRunStage, manifest: PaperManifest, body: PaperStageRerunRequest) -> JSONResponse | None:
    if not body.continue_downstream:
        return _error_response(422, "downstream_required", "Paper stage reruns must continue through downstream stages.")
    if not body.include_previous_successful_output:
        return _error_response(422, "history_required", "Paper stage reruns always load previous successful upstream history.")
    if stage in _OUTLINE_RERUN_STAGES and not body.confirm_regenerate_outline:
        return _error_response(409, "confirm_regenerate_outline", "Rerunning this stage regenerates the outline.")
    if stage in _SECTION_OVERWRITE_STAGES and _has_user_section_edits(manifest) and not body.confirm_overwrite_sections:
        return _error_response(409, "confirm_overwrite_sections", "Rerunning this stage may overwrite edited manuscript sections.")
    if stage in _CITATION_OVERWRITE_STAGES and _has_user_citation_edits(manifest) and not body.confirm_overwrite_citations:
        return _error_response(409, "confirm_overwrite_citations", "Rerunning this stage may overwrite user-edited citations.")
    return None


def _append_rerun_queued(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    *,
    stage: PaperRunStage,
    message: str,
) -> None:
    now = datetime.now(UTC).isoformat()
    manifest.stage_log.append(
        {
            "stage": stage.value,
            "status": "rerun_queued",
            "ts": now,
            "started_at": now,
            "finished_at": None,
            "duration_ms": None,
            "message": message,
        }
    )
    append_pipeline_event(
        paths,
        manifest,
        "rerun_queued",
        stage=stage.value,
        status="queued",
        started_at=now,
        message=message,
    )


def _guard_result_summary(paths: PaperRunPaths, guard: str, rel_path: str) -> GuardResultSummary | None:
    report = _load_json_file(paths.root / rel_path)
    if not report:
        return None
    return build_guard_result_summary(report, guard, max_sample_issues=_MAX_SAMPLE_ISSUES)


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


def _section_path_for_edit(paths: PaperRunPaths, manifest: Optional[PaperManifest], section_name: str) -> tuple[Path, str]:
    if not _SECTION_NAME_PATTERN.fullmatch(section_name):
        raise HTTPException(status_code=400, detail=f"Invalid section_name: {section_name!r}")
    path = paths.sections_dir / f"{section_name}.tex"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Section {section_name} not found")
    rel_path = path.relative_to(paths.root).as_posix()
    if not is_path_allowed_for_download(rel_path):
        raise HTTPException(status_code=403, detail="Section path is not editable.")
    if not _is_registered_public_artifact(manifest, rel_path):
        raise HTTPException(status_code=403, detail="Section is not registered public.")
    return path, rel_path


def _normalized_hash(value: str | None) -> str | None:
    text = (value or "").strip()
    return text.removeprefix("sha256:") or None


def _mark_downstream_artifacts_stale(manifest: PaperManifest) -> list[str]:
    stale_paths: list[str] = []
    for rel_path, raw in manifest.artifact_index.items():
        if not rel_path.startswith(_SECTION_EDIT_STALE_PREFIXES) or not isinstance(raw, dict):
            continue
        raw["stale"] = True
        stale_paths.append(rel_path)
    return sorted(stale_paths)


def _register_edited_section(manifest: PaperManifest, section_name: str, rel_path: str) -> None:
    previous = manifest.artifact_index.get(rel_path)
    payload = dict(previous) if isinstance(previous, dict) else {}
    payload.update(
        {
            "status": "ready",
            "visibility": "public",
            "downloadable": True,
            "label": payload.get("label") or f"Section: {section_name.replace('_', ' ').title()}",
            "content_type": payload.get("content_type") or "text/x-tex",
            "stale": False,
        }
    )
    manifest.artifact_index[rel_path] = payload


def _append_section_edit_stage_log(
    manifest: PaperManifest,
    *,
    section_name: str,
    stale_count: int,
) -> None:
    now = datetime.now(UTC).isoformat()
    manifest.stage_log.append(
        {
            "stage": PaperRunStage.section_writing.value,
            "status": "user_edited",
            "ts": now,
            "started_at": now,
            "finished_at": now,
            "duration_ms": 0,
            "message": f"User edited section {section_name}; {stale_count} downstream artifact(s) marked stale.",
            "section_name": section_name,
        }
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

    user_filter = None if _is_admin(user) else str(user.id)
    for source_task in body.source_tasks:
        _, source_task_paper_count = await PaperGenerationRunRepository.list_for_user(
            db,
            user_filter,
            limit=1,
            offset=0,
            source_task_id=source_task.task_id,
        )
        if source_task_paper_count >= _MAX_PAPERS_PER_SOURCE_TASK:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PAPER_LIMIT_EXCEEDED",
                    "message": (
                        f"Source task {source_task.task_id} already has "
                        f"{source_task_paper_count} paper runs. Delete some papers "
                        "before creating more."
                    ),
                    "source_task_id": source_task.task_id,
                    "current_count": source_task_paper_count,
                    "limit": _MAX_PAPERS_PER_SOURCE_TASK,
                },
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
    source_task_id: Optional[str] = Query(None, min_length=1),
) -> PaperRunListResponse:
    user_filter = None if _is_admin(user) else str(user.id)
    rows, total = await PaperGenerationRunRepository.list_for_user(
        db, user_filter, limit=limit, offset=offset, source_task_id=source_task_id
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
    config = _load_config(paths)
    summary = _row_to_summary(row, manifest)
    return PaperRunDetail(
        **summary.model_dump(),
        source_tasks=config.source_tasks if config is not None else [],
        artifacts=_public_artifacts(manifest),
        stage_log=manifest.stage_log if manifest is not None else [],
        validation_summary=_validation_summary(paths),
    )


@router.get("/{paper_id}/diagnostics", response_model=PaperRunDiagnostics)
async def get_paper_run_diagnostics(
    paper_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PaperRunDiagnostics:
    await _load_or_404(db, paper_id, user)
    paths = PaperRunPaths.for_paper(paper_id)
    return inspect_paper_run(paths, _load_manifest(paths))


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

    outline_payload = body.outline.model_dump(mode="json")
    outline_changed = _outline_payload_changed(paths, outline_payload)
    if outline_changed:
        _mark_outline_modified_by_user(outline_payload)
    _write_outline_artifacts(paths, manifest, outline_payload)
    if outline_changed:
        _append_outline_edit_stage_log(manifest, approved=body.approve)

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
    append_pipeline_event(
        paths,
        manifest,
        "outline_approved",
        stage=PaperRunStage.outlining.value,
        status="approved",
        started_at=now.isoformat(),
        finished_at=now.isoformat(),
        duration_ms=0,
        message="Outline approved by user.",
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
        failed_at = datetime.now(UTC)
        append_pipeline_event(
            paths,
            manifest,
            "outline_approval_enqueue_failed",
            stage=PaperRunStage.outlining.value,
            status="failed",
            finished_at=failed_at.isoformat(),
            error_type=type(exc).__name__,
            error_message=str(exc),
            message=manifest.error_message,
        )
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


@router.post("/{paper_id}/pause", response_model=None)
async def pause_paper_run(
    paper_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    row = await _load_or_404(db, paper_id, user)
    paths = PaperRunPaths.for_paper(paper_id)
    manifest = _load_manifest(paths)
    if manifest is None:
        raise HTTPException(status_code=500, detail=f"manifest.json not found for paper {paper_id}")

    active_statuses = {PaperRunStatus.pending.value, PaperRunStatus.running.value}
    active_manifest_statuses = {PaperRunStatus.pending, PaperRunStatus.running}
    if row.status not in active_statuses and manifest.status not in active_manifest_statuses:
        return _error_response(409, "not_active", f"paper run cannot be paused while status is {row.status}")

    manifest = request_pause(paper_id)
    await PaperGenerationRunRepository.update(
        db,
        paper_id,
        status=PaperRunStatus.paused.value,
        current_stage=manifest.current_stage.value,
        error_message=None,
        finished_at=None,
    )
    await db.commit()
    return {
        "paper_id": paper_id,
        "status": PaperRunStatus.paused.value,
        "current_stage": manifest.current_stage.value,
        "message": "Pause requested; the pipeline will stop at the next stage boundary.",
    }


# ---------------------------------------------------------------------------
# POST /papers/{paper_id}/render-export — rerender edited section source
# ---------------------------------------------------------------------------

@router.post("/{paper_id}/render-export")
async def rerender_paper_export(
    paper_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    row = await _load_or_404(db, paper_id, user)
    if row.status in {PaperRunStatus.pending.value, PaperRunStatus.running.value}:
        raise HTTPException(
            status_code=409,
            detail=f"render/export cannot be started while run status is {row.status}",
        )
    if row.status == PaperRunStatus.awaiting_outline_approval.value:
        raise HTTPException(
            status_code=409,
            detail="approve the outline before rendering/exporting the paper",
        )

    paths = PaperRunPaths.for_paper(paper_id)
    manifest = _load_manifest(paths)
    if manifest is None:
        raise HTTPException(status_code=500, detail=f"manifest.json not found for paper {paper_id}")
    if manifest.status in {PaperRunStatus.pending, PaperRunStatus.running}:
        raise HTTPException(
            status_code=409,
            detail=f"render/export cannot be started while manifest status is {manifest.status.value}",
        )
    if manifest.status == PaperRunStatus.awaiting_outline_approval:
        raise HTTPException(
            status_code=409,
            detail="approve the outline before rendering/exporting the paper",
        )
    if not paths.sections_dir.is_dir() or not any(paths.sections_dir.glob("*.tex")):
        raise HTTPException(status_code=409, detail="section source has not been generated yet")

    changed_sections = _sync_section_citations_to_selected_refs(paths)
    _mark_citation_section_sync_stale(paths, changed_sections)
    if changed_sections:
        manifest = _load_manifest(paths)
        if manifest is None:
            raise HTTPException(status_code=500, detail=f"manifest.json not found for paper {paper_id}")

    now = datetime.now(UTC)
    manifest.status = PaperRunStatus.running
    manifest.current_stage = PaperRunStage.rendering
    manifest.error_message = None
    manifest.finished_at = None
    manifest.stage_log.append(
        {
            "stage": PaperRunStage.rendering.value,
            "status": "queued",
            "ts": now.isoformat(),
            "started_at": now.isoformat(),
            "finished_at": None,
            "duration_ms": None,
            "message": "Render/export requested after section edits.",
        }
    )
    append_pipeline_event(
        paths,
        manifest,
        "render_export_requested",
        stage=PaperRunStage.rendering.value,
        status="queued",
        started_at=now.isoformat(),
        message="Render/export requested after section edits.",
    )
    _save_manifest(paths, manifest)
    await PaperGenerationRunRepository.update(
        db,
        paper_id,
        status=PaperRunStatus.running.value,
        current_stage=PaperRunStage.rendering.value,
        error_message=None,
        finished_at=None,
    )
    await db.commit()

    try:
        await _enqueue_paper_generation_job(paper_id, _RENDER_EXPORT_HANDLER)
    except Exception as exc:
        logger.exception("paper_generation: failed to enqueue render/export job for %s", paper_id)
        failed_at = datetime.now(UTC)
        manifest.status = PaperRunStatus.failed
        manifest.current_stage = PaperRunStage.rendering
        manifest.error_message = f"render/export enqueue failed: {exc}"
        manifest.finished_at = failed_at
        manifest.stage_log.append(
            {
                "stage": PaperRunStage.rendering.value,
                "status": "failed",
                "ts": failed_at.isoformat(),
                "started_at": now.isoformat(),
                "finished_at": failed_at.isoformat(),
                "duration_ms": max(0, int((failed_at - now).total_seconds() * 1000)),
                "message": manifest.error_message,
                "error_message": str(exc),
            }
        )
        append_pipeline_event(
            paths,
            manifest,
            "render_export_enqueue_failed",
            stage=PaperRunStage.rendering.value,
            status="failed",
            started_at=now.isoformat(),
            finished_at=failed_at.isoformat(),
            duration_ms=max(0, int((failed_at - now).total_seconds() * 1000)),
            error_type=type(exc).__name__,
            error_message=str(exc),
            message=manifest.error_message,
        )
        _save_manifest(paths, manifest)
        await PaperGenerationRunRepository.update(
            db,
            paper_id,
            status=PaperRunStatus.failed.value,
            current_stage=PaperRunStage.rendering.value,
            error_message=manifest.error_message,
            finished_at=failed_at,
        )
        await db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to enqueue render/export paper job: {exc}",
        ) from exc

    return {
        "paper_id": paper_id,
        "status": PaperRunStatus.running.value,
        "current_stage": PaperRunStage.rendering.value,
        "message": "Render/export job queued.",
    }


# ---------------------------------------------------------------------------
# POST /papers/{paper_id}/retry and /stages/{stage}:rerun
# ---------------------------------------------------------------------------

async def _queue_stage_rerun(
    *,
    paper_id: str,
    stage: PaperRunStage,
    row,
    paths: PaperRunPaths,
    manifest: PaperManifest,
    db: AsyncSession,
    body: PaperStageRerunRequest,
) -> dict[str, object] | JSONResponse:
    if row.status in {PaperRunStatus.pending.value, PaperRunStatus.running.value}:
        return _error_response(409, "run_active", f"stage rerun cannot start while run status is {row.status}")
    if row.status == PaperRunStatus.awaiting_outline_approval.value and stage not in _OUTLINE_RERUN_STAGES:
        return _error_response(409, "outline_approval_required", "Approve the outline before rerunning post-outline stages.")
    validation_error = _validate_rerun_request(stage, manifest, body)
    if validation_error is not None:
        return validation_error

    previous_state = {
        "status": manifest.status,
        "current_stage": manifest.current_stage,
        "error_message": manifest.error_message,
        "finished_at": manifest.finished_at,
        "stage_log_len": len(manifest.stage_log),
    }
    manifest.status = PaperRunStatus.running
    manifest.current_stage = stage
    manifest.error_message = None
    manifest.finished_at = None
    _append_rerun_queued(
        paths,
        manifest,
        stage=stage,
        message=f"Rerun from {stage.value} queued with successful upstream history.",
    )
    _save_manifest(paths, manifest)
    await PaperGenerationRunRepository.update(
        db,
        paper_id,
        status=PaperRunStatus.running.value,
        current_stage=stage.value,
        error_message=None,
        finished_at=None,
    )
    await db.commit()

    try:
        await _enqueue_paper_stage_rerun(paper_id, stage)
    except Exception as exc:
        logger.exception("paper_generation: failed to enqueue rerun for %s from %s", paper_id, stage.value)
        manifest.status = previous_state["status"]
        manifest.current_stage = previous_state["current_stage"]
        manifest.error_message = f"stage rerun enqueue failed: {exc}"
        manifest.finished_at = previous_state["finished_at"]
        del manifest.stage_log[int(previous_state["stage_log_len"]):]
        failed_at = datetime.now(UTC)
        manifest.stage_log.append(
            {
                "stage": stage.value,
                "status": "failed",
                "ts": failed_at.isoformat(),
                "started_at": failed_at.isoformat(),
                "finished_at": failed_at.isoformat(),
                "duration_ms": 0,
                "message": manifest.error_message,
                "error_message": str(exc),
            }
        )
        _save_manifest(paths, manifest)
        await PaperGenerationRunRepository.update(
            db,
            paper_id,
            status=previous_state["status"].value,
            current_stage=previous_state["current_stage"].value,
            error_message=manifest.error_message,
            finished_at=previous_state["finished_at"],
        )
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to enqueue paper stage rerun: {exc}") from exc

    return {
        "paper_id": paper_id,
        "status": PaperRunStatus.running.value,
        "current_stage": stage.value,
        "message": f"Rerun from {stage.value} queued.",
    }


@router.post("/{paper_id}/retry", response_model=None)
async def retry_failed_paper_stage(
    paper_id: str,
    body: PaperStageRerunRequest | None = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    row = await _load_or_404(db, paper_id, user)
    paths = PaperRunPaths.for_paper(paper_id)
    manifest = _load_manifest(paths)
    if manifest is None:
        raise HTTPException(status_code=500, detail=f"manifest.json not found for paper {paper_id}")
    if row.status != PaperRunStatus.failed.value and manifest.status != PaperRunStatus.failed:
        return _error_response(409, "not_failed", "Only failed paper runs can use retry. Choose a stage rerun instead.")
    stage = _latest_failed_stage(manifest)
    if stage is None:
        return _error_response(409, "failed_stage_unknown", "Could not determine which stage failed.")
    return await _queue_stage_rerun(
        paper_id=paper_id,
        stage=stage,
        row=row,
        paths=paths,
        manifest=manifest,
        db=db,
        body=body or PaperStageRerunRequest(
            confirm_overwrite_sections=True,
            confirm_overwrite_citations=True,
            confirm_regenerate_outline=True,
        ),
    )


@router.post("/{paper_id}/stages/{stage}:rerun", response_model=None)
async def rerun_paper_stage(
    paper_id: str,
    stage: str,
    body: PaperStageRerunRequest | None = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    row = await _load_or_404(db, paper_id, user)
    paths = PaperRunPaths.for_paper(paper_id)
    manifest = _load_manifest(paths)
    if manifest is None:
        raise HTTPException(status_code=500, detail=f"manifest.json not found for paper {paper_id}")
    stage_enum = _coerce_rerun_stage(stage, manifest)
    return await _queue_stage_rerun(
        paper_id=paper_id,
        stage=stage_enum,
        row=row,
        paths=paths,
        manifest=manifest,
        db=db,
        body=body or PaperStageRerunRequest(),
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
    changed_sections = _sync_section_citations_to_selected_refs(paths)
    _mark_citation_section_sync_stale(paths, changed_sections)
    manifest = _load_manifest(paths)
    return PaperSectionListResponse(sections=_public_sections(paths, manifest))


@router.put("/{paper_id}/sections/{section_name}", response_model=PaperSectionUpdateResponse)
async def update_paper_section(
    paper_id: str,
    section_name: str,
    body: PaperSectionUpdateRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PaperSectionUpdateResponse | JSONResponse:
    await _load_or_404(db, paper_id, user)
    paths = PaperRunPaths.for_paper(paper_id)
    manifest = _load_manifest(paths)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
    path, rel_path = _section_path_for_edit(paths, manifest, section_name)
    current_text = path.read_text(encoding="utf-8")
    current_hash = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
    expected_hash = _normalized_hash(body.source_hash)
    if expected_hash and expected_hash != current_hash:
        return _error_response(
            409,
            "stale_section",
            "Section changed since it was loaded. Refresh before saving.",
            current_source_hash=current_hash,
        )

    _atomic_write_text(path, body.text)
    _register_edited_section(manifest, section_name, rel_path)
    stale_artifacts = _mark_downstream_artifacts_stale(manifest)
    _append_section_edit_stage_log(
        manifest,
        section_name=section_name,
        stale_count=len(stale_artifacts),
    )
    _save_manifest(paths, manifest)
    return PaperSectionUpdateResponse(
        section=_section_from_file(paths, path),
        downstream_stale=bool(stale_artifacts),
        stale_artifacts=stale_artifacts,
    )


# ---------------------------------------------------------------------------
# GET/POST/DELETE /papers/{paper_id}/citations — selected reference workflow
# ---------------------------------------------------------------------------

@router.get("/{paper_id}/citations", response_model=CitationsView)
async def get_paper_citations(
    paper_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CitationsView:
    await _load_or_404(db, paper_id, user)
    paths = PaperRunPaths.for_paper(paper_id)
    selected_refs = _load_selected_refs(paths)
    changed_sections = _sync_section_citations_to_selected_refs(paths, selected_refs)
    _mark_citation_section_sync_stale(paths, changed_sections)
    outline = _load_json_file(paths.outline_json)
    return CitationsView(
        paper_id=paper_id,
        selected_refs=[_ref_to_schema(ref) for ref in selected_refs],
        required_keys=_collect_required_keys(outline),
        coverage=_coverage_summary(paths, selected_refs),
        verified_pool_summary=_verified_pool_summary(paths, selected_refs),
    )


@router.post(
    "/{paper_id}/citations",
    responses={
        200: {"model": AddCitationPreview},
        201: {"model": AddCitationResponse},
    },
)
async def add_paper_citation(
    paper_id: str,
    body: AddCitationRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await _load_or_404(db, paper_id, user)
    paths = PaperRunPaths.for_paper(paper_id)
    try:
        candidate = parse_manual_citation_input(body)
    except ManualCitationError as exc:
        return _error_response(exc.status_code, exc.code, exc.message)

    identifier_report = scan_text(
        _candidate_metadata_text(candidate),
        rel="citations/manual_add_metadata",
    )
    if identifier_report.status == "fail":
        return _error_response(
            422,
            "phi_detected",
            "Citation metadata contains possible PHI or private identifiers.",
        )

    selected_refs = _load_selected_refs(paths)
    existing_keys = {ref.key for ref in selected_refs}
    duplicate_key = duplicate_of(candidate, selected_refs)
    if duplicate_key:
        return _error_response(
            409,
            "duplicate",
            f"Citation already exists as {duplicate_key}.",
            duplicate_of=duplicate_key,
        )

    key = make_unique_key(candidate, existing_keys)
    ref = CitationReferenceModel.from_candidate(
        candidate,
        key=key,
        required=body.required,
        added_by="user",
    )
    ref_schema = _ref_to_schema(ref)
    if body.dry_run:
        preview = AddCitationPreview(
            proposed_key=key,
            ref=ref_schema,
            duplicate_of=None,
        )
        return JSONResponse(status_code=200, content=preview.model_dump(mode="json"))

    selected_refs.append(ref)
    _write_selected_refs(paths, selected_refs)
    if body.required:
        _append_required_key(paths, key)
    _append_citation_stage_log(
        paths,
        status="user_added",
        message=f"User added citation {key} via {body.mode}",
    )
    response = AddCitationResponse(key=key, ref=ref_schema)
    return JSONResponse(status_code=201, content=response.model_dump(mode="json"))


@router.delete("/{paper_id}/citations/{key}", response_model=CitationDeleteResponse)
async def delete_paper_citation(
    paper_id: str,
    key: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CitationDeleteResponse | JSONResponse:
    await _load_or_404(db, paper_id, user)
    paths = PaperRunPaths.for_paper(paper_id)
    selected_refs = _load_selected_refs(paths)
    ref = next((item for item in selected_refs if item.key == key), None)
    if ref is None:
        return _error_response(404, "not_found", f"Citation {key} not found.")
    if key in _collect_required_keys(_load_json_file(paths.outline_json)):
        return _error_response(409, "still_required", f"Citation {key} is still required by the outline.")

    remaining = [item for item in selected_refs if item.key != key]
    _write_selected_refs(paths, remaining)
    changed_sections = sorted(
        {
            *_remove_citation_key_from_sections(paths, key),
            *_sync_section_citations_to_selected_refs(paths, remaining),
        }
    )
    stale_artifacts = _mark_citation_section_sync_stale(paths, changed_sections)
    _append_citation_stage_log(
        paths,
        status="citation_removed",
        message=(
            f"Removed citation {key}; removed manuscript cite from "
            f"{len(changed_sections)} section(s); {len(stale_artifacts)} downstream artifact(s) marked stale."
        ),
    )
    return CitationDeleteResponse(
        deleted=True,
        key=key,
        removed_from_sections=changed_sections,
        downstream_stale=bool(stale_artifacts),
        stale_artifacts=stale_artifacts,
    )


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
    user: User = Depends(get_user_from_header_or_param),
    db: AsyncSession = Depends(get_db),
):
    return await _download_paper_file_impl(paper_id, path, user, db)


@router.get("/{paper_id}/files/{path:path}")
async def download_paper_file(
    paper_id: str,
    path: str,
    user: User = Depends(get_user_from_header_or_param),
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

    return FileResponse(
        target,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
