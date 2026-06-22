"""Dense embedding index — encode chunks and search by cosine similarity."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np

from .types import PassageChunk, PassageHit

logger = logging.getLogger(__name__)

# Default embedding endpoint — Qwen3-Embedding served via vLLM on dgx-24:9001
DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_EMBEDDING_BASE_URL = "http://dgx-24.cm.cluster:9001/v1"
DEFAULT_EMBEDDING_API_KEY = "sk-pathlab"


class Embedder(Protocol):
    """Protocol for text embedding functions."""
    def __call__(self, texts: list[str]) -> np.ndarray: ...


def make_api_embedder(
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    base_url: str = DEFAULT_EMBEDDING_BASE_URL,
    api_key: str = DEFAULT_EMBEDDING_API_KEY,
    batch_size: int = 32,
    timeout: float = 60.0,
) -> Embedder:
    """Create an embedder that calls an OpenAI-compatible /v1/embeddings endpoint.

    Used for remote embedding services (e.g. Qwen3-Embedding served by vLLM).
    Returns L2-normalized vectors.
    """
    import requests

    def embed(texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)

        all_vecs: list[list[float]] = []
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = f"{base_url.rstrip('/')}/embeddings"

        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            payload = {"model": model_name, "input": batch}
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            for item in data["data"]:
                all_vecs.append(item["embedding"])

        arr = np.array(all_vecs, dtype=np.float32)
        # Normalize for cosine similarity
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return arr / norms

    return embed


def _make_sentence_transformers_embedder(model_name: str) -> Embedder:
    """Fallback: local sentence-transformers embedder."""
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name)

    def embed(texts: list[str]) -> np.ndarray:
        return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    return embed


def _default_embedder(
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    base_url: str = "",
    api_key: str = "",
) -> Embedder:
    """Create the default embedder.

    If the model name looks like an API-hosted model (contains '/') and a base
    URL is configured, use the OpenAI-compatible API embedder.  Otherwise fall
    back to sentence-transformers for local models.
    """
    resolved_base = base_url or os.environ.get("PATHSCIENTIST_RAG_EMBEDDING_BASE_URL", DEFAULT_EMBEDDING_BASE_URL)
    resolved_key = api_key or os.environ.get("PATHSCIENTIST_RAG_EMBEDDING_API_KEY", DEFAULT_EMBEDDING_API_KEY)

    # Heuristic: if model name looks like an API model (contains org/model or matches default), use API
    if "/" in model_name or model_name == DEFAULT_EMBEDDING_MODEL:
        return make_api_embedder(model_name=model_name, base_url=resolved_base, api_key=resolved_key)
    return _make_sentence_transformers_embedder(model_name)


class EmbeddingIndex:
    """Dense embedding index stored as numpy arrays on disk."""

    def __init__(
        self,
        index_dir: Path,
        embedder: Embedder | None = None,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        base_url: str = "",
        api_key: str = "",
    ):
        self._dir = Path(index_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._embeddings_path = self._dir / "embeddings.npy"
        self._chunk_ids_path = self._dir / "chunk_ids.json"
        self._metadata_path = self._dir / "metadata.json"
        self._model_name = model_name
        self._base_url = base_url
        self._api_key = api_key
        self._embedder = embedder
        self._matrix: np.ndarray | None = None
        self._chunk_ids: list[str] = []
        self._chunk_texts: dict[str, str] = {}
        self._chunk_meta: dict[str, dict[str, Any]] = {}

        # Load existing index if available
        if self._embeddings_path.exists() and self._chunk_ids_path.exists():
            self._load()

    def _get_embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = _default_embedder(
                self._model_name, base_url=self._base_url, api_key=self._api_key,
            )
        return self._embedder

    def build(self, chunks: list[PassageChunk]) -> int:
        """Build the embedding index from chunks. Returns count."""
        if not chunks:
            return 0

        embedder = self._get_embedder()
        texts = [c.text for c in chunks]
        embeddings = embedder(texts)

        self._matrix = np.array(embeddings, dtype=np.float32)
        self._chunk_ids = [c.chunk_id for c in chunks]
        self._chunk_texts = {c.chunk_id: c.text for c in chunks}
        # Plan-2026-04-29 grounding-routing-repair Task 7: persist
        # organ/task_type metadata so dense search can filter by them.
        self._chunk_meta = {
            c.chunk_id: {
                "paper_id": c.paper_id,
                "page": c.page,
                "section": c.section,
                "organ": str((c.metadata or {}).get("organ", "")),
                "task_type": str((c.metadata or {}).get("task_type", "")),
            }
            for c in chunks
        }

        # Save to disk
        np.save(str(self._embeddings_path), self._matrix)
        self._chunk_ids_path.write_text(
            json.dumps(self._chunk_ids, ensure_ascii=False), encoding="utf-8"
        )
        self._metadata_path.write_text(json.dumps({
            "model_name": self._model_name,
            "dimension": int(self._matrix.shape[1]),
            "count": len(self._chunk_ids),
            "texts": self._chunk_texts,
            "meta": self._chunk_meta,
        }, ensure_ascii=False), encoding="utf-8")

        return len(chunks)

    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.1,
        organ: str | None = None,
        task_type: str | None = None,
    ) -> list[PassageHit]:
        """Cosine similarity search over the embedding matrix.

        Plan-2026-04-29 grounding-routing-repair Task 7: optional
        ``organ`` / ``task_type`` filters. If a chunk's metadata field is
        empty (older indexes built before T7), it is NOT filtered out —
        keeps dense search useful while old indexes haven't been
        rebuilt.
        """
        if self._matrix is None or len(self._chunk_ids) == 0:
            return []

        embedder = self._get_embedder()
        query_vec = embedder([query])
        query_vec = np.array(query_vec, dtype=np.float32)
        if query_vec.ndim == 1:
            query_vec = query_vec.reshape(1, -1)

        # Cosine similarity (vectors are pre-normalized).
        # Over-fetch so metadata filtering doesn't shrink the result set
        # below top_k when many top hits get filtered out.
        scores = (self._matrix @ query_vec.T).flatten()
        fetch_k = top_k * 3 if (organ or task_type) else top_k
        top_indices = np.argsort(scores)[::-1][:fetch_k]

        hits: list[PassageHit] = []
        for idx in top_indices:
            idx = int(idx)
            chunk_id = self._chunk_ids[idx]
            score = float(scores[idx])
            if score < min_score:
                continue
            meta = self._chunk_meta.get(chunk_id, {})
            if organ:
                meta_organ = str(meta.get("organ", "")).lower()
                if meta_organ and organ.lower() not in meta_organ:
                    continue
            if task_type:
                meta_task = str(meta.get("task_type", "")).lower()
                if meta_task and task_type.lower() not in meta_task:
                    continue
            hits.append(PassageHit(
                paper_id=meta.get("paper_id", ""),
                chunk_id=chunk_id,
                text=self._chunk_texts.get(chunk_id, ""),
                score=score,
                dense_score=score,
                page=meta.get("page"),
                section=meta.get("section", ""),
            ))
            if len(hits) >= top_k:
                break
        return hits

    def _load(self) -> None:
        """Load existing index from disk."""
        try:
            self._matrix = np.load(str(self._embeddings_path))
            self._chunk_ids = json.loads(self._chunk_ids_path.read_text(encoding="utf-8"))
            if self._metadata_path.exists():
                meta = json.loads(self._metadata_path.read_text(encoding="utf-8"))
                self._chunk_texts = meta.get("texts", {})
                self._chunk_meta = meta.get("meta", {})
        except Exception as e:
            logger.warning(f"Failed to load embedding index: {e}")
            self._matrix = None
            self._chunk_ids = []
