"""
PDF Vector Store — LanceDB + sentence-transformers for semantic chunk retrieval.

Replaces BM25 page-level search with paragraph-level vector search.
- Embedding model: paraphrase-multilingual-MiniLM-L12-v2 (384-dim, 中英混合)
- Vector DB: LanceDB (embedded, local file storage, 0 port)
- Chunking: LlamaIndex MarkdownNodeParser + SentenceSplitter for structure-
  and sentence-aware chunking (with character-based fallback).
"""
import re
import threading
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ..dependencies import logger
from backend.common.config import Config
from .transformers_runtime import ensure_transformers_runtime_ready

# ── Lazy singletons ─────────────────────────────────────────────────────────
_embedding_model = None
_embedding_lock = threading.Lock()

EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384
# Token-based chunk size for SentenceSplitter (tiktoken tokens).
# 256 tokens ≈ 600-1000 chars — well-suited for the 128-token embedding model
# while preserving enough context for LLM consumption.
CHUNK_SIZE_TOKENS = 256
CHUNK_OVERLAP_TOKENS = 64
# Fallback character-based constants (used when llama-index is unavailable)
CHUNK_SIZE_CHARS = 500
CHUNK_OVERLAP_CHARS = 100
TABLE_NAME = "pdf_chunks"


def _get_vectorstore_dir() -> Path:
    """Return (and create) the LanceDB storage directory."""
    d = Config.get_uploads_dir() / "pdf_cache" / "vector_store"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_embedding_model():
    """Lazy-load the sentence-transformer model (thread-safe)."""
    global _embedding_model
    if _embedding_model is None:
        with _embedding_lock:
            if _embedding_model is None:
                ensure_transformers_runtime_ready("PDF vector embedding model")
                from sentence_transformers import SentenceTransformer
                logger.info(f"[VectorStore] Loading embedding model: {EMBEDDING_MODEL_NAME}")
                _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
                logger.info("[VectorStore] Embedding model loaded")
    return _embedding_model


def _embed_texts(texts: list[str]) -> np.ndarray:
    """Encode a list of texts into embedding vectors."""
    model = _get_embedding_model()
    return model.encode(texts, convert_to_numpy=True, show_progress_bar=False)


# ── Page marker extraction ─────────────────────────────────────────────────

def _extract_pages(markdown: str) -> list[tuple[int, str]]:
    """Split markdown by ``--- Page N ---`` markers into (page_num, content) pairs."""
    page_pattern = re.compile(r'---\s*Page\s+(\d+)\s*---')
    parts = page_pattern.split(markdown)

    pages: list[tuple[int, str]] = []
    if parts[0].strip():
        pages.append((0, parts[0].strip()))
    for i in range(1, len(parts) - 1, 2):
        page_num = int(parts[i])
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            pages.append((page_num, content))

    if not pages:
        pages = [(0, markdown.strip())]
    return pages


# ── Chunking (LlamaIndex pipeline) ────────────────────────────────────────

def _chunk_markdown(markdown: str, url_hash: str, paper_title: str) -> list[dict]:
    """Split markdown into structure- and sentence-aware chunks with metadata.

    Pipeline:
      1. Split by ``--- Page N ---`` markers to preserve page tracking.
      2. Apply ``MarkdownNodeParser`` to each page for header-based splitting.
      3. Apply ``SentenceSplitter`` to further split oversized sections while
         respecting sentence boundaries.
      4. Prepend the section header path to each chunk so the embedding
         captures structural context.

    Falls back to a simple character-based splitter when ``llama-index-core``
    is not installed.

    Each chunk dict has: url_hash, paper_title, page_num, chunk_index, chunk_text,
    block_type, block_id, section_path.
    """
    try:
        return _chunk_markdown_llamaindex(markdown, url_hash, paper_title)
    except ImportError:
        logger.warning(
            "[VectorStore] llama-index-core not installed — "
            "falling back to character-based chunking"
        )
        return _chunk_markdown_fallback(markdown, url_hash, paper_title)
    except Exception as e:
        logger.error(
            f"[VectorStore] LlamaIndex chunking failed, falling back: {e}"
        )
        return _chunk_markdown_fallback(markdown, url_hash, paper_title)


