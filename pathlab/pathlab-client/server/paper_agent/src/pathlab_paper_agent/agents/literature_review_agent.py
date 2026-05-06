"""Literature Review Agent derived from PaperOrchestra Appendix F.3."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Protocol

from ..bootstrap import ensure_server_on_path

ensure_server_on_path()

from ..citations import (  # noqa: E402
    CitationCandidate,
    CitationReference,
    ReferenceSelection,
    VerificationReport,
    check_citation_coverage,
    check_orphan_cites,
    generate_bibtex,
    select_references,
    verify_candidates,
)
from . import _common  # noqa: E402
from ..citations.coverage_gate import extract_cite_keys  # noqa: E402
from ..citations.openalex import OpenAlexClient  # noqa: E402
from ..citations.pubmed import PubMedClient  # noqa: E402
from ..citations.semantic_scholar import SemanticScholarClient  # noqa: E402
from ..evidence.phi import PhiScrubber  # noqa: E402
from ..llm import LLMClient, LLMMessage, LLMResponse, OpenAICompatibleLLMClient  # noqa: E402
from ..templates import get_template  # noqa: E402

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)
_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s,;\"']+")
_UNC_PATH_RE = re.compile(
    r"\\\\[A-Za-z0-9_.-]+\\[A-Za-z0-9_. -]+(?:\\[A-Za-z0-9_. -]+)*"
)
_POSIX_PATH_RE = re.compile(
    r"(?<![\w:/])/(?:Users|home|private|var|tmp|mnt|data|scratch|nfs|Volumes|workspace|opt|srv)"
    r"(?:/[^\s,;\"']+)+"
)
# Mirrors the M7 outline agent's hard-fail set: dates are PHI when paired with
# a cohort or institution, so YYYY-MM-DD strings must not reach an LLM prompt
# even though the M3 scrubber already replaces them upstream.
_PHI_HARD_FAIL_KEYS = ("raw_paths", "case_ids", "institution_names", "dates")
_DEFAULT_MAX_REFS = 30
_DEFAULT_SEARCH_LIMIT = 10
_DEFAULT_CONCURRENCY = 10
_MIN_SELECTED_COVERAGE = 0.9
_GENERATED_DISCOVERY_MARKER = "m8b_literature_agent"
_MANUAL_DISCOVERY_MODES = {"manual", "manual_candidates", "manual_seed", "manual_fixture"}


class LiteratureReviewAgentError(RuntimeError):
    """Raised when the Literature Review Agent cannot complete safely."""


class LiteraturePhiLeakError(LiteratureReviewAgentError):
    """Raised when private identifiers would reach an LLM prompt or output."""


@dataclass(frozen=True)
class ExpandedQuery:
    """One concrete API search query generated from the outline."""

    query: str
    cluster: str
    source: str = "both"
    origin: str = "outline"
    limit: int = _DEFAULT_SEARCH_LIMIT

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "cluster": self.cluster,
            "source": self.source,
            "origin": self.origin,
            "limit": self.limit,
        }


@dataclass(frozen=True)
class LiteratureReviewInputs:
    """Inputs consumed by the Literature Review Agent."""

    outline: dict[str, Any]
    template_style: dict[str, Any] = field(default_factory=dict)
    submission_cutoff_year: int | None = None
    paper_title: str | None = None

    @classmethod
    def from_paths(cls, paths: Any, config: Any) -> "LiteratureReviewInputs":
        outline = _read_json_object_or_default(paths.outline_json, {})
        template_style = _template_style_from_outline_or_config(outline, config)
        cutoff_year = _cutoff_year_from_env()
        return cls(
            outline=outline,
            template_style=template_style,
            submission_cutoff_year=cutoff_year,
            paper_title=getattr(config, "title", None),
        )


@dataclass(frozen=True)
class LiteratureDraft:
    """LLM-authored introduction and related-work draft."""

    introduction_tex: str
    related_work_tex: str


@dataclass(frozen=True)
class LiteratureReviewResult:
    """Artifacts produced by the Literature Review Agent."""

    queries: list[ExpandedQuery]
    candidates: list[CitationCandidate]
    verification: VerificationReport
    selection: ReferenceSelection
    bibtex: str
    draft: LiteratureDraft
    coverage_report: dict[str, Any]
    discovery_mode: str


class LiteratureCoverageError(LiteratureReviewAgentError):
    """Raised after artifacts are assembled when citation coverage fails."""

    def __init__(self, message: str, result: LiteratureReviewResult) -> None:
        super().__init__(message)
        self.result = result


class CitationSearchProvider(Protocol):
    """Search provider wrapper around the deterministic M8a API clients."""

    def search_semantic_scholar(
        self,
        query: str,
        *,
        limit: int = _DEFAULT_SEARCH_LIMIT,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        """Return S2 candidates for one query."""

    def search_pubmed(
        self,
        query: str,
        *,
        limit: int = _DEFAULT_SEARCH_LIMIT,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        """Return PubMed candidates for one query."""

    def search_openalex(
        self,
        query: str,
        *,
        limit: int = _DEFAULT_SEARCH_LIMIT,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        """Return OpenAlex candidates for one query."""

    def close(self) -> None:
        """Release any underlying clients."""


class ProductionCitationSearchProvider:
    """Adapter that treats M8a S2 and PubMed clients as a library."""

    def __init__(self) -> None:
        self._s2 = SemanticScholarClient(api_key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY"))
        self._pubmed = PubMedClient(
            api_key=os.environ.get("PUBMED_API_KEY"),
            email=os.environ.get("PUBMED_EMAIL"),
        )
        self._openalex = OpenAlexClient(
            api_key=os.environ.get("OPENALEX_API_KEY"),
            mailto=os.environ.get("OPENALEX_MAILTO") or os.environ.get("OPENALEX_EMAIL"),
        )

    def search_semantic_scholar(
        self,
        query: str,
        *,
        limit: int = _DEFAULT_SEARCH_LIMIT,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        return self._s2.search(query, limit=limit, cluster=cluster)

    def search_pubmed(
        self,
        query: str,
        *,
        limit: int = _DEFAULT_SEARCH_LIMIT,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        return self._pubmed.search(query, limit=limit, cluster=cluster)

    def search_openalex(
        self,
        query: str,
        *,
        limit: int = _DEFAULT_SEARCH_LIMIT,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        return self._openalex.search(query, limit=limit, cluster=cluster)

    def close(self) -> None:
        self._s2.close()
        self._pubmed.close()
        self._openalex.close()


class LiteratureReviewAgent:
    """Orchestrate query expansion, citation verification, and Intro/RW drafting."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        search_provider: CitationSearchProvider | None = None,
        lit_search_prompt: str | None = None,
        intro_rw_prompt: str | None = None,
        max_concurrency: int = _DEFAULT_CONCURRENCY,
        min_selected_coverage: float = _MIN_SELECTED_COVERAGE,
    ) -> None:
        self.llm_client = llm_client or _default_llm_client()
        self.search_provider = search_provider or _default_search_provider()
        self._owns_search_provider = search_provider is None
        self.lit_search_prompt = lit_search_prompt or _load_prompt_template("lit_search_v1.txt")
        self.intro_rw_prompt = intro_rw_prompt or _load_prompt_template("intro_rw_draft_v1.txt")
        self.max_concurrency = max(1, max_concurrency)
        self.min_selected_coverage = min_selected_coverage

    def close(self) -> None:
        if self._owns_search_provider:
            self.search_provider.close()

    def generate(
        self,
        inputs: LiteratureReviewInputs,
        *,
        existing_candidates: Sequence[CitationCandidate] | None = None,
    ) -> LiteratureReviewResult:
        queries = self.expand_queries(inputs)
        if existing_candidates is not None:
            candidates = list(existing_candidates)
            discovery_mode = "manual_candidates"
        else:
            candidates = self.discover_candidates(queries)
            discovery_mode = "api_search"
            if isinstance(self.search_provider, _NoNetworkCitationSearchProvider):
                discovery_mode = "ci_no_network_api_fixture"

        verification = verify_candidates(candidates, cutoff_year=inputs.submission_cutoff_year)
        selection = select_references(
            verification.verified,
            max_refs=_max_refs_from_inputs(inputs),
        )
        _assert_non_empty_selection(selection)
        draft = self.draft_intro_related_work(inputs, selection.selected_refs, selection.required_cites)
        coverage_report = self.coverage_report(selection.selected_refs, selection.required_cites, draft)
        result = LiteratureReviewResult(
            queries=queries,
            candidates=candidates,
            verification=verification,
            selection=selection,
            bibtex=generate_bibtex(selection.selected_refs),
            draft=draft,
            coverage_report=coverage_report,
            discovery_mode=discovery_mode,
        )
        if coverage_report["status"] != "pass":
            raise LiteratureCoverageError(
                "Citation coverage gate failed: "
                f"selected_coverage={coverage_report['selected_coverage']:.3f}, "
                f"orphan_status={coverage_report['orphan_status']}, "
                f"coverage_status={coverage_report['coverage_status']}",
                result,
            )
        return result

    def expand_queries(self, inputs: LiteratureReviewInputs) -> list[ExpandedQuery]:
        payload = {
            "paper_title": inputs.paper_title,
            "outline_literature_fields": _outline_literature_fields(inputs.outline),
            "template_style": inputs.template_style,
            "submission_cutoff_year": inputs.submission_cutoff_year,
            "pathology_query_dictionary": [
                "computational pathology",
                "whole slide image",
                "multiple instance learning",
                "clinical validation",
                "external validation",
                "histopathology deep learning",
            ],
            "search_sources": ["semantic_scholar", "pubmed", "openalex"],
        }
        _assert_no_private_identifiers(payload, context="literature search prompt payload")
        prompt = _render_prompt(self.lit_search_prompt, payload)
        _assert_no_private_identifiers(prompt, context="literature search prompt")
        response = self.llm_client.complete(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "You are PathLab's Literature Review Agent. Return only JSON "
                        "with concrete Semantic Scholar and PubMed search queries."
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        queries = _parse_expanded_queries(_response_text(response))
        if not queries:
            raise LiteratureReviewAgentError("Literature search LLM returned no queries")
        _assert_no_private_identifiers([query.to_dict() for query in queries], context="expanded literature queries")
        return queries

    def discover_candidates(self, queries: Sequence[ExpandedQuery]) -> list[CitationCandidate]:
        futures = {}
        with ThreadPoolExecutor(max_workers=self.max_concurrency) as executor:
            for query in queries:
                for source in _sources_for_query(query.source):
                    future = executor.submit(self._search_one, query, source)
                    futures[future] = (query, source)
            candidates: list[CitationCandidate] = []
            for future in as_completed(futures):
                _query, _source = futures[future]
                try:
                    candidates.extend(future.result())
                except Exception:
                    # Public literature APIs frequently rate-limit or time out.
                    # Keep the review moving when other backends can still
                    # provide verified references; the empty-selection gate
                    # below remains the hard failure if every source fails.
                    continue
        return candidates

    def draft_intro_related_work(
        self,
        inputs: LiteratureReviewInputs,
        selected_refs: Sequence[CitationReference],
        required_cites: Sequence[CitationReference],
    ) -> LiteratureDraft:
        payload = {
            "paper_title": inputs.paper_title,
            "outline": inputs.outline,
            "template_style": inputs.template_style,
            "selected_refs": [ref.to_dict() for ref in selected_refs],
            "required_cites": [ref.to_dict() for ref in required_cites],
            "draft_constraints": {
                "allowed_cite_keys": [ref.key for ref in selected_refs],
                "required_cite_keys": [ref.key for ref in required_cites],
                "min_selected_coverage": self.min_selected_coverage,
                "write_destination": "drafts/intro_rw_draft",
            },
        }
        _assert_no_private_identifiers(payload, context="intro/RW draft prompt payload")
        prompt = _render_prompt(self.intro_rw_prompt, payload)
        _assert_no_private_identifiers(prompt, context="intro/RW draft prompt")
        response = self.llm_client.complete(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "You are PathLab's Literature Review Agent. Draft only "
                        "Introduction and Related Work LaTeX using selected citations."
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.25,
            response_format={"type": "json_object"},
        )
        draft = _parse_literature_draft(_response_text(response))
        _assert_no_private_identifiers(
            {"introduction": draft.introduction_tex, "related_work": draft.related_work_tex},
            context="intro/RW draft output",
        )
        return draft

    def coverage_report(
        self,
        selected_refs: Sequence[CitationReference],
        required_cites: Sequence[CitationReference],
        draft: LiteratureDraft,
    ) -> dict[str, Any]:
        used_keys = extract_cite_keys(f"{draft.introduction_tex}\n{draft.related_work_tex}")
        required_report = check_citation_coverage(selected_refs, required_cites, used_keys)
        orphan_report = check_orphan_cites(used_keys, selected_refs)
        selected_keys = {ref.key for ref in selected_refs}
        used_selected = selected_keys & used_keys
        selected_coverage = 1.0 if not selected_keys else len(used_selected) / len(selected_keys)
        payload = required_report.to_dict()
        payload.update(
            {
                "coverage_status": required_report.status,
                "orphan_status": orphan_report.status,
                "orphan_cites": list(orphan_report.orphan_cites),
                "required_cite_keys": sorted(ref.key for ref in required_cites),
                "selected_ref_keys": sorted(selected_keys),
                "used_cite_keys": sorted(used_keys),
                "selected_coverage": selected_coverage,
                "min_selected_coverage": self.min_selected_coverage,
            }
        )
        payload["status"] = (
            "pass"
            if required_report.status == "pass"
            and orphan_report.status == "pass"
            and selected_coverage >= self.min_selected_coverage
            else "fail"
        )
        return payload

    def _search_one(self, query: ExpandedQuery, source: str) -> list[CitationCandidate]:
        if source == "semantic_scholar":
            return self.search_provider.search_semantic_scholar(
                query.query,
                limit=query.limit,
                cluster=query.cluster,
            )
        if source == "pubmed":
            return self.search_provider.search_pubmed(
                query.query,
                limit=query.limit,
                cluster=query.cluster,
            )
        if source == "openalex":
            return self.search_provider.search_openalex(
                query.query,
                limit=query.limit,
                cluster=query.cluster,
            )
        raise LiteratureReviewAgentError(f"Unknown search source: {source}")


class _NoNetworkLiteratureLLMClient:
    """CI fixture that keeps unrelated pipeline tests off real LLM providers."""

    def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float = 0.2,
        response_format: Mapping[str, Any] | None = None,
        stream: bool | None = None,
    ) -> LLMResponse:
        del temperature, response_format, stream
        prompt = messages[-1].content if messages else ""
        payload = _payload_from_prompt(prompt)
        if "selected_refs" in payload:
            content = _deterministic_draft_response(payload)
        else:
            content = _deterministic_query_response(payload)
        return LLMResponse(
            content=json.dumps(content),
            model="no-network-literature-fixture",
            provider="ci_no_network",
        )


