"""Online literature search clients — provider abstraction for metadata discovery."""
from __future__ import annotations

import logging
from typing import Any, Protocol

import requests

from .types import PaperRecord

logger = logging.getLogger(__name__)


class OnlineLiteratureClient(Protocol):
    """Protocol for online literature search providers."""

    def search(
        self,
        query: str,
        organ: str | None = None,
        task_type: str | None = None,
        top_k: int = 10,
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
        mailto: str = "pathscientist@pathlab.local",
        raise_on_error: bool = False,
    ):
        self._timeout = timeout
        self._mailto = mailto
        # Plan-2026-04-29 literature-acquisition Phase 1 / Task 4 wires
        # ``raise_on_error`` to actually re-raise; Task 3 just accepts the
        # kwarg so the factory can forward it without crashing.
        self._raise_on_error = raise_on_error
        self.last_error = ""
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
        if not query.strip():
            return []

        params: dict[str, Any] = {
            "search": query,
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
                headers={"User-Agent": f"PathScientist/1.0 (mailto:{self._mailto})"},
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
                headers={"User-Agent": f"PathScientist/1.0 (mailto:{self._mailto})"},
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
    if provider == "openalex":
        return OpenAlexClient(timeout=timeout, raise_on_error=raise_on_error)
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
    key = (session_id or "global", provider, int(timeout), bool(raise_on_error))
    if key not in _session_clients:
        _session_clients[key] = create_online_client(
            provider=provider,
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
