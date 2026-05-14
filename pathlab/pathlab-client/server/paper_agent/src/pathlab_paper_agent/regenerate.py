"""M12b section-level regenerate coordinator."""

from __future__ import annotations

import difflib
import shutil
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .agents.content_refinement_agent import (
    ContentRefinementAgent,
    CriticReview,
    RefinementInputs,
    RevisionResult,
    parse_revision_json,
    render_revised_sections,
)
from .agents.section_writing_agent import (
    SectionWritingAgent,
    SectionWritingInputs,
    required_section_slugs,
    section_slug,
)
from .agents.selection_rewrite_agent import (
    SelectionRewriteAgent,
    SelectionRewriteInputs,
    SelectionRewriteResult,
)
from .bootstrap import configure_uploads_dir
from .llm import LLMMessage
from .pipeline import load_manifest, save_manifest
from .renderers.bundle_validator import validate_bundle
from .renderers.latex_compiler import maybe_compile_with_docker
from .renderers.template_renderer import render_template
from .renderers.zip_exporter import export_bundle
from .schemas import (
    DiffSummary,
    PaperManifest,
    RegenerateJobEntry,
    RegenerateProgress,
    SelectionLocatorResult,
    TemplateId,
)
from .selection_locator import SelectionLocatorError, locate_selection, section_content_hash
from .stages.common import load_config, read_json, register_artifact, write_json
from .stages.refining import run as run_refining
from .stages.validating import run as run_validating
from .storage import PaperRunPaths

_GUARD_REPORT_NAMES = (
    "metric_guard",
    "identifier_guard",
    "latex_guard",
    "citation_guard",
    "claim_guard",
    "consistency_guard",
)


class UnknownSectionError(ValueError):
    """Raised when a requested section is not in the current paper plan."""


class MissingSectionDraftError(FileNotFoundError):
    """Raised when the section is valid but its draft file is absent."""


class RegenerateRejectedError(RuntimeError):
    """Raised when regenerate writes a candidate that guards/refinement reject."""


class RegenerateJobNotFoundError(FileNotFoundError):
    """Raised when a regenerate job id is not present in the manifest."""


