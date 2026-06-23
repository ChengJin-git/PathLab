"""Semantic Scholar API client for deterministic citation discovery."""

from __future__ import annotations

from typing import Optional

import httpx

from .models import CitationCandidate

_DEFAULT_FIELDS = ",".join(
    [
        "paperId",
        "title",
        "abstract",
        "authors",
        "year",
        "venue",
        "journal",
        "publicationTypes",
        "externalIds",
        "url",
        "citationCount",
    ]
)


class SemanticScholarClient:
    """Small sync client around the S2 Graph search endpoint.

    Tests can pass an `httpx.MockTransport`; production can provide an API key
    through the environment or PathLab settings in later milestones.
    """

    def __init__(
        self,
        *,
        base_url: str = "https://api.semanticscholar.org/graph/v1",
        api_key: Optional[str] = None,
        timeout: float = 20.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def search(self, query: str, *, limit: int = 10, cluster: Optional[str] = None) -> list[CitationCandidate]:
        response = self._client.get(
            f"{self.base_url}/paper/search",
            params={"query": query, "limit": limit, "fields": _DEFAULT_FIELDS},
            headers=self._headers(),
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("data") or []
        return [self._candidate_from_item(item, query=query, cluster=cluster) for item in items]

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {"x-api-key": self.api_key}

    @staticmethod
    def _candidate_from_item(
        item: dict,
        *,
        query: str,
        cluster: Optional[str],
    ) -> CitationCandidate:
        external = item.get("externalIds") or {}
        authors = tuple(
            str(author.get("name"))
            for author in (item.get("authors") or [])
            if isinstance(author, dict) and author.get("name")
        )
        journal = item.get("journal") if isinstance(item.get("journal"), dict) else {}
        publication_types = item.get("publicationTypes")
        publication_type = None
        if isinstance(publication_types, list) and publication_types:
            publication_type = str(publication_types[0])
        return CitationCandidate(
            title=str(item.get("title") or ""),
            source="semantic_scholar",
            abstract=item.get("abstract"),
            authors=authors,
            year=item.get("year"),
            venue=item.get("venue"),
            journal=journal.get("name") or item.get("venue"),
            volume=journal.get("volume"),
            pages=journal.get("pages"),
            publication_type=publication_type,
            doi=external.get("DOI"),
            pmid=external.get("PubMed"),
            s2_paper_id=item.get("paperId"),
            url=item.get("url"),
            citation_count=int(item.get("citationCount") or 0),
            query=query,
            cluster=cluster,
            raw=item,
        )