def _chunk_markdown_llamaindex(
    markdown: str, url_hash: str, paper_title: str,
) -> list[dict]:
    """Structure-aware chunking via LlamaIndex MarkdownNodeParser + SentenceSplitter."""
    from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
    from llama_index.core.schema import Document

    md_parser = MarkdownNodeParser.from_defaults()
    sentence_splitter = SentenceSplitter(
        chunk_size=CHUNK_SIZE_TOKENS,
        chunk_overlap=CHUNK_OVERLAP_TOKENS,
    )

    pages = _extract_pages(markdown)
    chunks: list[dict] = []
    chunk_index = 0

    for page_num, page_text in pages:
        # Wrap page content as a LlamaIndex Document
        doc = Document(text=page_text)

        # Step 1: split by markdown headers → one node per section
        section_nodes = md_parser.get_nodes_from_documents([doc])

        for section_node in section_nodes:
            section_text = section_node.get_content()
            header_path = section_node.metadata.get("header_path", "/")

            # Step 2: further split large sections by sentence boundaries
            sub_texts = sentence_splitter.split_text(section_text)

            for sub_text in sub_texts:
                sub_text = sub_text.strip()
                if not sub_text:
                    continue

                # Prepend header path for embedding context (skip if root-only)
                if header_path and header_path != "/":
                    chunk_text = f"[Section: {header_path}]\n{sub_text}"
                else:
                    chunk_text = sub_text

                chunks.append({
                    "url_hash": url_hash,
                    "paper_title": paper_title,
                    "page_num": page_num,
                    "chunk_index": chunk_index,
                    "chunk_text": chunk_text,
                    "display_text": chunk_text,
                    "block_type": "paragraph",
                    "block_id": f"md-p{page_num}-{chunk_index}",
                    "section_path": header_path if header_path and header_path != "/" else "",
                })
                chunk_index += 1

    return chunks


def _chunk_markdown_fallback(
    markdown: str, url_hash: str, paper_title: str,
) -> list[dict]:
    """Simple character-based chunking (fallback when llama-index is unavailable)."""
    pages = _extract_pages(markdown)
    chunks: list[dict] = []
    chunk_index = 0

    for page_num, page_text in pages:
        start = 0
        text_len = len(page_text)
        while start < text_len:
            end = start + CHUNK_SIZE_CHARS
            chunk_text = page_text[start:end].strip()
            if chunk_text:
                chunks.append({
                    "url_hash": url_hash,
                    "paper_title": paper_title,
                    "page_num": page_num,
                    "chunk_index": chunk_index,
                    "chunk_text": chunk_text,
                    "display_text": chunk_text,
                    "block_type": "paragraph",
                    "block_id": f"fallback-p{page_num}-{chunk_index}",
                    "section_path": "",
                })
                chunk_index += 1
            start += CHUNK_SIZE_CHARS - CHUNK_OVERLAP_CHARS
            if end >= text_len:
                break

    return chunks


def _stringify_block_for_embedding(block: dict, paper_title: str) -> str:
    block_type = str(block.get("type") or "paragraph")
    section_path = block.get("section_path") or []
    section_prefix = " / ".join(str(item) for item in section_path if item)
    prefix_parts = [f"[BlockType: {block_type}]"]
    if section_prefix:
        prefix_parts.append(f"[Section: {section_prefix}]")

    body = ""
    if block_type == "paragraph":
        body = str(block.get("text") or "")
    elif block_type == "section":
        body = str(block.get("text") or "")
    elif block_type == "list":
        body = str(block.get("text") or "")
    elif block_type == "code":
        body = str(block.get("text") or "")
    elif block_type == "table":
        body = str(block.get("caption") or "")
        table_markdown = str(block.get("markdown") or "")
        body = f"{body}\n{table_markdown}".strip()
    elif block_type == "figure":
        caption = str(block.get("caption") or "")
        vision_summary = str(block.get("vision_summary") or "")
        body = f"{caption}\n{vision_summary}".strip()
    elif block_type == "equation":
        latex = str(block.get("latex") or "")
        surrounding = str(block.get("surrounding_text") or "")
        body = f"{latex}\n{surrounding}".strip()
    else:
        body = str(block.get("text") or block.get("markdown") or "")

    prefix = " ".join(prefix_parts)
    candidate = f"{prefix}\n{body}".strip()
    return candidate or f"[BlockType: {block_type}] {paper_title}"


