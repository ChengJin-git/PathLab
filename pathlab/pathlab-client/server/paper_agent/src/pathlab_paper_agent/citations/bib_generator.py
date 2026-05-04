"""BibTeX generation for selected references."""

from __future__ import annotations

from typing import Iterable

from .models import CitationReference

_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(value: str) -> str:
    return "".join(_LATEX_ESCAPES.get(char, char) for char in value)


def generate_bibtex(refs: Iterable[CitationReference]) -> str:
    entries = [_entry(ref) for ref in refs]
    if not entries:
        return "% No verified references selected.\n"
    return "\n\n".join(entries) + "\n"


def _entry(ref: CitationReference) -> str:
    fields: list[tuple[str, str]] = [("title", ref.title)]
    if ref.authors:
        fields.append(("author", " and ".join(ref.authors)))
    if ref.venue:
        fields.append(("journal", ref.venue))
    if ref.year:
        fields.append(("year", str(ref.year)))
    if ref.doi:
        fields.append(("doi", ref.doi))
    if ref.pmid:
        fields.append(("pmid", ref.pmid))
    if ref.s2_paper_id:
        fields.append(("s2paperid", ref.s2_paper_id))
    if ref.url:
        fields.append(("url", ref.url))
    rendered = ",\n".join(
        f"  {name} = {{{latex_escape(str(value))}}}" for name, value in fields if value
    )
    return f"@article{{{ref.key},\n{rendered}\n}}"
