"""Online literature search clients — provider abstraction for metadata discovery."""
from __future__ import annotations

import logging
from typing import Any, Protocol
from xml.etree import ElementTree as ET

import requests

from .types import PaperRecord
from .query_builder import build_literature_search_query

logger = logging.getLogger(__name__)


# Plan-2026-05-16: PubMed-friendly query builder. PubMed's esearch matches
# MeSH-indexed terms with explicit boolean operators; the pipeline-wide
# alias-expanded query (e.g. "TCGA-LUNG TCGA lung cancer cancer subtype
# classification NSCLC histopathology") behaves like a bag of words and
# returns 0 hits. We extract a small focused set of biomedical phrases
# plus an organ guard and a methodology guard, joined with OR/AND.
_ORGAN_MESH_PHRASES: dict[str, list[str]] = {
    "lung":       ['"lung neoplasms"[MeSH]', '"NSCLC"', '"non-small cell lung cancer"', '"lung cancer"'],
    "breast":     ['"breast neoplasms"[MeSH]', '"breast cancer"'],
    "prostate":   ['"prostatic neoplasms"[MeSH]', '"prostate cancer"'],
    "colorectal": ['"colorectal neoplasms"[MeSH]', '"colorectal cancer"', '"CRC"'],
    "colon":      ['"colonic neoplasms"[MeSH]', '"colon cancer"'],
    "rectal":     ['"rectal neoplasms"[MeSH]', '"rectal cancer"'],
    "kidney":     ['"kidney neoplasms"[MeSH]', '"renal cancer"'],
    "stomach":    ['"stomach neoplasms"[MeSH]', '"gastric cancer"', '"chronic gastritis"'],
    "gastric":    ['"stomach neoplasms"[MeSH]', '"gastric cancer"', '"chronic gastritis"'],
    "uterus":     ['"uterine neoplasms"[MeSH]', '"endometrial cancer"'],
    "lymph_node": ['"lymph nodes"[MeSH]', '"sentinel lymph node"', '"lymph node metastasis"'],
}
_METHOD_PHRASES: dict[str, list[str]] = {
    "classification":     ['"deep learning"', 'histopathology', 'pathology'],
    "segmentation":       ['"deep learning"', '"semantic segmentation"', 'histopathology'],
    "survival":           ['"deep learning"', '"survival analysis"', 'histopathology'],
    "feature_extraction": ['"foundation model"', '"representation learning"', 'histopathology'],
}
_DATASET_HINT_TOKENS: list[str] = [
    "TCGA", "CAMELYON", "PANDA", "BRACS", "NSCLC", "LUAD", "LUSC",
    "MSI", "HER2", "EGFR", "Gleason", "ISUP",
]


def _build_pubmed_query(
    query: str,
    *,
    organ: str | None = None,
    task_type: str | None = None,
) -> str:
    """Compose a focused MeSH-friendly query for PubMed esearch.

    Strategy: ``(organ_group) AND (method_group) AND (extra_tokens)?``
    where each group is an OR of curated phrases. Extra tokens come from
    salient biomedical terms (NSCLC, TCGA, etc.) found in the input
    query. Falls back to the raw ``query`` if no organ + task signal.
    """
    query_low = (query or "").lower()
    organ_low = (organ or "").strip().lower()
    task_low = (task_type or "").strip().lower()

    parts: list[str] = []

    organ_terms = _ORGAN_MESH_PHRASES.get(organ_low, [])
    if organ_terms:
        parts.append("(" + " OR ".join(organ_terms) + ")")

    method_terms = _METHOD_PHRASES.get(task_low, _METHOD_PHRASES.get("classification", []))
    if method_terms:
        parts.append("(" + " OR ".join(method_terms) + ")")

    # Pull salient dataset / target tokens from the input query if present.
    salient = [tok for tok in _DATASET_HINT_TOKENS if tok.lower() in query_low]
    if salient:
        parts.append("(" + " OR ".join(f'"{t}"' for t in salient) + ")")

    if not parts:
        # No structured signals to lean on; fall back to the raw query
        # so PubMed at least gets *something* to match against.
        return (query or "").strip()
    return " AND ".join(parts)


class OnlineLiteratureClient(Protocol):
    """Protocol for online literature search providers."""

    def search(
        self,
        query: str,
        organ: str | None = None,
        task_type: str | None = None,
        top_k: int = 10,
        venue: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        min_citations: int | None = None,
    ) -> list[PaperRecord]: ...