def _stringify_block_for_display(block: dict) -> str:
    block_type = str(block.get("type") or "paragraph")
    if block_type in {"paragraph", "section", "list", "code"}:
        return str(block.get("text") or "").strip()
    if block_type == "table":
        caption = str(block.get("caption") or "").strip()
        markdown = str(block.get("markdown") or "").strip()
        return f"{caption}\n{markdown}".strip()
    if block_type == "figure":
        caption = str(block.get("caption") or "").strip()
        vision_summary = str(block.get("vision_summary") or "").strip()
        image = str(block.get("image") or "").strip()
        return "\n".join(part for part in [caption, vision_summary, image] if part).strip()
    if block_type == "equation":
        latex = str(block.get("latex") or "").strip()
        surrounding = str(block.get("surrounding_text") or "").strip()
        return "\n".join(part for part in [latex, surrounding] if part).strip()
    return str(block.get("text") or block.get("markdown") or "").strip()


def _chunk_structured_content(
    structured_content: dict,
    url_hash: str,
    paper_title: str,
) -> list[dict]:
    """Flatten the normalized Document Graph / Block Graph into embedding chunks."""
    blocks = structured_content.get("blocks") if isinstance(structured_content, dict) else None
    if not isinstance(blocks, list):
        return []

    chunks: list[dict] = []
    for chunk_index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        chunk_text = _stringify_block_for_embedding(block, paper_title).strip()
        if not chunk_text:
            continue
        section_path_items = block.get("section_path") or []
        if isinstance(section_path_items, list):
            section_path = " / ".join(str(item) for item in section_path_items if item)
        else:
            section_path = str(section_path_items or "")
        chunks.append({
            "url_hash": url_hash,
            "paper_title": paper_title,
            "page_num": int(block.get("page") or 0),
            "chunk_index": chunk_index,
            "chunk_text": chunk_text,
            "display_text": _stringify_block_for_display(block),
            "block_type": str(block.get("type") or "paragraph"),
            "block_id": str(block.get("id") or f"block-{chunk_index}"),
            "section_path": section_path,
        })
    return chunks


def _create_or_replace_table(db: Any, records: list[dict]) -> None:
    try:
        db.drop_table(TABLE_NAME)
    except Exception:
        pass
    db.create_table(TABLE_NAME, records)


# ── LanceDB operations ──────────────────────────────────────────────────────

def _get_db():
    """Connect to (or create) the LanceDB database."""
    import lancedb
    return lancedb.connect(str(_get_vectorstore_dir()))


def _table_exists(db, name: str) -> bool:
    """Check if a table exists in the DB."""
    try:
        return name in db.table_names()
    except Exception:
        return False


