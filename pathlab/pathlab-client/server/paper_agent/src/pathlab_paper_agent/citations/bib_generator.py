"""BibTeX generation for selected references."""

from __future__ import annotations

import re
from typing import Iterable

from .models import CitationReference

_TEXT_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

_BRACE_ESCAPES = {
    "{": r"\{",
    "}": r"\}",
}

_CONFERENCE_MARKERS = (
    "aaai",
    "amia",
    "computer vision and pattern recognition",
    "conference on",
    "cvpr",
    "eccv",
    "iccv",
    "iclr",
    "icml",
    "ijcai",
    "international conference",
    "ipmi",
    "isbi",
    "medical image computing",
    "miccai",
    "mlhc",
    "neurips",
    "nips",
    "proceedings",
    "proceedings of",
    "workshop on",
)

_PREPRINT_MARKERS = (
    "arxiv",
    "biorxiv",
    "medrxiv",
    "posted-content",
    "preprint",
)

_PROTECTED_TITLE_TERMS = (
    "AI",
    "AUC",
    "CI",
    "CNN",
    "CRC",
    "CT",
    "DNA",
    "H&E",
    "ICD",
    "MIL",
    "MRI",
    "MSI",
    "MSS",
    "PET",
    "PR",
    "RNA",
    "ROC",
    "TCGA",
    "WSI",
)

_ARXIV_RE = re.compile(
    r"(?:arxiv(?:\.org)?/(?:abs|pdf)/|arxiv:|10\.48550/arxiv\.)([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)",
    re.IGNORECASE,
)

_FIELD_KIND_TEXT = "text"
_FIELD_KIND_TITLE = "title"
_FIELD_KIND_IDENTIFIER = "identifier"
_FIELD_KIND_RAW = "raw"


def latex_escape(value: str, *, preserve_braces: bool = True) -> str:
    """Escape BibTeX field text while preserving balanced protection braces."""
    text = str(value)
    keep_braces = preserve_braces and _has_balanced_braces(text)
    output: list[str] = []
    for char in text:
        if char in _BRACE_ESCAPES and not keep_braces:
            output.append(_BRACE_ESCAPES[char])
        elif char in _BRACE_ESCAPES:
            output.append(char)
        else:
            output.append(_TEXT_ESCAPES.get(char, char))
    return "".join(output)


def generate_bibtex(refs: Iterable[CitationReference]) -> str:
    entries = [_entry(ref) for ref in refs]
    if not entries:
        return "% No verified references selected.\n"
    return "\n\n".join(entries) + "\n"


def _entry(ref: CitationReference) -> str:
    entry_type = _entry_type(ref)
    fields: list[tuple[str, str, str]] = [("title", ref.title, _FIELD_KIND_TITLE)]
    if ref.authors:
        fields.append(("author", " and ".join(ref.authors), _FIELD_KIND_TEXT))
    venue = _venue_for_entry(ref, entry_type=entry_type)
    if venue and entry_type == "inproceedings":
        fields.append(("booktitle", venue, _FIELD_KIND_TITLE))
    elif venue and entry_type == "article":
        fields.append(("journal", venue, _FIELD_KIND_TITLE))
    if ref.year:
        fields.append(("year", str(ref.year), _FIELD_KIND_RAW))
    for name in ("volume", "number", "pages", "publisher"):
        value = getattr(ref, name, None)
        if value:
            fields.append((name, str(value), _FIELD_KIND_TEXT))
    arxiv_id = _arxiv_id(ref)
    if arxiv_id:
        fields.append(("eprint", arxiv_id, _FIELD_KIND_IDENTIFIER))
        fields.append(("archivePrefix", "arXiv", _FIELD_KIND_RAW))
    if ref.doi:
        fields.append(("doi", ref.doi, _FIELD_KIND_IDENTIFIER))
    if ref.pmid:
        fields.append(("pmid", ref.pmid, _FIELD_KIND_IDENTIFIER))
    if ref.s2_paper_id:
        fields.append(("s2paperid", ref.s2_paper_id, _FIELD_KIND_IDENTIFIER))
    if ref.openalex_id:
        fields.append(("openalexid", ref.openalex_id, _FIELD_KIND_IDENTIFIER))
    if ref.url:
        fields.append(("url", ref.url, _FIELD_KIND_IDENTIFIER))
    rendered = ",\n".join(
        f"  {name} = {{{_render_value(str(value), kind)}}}"
        for name, value, kind in fields
        if value
    )
    return f"@{entry_type}{{{ref.key},\n{rendered}\n}}"


