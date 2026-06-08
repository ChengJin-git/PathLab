"""Search for papers online and optionally save to the local literature store.

Usage:
    # Search and display results
    python -m pathscientist.literature_search "TransMIL attention MIL"

    # Search with more results
    python -m pathscientist.literature_search "UNI foundation model" --top-k 10

    # Save found papers to the local LiteratureStore
    python -m pathscientist.literature_search "TransMIL" --save

    # Save AND ingest into RAG corpus (chunks + sparse + dense)
    python -m pathscientist.literature_search "TransMIL" --save --ingest-to-rag

Environment variables (used as defaults):
    PATHSCIENTIST_BASE_DIR
    PATHSCIENTIST_LITERATURE_ONLINE_PROVIDER
    PATHSCIENTIST_LITERATURE_ONLINE_PROVIDERS
    PATHSCIENTIST_LITERATURE_ONLINE_TIMEOUT
    PATHSCIENTIST_RAG_EMBEDDING_MODEL
    PATHSCIENTIST_RAG_EMBEDDING_BASE_URL
    PATHSCIENTIST_RAG_EMBEDDING_API_KEY
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import DEFAULT_LITERATURE_ONLINE_PROVIDERS, parse_provider_list
from .literature.online_clients import create_online_client
from .literature.types import PaperRecord

logger = logging.getLogger("pathscientist.literature_search")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search for papers online and optionally save to local store / RAG corpus",
    )
    parser.add_argument("query", help="Search query (e.g. 'TransMIL attention MIL pathology')")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results (default: 5)")
    parser.add_argument("--provider", default="", help="Single provider override")
    parser.add_argument(
        "--providers",
        default=os.environ.get("PATHSCIENTIST_LITERATURE_ONLINE_PROVIDERS", ""),
        help="Comma-separated providers, e.g. openalex,europepmc,semantic_scholar,pubmed",
    )
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("PATHSCIENTIST_LITERATURE_ONLINE_TIMEOUT", "15")))
    parser.add_argument("--venue", default="", help="Filter by venue/journal (e.g. 'Nature', 'CVPR', 'Medical Image Analysis')")
    parser.add_argument("--year", default="", help="Filter by year or range (e.g. '2024', '2022-2025')")
    parser.add_argument("--min-citations", type=int, default=0, help="Minimum citation count (e.g. 10)")
    parser.add_argument("--save", action="store_true", help="Save found papers to local LiteratureStore")
    parser.add_argument("--ingest-to-rag", action="store_true", help="Also generate RAG chunks + rebuild indexes (implies --save)")
    parser.add_argument("--base-dir", default=os.environ.get("PATHSCIENTIST_BASE_DIR", "/project/vcompath/storage/ywangrm/tmp/pathscientist"))
    parser.add_argument("--embedding-model", default=os.environ.get("PATHSCIENTIST_RAG_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"))
    parser.add_argument("--embedding-base-url", default=os.environ.get("PATHSCIENTIST_RAG_EMBEDDING_BASE_URL", "http://dgx-24.cm.cluster:9001/v1"))
    parser.add_argument("--embedding-api-key", default=os.environ.get("PATHSCIENTIST_RAG_EMBEDDING_API_KEY", "sk-pathlab"))
    return parser.parse_args(argv)


def search_papers(
    query: str,
    provider: str = "openalex",
    providers: list[str] | str | None = None,
    top_k: int = 5,
    timeout: int = 15,
    venue: str = "",
    year_min: int | None = None,
    year_max: int | None = None,
    min_citations: int = 0,
) -> list[PaperRecord]:
    """Search for papers using one or more online providers."""
    provider_names = _provider_names(provider=provider, providers=providers)
    papers: list[PaperRecord] = []
    seen: set[str] = set()
    for provider_name in provider_names:
        client = create_online_client(provider=provider_name, timeout=timeout)
        fetched = client.search(
            query, top_k=top_k,
            venue=venue or None,
            year_min=year_min,
            year_max=year_max,
            min_citations=min_citations or None,
        )
        for paper in fetched:
            keys = _paper_keys(paper)
            if keys.isdisjoint(seen):
                papers.append(paper)
                seen.update(keys)
                if len(papers) >= top_k:
                    return papers
    return papers


def _provider_names(provider: str, providers: list[str] | str | None) -> list[str]:
    if providers:
        if isinstance(providers, str):
            return parse_provider_list(providers)
        return parse_provider_list(",".join(providers))
    return parse_provider_list(provider)


def _paper_keys(paper: PaperRecord) -> set[str]:
    keys = {paper.paper_id}
    if paper.url:
        keys.add(paper.url.rstrip("/").lower())
    for alias in getattr(paper, "aliases", []) or []:
        if alias:
            keys.add(str(alias).strip().lower())
    if paper.title and paper.year:
        keys.add(f"{paper.title.strip().lower()}:{paper.year}")
    return {key for key in keys if key}


def save_papers(papers: list[PaperRecord], base_dir: str) -> int:
    """Save papers to the local LiteratureStore. Returns count saved."""
    from .literature.store import LiteratureStore

    lit_dir = Path(base_dir) / "literature"
    store = LiteratureStore(lit_dir)
    saved = 0
    for paper in papers:
        try:
            store.add(paper)
            saved += 1
        except Exception as e:
            logger.warning(f"Failed to save {paper.paper_id}: {e}")
    return saved


def ingest_papers_to_rag(
    papers: list[PaperRecord],
    base_dir: str,
    embedding_model: str,
    embedding_base_url: str,
    embedding_api_key: str,
) -> dict:
    """Generate RAG chunks from papers and rebuild indexes."""
    from .literature.chunk_store import ChunkStore
    from .literature.ingest import chunks_from_paper_metadata
    from .rag_ingest import _rebuild_indexes

    lit_dir = Path(base_dir) / "literature"
    chunk_store = ChunkStore(lit_dir)

    total_chunks = 0
    for paper in papers:
        chunks = chunks_from_paper_metadata(paper)
        if chunks:
            chunk_store.save_chunks(paper.paper_id, chunks)
            total_chunks += len(chunks)

    sparse_count, dense_count, dense_dim = _rebuild_indexes(
        base_dir, chunk_store,
        embedding_model=embedding_model,
        embedding_base_url=embedding_base_url,
        embedding_api_key=embedding_api_key,
    )

    return {
        "chunks_added": total_chunks,
        "sparse_count": sparse_count,
        "dense_count": dense_count,
        "dense_dim": dense_dim,
    }


def parse_year_range(year_str: str) -> tuple[int | None, int | None]:
    """Parse year string: '2024' → (2024, 2024), '2022-2025' → (2022, 2025), '' → (None, None)."""
    if not year_str:
        return None, None
    if "-" in year_str:
        parts = year_str.split("-", 1)
        return int(parts[0]), int(parts[1])
    y = int(year_str)
    return y, y


def print_results(papers: list[PaperRecord]) -> None:
    """Pretty-print search results."""
    if not papers:
        print("No papers found.")
        return

    print(f"\nFound {len(papers)} paper(s):\n")
    print(f"{'#':>3}  {'Year':>4}  {'Title':<55}  {'Venue':<20}  {'ID'}")
    print(f"{'─'*3}  {'─'*4}  {'─'*55}  {'─'*20}  {'─'*30}")
    for i, p in enumerate(papers, 1):
        title = p.title[:53] + ".." if len(p.title) > 55 else p.title
        venue = (p.venue or "-")[:20]
        print(f"{i:>3}  {p.year:>4}  {title:<55}  {venue:<20}  {p.paper_id}")

    # Show abstracts
    print()
    for i, p in enumerate(papers, 1):
        if p.abstract:
            abstract = p.abstract[:200] + "..." if len(p.abstract) > 200 else p.abstract
            print(f"  [{i}] {abstract}")
    print()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    if args.ingest_to_rag:
        args.save = True  # ingest implies save

    # Parse year filter
    year_min, year_max = parse_year_range(args.year)

    # Search
    filter_desc = []
    if args.venue:
        filter_desc.append(f"venue={args.venue}")
    if args.year:
        filter_desc.append(f"year={args.year}")
    if args.min_citations:
        filter_desc.append(f"citations>={args.min_citations}")
    filter_str = f" [{', '.join(filter_desc)}]" if filter_desc else ""
    provider_names = parse_provider_list(
        args.providers
        or args.provider
        or os.environ.get("PATHSCIENTIST_LITERATURE_ONLINE_PROVIDER", "")
        or DEFAULT_LITERATURE_ONLINE_PROVIDERS
    )
    logger.info(f"Searching {','.join(provider_names)} for: {args.query}{filter_str}")

    papers = search_papers(
        args.query, provider=args.provider, providers=provider_names, top_k=args.top_k, timeout=args.timeout,
        venue=args.venue, year_min=year_min, year_max=year_max, min_citations=args.min_citations,
    )

    if not papers:
        print("No papers found.")
        return 0

    print_results(papers)

    # Save
    if args.save:
        saved = save_papers(papers, args.base_dir)
        print(f"Saved {saved} paper(s) to local store ({args.base_dir}/literature/)")

    # Ingest to RAG
    if args.ingest_to_rag:
        logger.info("Ingesting papers into RAG corpus...")
        stats = ingest_papers_to_rag(
            papers, args.base_dir,
            embedding_model=args.embedding_model,
            embedding_base_url=args.embedding_base_url,
            embedding_api_key=args.embedding_api_key,
        )
        print(f"RAG ingest: {stats['chunks_added']} chunks, "
              f"sparse={stats['sparse_count']}, dense={stats['dense_count']}×{stats['dense_dim']}d")

    return 0


if __name__ == "__main__":
    sys.exit(main())
