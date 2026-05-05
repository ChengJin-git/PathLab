"""Literature-review stage backed by the M8b Literature Review Agent."""

from __future__ import annotations

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from pathlab_paper_agent.agents.literature_review_agent import (
    LiteratureCoverageError,
    LiteratureReviewAgent,
    LiteratureReviewInputs,
    LiteratureReviewResult,
    load_existing_candidates,
)

from .common import load_config, register_artifact, write_json, write_text


def run(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    *,
    agent: LiteratureReviewAgent | None = None,
) -> None:
    config = load_config(paths)
    literature_agent = agent or LiteratureReviewAgent()
    try:
        try:
            result = literature_agent.generate(
                LiteratureReviewInputs.from_paths(paths, config),
                existing_candidates=load_existing_candidates(paths.citations_dir / "discovery_pool.json"),
            )
        except LiteratureCoverageError as exc:
            _write_outputs(paths, exc.result)
            _register_artifacts(manifest)
            raise RuntimeError(str(exc)) from exc
        _write_outputs(paths, result)
        _register_artifacts(manifest)
    finally:
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
