"""Identifier guard: detect PHI and private provenance leakage."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from pathlab_paper_agent.storage import PaperRunPaths

from .common import GuardReport, paper_text_files, rel_to_run

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_RAW_PATH_RE = re.compile(
    r"(?:/Users/|/home/|/private/|/var/|[A-Za-z]:\\|uploads/(?:logs|models|ai_results_bundles|training)/)",
)
_CASE_ID_RE = re.compile(r"\b(?:case|patient|mrn|slide)[-_ ]?[A-Za-z]*\d{3,}\b", re.IGNORECASE)
_HOSPITAL_RE = re.compile(
    r"\b[A-Z][A-Za-z&.\'-]+(?:\s+[A-Z][A-Za-z&.\'-]+){0,5}\s+(?:Hospital|Medical Center|Clinic)\b"
)


def _load_private_identifiers(paths: PaperRunPaths) -> set[str]:
    if not paths.evidence_lock_private.exists():
        return set()
    data = json.loads(paths.evidence_lock_private.read_text(encoding="utf-8"))
    identifiers: set[str] = set()

    def add_value(value: Any) -> None:
        if isinstance(value, str) and len(value.strip()) >= 3:
            identifiers.add(value.strip())
        elif isinstance(value, list):
            for item in value:
                add_value(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                add_value(key)
                add_value(item)

    for key in (
        "phi_mapping",
        "private_identifiers",
        "raw_identifiers",
        "case_ids",
        "patient_ids",
        "institution_names",
        "raw_paths",
    ):
        if key in data:
            add_value(data[key])
    return identifiers


def _context(text: str, start: int, end: int) -> str:
    prefix = max(0, start - 40)
    suffix = min(len(text), end + 40)
    return text[prefix:suffix].replace("\n", " ")


def _check_regex(report: GuardReport, rel: str, text: str, regex: re.Pattern[str], code: str, message: str) -> None:
    for match in regex.finditer(text):
        report.error(code, message, path=rel, context=_context(text, match.start(), match.end()))


def _check_known_identifiers(report: GuardReport, rel: str, text: str, identifiers: Iterable[str]) -> None:
    for identifier in sorted(set(identifiers), key=len, reverse=True):
        if identifier and identifier in text:
            report.error(
                "private_identifier_leak",
                "Text contains an identifier recorded in private evidence.",
                path=rel,
                context=identifier,
            )


def run(paths: PaperRunPaths) -> GuardReport:
    identifiers = _load_private_identifiers(paths)
    report = GuardReport(
        "identifier_guard",
        metadata={"private_identifier_count": len(identifiers), "checked_files": []},
    )
    checked = paper_text_files(paths)
    report.metadata["checked_files"] = [rel_to_run(paths, path) for path in checked]
    for path in checked:
        rel = rel_to_run(paths, path)
        text = path.read_text(encoding="utf-8")
        _check_known_identifiers(report, rel, text, identifiers)
        _check_regex(report, rel, text, _EMAIL_RE, "email_leak", "Email address appears in paper-facing text.")
        _check_regex(report, rel, text, _RAW_PATH_RE, "raw_path_leak", "Raw filesystem/upload path appears in paper-facing text.")
        _check_regex(report, rel, text, _CASE_ID_RE, "case_identifier_leak", "Possible case/patient/slide identifier appears in paper-facing text.")
        _check_regex(report, rel, text, _HOSPITAL_RE, "institution_name_leak", "Possible institution name appears in paper-facing text.")
    return report
