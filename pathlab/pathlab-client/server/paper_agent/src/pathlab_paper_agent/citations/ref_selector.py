"""Select final references and required cites from verified candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import CitationCandidate, CitationReference, normalize_title, stable_key


@dataclass(frozen=True)
class ReferenceSelection:
    selected_refs: tuple[CitationReference, ...]
    required_cites: tuple[CitationReference, ...]

    def to_dict(self) -> dict:
        return {
            "selected_refs": [item.to_dict() for item in self.selected_refs],
            "required_cites": [item.to_dict() for item in self.required_cites],
            "selected_ref_count": len(self.selected_refs),
            "required_cite_count": len(self.required_cites),
        }


def select_references(
    candidates: Iterable[CitationCandidate],
    *,
    max_refs: int = 30,
    required_per_cluster: int = 1,
) -> ReferenceSelection:
    """Pick selected refs and core required cites.

    Required cites are chosen as the highest-scoring candidate per cluster.
    Remaining references are filled by global score until `max_refs`.
    """
    ordered = sorted(candidates, key=_score_key)
    selected_candidates = ordered[:max(0, max_refs)]
    used_keys: set[str] = set()
    references: list[CitationReference] = []
    for candidate in selected_candidates:
        key = _make_unique_key(candidate, used_keys)
        used_keys.add(key)
        references.append(CitationReference.from_candidate(candidate, key=key))

    by_cluster: dict[str, list[CitationReference]] = {}
    for ref in references:
        cluster = ref.cluster or ref.query or "general"
        by_cluster.setdefault(cluster, []).append(ref)

    required_keys: set[str] = set()
    for refs in by_cluster.values():
        for ref in refs[:required_per_cluster]:
            required_keys.add(ref.key)

    selected_refs = tuple(
        CitationReference.from_dict({**ref.to_dict(), "required": ref.key in required_keys})
        for ref in references
    )
    required_cites = tuple(ref for ref in selected_refs if ref.required)
    return ReferenceSelection(selected_refs=selected_refs, required_cites=required_cites)


def _score_key(candidate: CitationCandidate) -> tuple:
    pubmed_bonus = 1 if candidate.source == "pubmed" else 0
    has_abstract = 1 if candidate.abstract else 0
    year = candidate.year or 0
    return (-pubmed_bonus, -has_abstract, -(candidate.citation_count or 0), -year, normalize_title(candidate.title))


def _make_unique_key(candidate: CitationCandidate, used: set[str]) -> str:
    author = "ref"
    if candidate.authors:
        author = candidate.authors[0].split()[-1]
    elif candidate.s2_paper_id:
        author = "s2"
    elif candidate.pmid:
        author = "pmid"
    elif candidate.openalex_id:
        author = "openalex"
    year = str(candidate.year or "nd")
    title_words = "_".join(normalize_title(candidate.title).split()[:3])
    base = stable_key(f"{author}{year}_{title_words}")
    key = base
    suffix = 2
    while key in used:
        key = f"{base}_{suffix}"
        suffix += 1
    return key
