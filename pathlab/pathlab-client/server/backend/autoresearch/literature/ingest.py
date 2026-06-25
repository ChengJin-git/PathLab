"""Corpus ingestion — parse documents into provenance-rich chunks."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .parsers import parser_for_path
from .types import PassageChunk


def ingest_document(
    paper_id: str,
    path: Path,
    chunk_size: int = 300,
    chunk_overlap: int = 50,
) -> list[PassageChunk]:
    """Parse a document and split into chunks with provenance.

    Returns a list of PassageChunk objects ready for indexing.
    """
    parser = parser_for_path(path)
    text, metadata = parser.parse(path)
    if not text.strip():
        return []
    return chunk_text(paper_id, text, metadata, chunk_size=chunk_size, chunk_overlap=chunk_overlap)


def chunk_text(
    paper_id: str,
    text: str,
    metadata: dict[str, Any] | None = None,
    chunk_size: int = 300,
    chunk_overlap: int = 50,
) -> list[PassageChunk]:
    """Split text into overlapping chunks with section awareness.

    Uses a sliding window of ~chunk_size words with ~chunk_overlap word overlap.
    Detects markdown-style section headers (# or ##) to assign section names.
    """
    metadata = metadata or {}

    # Build page boundary map from PDF parser metadata if available
    page_boundaries = _build_page_boundaries(text, metadata)

    sections = _split_into_sections(text)
    chunks: list[PassageChunk] = []
    chunk_idx = 0

    for section_name, section_text in sections:
        words = section_text.split()
        if not words:
            continue

        start = 0
        while start < len(words):
            end = min(start + chunk_size, len(words))
            chunk_words = words[start:end]
            chunk_text_str = " ".join(chunk_words)

            # Compute character offsets in original text
            char_start = text.find(chunk_words[0], 0 if not chunks else chunks[-1].char_end)
            if char_start < 0:
                char_start = 0
            char_end = char_start + len(chunk_text_str)

            # Resolve page number from character offset
            page = _resolve_page(char_start, page_boundaries)

            chunks.append(PassageChunk(
                paper_id=paper_id,
                chunk_id=f"{paper_id}:{chunk_idx}",
                text=chunk_text_str,
                page=page,
                section=section_name,
                char_start=char_start,
                char_end=min(char_end, len(text)),
                token_count=len(chunk_words),
                metadata=metadata,
            ))
            chunk_idx += 1

            # Advance with overlap
            step = max(1, chunk_size - chunk_overlap)
            if start + step >= len(words):
                break
            start += step

    return chunks


def _build_page_boundaries(text: str, metadata: dict[str, Any]) -> list[tuple[int, int]]:
    """Build a list of (char_offset, page_number) from PDF parser metadata.

    Returns sorted list of (char_start, page_num) boundaries.
    If no page info available, returns empty list.
    """
    page_texts = metadata.get("page_texts")
    if not page_texts:
        return []

    boundaries: list[tuple[int, int]] = []
    offset = 0
    for page_num, page_text in page_texts:
        boundaries.append((offset, page_num))
        offset += len(page_text) + 2  # +2 for "\n\n" separator
    return boundaries


def _resolve_page(char_offset: int, page_boundaries: list[tuple[int, int]]) -> int | None:
    """Resolve which page a character offset falls on."""
    if not page_boundaries:
        return None
    page = page_boundaries[0][1]
    for boundary_offset, page_num in page_boundaries:
        if char_offset >= boundary_offset:
            page = page_num
        else:
            break
    return page


def _split_into_sections(text: str) -> list[tuple[str, str]]:
    """Split text by markdown headers. Returns [(section_name, section_text), ...]."""
    sections: list[tuple[str, str]] = []
    current_name = ""
    current_lines: list[str] = []

    for line in text.split("\n"):
        header_match = re.match(r'^#{1,3}\s+(.+)', line)
        if header_match:
            if current_lines:
                sections.append((current_name, "\n".join(current_lines)))
            current_name = header_match.group(1).strip().lower()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_name, "\n".join(current_lines)))

    return sections


def chunks_from_paper_metadata(paper) -> list[PassageChunk]:
    """Build synthetic chunks from a PaperRecord's metadata.

    Produces up to 3 chunks per paper for bootstrap RAG without full PDFs:
    - ``abstract``: title + authors + year + abstract
    - ``methods``: title + methods/datasets/organ/task_type summary
    - ``results``: title + baseline table (one line per reported metric)

    Each chunk is tagged with ``metadata["source"] = "seed_metadata"`` so the
    source can later be distinguished from user-ingested full-text chunks.
    """
    chunks: list[PassageChunk] = []
    base_meta = {
        "source": "seed_metadata",
        "organ": getattr(paper, "organ", ""),
        "task_type": getattr(paper, "task_type", ""),
        "year": getattr(paper, "year", 0),
        "venue": getattr(paper, "venue", ""),
    }

    # 1. Abstract chunk
    title = getattr(paper, "title", "")
    abstract = getattr(paper, "abstract", "")
    if title or abstract:
        parts = []
        if title:
            parts.append(title)
        authors = getattr(paper, "authors", [])
        if authors:
            parts.append(f"Authors: {', '.join(authors[:5])}")
        year = getattr(paper, "year", 0)
        if year:
            parts.append(f"({year})")
        if abstract:
            parts.append(abstract)
        text = ". ".join(parts)
        chunks.append(PassageChunk(
            paper_id=paper.paper_id,
            chunk_id=f"{paper.paper_id}:abstract",
            text=text,
            section="abstract",
            token_count=len(text.split()),
            metadata=base_meta,
        ))

    # 2. Methods chunk
    methods = getattr(paper, "methods", [])
    datasets = getattr(paper, "datasets", [])
    if methods or datasets:
        parts = [title] if title else []
        if methods:
            parts.append(f"Methods: {', '.join(methods)}")
        if datasets:
            parts.append(f"Datasets: {', '.join(datasets)}")
        organ = getattr(paper, "organ", "")
        if organ:
            parts.append(f"Organ: {organ}")
        task_type = getattr(paper, "task_type", "")
        if task_type:
            parts.append(f"Task type: {task_type}")
        tags = getattr(paper, "tags", [])
        if tags:
            parts.append(f"Tags: {', '.join(tags)}")
        text = ". ".join(parts)
        chunks.append(PassageChunk(
            paper_id=paper.paper_id,
            chunk_id=f"{paper.paper_id}:methods",
            text=text,
            section="methods",
            token_count=len(text.split()),
            metadata=base_meta,
        ))

    # 3. Baselines / results chunk
    baselines = getattr(paper, "baselines", [])
    if baselines:
        lines = [f"{title}. Reported results:"] if title else ["Reported results:"]
        for b in baselines:
            method = getattr(b, "method", "?")
            metric_name = getattr(b, "metric_name", "?")
            metric_value = getattr(b, "metric_value", 0.0)
            dataset = getattr(b, "dataset", "?")
            lines.append(f"- {method} achieves {metric_value:.3f} {metric_name} on {dataset}")
        text = "\n".join(lines)
        chunks.append(PassageChunk(
            paper_id=paper.paper_id,
            chunk_id=f"{paper.paper_id}:results",
            text=text,
            section="results",
            token_count=len(text.split()),
            metadata=base_meta,
        ))

    return chunks


class IngestManifest:
    """Tracks which files have been ingested for incremental re-ingestion."""

    def __init__(self, manifest_path: Path):
        self._path = Path(manifest_path)
        self._data: dict[str, str] = {}
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                pass

    def should_reingest(self, path: Path) -> bool:
        """Check if a file needs re-ingestion (new or changed)."""
        key = str(Path(path).resolve())
        current_hash = self._file_hash(path)
        return self._data.get(key) != current_hash

    def record(self, path: Path) -> None:
        """Record that a file has been ingested."""
        key = str(Path(path).resolve())
        self._data[key] = self._file_hash(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _file_hash(path: Path) -> str:
        """Quick hash of file content for change detection."""
        h = hashlib.md5()
        h.update(Path(path).read_bytes())
        return h.hexdigest()
