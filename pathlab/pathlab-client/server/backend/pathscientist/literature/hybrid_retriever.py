"""Hybrid retriever — merges sparse (FTS5) and dense (embedding) retrieval."""
from __future__ import annotations

import logging

from .embeddings import EmbeddingIndex
from .sparse_index import SparseChunkIndex
from .types import PassageHit

logger = logging.getLogger(__name__)


# Plan-2026-04-29 P0-2: surface why retrieval degraded so the operator
# can tell "no passages because nothing matched" apart from "no passages
# because the embedding endpoint is down".
RAG_STATUS_HYBRID = "hybrid"
RAG_STATUS_SPARSE_ONLY = "sparse_only"
RAG_STATUS_SPARSE_ONLY_DENSE_UNAVAILABLE = "sparse_only_dense_unavailable"
RAG_STATUS_DENSE_ONLY_SPARSE_UNAVAILABLE = "dense_only_sparse_unavailable"
RAG_STATUS_UNAVAILABLE = "unavailable"
RAG_STATUS_EMPTY = "empty"
# Plan-2026-04-29 literature-acquisition Phase 1 / Task 7:
RAG_STATUS_SPARSE_ONLY_DENSE_DISABLED = "sparse_only_dense_disabled"


class HybridLiteratureRetriever:
    """Combines sparse and dense retrieval with reciprocal rank fusion.

    Plan-2026-04-29 P0-2: dense lookup may fail (embedding endpoint down,
    network refused) — pre-fix the whole call propagated the exception to
    grounding and ``passages = []`` with no observable cause. Now dense
    failures degrade to sparse-only and the last call's ``last_status``
    explains what happened.
    """

    def __init__(
        self,
        sparse_index: SparseChunkIndex,
        embedding_index: EmbeddingIndex,
        sparse_weight: float = 0.5,
        dense_weight: float = 0.5,
        policy=None,  # NetworkPolicy | None — defer import for cycles
    ):
        self._sparse = sparse_index
        self._dense = embedding_index
        self._sparse_weight = sparse_weight
        self._dense_weight = dense_weight
        # Plan-2026-04-29 literature-acquisition Phase 1 / Task 7:
        # ``policy=None`` preserves legacy behavior — auto stage with
        # rag_dense leg always allowed.
        from .. runtime.network_policy import NetworkLegStatus, NetworkPolicy
        if policy is None:
            policy = NetworkPolicy(
                stage="auto",
                allow_papers=False,
                allow_sota=False,
                allow_rag_dense=True,
            )
        self._policy = policy
        self.last_status: str = "not_started"
        self.last_dense_error: str = ""
        self.last_sparse_error: str = ""
        self.last_network_status = NetworkLegStatus(
            leg="rag_dense", state="not_invoked",
        )

    def retrieve_passages(
        self,
        query: str,
        top_k: int = 5,
        organ: str | None = None,
        task_type: str | None = None,
        dense_min_score: float = 0.1,
    ) -> list[PassageHit]:
        """Retrieve passages using hybrid sparse+dense retrieval with RRF merge.

        Returns sparse-only results when the dense endpoint is unavailable
        (catches any exception from ``embedding_index.search`` — e.g.
        ``ConnectionError`` when the vLLM endpoint is down).
        """
        from ..runtime.network_policy import (
            NetworkLegStatus, NetworkUnavailableError,
        )
        fetch_k = top_k * 3  # over-fetch for better merge quality
        self.last_dense_error = ""
        self.last_sparse_error = ""

        # Sparse leg always runs — it's local.
        sparse_hits: list[PassageHit] = []
        try:
            sparse_hits = self._sparse.search(
                query, top_k=fetch_k, organ=organ, task_type=task_type,
            )
        except Exception as e:
            self.last_sparse_error = f"{type(e).__name__}: {str(e)[:200]}"
            logger.warning("Sparse search failed: %s", self.last_sparse_error)

        # Plan-2026-04-29 literature-acquisition Phase 1 / Task 7:
        # gate dense leg on policy. local-only / cached stages skip the
        # embedding endpoint entirely.
        dense_hits: list[PassageHit] = []
        dense_status: str | None = None  # set by policy gates
        if not self._policy.is_leg_enabled("rag_dense"):
            dense_status = "disabled"
            self.last_status = RAG_STATUS_SPARSE_ONLY_DENSE_DISABLED
        elif self._policy.is_cache_only():
            # Phase 2 will add a dense query cache. Until then, "cached"
            # means refuse new network calls.
            dense_status = "refused"
            self.last_status = RAG_STATUS_SPARSE_ONLY_DENSE_DISABLED
        elif self._policy.allows_network("rag_dense"):
            try:
                dense_hits = self._dense.search(
                    query, top_k=fetch_k, min_score=dense_min_score,
                    organ=organ, task_type=task_type,
                )
            except Exception as e:
                self.last_dense_error = f"{type(e).__name__}: {str(e)[:200]}"
                logger.warning(
                    "Dense search failed (degrading to sparse-only): %s",
                    self.last_dense_error,
                )
                if self._policy.should_fail_hard():
                    raise NetworkUnavailableError(
                        f"RAG dense retrieval failed (policy.stage="
                        f"{self._policy.stage}): {self.last_dense_error}"
                    ) from e

        # If a policy gate was active, network status is decided already.
        # Otherwise compute status from which legs returned hits.
        if dense_status is not None:
            self.last_network_status = NetworkLegStatus(
                leg="rag_dense", state=dense_status,
            )
        else:
            if self.last_sparse_error and self.last_dense_error:
                self.last_status = RAG_STATUS_UNAVAILABLE
            elif self.last_dense_error:
                self.last_status = RAG_STATUS_SPARSE_ONLY_DENSE_UNAVAILABLE
            elif self.last_sparse_error:
                self.last_status = RAG_STATUS_DENSE_ONLY_SPARSE_UNAVAILABLE
            elif sparse_hits and dense_hits:
                self.last_status = RAG_STATUS_HYBRID
            elif sparse_hits:
                self.last_status = RAG_STATUS_SPARSE_ONLY
            elif dense_hits:
                self.last_status = "dense_only"
            else:
                self.last_status = RAG_STATUS_EMPTY

            # Network status for the dense leg.
            if self.last_dense_error:
                state = "error"
            elif dense_hits:
                state = "ok"
            else:
                state = "ok"  # ran cleanly, just no hits
            self.last_network_status = NetworkLegStatus(
                leg="rag_dense", state=state,
                provider="dense",
                count=len(dense_hits),
                error=self.last_dense_error,
            )

        return _reciprocal_rank_fusion(
            sparse_hits, dense_hits,
            sparse_weight=self._sparse_weight,
            dense_weight=self._dense_weight,
            top_k=top_k,
        )


