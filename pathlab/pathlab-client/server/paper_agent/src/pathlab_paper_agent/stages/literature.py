"""Literature-review stage with deterministic M8a citation chain."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from pathlab_paper_agent.citations import (
    CitationCandidate,
    CitationReference,
    check_citation_coverage,
    check_orphan_cites,
    generate_bibtex,
    select_references,
    verify_candidates,
)
from pathlab_paper_agent.citations.coverage_gate import read_tex_citations
from pathlab_paper_agent.citations.pubmed import PubMedClient
from pathlab_paper_agent.citations.semantic_scholar import SemanticScholarClient

from .common import read_json, register_artifact, write_json, write_text

_NETWORK_ENV = "PATHLAB_PAPER_AGENT_ENABLE_CITATION_NETWORK"


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    outline = _read_outline(paths)
    query_specs = _query_specs_from_outline(outline)
    candidates = _load_existing_candidates(paths)
    discovery_mode = "manual_candidates" if candidates else "query_only"

    if not candidates and os.environ.get(_NETWORK_ENV) == "1":
        candidates = _discover_with_network(query_specs)
        discovery_mode = "network"

    write_json(
        paths.citations_dir / "discovery_pool.json",
        {
            "mode": discovery_mode,
            "queries": query_specs,
            "items": [candidate.to_dict() for candidate in candidates],
        },
    )

    cutoff_year = int(os.environ.get("PAPER_GEN_CITATION_CUTOFF_YEAR") or _current_year())
    verification = verify_candidates(candidates, cutoff_year=cutoff_year)
    write_json(paths.citations_dir / "verified_pool.json", verification.to_dict())

    selection = select_references(verification.verified, max_refs=_max_refs_from_outline(outline))
    selected_refs = list(selection.selected_refs)
    required_cites = list(selection.required_cites)
    write_json(
        paths.citations_dir / "selected_refs.json",
        {"items": [ref.to_dict() for ref in selected_refs]},
    )
    write_json(
        paths.citations_dir / "required_cites.json",
        {"items": [ref.to_dict() for ref in required_cites]},
    )
    write_text(paths.refs_bib, generate_bibtex(selected_refs))

    _write_intro_related_placeholders(paths, required_cites)
    used_keys = read_tex_citations(
        [
            paths.intro_rw_draft_dir / "introduction.tex",
            paths.intro_rw_draft_dir / "related_work.tex",
        ]
    )
    coverage = check_citation_coverage(selected_refs, required_cites, used_keys)
    orphan_report = check_orphan_cites(used_keys, selected_refs)
    coverage_payload = coverage.to_dict()
    coverage_payload.update(
        {
            "coverage_status": coverage.status,
            "mode": discovery_mode,
            "orphan_status": orphan_report.status,
            "orphan_cites": list(orphan_report.orphan_cites),
            "required_cite_keys": sorted(ref.key for ref in required_cites),
            "selected_ref_keys": sorted(ref.key for ref in selected_refs),
            "used_cite_keys": sorted(used_keys),
            "verified_count": len(verification.verified),
            "rejected_count": len(verification.rejected),
        }
    )
    coverage_payload["status"] = (
        "pass" if coverage.status == "pass" and orphan_report.status == "pass" else "fail"
    )
    write_json(paths.citations_dir / "coverage_report.json", coverage_payload)

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


def _read_outline(paths: PaperRunPaths) -> dict[str, Any]:
    if paths.outline_json.exists():
        return read_json(paths.outline_json)
    return {}


def _query_specs_from_outline(outline: dict[str, Any]) -> list[dict[str, Optional[str]]]:
    specs: list[dict[str, Optional[str]]] = []
    for query in outline.get("macro_lit_search") or []:
        specs.append({"query": str(query), "cluster": "macro"})
    for cluster in outline.get("micro_lit_clusters") or []:
        if not isinstance(cluster, dict):
            continue
        cluster_name = str(cluster.get("cluster") or "micro")
        for query in cluster.get("queries") or []:
            specs.append({"query": str(query), "cluster": cluster_name})
    deduped: list[dict[str, Optional[str]]] = []
    seen: set[tuple[str, Optional[str]]] = set()
    for spec in specs:
        query = spec.get("query") or ""
        key = (query, spec.get("cluster"))
        if query and key not in seen:
            seen.add(key)
            deduped.append(spec)
    return deduped


def _load_existing_candidates(paths: PaperRunPaths) -> list[CitationCandidate]:
    pool_path = paths.citations_dir / "discovery_pool.json"
    if not pool_path.exists():
        return []
    payload = read_json(pool_path)
    items = payload.get("items") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []
    return [CitationCandidate.from_dict(item) for item in items if isinstance(item, dict)]


def _discover_with_network(query_specs: Iterable[dict[str, Optional[str]]]) -> list[CitationCandidate]:
    candidates: list[CitationCandidate] = []
    s2 = SemanticScholarClient(api_key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY"))
    pubmed = PubMedClient(
        api_key=os.environ.get("PUBMED_API_KEY"),
        email=os.environ.get("PUBMED_EMAIL"),
    )
    try:
        for spec in query_specs:
            query = spec.get("query") or ""
            cluster = spec.get("cluster")
            if not query:
                continue
            candidates.extend(s2.search(query, limit=10, cluster=cluster))
            candidates.extend(pubmed.search(query, limit=10, cluster=cluster))
    finally:
        s2.close()
        pubmed.close()
    return candidates


def _write_intro_related_placeholders(
    paths: PaperRunPaths, required_cites: list[CitationReference]
) -> None:
    if required_cites:
        cite_text = ", ".join(f"\\cite{{{ref.key}}}" for ref in required_cites)
        intro = (
            "% Deterministic M8a placeholder. M8b rewrites narrative with LLM.\n"
            "\\section{Introduction}\n"
            f"Core computational pathology references are reserved here: {cite_text}.\n"
        )
        related_lines = [
            "% Deterministic M8a related-work placeholder.\n",
            "\\section{Related Work}\n",
            "The verified citation set covers the planned literature clusters.\n",
        ]
        for ref in required_cites:
            cluster = ref.cluster or "general"
            related_lines.append(f"% required cluster={cluster}: \\cite{{{ref.key}}}\n")
        _write_intro_related_files(paths, intro, "".join(related_lines))
        return

    _write_intro_related_files(
        paths,
        "% No verified references selected yet. M8b will draft Introduction after discovery.\n"
        "\\section{Introduction}\n",
        "% No verified references selected yet. M8b will draft Related Work after discovery.\n"
        "\\section{Related Work}\n",
    )


def _write_intro_related_files(paths: PaperRunPaths, intro: str, related_work: str) -> None:
    """Write M8a citation placeholders and mirror them into final sections."""
    write_text(paths.intro_rw_draft_dir / "introduction.tex", intro)
    write_text(paths.intro_rw_draft_dir / "related_work.tex", related_work)
    write_text(paths.sections_dir / "introduction.tex", intro)
    write_text(paths.sections_dir / "related_work.tex", related_work)


def _max_refs_from_outline(outline: dict[str, Any]) -> int:
    style = outline.get("template_style") if isinstance(outline.get("template_style"), dict) else {}
    raw = style.get("max_refs") if style else None
    try:
        return int(raw) if raw else 30
    except (TypeError, ValueError):
        return 30


def _current_year() -> int:
    return datetime.now(timezone.utc).year