def _entry_type(ref: CitationReference) -> str:
    explicit = str(getattr(ref, "entry_type", "") or "").strip().lower()
    if explicit in {"article", "inproceedings", "misc"}:
        return explicit
    if explicit in {"conference", "inproceeding", "proceedings", "proceedings-article"}:
        return "inproceedings"
    if explicit in {"journal", "journal-article", "journal_article"}:
        return "article"
    if explicit in {"arxiv", "posted-content", "preprint"}:
        return "misc"
    if _arxiv_id(ref) or _contains_any(_metadata_blob(ref), _PREPRINT_MARKERS):
        return "misc"
    booktitle = str(getattr(ref, "booktitle", "") or "")
    if (
        booktitle
        or _contains_any(_venue_for_entry(ref), _CONFERENCE_MARKERS)
        or _contains_any(_metadata_blob(ref), _CONFERENCE_MARKERS)
    ):
        return "inproceedings"
    return "article"


def _venue_for_entry(
    ref: CitationReference,
    *,
    entry_type: str | None = None,
) -> str | None:
    journal = getattr(ref, "journal", None)
    booktitle = getattr(ref, "booktitle", None)
    if entry_type == "inproceedings" and booktitle:
        return str(booktitle)
    if entry_type == "article" and journal:
        return str(journal)
    if ref.venue:
        return ref.venue
    if booktitle:
        return str(booktitle)
    if journal:
        return str(journal)
    return None


def _render_value(value: str, kind: str) -> str:
    stripped = re.sub(r"\s+", " ", value.strip())
    if kind == _FIELD_KIND_RAW:
        return stripped
    if kind == _FIELD_KIND_IDENTIFIER:
        return _escape_identifier(stripped)
    if kind == _FIELD_KIND_TITLE:
        return latex_escape(_protect_title_case(stripped), preserve_braces=True)
    return latex_escape(stripped, preserve_braces=True)


def _escape_identifier(value: str) -> str:
    return value.replace("\\", r"\textbackslash{}").replace("{", r"\{").replace("}", r"\}")


def _protect_title_case(value: str) -> str:
    protected = value
    for term in _PROTECTED_TITLE_TERMS:
        # `s?` lets common English plurals (WSIs / CNNs / AUCs / CIs) be wrapped
        # in the same brace as the singular acronym; the look-ahead still
        # rejects bigger words that just happen to start with the acronym
        # (e.g. "MILstone" must not match the "MIL" term).
        pattern = re.compile(
            rf"(?<![A-Za-z0-9{{]){re.escape(term)}s?(?![A-Za-z0-9}}])"
        )
        protected = pattern.sub(lambda match: f"{{{match.group(0)}}}", protected)
    return protected


def _contains_any(value: str | None, markers: tuple[str, ...]) -> bool:
    if not value:
        return False
    lowered = value.casefold()
    return any(marker in lowered for marker in markers)


def _metadata_blob(ref: CitationReference) -> str:
    values = [
        ref.source,
        ref.venue,
        ref.url,
        ref.doi,
        str(getattr(ref, "publication_type", "") or ""),
    ]
    return " ".join(value for value in values if value)


def _arxiv_id(ref: CitationReference) -> str | None:
    explicit = str(getattr(ref, "arxiv_id", "") or "").strip()
    if explicit:
        return explicit.removeprefix("arXiv:").removeprefix("arxiv:")
    for value in (ref.url, ref.doi, ref.venue, ref.source):
        if not value:
            continue
        match = _ARXIV_RE.search(str(value))
        if match:
            return match.group(1)
    return None


def _has_balanced_braces(value: str) -> bool:
    depth = 0
    escaped = False
    for char in value:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0