class RegenerateStateError(RuntimeError):
    """Raised when reject/cancel cannot safely change a regenerate job."""

    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def regenerate_section(
    paper_id: str,
    section_name: str,
    *,
    uploads_dir: str | Path | None = None,
    regen_id: str | None = None,
    mode: str = "section",
    target_section: str | None = None,
    target_paragraph: int | None = None,
    target_sentence: int | None = None,
    selected_text: str | None = None,
    source_hash: str | None = None,
    char_start: int | None = None,
    char_end: int | None = None,
    user_note: str | None = None,
    template_id: str | TemplateId | None = None,
    rewrite_agent: SelectionRewriteAgent | None = None,
) -> PaperManifest:
    """Regenerate exactly one section and leave all other section files locked."""
    configure_uploads_dir(uploads_dir)
    manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    config = load_config(paths)
    inputs = SectionWritingInputs.from_paths(paths, config)
    requested_section = target_section or section_name
    target_section_slug = _validate_section_name(requested_section, inputs)
    _require_existing_section(paths, target_section_slug)
    mode = _normalize_mode(mode)
    if mode == "paragraph" and target_paragraph is None:
        raise ValueError("target_paragraph is required when mode='paragraph'")

    run_id = regen_id or _new_regen_id()
    if _job_was_cancelled_before_start(manifest, run_id):
        save_manifest(manifest, uploads_dir=uploads_dir)
        return manifest
    run_dir = paths.drafts_dir / "regenerate_runs" / run_id
    before_dir = run_dir / "before"
    after_dir = run_dir / "after"
    snapshots_dir = run_dir / "snapshots"
    log_path = run_dir / "log.json"
    log_rel_path = _rel_to_run(paths, log_path)
    _snapshot_current_sections(paths.sections_dir, before_dir)
    _upsert_regen_job(
        manifest,
        regen_id=run_id,
        mode=mode,
        section_name=target_section_slug,
        status="running",
        target_paragraph=target_paragraph,
        target_sentence=target_sentence,
        selected_text=selected_text,
        source_hash=source_hash,
        user_note=user_note,
        template_id=_template_value(template_id),
        started_at=datetime.now(UTC),
        error_code=None,
        error_message=None,
    )
    _set_regen_progress(manifest, run_id, "drafting", "Preparing regenerate inputs.", percent=10)
    save_manifest(manifest, uploads_dir=uploads_dir)

    status = "rejected"
    error_message: str | None = None
    initial_guard_reports: list[dict[str, Any]] = []
    final_guard_reports: list[dict[str, Any]] = []
    refinement_log: dict[str, Any] = {}
    locator: SelectionLocatorResult | None = None
    replacement_result: SelectionRewriteResult | None = None
    final_pdf_path: str | None = None
    export_bundle_path: str | None = None
    diff_summary: DiffSummary | None = None

    try:
        _raise_if_cancel_requested(paths, run_id)
        if mode == "selection":
            _set_regen_progress(manifest, run_id, "locating", "Locating selected text in LaTeX source.", percent=20)
            save_manifest(manifest, uploads_dir=uploads_dir)
            locator = locate_selection(
                paths,
                target_section_slug,
                selected_text=selected_text,
                source_hash=source_hash,
                target_paragraph=target_paragraph,
                target_sentence=target_sentence,
                char_start=char_start,
                char_end=char_end,
            )
            target_paragraph = locator.paragraph_index
            target_sentence = locator.sentence_index
            _upsert_regen_job(
                manifest,
                regen_id=run_id,
                locator=locator.model_dump(mode="json"),
                target_paragraph=target_paragraph,
                target_sentence=target_sentence,
            )
            _set_regen_progress(manifest, run_id, "drafting", "Rewriting selected span.", percent=35)
            save_manifest(manifest, uploads_dir=uploads_dir)
            _raise_if_cancel_requested(paths, run_id)
            replacement_result = (rewrite_agent or SelectionRewriteAgent()).rewrite(
                _selection_rewrite_inputs(
                    paths,
                    section_name=target_section_slug,
                    locator=locator,
                    selected_text=selected_text,
                    user_note=user_note,
                    template_id=_template_value(template_id),
                )
            )
            _patch_selection_span(paths, target_section_slug, locator, replacement_result.replacement_text)
        else:
            _raise_if_cancel_requested(paths, run_id)
            result = SectionWritingAgent().generate(_inputs_with_user_note(inputs, user_note))
            if target_section_slug not in result.sections:
                raise RegenerateRejectedError(f"SectionWritingAgent omitted required section: {target_section_slug}")
            candidate_text = result.sections[target_section_slug]
            if mode == "paragraph":
                candidate_text = _replace_target_paragraph(
                    (paths.sections_dir / f"{target_section_slug}.tex").read_text(encoding="utf-8"),
                    candidate_text,
                    target_paragraph,
                )
            _write_target_section(paths, target_section_slug, candidate_text)

        _set_regen_progress(manifest, run_id, "guarding", "Running manuscript guards.", percent=55)
        save_manifest(manifest, uploads_dir=uploads_dir)
        _raise_if_cancel_requested(paths, run_id)
        initial_guard_reports = _run_validating_collect(paths, manifest)

        if mode == "selection":
            refinement_log = _read_refinement_log(paths)
        else:
            _set_regen_progress(manifest, run_id, "refining", "Running target-section refinement.", percent=70)
            save_manifest(manifest, uploads_dir=uploads_dir)
            _raise_if_cancel_requested(paths, run_id)
            run_refining(
                paths,
                manifest,
                agent=_TargetSectionRefinementAgent(ContentRefinementAgent(), target_section_slug),
                snapshots_subdir=snapshots_dir,
            )
            refinement_log = _read_refinement_log(paths)

        _restore_locked_sections(before_dir, paths.sections_dir, target_section_slug)
        final_guard_reports = _run_validating_collect(paths, manifest)

        if _is_hard_refinement_reject(refinement_log):
            raise RegenerateRejectedError("refinement rejected the regenerated candidate")
        status = "accepted"
        _snapshot_after_sections(paths.sections_dir, after_dir, [target_section_slug])
        before_path = before_dir / f"{target_section_slug}.tex"
        after_path = after_dir / f"{target_section_slug}.tex"
        diff_summary = _diff_summary(
            _read_text_or_empty(before_path),
            _read_text_or_empty(after_path),
            locator=locator,
        )
        _set_regen_progress(manifest, run_id, "compiling", "Refreshing template PDF and export bundle.", percent=85)
        save_manifest(manifest, uploads_dir=uploads_dir)
        _raise_if_cancel_requested(paths, run_id)
        final_pdf_path, export_bundle_path = _refresh_template_outputs(paths, manifest, template_id)
        _write_regenerate_log(
            paths,
            log_path,
            run_id=run_id,
            section_name=target_section_slug,
            status=status,
            mode=mode,
            before_dir=before_dir,
            after_dir=after_dir,
            snapshots_dir=snapshots_dir,
            initial_guard_reports=initial_guard_reports,
            final_guard_reports=final_guard_reports,
            refinement_log=refinement_log,
            locator=locator,
            replacement_text_preview=_preview(replacement_result.replacement_text if replacement_result else None),
            diff_summary=diff_summary,
            final_pdf_path=final_pdf_path,
            export_bundle_path=export_bundle_path,
        )
        _register_regenerate_log(manifest, log_rel_path, status=status)
        _register_snapshot_artifacts(manifest, paths, before_path, after_path)
        _append_stage_log(
            manifest,
            message=f"Regenerated section {target_section_slug!r} in {run_id}.",
            run_id=run_id,
            section_name=target_section_slug,
            status=status,
        )
        _upsert_regen_job(
            manifest,
            regen_id=run_id,
            status="completed",
            finished_at=datetime.now(UTC),
            error_code=None,
            error_message=None,
            locator=locator.model_dump(mode="json") if locator else None,
            replacement_text_preview=_preview(replacement_result.replacement_text if replacement_result else None),
            before_path=_rel_to_run(paths, before_path),
            after_path=_rel_to_run(paths, after_path),
            diff_summary=diff_summary.model_dump(mode="json") if diff_summary else None,
            guard_summary=final_guard_reports,
            refinement_summary=_refinement_summary(refinement_log),
            final_pdf_path=final_pdf_path,
            export_bundle_path=export_bundle_path,
        )
        _set_regen_progress(manifest, run_id, "finalizing", "Regenerate completed.", percent=100)
        save_manifest(manifest, uploads_dir=uploads_dir)
        return manifest
    except _RegenerateCancelled as exc:
        _restore_all_sections(before_dir, paths.sections_dir)
        error_message = str(exc)
        _upsert_regen_job(
            manifest,
            regen_id=run_id,
            status="cancelled",
            finished_at=datetime.now(UTC),
            error_code="cancelled",
            error_message=error_message,
        )
        _append_stage_log(
            manifest,
            message=f"Regenerate section {target_section_slug!r} cancelled in {run_id}.",
            run_id=run_id,
            section_name=target_section_slug,
            status="cancelled",
        )
        save_manifest(manifest, uploads_dir=uploads_dir)
        raise
    except Exception as exc:
        error_message = str(exc)
        if not initial_guard_reports:
            initial_guard_reports = _load_guard_reports(paths)
        _restore_all_sections(before_dir, paths.sections_dir)
        try:
            run_validating(paths, manifest)
            final_guard_reports = _load_guard_reports(paths)
        except Exception:
            final_guard_reports = _load_guard_reports(paths)
        refinement_log = refinement_log or _read_refinement_log(paths)
        _write_regenerate_log(
            paths,
            log_path,
            run_id=run_id,
            section_name=target_section_slug,
            status=status,
            mode=mode,
            before_dir=before_dir,
            after_dir=after_dir,
            snapshots_dir=snapshots_dir,
            initial_guard_reports=initial_guard_reports,
            final_guard_reports=final_guard_reports,
            refinement_log=refinement_log,
            locator=locator,
            replacement_text_preview=_preview(replacement_result.replacement_text if replacement_result else None),
            diff_summary=diff_summary,
            final_pdf_path=final_pdf_path,
            export_bundle_path=export_bundle_path,
            error=error_message,
            restored_from_before=True,
        )
        _register_regenerate_log(manifest, log_rel_path, status=status)
        _append_stage_log(
            manifest,
            message=f"Regenerate section {target_section_slug!r} rejected in {run_id}: {error_message}",
            run_id=run_id,
            section_name=target_section_slug,
            status=status,
        )
        error_code = exc.code if isinstance(exc, SelectionLocatorError) else "regenerate_failed"
        _upsert_regen_job(
            manifest,
            regen_id=run_id,
            status="failed",
            finished_at=datetime.now(UTC),
            error_code=error_code,
            error_message=error_message,
            locator=locator.model_dump(mode="json") if locator else None,
            before_path=_rel_to_run(paths, before_dir / f"{target_section_slug}.tex"),
            guard_summary=final_guard_reports,
            refinement_summary=_refinement_summary(refinement_log),
        )
        save_manifest(manifest, uploads_dir=uploads_dir)
        raise