def index_pdf_to_vectorstore(
    url_hash: str,
    markdown: str,
    paper_title: str,
    structured_content: Optional[dict] = None,
) -> int:
    """Chunk + embed + upsert a PDF into the vector store.

    Returns the number of chunks indexed.
    """
    try:
        chunks = _chunk_structured_content(structured_content or {}, url_hash, paper_title)
        if not chunks:
            chunks = _chunk_markdown(markdown, url_hash, paper_title)
        if not chunks:
            logger.warning(f"[VectorStore] No chunks produced for {url_hash}")
            return 0

        # Embed all chunk texts
        texts = [c["chunk_text"] for c in chunks]
        vectors = _embed_texts(texts)

        # Build records
        records = []
        for chunk, vec in zip(chunks, vectors):
            records.append({
                "url_hash": chunk["url_hash"],
                "paper_title": chunk["paper_title"],
                "page_num": chunk["page_num"],
                "chunk_index": chunk["chunk_index"],
                "block_type": chunk.get("block_type", "paragraph"),
                "block_id": chunk.get("block_id", ""),
                "section_path": chunk.get("section_path", ""),
                "display_text": chunk.get("display_text", chunk["chunk_text"]),
                "chunk_text": chunk["chunk_text"],
                "vector": vec.tolist(),
            })

        db = _get_db()

        # Delete old data for this url_hash, then insert new
        if _table_exists(db, TABLE_NAME):
            table = db.open_table(TABLE_NAME)
            try:
                table.delete(f"url_hash = '{url_hash}'")
            except Exception:
                pass  # table might be empty or column missing
            try:
                table.add(records)
            except Exception as e:
                logger.warning(f"[VectorStore] Recreating table after schema drift: {e}")
                _create_or_replace_table(db, records)
        else:
            db.create_table(TABLE_NAME, records)

        logger.info(
            f"[VectorStore] Indexed {len(records)} chunks for "
            f"'{paper_title}' ({url_hash})"
        )
        return len(records)
    except Exception as e:
        logger.error(f"[VectorStore] Indexing failed for {url_hash}: {e}")
        return 0


def search_pdf_chunks(
    query: str,
    url_hashes: list[str] | None = None,
    top_k: int = 15,
) -> list[dict]:
    """Search indexed PDF chunks by semantic similarity.

    Parameters
    ----------
    query : str
        User query text.
    url_hashes : list[str] | None
        If provided, restrict search to these papers only.
    top_k : int
        Maximum number of chunks to return.

    Returns
    -------
    list[dict]
        Each dict has: url_hash, paper_title, page_num, chunk_index,
        block_type, block_id, section_path, display_text, chunk_text, _distance.
    """
    try:
        db = _get_db()
        if not _table_exists(db, TABLE_NAME):
            return []

        query_vec = _embed_texts([query])[0].tolist()
        table = db.open_table(TABLE_NAME)

        search = table.search(query_vec).limit(top_k)

        # Apply URL filter if specified
        if url_hashes:
            if len(url_hashes) == 1:
                search = search.where(f"url_hash = '{url_hashes[0]}'")
            else:
                in_list = ", ".join(f"'{h}'" for h in url_hashes)
                search = search.where(f"url_hash IN ({in_list})")

        results = search.to_list()

        # Clean up results: remove raw vector, keep useful fields
        cleaned = []
        for r in results:
            cleaned.append({
                "url_hash": r.get("url_hash", ""),
                "paper_title": r.get("paper_title", ""),
                "page_num": r.get("page_num", 0),
                "chunk_index": r.get("chunk_index", 0),
                "block_type": r.get("block_type", "paragraph"),
                "block_id": r.get("block_id", ""),
                "section_path": r.get("section_path", ""),
                "display_text": r.get("display_text", r.get("chunk_text", "")),
                "chunk_text": r.get("chunk_text", ""),
                "_distance": r.get("_distance", 999.0),
            })
        return cleaned
    except Exception as e:
        logger.error(f"[VectorStore] Search failed: {e}")
        return []


def delete_pdf_from_vectorstore(url_hash: str) -> None:
    """Remove all chunks for a given url_hash from the vector store."""
    try:
        db = _get_db()
        if not _table_exists(db, TABLE_NAME):
            return
        table = db.open_table(TABLE_NAME)
        table.delete(f"url_hash = '{url_hash}'")
        logger.info(f"[VectorStore] Deleted chunks for {url_hash}")
    except Exception as e:
        logger.error(f"[VectorStore] Delete failed for {url_hash}: {e}")


def is_pdf_indexed(url_hash: str) -> bool:
    """Check whether a PDF is already indexed in the vector store."""
    try:
        db = _get_db()
        if not _table_exists(db, TABLE_NAME):
            return False
        table = db.open_table(TABLE_NAME)
        # Quick probe: search with dummy vector + filter, limit 1
        dummy_vec = [0.0] * EMBEDDING_DIM
        results = table.search(dummy_vec).where(f"url_hash = '{url_hash}'").limit(1).to_list()
        return len(results) > 0
    except Exception:
        return False

