"""Surface known dataset path corrections in the execution brief.

Plan T7 (docs/plans/2026-04-28-autoresearch-latest-session-review-fixes-plan.md):
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
    # Session c8ccabbf95bb: prompt ingress/OCR corrupted llmponco into
    # visually similar prefixes. Only use these if the corrected target exists.
    "/project/lImponco/": "/project/llmponco/",
    "/project/1 1mponco/": "/project/llmponco/",
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


def _scan_alias_path_starting_at(text: str, start: int, bad_prefix: str) -> str:
    """Return the full path token for a known bad prefix occurrence.

    Some known bad prefixes contain whitespace (for example
    ``/project/1 1mponco/``). The generic token scanner would stop at that
    embedded space, so scan the prefix as an atomic literal first and only
    apply token terminators to the suffix.
    """
    i = start + len(bad_prefix)
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
            original = _scan_alias_path_starting_at(text, idx, bad)
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


# Regex for absolute-path tokens. Starts at ``/<letter>`` to skip plain
# slashes / fractions in prose. Matches path-safe chars then stops at
# whitespace / punctuation.
_PATH_RE = re.compile(r"/[A-Za-z][\w./_\-~]*")


def find_existing_data_paths(text: str) -> list[str]:
    """Return absolute paths mentioned in ``text`` that exist as
    directories on disk, after applying ``KNOWN_PREFIX_ALIASES``.

    Used by the orchestrator runner to detect "user supplied a local
    dataset path inline in the prompt" — those paths should bypass
    acquisition. We only return directories (not files) because data
    mounts are folder-shaped; a user pointing at a CSV file or a single
    image is a different (later) feature.

    Order: first the path as-typed (no alias), then alias-corrected. We
    dedupe so an as-typed match isn't re-reported as alias-corrected.
    """
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []

    def _append_if_existing_dir(token: str) -> bool:
        if not token:
            return False
        try:
            if Path(token).is_dir() and token not in seen:
                seen.add(token)
                out.append(token)
                return True
        except OSError:
            return False
        return False

    def _append_alias_if_existing_dir(token: str) -> None:
        for bad, good in KNOWN_PREFIX_ALIASES.items():
            if token.startswith(bad):
                candidate = good + token[len(bad):]
                _append_if_existing_dir(candidate)
                break

    for match in _PATH_RE.finditer(text):
        token = match.group(0).rstrip(".,;")
        if not token:
            continue
        # As-typed.
        if _append_if_existing_dir(token):
            continue
        # Alias-corrected.
        _append_alias_if_existing_dir(token)

    # Alias literals can contain characters (notably whitespace) that the
    # regex path tokenizer intentionally treats as token boundaries. Scan
    # known aliases directly so those full paths can still be corrected.
    for bad in KNOWN_PREFIX_ALIASES:
        idx = 0
        while True:
            idx = text.find(bad, idx)
            if idx < 0:
                break
            original = _scan_alias_path_starting_at(text, idx, bad).rstrip(".,;")
            idx += len(bad)
            if _append_if_existing_dir(original):
                continue
            _append_alias_if_existing_dir(original)
    return out