def latest_regenerate_log_summary(
    paper_id: str,
    *,
    uploads_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return a compact summary of the latest regenerate run for API responses."""
    configure_uploads_dir(uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    logs_root = paths.drafts_dir / "regenerate_runs"
    logs = sorted(logs_root.glob("*/log.json")) if logs_root.exists() else []
    if not logs:
        return {}
    payload = read_json(logs[-1])
    return _api_summary_from_log(payload)


def get_regenerate_job(
    paper_id: str,
    regen_id: str,
    *,
    uploads_dir: str | Path | None = None,
) -> RegenerateJobEntry:
    configure_uploads_dir(uploads_dir)
    manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
    entry = _find_regen_job(manifest, regen_id)
    if entry is None:
        raise RegenerateJobNotFoundError(f"regenerate job not found: {regen_id}")
    return RegenerateJobEntry.model_validate(entry)


def reject_regenerate(
    paper_id: str,
    regen_id: str,
    *,
    reason: str | None = None,
    template_id: str | TemplateId | None = None,
    uploads_dir: str | Path | None = None,
) -> tuple[PaperManifest, dict[str, Any]]:
    """Reject a completed regenerate job and restore its before snapshot."""
    configure_uploads_dir(uploads_dir)
    manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    entry = _find_regen_job(manifest, regen_id)
    if entry is None:
        raise RegenerateJobNotFoundError(f"regenerate job not found: {regen_id}")
    if entry.get("status") == "rejected":
        raise RegenerateStateError("already_rejected", f"Regenerate job {regen_id} is already rejected.")
    if entry.get("status") != "completed":
        raise RegenerateStateError(
            "not_rejectable",
            f"Regenerate job {regen_id} cannot be rejected at status {entry.get('status')}.",
        )
    section_name = str(entry.get("section_name") or "")
    if not _is_latest_completed_for_section(manifest, regen_id, section_name):
        raise RegenerateStateError(
            "stale_reject",
            "A later regenerate modified this section; reject is no longer safe.",
            status_code=409,
        )
    before_path = paths.root / str(entry.get("before_path") or "")
    after_path = paths.root / str(entry.get("after_path") or "")
    current_path = paths.sections_dir / f"{section_name}.tex"
    if not before_path.is_file() or not after_path.is_file() or not current_path.is_file():
        raise RegenerateStateError("snapshot_missing", "Regenerate before/after snapshot is missing.", status_code=409)
    if section_content_hash(current_path.read_text(encoding="utf-8")) != section_content_hash(
        after_path.read_text(encoding="utf-8")
    ):
        raise RegenerateStateError(
            "stale_reject",
            "Section was modified after this regenerate; reject is no longer safe.",
            status_code=409,
        )

    shutil.copy2(before_path, current_path)
    final_pdf_path, export_bundle_path = _refresh_template_outputs(paths, manifest, template_id or entry.get("template_id"))
    now = datetime.now(UTC)
    _upsert_regen_job(
        manifest,
        regen_id=regen_id,
        status="rejected",
        rejected_at=now,
        rejection_reason=reason,
        final_pdf_path=final_pdf_path,
        export_bundle_path=export_bundle_path,
    )
    _append_stage_log(
        manifest,
        message=f"User rejected regen {regen_id}.",
        run_id=regen_id,
        section_name=section_name,
        status="rejected",
    )
    save_manifest(manifest, uploads_dir=uploads_dir)
    return manifest, {
        "regen_id": regen_id,
        "status": "rejected",
        "restored_sections": [section_name],
        "final_pdf_path": final_pdf_path,
    }


def cancel_regenerate(
    paper_id: str,
    regen_id: str,
    *,
    uploads_dir: str | Path | None = None,
) -> dict[str, str]:
    configure_uploads_dir(uploads_dir)
    manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
    entry = _find_regen_job(manifest, regen_id)
    if entry is None:
        raise RegenerateJobNotFoundError(f"regenerate job not found: {regen_id}")
    status = str(entry.get("status"))
    if status == "cancelling":
        raise RegenerateStateError("already_cancelling", f"Regenerate job {regen_id} is already cancelling.", status_code=409)
    if status == "queued":
        new_status = "cancelled"
        _upsert_regen_job(
            manifest,
            regen_id=regen_id,
            status=new_status,
            finished_at=datetime.now(UTC),
            error_code="cancelled",
            error_message="Cancelled before the worker started.",
        )
    elif status == "running":
        new_status = "cancelling"
        _upsert_regen_job(manifest, regen_id=regen_id, status=new_status)
    elif status == "completed":
        raise RegenerateStateError("already_completed", f"Regenerate job {regen_id} already completed.")
    else:
        raise RegenerateStateError("not_cancellable", f"Regenerate job {regen_id} cannot be cancelled at status {status}.")
    save_manifest(manifest, uploads_dir=uploads_dir)
    return {"regen_id": regen_id, "status": new_status}


def _validate_section_name(section_name: str, inputs: SectionWritingInputs) -> str:
    requested = section_slug(section_name)
    if requested is None:
        raise UnknownSectionError(f"Unknown section name: {section_name!r}")
    allowed = set(required_section_slugs(inputs))
    if requested not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise UnknownSectionError(f"Unknown section {section_name!r}. Allowed sections: {allowed_text}")
    return requested


def _require_existing_section(paths: PaperRunPaths, section_name: str) -> None:
    if not paths.sections_dir.is_dir():
        raise FileNotFoundError(f"sections directory missing for paper {paths.paper_id}")
    target = paths.sections_dir / f"{section_name}.tex"
    if not target.is_file():
        raise MissingSectionDraftError(f"section draft missing: {target}")


def _timestamp_slug() -> str:
    stamp = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return stamp.replace(":", "-").replace(".", "-")


def _new_regen_id() -> str:
    return f"reg_{uuid.uuid4().hex[:12]}"


def _normalize_mode(mode: str) -> str:
    if mode not in {"section", "paragraph", "selection"}:
        raise ValueError("mode must be one of: section, paragraph, selection")
    return mode


def _template_value(template_id: str | TemplateId | None) -> str | None:
    if template_id is None:
        return None
    return template_id.value if isinstance(template_id, TemplateId) else str(template_id)


class _RegenerateCancelled(RuntimeError):
    """Internal cooperative-cancel signal."""


def _snapshot_current_sections(sections_dir: Path, before_dir: Path) -> None:
    if before_dir.exists():
        shutil.rmtree(before_dir)
    before_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(sections_dir.glob("*.tex")):
        if path.is_file():
            shutil.copy2(path, before_dir / path.name)


def _snapshot_after_sections(sections_dir: Path, after_dir: Path, section_names: list[str]) -> None:
    if after_dir.exists():
        shutil.rmtree(after_dir)
    after_dir.mkdir(parents=True, exist_ok=True)
    wanted = {f"{name}.tex" for name in section_names}
    for path in sorted(sections_dir.glob("*.tex")):
        if path.is_file() and path.name in wanted:
            shutil.copy2(path, after_dir / path.name)


def _write_target_section(paths: PaperRunPaths, section_name: str, text: str) -> None:
    paths.sections_dir.mkdir(parents=True, exist_ok=True)
    target = paths.sections_dir / f"{section_name}.tex"
    target.write_text(text if text.endswith("\n") else f"{text}\n", encoding="utf-8")


def _patch_selection_span(
    paths: PaperRunPaths,
    section_name: str,
    locator: SelectionLocatorResult,
    replacement_text: str,
) -> None:
    path = paths.sections_dir / f"{section_name}.tex"
    text = path.read_text(encoding="utf-8")
    if text[locator.char_start:locator.char_end] != locator.matched_source_text:
        raise RegenerateRejectedError("selection source span changed before patching")
    patched = text[: locator.char_start] + replacement_text + text[locator.char_end:]
    path.write_text(patched if patched.endswith("\n") else f"{patched}\n", encoding="utf-8")


def _replace_target_paragraph(original_text: str, candidate_text: str, target_paragraph: int | None) -> str:
    if target_paragraph is None:
        raise ValueError("target_paragraph is required")
    original_spans = _paragraph_spans(original_text)
    candidate_spans = _paragraph_spans(candidate_text)
    if target_paragraph >= len(original_spans):
        raise ValueError(f"target_paragraph {target_paragraph} out of range")
    if target_paragraph < len(candidate_spans):
        c_start, c_end = candidate_spans[target_paragraph]
        replacement = candidate_text[c_start:c_end]
    else:
        replacement = candidate_text.strip()
    start, end = original_spans[target_paragraph]
    return original_text[:start] + replacement + original_text[end:]


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    import re

    spans: list[tuple[int, int]] = []
    start = 0
    for match in re.finditer(r"\n[ \t]*\n+", text):
        end = match.start()
        if text[start:end].strip():
            spans.append((start, end))
        start = match.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans or [(0, len(text))]


def re_split_paragraphs(text: str) -> list[str]:
    import re

    return re.split(r"\n[ \t]*\n+", text)


def _inputs_with_user_note(inputs: SectionWritingInputs, user_note: str | None) -> SectionWritingInputs:
    if not user_note:
        return inputs
    note = f"\n\nRegenerate instruction from user: {user_note.strip()}"
    return replace(inputs, idea=(inputs.idea or "") + note)


def _selection_rewrite_inputs(
    paths: PaperRunPaths,
    *,
    section_name: str,
    locator: SelectionLocatorResult,
    selected_text: str | None,
    user_note: str | None,
    template_id: str | None,
) -> SelectionRewriteInputs:
    section_text = (paths.sections_dir / f"{section_name}.tex").read_text(encoding="utf-8")
    paragraph_context = _paragraph_context_for_locator(section_text, locator)
    evidence_context = ""
    if paths.experimental_log.exists():
        evidence_context = paths.experimental_log.read_text(encoding="utf-8")[:2000]
    return SelectionRewriteInputs(
        section_name=section_name,
        selected_source_text=locator.matched_source_text,
        selected_rendered_text=selected_text,
        paragraph_context=paragraph_context,
        user_note=user_note,
        template_id=template_id,
        evidence_context=evidence_context,
    )


def _paragraph_context_for_locator(section_text: str, locator: SelectionLocatorResult) -> str:
    paragraphs = [block for block in re_split_paragraphs(section_text) if block.strip()]
    index = locator.paragraph_index
    start = max(0, index - 1)
    end = min(len(paragraphs), index + 2)
    return "\n\n".join(paragraphs[start:end])[:4000]


def _run_validating_collect(paths: PaperRunPaths, manifest: PaperManifest) -> list[dict[str, Any]]:
    run_validating(paths, manifest)
    reports = _load_guard_reports(paths)
    failed = [str(report.get("guard")) for report in reports if report.get("status") == "fail"]
    if failed:
        raise RegenerateRejectedError(
            f"validation rejected regenerated candidate: {', '.join(failed)}"
        )
    return reports


def _restore_all_sections(before_dir: Path, sections_dir: Path) -> None:
    if sections_dir.exists():
        shutil.rmtree(sections_dir)
    sections_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(before_dir.glob("*.tex")):
        if path.is_file():
            shutil.copy2(path, sections_dir / path.name)


def _restore_locked_sections(before_dir: Path, sections_dir: Path, target_section: str) -> None:
    original_names = {path.name for path in before_dir.glob("*.tex") if path.is_file()}
    for path in sorted(sections_dir.glob("*.tex")):
        if path.stem == target_section:
            continue
        if path.name not in original_names:
            path.unlink()
    for path in sorted(before_dir.glob("*.tex")):
        if path.is_file() and path.stem != target_section:
            shutil.copy2(path, sections_dir / path.name)


def _load_guard_reports(paths: PaperRunPaths) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for name in _GUARD_REPORT_NAMES:
        path = paths.validation_dir / f"{name}.json"
        if path.exists():
            reports.append(read_json(path))
    return reports


def _find_regen_job(manifest: PaperManifest, regen_id: str) -> dict[str, Any] | None:
    for entry in manifest.regenerate_jobs:
        if isinstance(entry, dict) and entry.get("regen_id") == regen_id:
            return entry
    return None


def _upsert_regen_job(manifest: PaperManifest, *, regen_id: str, **fields: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    entry = _find_regen_job(manifest, regen_id)
    if entry is None:
        entry = {
            "regen_id": regen_id,
            "status": "queued",
            "enqueued_at": now.isoformat(),
        }
        manifest.regenerate_jobs.append(entry)
    for key, value in fields.items():
        if value is None and key not in {"error_code", "error_message", "locator", "diff_summary"}:
            continue
        if isinstance(value, datetime):
            entry[key] = value.isoformat()
        elif hasattr(value, "model_dump"):
            entry[key] = value.model_dump(mode="json")
        else:
            entry[key] = value
    manifest.updated_at = now
    return entry


def _job_was_cancelled_before_start(manifest: PaperManifest, regen_id: str) -> bool:
    entry = _find_regen_job(manifest, regen_id)
    if entry is None or entry.get("status") not in {"cancelled", "cancelling"}:
        return False
    if entry.get("status") == "cancelling":
        _upsert_regen_job(
            manifest,
            regen_id=regen_id,
            status="cancelled",
            finished_at=datetime.now(UTC),
            error_code="cancelled",
            error_message="Cancelled before the worker started.",
        )
    return True


def _set_regen_progress(
    manifest: PaperManifest,
    regen_id: str,
    step: str,
    detail: str | None = None,
    *,
    percent: int | None = None,
) -> None:
    progress = RegenerateProgress(
        step=step,  # type: ignore[arg-type]
        detail=detail,
        percent=percent,
        updated_at=datetime.now(UTC),
    )
    _upsert_regen_job(manifest, regen_id=regen_id, progress=progress.model_dump(mode="json"))


def _raise_if_cancel_requested(paths: PaperRunPaths, regen_id: str) -> None:
    try:
        manifest = load_manifest(paths.paper_id)
    except FileNotFoundError:
        return
    entry = _find_regen_job(manifest, regen_id)
    if entry and entry.get("status") in {"cancelling", "cancelled"}:
        raise _RegenerateCancelled(f"Regenerate job {regen_id} was cancelled.")


def _is_latest_completed_for_section(manifest: PaperManifest, regen_id: str, section_name: str) -> bool:
    for entry in reversed(manifest.regenerate_jobs):
        if not isinstance(entry, dict):
            continue
        if entry.get("section_name") != section_name:
            continue
        if entry.get("status") == "completed":
            return entry.get("regen_id") == regen_id
    return False


def _read_refinement_log(paths: PaperRunPaths) -> dict[str, Any]:
    path = paths.validation_dir / "refinement_log.json"
    return read_json(path) if path.exists() else {}


def _is_hard_refinement_reject(refinement_log: dict[str, Any]) -> bool:
    if refinement_log.get("final_status") != "rejected":
        return False
    accepted = refinement_log.get("accepted_iterations")
    return not isinstance(accepted, list) or not accepted


def _write_regenerate_log(
    paths: PaperRunPaths,
    log_path: Path,
    *,
    run_id: str,
    section_name: str,
    status: str,
    mode: str,
    before_dir: Path,
    after_dir: Path,
    snapshots_dir: Path,
    initial_guard_reports: list[dict[str, Any]],
    final_guard_reports: list[dict[str, Any]],
    refinement_log: dict[str, Any],
    locator: SelectionLocatorResult | None = None,
    replacement_text_preview: str | None = None,
    diff_summary: DiffSummary | None = None,
    final_pdf_path: str | None = None,
    export_bundle_path: str | None = None,
    error: str | None = None,
    restored_from_before: bool = False,
) -> None:
    before_text = _read_text_or_empty(before_dir / f"{section_name}.tex")
    after_path = after_dir / f"{section_name}.tex"
    after_text = _read_text_or_empty(after_path if after_path.exists() else paths.sections_dir / f"{section_name}.tex")
    payload: dict[str, Any] = {
        "run_id": run_id,
        "section_name": section_name,
        "status": status,
        "mode": mode,
        "regenerated_sections": [section_name] if status == "accepted" else [],
        "non_target_revisions_discarded": _non_target_revisions_discarded(refinement_log, section_name),
        "before_dir": _rel_to_run(paths, before_dir),
        "before_path": _rel_to_run(paths, before_dir / f"{section_name}.tex"),
        "after_dir": _rel_to_run(paths, after_dir),
        "snapshots_dir": _rel_to_run(paths, snapshots_dir),
        "after_path": _rel_to_run(paths, after_path if after_path.exists() else paths.sections_dir / f"{section_name}.tex"),
        "diff_size": _diff_size(before_text, after_text),
        "diff_summary": diff_summary.model_dump(mode="json") if diff_summary else None,
        "initial_guard_reports": initial_guard_reports,
        "final_guard_reports": final_guard_reports,
        "refinement_log_summary": _refinement_summary(refinement_log),
        "refinement_log": refinement_log,
        "restored_from_before": restored_from_before,
        "locator": locator.model_dump(mode="json") if locator else None,
        "replacement_text_preview": replacement_text_preview,
        "final_pdf_path": final_pdf_path,
        "export_bundle_path": export_bundle_path,
    }
    if error:
        payload["error"] = error
    write_json(log_path, payload)


def _register_regenerate_log(manifest: PaperManifest, rel_path: str, *, status: str) -> None:
    register_artifact(
        manifest,
        rel_path,
        status=status,
        visibility="private_backend_only",
        downloadable=False,
        label="Section regenerate log",
        content_type="application/json",
    )


def _append_stage_log(
    manifest: PaperManifest,
    *,
    message: str,
    run_id: str,
    section_name: str,
    status: str,
) -> None:
    now = datetime.now(UTC)
    manifest.updated_at = now
    manifest.stage_log.append(
        {
            "stage": "regenerate",
            "ts": now.isoformat(),
            "message": message,
            "run_id": run_id,
            "section_name": section_name,
            "status": status,
        }
    )


def _api_summary_from_log(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": payload.get("run_id"),
        "regen_id": payload.get("run_id"),
        "section_name": payload.get("section_name"),
        "status": payload.get("status"),
        "regenerated_sections": payload.get("regenerated_sections", []),
        "refinement_log_summary": payload.get("refinement_log_summary", {}),
        "diff_size": payload.get("diff_size", 0),
        "diff_summary": payload.get("diff_summary"),
        "final_pdf_path": payload.get("final_pdf_path"),
        "export_bundle_path": payload.get("export_bundle_path"),
    }


def _refinement_summary(refinement_log: dict[str, Any]) -> dict[str, Any]:
    if not refinement_log:
        return {}
    return {
        "final_status": refinement_log.get("final_status"),
        "accepted_iterations": refinement_log.get("accepted_iterations", []),
        "iteration_count": len(refinement_log.get("iterations", [])),
        "initial_score": refinement_log.get("initial_score", {}),
    }


def _non_target_revisions_discarded(refinement_log: dict[str, Any], target_section: str) -> list[str]:
    """Return non-target sections that refinement claimed to revise.

    M12b restores every section other than the target after refinement runs,
    so any section the M11 loop edited besides the target is silently dropped
    from disk. Surface those names in the regenerate log so audits can
    explain the divergence between refinement_log claims and disk content.
    """
    if not isinstance(refinement_log, dict):
        return []
    accepted = refinement_log.get("accepted_iterations") or []
    if not isinstance(accepted, list):
        return []
    iterations = refinement_log.get("iterations") or []
    if not isinstance(iterations, list):
        return []
    discarded: set[str] = set()
    for iteration in iterations:
        if not isinstance(iteration, dict):
            continue
        if iteration.get("iteration") not in accepted:
            continue
        revision = iteration.get("revision") if isinstance(iteration.get("revision"), dict) else {}
        for section in revision.get("changed_sections") or []:
            if isinstance(section, str) and section and section != target_section:
                discarded.add(section)
    return sorted(discarded)


def _diff_size(before: str, after: str) -> int:
    return len(
        list(
            difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                lineterm="",
            )
        )
    )


def _diff_summary(before: str, after: str, *, locator: SelectionLocatorResult | None = None) -> DiffSummary:
    matcher = difflib.SequenceMatcher(None, before, after)
    chars_added = 0
    chars_removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            chars_removed += i2 - i1
        if tag in {"replace", "insert"}:
            chars_added += j2 - j1
    before_paragraphs = [block for block in re_split_paragraphs(before) if block.strip()]
    after_paragraphs = [block for block in re_split_paragraphs(after) if block.strip()]
    paragraphs_changed = [
        index
        for index in range(max(len(before_paragraphs), len(after_paragraphs)))
        if (before_paragraphs[index] if index < len(before_paragraphs) else None)
        != (after_paragraphs[index] if index < len(after_paragraphs) else None)
    ]
    preview = "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="before",
            tofile="after",
            lineterm="",
        )
    )
    return DiffSummary(
        chars_added=chars_added,
        chars_removed=chars_removed,
        paragraphs_changed=paragraphs_changed,
        sentences_changed=[locator.sentence_index] if locator and locator.sentence_index is not None else [],
        preview_unified=preview[:2000],
    )


def _refresh_template_outputs(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    template_id: str | TemplateId | None,
) -> tuple[str | None, str | None]:
    config = load_config(paths)
    selected = [template.value for template in config.selected_templates]
    requested = _template_value(template_id) or (selected[0] if selected else TemplateId.miccai.value)
    if requested not in {item.value for item in TemplateId}:
        raise ValueError(f"unsupported_template: {requested}")
    render_template(paths, config, requested)
    compile_result = maybe_compile_with_docker(paths.root, requested)
    register_artifact(
        manifest,
        f"final/{requested}/main.tex",
        label=f"{requested} LaTeX main",
        content_type="text/x-tex",
    )
    register_artifact(
        manifest,
        f"final/{requested}/main.compile_summary.txt",
        label=f"{requested} compile summary",
        content_type="text/plain",
    )
    final_pdf_rel = f"final/{requested}/main.pdf"
    manifest.artifact_index.pop(final_pdf_rel, None)
    final_pdf_path = paths.final_for_template(requested) / "main.pdf"
    if compile_result.status == "compiled" and final_pdf_path.is_file():
        register_artifact(
            manifest,
            final_pdf_rel,
            label=f"{requested} compiled PDF",
            content_type="application/pdf",
        )
        final_pdf = final_pdf_rel
    else:
        final_pdf = final_pdf_rel if final_pdf_path.is_file() else None

    bundle_rel = f"exports/{requested}_bundle.zip"
    export_result = export_bundle(
        paths.final_for_template(requested),
        paths.exports_dir / f"{requested}_bundle.zip",
        config,
        requested,
    )
    validation_result = validate_bundle(paths.exports_dir / f"{requested}_bundle.zip")
    register_artifact(
        manifest,
        bundle_rel,
        downloadable=(
            compile_result.status == "compiled"
            and export_result.dependency_closed
            and validation_result.downloadable
        ),
        label=f"{requested} submission bundle",
        content_type="application/zip",
    )
    return final_pdf, bundle_rel


def _register_snapshot_artifacts(
    manifest: PaperManifest,
    paths: PaperRunPaths,
    before_path: Path,
    after_path: Path,
) -> None:
    for path, label in ((before_path, "Regenerate before section"), (after_path, "Regenerate after section")):
        if not path.is_file():
            continue
        register_artifact(
            manifest,
            _rel_to_run(paths, path),
            label=label,
            content_type="text/x-tex",
        )


def _preview(text: str | None, *, limit: int = 300) -> str | None:
    if text is None:
        return None
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _read_text_or_empty(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _rel_to_run(paths: PaperRunPaths, path: Path) -> str:
    try:
        return path.relative_to(paths.root).as_posix()
    except ValueError:
        return str(path)


class _TargetSectionRefinementAgent(ContentRefinementAgent):
    """Content refinement wrapper that applies only the regenerated section."""

    def __init__(self, inner: ContentRefinementAgent, target_section: str) -> None:
        self.llm_client = inner.llm_client
        self.critic_prompt_template = inner.critic_prompt_template
        self.revise_prompt_template = inner.revise_prompt_template
        self.event_sink = getattr(inner, "event_sink", None)
        self.target_section = target_section

    def revise(self, inputs: RefinementInputs, review: CriticReview) -> RevisionResult:
        prompt = self.build_revise_prompt(inputs, review)
        response = self.llm_client.complete(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "You are PathLab's Content Refinement reviser. Return only JSON section updates. "
                        "Use [CITE:key] and {{m:key}} placeholders in changed sections."
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.25,
            response_format={"type": "json_object"},
        )
        raw_sections, worklog = parse_revision_json(_response_text(response))
        target_only = (
            {self.target_section: raw_sections[self.target_section]}
            if self.target_section in raw_sections
            else {}
        )
        rendered = render_revised_sections(target_only, inputs)
        worklog = dict(worklog)
        skipped = sorted(section for section in raw_sections if section != self.target_section)
        if skipped:
            worklog["ignored_non_target_sections"] = skipped
        return RevisionResult(sections=rendered, raw_sections=target_only, worklog=worklog)


def _response_text(response: Any) -> str:
    raw_content = getattr(response, "content", response)
    return raw_content if isinstance(raw_content, str) else str(raw_content)
