"""Deterministic citation candidate verification."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Iterable, Optional

from .models import CitationCandidate, VerificationReport, normalize_title


def title_similarity(left: str, right: str) -> float:
    """Return normalized title similarity in [0, 1]."""
    norm_left = normalize_title(left)
    norm_right = normalize_title(right)
    if not norm_left or not norm_right:
        return 0.0
    return SequenceMatcher(None, norm_left, norm_right).ratio()


def verify_candidates(
    candidates: Iterable[CitationCandidate],
    *,
    cutoff_year: Optional[int] = None,
    min_title_similarity: float = 0.7,
) -> VerificationReport:
    """Verify and deduplicate paper candidates.

    Hard gates:
      - title must be present
      - year must not exceed cutoff when cutoff is supplied
      - if a `claimed_title` is present, it must match the verified title
        above the configured similarity threshold
      - duplicate DOI / PMID / S2 id / normalized title collapse to one item

    Abstract and venue are recorded as warnings because API coverage differs
    between S2 and PubMed; later LLM stages can decide if missing context is
    acceptable for the writing task.
    """
    verified: list[CitationCandidate] = []
    rejected: list[dict] = []
    seen: set[str] = set()

    for candidate in sorted(candidates, key=_sort_key):
        reasons: list[str] = []
        warnings: list[str] = []
        title = candidate.title.strip()
        if not title:
            reasons.append("missing_title")
        if cutoff_year is not None and candidate.year is not None and candidate.year > cutoff_year:
            reasons.append("after_cutoff_year")
        if candidate.claimed_title:
            score = title_similarity(candidate.claimed_title, candidate.title)
            if score < min_title_similarity:
                reasons.append("title_similarity_below_threshold")
        if not candidate.abstract:
            warnings.append("missing_abstract")
        if not candidate.venue:
            warnings.append("missing_venue")

        dedup_keys = _dedup_keys(candidate)
        if seen.intersection(dedup_keys):
            reasons.append("duplicate")

        if reasons:
            rejected.append(
                {
                    "candidate": candidate.to_dict(),
                    "reasons": reasons,
                    "warnings": warnings,
                }
            )
            continue

        seen.update(dedup_keys)
        if warnings:
            raw = dict(candidate.raw)
            raw.setdefault("verification_warnings", warnings)
            candidate = CitationCandidate(
                **{**candidate.to_dict(), "authors": tuple(candidate.authors), "raw": raw}
            )
        verified.append(candidate)

    verified.sort(key=_sort_key)
    return VerificationReport(
        verified=tuple(verified),
        rejected=tuple(rejected),
        cutoff_year=cutoff_year,
        min_title_similarity=min_title_similarity,
    )


def _dedup_keys(candidate: CitationCandidate) -> set[str]:
    keys = {f"title:{normalize_title(candidate.title)}"}
    if candidate.s2_paper_id:
        keys.add(f"s2:{candidate.s2_paper_id}")
    if candidate.openalex_id:
        keys.add(f"openalex:{candidate.openalex_id}")
    if candidate.doi:
        keys.add(f"doi:{candidate.doi.casefold()}")
    if candidate.pmid:
        keys.add(f"pmid:{candidate.pmid}")
    return {key for key in keys if not key.endswith(":")}


def _sort_key(candidate: CitationCandidate) -> tuple:
    year = candidate.year or 0
    source_rank = 0 if candidate.source == "pubmed" else 1
    return (source_rank, -(candidate.citation_count or 0), -year, normalize_title(candidate.title))
