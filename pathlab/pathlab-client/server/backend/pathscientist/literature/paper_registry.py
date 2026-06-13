"""Single source of paper truth — canonical IDs + alias resolution.

Plan-2026-04-29 literature-acquisition Phase 3 / Task 1.

The orchestrator currently has three views of "the literature":

- ``LiteratureStore`` (curated paper IDs, baselines)
- ``ChunkStore`` (passages, may use curated or OpenAlex IDs)
- ``SotaCache`` (paper IDs from PwC / OpenAlex / curated)

These three never share a paper identity, so the same paper appearing
under different IDs (curated ``kather2019`` vs DOI ``10.1038/...`` vs
OpenAlex ``W2934015580``) cannot be deduped or joined.

``PaperRegistry`` is the canonical paper store. ``register(paper)``
merges by alias overlap so two records with overlapping IDs collapse
into one. ``resolve(any_id)`` returns the canonical ID for any alias.
``Paper.from_legacy_dict()`` bridges current ``LiteratureStore`` JSON
records into the new model with no migration script needed up front.

Phase 3 Task 3+ wires the consumers (LiteratureStore, ChunkStore,
SotaLookup, CitationTracker) to read/write through the registry.
This module is the data layer only — additive, no consumer changes
required to land it.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .id_resolver import canonicalize_aliases, to_canonical_id

logger = logging.getLogger(__name__)


@dataclass
class Paper:
    """One paper, identified by a canonical ID + 0..N aliases.

    Bibliographic + subject metadata mirrors ``literature/types.py``'s
    ``PaperRecord`` so a legacy record converts losslessly via
    ``from_legacy_dict``.

    The citation graph fields (``cites``, ``cited_by``) are populated by
    Phase 5 when adapter-driven enrichment lands; they're declared here
    so the schema doesn't shift later.
    """

    canonical_id: str = ""
    aliases: list[str] = field(default_factory=list)

    # Bibliographic
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int = 0
    venue: str = ""
    abstract: str = ""

    # Source metadata
    source: str = "local"
    url: str = ""

    # Subject metadata
    organ: str = ""
    task_type: str = ""
    methods: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    # Citation graph (Phase 5)
    cites: list[str] = field(default_factory=list)
    cited_by: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Paper":
        return cls(
            canonical_id=data.get("canonical_id", ""),
            aliases=list(data.get("aliases", []) or []),
            title=data.get("title", ""),
            authors=list(data.get("authors", []) or []),
            year=int(data.get("year", 0) or 0),
            venue=data.get("venue", ""),
            abstract=data.get("abstract", ""),
            source=data.get("source", "local"),
            url=data.get("url", ""),
            organ=data.get("organ", ""),
            task_type=data.get("task_type", ""),
            methods=list(data.get("methods", []) or []),
            datasets=list(data.get("datasets", []) or []),
            tags=list(data.get("tags", []) or []),
            cites=list(data.get("cites", []) or []),
            cited_by=list(data.get("cited_by", []) or []),
        )

    @classmethod
    def from_legacy_dict(cls, data: dict[str, Any]) -> "Paper":
        """Bridge a legacy ``LiteratureStore`` JSON record (paper_id +
        optional doi/openalex_id/arxiv_id fields) into a Paper with a
        canonical ID and alias list.

        Promotes DOI to canonical when present (highest priority),
        else falls back to whatever single ID the legacy record carries.
        """
        candidate_ids: list[str] = []
        for key in ("doi", "openalex_id", "arxiv_id", "pmid", "s2_id"):
            value = data.get(key, "")
            if value:
                candidate_ids.append(str(value))
        legacy_id = data.get("paper_id", "")
        if legacy_id:
            candidate_ids.append(str(legacy_id))
        canonical, aliases = canonicalize_aliases(candidate_ids)

        return cls(
            canonical_id=canonical,
            aliases=aliases,
            title=data.get("title", ""),
            authors=list(data.get("authors", []) or []),
            year=int(data.get("year", 0) or 0),
            venue=data.get("venue", ""),
            abstract=data.get("abstract", ""),
            source=data.get("source", "local"),
            url=data.get("url", ""),
            organ=data.get("organ", ""),
            task_type=data.get("task_type", ""),
            methods=list(data.get("methods", []) or []),
            datasets=list(data.get("datasets", []) or []),
            tags=list(data.get("tags", []) or []),
        )


class PaperRegistry:
    """Keyed-by-canonical-ID store with alias resolution + merge-on-overlap.

    Mutations:
      - ``register(paper)``: insert or merge with an existing paper that
        shares any alias. Returns the canonical ID of the merged paper.

    Reads:
      - ``resolve(any_id)``: alias → canonical ID, or ``None`` when unknown.
      - ``get(canonical_id)``: full Paper or ``None``.
      - ``list()``: all papers.

    Persistence: ``save(path)`` / ``load(path)`` JSON round-trip.
    Designed to fail open — corrupt or missing file becomes empty
    registry, never an exception.
    """

    def __init__(self):
        self._papers: dict[str, Paper] = {}
        # Alias index: any alias (incl. canonical) → canonical_id.
        self._alias_to_canonical: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def resolve(self, any_id: str) -> str | None:
        if not any_id:
            return None
        normalized = to_canonical_id(any_id)
        if normalized in self._alias_to_canonical:
            return self._alias_to_canonical[normalized]
        return None

    def get(self, canonical_id: str) -> Paper | None:
        return self._papers.get(canonical_id)

    def list(self) -> list[Paper]:
        return list(self._papers.values())

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def register(self, paper: Paper) -> str:
        """Insert or merge ``paper`` into the registry.

        Merge happens when the incoming paper shares any alias (canonical
        OR explicit) with an existing entry. The merged paper's canonical
        ID is whichever alias set has the highest-priority canonical
        (DOI > OpenAlex > pmid > s2 > arxiv > curated).
        """
        if not paper.canonical_id:
            return ""

        # All known IDs for the incoming record.
        incoming_ids = {paper.canonical_id, *paper.aliases}

        # Find existing canonical IDs that share any alias.
        matches: set[str] = set()
        for any_id in incoming_ids:
            existing = self._alias_to_canonical.get(any_id)
            if existing:
                matches.add(existing)

        if not matches:
            self._insert_fresh(paper)
            return paper.canonical_id

        # Merge: combine all aliases from incoming + matched papers.
        all_papers = [paper]
        for canonical in matches:
            existing_paper = self._papers.pop(canonical)
            all_papers.append(existing_paper)
            # Drop alias index entries for this paper (we'll rebuild).
            for alias in [
                k for k, v in self._alias_to_canonical.items() if v == canonical
            ]:
                del self._alias_to_canonical[alias]

        # Pool of all known IDs.
        all_ids: list[str] = []
        for p in all_papers:
            all_ids.append(p.canonical_id)
            all_ids.extend(p.aliases)
        new_canonical, new_aliases = canonicalize_aliases(all_ids)

        # Field merge: prefer the most-informative non-empty value across
        # papers. Heuristic: existing populated wins over empty; otherwise
        # the new (incoming) overrides.
        merged = Paper(canonical_id=new_canonical, aliases=new_aliases)
        for source in all_papers:
            for key, value in source.to_dict().items():
                if key in {"canonical_id", "aliases"}:
                    continue
                current = getattr(merged, key)
                # Empty list / empty string / 0 → take any non-empty value.
                if isinstance(current, list):
                    if value:
                        seen = set(current)
                        for item in value:
                            if item not in seen:
                                current.append(item)
                                seen.add(item)
                elif not current and value:
                    setattr(merged, key, value)

        self._insert_fresh(merged)
        return new_canonical

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _insert_fresh(self, paper: Paper) -> None:
        self._papers[paper.canonical_id] = paper
        # Index canonical + every alias to point at this canonical_id.
        self._alias_to_canonical[paper.canonical_id] = paper.canonical_id
        for alias in paper.aliases:
            self._alias_to_canonical[alias] = paper.canonical_id

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                [p.to_dict() for p in self._papers.values()],
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "PaperRegistry":
        registry = cls()
        path = Path(path)
        if not path.exists():
            return registry
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(
                "PaperRegistry.load corrupt JSON at %s: %s; empty registry",
                path, e,
            )
            return registry
        if not isinstance(data, list):
            logger.warning(
                "PaperRegistry.load expected list at %s, got %s",
                path, type(data).__name__,
            )
            return registry
        for record in data:
            if isinstance(record, dict):
                registry.register(Paper.from_dict(record))
        return registry
