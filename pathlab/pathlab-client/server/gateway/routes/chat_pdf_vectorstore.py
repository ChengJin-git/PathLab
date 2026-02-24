"""
PDF Vector Store — LanceDB + sentence-transformers for semantic chunk retrieval.

Replaces BM25 page-level search with paragraph-level vector search.
- Embedding model: paraphrase-multilingual-MiniLM-L12-v2 (384-dim, 中英混合)
- Vector DB: LanceDB (embedded, local file storage, 0 port)
- Chunking: ~500 chars with 100 char overlap
"""
import re
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from ..dependencies import logger
from backend.common.config import Config

# ── Lazy singletons ─────────────────────────────────────────────────────────
_embedding_model = None
_embedding_lock = threading.Lock()

EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100
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
                from sentence_transformers import SentenceTransformer
                logger.info(f"[VectorStore] Loading embedding model: {EMBEDDING_MODEL_NAME}")
                _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
                logger.info("[VectorStore] Embedding model loaded")
    return _embedding_model


def _embed_texts(texts: list[str]) -> np.ndarray:
    """Encode a list of texts into embedding vectors."""
    model = _get_embedding_model()
    return model.encode(texts, convert_to_numpy=True, show_progress_bar=False)


# ── Chunking ────────────────────────────────────────────────────────────────

def _chunk_markdown(markdown: str, url_hash: str, paper_title: str) -> list[dict]:
    """Split markdown into overlapping chunks with metadata.

    Each chunk dict has: url_hash, paper_title, page_num, chunk_index, chunk_text.
    """
    chunks: list[dict] = []

    # Split by page markers: '--- Page N ---'
    page_pattern = re.compile(r'---\s*Page\s+(\d+)\s*---')
    parts = page_pattern.split(markdown)

    # parts = [before_first_marker, page_num_1, content_1, page_num_2, content_2, ...]
    pages: list[tuple[int, str]] = []
    if parts[0].strip():
        pages.append((0, parts[0].strip()))
    for i in range(1, len(parts) - 1, 2):
        page_num = int(parts[i])
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            pages.append((page_num, content))

    if not pages:
        # No page markers — treat entire doc as page 0
        pages = [(0, markdown.strip())]

    chunk_index = 0
    for page_num, page_text in pages:
        # Split page text into chunks with overlap
        start = 0
        text_len = len(page_text)
        while start < text_len:
            end = start + CHUNK_SIZE
            chunk_text = page_text[start:end].strip()
            if chunk_text:
                chunks.append({
                    "url_hash": url_hash,
                    "paper_title": paper_title,
                    "page_num": page_num,
                    "chunk_index": chunk_index,
                    "chunk_text": chunk_text,
                })
                chunk_index += 1
            # Advance by (CHUNK_SIZE - CHUNK_OVERLAP) to create overlap
            start += CHUNK_SIZE - CHUNK_OVERLAP
            if end >= text_len:
                break

    return chunks


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


def index_pdf_to_vectorstore(url_hash: str, markdown: str, paper_title: str) -> int:
    """Chunk + embed + upsert a PDF into the vector store.

    Returns the number of chunks indexed.
    """
    try:
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
            table.add(records)
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
        chunk_text, _distance.
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

