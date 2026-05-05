"""Deterministic renderer for M9 citation placeholders."""

from __future__ import annotations

import re
from collections.abc import Iterable

CITE_PLACEHOLDER_RE = re.compile(r"\[CITE:([A-Za-z0-9_:-]+)\]")
_MALFORMED_CITE_RE = re.compile(r"\[CITE:[^\]]*\]")


class CitationRenderError(ValueError):
    """Raised when citation placeholders cannot be rendered safely."""


def extract_citation_placeholders(text: str) -> set[str]:
    """Return citation keys referenced through the M9 placeholder syntax."""
    return {match.group(1) for match in CITE_PLACEHOLDER_RE.finditer(text)}


def render_citation_placeholders(text: str, allowed_keys: Iterable[str]) -> str:
    """Render ``[CITE:paperId]`` placeholders to LaTeX ``\\cite{paperId}``.

    The renderer is intentionally strict: malformed placeholders and keys outside
    the selected reference set fail before any paper-facing TeX is written.
    """
    allowed = {str(key) for key in allowed_keys if str(key)}
    malformed = [match.group(0) for match in _MALFORMED_CITE_RE.finditer(text) if not CITE_PLACEHOLDER_RE.fullmatch(match.group(0))]
    if malformed:
        examples = ", ".join(sorted(set(malformed))[:5])
        raise CitationRenderError(f"Malformed citation placeholder(s): {examples}")

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in allowed:
            raise CitationRenderError(f"Citation key {key!r} is not present in selected_refs.json")
        return rf"\cite{{{key}}}"

    return CITE_PLACEHOLDER_RE.sub(repl, text)
