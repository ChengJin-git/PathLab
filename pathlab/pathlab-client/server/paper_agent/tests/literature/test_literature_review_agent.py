from __future__ import annotations

import json

import pytest

from pathlab_paper_agent.agents.literature_review_agent import (
    LiteratureCoverageError,
    LiteraturePhiLeakError,
    LiteratureReviewAgentError,
    LiteratureReviewAgent,
    LiteratureReviewInputs,
    load_existing_candidates,
)
from pathlab_paper_agent.citations import CitationCandidate
from pathlab_paper_agent.llm import LLMResponse
from pathlab_paper_agent.pipeline import create_dev_run
from pathlab_paper_agent.schemas import PaperManifest
from pathlab_paper_agent.stages.literature import run as run_literature


class MockLLM:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(
        self,
        messages,
        *,
        temperature: float = 0.2,
        response_format=None,
        stream=None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "response_format": response_format,
                "stream": stream,
            }
        )
        response = self.responses.pop(0)
        content = response(messages[-1].content) if callable(response) else response
        return LLMResponse(
            content=json.dumps(content) if isinstance(content, dict) else str(content),
            model="mock",
            provider="mock",
        )


class MockSearchProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, str | None]] = []
        self.closed = False

    def search_semantic_scholar(
        self,
        query: str,
        *,
        limit: int = 10,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        self.calls.append(("semantic_scholar", query, limit, cluster))
        return [_candidate(query, "semantic_scholar", cluster, "S2 Author")]

    def search_pubmed(
        self,
        query: str,
        *,
        limit: int = 10,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        self.calls.append(("pubmed", query, limit, cluster))
        return [_candidate(query, "pubmed", cluster, "PubMed Author")]

    def search_openalex(
        self,
        query: str,
        *,
        limit: int = 10,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        self.calls.append(("openalex", query, limit, cluster))
        return [_candidate(query, "openalex", cluster, "OpenAlex Author")]

    def close(self) -> None:
        self.closed = True


class EmptySearchProvider(MockSearchProvider):
    def search_semantic_scholar(
        self,
        query: str,
        *,
        limit: int = 10,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        self.calls.append(("semantic_scholar", query, limit, cluster))
        return []

    def search_pubmed(
        self,
        query: str,
        *,
        limit: int = 10,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        self.calls.append(("pubmed", query, limit, cluster))
        return []

    def search_openalex(
        self,
        query: str,
        *,
        limit: int = 10,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        self.calls.append(("openalex", query, limit, cluster))
        return []


def _candidate(query: str, source: str, cluster: str | None, author: str) -> CitationCandidate:
    slug = query.lower().replace(" ", "-")[:32]
    title = f"{source.replace('_', ' ').title()} {query.title()}"
    return CitationCandidate(
        title=title,
        claimed_title=title,
        source=source,
        abstract=f"Abstract for {title}.",
        authors=(author,),
        year=2022,
        venue="Mock Venue",
        doi=f"10.1234/{slug}" if source == "pubmed" else None,
        pmid=f"pmid-{slug}" if source == "pubmed" else None,
        s2_paper_id=f"s2-{slug}" if source == "semantic_scholar" else None,
        openalex_id=f"https://openalex.org/W{slug}" if source == "openalex" else None,
        url=f"https://example.test/{slug}",
        citation_count=5,
        query=query,
        cluster=cluster,
    )


def _inputs(outline: dict | None = None) -> LiteratureReviewInputs:
    return LiteratureReviewInputs(
        outline=outline
        or {
            "macro_lit_search": ["whole slide image computational pathology"],
            "micro_lit_clusters": [
                {
                    "cluster": "clinical validation",
                    "queries": ["AI pathology clinical validation"],
                }
            ],
            "section_plan": [
                {
                    "section": "Introduction",
                    "citation_hints": ["computational pathology"],
                }
            ],
            "template_style": {"max_refs": 30},
        },
        template_style={"max_refs": 30},
        submission_cutoff_year=2026,
        paper_title="Mock PathLab Literature Paper",
    )


def _search_response() -> dict:
    return {
        "queries": [
            {
                "query": "whole slide image computational pathology",
                "cluster": "macro",
                "source": "semantic_scholar",
                "origin": "macro_lit_search",
                "limit": 10,
            },
            {
                "query": "AI pathology clinical validation",
                "cluster": "clinical validation",
                "source": "pubmed",
                "origin": "micro_lit_clusters",
                "limit": 10,
            },
        ]
    }


def _search_all_response() -> dict:
    return {
        "queries": [
            {
                "query": "whole slide image computational pathology",
                "cluster": "macro",
                "source": "all",
                "origin": "macro_lit_search",
                "limit": 10,
            }
        ]
    }


def _payload_from_prompt(prompt: str) -> dict:
    return json.loads(prompt.split("Input payload:", 1)[1].strip())


def _draft_all_selected(prompt: str) -> dict:
    payload = _payload_from_prompt(prompt)
    keys = [item["key"] for item in payload["selected_refs"]]
    first = keys[:1]
    rest = keys[1:] or keys[:1]
    return {
        "introduction_tex": "\\section{Introduction}\n"
        f"Computational pathology motivates this study \\cite{{{','.join(first)}}}.\n",
        "related_work_tex": "\\section{Related Work}\n"
        f"Prior WSI validation work frames the method \\cite{{{','.join(rest)}}}.\n",
    }


def _draft_first_selected_only(prompt: str) -> dict:
    payload = _payload_from_prompt(prompt)
    key = payload["selected_refs"][0]["key"]
    return {
        "introduction_tex": f"\\section{{Introduction}}\nOnly one citation is used \\cite{{{key}}}.\n",
        "related_work_tex": "\\section{Related Work}\nNo additional citation.\n",
    }


def _draft_with_orphan(_prompt: str) -> dict:
    return {
        "introduction_tex": "\\section{Introduction}\nThis cites an unknown key \\cite{Ghost2026}.\n",
        "related_work_tex": "\\section{Related Work}\nNo verified citation.\n",
    }


def test_literature_agent_expands_queries_searches_and_drafts_with_mocks() -> None:
    search = MockSearchProvider()
    llm = MockLLM([_search_response(), _draft_all_selected])
    agent = LiteratureReviewAgent(llm, search_provider=search)

    result = agent.generate(_inputs())

    assert len(llm.calls) == 2
    assert llm.calls[0]["response_format"] == {"type": "json_object"}
    assert [call[0] for call in search.calls] == ["semantic_scholar", "pubmed"]
    assert result.discovery_mode == "api_search"
    assert len(result.selection.selected_refs) == 2
    assert result.coverage_report["status"] == "pass"
    assert result.coverage_report["selected_coverage"] == 1.0
    assert "@article" in result.bibtex
    assert "\\section{Introduction}" in result.draft.introduction_tex


def test_literature_agent_routes_all_queries_to_openalex_too() -> None:
    search = MockSearchProvider()
    llm = MockLLM([_search_all_response(), _draft_all_selected])
    agent = LiteratureReviewAgent(llm, search_provider=search)

    result = agent.generate(_inputs())

    assert [call[0] for call in search.calls] == ["semantic_scholar", "pubmed", "openalex"]
    assert {ref.source for ref in result.selection.selected_refs} == {
        "semantic_scholar",
        "pubmed",
        "openalex",
    }
    assert result.coverage_report["status"] == "pass"


@pytest.mark.asyncio
async def test_literature_stage_writes_refs_reports_and_intro_rw_drafts(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_lit_stage", uploads_dir=tmp_path)
    paths.outline_json.write_text(json.dumps(_inputs().outline), encoding="utf-8")
    (paths.sections_dir / "introduction.tex").write_text("USER INTRO\n", encoding="utf-8")
    (paths.sections_dir / "related_work.tex").write_text("USER RELATED\n", encoding="utf-8")
    manifest = PaperManifest.model_validate(json.loads(paths.manifest.read_text(encoding="utf-8")))
    agent = LiteratureReviewAgent(
        MockLLM([_search_response(), _draft_all_selected]),
        search_provider=MockSearchProvider(),
    )

    run_literature(paths, manifest, agent=agent)

    selected = json.loads((paths.citations_dir / "selected_refs.json").read_text(encoding="utf-8"))
    coverage = json.loads((paths.citations_dir / "coverage_report.json").read_text(encoding="utf-8"))
    intro = (paths.intro_rw_draft_dir / "introduction.tex").read_text(encoding="utf-8")
    related = (paths.intro_rw_draft_dir / "related_work.tex").read_text(encoding="utf-8")
    discovery = json.loads((paths.citations_dir / "discovery_pool.json").read_text(encoding="utf-8"))

    assert len(selected["items"]) == 2
    assert coverage["status"] == "pass"
    assert coverage["selected_coverage"] == 1.0
    assert discovery["generated_by"] == "m8b_literature_agent"
    assert "citations/selected_refs.json" in manifest.artifact_index
    assert "\\cite{" in intro
    assert "\\cite{" in related
    assert (paths.sections_dir / "introduction.tex").read_text(encoding="utf-8") == "USER INTRO\n"
    assert (paths.sections_dir / "related_work.tex").read_text(encoding="utf-8") == "USER RELATED\n"
    assert "@article" in paths.refs_bib.read_text(encoding="utf-8")


def test_literature_agent_hard_fails_when_selected_coverage_is_low() -> None:
    agent = LiteratureReviewAgent(
        MockLLM([_search_response(), _draft_first_selected_only]),
        search_provider=MockSearchProvider(),
    )

    with pytest.raises(LiteratureCoverageError) as exc_info:
        agent.generate(_inputs())

    assert exc_info.value.result.coverage_report["status"] == "fail"
    assert exc_info.value.result.coverage_report["selected_coverage"] == 0.5


def test_literature_agent_hard_fails_on_orphan_citation() -> None:
    agent = LiteratureReviewAgent(
        MockLLM([_search_response(), _draft_with_orphan]),
        search_provider=MockSearchProvider(),
    )

    with pytest.raises(LiteratureCoverageError) as exc_info:
        agent.generate(_inputs())

    assert exc_info.value.result.coverage_report["orphan_status"] == "fail"
    assert exc_info.value.result.coverage_report["orphan_cites"] == ["Ghost2026"]


def test_literature_agent_hard_fails_when_no_refs_are_selected() -> None:
    llm = MockLLM([_search_response(), _draft_all_selected])
    agent = LiteratureReviewAgent(llm, search_provider=EmptySearchProvider())

    with pytest.raises(LiteratureReviewAgentError, match="No verified references"):
        agent.generate(_inputs())

    assert len(llm.calls) == 1


@pytest.mark.parametrize(
    ("private_query", "expected_match"),
    [
        ("results from /private/pathlab/raw.csv", "raw_paths"),
        (r"raw share \\nas01\pathlab\slide.svs", "raw_paths"),
        ("cohort recruited 2024-01-15 at the trial site", "dates"),
    ],
)
def test_literature_prompt_phi_hard_fails_before_llm_call(
    private_query: str, expected_match: str
) -> None:
    llm = MockLLM([_search_response(), _draft_all_selected])
    agent = LiteratureReviewAgent(llm, search_provider=MockSearchProvider())
    outline = {
        "macro_lit_search": [private_query],
        "micro_lit_clusters": [],
        "section_plan": [],
    }

    with pytest.raises(LiteraturePhiLeakError, match=expected_match):
        agent.generate(_inputs(outline))

    assert llm.calls == []


def test_generated_discovery_pool_is_not_reused_as_manual_seed(tmp_path) -> None:
    pool = tmp_path / "discovery_pool.json"
    pool.write_text(
        json.dumps(
            {
                "mode": "api_search",
                "generated_by": "m8b_literature_agent",
                "items": [
                    {
                        "title": "Stale prior run candidate",
                        "source": "semantic_scholar",
                        "year": 2020,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert load_existing_candidates(pool) is None
