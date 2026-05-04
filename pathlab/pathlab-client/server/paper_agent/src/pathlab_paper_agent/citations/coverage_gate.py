"""Citation coverage checks shared by M8a and M10a."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import CitationReference

_LATEX_CITE_RE = re.compile(
    r"\\(?:"
    r"cite|citet|citep|citealp|citealt|citeauthor|citeyear|citeyearpar|"
    r"parencite|textcite|autocite|supercite|footcite"
    r")\*?(?:\s*\[[^\]]*\])*\s*\{([^{}]+)\}"
)
_PLACEHOLDER_CITE_RE = re.compile(r"\[CITE:([^\]]+)\]")


@dataclass(frozen=True)
class CitationCoverageReport:
    selected_ref_count: int
    required_cite_count: int
    used_selected_count: int
    coverage: float
    missing_required: tuple[str, ...]
    unused_selected: tuple[str, ...]
    status: str

    def to_dict(self) -> dict:
        return {
            "selected_ref_count": self.selected_ref_count,
            "required_cite_count": self.required_cite_count,
            "used_selected_count": self.used_selected_count,
            "coverage": self.coverage,
            "missing_required": list(self.missing_required),
            "unused_selected": list(self.unused_selected),
            "status": self.status,
        }


def extract_cite_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for pattern in (_LATEX_CITE_RE, _PLACEHOLDER_CITE_RE):
        for match in pattern.finditer(text):
            keys.update(_split_cite_keys(match.group(1) or ""))
    return keys


def _split_cite_keys(raw: str) -> set[str]:
    return {key.strip() for key in raw.split(",") if key.strip()}


def read_tex_citations(paths: Iterable[Path]) -> set[str]:
    keys: set[str] = set()
    for path in paths:
        if path.exists() and path.is_file():
            keys.update(extract_cite_keys(path.read_text(encoding="utf-8")))
    return keys


def check_citation_coverage(
    selected_refs: Iterable[CitationReference],
    required_cites: Iterable[CitationReference],
    used_keys: set[str],
    *,
    min_coverage: float = 0.9,
) -> CitationCoverageReport:
    selected = {ref.key for ref in selected_refs}
    required = {ref.key for ref in required_cites}
    used_selected = selected & used_keys
    used_required = required & used_keys
    coverage = 1.0 if not required else len(used_required) / len(required)
    missing_required = tuple(sorted(required - used_keys))
    unused_selected = tuple(sorted(selected - used_keys))
    status = "pass" if coverage >= min_coverage and not missing_required else "fail"
    return CitationCoverageReport(
        selected_ref_count=len(selected),
        required_cite_count=len(required),
        used_selected_count=len(used_selected),
        coverage=coverage,
        missing_required=missing_required,
        unused_selected=unused_selected,
        status=status,
    )
