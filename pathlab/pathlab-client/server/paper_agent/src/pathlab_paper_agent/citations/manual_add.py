"""Manual citation ingestion for DOI, arXiv, BibTeX, and form fields."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import replace
from typing import Any
from urllib.parse import quote

import bibtexparser
import httpx

from pathlab_paper_agent.citations.models import CitationCandidate
from pathlab_paper_agent.schemas import AddCitationRequest

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_DOI_IN_TEXT_RE = re.compile(r"(10\.\d{4,9}/[^\s<>\"{}|\\^`]+)", re.IGNORECASE)
_ARXIV_RE = re.compile(
    r"(?:arxiv(?:\.org)?/(?:abs|pdf)/|arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)
_ENTRY_TYPES = {"article", "inproceedings", "misc"}


class ManualCitationError(Exception):
    """Structured error surfaced by the citations API."""

    def __init__(self, code: str, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def parse_input(req: AddCitationRequest) -> CitationCandidate:
    """Normalize one user-submitted citation payload into a candidate."""
    if req.mode == "doi":
        return _with_request_fields(fetch_doi_metadata(req.doi or ""), req)
    if req.mode == "arxiv":
        return _with_request_fields(fetch_arxiv_metadata(req.arxiv_id_or_url or ""), req)
    if req.mode == "bibtex":
        return _with_request_fields(parse_bibtex_string(req.bibtex_raw or ""), req)
    if req.mode == "manual":
        return _with_request_fields(_parse_manual(req), req)
    raise ManualCitationError("missing_required", f"Unsupported citation mode: {req.mode}")


def fetch_doi_metadata(doi: str) -> CitationCandidate:
    normalized = normalize_doi(doi)
    if not normalized:
        raise ManualCitationError("invalid_doi", "DOI must start with 10.<registrant>/...")
    try:
        with httpx.Client(follow_redirects=True, timeout=8.0) as client:
            try:
                response = client.get(
                    f"https://doi.org/{normalized}",
                    headers={"Accept": "application/x-bibtex"},
                )
                response.raise_for_status()
                candidate = parse_bibtex_string(response.text)
                return replace(
                    candidate,
                    source="doi",
                    doi=candidate.doi or normalized,
                    url=candidate.url or f"https://doi.org/{normalized}",
                )
            except (ManualCitationError, httpx.HTTPError):
                return _fetch_crossref_metadata(client, normalized)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise ManualCitationError(
            "fetch_failed",
            f"Failed to fetch DOI metadata for {normalized}.",
            status_code=502,
        ) from exc


def _fetch_crossref_metadata(client: httpx.Client, doi: str) -> CitationCandidate:
    response = client.get(f"https://api.crossref.org/works/{quote(doi, safe='')}")
    response.raise_for_status()
    message = response.json().get("message") or {}
    title = _first_text(message.get("title"))
    if not title:
        raise ValueError("Crossref response did not include a title.")
    journal = _first_text(message.get("container-title"))
    doi_value = normalize_doi(message.get("DOI") or doi) or doi
    return CitationCandidate(
        title=title,
        source="doi",
        authors=_crossref_authors(message.get("author")),
        year=_crossref_year(message),
        venue=journal,
        entry_type=_crossref_entry_type(message.get("type")),
        journal=journal,
        volume=_string_or_none(message.get("volume")),
        number=_string_or_none(message.get("issue")),
        pages=_string_or_none(message.get("page")),
        publisher=_string_or_none(message.get("publisher")),
        publication_type=_string_or_none(message.get("type")),
        doi=doi_value,
        url=_string_or_none(message.get("URL")) or f"https://doi.org/{doi_value}",
        raw={
            "crossref_type": message.get("type"),
            "crossref_member": message.get("member"),
        },
    )


def fetch_arxiv_metadata(id_or_url: str) -> CitationCandidate:
    arxiv_id = normalize_arxiv_id(id_or_url)
    if not arxiv_id:
        raise ManualCitationError("invalid_arxiv_id", "Could not parse an arXiv identifier.")
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.get(
                "http://export.arxiv.org/api/query",
                params={"id_list": arxiv_id},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ManualCitationError(
            "fetch_failed",
            f"Failed to fetch arXiv metadata for {arxiv_id}.",
            status_code=502,
        ) from exc
    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as exc:
        raise ManualCitationError(
            "fetch_failed",
            f"arXiv returned invalid metadata for {arxiv_id}.",
            status_code=502,
        ) from exc

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise ManualCitationError("invalid_arxiv_id", f"No arXiv entry found for {arxiv_id}.")
    title = _collapse_ws(_text(entry.find("atom:title", ns)))
    if not title:
        raise ManualCitationError("invalid_arxiv_id", f"No arXiv title found for {arxiv_id}.")
    authors = tuple(
        _collapse_ws(_text(author.find("atom:name", ns)))
        for author in entry.findall("atom:author", ns)
    )
    authors = tuple(author for author in authors if author)
    published = _text(entry.find("atom:published", ns))
    year = _parse_year(published[:4]) if published else None
    doi = _text(entry.find("arxiv:doi", ns)) or None
    link = f"https://arxiv.org/abs/{arxiv_id}"
    return CitationCandidate(
        title=title,
        source="arxiv",
        abstract=_collapse_ws(_text(entry.find("atom:summary", ns))) or None,
        authors=authors,
        year=year,
        venue="arXiv",
        entry_type="misc",
        arxiv_id=arxiv_id,
        doi=doi,
        url=link,
        publication_type="preprint",
        raw={"arxiv_id": arxiv_id},
    )


def parse_bibtex_string(raw: str) -> CitationCandidate:
    text = (raw or "").strip()
    if not text.startswith("@"):
        raise ManualCitationError("invalid_bibtex", "BibTeX must start with an entry.")
    try:
        database = bibtexparser.loads(text)
    except Exception as exc:  # bibtexparser raises a few parser-specific errors.
        raise ManualCitationError("invalid_bibtex", "Could not parse BibTeX input.") from exc
    entries = getattr(database, "entries", None) or []
    if not entries:
        raise ManualCitationError("invalid_bibtex", "No BibTeX entry found.")
    entry = entries[0]
    title = _strip_bibtex_value(entry.get("title") or "")
    if not title:
        raise ManualCitationError("invalid_bibtex", "BibTeX entry is missing a title.")
    entry_type = _normalize_entry_type(entry.get("ENTRYTYPE"))
    journal = _strip_bibtex_value(entry.get("journal") or "") or None
    booktitle = _strip_bibtex_value(entry.get("booktitle") or "") or None
    doi = normalize_doi(entry.get("doi") or entry.get("DOI") or "")
    arxiv_id = normalize_arxiv_id(
        entry.get("eprint") or entry.get("arxiv_id") or entry.get("url") or entry.get("doi") or ""
    )
    return CitationCandidate(
        title=title,
        source="bibtex",
        authors=_parse_authors(entry.get("author") or ""),
        year=_parse_year(entry.get("year")),
        venue=journal or booktitle or _strip_bibtex_value(entry.get("venue") or "") or None,
        entry_type=entry_type,
        journal=journal,
        booktitle=booktitle,
        volume=_string_or_none(entry.get("volume")),
        number=_string_or_none(entry.get("number")),
        pages=_strip_bibtex_value(entry.get("pages") or "") or None,
        publisher=_strip_bibtex_value(entry.get("publisher") or "") or None,
        arxiv_id=arxiv_id,
        publication_type=entry.get("ENTRYTYPE"),
        doi=doi,
        url=_strip_bibtex_value(entry.get("url") or "") or None,
        raw={"bibtex_key": entry.get("ID"), "entry_type": entry.get("ENTRYTYPE")},
    )


def normalize_doi(value: str) -> str | None:
    text = (value or "").strip()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    match = _DOI_IN_TEXT_RE.search(text)
    candidate = (match.group(1) if match else text).strip().rstrip(".,;")
    return candidate if _DOI_RE.match(candidate) else None


def normalize_arxiv_id(value: str) -> str | None:
    text = (value or "").strip()
    text = text.removesuffix(".pdf")
    match = _ARXIV_RE.search(text)
    return match.group(1) if match else None


def _with_request_fields(candidate: CitationCandidate, req: AddCitationRequest) -> CitationCandidate:
    return replace(
        candidate,
        cluster=req.cluster or candidate.cluster,
        raw={**candidate.raw, "manual_add_mode": req.mode},
    )


def _parse_manual(req: AddCitationRequest) -> CitationCandidate:
    fields = req.manual
    if fields is None or not fields.title.strip():
        raise ManualCitationError("missing_required", "Manual citation mode requires a title.")
    entry_type = fields.entry_type or _infer_entry_type(fields.journal, fields.booktitle)
    doi = normalize_doi(fields.doi or "") if fields.doi else None
    arxiv_id = normalize_arxiv_id(fields.arxiv_id or fields.url or "") if (fields.arxiv_id or fields.url) else None
    return CitationCandidate(
        title=fields.title.strip(),
        source="manual",
        authors=tuple(author.strip() for author in fields.authors if author.strip()),
        year=fields.year,
        venue=fields.venue or fields.journal or fields.booktitle,
        entry_type=entry_type,
        journal=fields.journal,
        booktitle=fields.booktitle,
        doi=doi,
        arxiv_id=arxiv_id,
        url=fields.url,
        cluster=req.cluster,
    )


def _parse_authors(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(
        _strip_bibtex_value(author)
        for author in re.split(r"\s+and\s+", value)
        if _strip_bibtex_value(author)
    )


def _parse_year(value: Any) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d{4}", str(value))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _normalize_entry_type(value: str | None) -> str:
    entry_type = (value or "").strip().lower()
    if entry_type in _ENTRY_TYPES:
        return entry_type
    if entry_type in {"conference", "inproceeding", "proceedings", "incollection"}:
        return "inproceedings"
    if entry_type in {"journal", "journal-article"}:
        return "article"
    return "misc"


def _infer_entry_type(journal: str | None, booktitle: str | None) -> str:
    if booktitle:
        return "inproceedings"
    if journal:
        return "article"
    return "misc"


def _first_text(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            text = _collapse_ws(str(item)) if item is not None else ""
            if text:
                return text
        return None
    text = _collapse_ws(str(value)) if value is not None else ""
    return text or None


def _crossref_authors(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    authors: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _first_text(item.get("name"))
        given = _first_text(item.get("given"))
        family = _first_text(item.get("family"))
        if name:
            authors.append(name)
        elif given and family:
            authors.append(f"{given} {family}")
        elif family:
            authors.append(family)
        elif given:
            authors.append(given)
    return tuple(authors)


def _crossref_year(message: dict[str, Any]) -> int | None:
    for field in ("published-print", "published-online", "published", "issued", "created"):
        value = message.get(field)
        if not isinstance(value, dict):
            continue
        parts = value.get("date-parts")
        if not isinstance(parts, list) or not parts:
            continue
        first = parts[0]
        if not isinstance(first, list) or not first:
            continue
        year = _parse_year(first[0])
        if year is not None:
            return year
    return None


def _crossref_entry_type(value: Any) -> str:
    entry_type = _collapse_ws(str(value or "")).casefold()
    if entry_type in {"journal-article", "posted-content"}:
        return "article"
    if entry_type in {"proceedings-article", "proceedings"}:
        return "inproceedings"
    return "misc"


def _strip_bibtex_value(value: str) -> str:
    text = _collapse_ws(str(value))
    if len(text) >= 2 and text[0] == "{" and text[-1] == "}":
        text = text[1:-1]
    return _collapse_ws(text)


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _string_or_none(value: Any) -> str | None:
    text = _strip_bibtex_value(str(value)) if value is not None else ""
    return text or None


def _text(element: ET.Element[str] | None) -> str:
    return element.text if element is not None and element.text is not None else ""
