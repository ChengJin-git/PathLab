"""Deterministic PHI and private-provenance scrubbing."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

_PATH_RE = re.compile(
    r"(?:/Users/|/home/|/private/|/var/|uploads/(?:logs|models|ai_results_bundles|training)/)[^\s,;\"']+"
)
_CASE_RE = re.compile(r"\b(?:CASE|PATIENT|MRN|SLIDE)[-_ ]?[A-Za-z]*\d{3,}\b", re.IGNORECASE)
_INSTITUTION_RE = re.compile(
    r"\b[A-Z][A-Za-z&.'-]+(?:\s+[A-Z][A-Za-z&.'-]+){0,5}\s+(?:Hospital|Medical Center|Clinic)\b"
)
_DATE_RE = re.compile(r"\b(?:19|20)\d{2}[-_/](?:0?[1-9]|1[0-2])[-_/](?:0?[1-9]|[12]\d|3[01])\b")


@dataclass
class PhiScrubber:
    """Collect raw identifiers and replace them with deterministic placeholders."""

    case_ids: dict[str, str] = field(default_factory=dict)
    institution_names: dict[str, str] = field(default_factory=dict)
    raw_paths: dict[str, str] = field(default_factory=dict)
    dates: dict[str, str] = field(default_factory=dict)

    def observe(self, value: Any) -> None:
        if isinstance(value, str):
            self._observe_text(value)
        elif isinstance(value, Mapping):
            for key, item in value.items():
                self.observe(key)
                self.observe(item)
        elif isinstance(value, list | tuple | set):
            for item in value:
                self.observe(item)

    def scrub(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.scrub_text(value)
        if isinstance(value, Mapping):
            return {str(self.scrub_text(str(key))): self.scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.scrub(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.scrub(item) for item in value)
        return value

    def scrub_text(self, text: str) -> str:
        scrubbed = text
        for raw, replacement in sorted(self.raw_paths.items(), key=lambda item: len(item[0]), reverse=True):
            scrubbed = scrubbed.replace(raw, replacement)
        for raw, replacement in sorted(self.case_ids.items(), key=lambda item: len(item[0]), reverse=True):
            scrubbed = scrubbed.replace(raw, replacement)
        for raw, replacement in sorted(self.institution_names.items(), key=lambda item: len(item[0]), reverse=True):
            scrubbed = scrubbed.replace(raw, replacement)
        for raw, replacement in sorted(self.dates.items(), key=lambda item: len(item[0]), reverse=True):
            scrubbed = scrubbed.replace(raw, replacement)
        return scrubbed

    def private_identifiers(self) -> dict[str, list[str]]:
        return {
            "case_ids": sorted(self.case_ids),
            "institution_names": sorted(self.institution_names),
            "raw_paths": sorted(self.raw_paths),
            "dates": sorted(self.dates),
        }

    def mapping(self) -> dict[str, dict[str, str]]:
        return {
            "case_ids": dict(sorted(self.case_ids.items())),
            "institution_names": dict(sorted(self.institution_names.items())),
            "raw_paths": dict(sorted(self.raw_paths.items())),
            "dates": dict(sorted(self.dates.items())),
        }

    def _observe_text(self, text: str) -> None:
        for path in _PATH_RE.findall(text):
            self.raw_paths.setdefault(path, f"PRIVATE_PATH_{len(self.raw_paths) + 1:03d}")
        for case_id in _CASE_RE.findall(text):
            self.case_ids.setdefault(case_id, f"PRIVATE_CASE_{len(self.case_ids) + 1:03d}")
        for institution in _INSTITUTION_RE.findall(text):
            self.institution_names.setdefault(
                institution,
                f"PRIVATE_INSTITUTION_{len(self.institution_names) + 1:03d}",
            )
        for date in _DATE_RE.findall(text):
            self.dates.setdefault(date, f"PRIVATE_DATE_{len(self.dates) + 1:03d}")