class OpenAlexClient:
    """OpenAlex API client — returns PaperRecord objects from works search.

    API docs: https://docs.openalex.org/api-entities/works
    No API key required for polite usage (include mailto in User-Agent).

    Supports filtering by venue, year range, and minimum citation count.
    """

    # Plan-2026-04-29 literature-acquisition Phase 2 / Task 3:
    # canonical provider name used by ``PaperCache`` keys + status
    # reporting. Test fakes can declare their own to share cache slots
    # with the real client.
    provider_name = "openalex"

    BASE_URL = "https://api.openalex.org/works"
    SOURCES_URL = "https://api.openalex.org/sources"

    def __init__(
        self,
        timeout: int = 15,
        mailto: str = "autoresearch@pathlab.local",
        raise_on_error: bool = False,
    ):
        self._timeout = timeout
        self._mailto = mailto
        # Plan-2026-04-29 literature-acquisition Phase 1 / Task 4 wires
        # ``raise_on_error`` to actually re-raise; Task 3 just accepts the
        # kwarg so the factory can forward it without crashing.
        self._raise_on_error = raise_on_error
        self.last_error = ""
        self.last_query = ""
        self._venue_cache: dict[str, str] = {}  # venue name → source ID

    def search(
        self,
        query: str,
        organ: str | None = None,
        task_type: str | None = None,
        top_k: int = 10,
        venue: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        min_citations: int | None = None,
    ) -> list[PaperRecord]:
        """Search OpenAlex for papers matching a query with optional filters."""
        search_query = build_literature_search_query(
            query,
            organ=organ,
            task_type=task_type,
        )
        self.last_query = search_query
        if not search_query.strip():
            return []

        params: dict[str, Any] = {
            "search": search_query,
            "per-page": min(top_k, 25),
            "mailto": self._mailto,
        }

        # Build filter string
        filters = _build_filters(
            venue_source_id=self._resolve_venue(venue) if venue else None,
            year_min=year_min,
            year_max=year_max,
            min_citations=min_citations,
        )
        if filters:
            params["filter"] = filters

        try:
            resp = requests.get(
                self.BASE_URL,
                params=params,
                timeout=self._timeout,
                headers={"User-Agent": f"AutoResearch/1.0 (mailto:{self._mailto})"},
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            # Plan-2026-04-29 literature-acquisition Phase 1 / Task 4:
            # record + re-raise when raise_on_error=True so fail-hard
            # policy can abort the session instead of silently degrading.
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            logger.warning(f"OpenAlex search failed: {self.last_error}")
            if self._raise_on_error:
                raise
            return []

        papers: list[PaperRecord] = []
        for work in data.get("results", [])[:top_k]:
            try:
                paper = _normalize_openalex_work(work)
                papers.append(paper)
            except Exception as e:
                logger.debug(f"Skipping malformed OpenAlex work: {e}")
                continue

        return papers

    def _resolve_venue(self, venue_name: str) -> str | None:
        """Resolve a venue display name to an OpenAlex source ID.

        Caches results to avoid repeated API calls.
        """
        if not venue_name:
            return None

        key = venue_name.strip().lower()
        if key in self._venue_cache:
            return self._venue_cache[key]

        try:
            resp = requests.get(
                self.SOURCES_URL,
                params={"search": venue_name, "per-page": 1, "mailto": self._mailto},
                timeout=self._timeout,
                headers={"User-Agent": f"AutoResearch/1.0 (mailto:{self._mailto})"},
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if results:
                source_id = results[0]["id"].split("/")[-1]  # e.g. "S137773608"
                self._venue_cache[key] = source_id
                logger.info(f"Resolved venue '{venue_name}' → {source_id} ({results[0].get('display_name')})")
                return source_id
        except Exception as e:
            logger.warning(f"Venue resolution failed for '{venue_name}': {e}")

        self._venue_cache[key] = ""
        return None


class EuropePMCClient:
    """Europe PMC search client for biomedical/pathology metadata."""

    provider_name = "europepmc"
    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, timeout: int = 15, raise_on_error: bool = False):
        self._timeout = timeout
        self._raise_on_error = raise_on_error
        self.last_error = ""
        self.last_query = ""

    def search(
        self,
        query: str,
        organ: str | None = None,
        task_type: str | None = None,
        top_k: int = 10,
        venue: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        min_citations: int | None = None,
    ) -> list[PaperRecord]:
        search_query = build_literature_search_query(
            query,
            organ=organ,
            task_type=task_type,
        )
        self.last_query = search_query
        if not search_query.strip():
            return []
        params = {
            "query": search_query,
            "format": "json",
            "pageSize": min(top_k, 25),
        }
        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            logger.warning("Europe PMC search failed: %s", self.last_error)
            if self._raise_on_error:
                raise
            return []

        papers: list[PaperRecord] = []
        results = ((data.get("resultList") or {}).get("result") or [])
        for item in results[:top_k]:
            try:
                paper = _normalize_europepmc_work(item)
                if _matches_light_filters(
                    paper,
                    venue=venue,
                    year_min=year_min,
                    year_max=year_max,
                    min_citations=min_citations,
                ):
                    papers.append(paper)
            except Exception as e:
                logger.debug("Skipping malformed Europe PMC work: %s", e)
        return papers


class SemanticScholarClient:
    """Semantic Scholar Graph API client for academic metadata.

    Plan-2026-05-16: reads ``SEMANTIC_SCHOLAR_API_KEY`` /
    ``S2_API_KEY`` env vars. The Graph API rate-limits unauthenticated
    requests aggressively (effectively ~1 req / 3-5 seconds; bursty
    grounding calls hit 429 immediately). With an API key the limit
    rises to 1 req/s and 429 becomes rare; without one we still respect
    ``Retry-After`` on 429 so the upstream retry layer doesn't burn
    attempts uselessly.
    """

    provider_name = "semantic_scholar"
    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(self, timeout: int = 15, raise_on_error: bool = False):
        import os as _os
        self._timeout = timeout
        self._raise_on_error = raise_on_error
        self._api_key = (
            _os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
            or _os.environ.get("S2_API_KEY")
            or ""
        ).strip()
        self.last_error = ""
        self.last_query = ""

    def search(
        self,
        query: str,
        organ: str | None = None,
        task_type: str | None = None,
        top_k: int = 10,
        venue: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        min_citations: int | None = None,
    ) -> list[PaperRecord]:
        search_query = build_literature_search_query(
            query,
            organ=organ,
            task_type=task_type,
        )
        self.last_query = search_query
        if not search_query.strip():
            return []
        params = {
            "query": search_query,
            "limit": min(top_k, 25),
            "fields": "paperId,title,year,abstract,venue,url,authors,externalIds",
        }
        headers = {"x-api-key": self._api_key} if self._api_key else {}
        try:
            resp = requests.get(
                self.BASE_URL, params=params, headers=headers,
                timeout=self._timeout,
            )
            # Plan-2026-05-16: respect 429 Retry-After when present so
            # retriever's retry layer doesn't burn attempts immediately.
            # ``getattr`` tolerates test doubles that only stub ``.json``
            # and ``.raise_for_status`` without ``.status_code``.
            if getattr(resp, "status_code", 0) == 429:
                retry_after = resp.headers.get("Retry-After", "")
                try:
                    sleep_for = float(retry_after) if retry_after else 2.0
                except ValueError:
                    sleep_for = 2.0
                sleep_for = min(sleep_for, 5.0)  # cap so we don't blow timeout
                logger.info(
                    "Semantic Scholar 429; sleeping %.1fs before failure",
                    sleep_for,
                )
                import time as _t
                _t.sleep(sleep_for)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            logger.warning("Semantic Scholar search failed: %s", self.last_error)
            if self._raise_on_error:
                raise
            return []

        papers: list[PaperRecord] = []
        for item in data.get("data", [])[:top_k]:
            try:
                paper = _normalize_semantic_scholar_work(item)
                if _matches_light_filters(
                    paper,
                    venue=venue,
                    year_min=year_min,
                    year_max=year_max,
                    min_citations=min_citations,
                ):
                    papers.append(paper)
            except Exception as e:
                logger.debug("Skipping malformed Semantic Scholar work: %s", e)
        return papers


class PubMedClient:
    """PubMed E-utilities client for biomedical metadata.

    Plan-2026-05-16: PubMed's ``esearch`` matches against MeSH-indexed
    terms with boolean operators. The pipeline-wide
    ``build_literature_search_query`` produces an 11-token bag-of-words
    query that doesn't match MeSH-style indexing (returns 0 hits for
    "TCGA-LUNG TCGA lung cancer cancer subtype classification ..."). We
    build a focused query here from the structured signals (organ +
    task) so PubMed contributes meaningfully alongside the other
    providers.
    """

    provider_name = "pubmed"
    ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    def __init__(self, timeout: int = 15, raise_on_error: bool = False):
        self._timeout = timeout
        self._raise_on_error = raise_on_error
        self.last_error = ""
        self.last_query = ""

    def search(
        self,
        query: str,
        organ: str | None = None,
        task_type: str | None = None,
        top_k: int = 10,
        venue: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        min_citations: int | None = None,
    ) -> list[PaperRecord]:
        # Plan-2026-05-16: build a focused PubMed query rather than
        # reusing the long alias-expanded one. The long query returns 0
        # hits because PubMed needs short keywords + boolean operators
        # that match MeSH terms.
        search_query = _build_pubmed_query(query, organ=organ, task_type=task_type)
        self.last_query = search_query
        if not search_query.strip():
            return []

        try:
            search_resp = requests.get(
                self.ESEARCH_URL,
                params={
                    "db": "pubmed",
                    "term": search_query,
                    "retmode": "json",
                    "retmax": min(top_k, 25),
                },
                timeout=self._timeout,
            )
            search_resp.raise_for_status()
            ids = ((search_resp.json().get("esearchresult") or {}).get("idlist") or [])
            if not ids:
                return []
            fetch_resp = requests.get(
                self.EFETCH_URL,
                params={
                    "db": "pubmed",
                    "id": ",".join(str(item) for item in ids[:top_k]),
                    "retmode": "xml",
                },
                timeout=self._timeout,
            )
            fetch_resp.raise_for_status()
            root = ET.fromstring(fetch_resp.text or "")
        except (requests.RequestException, ET.ParseError) as e:
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            logger.warning("PubMed search failed: %s", self.last_error)
            if self._raise_on_error:
                raise
            return []

        papers: list[PaperRecord] = []
        for article in root.findall(".//PubmedArticle")[:top_k]:
            try:
                paper = _normalize_pubmed_article(article)
                if _matches_light_filters(
                    paper,
                    venue=venue,
                    year_min=year_min,
                    year_max=year_max,
                    min_citations=min_citations,
                ):
                    papers.append(paper)
            except Exception as e:
                logger.debug("Skipping malformed PubMed article: %s", e)
        return papers


def _normalize_europepmc_work(item: dict[str, Any]) -> PaperRecord:
    source = str(item.get("source") or "europepmc")
    work_id = str(item.get("id") or item.get("pmid") or item.get("pmcid") or "")
    title = str(item.get("title") or "")
    doi = str(item.get("doi") or "").strip()
    author_string = str(item.get("authorString") or "")
    authors = [
        part.strip()
        for part in author_string.replace(";", ",").split(",")
        if part.strip()
    ][:10]
    return PaperRecord(
        paper_id=f"europepmc:{source}:{work_id}" if work_id else f"europepmc:{title[:64]}",
        title=title,
        authors=authors,
        year=_safe_int(item.get("pubYear") or item.get("year")),
        abstract=str(item.get("abstractText") or ""),
        venue=str(item.get("journalTitle") or ""),
        source="europepmc",
        url=_doi_url(doi) or str(item.get("fullTextUrlList", {}).get("fullTextUrl", "") or ""),
        tags=[],
        aliases=[alias for alias in [doi, str(item.get("pmid") or ""), str(item.get("pmcid") or "")] if alias],
    )


def _normalize_semantic_scholar_work(item: dict[str, Any]) -> PaperRecord:
    paper_id = str(item.get("paperId") or "")
    external = item.get("externalIds") if isinstance(item.get("externalIds"), dict) else {}
    doi = str(external.get("DOI") or "").strip()
    authors = [
        str(author.get("name") or "")
        for author in item.get("authors", [])[:10]
        if isinstance(author, dict) and author.get("name")
    ]
    return PaperRecord(
        paper_id=f"s2:{paper_id}" if paper_id else f"s2:{str(item.get('title') or '')[:64]}",
        title=str(item.get("title") or ""),
        authors=authors,
        year=_safe_int(item.get("year")),
        abstract=str(item.get("abstract") or ""),
        venue=str(item.get("venue") or ""),
        source="semantic_scholar",
        url=_doi_url(doi) or str(item.get("url") or ""),
        tags=[],
        aliases=[alias for alias in [doi, paper_id, str(external.get("CorpusId") or "")] if alias],
    )


def _normalize_pubmed_article(article: ET.Element) -> PaperRecord:
    pmid = _xml_text(article.find(".//MedlineCitation/PMID"))
    article_node = article.find(".//MedlineCitation/Article")
    title = _xml_text(article_node.find("ArticleTitle") if article_node is not None else None)
    abstract_parts = [
        _xml_text(item)
        for item in article.findall(".//MedlineCitation/Article/Abstract/AbstractText")
    ]
    abstract = " ".join(part for part in abstract_parts if part)
    venue = _xml_text(article.find(".//MedlineCitation/Article/Journal/Title"))
    year = _safe_int(
        _xml_text(article.find(".//MedlineCitation/Article/Journal/JournalIssue/PubDate/Year"))
        or _xml_text(article.find(".//MedlineCitation/Article/ArticleDate/Year"))
    )
    authors = []
    for author in article.findall(".//MedlineCitation/Article/AuthorList/Author")[:10]:
        collective = _xml_text(author.find("CollectiveName"))
        if collective:
            authors.append(collective)
            continue
        fore = _xml_text(author.find("ForeName"))
        last = _xml_text(author.find("LastName"))
        name = " ".join(part for part in [fore, last] if part).strip()
        if name:
            authors.append(name)
    doi = ""
    for item in article.findall(".//MedlineCitation/Article/ELocationID"):
        if (item.attrib.get("EIdType") or "").lower() == "doi":
            doi = _xml_text(item)
            break
    if not doi:
        for item in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
            if (item.attrib.get("IdType") or "").lower() == "doi":
                doi = _xml_text(item)
                break
    return PaperRecord(
        paper_id=f"pubmed:{pmid}" if pmid else f"pubmed:{title[:64]}",
        title=title,
        authors=authors,
        year=year,
        abstract=abstract,
        venue=venue,
        source="pubmed",
        url=_doi_url(doi) or (f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""),
        tags=[],
        aliases=[alias for alias in [pmid, doi] if alias],
    )


def _xml_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _doi_url(value: str) -> str:
    doi = str(value or "").strip()
    if not doi:
        return ""
    if doi.startswith("http://") or doi.startswith("https://"):
        return doi
    return f"https://doi.org/{doi}"


def _matches_light_filters(
    paper: PaperRecord,
    *,
    venue: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    min_citations: int | None = None,
) -> bool:
    """Apply filters that non-OpenAlex providers do not expose uniformly."""
    if venue and venue.lower() not in (paper.venue or "").lower():
        return False
    if year_min and paper.year and paper.year < year_min:
        return False
    if year_max and paper.year and paper.year > year_max:
        return False
    # Citation counts are not present in our normalized records for these
    # providers; leave that filter to OpenAlex instead of dropping everything.
    return True


def _build_filters(
    venue_source_id: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    min_citations: int | None = None,
) -> str:
    """Build an OpenAlex filter string from optional criteria."""
    parts: list[str] = []
    if venue_source_id:
        parts.append(f"primary_location.source.id:{venue_source_id}")
    if year_min and year_max:
        parts.append(f"publication_year:{year_min}-{year_max}")
    elif year_min:
        parts.append(f"publication_year:>{year_min - 1}")
    elif year_max:
        parts.append(f"publication_year:<{year_max + 1}")
    if min_citations is not None and min_citations > 0:
        parts.append(f"cited_by_count:>{min_citations - 1}")
    return ",".join(parts)


def _normalize_openalex_work(work: dict[str, Any]) -> PaperRecord:
    """Convert an OpenAlex work object into a PaperRecord."""
    work_id = work.get("id", "").split("/")[-1]  # extract W-id from URL
    title = work.get("title", "") or ""

    # Authors
    authors = []
    for authorship in work.get("authorships", [])[:10]:
        name = authorship.get("author", {}).get("display_name", "")
        if name:
            authors.append(name)

    # Year
    year = work.get("publication_year", 0) or 0

    # Abstract from inverted index
    abstract = ""
    abstract_idx = work.get("abstract_inverted_index")
    if abstract_idx:
        abstract = _decode_abstract_inverted_index(abstract_idx)

    # Venue
    venue = ""
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    venue = source.get("display_name", "") or ""

    # URL — prefer DOI, then OpenAlex landing page
    doi = work.get("doi", "") or ""
    url = doi if doi else work.get("id", "")

    # Concepts as tags (top 3 by score)
    tags = []
    for concept in sorted(work.get("concepts", []), key=lambda c: c.get("score", 0), reverse=True)[:3]:
        tag = concept.get("display_name", "")
        if tag:
            tags.append(tag)

    return PaperRecord(
        paper_id=f"openalex:{work_id}",
        title=title,
        authors=authors,
        year=year,
        abstract=abstract,
        venue=venue,
        source="openalex",
        url=url,
        methods=[],
        datasets=[],
        baselines=[],
        organ="",
        task_type="",
        tags=tags,
    )


def _decode_abstract_inverted_index(idx: dict[str, list[int]]) -> str:
    """Reconstruct abstract text from OpenAlex abstract_inverted_index.

    The index maps each word to a list of positions where it appears.
    """
    if not idx:
        return ""

    # Build (position, word) pairs
    pairs: list[tuple[int, str]] = []
    for word, positions in idx.items():
        for pos in positions:
            pairs.append((pos, word))

    # Sort by position and join
    pairs.sort(key=lambda p: p[0])
    return " ".join(word for _, word in pairs)


def create_online_client(
    provider: str = "openalex",
    timeout: int = 15,
    raise_on_error: bool = False,
) -> OnlineLiteratureClient:
    """Factory: create an online literature client by provider name.

    Plan-2026-04-29 literature-acquisition Phase 1 / Task 3+4:
    ``raise_on_error`` is forwarded to the client (Task 4 wires
    OpenAlexClient to honor it). ``False`` keeps the historical
    "swallow + log" behavior; ``True`` re-raises so fail-hard policy
    runs can abort.
    """
    normalized = provider.strip().lower().replace("-", "_")
    if normalized == "openalex":
        return OpenAlexClient(timeout=timeout, raise_on_error=raise_on_error)
    if normalized in {"europepmc", "europe_pmc"}:
        return EuropePMCClient(timeout=timeout, raise_on_error=raise_on_error)
    if normalized in {"semantic_scholar", "semanticscholar", "s2"}:
        return SemanticScholarClient(timeout=timeout, raise_on_error=raise_on_error)
    if normalized in {"pubmed", "pub_med"}:
        return PubMedClient(timeout=timeout, raise_on_error=raise_on_error)
    raise ValueError(f"Unknown online literature provider: {provider}")


# Plan-2026-04-29 literature-acquisition Phase 1 / Task 3: session-scoped
# singleton cache. Pre-fix, runner.py constructed two OpenAlex clients per
# session — one for paper search, one inside ``_build_sota_lookup`` for the
# BenchmarkExtractor. Now we cache by (session_id, provider, timeout,
# raise_on_error) so consumers with matching settings share state.
_session_clients: dict[tuple[str, str, int, bool], OnlineLiteratureClient] = {}


def get_or_create_online_client(
    provider: str = "openalex",
    *,
    timeout: int = 15,
    session_id: str = "",
    raise_on_error: bool = False,
) -> OnlineLiteratureClient:
    """Return a session-scoped online literature client.

    Key includes settings that change behavior (timeout, raise_on_error)
    so a strict fail-hard caller never accidentally reuses a graceful-
    degradation instance.
    """
    provider_key = provider.strip().lower().replace("-", "_")
    key = (session_id or "global", provider_key, int(timeout), bool(raise_on_error))
    if key not in _session_clients:
        _session_clients[key] = create_online_client(
            provider=provider_key,
            timeout=timeout,
            raise_on_error=raise_on_error,
        )
    return _session_clients[key]


def reset_session_clients(session_id: str = "") -> None:
    """Drop cached clients. ``session_id=""`` clears everything; otherwise
    only clears entries for the named session.

    Tests + session teardown call this.
    """
    if not session_id:
        _session_clients.clear()
        return
    for key in list(_session_clients):
        if key[0] == session_id:
            del _session_clients[key]
