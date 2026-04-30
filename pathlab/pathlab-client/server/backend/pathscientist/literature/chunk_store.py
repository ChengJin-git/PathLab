"""Chunk store — JSONL-based persistence for passage chunks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator
from urllib.parse import quote, unquote

from .types import PassageChunk


class ChunkStore:
    """File-based passage chunk storage under corpus/chunks/<paper_id>.jsonl."""

    def __init__(self, literature_dir: Path):
        self._chunks_dir = Path(literature_dir) / "corpus" / "chunks"
        self._chunks_dir.mkdir(parents=True, exist_ok=True)

    def save_chunks(self, paper_id: str, chunks: list[PassageChunk]) -> Path:
        """Write chunks for one paper as JSONL."""
        path = self._chunk_path(paper_id)
        with open(path, "w", encoding="utf-8") as f:
            for chunk in chunks:
                f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
        return path

    def get_chunks(self, paper_id: str) -> list[PassageChunk]:
        """Read all chunks for one paper."""
        path = self._chunk_path(paper_id)
        if not path.exists():
            return []
        chunks = []
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if line:
                chunks.append(PassageChunk.from_dict(json.loads(line)))
        return chunks

    def iter_all_chunks(self) -> Iterator[PassageChunk]:
        """Iterate all chunks across all papers."""
        for path in sorted(self._chunks_dir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").strip().split("\n"):
                if line:
                    yield PassageChunk.from_dict(json.loads(line))

    def list_paper_ids(self) -> list[str]:
        """List paper IDs that have chunks stored."""
        return [unquote(p.stem) for p in sorted(self._chunks_dir.glob("*.jsonl"))]

    def _chunk_path(self, paper_id: str) -> Path:
        safe_id = quote(paper_id, safe="")
        return self._chunks_dir / f"{safe_id}.jsonl"
