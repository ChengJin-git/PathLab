"""Pre-build the RAG corpus (chunks + sparse index + dense embedding index).

Usage:
    # Incremental build — only new/changed files get re-ingested/re-embedded
    python -m pathscientist.rag_ingest --corpus-dir /path/to/papers

    # Force rebuild from scratch (clears chunks, sparse, dense)
    python -m pathscientist.rag_ingest --corpus-dir /path/to/papers --force

    # Show current index status without ingesting
    python -m pathscientist.rag_ingest --status

    # Override embedding model / endpoint
    python -m pathscientist.rag_ingest --corpus-dir /path/to/papers \\
        --embedding-model Qwen/Qwen3-Embedding-8B \\
        --embedding-base-url http://dgx-24.cm.cluster:9001/v1

Environment variables (used as defaults):
    PATHSCIENTIST_BASE_DIR
    PATHSCIENTIST_RAG_CORPUS_DIR
    PATHSCIENTIST_RAG_EMBEDDING_MODEL
    PATHSCIENTIST_RAG_EMBEDDING_BASE_URL
    PATHSCIENTIST_RAG_EMBEDDING_API_KEY
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from .literature.chunk_store import ChunkStore
from .literature.embeddings import (
    DEFAULT_EMBEDDING_API_KEY,
    DEFAULT_EMBEDDING_BASE_URL,
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingIndex,
)
from .literature.ingest import (
    IngestManifest,
    chunks_from_paper_metadata,
    ingest_document,
)
from .literature.sparse_index import SparseChunkIndex
from .runtime.session import DEFAULT_BASE_DIR

logger = logging.getLogger("pathscientist.rag_ingest")


SUPPORTED_SUFFIXES = {".txt", ".md", ".rst", ".pdf"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pre-build the PathScientist RAG corpus (chunks + sparse + dense indexes)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--corpus-dir", default=os.environ.get("PATHSCIENTIST_RAG_CORPUS_DIR", ""),
        help="Directory of local papers (.txt/.md/.pdf). Required unless --status is set.",
    )
    parser.add_argument(
        "--base-dir", default=os.environ.get("PATHSCIENTIST_BASE_DIR", DEFAULT_BASE_DIR),
        help="PathScientist base directory (literature/ will be created inside).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Clear all chunks + sparse + dense indexes and rebuild from scratch.",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Print current index status (paper count, chunk count, dense dims) and exit.",
    )
    parser.add_argument(
        "--from-seed-data", action="store_true",
        help="Bootstrap RAG indexes from the 14 curated seed papers (title+abstract+baselines). "
             "Can be combined with --corpus-dir to also ingest user papers.",
    )
    parser.add_argument(
        "--embedding-model", default=os.environ.get("PATHSCIENTIST_RAG_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        help="Embedding model name.",
    )
    parser.add_argument(
        "--embedding-base-url", default=os.environ.get("PATHSCIENTIST_RAG_EMBEDDING_BASE_URL", DEFAULT_EMBEDDING_BASE_URL),
        help="OpenAI-compatible embedding endpoint base URL.",
    )
    parser.add_argument(
        "--embedding-api-key", default=os.environ.get("PATHSCIENTIST_RAG_EMBEDDING_API_KEY", DEFAULT_EMBEDDING_API_KEY),
        help="API key for the embedding endpoint.",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=300,
        help="Words per chunk (default: 300).",
    )
    parser.add_argument(
        "--chunk-overlap", type=int, default=50,
        help="Word overlap between chunks (default: 50).",
    )
    return parser.parse_args(argv)


def _lit_dir(base_dir: str) -> Path:
    return Path(base_dir) / "literature"


def print_status(base_dir: str) -> int:
    """Print current index status without modifying anything."""
    lit_dir = _lit_dir(base_dir)
    chunk_store = ChunkStore(lit_dir)
    paper_ids = chunk_store.list_paper_ids()
    total_chunks = sum(1 for _ in chunk_store.iter_all_chunks())

    sparse_db_path = lit_dir / "corpus" / "sparse" / "fts.db"
    sparse_count = 0
    if sparse_db_path.exists():
        try:
            sparse_index = SparseChunkIndex(sparse_db_path)
            sparse_count = sparse_index.count()
            sparse_index.close()
        except Exception as e:
            logger.warning(f"Sparse index check failed: {e}")

    dense_dir = lit_dir / "corpus" / "dense"
    dense_status = "not built"
    if (dense_dir / "embeddings.npy").exists():
        try:
            import json
            meta_path = dense_dir / "metadata.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                dense_status = f"{meta.get('count', '?')} chunks × {meta.get('dimension', '?')}d ({meta.get('model_name', '?')})"
            else:
                dense_status = "built (no metadata)"
        except Exception as e:
            logger.warning(f"Dense index check failed: {e}")

    print(f"Literature dir: {lit_dir}")
    print(f"Papers ingested:  {len(paper_ids)}")
    print(f"Total chunks:     {total_chunks}")
    print(f"Sparse index:     {sparse_count} rows")
    print(f"Dense index:      {dense_status}")
    if paper_ids:
        print(f"Paper IDs:        {', '.join(paper_ids[:10])}" + (f" (+{len(paper_ids)-10} more)" if len(paper_ids) > 10 else ""))
    return 0


def clear_indexes(base_dir: str) -> None:
    """Remove all chunks, sparse, dense, and ingest manifest."""
    lit_dir = _lit_dir(base_dir)
    corpus_dir = lit_dir / "corpus"
    if corpus_dir.exists():
        shutil.rmtree(corpus_dir)
        logger.info(f"Cleared {corpus_dir}")


def _rebuild_indexes(
    base_dir: str,
    chunk_store: ChunkStore,
    embedding_model: str,
    embedding_base_url: str,
    embedding_api_key: str,
) -> tuple[int, int, int]:
    """Rebuild sparse + dense indexes from the current chunk store state.

    Returns (sparse_count, dense_count, dense_dim).
    """
    lit_dir = _lit_dir(base_dir)

    sparse_db_path = lit_dir / "corpus" / "sparse" / "fts.db"
    sparse_index = SparseChunkIndex(sparse_db_path)
    sparse_count = sparse_index.rebuild(chunk_store)
    sparse_index.close()
    logger.info(f"Sparse index rebuilt: {sparse_count} chunks")

    all_chunks = list(chunk_store.iter_all_chunks())
    dense_count = 0
    dense_dim = 0
    if all_chunks:
        dense_index = EmbeddingIndex(
            lit_dir / "corpus" / "dense",
            model_name=embedding_model,
            base_url=embedding_base_url,
            api_key=embedding_api_key,
        )
        logger.info(f"Building dense index with {embedding_model} ({len(all_chunks)} chunks)...")
        dense_count = dense_index.build(all_chunks)
        if dense_index._matrix is not None:
            dense_dim = int(dense_index._matrix.shape[1])
        logger.info(f"Dense index built: {dense_count} vectors × {dense_dim}d")

    return sparse_count, dense_count, dense_dim


def ingest_from_seed_data(
    base_dir: str,
    embedding_model: str,
    embedding_base_url: str,
    embedding_api_key: str,
    rebuild_indexes: bool = True,
) -> dict:
    """Bootstrap chunks from the 14 curated seed papers (title + abstract + baselines).

    Loads the LiteratureStore (seeding it from pathology_papers.json if empty),
    turns each PaperRecord into 2-3 synthetic chunks, and saves them via
    ChunkStore. Optionally rebuilds sparse + dense indexes afterwards.
    """
    from .literature.seed import seed_literature
    from .literature.store import LiteratureStore

    t0 = time.time()
    lit_dir = _lit_dir(base_dir)
    store = LiteratureStore(lit_dir)
    if not store.list_papers():
        logger.info("Literature store empty — seeding from pathology_papers.json")
        seed_literature(store)

    papers = store.list_papers()
    if not papers:
        raise RuntimeError("Literature store still empty after seed attempt")

    chunk_store = ChunkStore(lit_dir)

    papers_ingested = 0
    total_chunks = 0
    for paper in papers:
        chunks = chunks_from_paper_metadata(paper)
        if chunks:
            chunk_store.save_chunks(paper.paper_id, chunks)
            papers_ingested += 1
            total_chunks += len(chunks)
            logger.info(f"  seeded: {paper.paper_id} -> {len(chunks)} chunks")

    sparse_count = 0
    dense_count = 0
    dense_dim = 0
    if rebuild_indexes:
        sparse_count, dense_count, dense_dim = _rebuild_indexes(
            base_dir, chunk_store,
            embedding_model=embedding_model,
            embedding_base_url=embedding_base_url,
            embedding_api_key=embedding_api_key,
        )

    return {
        "papers_ingested": papers_ingested,
        "papers_skipped": 0,
        "chunks_total": total_chunks,
        "sparse_count": sparse_count,
        "dense_count": dense_count,
        "dense_dim": dense_dim,
        "duration_sec": round(time.time() - t0, 2),
    }


def ingest_corpus(
    base_dir: str,
    corpus_dir: str,
    embedding_model: str,
    embedding_base_url: str,
    embedding_api_key: str,
    chunk_size: int = 300,
    chunk_overlap: int = 50,
) -> dict:
    """Build chunks + sparse + dense indexes from a corpus directory.

    Returns a stats dict with keys: papers_ingested, chunks_total, dense_dim, duration_sec.
    """
    t0 = time.time()
    lit_dir = _lit_dir(base_dir)
    corpus_path = Path(corpus_dir)
    if not corpus_path.is_dir():
        raise FileNotFoundError(f"Corpus directory not found: {corpus_path}")

    chunk_store = ChunkStore(lit_dir)
    manifest_path = lit_dir / "corpus" / "manifests" / "ingest_state.json"
    manifest = IngestManifest(manifest_path)

    # Step 1: ingest documents incrementally
    logger.info(f"Scanning corpus: {corpus_path}")
    papers_ingested = 0
    papers_skipped = 0
    for doc_path in sorted(corpus_path.iterdir()):
        if doc_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        paper_id = doc_path.stem
        if not manifest.should_reingest(doc_path):
            papers_skipped += 1
            logger.debug(f"  skip (unchanged): {doc_path.name}")
            continue
        try:
            chunks = ingest_document(
                paper_id=paper_id, path=doc_path,
                chunk_size=chunk_size, chunk_overlap=chunk_overlap,
            )
            if chunks:
                chunk_store.save_chunks(paper_id, chunks)
                manifest.record(doc_path)
                papers_ingested += 1
                logger.info(f"  ingested: {doc_path.name} -> {len(chunks)} chunks")
            else:
                logger.warning(f"  no chunks extracted from {doc_path.name}")
        except Exception as e:
            logger.warning(f"  failed to ingest {doc_path.name}: {e}")

    logger.info(f"Ingest: {papers_ingested} new/changed, {papers_skipped} skipped")

    # Rebuild sparse + dense indexes
    sparse_count, dense_count, dense_dim = _rebuild_indexes(
        base_dir, chunk_store,
        embedding_model=embedding_model,
        embedding_base_url=embedding_base_url,
        embedding_api_key=embedding_api_key,
    )

    return {
        "papers_ingested": papers_ingested,
        "papers_skipped": papers_skipped,
        "chunks_total": sum(1 for _ in chunk_store.iter_all_chunks()),
        "sparse_count": sparse_count,
        "dense_count": dense_count,
        "dense_dim": dense_dim,
        "duration_sec": round(time.time() - t0, 2),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.status:
        return print_status(args.base_dir)

    if not args.corpus_dir and not args.from_seed_data:
        print(
            "ERROR: --corpus-dir or --from-seed-data is required "
            "(or set PATHSCIENTIST_RAG_CORPUS_DIR)",
            file=sys.stderr,
        )
        return 2

    if args.force:
        logger.info("Force mode: clearing existing indexes")
        clear_indexes(args.base_dir)

    stats = {
        "papers_ingested": 0,
        "papers_skipped": 0,
        "chunks_total": 0,
        "sparse_count": 0,
        "dense_count": 0,
        "dense_dim": 0,
        "duration_sec": 0.0,
    }

    try:
        # Step 1: seed-data bootstrap (optional)
        if args.from_seed_data:
            # Defer index rebuild if we're also ingesting a corpus afterwards
            defer_rebuild = bool(args.corpus_dir)
            seed_stats = ingest_from_seed_data(
                base_dir=args.base_dir,
                embedding_model=args.embedding_model,
                embedding_base_url=args.embedding_base_url,
                embedding_api_key=args.embedding_api_key,
                rebuild_indexes=not defer_rebuild,
            )
            for k in ("papers_ingested", "chunks_total", "sparse_count",
                      "dense_count", "dense_dim", "duration_sec"):
                stats[k] += seed_stats[k] if isinstance(seed_stats[k], (int, float)) else 0
            if seed_stats["dense_dim"]:
                stats["dense_dim"] = seed_stats["dense_dim"]

        # Step 2: user corpus ingest (optional)
        if args.corpus_dir:
            corpus_stats = ingest_corpus(
                base_dir=args.base_dir,
                corpus_dir=args.corpus_dir,
                embedding_model=args.embedding_model,
                embedding_base_url=args.embedding_base_url,
                embedding_api_key=args.embedding_api_key,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
            )
            stats["papers_ingested"] += corpus_stats["papers_ingested"]
            stats["papers_skipped"] += corpus_stats["papers_skipped"]
            stats["chunks_total"] = corpus_stats["chunks_total"]
            stats["sparse_count"] = corpus_stats["sparse_count"]
            stats["dense_count"] = corpus_stats["dense_count"]
            stats["dense_dim"] = corpus_stats["dense_dim"]
            stats["duration_sec"] += corpus_stats["duration_sec"]
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print()
    print("=" * 60)
    print("RAG corpus ingestion complete")
    print("=" * 60)
    sources = []
    if args.from_seed_data:
        sources.append("seed metadata")
    if args.corpus_dir:
        sources.append(f"corpus dir {args.corpus_dir}")
    if sources:
        print(f"Sources:          {', '.join(sources)}")
    print(f"Papers ingested:  {stats['papers_ingested']}")
    if stats['papers_skipped']:
        print(f"Papers skipped:   {stats['papers_skipped']} (unchanged)")
    print(f"Total chunks:     {stats['chunks_total']}")
    print(f"Sparse index:     {stats['sparse_count']} rows")
    print(f"Dense index:      {stats['dense_count']} × {stats['dense_dim']}d")
    print(f"Embedding model:  {args.embedding_model}")
    print(f"Duration:         {round(stats['duration_sec'], 2)}s")
    print()
    print(f"Location: {_lit_dir(args.base_dir)}/corpus/")
    print()
    print("To use with a research session:")
    if args.corpus_dir:
        print(f"  bash start.sh --rag --rag-corpus-dir {args.corpus_dir}")
    else:
        print("  bash start.sh --rag")
    return 0


if __name__ == "__main__":
    sys.exit(main())
