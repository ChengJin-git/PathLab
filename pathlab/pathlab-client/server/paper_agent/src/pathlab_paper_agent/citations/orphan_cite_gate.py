"""Orphan citation gate: every cite key must exist in refs.bib/selected refs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import CitationReference


@dataclass(frozen=True)
class OrphanCitationReport:
    used_cite_count: int
    known_ref_count: int
    orphan_cites: tuple[str, ...]
    status: str

    def to_dict(self) -> dict:
        return {
            "used_cite_count": self.used_cite_count,
            "known_ref_count": self.known_ref_count,
            "orphan_cites": list(self.orphan_cites),
            "status": self.status,
        }


def check_orphan_cites(
    used_keys: set[str], refs: Iterable[CitationReference]
) -> OrphanCitationReport:
    known = {ref.key for ref in refs}
    orphans = tuple(sorted(used_keys - known))
    return OrphanCitationReport(
        used_cite_count=len(used_keys),
        known_ref_count=len(known),
        orphan_cites=orphans,
        status="pass" if not orphans else "fail",
    )
