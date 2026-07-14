"""Helpers for keeping manuscript citation commands aligned with selected refs."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable

from pathlab_paper_agent.storage import PaperRunPaths

_CITE_COMMAND_RE = re.compile(r"(\\cite[a-zA-Z*]*(?:\[[^\]]*\])*)\{([^{}]+)\}")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _citation_items(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        raw_items = payload.get("items")
    else:
        raw_items = payload
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def selected_ref_keys(paths: PaperRunPaths) -> set[str]:
    selected_refs_path = paths.citations_dir / "selected_refs.json"
    if not selected_refs_path.exists():
        return set()
    try:
        payload = json.loads(selected_refs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    keys: set[str] = set()
    for item in _citation_items(payload):
        key = str(item.get("key") or "").strip()
        if key:
            keys.add(key)
    return keys


def prune_unselected_citation_keys_from_text(text: str, selected_keys: Iterable[str]) -> str:
    allowed = set(selected_keys)
    changed = False

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        prefix = match.group(1)
        raw_keys = [part.strip() for part in match.group(2).split(",") if part.strip()]
        if not raw_keys:
            return match.group(0)
        remaining = [part for part in raw_keys if part in allowed]
        if len(remaining) == len(raw_keys):
            return match.group(0)
        changed = True
        return f"{prefix}{{{','.join(remaining)}}}" if remaining else ""

    next_text = _CITE_COMMAND_RE.sub(repl, text)
    if not changed:
        return text
    next_text = re.sub(r"[（(]\s*[）)]", "", next_text)
    next_text = re.sub(r"[ \t]+([,.;:!?])", r"\1", next_text)
    next_text = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", next_text)
    return next_text


def sync_section_citations_to_selected_refs(
    paths: PaperRunPaths,
    selected_keys: Iterable[str] | None = None,
) -> list[str]:
    if not paths.sections_dir.is_dir():
        return []
    selected = selected_ref_keys(paths) if selected_keys is None else set(selected_keys)
    changed_sections: list[str] = []
    for path in sorted(paths.sections_dir.glob("*.tex")):
        if not path.is_file():
            continue
        current = path.read_text(encoding="utf-8")
        updated = prune_unselected_citation_keys_from_text(current, selected)
        if updated == current:
            continue
        _atomic_write_text(path, updated)
        changed_sections.append(path.relative_to(paths.root).as_posix())
    return changed_sections
