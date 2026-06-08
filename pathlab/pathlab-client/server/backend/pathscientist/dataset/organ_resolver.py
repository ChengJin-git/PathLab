"""Ontology-backed organ/site normalization for task grounding.

The resolver is intentionally local and deterministic: LLMs may propose an
organ, but this module decides the canonical value used by dataset matching.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Any


@dataclass(frozen=True)
class OrganMatch:
    canonical: str = ""
    raw: str = ""
    matched_term: str = ""
    confidence: str = ""
    source: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class _OrganEntry:
    canonical: str
    display: str
    aliases: tuple[str, ...]
    disease_terms: tuple[str, ...]
    tcga_codes: tuple[str, ...]


_BOUNDARY_LEFT = r"(?<![A-Za-z0-9])"
_BOUNDARY_RIGHT = r"(?![A-Za-z0-9])"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", _clean(value).lower())


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term).replace(r"\ ", r"\s+")
    return re.compile(f"{_BOUNDARY_LEFT}{escaped}{_BOUNDARY_RIGHT}", re.IGNORECASE)


class OrganResolver:
    """Resolve raw organ/site strings and text snippets to canonical organs."""

    def __init__(self, entries: Iterable[_OrganEntry]):
        self._entries = list(entries)
        self._by_canonical = {entry.canonical: entry for entry in self._entries}
        self._alias_to_canonical: dict[str, str] = {}
        self._term_index: list[tuple[str, str, str, re.Pattern[str]]] = []
        for entry in self._entries:
            terms = {entry.canonical, *entry.aliases, *entry.tcga_codes}
            for term in terms:
                key = _norm(term)
                if key:
                    self._alias_to_canonical.setdefault(key, entry.canonical)
                    self._term_index.append((entry.canonical, key, "alias", _term_pattern(key)))
            for term in entry.disease_terms:
                key = _norm(term)
                if key:
                    self._term_index.append((entry.canonical, key, "disease", _term_pattern(key)))
        self._term_index.sort(key=lambda item: len(item[1]), reverse=True)

    @classmethod
    @lru_cache(maxsize=1)
    def load_default(cls) -> "OrganResolver":
        path = Path(__file__).with_name("ontology") / "organs.json"
        raw = json.loads(path.read_text())
        entries: list[_OrganEntry] = []
        for row in raw.get("organs", []):
            canonical = _norm(row.get("canonical"))
            if not canonical:
                continue
            entries.append(
                _OrganEntry(
                    canonical=canonical,
                    display=_clean(row.get("display")) or canonical,
                    aliases=tuple(_clean(v) for v in row.get("aliases", []) if _clean(v)),
                    disease_terms=tuple(_clean(v) for v in row.get("disease_terms", []) if _clean(v)),
                    tcga_codes=tuple(_clean(v) for v in row.get("tcga_codes", []) if _clean(v)),
                )
            )
        return cls(entries)

    def has_canonical(self, organ: str) -> bool:
        return _norm(organ) in self._by_canonical

    def aliases_for(self, canonical: str) -> set[str]:
        key = self.normalize(canonical).canonical or _norm(canonical)
        entry = self._by_canonical.get(key)
        if entry is None:
            return {key} if key else set()
        return {_norm(entry.canonical), *{_norm(v) for v in entry.aliases}, *{_norm(v) for v in entry.tcga_codes}}

    def normalize(self, value: str, *, source: str = "") -> OrganMatch:
        raw = _clean(value)
        key = _norm(raw)
        if not key:
            return OrganMatch(raw=raw, source=source)
        canonical = self._alias_to_canonical.get(key)
        if canonical:
            return self._match(canonical, raw=raw, matched_term=key, confidence="high", source=source)
        if key in self._by_canonical:
            return self._match(key, raw=raw, matched_term=key, confidence="high", source=source)
        return OrganMatch(raw=raw, source=source)

    def resolve_text(self, text: str, *, source: str = "text") -> OrganMatch:
        raw = _clean(text)
        if not raw:
            return OrganMatch(raw=raw, source=source)
        exact = self.normalize(raw, source=source)
        if exact.canonical:
            return exact
        for canonical, term, kind, pattern in self._term_index:
            if pattern.search(raw):
                confidence = "high" if kind == "alias" else "medium"
                return self._match(
                    canonical,
                    raw=raw,
                    matched_term=term,
                    confidence=confidence,
                    source=source,
                )
        return OrganMatch(raw=raw, source=source)

    def organ_matches(self, left: str, right_values: Iterable[str]) -> bool:
        left_match = self.normalize(left, source="match")
        left_key = left_match.canonical or _norm(left)
        if not left_key:
            return False
        left_aliases = self.aliases_for(left_key)
        for value in right_values:
            right_match = self.normalize(value, source="match")
            right_key = right_match.canonical or _norm(value)
            if right_key and (right_key == left_key or right_key in left_aliases):
                return True
            if right_key and left_key in self.aliases_for(right_key):
                return True
        return False

    def _match(
        self,
        canonical: str,
        *,
        raw: str,
        matched_term: str,
        confidence: str,
        source: str,
    ) -> OrganMatch:
        entry = self._by_canonical.get(canonical)
        aliases: tuple[str, ...] = ()
        if entry is not None:
            aliases = tuple(sorted({_norm(v) for v in (entry.canonical, *entry.aliases, *entry.tcga_codes) if _norm(v)}))
        return OrganMatch(
            canonical=canonical,
            raw=raw,
            matched_term=matched_term,
            confidence=confidence,
            source=source,
            aliases=aliases,
        )
