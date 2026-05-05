from __future__ import annotations

import json
import httpx
import pytest

from pathlab_paper_agent.citations import (
    CitationCandidate,
    CitationReference,
    check_citation_coverage,
    check_orphan_cites,
    extract_cite_keys,
    generate_bibtex,
    select_references,
    verify_candidates,
)
from pathlab_paper_agent.citations.pubmed import PubMedClient
from pathlab_paper_agent.citations.semantic_scholar import SemanticScholarClient
from pathlab_paper_agent.pipeline import create_dev_run, run_stage


def test_verifier_filters_deduplicates_and_keeps_valid_candidates() -> None:
    candidates = [
        CitationCandidate(
            title="Attention-Based Deep Multiple Instance Learning",
            claimed_title="Attention Based Deep Multiple Instance Learning",
            source="semantic_scholar",
            authors=("Ilse M",),
            year=2018,
            venue="ICML",
            s2_paper_id="s2-1",
            citation_count=1000,
        ),
        CitationCandidate(
            title="Attention-Based Deep Multiple Instance Learning",
            source="pubmed",
            authors=("Ilse M",),
            year=2018,
            doi="10.1/example",
        ),
        CitationCandidate(title="", year=2020),
        CitationCandidate(
            title="Future Paper",
            claimed_title="Completely Different Title",
            year=2035,
        ),
    ]

    report = verify_candidates(candidates, cutoff_year=2026)

    assert len(report.verified) == 1
    assert report.verified[0].title == "Attention-Based Deep Multiple Instance Learning"
    reasons = {reason for item in report.rejected for reason in item["reasons"]}
    assert "duplicate" in reasons
    assert "missing_title" in reasons
    assert "after_cutoff_year" in reasons
    assert "title_similarity_below_threshold" in reasons


def test_ref_selector_and_bibtex_generation_are_stable() -> None:
    candidates = [
        CitationCandidate(
            title="Computational pathology with whole-slide images",
            source="pubmed",
            authors=("Smith J", "Lee K"),
            year=2020,
            venue="Nature Medicine",
            doi="10.1000/test",
            cluster="macro",
        ),
        CitationCandidate(
            title="Multiple instance learning for WSI",
            source="semantic_scholar",
            authors=("Doe A",),
            year=2021,
            venue="MICCAI",
            s2_paper_id="abc",
            cluster="mil",
        ),
    ]

    selection = select_references(candidates, max_refs=10)
    bibtex = generate_bibtex(selection.selected_refs)

    assert len(selection.selected_refs) == 2
    assert len(selection.required_cites) == 2
    assert "@article{" in bibtex
    assert "title = {Computational pathology with whole-slide images}" in bibtex
    assert "doi = {10.1000/test}" in bibtex


def test_coverage_and_orphan_gates() -> None:
    refs = (
        CitationReference(key="Smith2020", title="A", required=True),
        CitationReference(key="Doe2021", title="B", required=False),
    )
    used = extract_cite_keys(r"See \citep[see][p.~3]{Smith2020} and \parencite{Ghost}.")

    coverage = check_citation_coverage(refs, (refs[0],), used)
    orphan = check_orphan_cites(used, refs)

    assert coverage.status == "pass"
    assert coverage.coverage == 1.0
    assert coverage.unused_selected == ("Doe2021",)
    assert orphan.status == "fail"
    assert orphan.orphan_cites == ("Ghost",)


def test_semantic_scholar_client_parses_search_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/paper/search")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "s2paper",
                        "title": "WSI MIL",
                        "abstract": "abstract",
                        "authors": [{"name": "Author One"}],
                        "year": 2022,
                        "venue": "MICCAI",
                        "externalIds": {"DOI": "10.2/s2", "PubMed": "123"},
                        "url": "https://example.test/s2",
                        "citationCount": 7,
                    }
                ]
            },
        )

    client = SemanticScholarClient(transport=httpx.MockTransport(handler))
    try:
        results = client.search("wsi mil", cluster="mil")
    finally:
        client.close()

    assert len(results) == 1
    assert results[0].s2_paper_id == "s2paper"
    assert results[0].doi == "10.2/s2"
    assert results[0].pmid == "123"
    assert results[0].cluster == "mil"


def test_pubmed_client_parses_search_and_summary_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["111"]}})
        if request.url.path.endswith("/esummary.fcgi"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "111": {
                            "uid": "111",
                            "title": "Computational pathology review",
                            "authors": [{"name": "Path A"}],
                            "pubdate": "2021 Jan",
                            "fulljournalname": "J Pathol",
                            "articleids": [{"idtype": "doi", "value": "10.3/pubmed"}],
                        }
                    }
                },
            )
        raise AssertionError(f"unexpected URL {request.url}")

    client = PubMedClient(transport=httpx.MockTransport(handler))
    try:
        results = client.search("computational pathology", cluster="macro")
    finally:
        client.close()

    assert len(results) == 1
    assert results[0].pmid == "111"
    assert results[0].doi == "10.3/pubmed"
    assert results[0].year == 2021
    assert results[0].url == "https://pubmed.ncbi.nlm.nih.gov/111/"


@pytest.mark.asyncio
async def test_literature_stage_uses_manual_candidates_without_network(tmp_path) -> None:
    paper_id, paths = await create_dev_run(paper_id="paper_m8a", uploads_dir=tmp_path)
    run_stage(paper_id, "outlining", uploads_dir=tmp_path)
    paths.citations_dir.mkdir(parents=True, exist_ok=True)
    manual_pool = {
        "items": [
            {
                "title": "Attention-Based Deep Multiple Instance Learning",
                "source": "semantic_scholar",
                "authors": ["Ilse M"],
                "year": 2018,
                "venue": "ICML",
                "s2_paper_id": "s2-ilse",
                "citation_count": 1000,
                "cluster": "multiple instance learning for pathology",
            },
            {
                "title": "Clinical validation in computational pathology",
                "source": "pubmed",
                "authors": ["Pathologist P"],
                "year": 2021,
                "venue": "J Pathol",
                "pmid": "999",
                "cluster": "macro",
            },
        ]
    }
    (paths.citations_dir / "discovery_pool.json").write_text(
        json.dumps(manual_pool), encoding="utf-8"
    )

    manifest = run_stage(paper_id, "literature_review", uploads_dir=tmp_path)

    selected = json.loads((paths.citations_dir / "selected_refs.json").read_text())
    required = json.loads((paths.citations_dir / "required_cites.json").read_text())
    coverage = json.loads((paths.citations_dir / "coverage_report.json").read_text())
    intro_text = (paths.intro_rw_draft_dir / "introduction.tex").read_text()

    assert manifest.current_stage.value == "literature_review"
    assert len(selected["items"]) == 2
    assert len(required["items"]) == 2
    assert coverage["status"] == "pass"
    assert coverage["orphan_status"] == "pass"
    assert coverage["orphan_cites"] == []
    assert coverage["coverage"] == 1.0
    assert "\\cite{" in intro_text
    assert "@article" in paths.refs_bib.read_text()
    assert manifest.artifact_index["citations/selected_refs.json"]["visibility"] == "private_backend_only"

    run_stage(paper_id, "section_writing", uploads_dir=tmp_path)
    section_intro_text = (paths.sections_dir / "introduction.tex").read_text()
    assert "\\cite{" in section_intro_text
    assert "\\section{Introduction}" in section_intro_text
