"""HTML full-text fetcher with table + section extraction.

FT-T3 of docs/plans/2026-05-01-autoresearch-fulltext-sota-extraction-plan.md.

A new fetch path that sits between ``LiteratureRetriever`` (which produces
``oa_url`` / ``pdf_url`` pointers) and ``BenchmarkExtractor`` (which feeds
chunks to an LLM). Three reasons it lives here:

1. **Publisher allowlist.** We only scrape sites with broad open-access
   policies (arxiv, biorxiv, medrxiv, PMC/NCBI, openreview, OA Nature/Cell).
   Anything else fails soft so the rest of the pipeline isn't blocked.
2. **HTML-only.** PDFs need GROBID/papermage and have ~50-70% table recall.
   Defer to a follow-up plan if HTML coverage proves inadequate.
3. **Tables matter.** Many pathology benchmark numbers live in
   ``<table>`` elements, not the abstract. We render each table as
   markdown so the LLM extractor can read row/column headers.

The fetcher is pure HTTP + parse — ``NetworkPolicy`` gating happens at the
runner-side wiring; the fetcher itself is policy-agnostic so unit tests
don't need a network stub.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .fulltext_cache import FulltextCache
from .fulltext_types import FulltextChunk, FulltextDoc

logger = logging.getLogger(__name__)


DEFAULT_PUBLISHER_ALLOWLIST: frozenset[str] = frozenset({
    "arxiv.org",
    "www.biorxiv.org", "biorxiv.org",
    "www.medrxiv.org", "medrxiv.org",
    "www.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",   # PMC
    "www.nature.com", "nature.com",                # OA subset
    "openreview.net",
    "www.cell.com", "cell.com",                    # OA subset
    "pmc.ncbi.nlm.nih.gov",                        # newer PMC subdomain
})


_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MIN_SECTION_CHARS = 50
_MAX_SLUG_CHARS = 40


def _slugify(value: str) -> str:
    s = (value or "").strip().lower()
    s = _SLUG_RE.sub("_", s).strip("_")
    return s[:_MAX_SLUG_CHARS]


class FulltextFetcher:
    """Fetch HTML for a paper and break it into chunks.

    All side-effecting parts (HTTP session, cache, sleep) are injectable
    so tests don't need monkeypatching. ``rate_limit_seconds=0.0`` is
    standard for unit tests; the runner uses ~1.5 to be polite.
    """

    def __init__(
        self,
        *,
        cache: FulltextCache | None = None,
        session: Any | None = None,
        timeout: int = 30,
        user_agent: str = "AutoResearch/1.0 (+https://pathlab/contact)",
        publisher_allowlist: set[str] | frozenset[str] | None = None,
        max_chunks: int = 50,
        rate_limit_seconds: float = 1.5,
        chunk_store: Any | None = None,
        enable_rag_ingest: bool = True,
        clock=None,            # injectable for tests; defaults to time module
    ) -> None:
        self._cache = cache
        self._sess = session if session is not None else self._build_session()
        self._timeout = timeout
        self._ua = user_agent
        self._allowlist = (
            frozenset(s.lower() for s in publisher_allowlist)
            if publisher_allowlist is not None
            else DEFAULT_PUBLISHER_ALLOWLIST
        )
        self._max_chunks = max(1, int(max_chunks))
        self._rate_limit_seconds = float(rate_limit_seconds)
        self._last_request_at = 0.0
        self._chunk_store = chunk_store
        self._enable_rag_ingest = bool(enable_rag_ingest)
        self._clock = clock or time

    @staticmethod
    def _build_session():
        try:
            import requests
            return requests.Session()
        except Exception:  # pragma: no cover - requests is a hard dep
            return None

    # ---- public API -----------------------------------------------------

    def fetch(
        self,
        paper_id: str,
        oa_url: str,
        *,
        force_refresh: bool = False,
    ) -> FulltextDoc:
        if self._cache is not None and not force_refresh:
            cached = self._cache.get(paper_id)
            if cached is not None:
                return cached

        host = (urlparse(oa_url).netloc or "").lower()
        if host not in self._allowlist:
            doc = self._fail(paper_id, oa_url, f"publisher_not_allowed:{host}")
            self._maybe_cache(doc)
            return doc

        self._rate_limit_sleep()

        try:
            resp = self._sess.get(
                oa_url,
                timeout=self._timeout,
                headers={
                    "Accept": "text/html, */*; q=0.1",
                    "User-Agent": self._ua,
                },
            )
            resp.raise_for_status()
        except Exception as e:
            doc = self._fail(
                paper_id, oa_url,
                f"http_error:{type(e).__name__}:{e}",
            )
            self._maybe_cache(doc)
            return doc

        ctype = (
            (resp.headers.get("Content-Type") or "")
            if hasattr(resp, "headers") and resp.headers is not None
            else ""
        ).lower()
        if "text/html" not in ctype and "application/xhtml" not in ctype:
            doc = self._fail(
                paper_id, oa_url,
                f"unsupported_content_type:{ctype}",
            )
            self._maybe_cache(doc)
            return doc

        chunks = self._parse_html(
            resp.text or "", paper_id=paper_id, source_url=oa_url,
        )
        doc = FulltextDoc(
            paper_id=paper_id,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            fetch_url=oa_url,
            success=bool(chunks),
            error="" if chunks else "no_chunks_extracted",
            chunks=chunks[: self._max_chunks],
        )
        self._maybe_cache(doc)
        if doc.success and self._chunk_store is not None and self._enable_rag_ingest:
            self._push_to_chunk_store(doc)
        return doc

    # ---- internals ------------------------------------------------------

    def _fail(self, paper_id: str, url: str, error: str) -> FulltextDoc:
        return FulltextDoc(
            paper_id=paper_id,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            fetch_url=url,
            success=False,
            error=error,
            chunks=[],
        )

    def _maybe_cache(self, doc: FulltextDoc) -> None:
        if self._cache is None:
            return
        try:
            self._cache.put(doc)
        except Exception as e:
            logger.warning(
                "FulltextFetcher: cache.put failed for %s: %s",
                doc.paper_id, e,
            )

    def _rate_limit_sleep(self) -> None:
        if self._rate_limit_seconds <= 0:
            return
        now = self._clock.monotonic()
        elapsed = now - self._last_request_at
        wait = self._rate_limit_seconds - elapsed
        if wait > 0:
            self._clock.sleep(wait)
        self._last_request_at = self._clock.monotonic()

    def _push_to_chunk_store(self, doc: FulltextDoc) -> None:
        records = [
            {
                "paper_id": c.paper_id,
                "chunk_id": f"{c.paper_id}::{c.section}",
                "text": c.text,
                "section": c.section,
                "page": None,
            }
            for c in doc.chunks
        ]
        try:
            self._chunk_store.add_chunks(records)
        except Exception as e:
            logger.warning(
                "FulltextFetcher: chunk_store push failed for %s: %s",
                doc.paper_id, e,
            )

    # ---- parsing --------------------------------------------------------

    def _parse_html(
        self,
        html: str,
        *,
        paper_id: str,
        source_url: str,
    ) -> list[FulltextChunk]:
        try:
            from bs4 import BeautifulSoup
        except Exception as e:
            logger.warning("BeautifulSoup not available: %s", e)
            return []

        soup = BeautifulSoup(html, "html.parser")

        # Strip noise.
        for tag in soup(["script", "style", "nav", "aside", "footer"]):
            tag.decompose()

        chunks: list[FulltextChunk] = []
        seen_sections: set[str] = set()

        # --- Abstract --------------------------------------------------
        abstract_text = self._extract_abstract(soup)
        if abstract_text:
            chunks.append(FulltextChunk(
                paper_id=paper_id, section="abstract",
                text=abstract_text, source_url=source_url,
            ))
            seen_sections.add("abstract")

        # --- Tables ----------------------------------------------------
        for idx, table in enumerate(soup.find_all("table")):
            md = self._table_to_markdown(table)
            if not md:
                continue
            section = f"table_{idx}"
            if section in seen_sections:
                continue
            chunks.append(FulltextChunk(
                paper_id=paper_id, section=section, text=md,
                is_table=True, source_url=source_url,
            ))
            seen_sections.add(section)

        # --- Sections --------------------------------------------------
        for heading in soup.find_all(["h1", "h2", "h3"]):
            heading_text = (heading.get_text(" ", strip=True) or "")
            if not heading_text:
                continue
            slug = _slugify(heading_text)
            if not slug or slug == "abstract":
                continue
            section = f"section_{slug}"
            if section in seen_sections:
                continue
            body_parts: list[str] = []
            for sib in heading.next_siblings:
                if getattr(sib, "name", None) in {"h1", "h2", "h3"}:
                    break
                text = (
                    sib.get_text(" ", strip=True)
                    if hasattr(sib, "get_text")
                    else str(sib).strip()
                )
                if text:
                    body_parts.append(text)
            body = " ".join(body_parts).strip()
            if len(body) < _MIN_SECTION_CHARS:
                continue
            chunks.append(FulltextChunk(
                paper_id=paper_id, section=section, text=body,
                source_url=source_url,
            ))
            seen_sections.add(section)

        return chunks

    def _extract_abstract(self, soup) -> str:
        # Standard abstract containers.
        for selector in [
            ("section", {"class": re.compile(r"\babstract\b", re.I)}),
            ("div", {"class": re.compile(r"\babstract\b", re.I)}),
            ("section", {"id": re.compile(r"\babstract\b", re.I)}),
            ("div", {"id": re.compile(r"\babstract\b", re.I)}),
        ]:
            tag_name, attrs = selector
            node = soup.find(tag_name, attrs=attrs)
            if node:
                text = node.get_text(" ", strip=True)
                if text:
                    return text

        # Fallback: <h2>Abstract</h2> followed by <p>...</p>.
        for heading in soup.find_all(["h1", "h2", "h3"]):
            if (heading.get_text(strip=True) or "").lower().startswith("abstract"):
                parts: list[str] = []
                for sib in heading.next_siblings:
                    if getattr(sib, "name", None) in {"h1", "h2", "h3"}:
                        break
                    text = (
                        sib.get_text(" ", strip=True)
                        if hasattr(sib, "get_text")
                        else str(sib).strip()
                    )
                    if text:
                        parts.append(text)
                joined = " ".join(parts).strip()
                if joined:
                    return joined
        return ""

    def _table_to_markdown(self, table) -> str:
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [
                _cell_text(td)
                for td in tr.find_all(["th", "td"])
            ]
            cells = [c for c in cells if c is not None]
            if cells:
                rows.append(cells)

        if len(rows) < 2:
            return ""
        ncols = max(len(r) for r in rows)
        if ncols < 2:
            return ""

        # Pad short rows to the widest row.
        rows = [r + [""] * (ncols - len(r)) for r in rows]

        header = rows[0]
        body = rows[1:]
        out = []
        out.append("| " + " | ".join(header) + " |")
        out.append("| " + " | ".join(["---"] * ncols) + " |")
        for r in body:
            out.append("| " + " | ".join(r) + " |")
        return "\n".join(out)


def _cell_text(td) -> str:
    raw = td.get_text(" ", strip=True) or ""
    # Escape pipe so markdown row stays parseable.
    return raw.replace("|", "\\|")
