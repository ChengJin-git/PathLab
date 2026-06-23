"""Citation guard: orphan cites and selected/required reference coverage."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pathlab_paper_agent.storage import PaperRunPaths

from .common import GuardReport, rel_to_run, tex_files_under

_CITE_RE = re.compile(r"\\cite\w*\{([^}]+)\}")
_BIB_KEY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)", re.MULTILINE)


def parse_cites(text: str) -> set[str]:
    keys: set[str] = set()
    for match in _CITE_RE.finditer(text):
        for key in match.group(1).split(","):
            stripped = key.strip()
            if stripped:
                keys.add(stripped)
    return keys


def parse_bib_keys(text: str) -> set[str]:
    return {match.group(1).strip() for match in _BIB_KEY_RE.finditer(text)}


def _ref_key(item: dict[str, Any]) -> str | None:
    for field in ("bib_key", "key", "paper_id", "paperId", "id"):
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _load_ref_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("items") if isinstance(data, dict) else data
    keys: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                key = _ref_key(item)
                if key:
                    keys.add(key)
            elif isinstance(item, str):
                keys.add(item)
    return keys


def run(paths: PaperRunPaths, *, min_selected_coverage: float = 0.9) -> GuardReport:
    report = GuardReport("citation_guard", metadata={})
    tex_files = tex_files_under(paths.sections_dir)
    cited: set[str] = set()
    for path in tex_files:
        cited.update(parse_cites(path.read_text(encoding="utf-8")))

    bib_keys = parse_bib_keys(paths.refs_bib.read_text(encoding="utf-8")) if paths.refs_bib.exists() else set()
    selected = _load_ref_keys(paths.citations_dir / "selected_refs.json")
    required = _load_ref_keys(paths.citations_dir / "required_cites.json")

    report.metadata.update(
        {
            "cited_count": len(cited),
            "bib_key_count": len(bib_keys),
            "selected_ref_count": len(selected),
            "required_cite_count": len(required),
            "selected_coverage": 1.0 if not selected else len(cited & selected) / len(selected),
            "checked_files": [rel_to_run(paths, path) for path in tex_files],
        }
    )

    for key in sorted(cited - bib_keys):
        report.error("orphan_cite", "Citation key is used in sections but missing from refs.bib.", context=key)
    for key in sorted(bib_keys - selected):
        if selected:
            report.error("unselected_bib_entry", "refs.bib contains a key not present in selected_refs.json.", context=key)
    missing_required = required - cited
    for key in sorted(missing_required):
        report.error("missing_required_cite", "Required cite is not used in final sections.", context=key)
    if selected and report.metadata["selected_coverage"] < min_selected_coverage:
        report.error(
            "citation_coverage_low",
            f"Selected reference coverage is below {min_selected_coverage:.0%}.",
            context=f"coverage={report.metadata['selected_coverage']:.3f}",
        )
    if cited and not paths.refs_bib.exists():
        report.error("missing_refs_bib", "Sections contain citations but refs.bib is missing.")
    return report