class _NoNetworkCitationSearchProvider:
    """Deterministic citation fixture used only while pytest is running."""

    def search_semantic_scholar(
        self,
        query: str,
        *,
        limit: int = _DEFAULT_SEARCH_LIMIT,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        del limit
        return [_fixture_candidate(query, source="semantic_scholar", cluster=cluster)]

    def search_pubmed(
        self,
        query: str,
        *,
        limit: int = _DEFAULT_SEARCH_LIMIT,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        del limit
        return [_fixture_candidate(query, source="pubmed", cluster=cluster)]

    def search_openalex(
        self,
        query: str,
        *,
        limit: int = _DEFAULT_SEARCH_LIMIT,
        cluster: str | None = None,
    ) -> list[CitationCandidate]:
        del limit
        return [_fixture_candidate(query, source="openalex", cluster=cluster)]

    def close(self) -> None:
        return None


def load_existing_candidates(path: Path) -> list[CitationCandidate] | None:
    """Load a pre-seeded discovery pool, preserving M8a manual-fixture support."""
    if not path.exists():
        return None
    payload = _read_json_object_or_default(path, {})
    if payload.get("generated_by") == _GENERATED_DISCOVERY_MARKER:
        return None
    mode = str(payload.get("mode") or "").strip().lower()
    if mode and mode not in _MANUAL_DISCOVERY_MODES:
        return None
    items = payload.get("items") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []
    return [CitationCandidate.from_dict(item) for item in items if isinstance(item, dict)]


def _default_llm_client() -> LLMClient:
    if _ci_should_disable_network_clients():
        return _NoNetworkLiteratureLLMClient()
    return OpenAICompatibleLLMClient()


def _default_search_provider() -> CitationSearchProvider:
    if _ci_should_disable_network_clients():
        return _NoNetworkCitationSearchProvider()
    return ProductionCitationSearchProvider()


def _ci_should_disable_network_clients() -> bool:
    if os.environ.get("PAPER_GEN_LITERATURE_ALLOW_NETWORK_IN_TESTS") == "1":
        return False
    return "PYTEST_CURRENT_TEST" in os.environ


def _outline_literature_fields(outline: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "macro_lit_search": outline.get("macro_lit_search") or [],
        "micro_lit_clusters": outline.get("micro_lit_clusters") or [],
        "section_plan_citation_hints": _section_plan_citation_hints(outline),
    }


def _section_plan_citation_hints(outline: Mapping[str, Any]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    section_plan = outline.get("section_plan") or []
    if not isinstance(section_plan, list):
        return hints
    for item in section_plan:
        if not isinstance(item, Mapping):
            continue
        citation_hints = item.get("citation_hints") or []
        if citation_hints:
            hints.append({"section": item.get("section"), "citation_hints": citation_hints})
    return hints


def _assert_non_empty_selection(selection: ReferenceSelection) -> None:
    if not selection.selected_refs:
        raise LiteratureReviewAgentError(
            "No verified references were selected; refusing to produce an empty bibliography"
        )
    if not selection.required_cites:
        raise LiteratureReviewAgentError(
            "No required citations were selected; every literature run must preserve core cites"
        )


def _parse_expanded_queries(text: str) -> list[ExpandedQuery]:
    payload = _parse_json_object(text, label="literature search response")
    raw_queries = payload.get("queries")
    if not isinstance(raw_queries, list):
        raise LiteratureReviewAgentError("Literature search response missing queries list")
    queries: list[ExpandedQuery] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw_queries:
        if not isinstance(item, Mapping):
            continue
        query_text = _one_sentence_query(str(item.get("query") or ""))
        if not query_text:
            continue
        source = _normalize_source(str(item.get("source") or "both"))
        cluster = str(item.get("cluster") or "general")
        origin = str(item.get("origin") or "outline")
        limit = _safe_int(item.get("limit"), default=_DEFAULT_SEARCH_LIMIT)
        key = (query_text.casefold(), cluster.casefold(), source)
        if key in seen:
            continue
        seen.add(key)
        queries.append(
            ExpandedQuery(
                query=query_text,
                cluster=cluster,
                source=source,
                origin=origin,
                limit=max(1, min(limit, _DEFAULT_SEARCH_LIMIT)),
            )
        )
    return queries


def _parse_literature_draft(text: str) -> LiteratureDraft:
    payload = _parse_json_object(text, label="intro/RW draft response")
    intro = payload.get("introduction_tex") or payload.get("introduction")
    related = payload.get("related_work_tex") or payload.get("related_work")
    if not isinstance(intro, str) or not intro.strip():
        raise LiteratureReviewAgentError("Intro/RW draft response missing introduction_tex")
    if not isinstance(related, str) or not related.strip():
        raise LiteratureReviewAgentError("Intro/RW draft response missing related_work_tex")
    return LiteratureDraft(
        introduction_tex=_ensure_section(intro.strip(), "Introduction"),
        related_work_tex=_ensure_section(related.strip(), "Related Work"),
    )


def _parse_json_object(text: str, *, label: str) -> dict[str, Any]:
    stripped = text.strip()
    fence_match = _JSON_FENCE_RE.search(stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        value = _decode_first_json_object(stripped, label=label)
    if not isinstance(value, dict):
        raise LiteratureReviewAgentError(f"{label} must be a JSON object")
    return value


def _decode_first_json_object(text: str, *, label: str) -> Any:
    value = _common.decode_first_json_object(text)
    if value is None:
        raise LiteratureReviewAgentError(f"{label} did not contain a JSON object")
    return value


_response_text = _common.response_text


def _render_prompt(template: str, payload: Mapping[str, Any]) -> str:
    payload_json = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    return template.replace("{{INPUT_PAYLOAD_JSON}}", payload_json)


_payload_from_prompt = _common.payload_from_prompt


def _deterministic_query_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    fields = payload.get("outline_literature_fields")
    outline_fields = fields if isinstance(fields, Mapping) else {}
    queries: list[dict[str, Any]] = []
    for query in outline_fields.get("macro_lit_search") or []:
        queries.append(
            {
                "query": _one_sentence_query(str(query)),
                "cluster": "macro",
                "source": "all",
                "origin": "macro_lit_search",
                "limit": _DEFAULT_SEARCH_LIMIT,
            }
        )
    for cluster in outline_fields.get("micro_lit_clusters") or []:
        if not isinstance(cluster, Mapping):
            continue
        cluster_name = str(cluster.get("cluster") or "micro")
        for query in cluster.get("queries") or []:
            queries.append(
                {
                    "query": _one_sentence_query(str(query)),
                    "cluster": cluster_name,
                    "source": "all",
                    "origin": "micro_lit_clusters",
                    "limit": _DEFAULT_SEARCH_LIMIT,
                }
            )
    if not queries:
        queries.append(
            {
                "query": "computational pathology whole slide image clinical validation",
                "cluster": "macro",
                "source": "all",
                "origin": "fallback",
                "limit": _DEFAULT_SEARCH_LIMIT,
            }
        )
    return {"queries": queries}


def _deterministic_draft_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    refs = payload.get("selected_refs") if isinstance(payload.get("selected_refs"), list) else []
    macro_keys: list[str] = []
    micro_keys: list[str] = []
    for ref in refs:
        if not isinstance(ref, Mapping):
            continue
        key = str(ref.get("key") or "")
        if not key:
            continue
        cluster = str(ref.get("cluster") or "")
        if cluster == "macro":
            macro_keys.append(key)
        else:
            micro_keys.append(key)
    if not macro_keys and refs:
        first = refs[0]
        if isinstance(first, Mapping) and first.get("key"):
            macro_keys.append(str(first["key"]))
            micro_keys = [key for key in micro_keys if key != first["key"]]
    intro_cite = _cite_text(macro_keys)
    related_cite = _cite_text(micro_keys)
    all_keys = [str(ref.get("key")) for ref in refs if isinstance(ref, Mapping) and ref.get("key")]
    missing_from_split = [key for key in all_keys if key not in {*macro_keys, *micro_keys}]
    if missing_from_split:
        related_cite = _cite_text([*micro_keys, *missing_from_split])
    introduction = (
        "\\section{Introduction}\n"
        "Computational pathology studies increasingly use whole-slide image analysis "
        "to connect algorithmic predictions with clinically meaningful validation"
    )
    if intro_cite:
        introduction += f" {intro_cite}"
    introduction += ".\n"
    related = (
        "\\section{Related Work}\n"
        "Prior work spans representation learning, multiple instance learning, and "
        "clinical validation protocols for pathology models"
    )
    if related_cite:
        related += f" {related_cite}"
    related += ".\n"
    return {"introduction_tex": introduction, "related_work_tex": related}


def _cite_text(keys: Sequence[str]) -> str:
    cleaned = [key for key in keys if key]
    if not cleaned:
        return ""
    return "\\cite{" + ",".join(cleaned) + "}"


def _fixture_candidate(query: str, *, source: str, cluster: str | None) -> CitationCandidate:
    title = " ".join(word.capitalize() for word in _one_sentence_query(query).split()[:8])
    if not title:
        title = "Computational Pathology Validation"
    normalized_id = re.sub(r"[^A-Za-z0-9]+", "-", f"{source}-{cluster or 'general'}-{title}").strip("-")
    return CitationCandidate(
        title=title,
        claimed_title=title,
        source=source,
        abstract=f"Fixture abstract for {title}.",
        authors=("PathLab Fixture",),
        year=2023,
        venue="Fixture Journal" if source == "pubmed" else "Fixture Conference",
        doi=f"10.0000/{normalized_id.lower()}" if source == "pubmed" else None,
        pmid=normalized_id[:30] if source == "pubmed" else None,
        s2_paper_id=normalized_id[:40] if source == "semantic_scholar" else None,
        openalex_id=f"https://openalex.org/{normalized_id[:32]}" if source == "openalex" else None,
        url=f"https://example.test/{normalized_id}",
        citation_count=10,
        query=query,
        cluster=cluster,
    )


def _sources_for_query(source: str) -> tuple[str, ...]:
    normalized = _normalize_source(source)
    if normalized == "all":
        return ("semantic_scholar", "pubmed", "openalex")
    if normalized == "both":
        return ("semantic_scholar", "pubmed")
    return (normalized,)


def _normalize_source(source: str) -> str:
    normalized = source.strip().lower().replace("-", "_")
    if normalized in {"s2", "semantic", "semantic_scholar", "semanticscholar"}:
        return "semantic_scholar"
    if normalized in {"pubmed", "pmid", "ncbi"}:
        return "pubmed"
    if normalized in {"openalex", "open_alex", "alex"}:
        return "openalex"
    if normalized in {"all", "s2_pubmed_openalex", "semantic_scholar_pubmed_openalex"}:
        return "all"
    if normalized in {"both", "s2_pubmed", "semantic_scholar_pubmed"}:
        return "both"
    return "all"


def _one_sentence_query(value: str) -> str:
    cleaned = " ".join(value.replace("\n", " ").split())
    if not cleaned:
        return ""
    for delimiter in (". ", "? ", "! "):
        if delimiter in cleaned:
            cleaned = cleaned.split(delimiter, 1)[0]
            break
    return cleaned.strip(" .?!")[:240]


def _ensure_section(text: str, title: str) -> str:
    if text.lstrip().startswith("\\section"):
        return text + ("\n" if not text.endswith("\n") else "")
    return f"\\section{{{title}}}\n{text}\n"


def _max_refs_from_inputs(inputs: LiteratureReviewInputs) -> int:
    style = inputs.template_style
    for key in ("max_refs", "max_references"):
        if style.get(key) is not None:
            return _safe_int(style.get(key), default=_DEFAULT_MAX_REFS)
    constraints = style.get("style_constraints")
    if isinstance(constraints, Mapping) and constraints.get("max_references") is not None:
        return _safe_int(constraints.get("max_references"), default=_DEFAULT_MAX_REFS)
    return _DEFAULT_MAX_REFS


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _template_style_from_outline_or_config(outline: Mapping[str, Any], config: Any) -> dict[str, Any]:
    style = outline.get("template_style")
    if isinstance(style, Mapping):
        return dict(style)
    if isinstance(config, Mapping):
        selected_templates = config.get("selected_templates", []) or []
    else:
        selected_templates = getattr(config, "selected_templates", []) or []
    if selected_templates:
        template_id = str(getattr(selected_templates[0], "value", selected_templates[0]))
        return dict(get_template(template_id).style)
    return {}


def _cutoff_year_from_env() -> int:
    raw = os.environ.get("PAPER_GEN_CITATION_CUTOFF_YEAR")
    if raw:
        return _safe_int(raw, default=_current_year())
    return _current_year()


def _current_year() -> int:
    return datetime.now(timezone.utc).year


def _read_json_object_or_default(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise LiteratureReviewAgentError(f"{path} must contain a JSON object")
    return payload


def _assert_no_private_identifiers(value: Any, *, context: str) -> None:
    scrubber = PhiScrubber()
    scrubber.observe(value)
    identifiers = scrubber.private_identifiers()
    paths = _extra_private_paths(value)
    if paths:
        identifiers["raw_paths"] = sorted(set([*identifiers.get("raw_paths", []), *paths]))
    leaked = {
        key: identifiers.get(key, [])
        for key in _PHI_HARD_FAIL_KEYS
        if identifiers.get(key)
    }
    if not leaked:
        return
    counts = ", ".join(f"{key}={len(items)}" for key, items in sorted(leaked.items()))
    raise LiteraturePhiLeakError(f"PHI/private identifiers detected in {context}: {counts}")


def _extra_private_paths(value: Any) -> list[str]:
    matches: set[str] = set()

    def observe(item: Any) -> None:
        if isinstance(item, str):
            matches.update(_WINDOWS_PATH_RE.findall(item))
            matches.update(_UNC_PATH_RE.findall(item))
            matches.update(_POSIX_PATH_RE.findall(item))
        elif isinstance(item, Mapping):
            for key, nested in item.items():
                observe(key)
                observe(nested)
        elif isinstance(item, list | tuple | set):
            for nested in item:
                observe(nested)

    observe(value)
    return sorted(matches)


def _load_prompt_template(filename: str) -> str:
    prompt_ref = resources.files("pathlab_paper_agent") / "prompts" / filename
    return Path(str(prompt_ref)).read_text(encoding="utf-8")
