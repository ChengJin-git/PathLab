"""Surface known dataset path corrections in the execution brief.

Plan T7 (docs/plans/2026-04-28-pathscientist-latest-session-review-fixes-plan.md):
session_a70dd3a564c1's user typed ``/project/compath/.../CRC-MSI`` (missing
the ``v``). The correct path is ``/project/vcompath/.../CRC-MSI``. The agent
spent iterations failing on a non-existent path before figuring it out.

This module surfaces path corrections in the execution brief WITHOUT
rewriting the user's question — keeping the original verbatim while
making the alternative explicit and verifiable (we only suggest a
correction when the alias target actually exists on disk).
"""
from __future__ import annotations

import re
from pathlib import Path

KNOWN_PREFIX_ALIASES: dict[str, str] = {
    # session_a70dd3a564c1: user wrote "compath" (without 'v'), real path
    # is "vcompath".
    "/project/compath/": "/project/vcompath/",
}

# Path token terminators: whitespace, comma, semicolon, fullwidth Chinese
# 。 (objectives are often Chinese-prefixed). Within a token, slashes,
# letters, digits, dots, dashes, underscores, and tildes are all path-safe.
_TOKEN_TERMINATORS = " \t\n\r,;。"


def _scan_path_starting_at(text: str, start: int) -> str:
    """Return the absolute-path token starting at ``text[start]`` (which
    is presumed to be the first char of a path prefix — e.g. ``/`` of
    ``/project/...``). Stops at the first whitespace/punctuation."""
    i = start
    while i < len(text) and text[i] not in _TOKEN_TERMINATORS:
        i += 1
    return text[start:i]


def find_path_corrections(text: str) -> list[tuple[str, str]]:
    """Return (typo'd, corrected) pairs for paths that are wrong but
    have an existing-on-disk alias.

    Strategy: for each known prefix alias, find every occurrence of the
    bad prefix in the text, extract the full path token starting there,
    and check whether substituting the corrected prefix yields an
    existing path on disk. Dedupes (original, corrected) pairs.

    Filters out paths that already exist (no correction needed) and
    aliases whose target also doesn't exist (no help to be had).
    """
    if not text:
        return []
    seen: set[tuple[str, str]] = set()
    corrections: list[tuple[str, str]] = []
    for bad, good in KNOWN_PREFIX_ALIASES.items():
        idx = 0
        while True:
            idx = text.find(bad, idx)
            if idx < 0:
                break
            original = _scan_path_starting_at(text, idx)
            idx += len(bad)
            if Path(original).exists():
                continue
            candidate = good + original[len(bad):]
            if Path(candidate).exists():
                pair = (original, candidate)
                if pair not in seen:
                    seen.add(pair)
                    corrections.append(pair)
    return corrections
