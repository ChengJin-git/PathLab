"""Deduplication helpers for user-added citations."""

from __future__ import annotations

from collections.abc import Iterable

from pathlab_paper_agent.citations.models import (
    CitationCandidate,
    CitationReference,
    normalize_title,
)
from pathlab_paper_agent.citations.verifier import title_similarity

_TITLE_DUPLICATE_THRESHOLD = 0.92


def duplicate_of(
    candidate: CitationCandidate,
    existing_refs: Iterable[CitationReference],
    *,
    title_threshold: float = _TITLE_DUPLICATE_THRESHOLD,
) -> str | None:
    """Return the existing citekey that matches the candidate, if any."""
    for ref in existing_refs:
        if _exact_identifier_match(candidate, ref):
            return ref.key
    candidate_title = normalize_title(candidate.title)
    if not candidate_title:
        return None
    for ref in existing_refs:
        if normalize_title(ref.title) and title_similarity(candidate.title, ref.title) >= title_threshold:
            return ref.key
    return None


def _exact_identifier_match(candidate: CitationCandidate, ref: CitationReference) -> bool:
    for left, right in (
        (_normalize_identifier(candidate.doi), _normalize_identifier(ref.doi)),
        (_normalize_identifier(candidate.arxiv_id), _normalize_identifier(ref.arxiv_id)),
        (_normalize_identifier(candidate.s2_paper_id), _normalize_identifier(ref.s2_paper_id)),
        (_normalize_identifier(candidate.pmid), _normalize_identifier(ref.pmid)),
        (_normalize_identifier(candidate.openalex_id), _normalize_identifier(ref.openalex_id)),
    ):
        if left and right and left == right:
            return True
    return False


def _normalize_identifier(value: str | None) -> str:
    return str(value or "").strip().casefold()