def _reciprocal_rank_fusion(
    sparse_hits: list[PassageHit],
    dense_hits: list[PassageHit],
    sparse_weight: float = 0.5,
    dense_weight: float = 0.5,
    top_k: int = 5,
    k: int = 60,
) -> list[PassageHit]:
    """Merge two ranked lists using Reciprocal Rank Fusion (RRF).

    RRF score = sum(weight / (k + rank)) across lists.
    """
    scores: dict[str, float] = {}
    hit_map: dict[str, PassageHit] = {}
    sparse_scores: dict[str, float] = {}
    dense_scores: dict[str, float] = {}

    for rank, hit in enumerate(sparse_hits):
        rrf = sparse_weight / (k + rank + 1)
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + rrf
        sparse_scores[hit.chunk_id] = hit.sparse_score
        if hit.chunk_id not in hit_map:
            hit_map[hit.chunk_id] = hit

    for rank, hit in enumerate(dense_hits):
        rrf = dense_weight / (k + rank + 1)
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + rrf
        dense_scores[hit.chunk_id] = hit.dense_score
        if hit.chunk_id not in hit_map:
            hit_map[hit.chunk_id] = hit

    # Sort by fused score
    sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:top_k]

    results = []
    for chunk_id in sorted_ids:
        hit = hit_map[chunk_id]
        results.append(PassageHit(
            paper_id=hit.paper_id,
            chunk_id=chunk_id,
            text=hit.text,
            score=scores[chunk_id],
            sparse_score=sparse_scores.get(chunk_id, 0.0),
            dense_score=dense_scores.get(chunk_id, 0.0),
            page=hit.page,
            section=hit.section,
        ))
    return results
