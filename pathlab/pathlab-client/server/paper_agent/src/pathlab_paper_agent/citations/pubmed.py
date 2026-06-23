"""PubMed E-utilities client for deterministic citation discovery."""

from __future__ import annotations

from typing import Optional

import httpx

from .models import CitationCandidate


class PubMedClient:
    """Small sync client using NCBI ESearch + ESummary.

    Abstract retrieval is intentionally left for M8b/M9 if needed; M8a only
    needs verified metadata and stable IDs for BibTeX generation.
    """

    def __init__(
        self,
        *,
        base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        api_key: Optional[str] = None,
        tool: str = "pathlab-paper-agent",
        email: Optional[str] = None,
        timeout: float = 20.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.tool = tool
        self.email = email
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def search(self, query: str, *, limit: int = 10, cluster: Optional[str] = None) -> list[CitationCandidate]:
        search_response = self._client.get(
            f"{self.base_url}/esearch.fcgi",
            params={**self._common_params(), "db": "pubmed", "term": query, "retmax": limit},
        )
        search_response.raise_for_status()
        ids = (search_response.json().get("esearchresult") or {}).get("idlist") or []
        if not ids:
            return []

        summary_response = self._client.get(
            f"{self.base_url}/esummary.fcgi",
            params={**self._common_params(), "db": "pubmed", "id": ",".join(ids)},
        )
        summary_response.raise_for_status()
        result = summary_response.json().get("result") or {}
        return [
            self._candidate_from_summary(result[pmid], query=query, cluster=cluster)
            for pmid in ids
            if isinstance(result.get(pmid), dict)
        ]

    def _common_params(self) -> dict[str, str]:
        params = {"retmode": "json", "tool": self.tool}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.email:
            params["email"] = self.email
        return params

    @staticmethod
    def _candidate_from_summary(
        item: dict,
        *,
        query: str,
        cluster: Optional[str],
    ) -> CitationCandidate:
        authors = tuple(
            str(author.get("name"))
            for author in (item.get("authors") or [])
            if isinstance(author, dict) and author.get("name")
        )
        article_ids = item.get("articleids") or []
        doi = None
        for article_id in article_ids:
            if isinstance(article_id, dict) and article_id.get("idtype") == "doi":
                doi = article_id.get("value")
                break
        year = None
        pubdate = str(item.get("pubdate") or "")
        if len(pubdate) >= 4 and pubdate[:4].isdigit():
            year = int(pubdate[:4])
        pmid = str(item.get("uid") or "")
        return CitationCandidate(
            title=str(item.get("title") or ""),
            source="pubmed",
            authors=authors,
            year=year,
            venue=item.get("fulljournalname") or item.get("source"),
            journal=item.get("fulljournalname") or item.get("source"),
            volume=str(item["volume"]) if item.get("volume") else None,
            number=str(item["issue"]) if item.get("issue") else None,
            pages=item.get("pages"),
            publication_type=_publication_type(item.get("pubtype")),
            doi=doi,
            pmid=pmid or None,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
            query=query,
            cluster=cluster,
            raw=item,
        )


def _publication_type(value: object) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    if value:
        return str(value)
    return None
