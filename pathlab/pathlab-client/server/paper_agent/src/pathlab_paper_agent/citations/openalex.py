"""OpenAlex API client for deterministic citation discovery."""

from __future__ import annotations

import re
from typing import Any, Optional

import httpx

from .models import CitationCandidate

_DEFAULT_SELECT_FIELDS = ",".join(
    [
        "id",
        "doi",
        "display_name",
        "publication_year",
        "authorships",
        "primary_location",
        "locations",
        "ids",
        "cited_by_count",
        "abstract_inverted_index",
    ]
)
_DOI_PREFIX_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)
_PMID_RE = re.compile(r"(\d+)(?:/)?$")


class OpenAlexClient:
    """Small sync client around the OpenAlex works search endpoint."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.openalex.org",
        api_key: Optional[str] = None,
        mailto: Optional[str] = None,
        timeout: float = 20.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.mailto = mailto
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def search(self, query: str, *, limit: int = 10, cluster: Optional[str] = None) -> list[CitationCandidate]:
        response = self._client.get(
            f"{self.base_url}/works",
            params={
                **self._auth_params(),
                "search": query,
                "per_page": limit,
                "select": _DEFAULT_SELECT_FIELDS,
            },
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("results") or []
        return [self._candidate_from_item(item, query=query, cluster=cluster) for item in items]

    def _auth_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.mailto:
            params["mailto"] = self.mailto
        return params

    @staticmethod
    def _candidate_from_item(
        item: dict[str, Any],
        *,
        query: str,
        cluster: Optional[str],
    ) -> CitationCandidate:
        ids = item.get("ids") if isinstance(item.get("ids"), dict) else {}
        doi = _normalize_doi(item.get("doi") or ids.get("doi"))
        pmid = _normalize_pmid(ids.get("pmid"))
        openalex_id = str(item.get("id") or ids.get("openalex") or "").strip() or None
        return CitationCandidate(
            title=str(item.get("display_name") or ""),
            source="openalex",
            abstract=_abstract_from_inverted_index(item.get("abstract_inverted_index")),
            authors=_authors_from_authorships(item.get("authorships")),
            year=_safe_int(item.get("publication_year")),
            venue=_venue_from_locations(item),
            doi=doi,
            pmid=pmid,
            openalex_id=openalex_id,
            url=_url_from_item(item, doi=doi, openalex_id=openalex_id),
            citation_count=_safe_int(item.get("cited_by_count")) or 0,
            query=query,
            cluster=cluster,
            raw=item,
        )


def _authors_from_authorships(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    authors: list[str] = []
    for authorship in value:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if isinstance(author, dict) and author.get("display_name"):
            authors.append(str(author["display_name"]))
    return tuple(authors)


def _venue_from_locations(item: dict[str, Any]) -> str | None:
    primary = item.get("primary_location")
    venue = _source_name_from_location(primary)
    if venue:
        return venue
    locations = item.get("locations")
    if not isinstance(locations, list):
        return None
    for location in locations:
        venue = _source_name_from_location(location)
        if venue:
            return venue
    return None


def _source_name_from_location(location: Any) -> str | None:
    if not isinstance(location, dict):
        return None
    source = location.get("source")
    if isinstance(source, dict) and source.get("display_name"):
        return str(source["display_name"])
    return None


def _url_from_item(item: dict[str, Any], *, doi: str | None, openalex_id: str | None) -> str | None:
    primary = item.get("primary_location")
    if isinstance(primary, dict) and primary.get("landing_page_url"):
        return str(primary["landing_page_url"])
    if doi:
        return f"https://doi.org/{doi}"
    return openalex_id


def _abstract_from_inverted_index(value: Any) -> str | None:
    if not isinstance(value, dict) or not value:
        return None
    positions: list[tuple[int, str]] = []
    for word, raw_indexes in value.items():
        if not isinstance(raw_indexes, list):
            continue
        for raw_index in raw_indexes:
            index = _safe_int(raw_index)
            if index is not None:
                positions.append((index, str(word)))
    if not positions:
        return None
    return " ".join(word for _index, word in sorted(positions))


def _normalize_doi(value: Any) -> str | None:
    if not value:
        return None
    doi = _DOI_PREFIX_RE.sub("", str(value).strip())
    return doi or None


def _normalize_pmid(value: Any) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    match = _PMID_RE.search(raw)
    return match.group(1) if match else raw or None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
