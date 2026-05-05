"""M12b section-level regenerate coordinator."""

from __future__ import annotations

import difflib
import shutil
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
from .bootstrap import configure_uploads_dir
from .llm import LLMMessage
from .pipeline import load_manifest, save_manifest
from .schemas import PaperManifest
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


def regenerate_section(
    paper_id: str,
    section_name: str,
    *,
    uploads_dir: str | Path | None = None,
) -> PaperManifest:
    """Regenerate exactly one section and leave all other section files locked."""
    configure_uploads_dir(uploads_dir)
    manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    config = load_config(paths)
    inputs = SectionWritingInputs.from_paths(paths, config)
    target_section = _validate_section_name(section_name, inputs)
    _require_existing_section(paths, target_section)

    run_id = _timestamp_slug()
    run_dir = paths.drafts_dir / "regenerate_runs" / run_id
    before_dir = run_dir / "before"
    snapshots_dir = run_dir / "snapshots"
    log_path = run_dir / "log.json"
    log_rel_path = _rel_to_run(paths, log_path)
    _snapshot_current_sections(paths.sections_dir, before_dir)

    status = "rejected"
    error_message: str | None = None
    initial_guard_reports: list[dict[str, Any]] = []
    final_guard_reports: list[dict[str, Any]] = []
    refinement_log: dict[str, Any] = {}

    try:
        result = SectionWritingAgent().generate(inputs)
        if target_section not in result.sections:
            raise RegenerateRejectedError(f"SectionWritingAgent omitted required section: {target_section}")
        _write_target_section(paths, target_section, result.sections[target_section])

        initial_guard_reports = _run_validating_collect(paths, manifest)

        run_refining(
            paths,
            manifest,
            agent=_TargetSectionRefinementAgent(ContentRefinementAgent(), target_section),
            snapshots_subdir=snapshots_dir,
        )
        refinement_log = _read_refinement_log(paths)

        _restore_locked_sections(before_dir, paths.sections_dir, target_section)
        final_guard_reports = _run_validating_collect(paths, manifest)

        if _is_hard_refinement_reject(refinement_log):
            raise RegenerateRejectedError("refinement rejected the regenerated candidate")
        status = "accepted"
        _write_regenerate_log(
            paths,
            log_path,
            run_id=run_id,
            section_name=target_section,
            status=status,
            before_dir=before_dir,
            snapshots_dir=snapshots_dir,
            initial_guard_reports=initial_guard_reports,
            final_guard_reports=final_guard_reports,
            refinement_log=refinement_log,
        )
        _register_regenerate_log(manifest, log_rel_path, status=status)
        _append_stage_log(
            manifest,
            message=f"Regenerated section {target_section!r} in {run_id}.",
            run_id=run_id,
            section_name=target_section,
            status=status,
        )
        save_manifest(manifest, uploads_dir=uploads_dir)
        return manifest
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
            section_name=target_section,
            status=status,
            before_dir=before_dir,
            snapshots_dir=snapshots_dir,
            initial_guard_reports=initial_guard_reports,
            final_guard_reports=final_guard_reports,
            refinement_log=refinement_log,
            error=error_message,
            restored_from_before=True,
        )
        _register_regenerate_log(manifest, log_rel_path, status=status)
        _append_stage_log(
            manifest,
            message=f"Regenerate section {target_section!r} rejected in {run_id}: {error_message}",
            run_id=run_id,
            section_name=target_section,
            status=status,
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


def _snapshot_current_sections(sections_dir: Path, before_dir: Path) -> None:
    if before_dir.exists():
        shutil.rmtree(before_dir)
    before_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(sections_dir.glob("*.tex")):
        if path.is_file():
            shutil.copy2(path, before_dir / path.name)


def _write_target_section(paths: PaperRunPaths, section_name: str, text: str) -> None:
    paths.sections_dir.mkdir(parents=True, exist_ok=True)
    target = paths.sections_dir / f"{section_name}.tex"
    target.write_text(text if text.endswith("\n") else f"{text}\n", encoding="utf-8")


def _run_validating_collect(paths: PaperRunPaths, manifest: PaperManifest) -> list[dict[str, Any]]:
    try:
        run_validating(paths, manifest)
    except RuntimeError as exc:
        reports = _load_guard_reports(paths)
        failed = [str(report.get("guard")) for report in reports if report.get("status") == "fail"]
        failed_text = ", ".join(failed) if failed else str(exc)
        raise RegenerateRejectedError(f"validation rejected regenerated candidate: {failed_text}") from exc
    return _load_guard_reports(paths)


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
    before_dir: Path,
    snapshots_dir: Path,
    initial_guard_reports: list[dict[str, Any]],
    final_guard_reports: list[dict[str, Any]],
    refinement_log: dict[str, Any],
    error: str | None = None,
    restored_from_before: bool = False,
) -> None:
    before_text = _read_text_or_empty(before_dir / f"{section_name}.tex")
    after_text = _read_text_or_empty(paths.sections_dir / f"{section_name}.tex")
    payload: dict[str, Any] = {
        "run_id": run_id,
        "section_name": section_name,
        "status": status,
        "regenerated_sections": [section_name] if status == "accepted" else [],
        "before_dir": _rel_to_run(paths, before_dir),
        "snapshots_dir": _rel_to_run(paths, snapshots_dir),
        "after_path": _rel_to_run(paths, paths.sections_dir / f"{section_name}.tex"),
        "diff_size": _diff_size(before_text, after_text),
        "initial_guard_reports": initial_guard_reports,
        "final_guard_reports": final_guard_reports,
        "refinement_log_summary": _refinement_summary(refinement_log),
        "refinement_log": refinement_log,
        "restored_from_before": restored_from_before,
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
        "section_name": payload.get("section_name"),
        "status": payload.get("status"),
        "regenerated_sections": payload.get("regenerated_sections", []),
        "refinement_log_summary": payload.get("refinement_log_summary", {}),
        "diff_size": payload.get("diff_size", 0),
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
