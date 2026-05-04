"""Literature-review stage scaffold."""

from __future__ import annotations

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from .common import register_artifact, write_json, write_text


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    write_json(paths.citations_dir / "discovery_pool.json", {"items": []})
    write_json(paths.citations_dir / "verified_pool.json", {"items": []})
    write_json(paths.citations_dir / "selected_refs.json", {"items": []})
    write_json(paths.citations_dir / "required_cites.json", {"items": []})
    write_text(
        paths.refs_bib,
        "% Scaffold bibliography. Verified references are added by the literature review agent.\n",
    )
    write_json(
        paths.citations_dir / "coverage_report.json",
        {
            "status": "scaffold",
            "selected_ref_count": 0,
            "required_cite_count": 0,
            "coverage": 1.0,
        },
    )
    write_text(
        paths.intro_rw_draft_dir / "introduction.tex",
        "% Literature Review Agent draft placeholder. Not used directly for final compilation.\n",
    )
    write_text(
        paths.intro_rw_draft_dir / "related_work.tex",
        "% Literature Review Agent related-work placeholder. Not used directly for final compilation.\n",
    )

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
