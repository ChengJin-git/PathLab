"""Dev-only FastAPI service for standalone paper-agent testing."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .bootstrap import configure_uploads_dir
from .citations import generate_bibtex, make_unique_key
from .citations.manual_add import ManualCitationError, parse_input as parse_manual_citation_input
from .citations.manual_dedup import duplicate_of
from .citations.models import CitationCandidate, CitationReference as CitationReferenceModel
from .pipeline import (
    create_dev_run,
    load_manifest,
    latest_failed_stage,
    manifest_artifacts,
    run_after_outline,
    run_from_stage,
    run_render_export,
    run_stage,
    save_manifest,
    summarize_manifest,
)
from .regenerate import MissingSectionDraftError, UnknownSectionError, latest_regenerate_log_summary, regenerate_section
from .process_logging import append_pipeline_event
from .outline_markdown import outline_to_markdown
from .schemas import (
    AddCitationPreview,
    AddCitationRequest,
    AddCitationResponse,
    CitationCoverageSummary,
    CitationDeleteResponse,
    CitationReference as CitationReferenceSchema,
    CitationsView,
    CreatePaperRequest,
    GuardIssueSummary,
    GuardResultSummary,
    OutlineApprovalRequest,
    PaperConfig,
    PaperStageRerunRequest,
    PaperRunCreateResponse,
    PaperRunDetail,
    PaperRunListResponse,
    PaperSection,
    PaperSectionListResponse,
    PaperSectionUpdateRequest,
    PaperSectionUpdateResponse,
    PaperRunStage,
    PaperRunStatus,
    RefinementSummary,
    RegenerateSectionRequest,
    ValidationSummary,
    VerifiedPoolRejection,
    VerifiedPoolSummary,
)
from .storage import PaperRunPaths, is_path_allowed_for_download, papers_root, safe_resolve, validate_paper_id
from .validators.identifier_guard import scan_text

logger = logging.getLogger(__name__)

_STAGES_FULL: tuple[PaperRunStage, ...] = (
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
_EXECUTABLE_RERUN_STAGES = set(_STAGES_FULL)
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
_SECTION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,80}$")
_SECTION_EDIT_STALE_PREFIXES = ("final/", "exports/", "validation/")
_CRC_MSI_TASK_ID = "crc_msi_abmil_fixture"
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


def _is_registered_public_artifact(manifest, rel_path: str) -> bool:
    raw = manifest.artifact_index.get(rel_path)
    if not isinstance(raw, dict):
        return False
    return (
        raw.get("visibility") == "public"
        and bool(raw.get("downloadable", True))
        and raw.get("status", "ready") in {"ready", "generated", "completed"}
    )


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "crc_msi_classification"


def _read_fixture_json(name: str) -> dict:
    path = _fixture_dir() / name
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_json_object(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("paper_agent dev_server: failed to read JSON %s: %s", path, exc)
        return {}
    return value if isinstance(value, dict) else {}


def _read_json_any(path: Path) -> object:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("paper_agent dev_server: failed to read JSON %s: %s", path, exc)
        return None


def _citation_items(payload: object) -> list[dict]:
    raw_items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def _load_selected_refs(paths: PaperRunPaths) -> list[CitationReferenceModel]:
    refs: list[CitationReferenceModel] = []
    for item in _citation_items(_read_json_any(paths.citations_dir / "selected_refs.json")):
        try:
            refs.append(CitationReferenceModel.from_dict(item))
        except Exception as exc:
            logger.warning("paper_agent dev_server: invalid citation reference skipped: %s", exc)
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


def _write_outline_artifacts(paths: PaperRunPaths, manifest, outline: dict[str, object]) -> None:
    paths.outline_json.parent.mkdir(parents=True, exist_ok=True)
    paths.outline_json.write_text(json.dumps(outline, indent=2, ensure_ascii=False), encoding="utf-8")
    paths.outline_markdown.write_text(outline_to_markdown(outline), encoding="utf-8")
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


def _append_outline_edit_stage_log(manifest, *, approved: bool) -> None:
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


def _int_value(value: object, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


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


def _coverage_summary(
    paths: PaperRunPaths,
    selected_refs: list[CitationReferenceModel],
) -> CitationCoverageSummary | None:
    payload = _read_json_object(paths.citations_dir / "coverage_report.json")
    if not payload:
        return None
    selected_keys = payload.get("selected_ref_keys")
    used_keys = payload.get("used_cite_keys")
    selected_set = (
        {str(key) for key in selected_keys if key}
        if isinstance(selected_keys, list)
        else {ref.key for ref in selected_refs}
    )
    used_set = {str(key) for key in used_keys if key} if isinstance(used_keys, list) else set()
    return CitationCoverageSummary(
        selected_count=_int_value(payload.get("selected_count"), len(selected_set)),
        cited_count=_int_value(payload.get("cited_count"), len(selected_set & used_set)),
        coverage_ratio=_float_value(
            payload.get("coverage_ratio"),
            _float_value(payload.get("selected_coverage"), 0.0),
        ),
        threshold=_float_value(
            payload.get("threshold"),
            _float_value(payload.get("min_selected_coverage"), 0.0),
        ),
        status=_coverage_status(payload.get("status")),
    )


def _verified_pool_summary(
    paths: PaperRunPaths,
    selected_refs: list[CitationReferenceModel],
) -> VerifiedPoolSummary | None:
    discovery = _read_json_any(paths.citations_dir / "discovery_pool.json")
    verified = _read_json_any(paths.citations_dir / "verified_pool.json")
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


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


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
    payload["detail"] = dict(payload)
    return JSONResponse(status_code=status_code, content=payload)


def _candidate_metadata_text(candidate: CitationCandidate) -> str:
    return "\n".join([candidate.title, *candidate.authors])


def _write_selected_refs(paths: PaperRunPaths, refs: list[CitationReferenceModel]) -> None:
    _atomic_write_json(
        paths.citations_dir / "selected_refs.json",
        {"items": [ref.to_dict() for ref in refs]},
    )
    _atomic_write_text(paths.refs_bib, generate_bibtex(refs))


def _append_required_key(paths: PaperRunPaths, key: str) -> None:
    outline = _read_json_object(paths.outline_json)
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
    try:
        manifest = load_manifest(paths.paper_id)
    except FileNotFoundError:
        return []
    for rel_path in changed_sections:
        _register_edited_section(manifest, Path(rel_path).stem, rel_path)
    stale_artifacts = _mark_downstream_artifacts_stale(manifest)
    save_manifest(manifest)
    return stale_artifacts


def _append_citation_stage_log(paths: PaperRunPaths, *, status: str, message: str) -> None:
    try:
        manifest = load_manifest(paths.paper_id)
    except FileNotFoundError:
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
    save_manifest(manifest)


def _coerce_rerun_stage_for_dev(stage: str, manifest) -> PaperRunStage:
    if stage == PaperRunStage.failed.value:
        resolved = latest_failed_stage(manifest)
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


def _has_user_section_edits(manifest) -> bool:
    return any(
        entry.get("stage") == PaperRunStage.section_writing.value
        and str(entry.get("status")) == "user_edited"
        for entry in manifest.stage_log
    )


def _has_user_citation_edits(manifest) -> bool:
    return any(
        entry.get("stage") == PaperRunStage.literature_review.value
        and str(entry.get("status")) in {"user_added", "user_removed"}
        for entry in manifest.stage_log
    )


def _validate_rerun_request_for_dev(stage: PaperRunStage, manifest, body: PaperStageRerunRequest) -> JSONResponse | None:
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


def _append_rerun_queued_for_dev(paths: PaperRunPaths, manifest, stage: PaperRunStage) -> None:
    now = datetime.now(UTC).isoformat()
    message = f"Rerun from {stage.value} queued with successful upstream history."
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
    report = _read_json_object(paths.root / rel_path)
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
    payload = _read_json_object(paths.root / _REFINEMENT_LOG_PATH)
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


def _section_sort_key(section: PaperSection) -> tuple[int, str]:
    return (_SECTION_ORDER.get(section.section_name, 999), section.section_name)


def _section_from_file(paths: PaperRunPaths, path: Path) -> PaperSection:
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


def _section_path_for_edit(paths: PaperRunPaths, manifest, section_name: str) -> tuple[Path, str]:
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


def _mark_downstream_artifacts_stale(manifest) -> list[str]:
    stale_paths: list[str] = []
    for rel_path, raw in manifest.artifact_index.items():
        if not rel_path.startswith(_SECTION_EDIT_STALE_PREFIXES) or not isinstance(raw, dict):
            continue
        raw["stale"] = True
        stale_paths.append(rel_path)
    return sorted(stale_paths)


def _register_edited_section(manifest, section_name: str, rel_path: str) -> None:
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


def _append_section_edit_stage_log(manifest, *, section_name: str, stale_count: int) -> None:
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


def _public_sections(paths: PaperRunPaths, manifest) -> list[PaperSection]:
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


def _crc_msi_task() -> dict:
    task = _read_fixture_json("task_record.json")
    return {
        "task_id": task.get("task_id", _CRC_MSI_TASK_ID),
        "task_name": task.get("task_name", "CRC MSI WSI Classification"),
        "task_type": task.get("task_type", "wsi_classification"),
        "data_type": task.get("data_type", "wsi"),
        "task_description": task.get("task_description"),
        "status": task.get("status", "completed"),
        "progress": 100,
        "error_message": None,
        "preprocessing_config": task.get("preprocessing_config"),
        "model_config": task.get("model_config"),
        "classes": task.get("classes", ["MSI", "MSS"]),
        "source_dataset_id": "crc_msi_dataset_fixture",
        "created_at": "2026-05-05T09:30:00+00:00",
        "updated_at": "2026-05-05T11:20:00+00:00",
        "started_at": "2026-05-05T09:35:00+00:00",
        "finished_at": "2026-05-05T11:20:00+00:00",
        "user_id": "00000000-0000-0000-0000-000000000000",
        "username": "demo",
    }


def _task_matches(task: dict, search: str | None) -> bool:
    if not search:
        return True
    needle = search.casefold()
    return any(
        needle in str(task.get(key) or "").casefold()
        for key in ("task_id", "task_name", "task_type", "task_description")
    )


def _with_crc_msi_defaults(body: CreatePaperRequest | None) -> CreatePaperRequest:
    request = body or CreatePaperRequest()
    if not any(task.task_id == _CRC_MSI_TASK_ID for task in request.source_tasks):
        return request

    fixture_request = _read_fixture_json("paper_request.json")
    updates = {}
    if not request.title:
        updates["title"] = fixture_request.get("title") or "CRC MSI Prediction from H&E Whole-Slide Images"
    if not request.user_idea:
        updates["user_idea"] = fixture_request.get("user_idea")
    return request.model_copy(update=updates) if updates else request


def _uses_crc_msi_fixture(paths: PaperRunPaths) -> bool:
    if not paths.config.exists():
        return False
    try:
        config = json.loads(paths.config.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    tasks = config.get("source_tasks") or []
    return any(isinstance(task, dict) and task.get("task_id") == _CRC_MSI_TASK_ID for task in tasks)


def _seed_crc_msi_fixture(paths: PaperRunPaths) -> None:
    """Replace DB-missing dev collection with the synthetic CRC MSI fixture."""
    fixture_raw = _fixture_dir() / "raw_collected"
    if not fixture_raw.is_dir() or not _uses_crc_msi_fixture(paths):
        return
    target = paths.evidence_dir / "raw_collected"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(fixture_raw, target)
    logger.info("paper_agent dev_server: seeded CRC MSI fixture for %s", paths.paper_id)


def _run_full_pipeline_for_dev(paper_id: str, uploads_dir: Optional[str | Path]) -> None:
    configure_uploads_dir(uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    try:
        for stage in _STAGES_FULL:
            run_stage(paper_id, stage, uploads_dir=uploads_dir)
            if stage == PaperRunStage.collecting:
                _seed_crc_msi_fixture(paths)
        run_stage(
            paper_id,
            PaperRunStage.completed,
            uploads_dir=uploads_dir,
            message="Standalone paper-agent dev run completed.",
        )
    except Exception:
        logger.exception("paper_agent dev_server: background run failed for %s", paper_id)


def _run_after_outline_for_dev(paper_id: str, uploads_dir: Optional[str | Path]) -> None:
    configure_uploads_dir(uploads_dir)
    try:
        run_after_outline(paper_id, uploads_dir=uploads_dir)
    except Exception:
        logger.exception("paper_agent dev_server: post-outline background run failed for %s", paper_id)


def _run_render_export_for_dev(paper_id: str, uploads_dir: Optional[str | Path]) -> None:
    configure_uploads_dir(uploads_dir)
    try:
        run_render_export(paper_id, uploads_dir=uploads_dir)
    except Exception:
        logger.exception("paper_agent dev_server: render/export background run failed for %s", paper_id)


def _run_from_stage_for_dev(paper_id: str, stage: str, uploads_dir: Optional[str | Path]) -> None:
    configure_uploads_dir(uploads_dir)
    try:
        run_from_stage(paper_id, stage, uploads_dir=uploads_dir)
    except Exception:
        logger.exception("paper_agent dev_server: rerun from %s failed for %s", stage, paper_id)


def _list_papers(*, uploads_dir: Optional[str | Path], limit: int, offset: int) -> PaperRunListResponse:
    configure_uploads_dir(uploads_dir)
    root = papers_root()
    if not root.is_dir():
        return PaperRunListResponse(items=[], total=0)

    items = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or not (child / "manifest.json").is_file():
            continue
        try:
            items.append(summarize_manifest(child.name, uploads_dir=uploads_dir))
        except Exception as exc:
            logger.warning("paper_agent dev_server: skipping invalid run %s: %s", child.name, exc)
    items.sort(key=lambda item: item.created_at, reverse=True)
    total = len(items)
    return PaperRunListResponse(items=items[offset : offset + limit], total=total)


def create_app(*, uploads_dir: Optional[str | Path] = None, auto_run: bool | None = None) -> FastAPI:
    configure_uploads_dir(uploads_dir)
    if auto_run is None:
        auto_run = os.getenv("PATHLAB_PAPER_AGENT_DEV_AUTO_RUN") == "1"

    app = FastAPI(title="PathLab Paper Agent Dev Service", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "pathlab-paper-agent",
            "uploads": str(papers_root().parent),
            "auto_run": str(bool(auto_run)).lower(),
        }

    @app.get("/settings/public")
    async def public_settings() -> dict[str, object]:
        return {"turnstile_enabled": False, "turnstile_site_key": ""}

    @app.post("/auth/secure-login")
    async def secure_login() -> dict[str, str]:
        return {"access_token": "paper-agent-dev-token", "token_type": "bearer"}

    @app.post("/auth/jwt/logout")
    async def auth_logout() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/auth/me")
    async def auth_me() -> dict:
        return {
            "id": "00000000-0000-0000-0000-000000000000",
            "email": "demo@pathlab.local",
            "username": "demo",
            "is_active": True,
            "is_superuser": True,
            "is_verified": True,
            "role": "admin",
            "nickname": "Demo Admin",
        }

    @app.get("/auth/maintenance-notice/public")
    async def public_maintenance_notice() -> dict[str, object]:
        return {"active": False, "message": None}

    @app.get("/auth/maintenance-notice")
    async def maintenance_notice() -> dict[str, object]:
        return {"active": False, "message": None, "needs_acknowledgment": False}

    @app.post("/auth/acknowledge-notice")
    async def acknowledge_notice() -> dict:
        return await auth_me()

    @app.get("/wsi/my-grants")
    async def my_dataset_grants() -> dict[str, object]:
        return {
            "user_id": "00000000-0000-0000-0000-000000000000",
            "grants": [],
            "elevated_dataset_ids": [],
        }

    @app.get("/tasks/training")
    async def list_training_tasks(
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
        search: str | None = None,
        status_filter: str | None = None,
        sort_by: str | None = None,
    ) -> dict:
        del sort_by
        task = _crc_msi_task()
        tasks = [task] if _task_matches(task, search) else []
        if status_filter and status_filter != "all":
            tasks = [item for item in tasks if item.get("status") == status_filter]
        total = len(tasks)
        start = (page - 1) * page_size
        items = tasks[start : start + page_size]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "stats": {
                "total": total,
                "running": sum(1 for item in tasks if item.get("status") == "running"),
                "completed": sum(1 for item in tasks if item.get("status") == "completed"),
                "failed": sum(1 for item in tasks if item.get("status") == "failed"),
                "cancelled": sum(1 for item in tasks if item.get("status") == "cancelled"),
            },
        }

    @app.get("/tasks/training/{task_id}")
    async def get_training_task(task_id: str) -> dict:
        task = _crc_msi_task()
        if task_id != task["task_id"]:
            raise HTTPException(status_code=404, detail=f"Training task {task_id} not found")
        return {**task, "wsi_count": 312, "wsi_ids": []}

    @app.post("/papers", response_model=PaperRunCreateResponse)
    async def create_paper(
        background_tasks: BackgroundTasks,
        body: Optional[CreatePaperRequest] = None,
    ) -> PaperRunCreateResponse:
        request = _with_crc_msi_defaults(body)
        paper_id, _paths = await create_dev_run(request, uploads_dir=uploads_dir)
        if auto_run:
            background_tasks.add_task(_run_full_pipeline_for_dev, paper_id, uploads_dir)
        return PaperRunCreateResponse(
            paper_id=paper_id,
            message=(
                "Paper run accepted; standalone dev pipeline is running in background."
                if auto_run
                else "Paper run scaffold created by standalone dev service."
            ),
        )

    @app.get("/papers", response_model=PaperRunListResponse)
    async def list_paper_runs(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> PaperRunListResponse:
        return _list_papers(uploads_dir=uploads_dir, limit=limit, offset=offset)

    @app.get("/papers/{paper_id}", response_model=PaperRunDetail)
    async def get_paper(paper_id: str) -> PaperRunDetail:
        try:
            summary = summarize_manifest(paper_id, uploads_dir=uploads_dir)
            manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        paths = PaperRunPaths.for_paper(paper_id)
        source_tasks = []
        if paths.config.exists():
            try:
                config = PaperConfig.model_validate(
                    json.loads(paths.config.read_text(encoding="utf-8"))
                )
                source_tasks = config.source_tasks
            except Exception as exc:
                logger.warning(
                    "paper_generation: failed to parse config for %s: %s",
                    paper_id,
                    exc,
                )
        return PaperRunDetail(
            **summary.model_dump(),
            source_tasks=source_tasks,
            artifacts=manifest_artifacts(manifest),
            stage_log=manifest.stage_log,
            validation_summary=_validation_summary(PaperRunPaths.for_paper(paper_id)),
        )

    @app.delete("/papers/{paper_id}")
    async def delete_paper(paper_id: str) -> dict:
        try:
            validate_paper_id(paper_id)
            paths = PaperRunPaths.for_paper(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not paths.root.exists():
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        shutil.rmtree(paths.root)
        return {"paper_id": paper_id, "deleted": True, "deleted_at": _utc_iso()}

    @app.post("/papers/{paper_id}/stages/{stage}:run")
    async def run_paper_stage(paper_id: str, stage: str) -> dict:
        try:
            manifest = run_stage(paper_id, stage, uploads_dir=uploads_dir)
            if PaperRunStage(stage) == PaperRunStage.collecting:
                _seed_crc_msi_fixture(PaperRunPaths.for_paper(paper_id))
                save_manifest(manifest, uploads_dir=uploads_dir)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "paper_id": paper_id,
            "status": manifest.status.value,
            "current_stage": manifest.current_stage.value,
        }

    async def _queue_stage_rerun_for_dev(
        paper_id: str,
        stage: PaperRunStage,
        body: PaperStageRerunRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object] | JSONResponse:
        try:
            validate_paper_id(paper_id)
            paths = PaperRunPaths.for_paper(paper_id)
            if not paths.manifest.exists():
                raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
            manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
        except HTTPException:
            raise
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        if manifest.status in {PaperRunStatus.pending, PaperRunStatus.running}:
            return _error_response(409, "run_active", f"stage rerun cannot start while run status is {manifest.status.value}")
        if manifest.status == PaperRunStatus.awaiting_outline_approval and stage not in _OUTLINE_RERUN_STAGES:
            return _error_response(409, "outline_approval_required", "Approve the outline before rerunning post-outline stages.")
        validation_error = _validate_rerun_request_for_dev(stage, manifest, body)
        if validation_error is not None:
            return validation_error

        manifest.status = PaperRunStatus.running
        manifest.current_stage = stage
        manifest.error_message = None
        manifest.finished_at = None
        _append_rerun_queued_for_dev(paths, manifest, stage)
        save_manifest(manifest, uploads_dir=uploads_dir)
        background_tasks.add_task(_run_from_stage_for_dev, paper_id, stage.value, uploads_dir)
        return {
            "paper_id": paper_id,
            "status": PaperRunStatus.running.value,
            "current_stage": stage.value,
            "message": f"Rerun from {stage.value} queued.",
        }

    @app.post("/papers/{paper_id}/retry", response_model=None)
    async def retry_failed_paper_stage(
        paper_id: str,
        background_tasks: BackgroundTasks,
        body: PaperStageRerunRequest | None = None,
    ) -> dict[str, object] | JSONResponse:
        try:
            validate_paper_id(paper_id)
            paths = PaperRunPaths.for_paper(paper_id)
            if not paths.manifest.exists():
                raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
            manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
        except HTTPException:
            raise
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if manifest.status != PaperRunStatus.failed:
            return _error_response(409, "not_failed", "Only failed paper runs can use retry. Choose a stage rerun instead.")
        stage = latest_failed_stage(manifest)
        if stage is None:
            return _error_response(409, "failed_stage_unknown", "Could not determine which stage failed.")
        return await _queue_stage_rerun_for_dev(
            paper_id,
            stage,
            body or PaperStageRerunRequest(
                confirm_overwrite_sections=True,
                confirm_overwrite_citations=True,
                confirm_regenerate_outline=True,
            ),
            background_tasks,
        )

    @app.post("/papers/{paper_id}/stages/{stage}:rerun", response_model=None)
    async def rerun_paper_stage(
        paper_id: str,
        stage: str,
        background_tasks: BackgroundTasks,
        body: PaperStageRerunRequest | None = None,
    ) -> dict[str, object] | JSONResponse:
        try:
            validate_paper_id(paper_id)
            paths = PaperRunPaths.for_paper(paper_id)
            if not paths.manifest.exists():
                raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
            manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
        except HTTPException:
            raise
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        stage_enum = _coerce_rerun_stage_for_dev(stage, manifest)
        return await _queue_stage_rerun_for_dev(paper_id, stage_enum, body or PaperStageRerunRequest(), background_tasks)

    @app.put("/papers/{paper_id}/outline")
    async def update_paper_outline(
        paper_id: str,
        body: OutlineApprovalRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        try:
            validate_paper_id(paper_id)
            paths = PaperRunPaths.for_paper(paper_id)
            if not paths.manifest.exists():
                raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
            manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
        except HTTPException:
            raise
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        if manifest.status != PaperRunStatus.awaiting_outline_approval:
            raise HTTPException(
                status_code=422,
                detail=f"outline cannot be edited at status {manifest.status.value}",
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
            manifest.finished_at = None
            save_manifest(manifest, uploads_dir=uploads_dir)
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
        save_manifest(manifest, uploads_dir=uploads_dir)
        background_tasks.add_task(_run_after_outline_for_dev, paper_id, uploads_dir)
        return {
            "paper_id": paper_id,
            "approved": True,
            "current_stage": PaperRunStage.plotting.value,
        }

    @app.post("/papers/{paper_id}/render-export")
    async def rerender_paper_export(
        paper_id: str,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        try:
            validate_paper_id(paper_id)
            paths = PaperRunPaths.for_paper(paper_id)
            if not paths.manifest.exists():
                raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
            manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
        except HTTPException:
            raise
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        if manifest.status in {PaperRunStatus.pending, PaperRunStatus.running}:
            raise HTTPException(
                status_code=409,
                detail=f"render/export cannot be started while run status is {manifest.status.value}",
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
            manifest = load_manifest(paper_id, uploads_dir=uploads_dir)

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
        save_manifest(manifest, uploads_dir=uploads_dir)
        background_tasks.add_task(_run_render_export_for_dev, paper_id, uploads_dir)
        return {
            "paper_id": paper_id,
            "status": PaperRunStatus.running.value,
            "current_stage": PaperRunStage.rendering.value,
            "message": "Render/export job queued.",
        }

    @app.get("/papers/{paper_id}/sections", response_model=PaperSectionListResponse)
    async def get_paper_sections(paper_id: str) -> PaperSectionListResponse:
        try:
            validate_paper_id(paper_id)
            paths = PaperRunPaths.for_paper(paper_id)
            if not paths.manifest.exists():
                raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
            manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
        except HTTPException:
            raise
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        changed_sections = _sync_section_citations_to_selected_refs(paths)
        if changed_sections:
            _mark_citation_section_sync_stale(paths, changed_sections)
            manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
        return PaperSectionListResponse(sections=_public_sections(paths, manifest))

    @app.put("/papers/{paper_id}/sections/{section_name}", response_model=PaperSectionUpdateResponse)
    async def update_paper_section(
        paper_id: str,
        section_name: str,
        body: PaperSectionUpdateRequest,
    ) -> PaperSectionUpdateResponse | JSONResponse:
        try:
            validate_paper_id(paper_id)
            paths = PaperRunPaths.for_paper(paper_id)
            if not paths.manifest.exists():
                raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
            manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
            path, rel_path = _section_path_for_edit(paths, manifest, section_name)
        except HTTPException:
            raise
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

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
        save_manifest(manifest, uploads_dir=uploads_dir)
        return PaperSectionUpdateResponse(
            section=_section_from_file(paths, path),
            downstream_stale=bool(stale_artifacts),
            stale_artifacts=stale_artifacts,
        )

    @app.post("/papers/{paper_id}/sections/{section_name}/regenerate")
    async def regenerate_paper_section(
        paper_id: str,
        section_name: str,
        body: RegenerateSectionRequest | None = None,
    ) -> dict:
        request = body or RegenerateSectionRequest()
        try:
            manifest = regenerate_section(
                paper_id,
                section_name,
                uploads_dir=uploads_dir,
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
            summary = latest_regenerate_log_summary(paper_id, uploads_dir=uploads_dir)
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
        return {
            "paper_id": paper_id,
            "status": manifest.status.value,
            "current_stage": manifest.current_stage.value,
            "regenerated_sections": summary.get("regenerated_sections", []),
            "refinement_log_summary": summary.get("refinement_log_summary", {}),
        }

    @app.get("/papers/{paper_id}/citations", response_model=CitationsView)
    async def get_paper_citations(paper_id: str) -> CitationsView:
        try:
            validate_paper_id(paper_id)
            paths = PaperRunPaths.for_paper(paper_id)
            if not paths.manifest.exists():
                raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
            selected_refs = _load_selected_refs(paths)
            changed_sections = _sync_section_citations_to_selected_refs(paths, selected_refs)
            _mark_citation_section_sync_stale(paths, changed_sections)
            outline = _read_json_object(paths.outline_json)
            return CitationsView(
                paper_id=paper_id,
                selected_refs=[_ref_to_schema(ref) for ref in selected_refs],
                required_keys=_collect_required_keys(outline),
                coverage=_coverage_summary(paths, selected_refs),
                verified_pool_summary=_verified_pool_summary(paths, selected_refs),
            )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post(
        "/papers/{paper_id}/citations",
        responses={
            200: {"model": AddCitationPreview},
            201: {"model": AddCitationResponse},
        },
    )
    async def add_paper_citation(paper_id: str, body: AddCitationRequest) -> JSONResponse:
        try:
            validate_paper_id(paper_id)
            paths = PaperRunPaths.for_paper(paper_id)
            if not paths.manifest.exists():
                raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

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

    @app.delete("/papers/{paper_id}/citations/{key}", response_model=CitationDeleteResponse)
    async def delete_paper_citation(paper_id: str, key: str) -> CitationDeleteResponse | JSONResponse:
        try:
            validate_paper_id(paper_id)
            paths = PaperRunPaths.for_paper(paper_id)
            if not paths.manifest.exists():
                raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        selected_refs = _load_selected_refs(paths)
        ref = next((item for item in selected_refs if item.key == key), None)
        if ref is None:
            return _error_response(404, "not_found", f"Citation {key} not found.")
        if key in _collect_required_keys(_read_json_object(paths.outline_json)):
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

    @app.get("/papers/{paper_id}/files")
    async def get_file_by_query(paper_id: str, path: str = Query(...)):
        return _file_response(paper_id, path)

    @app.get("/papers/{paper_id}/files/{path:path}")
    async def get_file_by_path(paper_id: str, path: str):
        return _file_response(paper_id, path)

    def _file_response(paper_id: str, rel_path: str):
        try:
            validate_paper_id(paper_id)
            paths = PaperRunPaths.for_paper(paper_id)
            if not paths.manifest.exists():
                raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
            if not is_path_allowed_for_download(rel_path):
                raise HTTPException(status_code=403, detail="Path not in download allowlist.")
            manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
            if not _is_registered_public_artifact(manifest, rel_path):
                raise HTTPException(status_code=403, detail="Artifact is not registered public.")
            target = safe_resolve(paths, rel_path)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
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

    return app
