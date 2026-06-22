"""Parse and canonicalize paper identifiers across providers.

Plan-2026-04-29 literature-acquisition Phase 3 / Task 2.

A paper can be referred to by many IDs:

- DOI               ``10.1038/s41591-019-0508-1`` / ``doi:...`` / ``https://doi.org/...``
- OpenAlex          ``W2934015580`` / ``openalex:...`` / ``https://openalex.org/...``
- arXiv             ``1906.06337`` / ``arxiv:...`` / ``https://arxiv.org/abs/...``
- PubMed            ``31358813`` / ``pmid:...``
- Semantic Scholar  ``CorpusID:194098876`` / ``s2:...``
- Curated           ``kather2019`` (PathScientist's hand-picked seed IDs)

This module:

1. ``parse_id(any) -> (scheme, value)`` recognizes the scheme and strips
   prefix/URL syntax.
2. ``to_canonical_id(any) -> "<scheme>:<value>"`` normalizes any
   accepted form to a canonical string.
3. ``pick_canonical(ids) -> "<scheme>:<value>"`` chooses the
   highest-priority canonical from a set of aliases. DOI wins because
   it's the join key for OpenAlex / Semantic Scholar / OpenCitations.
4. ``canonicalize_aliases(ids) -> (canonical, aliases)`` returns the
   canonical plus the deduped, normalized rest.

Pure string manipulation — no network, no I/O. Failures fall back to
``("curated", original_string.strip())`` so unrecognized inputs become
explicitly-curated IDs and stay routable.
"""
from __future__ import annotations

import re
from typing import Iterable

# Priority order: highest first. DOI wins because it joins providers.
CANONICAL_PRIORITY: tuple[str, ...] = (
    "doi",
    "openalex",
    "pmid",
    "s2",
    "arxiv",
    "curated",
    "unknown",
)

_DOI_RE = re.compile(r"^10\.\d{4,9}/[\w\-\._;\(\)/:]+$", re.IGNORECASE)
_OPENALEX_RE = re.compile(r"^W\d{2,}$", re.IGNORECASE)
_ARXIV_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
_PMID_RE = re.compile(r"^\d{4,9}$")


def parse_id(any_id: str) -> tuple[str, str]:
    """Return ``(scheme, value)`` for ``any_id``.

    Recognized schemes: ``doi`` | ``openalex`` | ``arxiv`` | ``pmid`` |
    ``s2`` | ``curated``. Unknown inputs fall back to ``curated``.
    """
    if not any_id:
        return ("curated", "")
    raw = any_id.strip()

    # Explicit ``scheme:value`` form.
    if ":" in raw and not raw.lower().startswith(("http://", "https://")):
        head, _, rest = raw.partition(":")
        head_l = head.strip().lower()
        rest_stripped = rest.strip()
        if head_l in {"doi", "openalex", "arxiv", "pmid", "s2", "curated"}:
            return (head_l, rest_stripped)
        if head_l == "corpusid":
            return ("s2", rest_stripped)

    # URL forms.
    lower = raw.lower()
    if "doi.org/" in lower:
        # Strip everything up through the doi.org/ portion.
        idx = lower.find("doi.org/")
        return ("doi", raw[idx + len("doi.org/"):])
    if "openalex.org/" in lower:
        idx = lower.find("openalex.org/")
        return ("openalex", raw[idx + len("openalex.org/"):])
    if "arxiv.org/abs/" in lower:
        idx = lower.find("arxiv.org/abs/")
        return ("arxiv", raw[idx + len("arxiv.org/abs/"):])

    # Bare patterns.
    if _DOI_RE.match(raw):
        return ("doi", raw)
    if _OPENALEX_RE.match(raw):
        return ("openalex", raw)
    if _ARXIV_RE.match(raw):
        return ("arxiv", raw)
    # PMID is just digits — only treat as PMID when explicitly prefixed,
    # since bare digits are too ambiguous (could collide with arxiv etc.).
    # We already handled the "pmid:" prefix above, so a bare digit string
    # without prefix here falls through to curated (rare).

    # Unknown → treat as curated.
    return ("curated", raw)


def to_canonical_id(any_id: str) -> str:
    """Normalize ``any_id`` to ``"<scheme>:<value>"`` form."""
    scheme, value = parse_id(any_id)
    return f"{scheme}:{value}" if value else ""


def _scheme_rank(scheme: str) -> int:
    try:
        return CANONICAL_PRIORITY.index(scheme)
    except ValueError:
        return len(CANONICAL_PRIORITY)


def pick_canonical(ids: Iterable[str]) -> str:
    """Return the highest-priority canonical ID from ``ids``.

    Empty input → ``""``.
    """
    canonicals: list[tuple[int, str]] = []
    for any_id in ids:
        if not any_id:
            continue
        canonical = to_canonical_id(any_id)
        if not canonical:
            continue
        scheme = canonical.split(":", 1)[0]
        canonicals.append((_scheme_rank(scheme), canonical))
    if not canonicals:
        return ""
    canonicals.sort(key=lambda t: (t[0], t[1]))
    return canonicals[0][1]


def canonicalize_aliases(ids: Iterable[str]) -> tuple[str, list[str]]:
    """Return ``(canonical_id, aliases)`` from a mixed input list.

    All inputs are normalized via ``to_canonical_id``, deduped, and the
    canonical is excluded from the alias list.
    """
    seen: set[str] = set()
    normalized: list[str] = []
    for any_id in ids:
        if not any_id:
            continue
        canonical = to_canonical_id(any_id)
        if canonical and canonical not in seen:
            seen.add(canonical)
            normalized.append(canonical)
    if not normalized:
        return ("", [])
    canonical = pick_canonical(normalized)
    aliases = sorted(c for c in normalized if c != canonical)
    return (canonical, aliases)
