"""IndexManifest — track how a literature index was built.

Plan-2026-04-29 literature-acquisition Phase 2 / Task 1.

PaperQA2-inspired: every literature artifact (RAG chunk store, dense
embedding index, sparse FTS index, paper cache, SOTA cache) carries a
manifest that records:

- **Build settings**: embedder model + base URL, chunker version,
  retriever version. If any of these change, the on-disk index is no
  longer compatible — the consumer must rebuild.
- **Source identity**: source URIs + a payload hash of the canonical
  source content. If the corpus changes, the index is stale.
- **Build artifacts**: chunk count, embedding count, embedding dim —
  bookkeeping for diagnostics.
- **Bookkeeping**: built_at timestamp.

The split matters: ``settings_hash()`` only includes fields that
*change correctness*. ``built_at`` and ``chunk_count`` are NOT in the
hash, so a rebuild that produces the same chunks (deterministic) gets
a stable hash even if the timestamp shifts.

``is_stale_against(current)`` is the consumer-facing check: load the
saved manifest, build a current manifest from current settings, ask
whether they disagree. Disagreement → rebuild required.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(eq=True)
class IndexManifest:
    """Manifest describing how a literature artifact was built."""

    name: str = ""
    version: int = 1

    # --- Build settings (correctness-affecting; included in settings_hash) ---
    embedder_model: str = ""
    embedder_base_url: str = ""
    chunker_version: str = ""
    retriever_version: str = ""

    # --- Source identity (correctness-affecting) ---
    source_uris: list[str] = field(default_factory=list)
    source_payload_hash: str = ""

    # --- Build artifacts (informational; NOT in settings_hash) ---
    chunk_count: int = 0
    embedding_count: int = 0
    embedding_dim: int = 0

    # --- Bookkeeping (informational) ---
    built_at: str = ""

    # ------------------------------------------------------------------
    # Identity / staleness
    # ------------------------------------------------------------------

    def settings_hash(self) -> str:
        """Deterministic hash over correctness-affecting fields.

        Two manifests with the same ``settings_hash()`` describe indices
        that produce equivalent results — reusable interchangeably. Two
        manifests with different ``settings_hash()`` values describe
        incompatible indices; one must be rebuilt to match the other.
        """
        canonical = {
            "name": self.name,
            "version": self.version,
            "embedder_model": self.embedder_model,
            "embedder_base_url": self.embedder_base_url,
            "chunker_version": self.chunker_version,
            "retriever_version": self.retriever_version,
            "source_uris": sorted(self.source_uris),
            "source_payload_hash": self.source_payload_hash,
        }
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True).encode("utf-8"),
        ).hexdigest()

    def is_stale_against(self, current: "IndexManifest") -> bool:
        """Whether this manifest is incompatible with ``current``.

        Returns True if any correctness-affecting setting has changed.
        Volatile fields (``built_at``, ``chunk_count``, etc.) are
        ignored.
        """
        return self.settings_hash() != current.settings_hash()

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IndexManifest":
        return cls(
            name=data.get("name", ""),
            version=int(data.get("version", 1)),
            embedder_model=data.get("embedder_model", ""),
            embedder_base_url=data.get("embedder_base_url", ""),
            chunker_version=data.get("chunker_version", ""),
            retriever_version=data.get("retriever_version", ""),
            source_uris=list(data.get("source_uris", []) or []),
            source_payload_hash=data.get("source_payload_hash", ""),
            chunk_count=int(data.get("chunk_count", 0)),
            embedding_count=int(data.get("embedding_count", 0)),
            embedding_dim=int(data.get("embedding_dim", 0)),
            built_at=data.get("built_at", ""),
        )

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "IndexManifest | None":
        """Read manifest from disk. Returns None when missing or corrupt.

        Fail-open: a corrupt manifest is treated as "no manifest" rather
        than raising — callers will see ``is_stale=True`` against any
        meaningful current manifest and rebuild.
        """
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as e:
            logger.warning("IndexManifest.load OSError on %s: %s", path, e)
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("IndexManifest.load corrupt JSON at %s: %s", path, e)
            return None
        if not isinstance(data, dict):
            logger.warning("IndexManifest.load non-object at %s", path)
            return None
        return cls.from_dict(data)


def compute_payload_hash(items: list) -> str:
    """Hash a list of items deterministically.

    Used for ``source_payload_hash``: hash the canonical representation
    of the source corpus / provider response so any content change
    flips the hash.

    - Strings hash directly.
    - Dicts are normalized to JSON with sorted keys so key order doesn't
      affect the hash.
    - Other types stringify via ``repr``.
    """
    h = hashlib.sha256()
    for item in items:
        if isinstance(item, dict):
            h.update(json.dumps(item, sort_keys=True).encode("utf-8"))
        elif isinstance(item, str):
            h.update(item.encode("utf-8"))
        else:
            h.update(repr(item).encode("utf-8"))
        h.update(b"\x00")  # separator so concatenation isn't ambiguous
    return h.hexdigest()
