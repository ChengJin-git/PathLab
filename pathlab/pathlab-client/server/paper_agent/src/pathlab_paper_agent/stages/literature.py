"""Literature-review stage backed by the M8b Literature Review Agent."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pathlab_paper_agent.schemas import PaperManifest  # noqa: E402
from pathlab_paper_agent.storage import PaperRunPaths  # noqa: E402

from pathlab_paper_agent.agents.literature_review_agent import (
    LiteratureCoverageError,
    LiteratureReviewAgent,
    LiteratureReviewInputs,
    LiteratureReviewResult,
    load_existing_candidates,
)

from .common import load_config, register_artifact, write_json, write_text

_PROCESS_LOG_REL_PATH = "citations/literature_review_log.private.json"


def run(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    *,
    agent: LiteratureReviewAgent | None = None,
) -> None:
    config = load_config(paths)
    literature_agent = agent or LiteratureReviewAgent()
    events: list[dict[str, Any]] = []
    previous_sink = getattr(literature_agent, "event_sink", None)
    started_at = datetime.now(UTC)
    status = "failed"
    error_payload: dict[str, str] | None = None

    def sink(event: dict[str, Any]) -> None:
        events.append(event)
        if callable(previous_sink):
            previous_sink(event)

    if hasattr(literature_agent, "event_sink"):
        literature_agent.event_sink = sink
    try:
        try:
            result = literature_agent.generate(
                LiteratureReviewInputs.from_paths(paths, config),
                existing_candidates=load_existing_candidates(paths.citations_dir / "discovery_pool.json"),
            )
        except LiteratureCoverageError as exc:
            _write_outputs(paths, exc.result)
            _register_artifacts(manifest)
            error_payload = {"type": type(exc).__name__, "message": str(exc)}
            raise RuntimeError(str(exc)) from exc
        _write_outputs(paths, result)
        _register_artifacts(manifest)
        status = "completed"
    except Exception as exc:
        if error_payload is None:
            error_payload = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        if hasattr(literature_agent, "event_sink"):
            literature_agent.event_sink = previous_sink
        _write_process_log(
            paths,
            status=status,
            started_at=started_at,
            events=events,
            error=error_payload,
        )
        _register_process_log_artifact(manifest)
        if agent is None:
            literature_agent.close()


def _write_outputs(paths: PaperRunPaths, result: LiteratureReviewResult) -> None:
    write_json(
        paths.citations_dir / "discovery_pool.json",
        {
            "mode": result.discovery_mode,
            "generated_by": "m8b_literature_agent",
            "queries": [query.to_dict() for query in result.queries],
            "items": [candidate.to_dict() for candidate in result.candidates],
        },
    )
    write_json(paths.citations_dir / "verified_pool.json", result.verification.to_dict())
    write_json(
        paths.citations_dir / "selected_refs.json",
        {"items": [ref.to_dict() for ref in result.selection.selected_refs]},
    )
    write_json(
        paths.citations_dir / "required_cites.json",
        {"items": [ref.to_dict() for ref in result.selection.required_cites]},
    )
    write_text(paths.refs_bib, result.bibtex)
    write_text(paths.intro_rw_draft_dir / "introduction.tex", result.draft.introduction_tex)
    write_text(paths.intro_rw_draft_dir / "related_work.tex", result.draft.related_work_tex)

    coverage_payload = dict(result.coverage_report)
    coverage_payload.update(
        {
            "mode": result.discovery_mode,
            "verified_count": len(result.verification.verified),
            "rejected_count": len(result.verification.rejected),
        }
    )
    write_json(paths.citations_dir / "coverage_report.json", coverage_payload)


def _register_artifacts(manifest: PaperManifest) -> None:
    register_artifact(
        manifest,
        "citations/refs.bib",
        label="BibTeX references",
        content_type="text/x-bibtex",
    )
    register_artifact(
        manifest,
        "citations/coverage_report.json",
        label="Citation coverage report",
        content_type="application/json",
    )
    for rel_path in (
        "citations/discovery_pool.json",
        "citations/verified_pool.json",
        "citations/selected_refs.json",
        "citations/required_cites.json",
        "drafts/intro_rw_draft/introduction.tex",
        "drafts/intro_rw_draft/related_work.tex",
    ):
        register_artifact(
            manifest,
            rel_path,
            visibility="private_backend_only",
            downloadable=False,
            label=rel_path,
        )


def _write_process_log(
    paths: PaperRunPaths,
    *,
    status: str,
    started_at: datetime,
    events: list[dict[str, Any]],
    error: dict[str, str] | None,
) -> None:
    finished_at = datetime.now(UTC)
    write_json(
        paths.root / _PROCESS_LOG_REL_PATH,
        {
            "paper_id": paths.paper_id,
            "stage": "literature_review",
            "status": status,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": max(0, int((finished_at - started_at).total_seconds() * 1000)),
            "error": error,
            "event_count": len(events),
            "events": events,
        },
    )


def _register_process_log_artifact(manifest: PaperManifest) -> None:
    register_artifact(
        manifest,
        _PROCESS_LOG_REL_PATH,
        visibility="private_backend_only",
        downloadable=False,
        label="Literature review process log",
        content_type="application/json",
    )
