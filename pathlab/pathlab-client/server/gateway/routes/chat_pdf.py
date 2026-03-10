"""
PDF parsing utilities for AI chat.

When Exa search returns PDF links (e.g., arXiv papers),
this module downloads, parses, and summarizes the content for the AI agent.

Features:
- Supports 30+ academic journal URL patterns
- File-based cache with 7-day TTL
- Reference card generation for AI responses
"""
import json
import multiprocessing
import os
import re
import shutil
import tempfile
import asyncio
import hashlib
import uuid
import gc
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from datetime import datetime, timedelta
import httpx

from ..dependencies import logger
from backend.common.config import Config


_pdf_cache_dir: Path | None = None
PDF_CACHE_TTL_DAYS = 7
PDF_PARSE_METHOD_DOCLING = "docling"
PDF_PARSE_METHOD_PYMUPDF = "pymupdf"
PDF_PARSE_METHOD_FAILED = "parse_failed"
DOCLING_CACHE_SUFFIX = ".docling.md"
PYMUPDF_CACHE_SUFFIX = ".md"
STRUCTURED_CACHE_SUFFIX = ".structured.json"
STRUCTURED_SCHEMA_VERSION = 1
PdfParseMethod = Literal["docling", "pymupdf", "parse_failed"]


@dataclass(frozen=True, slots=True)
class ParsedPdfResult:
    markdown: str
    parse_method: PdfParseMethod
    page_count: int
    structured_content: dict[str, Any]


HIGH_QUALITY_CACHE_SUFFIXES: tuple[tuple[str, str], ...] = (
    (DOCLING_CACHE_SUFFIX, PDF_PARSE_METHOD_DOCLING),
)
CACHED_MARKDOWN_CANDIDATES: tuple[tuple[str, str], ...] = (
    *HIGH_QUALITY_CACHE_SUFFIXES,
    (PYMUPDF_CACHE_SUFFIX, PDF_PARSE_METHOD_PYMUPDF),
)
CACHE_ARTEFACT_SUFFIXES: tuple[str, ...] = (
    '.pdf',
    '.pdf.partial',
    '.json',
    STRUCTURED_CACHE_SUFFIX,
    *(suffix for suffix, _method in CACHED_MARKDOWN_CANDIDATES),
)
DOCLING_SUBPROCESS_JOIN_TIMEOUT_SECONDS = 5.0
_docling_upgrade_tasks: dict[str, asyncio.Task[None]] = {}


def _get_pdf_cache_dir() -> Path:
    global _pdf_cache_dir
    if _pdf_cache_dir is None:
        uploads_dir = Config.get_uploads_dir()
        _pdf_cache_dir = uploads_dir / "pdf_cache"
        _pdf_cache_dir.mkdir(parents=True, exist_ok=True)
    return _pdf_cache_dir


def get_pdf_image_path(url_hash: str, filename: str) -> Path:
    """Return the persistent storage path for an extracted PDF image.

    Used by the /pdf-images/{url_hash}/{filename} HTTP endpoint to locate files.
    Images are stored at: pdf_cache/images/{url_hash}/{filename}

    Supports **fig-N** aliases: ``fig-1.jpg`` resolves to the 1st image
    (alphabetically sorted) in the directory.  This prevents 404 errors
    caused by LLMs hallucinating hash-based filenames.
    """
    images_dir = _get_pdf_cache_dir() / "images" / url_hash

    # ── fig-N alias resolution ────────────────────────────────────────────
    # Tolerant regex: accepts fig-3.jpg, fig-2d.png, fig-12a.jpg, etc.
    # LLMs often hallucinate sub-figure letters (a/b/c/d) or wrong extensions.
    # We extract only the leading digits as the figure number.
    fig_match = re.match(r'^fig-(\d+)[a-zA-Z]*\.[a-zA-Z]+$', filename)
    if fig_match:
        fig_num = int(fig_match.group(1))  # 1-based, letter suffix ignored
        if images_dir.is_dir():
            image_files = sorted(
                f for f in images_dir.iterdir()
                if f.is_file()
                and not f.name.startswith('fig-')
                and not f.name.startswith('_')
            )
            if 1 <= fig_num <= len(image_files):
                return image_files[fig_num - 1]
        # If alias can't be resolved, fall through to the literal path
        # (will result in a 404 at the endpoint level).

    return images_dir / filename


PDF_URL_PATTERNS = [
    r'\.pdf$',
    
    r'arxiv\.org/(pdf|abs)/',
    r'arxiv\.org/pdf/',
    r'openreview\.net/(pdf|forum|note)\?id=',
    
    r'ncbi\.nlm\.nih\.gov/pmc/articles/',
    r'pubmed\.ncbi\.nlm\.nih\.gov/',
    
    r'semanticscholar\.org/paper/',
    r's2-pdf\.s3\.amazonaws\.com/',
    
    r'aclanthology\.org/',
    
    r'ieeexplore\.ieee\.org/document/',
    
    r'dl\.acm\.org/doi/',
    
    r'link\.springer\.com/',
    r'springer\.com/content/pdf/',
    
    r'sciencedirect\.com/science/article/',
    r'elsevier\.com/',
    r'doi\.org/10\.(1016|1056|1002)/',
    
    r'nature\.com/articles/',
    r'nature\.com/reviews/',
    
    r'onlinelibrary\.wiley\.com/doi/',
    
    r'plos\.org/',
    r'journals\.plos\.org/',
    
    r'biorxiv\.org/content/',
    r'medrxiv\.org/content/',
    
    r'jamanetwork\.com/journals/',
    r'jamanetwork\.com/articlepdf/',
    
    r'nejm\.org/doi/',
    r'nejm\.org/doi/pdf/',
    r'mediacenteratypon\.nejmgroup-production\.org/.*\.pdf',
    
    r'thelancet\.com/journals/',
    r'thelancet\.com/article/',
    r'sciencedirect\.com/journal/the-lancet/',
    
    r'cell\.com/cell/',
    r'cell\.com/.*fulltext',
    
    r'science\.org/doi/',
    r'science\.org/doi/pdf/',
    
    r'cancer\.gov/',
    r'nejm\.org/',
    
    r'academic\.oup\.com/',
    r'oup\.com/',
    
    r'frontiersin\.org/articles/',
    
    r'mdpi\.com/',
    
    r'royalsocietypublishing\.org/doi/',
    
    r'pnas\.org/doi/',
    
    r'sciencemag\.org/',
]


def is_pdf_url(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for pattern in PDF_URL_PATTERNS:
        if re.search(pattern, url_lower):
            return True
    return False


def _get_url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _remove_cached_pdf_artifacts(url_hash: str, *, remove_vectorstore: bool = False) -> None:
    """Delete all persisted cache artifacts for a cached PDF hash."""
    cache_dir = _get_pdf_cache_dir()
    for suffix in CACHE_ARTEFACT_SUFFIXES:
        file_path = cache_dir / f"{url_hash}{suffix}"
        if file_path.exists():
            file_path.unlink()

    images_dir = cache_dir / "images" / url_hash
    if images_dir.exists() and images_dir.is_dir():
        shutil.rmtree(images_dir, ignore_errors=True)

    if remove_vectorstore:
        try:
            from .chat_pdf_vectorstore import delete_pdf_from_vectorstore
            delete_pdf_from_vectorstore(url_hash)
        except Exception as e:
            logger.error(f"Error cleaning vector store for {url_hash}: {e}")


def _get_cached_pdf(url: str) -> tuple[bytes, dict[str, Any], str | None, str | None] | None:
    """Returns (pdf_bytes, meta, cached_markdown_or_None, parse_method_or_None)."""
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        meta_file = cache_dir / f"{url_hash}.json"
        pdf_file = cache_dir / f"{url_hash}.pdf"

        if not meta_file.exists() or not pdf_file.exists():
            return None

        with open(meta_file, 'r') as f:
            meta = json.load(f)

        cached_time = datetime.fromisoformat(meta.get('cached_at', '2000-01-01'))
        if datetime.now() - cached_time > timedelta(days=PDF_CACHE_TTL_DAYS):
            logger.info(f"PDF cache expired for {url}")
            try:
                _remove_cached_pdf_artifacts(url_hash, remove_vectorstore=True)
            except Exception:
                pass
            return None

        pdf_bytes = pdf_file.read_bytes()

        # Prefer the highest-quality cached markdown; fall back to PyMuPDF.
        cached_md = None
        cached_md_method = None
        for suffix, method in CACHED_MARKDOWN_CANDIDATES:
            md_candidate = cache_dir / f"{url_hash}{suffix}"
            if md_candidate.exists():
                try:
                    cached_md = md_candidate.read_text(encoding='utf-8')
                    cached_md_method = method
                    if method == PDF_PARSE_METHOD_DOCLING:
                        logger.info(f"PDF cache: using high-quality parsed result for {url}")
                    break
                except Exception:
                    pass

        return pdf_bytes, meta, cached_md, cached_md_method
    except Exception as e:
        logger.error(f"Error reading PDF cache: {e}")
        return None


def _save_pdf_to_cache(url: str, pdf_bytes: bytes, title: str = "", markdown: str = "") -> None:
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        meta_file = cache_dir / f"{url_hash}.json"
        pdf_file = cache_dir / f"{url_hash}.pdf"

        partial_file = cache_dir / f"{url_hash}.pdf.partial"
        partial_file.write_bytes(pdf_bytes)
        partial_file.rename(pdf_file)

        meta = {
            'url': url,
            'title': title,
            'cached_at': datetime.now().isoformat(),
            'size_bytes': len(pdf_bytes),
            'parse_method': None,
            'structured_parse_method': None,
            'structured_parse_ready': False,
            'high_quality_parse_pending': False,
            'high_quality_parse_ready': False,
        }
        with open(meta_file, 'w') as f:
            json.dump(meta, f, indent=2)

        # Also cache parsed markdown if provided
        if markdown:
            md_file = cache_dir / f"{url_hash}.md"
            md_file.write_text(markdown, encoding='utf-8')

        logger.info(f"Cached PDF: {url} ({len(pdf_bytes)} bytes)" + (" + markdown" if markdown else ""))
    except Exception as e:
        logger.error(f"Error saving PDF to cache: {e}")


def _extract_page_count(markdown: str) -> int:
    """Return the total page count from markdown with '--- Page X ---' markers.

    Scans all '--- Page X ---' markers and returns the maximum X found, which
    equals the total number of pages parsed.  Returns 0 if no markers are found.
    """
    page_nums = [int(m) for m in re.findall(r'--- Page (\d+) ---', markdown)]
    return max(page_nums) if page_nums else 0


def _update_meta_fields(url: str, **fields: Any) -> None:
    """Best-effort update for cached PDF metadata fields."""
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        meta_file = cache_dir / f"{url_hash}.json"
        if not meta_file.exists():
            return
        with open(meta_file, 'r') as f:
            meta = json.load(f)
        for key, value in fields.items():
            if value is not None:
                meta[key] = value
        with open(meta_file, 'w') as f:
            json.dump(meta, f, indent=2)
    except Exception as e:
        logger.error(f"Error updating meta for {url}: {e}")


def _update_meta_with_parse_info(url: str, page_count: int, parse_method: str) -> None:
    """Update the cached JSON metadata with page_count and parse_method.

    This is a best-effort update: failures are logged but never raised so that
    the caller (cache-save path) is never disrupted.
    """
    _update_meta_fields(url, page_count=page_count, parse_method=parse_method)


def _update_meta_academic_flag(url: str, is_academic: bool) -> None:
    """Persist the is_academic flag to the cached JSON metadata.

    Called after `is_academic_content()` so that follow-up questions (which
    rebuild context via `_build_merged_pdf_context`) can read it from cache
    without re-running heuristic detection.
    """
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        meta_file = cache_dir / f"{url_hash}.json"
        if not meta_file.exists():
            return
        with open(meta_file, 'r') as f:
            meta = json.load(f)
        meta['is_academic'] = is_academic
        with open(meta_file, 'w') as f:
            json.dump(meta, f, indent=2)
    except Exception as e:
        logger.error(f"Error updating academic flag for {url}: {e}")


def _save_structured_to_cache(url: str, structured_content: dict[str, Any]) -> None:
    """Persist the normalized Document Graph / Block Graph sidecar."""
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        structured_file = cache_dir / f"{url_hash}{STRUCTURED_CACHE_SUFFIX}"
        structured_file.write_text(
            json.dumps(structured_content, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
    except Exception as e:
        logger.error(f"Error saving structured cache for {url}: {e}")


def get_cached_structured_content(url: str) -> dict[str, Any] | None:
    """Return the cached normalized Document Graph / Block Graph for *url*."""
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        structured_file = cache_dir / f"{url_hash}{STRUCTURED_CACHE_SUFFIX}"
        if not structured_file.exists():
            return None
        return json.loads(structured_file.read_text(encoding='utf-8'))
    except Exception:
        return None


def _save_markdown_to_cache(
    url: str,
    markdown: str,
    paper_title: str = "",
    structured_content: dict[str, Any] | None = None,
    *,
    high_quality_pending: bool = False,
) -> None:
    """Save pymupdf-parsed markdown to cache (fast tier)."""
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        md_file = cache_dir / f"{url_hash}{PYMUPDF_CACHE_SUFFIX}"
        md_file.write_text(markdown, encoding='utf-8')
        page_count = _extract_page_count(markdown)
        _save_structured_to_cache(
            url,
            structured_content or _build_document_graph_from_markdown(markdown, PDF_PARSE_METHOD_PYMUPDF),
        )
        _update_meta_fields(
            url,
            page_count=page_count,
            parse_method=PDF_PARSE_METHOD_PYMUPDF,
            structured_parse_method=PDF_PARSE_METHOD_PYMUPDF,
            structured_parse_ready=True,
            high_quality_parse_pending=high_quality_pending,
            high_quality_parse_ready=False,
        )
        logger.info(f"Cached PyMuPDF markdown for {url} ({page_count} pages)")
        _trigger_vector_index(url_hash, markdown, paper_title, structured_content)
    except Exception as e:
        logger.error(f"Error saving markdown to cache: {e}")


def _has_docling_cache(url: str) -> bool:
    """Return True if a Docling high-quality result is already cached for this URL."""
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        return (cache_dir / f"{url_hash}{DOCLING_CACHE_SUFFIX}").exists()
    except Exception:
        return False


def _save_docling_to_cache(
    url: str,
    markdown: str,
    paper_title: str = "",
    structured_content: dict[str, Any] | None = None,
) -> None:
    """Save Docling high-quality parse result to cache."""
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        docling_file = cache_dir / f"{url_hash}{DOCLING_CACHE_SUFFIX}"
        docling_file.write_text(markdown, encoding='utf-8')
        page_count = _extract_page_count(markdown)
        _save_structured_to_cache(
            url,
            structured_content or _build_document_graph_from_markdown(markdown, PDF_PARSE_METHOD_DOCLING),
        )
        _update_meta_fields(
            url,
            page_count=page_count,
            parse_method=PDF_PARSE_METHOD_DOCLING,
            structured_parse_method=PDF_PARSE_METHOD_DOCLING,
            structured_parse_ready=True,
            high_quality_parse_pending=False,
            high_quality_parse_ready=True,
        )
        logger.info(f"Cached Docling markdown for {url} ({page_count} pages)")
        _trigger_vector_index(url_hash, markdown, paper_title, structured_content)
    except Exception as e:
        logger.error(f"Error saving Docling markdown to cache: {e}")


# ── Vector Index Helper ─────────────────────────────────────────────────────

def _trigger_vector_index(
    url_hash: str,
    markdown: str,
    paper_title: str,
    structured_content: dict[str, Any] | None = None,
) -> None:
    """Index PDF content into the vector store (best-effort, non-blocking)."""
    try:
        from .chat_pdf_vectorstore import index_pdf_to_vectorstore
        index_pdf_to_vectorstore(
            url_hash,
            markdown,
            paper_title or "Unknown",
            structured_content=structured_content,
        )
    except Exception as e:
        logger.error(f"[VectorIndex] Failed to index {url_hash}: {e}")


# ── BM25 Page-Level Search ──────────────────────────────────────────────────

def _tokenize_for_search(text: str) -> list[str]:
    """Simple tokenizer for BM25 search. Handles English, numbers, CJK, Japanese, and Korean.

    - Lowercases all text
    - Keeps alphanumeric runs (e.g. ``bm25``, ``page3``) as single tokens
    - Splits each CJK / Hiragana / Katakana / Hangul character as an individual token
    """
    # CJK Unified + Extension A + Hiragana + Katakana + Hangul Syllables
    return re.findall(
        r'[a-z0-9]+|[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]',
        text.lower(),
    )


def _split_md_into_pages(markdown: str) -> list[tuple[int, str]]:
    """Split markdown by ``--- Page X ---`` markers into ``(page_num, content)`` pairs.

    Content before the first marker (if any) is assigned page number 0.
    """
    parts = re.split(r'--- Page (\d+) ---', markdown)
    pages: list[tuple[int, str]] = []
    if parts[0].strip():
        pages.append((0, parts[0].strip()))
    for i in range(1, len(parts), 2):
        page_num = int(parts[i])
        content = parts[i + 1] if i + 1 < len(parts) else ""
        if content.strip():
            pages.append((page_num, content.strip()))
    return pages


def _parse_markdown_table_rows(table_lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in table_lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and any(cell and set(cell) != {"-", ":"} for cell in cells):
            rows.append(cells)
    return rows


def _build_document_graph_from_markdown(markdown: str, parse_method: PdfParseMethod) -> dict[str, Any]:
    """Normalize markdown into a lightweight Document Graph / Block Graph sidecar."""
    page_entries = _split_md_into_pages(markdown)
    blocks: list[dict[str, Any]] = []
    section_nodes: list[dict[str, Any]] = []
    block_counter = 0

    def _next_block_id(prefix: str, page_num: int) -> str:
        nonlocal block_counter
        block_counter += 1
        return f"{prefix}-p{page_num}-{block_counter}"

    def _append_block(page_num: int, page_node: dict[str, Any], block_type: str, **payload: Any) -> None:
        block_id = _next_block_id(block_type, page_num)
        block = {
            "id": block_id,
            "type": block_type,
            "page": page_num,
            "parent_id": page_node["id"],
            **payload,
        }
        blocks.append(block)
        page_node["children"].append(block_id)

    for page_num, page_text in page_entries:
        page_node = {
            "id": f"page-{page_num}",
            "type": "section",
            "title": f"Page {page_num}",
            "page_start": page_num,
            "page_end": page_num,
            "children": [],
        }
        section_nodes.append(page_node)

        paragraph_buffer: list[str] = []
        table_buffer: list[str] = []
        equation_buffer: list[str] = []
        in_equation = False
        current_path: list[str] = []

        def _flush_paragraph() -> None:
            if not paragraph_buffer:
                return
            text = "\n".join(paragraph_buffer).strip()
            paragraph_buffer.clear()
            if text:
                _append_block(
                    page_num,
                    page_node,
                    "paragraph",
                    text=text,
                    section_path=current_path.copy(),
                )

        def _flush_table() -> None:
            if not table_buffer:
                return
            table_markdown = "\n".join(table_buffer).strip()
            rows = _parse_markdown_table_rows(table_buffer)
            table_buffer.clear()
            if table_markdown:
                _append_block(
                    page_num,
                    page_node,
                    "table",
                    markdown=table_markdown,
                    cells=rows,
                    caption="",
                    section_path=current_path.copy(),
                )

        def _flush_equation() -> None:
            if not equation_buffer:
                return
            latex = "\n".join(equation_buffer).strip()
            equation_buffer.clear()
            if latex:
                _append_block(
                    page_num,
                    page_node,
                    "equation",
                    latex=latex,
                    surrounding_text="",
                    section_path=current_path.copy(),
                )

        for raw_line in page_text.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()

            if stripped.startswith("$$"):
                _flush_paragraph()
                _flush_table()
                if in_equation and stripped != "$$":
                    equation_buffer.append(stripped)
                in_equation = not in_equation
                if not in_equation:
                    _flush_equation()
                continue

            if in_equation:
                equation_buffer.append(line)
                continue

            heading_match = re.match(r'^(#{1,6})\s+(.*)$', stripped)
            image_match = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)$', stripped)

            if not stripped:
                _flush_paragraph()
                _flush_table()
                continue

            if heading_match:
                _flush_paragraph()
                _flush_table()
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                current_path = current_path[: max(level - 1, 0)]
                current_path.append(title)
                _append_block(
                    page_num,
                    page_node,
                    "section",
                    text=title,
                    level=level,
                    section_path=current_path.copy(),
                )
                continue

            if image_match:
                _flush_paragraph()
                _flush_table()
                _append_block(
                    page_num,
                    page_node,
                    "figure",
                    image=image_match.group(2).strip(),
                    caption=image_match.group(1).strip(),
                    vision_summary="",
                    section_path=current_path.copy(),
                )
                continue

            if stripped.startswith("|") and stripped.endswith("|"):
                _flush_paragraph()
                table_buffer.append(stripped)
                continue

            if table_buffer:
                _flush_table()

            paragraph_buffer.append(stripped)

        _flush_paragraph()
        _flush_table()
        _flush_equation()

    return {
        "schema_version": STRUCTURED_SCHEMA_VERSION,
        "type": "document",
        "parse_method": parse_method,
        "page_count": _extract_page_count(markdown),
        "children": section_nodes,
        "blocks": blocks,
    }


def _to_parsed_pdf_result(markdown: str, parse_method: PdfParseMethod) -> ParsedPdfResult:
    structured_content = _build_document_graph_from_markdown(markdown, parse_method)
    return ParsedPdfResult(
        markdown=markdown,
        parse_method=parse_method,
        page_count=int(structured_content.get("page_count") or 0),
        structured_content=structured_content,
    )


def search_pdf_pages(
    markdown: str, query: str, top_k: int = 10,
) -> list[tuple[int, str, float]]:
    """BM25 page-level search over parsed PDF markdown.

    Returns up to *top_k* pages as ``(page_num, content, score)`` tuples
    sorted by descending BM25 score.  Pages with score == 0 are excluded.

    Self-contained implementation — no external dependencies required.
    """
    import math
    from collections import Counter

    pages = _split_md_into_pages(markdown)
    if not pages:
        return []

    query_tokens = _tokenize_for_search(query)
    if not query_tokens:
        return []

    # Tokenize every page once
    page_token_lists = [_tokenize_for_search(content) for _, content in pages]

    # BM25 hyper-parameters
    k1, b = 1.5, 0.75
    N = len(pages)
    avgdl = sum(len(tl) for tl in page_token_lists) / N if N > 0 else 1

    # Document frequency for each unique query term
    unique_qts = set(query_tokens)
    df: dict[str, int] = {qt: 0 for qt in unique_qts}
    for tl in page_token_lists:
        present = unique_qts & set(tl)
        for qt in present:
            df[qt] += 1

    # Score each page
    scored: list[tuple[int, str, float]] = []
    for idx, (page_num, content) in enumerate(pages):
        tf = Counter(page_token_lists[idx])
        dl = len(page_token_lists[idx])
        score = 0.0
        for qt in query_tokens:
            if qt not in tf:
                continue
            n_qt = df[qt]
            idf = math.log((N - n_qt + 0.5) / (n_qt + 0.5) + 1)
            score += idf * (tf[qt] * (k1 + 1)) / (tf[qt] + k1 * (1 - b + b * dl / avgdl))
        if score > 0:
            scored.append((page_num, content, score))

    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:top_k]


def get_cached_markdown(url: str) -> str | None:
    """Return the best available cached markdown for *url*, or ``None``.

    Prefers high-quality structured parses over PyMuPDF.
    """
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        for suffix, _method in CACHED_MARKDOWN_CANDIDATES:
            md_file = cache_dir / f"{url_hash}{suffix}"
            if md_file.exists():
                return md_file.read_text(encoding='utf-8')
        return None
    except Exception:
        return None


def invalidate_pdf_cache(url: str) -> None:
    """Remove all cache artefacts for *url*.

    Called when a PDF download or parse is interrupted mid-way (e.g. user
    clicked the stop button) to prevent corrupted / partial files from being
    served on the next request.
    """
    try:
        url_hash = _get_url_hash(url)
        _remove_cached_pdf_artifacts(url_hash, remove_vectorstore=True)
        logger.info(f"Invalidated PDF cache artefacts for {url}")
    except Exception as e:
        logger.error(f"Error invalidating PDF cache for {url}: {e}")


def get_cached_pdf_meta(url: str) -> dict[str, Any] | None:
    """Return the cached JSON metadata dict for *url*, or ``None``."""
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        meta_file = cache_dir / f"{url_hash}.json"
        if not meta_file.exists():
            return None
        with open(meta_file, 'r') as f:
            return json.load(f)
    except Exception:
        return None


async def _parse_pdf_with_docling_best_effort(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir: Path | None,
    images_url_prefix: str | None,
) -> ParsedPdfResult | None:
    """Run Docling via GPU queue when possible, otherwise CPU, and normalize the result."""
    docling_markdown = await _parse_pdf_with_docling_via_gpu_queue(
        pdf_bytes,
        max_pages,
        images_output_dir,
        images_url_prefix,
    )
    if docling_markdown is None:
        docling_markdown = await _parse_pdf_with_docling_on_cpu(
            pdf_bytes,
            max_pages,
            images_output_dir,
            images_url_prefix,
        )
    if docling_markdown is None:
        return None
    return _to_parsed_pdf_result(docling_markdown, PDF_PARSE_METHOD_DOCLING)


def _register_docling_upgrade_task(url_hash: str, task: asyncio.Task[None]) -> None:
    _docling_upgrade_tasks[url_hash] = task

    def _cleanup(completed_task: asyncio.Task[None]) -> None:
        current_task = _docling_upgrade_tasks.get(url_hash)
        if current_task is completed_task:
            _docling_upgrade_tasks.pop(url_hash, None)
        try:
            completed_task.result()
        except asyncio.CancelledError:
            logger.info(f"Background Docling upgrade cancelled for {url_hash}")
        except Exception as e:
            logger.error(f"Background Docling upgrade failed for {url_hash}: {e}")

    task.add_done_callback(_cleanup)


async def _run_docling_background_upgrade(url: str, title: str, pdf_bytes: bytes) -> None:
    """Upgrade a fast PyMuPDF parse to a high-quality Docling parse in the background."""
    if _has_docling_cache(url):
        _update_meta_fields(url, high_quality_parse_pending=False, high_quality_parse_ready=True)
        return

    url_hash = _get_url_hash(url)
    images_output_dir = _get_pdf_cache_dir() / "images" / url_hash
    images_url_prefix = f"{Config.GATEWAY_SERVICE_URL}/pdf-images/{url_hash}"

    try:
        logger.info(f"Starting background Docling upgrade for {url}")
        result = await _parse_pdf_with_docling_best_effort(
            pdf_bytes,
            0,
            images_output_dir,
            images_url_prefix,
        )
        if result is None or not result.markdown or result.markdown.startswith("[Error"):
            _update_meta_fields(url, high_quality_parse_pending=False, high_quality_parse_ready=False)
            logger.warning(f"Background Docling upgrade produced no usable result for {url}")
            return

        _save_docling_to_cache(
            url,
            result.markdown,
            paper_title=title,
            structured_content=result.structured_content,
        )
        logger.info(f"Background Docling upgrade completed for {url}")
    except Exception as e:
        _update_meta_fields(url, high_quality_parse_pending=False, high_quality_parse_ready=False)
        logger.error(f"Background Docling upgrade error for {url}: {e}")


def schedule_docling_upgrade(url: str, title: str, pdf_bytes: bytes) -> bool:
    """Schedule a background Docling upgrade unless one is already cached or running."""
    url_hash = _get_url_hash(url)
    if _has_docling_cache(url):
        _update_meta_fields(url, high_quality_parse_pending=False, high_quality_parse_ready=True)
        return False

    existing_task = _docling_upgrade_tasks.get(url_hash)
    if existing_task is not None and not existing_task.done():
        _update_meta_fields(url, high_quality_parse_pending=True, high_quality_parse_ready=False)
        return False

    _update_meta_fields(url, high_quality_parse_pending=True, high_quality_parse_ready=False)
    task = asyncio.create_task(_run_docling_background_upgrade(url, title, pdf_bytes))
    _register_docling_upgrade_task(url_hash, task)
    return True


def cleanup_expired_pdf_cache() -> int:
    cleaned = 0
    try:
        cache_dir = _get_pdf_cache_dir()
        if not cache_dir.exists():
            return 0
        
        now = datetime.now()
        for meta_file in cache_dir.glob("*.json"):
            try:
                with open(meta_file, 'r') as f:
                    meta = json.load(f)
                
                cached_time = datetime.fromisoformat(meta.get('cached_at', '2000-01-01'))
                if now - cached_time > timedelta(days=PDF_CACHE_TTL_DAYS):
                    url_hash = meta_file.stem
                    _remove_cached_pdf_artifacts(url_hash, remove_vectorstore=True)
                    cleaned += 1
                    logger.info(f"Cleaned expired PDF cache: {meta.get('url', url_hash)}")
            except Exception as e:
                logger.error(f"Error cleaning cache file {meta_file}: {e}")
        
        if cleaned > 0:
            logger.info(f"PDF cache cleanup complete: {cleaned} files removed")
    except Exception as e:
        logger.error(f"Error in PDF cache cleanup: {e}")
    
    return cleaned


def get_arxiv_pdf_url(url: str) -> str:
    match = re.search(r'arxiv\.org/(abs|pdf|html)/([\w\.\-]+)', url)
    if match:
        paper_id = match.group(2)
        paper_id = paper_id.replace('.pdf', '')
        return f"https://arxiv.org/pdf/{paper_id}.pdf"
    return url


def get_openreview_pdf_url(url: str) -> str:
    """Convert OpenReview forum/note URLs to direct PDF download URLs."""
    if 'openreview.net/pdf?' in url:
        return url
    match = re.search(r'openreview\.net/(?:forum|note|pdf)\?id=([^&#]+)', url, re.IGNORECASE)
    if match:
        return f"https://openreview.net/pdf?id={match.group(1)}"
    return url


def get_sciencedirect_pdf_url(url: str) -> str:
    """Convert ScienceDirect article page URL to direct PDF download URL.

    The pdfft URL works for open-access articles without authentication.
    """
    if 'pdfft' in url or url.lower().endswith('.pdf'):
        return url
    pii_match = re.search(r'/pii/([A-Z0-9]+)', url, re.IGNORECASE)
    if pii_match:
        pii = pii_match.group(1).upper()
        return f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true"
    return url


def get_nature_pdf_url(url: str) -> str:
    """Append .pdf to Nature article page URLs for direct PDF download."""
    if url.lower().endswith('.pdf'):
        return url
    base = url.split('?')[0].split('#')[0].rstrip('/')
    if re.search(r'nature\.com/articles/[a-z0-9\-]+$', base, re.IGNORECASE):
        return base + '.pdf'
    return url


def get_wiley_pdf_url(url: str) -> str:
    """Convert Wiley article URL to PDF download URL."""
    if '/doi/pdf/' in url or url.lower().endswith('.pdf'):
        return url
    for old in ('/doi/abs/', '/doi/full/'):
        if old in url:
            return url.replace(old, '/doi/pdf/')
    # /doi/10.xxxx → /doi/pdf/10.xxxx
    if re.search(r'/doi/10\.[0-9]{4,}', url) and '/doi/pdf/' not in url:
        return url.replace('/doi/', '/doi/pdf/', 1)
    return url


def get_biorxiv_pdf_url(url: str) -> str:
    """Convert bioRxiv/medRxiv abstract URL to full PDF URL."""
    if url.lower().endswith('.pdf'):
        return url
    base = url.rstrip('/').split('?')[0]
    base = re.sub(r'\.(full|abstract|article-info|metrics)$', '', base)
    return base + '.full.pdf'


def get_science_pdf_url(url: str) -> str:
    if '/doi/full/' in url:
        return url.replace('/doi/full/', '/doi/pdf/')
    elif '/doi/' in url and '/pdf' not in url:
        return url.replace('/doi/', '/doi/pdf/')
    return url


def get_pmc_pdf_url(url: str) -> str:
    """Convert PMC article page URL to direct PDF download URL.

    Handles both pmc.ncbi.nlm.nih.gov and legacy ncbi.nlm.nih.gov/pmc URLs.
    """
    if url.rstrip('/').endswith('/pdf') or '/pdf/' in url:
        return url
    match = re.search(r'/(PMC[0-9]+)/?', url, re.IGNORECASE)
    if match:
        pmc_id = match.group(1).upper()
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/pdf/"
    return url


async def _resolve_pubmed_to_pdf_url(url: str) -> str:
    """Resolve a PubMed abstract URL to a downloadable PDF URL.

    Uses the NCBI ID converter API to map PMID → PMCID / DOI.
    Priority: PMC PDF (free full text) > publisher URL (via DOI redirect).

    When a DOI is found, follows the doi.org redirect to obtain the actual
    publisher URL (e.g. sciencedirect.com, nature.com) so that
    ``download_pdf``'s publisher-specific URL converters can be applied.

    Returns the best resolved URL, or the original URL unchanged on failure.
    """
    pmid_match = re.search(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', url)
    if not pmid_match:
        return url
    pmid = pmid_match.group(1)
    try:
        api_url = (
            f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
            f"?ids={pmid}&format=json&tool=pathlab&email=cjinag@connect.ust.hk"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                logger.warning(f"NCBI ID converter returned {resp.status_code} for PMID {pmid}")
                return url
            data = resp.json()
            records = data.get("records", [])
            if not records:
                logger.info(f"NCBI ID converter: no records for PMID {pmid}")
                return url
            record = records[0]
            # Prefer PMC (free full-text PDF)
            pmcid = record.get("pmcid")
            if pmcid:
                pdf_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/"
                logger.info(f"PubMed {pmid} → PMC PDF: {pdf_url}")
                return pdf_url
            # Fall back to DOI — follow the redirect to get the real publisher URL
            # so that download_pdf's elif chain can apply the right converter
            # (e.g. ScienceDirect pdfft, Nature /content/pdf, etc.)
            doi = record.get("doi")
            if doi:
                return await _follow_doi_redirect(doi, pmid)
    except Exception as e:
        logger.warning(f"NCBI ID converter error for PMID {pmid}: {e}")
    return url


async def _follow_doi_redirect(doi: str, pmid: str | None = None) -> str:
    """Follow a doi.org redirect to get the final publisher URL.

    Uses HEAD with follow_redirects to efficiently resolve without
    downloading the full page.  Returns the final URL on success,
    or ``https://doi.org/{doi}`` as fallback.
    """
    doi_url = f"https://doi.org/{doi}"
    label = f"PMID {pmid}" if pmid else f"DOI {doi}"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            head_resp = await client.head(doi_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,*/*",
            })
            final_url = str(head_resp.url)
            if final_url and final_url != doi_url:
                logger.info(f"{label} → DOI redirect → {final_url}")
                return final_url
    except Exception as e:
        logger.warning(f"DOI redirect failed for {label} ({doi_url}): {e}")
    logger.info(f"{label} → DOI (no redirect): {doi_url}")
    return doi_url


def get_acl_pdf_url(url: str) -> str:
    """Append .pdf to ACL Anthology article URL for direct PDF download.

    Per ACL Anthology FAQ: append .pdf to the canonical article URL.
    """
    if url.lower().endswith('.pdf'):
        return url
    base = url.split('?')[0].split('#')[0].rstrip('/')
    return base + '.pdf'


def get_ieee_pdf_url(url: str) -> str:
    """Convert IEEE Xplore document page URL to PDF viewer URL."""
    if url.lower().endswith('.pdf') or 'stamp.jsp' in url:
        return url
    match = re.search(r'/document/([0-9]+)', url)
    if match:
        return f"https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber={match.group(1)}"
    return url


def get_acm_pdf_url(url: str) -> str:
    """Convert ACM Digital Library article URL to PDF download URL.

    Insert 'pdf/' segment after '/doi/' in the URL.
    """
    if '/doi/pdf/' in url or url.lower().endswith('.pdf'):
        return url
    if '/doi/' in url:
        return url.replace('/doi/', '/doi/pdf/', 1)
    return url


def get_springer_pdf_url(url: str) -> str:
    """Convert SpringerLink article URL to direct PDF download URL.

    Article page: link.springer.com/article/10.xxxx/yyy
    PDF:          link.springer.com/content/pdf/10.xxxx/yyy.pdf
    """
    if '/content/pdf/' in url or url.lower().endswith('.pdf'):
        return url
    match = re.search(r'springer\.com/(?:article|chapter)/(10\.[0-9]{4,}[^\s?#]+)', url)
    if match:
        doi = match.group(1).rstrip('/')
        return f"https://link.springer.com/content/pdf/{doi}.pdf"
    return url


def get_plos_pdf_url(url: str) -> str:
    """Convert PLOS article page URL to direct PDF download URL.

    Article page: journals.plos.org/plosone/article?id=10.1371/journal.pone.xxxxxxx
    PDF:          journals.plos.org/plosone/article/file?id=10.1371/journal.pone.xxxxxxx&type=printable
    """
    if 'type=printable' in url or 'article/file' in url:
        return url
    doi_match = re.search(r'[?&]id=(10\.[0-9]{4,}/[^\s?#&]+)', url)
    if doi_match:
        doi = doi_match.group(1)
        journal_match = re.search(r'journals\.plos\.org/([^/?#]+)', url)
        journal = journal_match.group(1) if journal_match else 'plosone'
        return f"https://journals.plos.org/{journal}/article/file?id={doi}&type=printable"
    return url


def get_jama_pdf_url(url: str) -> str:
    """Convert JAMA Network article page URL to PDF download URL.

    Article page: jamanetwork.com/journals/jama/fullarticle/xxxxxxx
    PDF:          jamanetwork.com/journals/jama/articlepdf/xxxxxxx
    """
    if 'articlepdf' in url or url.lower().endswith('.pdf'):
        return url
    return url.replace('/fullarticle/', '/articlepdf/')


def get_nejm_pdf_url(url: str) -> str:
    """Convert NEJM article page URL to PDF download URL.

    Article page: nejm.org/doi/full/10.1056/NEJMxxx
    PDF:          nejm.org/doi/pdf/10.1056/NEJMxxx
    """
    if '/doi/pdf/' in url or url.lower().endswith('.pdf'):
        return url
    for old in ('/doi/full/', '/doi/abs/'):
        if old in url:
            return url.replace(old, '/doi/pdf/')
    if re.search(r'/doi/10\.[0-9]{4,}', url) and '/doi/pdf/' not in url:
        return url.replace('/doi/', '/doi/pdf/', 1)
    return url


def get_lancet_pdf_url(url: str) -> str:
    """Convert The Lancet article page URL to PDF download URL.

    Article page: thelancet.com/journals/lancet/article/PIISxxxxxxx/fulltext
    PDF:          thelancet.com/journals/lancet/article/PIISxxxxxxx/pdf
    """
    if '/pdf' in url or url.lower().endswith('.pdf'):
        return url
    base = url.rstrip('/')
    if base.endswith('/fulltext'):
        return base[:-len('/fulltext')] + '/pdf'
    return url


def get_cell_pdf_url(url: str) -> str:
    """Convert Cell Press article page URL to PDF download URL.

    Article page: cell.com/cell/fulltext/S0092-8674(22)01377-0
    PDF:          cell.com/cell/pdf/s0092-8674(22)01377-0.pdf
    """
    if url.lower().endswith('.pdf') or '/pdf/' in url:
        return url
    match = re.search(r'(https?://(?:www\.)?cell\.com/[^/]+)/fulltext/([^\s?#]+)', url, re.IGNORECASE)
    if match:
        base, pii = match.group(1), match.group(2)
        return f"{base}/pdf/{pii.lower()}.pdf"
    return url


def get_oup_pdf_url(url: str) -> str:
    """Convert Oxford Academic (OUP) article URL to PDF via pdf-lookup redirect.

    OUP provides a stable redirect endpoint: /pdf-lookup/doi/{doi}
    """
    if 'article-pdf' in url or 'pdf-lookup' in url or url.lower().endswith('.pdf'):
        return url
    doi_match = re.search(r'(10\.[0-9]{4,}/[^\s?#&]+)', url)
    if doi_match:
        doi = doi_match.group(1).rstrip('/')
        return f"https://academic.oup.com/pdf-lookup/doi/{doi}"
    return url


def get_frontiers_pdf_url(url: str) -> str:
    """Convert Frontiers article page URL to PDF download URL.

    Article page: frontiersin.org/journals/.../articles/10.3389/.../full
    PDF:          frontiersin.org/journals/.../articles/10.3389/.../pdf
    """
    if url.lower().endswith('.pdf') or url.rstrip('/').endswith('/pdf'):
        return url
    base = url.rstrip('/')
    if base.endswith('/full'):
        return base[:-5] + '/pdf'
    return base + '/pdf'


def get_mdpi_pdf_url(url: str) -> str:
    """Append /pdf to MDPI article URL for direct PDF download.

    Article page: mdpi.com/2075-4698/15/1/6
    PDF:          mdpi.com/2075-4698/15/1/6/pdf
    """
    if url.lower().endswith('.pdf') or url.rstrip('/').endswith('/pdf'):
        return url
    return url.rstrip('/') + '/pdf'


def get_rsp_pdf_url(url: str) -> str:
    """Convert Royal Society Publishing article URL to PDF download URL.

    Article page: royalsocietypublishing.org/doi/full/10.1098/xxx
    PDF:          royalsocietypublishing.org/doi/pdf/10.1098/xxx
    """
    if '/doi/pdf/' in url or url.lower().endswith('.pdf'):
        return url
    for old in ('/doi/full/', '/doi/abs/'):
        if old in url:
            return url.replace(old, '/doi/pdf/')
    if re.search(r'/doi/10\.[0-9]{4,}', url) and '/doi/pdf/' not in url:
        return url.replace('/doi/', '/doi/pdf/', 1)
    return url


def get_pnas_pdf_url(url: str) -> str:
    """Convert PNAS article URL to PDF download URL.

    Article page: pnas.org/doi/10.1073/pnas.xxxxxxxx
    PDF:          pnas.org/doi/pdf/10.1073/pnas.xxxxxxxx
    """
    if '/doi/pdf/' in url or url.lower().endswith('.pdf'):
        return url
    if '/doi/full/' in url:
        return url.replace('/doi/full/', '/doi/pdf/')
    if re.search(r'/doi/10\.[0-9]{4,}', url) and '/doi/pdf/' not in url:
        return url.replace('/doi/', '/doi/pdf/', 1)
    return url


def _extract_doi(url: str) -> str | None:
    """Extract DOI from common academic URL patterns."""
    # Direct DOI URL: https://doi.org/10.xxxx/...
    match = re.search(r'doi\.org/(10\.[0-9]{4,}[^\s?#]+)', url)
    if match:
        return match.group(1).rstrip('/')
    # Nature: nature.com/articles/s41586-024-07386-0
    match = re.search(r'nature\.com/articles/(s[0-9]+-[0-9]+-[0-9]+-[a-z0-9]+)', url, re.IGNORECASE)
    if match:
        return f"10.1038/{match.group(1)}"
    # Science: science.org/doi/10.1126/science.xxx
    match = re.search(r'science\.org/doi/(?:full/|abs/|pdf/)?(10\.[0-9]{4,}[^\s?#]+)', url)
    if match:
        return match.group(1).rstrip('/')
    # NEJM: nejm.org/doi/full/10.1056/NEJMxxx
    match = re.search(r'nejm\.org/doi/(?:full/|pdf/)?(10\.[0-9]{4,}[^\s?#]+)', url)
    if match:
        return match.group(1).rstrip('/')
    # Wiley: onlinelibrary.wiley.com/doi/10.xxxx/xxx
    match = re.search(r'wiley\.com/doi/(?:full/|abs/|pdf/)?(10\.[0-9]{4,}[^\s?#]+)', url)
    if match:
        return match.group(1).rstrip('/')
    # Springer: link.springer.com/article/10.xxxx/xxx
    match = re.search(r'springer\.com/(?:article|chapter)/?(10\.[0-9]{4,}[^\s?#]+)', url)
    if match:
        return match.group(1).rstrip('/')
    # Frontiers: frontiersin.org/journals/.../articles/10.3389/.../full
    # Must come before generic pattern to avoid capturing trailing /full or /pdf
    match = re.search(r'frontiersin\.org/(?:journals/[^/]+/)?articles/(10\.[0-9]{4,}/[^\s?#&/]+)', url)
    if match:
        return match.group(1).rstrip('/')
    # Generic DOI pattern in URL (must be last — greedily matches trailing path segments)
    match = re.search(r'(10\.[0-9]{4,}/[^\s?#&]+)', url)
    if match:
        return match.group(1).rstrip('/')
    return None


async def _try_crossref_doi_from_pii(pii: str) -> str | None:
    """Look up DOI for a ScienceDirect article via CrossRef using PII as alternative-id.

    ScienceDirect article URLs contain a PII (e.g. S2667325824005132) but not the DOI.
    CrossRef's filter API resolves PII → DOI so we can pass it to Unpaywall/Semantic Scholar.
    """
    try:
        api_url = f"https://api.crossref.org/works?filter=alternative-id:{pii}&rows=1"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                api_url,
                headers={"User-Agent": "PathLab/1.0 (mailto:cjinag@connect.ust.hk)"},
            )
            if resp.status_code == 200:
                items = resp.json().get("message", {}).get("items", [])
                if items:
                    doi = items[0].get("DOI")
                    if doi:
                        logger.info(f"CrossRef resolved PII {pii} → DOI {doi}")
                        return doi
    except Exception as e:
        logger.warning(f"CrossRef PII lookup error for {pii}: {e}")
    return None


async def _try_unpaywall_download(url: str, doi: str | None = None) -> bytes | None:
    """Try to get open access PDF via Unpaywall API."""
    if doi is None:
        doi = _extract_doi(url)
    if not doi:
        return None
    try:
        api_url = f"https://api.unpaywall.org/v2/{doi}?email=cjinag@connect.ust.hk"
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                logger.info(f"Unpaywall API returned {resp.status_code} for DOI {doi}")
                return None
            data = resp.json()
            best_oa = data.get("best_oa_location")
            if not best_oa:
                logger.info(f"No OA location found via Unpaywall for DOI {doi}")
                return None
            pdf_url = best_oa.get("url_for_pdf") or best_oa.get("url")
            if not pdf_url:
                return None
            logger.info(f"Unpaywall found OA PDF for DOI {doi}: {pdf_url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/pdf,*/*",
            }
            pdf_resp = await client.get(pdf_url, headers=headers)
            if pdf_resp.status_code == 200:
                content = pdf_resp.content
                if content[:4] == b'%PDF' or 'pdf' in pdf_resp.headers.get('content-type', '').lower():
                    logger.info(f"Unpaywall download successful: {len(content)} bytes")
                    return content
            return None
    except Exception as e:
        logger.warning(f"Unpaywall API error: {e}")
        return None


async def _try_semantic_scholar_download(url: str, doi: str | None = None) -> bytes | None:
    """Try to get PDF via Semantic Scholar API."""
    if doi is None:
        doi = _extract_doi(url)
    if not doi:
        return None
    try:
        api_url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf"
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                return None
            data = resp.json()
            oa_pdf = data.get("openAccessPdf")
            if not oa_pdf or not oa_pdf.get("url"):
                return None
            pdf_url = oa_pdf["url"]
            logger.info(f"Semantic Scholar found PDF for DOI {doi}: {pdf_url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/pdf,*/*",
            }
            pdf_resp = await client.get(pdf_url, headers=headers)
            if pdf_resp.status_code == 200:
                content = pdf_resp.content
                if content[:4] == b'%PDF' or 'pdf' in pdf_resp.headers.get('content-type', '').lower():
                    logger.info(f"Semantic Scholar download successful: {len(content)} bytes")
                    return content
            return None
    except Exception as e:
        logger.warning(f"Semantic Scholar API error: {e}")
        return None


# Maximum PDF file size to download (50 MB) — prevents OOM on huge files.
_MAX_PDF_DOWNLOAD_BYTES = 50 * 1024 * 1024


async def download_pdf(url: str, timeout: float = 60.0) -> bytes | None:
    try:
        # Validate URL scheme — only http(s) is supported.
        if not url.startswith(('http://', 'https://')):
            logger.warning(f"Invalid URL scheme (not http/https): {url}")
            return None

        # Pre-step: Resolve PubMed abstract URLs to the actual content URL
        # (PMC PDF or publisher page via DOI redirect).  This MUST run before
        # the publisher elif-chain so the resolved URL can be matched below.
        if 'pubmed.ncbi.nlm.nih.gov' in url:
            url = await _resolve_pubmed_to_pdf_url(url)

        # Step 1: Convert article page URLs to direct PDF download URLs.
        if 'arxiv.org' in url:
            url = get_arxiv_pdf_url(url)
        elif 'openreview.net' in url:
            url = get_openreview_pdf_url(url)
        elif 'nature.com' in url:
            url = get_nature_pdf_url(url)
        elif 'sciencedirect.com' in url or 'elsevier.com' in url:
            url = get_sciencedirect_pdf_url(url)
        elif 'science.org' in url:
            url = get_science_pdf_url(url)
        elif 'onlinelibrary.wiley.com' in url:
            url = get_wiley_pdf_url(url)
        elif 'biorxiv.org' in url or 'medrxiv.org' in url:
            url = get_biorxiv_pdf_url(url)
        elif 'pmc.ncbi.nlm.nih.gov' in url or 'ncbi.nlm.nih.gov/pmc' in url:
            url = get_pmc_pdf_url(url)
        elif 'aclanthology.org' in url:
            url = get_acl_pdf_url(url)
        elif 'ieeexplore.ieee.org' in url:
            url = get_ieee_pdf_url(url)
        elif 'dl.acm.org' in url:
            url = get_acm_pdf_url(url)
        elif 'link.springer.com' in url or ('springer.com' in url and 'content/pdf' not in url):
            url = get_springer_pdf_url(url)
        elif 'plos.org' in url:
            url = get_plos_pdf_url(url)
        elif 'jamanetwork.com' in url:
            url = get_jama_pdf_url(url)
        elif 'nejm.org' in url:
            url = get_nejm_pdf_url(url)
        elif 'thelancet.com' in url:
            url = get_lancet_pdf_url(url)
        elif 'cell.com' in url:
            url = get_cell_pdf_url(url)
        elif 'academic.oup.com' in url:
            url = get_oup_pdf_url(url)
        elif 'frontiersin.org' in url:
            url = get_frontiers_pdf_url(url)
        elif 'mdpi.com' in url:
            url = get_mdpi_pdf_url(url)
        elif 'royalsocietypublishing.org' in url:
            url = get_rsp_pdf_url(url)
        elif 'pnas.org' in url:
            url = get_pnas_pdf_url(url)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/pdf,application/x-pdf,*/*",
        }

        # Step 2: Attempt direct download.
        try_oa_fallback = False
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)

            if response.status_code == 200:
                content = response.content
                # Size guard — reject files larger than _MAX_PDF_DOWNLOAD_BYTES
                if len(content) > _MAX_PDF_DOWNLOAD_BYTES:
                    logger.warning(
                        f"PDF too large ({len(content) / 1024 / 1024:.1f} MB > "
                        f"{_MAX_PDF_DOWNLOAD_BYTES / 1024 / 1024:.0f} MB limit): {url}"
                    )
                    return None
                if content[:4] == b'%PDF':
                    return content
                content_type = response.headers.get('content-type', '')
                if 'pdf' in content_type.lower():
                    return content
                cd = response.headers.get('content-disposition', '')
                if '.pdf' in cd.lower():
                    return content
                # Got 200 but HTML/non-PDF — publisher returned a login or paywall page.
                # (ScienceDirect, Nature, and others do this for non-OA content.)
                logger.info(f"Got 200 non-PDF from {url}, trying open access APIs...")
                try_oa_fallback = True
            elif response.status_code in (403, 401, 451):
                logger.info(f"Got {response.status_code} from {url}, trying open access APIs...")
                try_oa_fallback = True
            else:
                logger.warning(f"Failed to download PDF from {url}: status {response.status_code}")

        if not try_oa_fallback:
            return None

        # Step 3: Open-access API fallback (Unpaywall → Semantic Scholar).
        doi = _extract_doi(url)
        # ScienceDirect URLs contain only a PII, not a DOI — resolve via CrossRef.
        if not doi and 'sciencedirect.com' in url:
            pii_match = re.search(r'/pii/([A-Z0-9]+)', url, re.IGNORECASE)
            if pii_match:
                doi = await _try_crossref_doi_from_pii(pii_match.group(1).upper())

        oa_bytes = await _try_unpaywall_download(url, doi)
        if oa_bytes:
            return oa_bytes
        oa_bytes = await _try_semantic_scholar_download(url, doi)
        if oa_bytes:
            return oa_bytes

        logger.warning(f"All download attempts failed for {url}")
        return None
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        logger.error(f"Network unreachable when downloading PDF from {url}: {e}")
        return None
    except httpx.TimeoutException as e:
        logger.error(f"Download timed out for PDF from {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error downloading PDF from {url}: {e}")
        return None


def _parse_pdf_with_pymupdf(
    pdf_bytes: bytes,
    max_pages: int = 10,
    images_output_dir: Path | None = None,
    images_url_prefix: str | None = None,
) -> str | None:
    """Fast PDF extraction using pymupdf4llm. No GPU required, typically <5 seconds.

    Uses pymupdf4llm.to_markdown() for high-quality Markdown output including:
    - Structured text with headers, bold/italic, code blocks
    - Table detection and formatting
    - Image extraction (when images_output_dir is provided)

    Returns markdown-formatted text with page markers, or None if:
    - pymupdf4llm / PyMuPDF is not installed
    - Extraction quality is poor (too few characters, too much garbage)

    Args:
        pdf_bytes: Raw PDF bytes.
        max_pages: Maximum pages to parse (0 = unlimited).
        images_output_dir: If provided, extracted images are saved here.
        images_url_prefix: If provided, image references in markdown are
            rewritten to use this URL prefix.
    """
    try:
        import pymupdf4llm
        import pymupdf
    except ImportError:
        logger.info("pymupdf4llm not installed, skipping fast extraction")
        return None

    # pymupdf4llm internally accesses doc.name for image filenames.
    # When a Document is opened from a byte stream, doc.name is None,
    # causing a TypeError in pymupdf4llm's save_image().  Work around
    # this by writing to a temp file so the Document has a valid name.
    import tempfile as _tempfile
    tmp_file = _tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        tmp_file.write(pdf_bytes)
        tmp_file.close()

        doc = pymupdf.open(tmp_file.name)
        total_pages = len(doc)
        pages_to_process = min(total_pages, max_pages) if max_pages > 0 else total_pages
        page_list = list(range(pages_to_process))

        # Determine whether to extract images
        write_images = images_output_dir is not None
        image_path = str(images_output_dir) if write_images else ""
        if write_images:
            images_output_dir.mkdir(parents=True, exist_ok=True)

        md_text = pymupdf4llm.to_markdown(
            doc,
            pages=page_list,
            write_images=write_images,
            image_path=image_path,
            image_format="png",
            dpi=150,
            page_chunks=True,
            show_progress=False,
        )

        doc.close()

        # md_text is a list of dicts when page_chunks=True
        # Each dict has "text", "metadata", "images", "tables", etc.
        page_sections = []
        total_chars = 0
        garbage_chars = 0

        for chunk in md_text:
            page_num = chunk["metadata"].get("page", chunk["metadata"].get("page_number", 0))
            text = chunk["text"].strip()
            if text:
                total_chars += len(text)
                garbage = sum(1 for c in text if ord(c) > 0xFFFF or (ord(c) < 32 and c not in '\n\r\t'))
                garbage_chars += garbage
                page_sections.append(f"--- Page {page_num} ---\n\n{text}")

        # Quality checks
        if total_chars < 200:
            logger.info(f"PyMuPDF: too short ({total_chars} chars), need structured-parser fallback")
            return None

        garbage_ratio = garbage_chars / total_chars if total_chars > 0 else 0
        if garbage_ratio > 0.1:
            logger.info(f"PyMuPDF: too much garbage ({garbage_ratio:.1%}), need structured-parser fallback")
            return None

        # Per-page density check: catch scanned PDFs with sparse headers/footers
        # that pass the total char threshold but have very little content per page.
        num_pages = len(page_sections)
        if num_pages > 0:
            avg_chars_per_page = total_chars / num_pages
            if avg_chars_per_page < 50 and num_pages >= 3:
                logger.info(
                    f"PyMuPDF: low per-page density ({avg_chars_per_page:.0f} chars/page "
                    f"across {num_pages} pages), likely scanned PDF — need structured-parser fallback"
                )
                return None

        md_content = "\n\n".join(page_sections)

        # Rewrite local image paths to HTTP URLs if prefix is provided
        if images_url_prefix and image_path:
            # pymupdf4llm writes image refs like ![desc](image_path/filename.png)
            md_content = md_content.replace(
                f"]({image_path}/", f"]({images_url_prefix}/"
            )
            # Also handle backslash paths on Windows (just in case)
            md_content = md_content.replace(
                f"]({image_path}\\", f"]({images_url_prefix}/"
            )

        img_count = md_content.count("![")
        logger.info(
            f"PyMuPDF fast extraction OK: {total_chars} chars, "
            f"{len(page_sections)} pages, {img_count} images"
        )
        return md_content

    except Exception as e:
        logger.warning(f"PyMuPDF extraction failed: {e}")
        return None
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_file.name)
        except OSError:
            pass



def _extract_gpu_index_from_device(assigned_device: str | None) -> int | None:
    """Extract the physical GPU index from strings like ``cuda:1``."""
    if not assigned_device:
        return None
    match = re.fullmatch(r'cuda:(\d+)', assigned_device.strip().lower())
    if not match:
        return None
    return int(match.group(1))


def _docling_subprocess_entry(
    result_conn,
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir_str: str | None,
    images_url_prefix: str | None,
    physical_gpu_index: int,
) -> None:
    """Child-process entrypoint for GPU-isolated Docling parsing."""
    try:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(physical_gpu_index)
        markdown = _parse_pdf_with_docling(
            pdf_bytes,
            max_pages,
            images_output_dir=Path(images_output_dir_str) if images_output_dir_str else None,
            images_url_prefix=images_url_prefix,
            accelerator_device="cuda",
        )
        result_conn.send({"ok": True, "markdown": markdown})
    except Exception as e:
        try:
            result_conn.send({"ok": False, "error": str(e)})
        except Exception:
            pass
    finally:
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        gc.collect()
        try:
            result_conn.close()
        except Exception:
            pass


def _run_docling_in_isolated_process(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir_str: str | None,
    images_url_prefix: str | None,
    assigned_device: str,
) -> str | None:
    """Run Docling in a short-lived subprocess pinned to the assigned GPU."""
    physical_gpu_index = _extract_gpu_index_from_device(assigned_device)
    if physical_gpu_index is None:
        raise RuntimeError(f"Invalid assigned GPU device for Docling parse: {assigned_device}")

    ctx = multiprocessing.get_context('spawn')
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_docling_subprocess_entry,
        args=(
            child_conn,
            pdf_bytes,
            max_pages,
            images_output_dir_str,
            images_url_prefix,
            physical_gpu_index,
        ),
    )

    payload = None
    try:
        process.start()
        child_conn.close()

        while True:
            if parent_conn.poll(0.5):
                payload = parent_conn.recv()
                break
            if not process.is_alive():
                break

        process.join(timeout=DOCLING_SUBPROCESS_JOIN_TIMEOUT_SECONDS)

        if payload is None:
            raise RuntimeError(
                f"Docling subprocess exited without returning a result "
                f"(exitcode={process.exitcode})"
            )
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error") or "Unknown Docling subprocess error")
        return payload.get("markdown")
    finally:
        try:
            parent_conn.close()
        except Exception:
            pass
        try:
            child_conn.close()
        except Exception:
            pass
        if process.is_alive():
            process.terminate()
            process.join(timeout=DOCLING_SUBPROCESS_JOIN_TIMEOUT_SECONDS)
        if process.is_alive():
            process.kill()
            process.join(timeout=DOCLING_SUBPROCESS_JOIN_TIMEOUT_SECONDS)


async def _parse_pdf_with_docling_on_assigned_gpu(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir: Path | None,
    images_url_prefix: str | None,
    assigned_device: str,
) -> str | None:
    """Run Docling in an isolated subprocess on the queue-assigned GPU."""
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            _run_docling_in_isolated_process,
            pdf_bytes,
            max_pages,
            str(images_output_dir) if images_output_dir else None,
            images_url_prefix,
            assigned_device,
        )
        logger.info(f"Docling GPU parse completed on {assigned_device}")
        return result
    except Exception as e:
        logger.warning(f"Docling GPU parse failed on {assigned_device}: {e}")
        return None


async def _parse_pdf_with_docling_via_gpu_queue(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir: Path | None,
    images_url_prefix: str | None,
) -> str | None:
    """Submit Docling parsing to the shared GPU queue and await the result."""
    from ..task_queue import TaskType, get_task_queue

    queue = get_task_queue()
    worker_task = getattr(queue, "_worker_task", None)
    if worker_task is None or worker_task.done():
        logger.warning("Task queue is not running; skipping Docling GPU parse")
        return None

    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[str | None] = loop.create_future()
    task_id = f"pdf-parse-{uuid.uuid4().hex}"

    async def _queued_docling_job(
        *,
        assigned_device: str,
        task_id: str | None = None,
        **_ignored_kwargs: Any,
    ) -> None:
        try:
            result = await _parse_pdf_with_docling_on_assigned_gpu(
                pdf_bytes,
                max_pages,
                images_output_dir,
                images_url_prefix,
                assigned_device,
            )
            if not result_future.done():
                result_future.set_result(result)
        except Exception as e:
            if task_id:
                logger.warning(f"Docling queued job {task_id} failed on {assigned_device}: {e}")
            if not result_future.done():
                result_future.set_exception(e)
            raise

    await queue.submit(task_id, TaskType.INFERENCE, _queued_docling_job)
    return await result_future


async def _parse_pdf_with_docling_on_cpu(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir: Path | None,
    images_url_prefix: str | None,
) -> str | None:
    """Run Docling on CPU in a worker thread when GPU parsing is unavailable."""
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            _parse_pdf_with_docling,
            pdf_bytes,
            max_pages,
            images_output_dir,
            images_url_prefix,
            "cpu",
        )
        if result is not None:
            logger.info("Docling CPU parse completed")
        return result
    except Exception as e:
        logger.warning(f"Docling CPU parse failed: {e}")
        return None


def _parse_pdf_with_docling(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir: Path | None = None,
    images_url_prefix: str | None = None,
    accelerator_device: str = "cpu",
) -> str | None:
    """High-quality PDF extraction using Docling.

    Returns markdown with page markers and appends extracted figure/table links
    when image export is enabled.
    """
    try:
        from docling_core.types.doc import ImageRefMode, PictureItem, TableItem
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as e:
        logger.info(f"Docling not available for structured fallback parse: {e}")
        return None

    tmp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        tmp_file.write(pdf_bytes)
        tmp_file.close()

        pipeline_options = PdfPipelineOptions()
        pipeline_options.images_scale = 2.0
        pipeline_options.generate_page_images = True
        pipeline_options.generate_picture_images = True
        pipeline_options.accelerator_options = AcceleratorOptions(
            num_threads=4,
            device=AcceleratorDevice.CUDA if accelerator_device == "cuda" else AcceleratorDevice.CPU,
        )

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )

        conv_res = converter.convert(tmp_file.name)
        markdown = conv_res.document.export_to_markdown(
            image_mode=ImageRefMode.PLACEHOLDER,
            page_break_placeholder="\n\n--- Page {page_no} ---\n\n",
        ).strip()

        if max_pages > 0:
            page_sections: list[str] = []
            for match in re.finditer(
                r'--- Page (\d+) ---\n\n([\s\S]*?)(?=\n\n--- Page \d+ ---|\Z)',
                markdown,
            ):
                if int(match.group(1)) > max_pages:
                    break
                page_sections.append(
                    f"--- Page {match.group(1)} ---\n\n{match.group(2).strip()}"
                )
            markdown = "\n\n".join(section for section in page_sections if section.strip())

        extracted_links: list[str] = []
        if images_output_dir is not None:
            images_output_dir.mkdir(parents=True, exist_ok=True)
            figure_counter = 0
            for element, _level in conv_res.document.iterate_items():
                if not isinstance(element, (PictureItem, TableItem)):
                    continue

                image = element.get_image(conv_res.document)
                if image is None:
                    continue

                figure_counter += 1
                filename = f"figure-{figure_counter:03d}.png"
                image_path = images_output_dir / filename
                image.save(image_path, "PNG")

                caption = ""
                if hasattr(element, "caption_text"):
                    try:
                        caption = str(element.caption_text(conv_res.document) or "").strip()
                    except Exception:
                        caption = ""

                if images_url_prefix is not None:
                    link_title = f"Figure {figure_counter}"
                    if caption:
                        link_title = f"{link_title}: {caption}"
                    extracted_links.append(f"![{link_title}]({images_url_prefix}/{filename})")

            if extracted_links:
                markdown = (
                    markdown.rstrip()
                    + "\n\n## Extracted Figures and Tables\n\n"
                    + "\n\n".join(extracted_links)
                )

        logger.info(
            f"Docling extraction OK: {len(markdown)} chars, "
            f"{len(extracted_links)} extracted figures/tables"
        )
        return markdown
    except Exception as e:
        logger.warning(f"Docling extraction failed: {e}")
        return None
    finally:
        try:
            os.unlink(tmp_file.name)
        except OSError:
            pass


async def parse_pdf(
    pdf_bytes: bytes,
    max_pages: int = 10,
    images_output_dir: Path | None = None,
    images_url_prefix: str | None = None,
) -> ParsedPdfResult:
    """Parse PDF with PyMuPDF first; fall back to Docling only if fast parse fails.

    Normal flow returns quickly with a PyMuPDF parse. Callers can schedule a
    background Docling upgrade separately to improve fidelity and structure.
    """
    pymupdf_result = _parse_pdf_with_pymupdf(
        pdf_bytes,
        max_pages,
        images_output_dir=images_output_dir,
        images_url_prefix=images_url_prefix,
    )
    if pymupdf_result is not None:
        return _to_parsed_pdf_result(pymupdf_result, PDF_PARSE_METHOD_PYMUPDF)

    docling_result = await _parse_pdf_with_docling_best_effort(
        pdf_bytes,
        max_pages,
        images_output_dir,
        images_url_prefix,
    )
    if docling_result is not None:
        return docling_result

    return _to_parsed_pdf_result(
        "[Error parsing PDF: PyMuPDF and Docling both failed]",
        PDF_PARSE_METHOD_FAILED,
    )


async def summarize_pdf_content(
    pdf_content: str,
    title: str,
    base_url: str,
    api_key: str,
    model: str,
    max_length: int = 3000,
    is_academic: bool = True,
) -> str:
    # Head + tail strategy: preserve both the beginning (abstract / intro) and the
    # end of the document (conclusions / author contributions / references).
    # 15 000 chars total budget: 10 000 head + 5 000 tail.
    if len(pdf_content) > 15000:
        head = pdf_content[:10000]
        tail = pdf_content[-5000:]
        pdf_content = head + "\n\n...[middle content omitted for length]...\n\n" + tail

    if is_academic:
        prompt = f"""Analyze this academic paper and provide a comprehensive summary.

Title: {title}

Content:
{pdf_content}

Provide:
1. **Main Topic**: What is this paper about?
2. **Key Contributions**: What are the main contributions or findings?
3. **Methodology**: Brief overview of the approach/method used
4. **Results**: Key results and their significance
5. **Limitations**: Any mentioned limitations or future work

Keep each section concise (2-3 sentences)."""
    else:
        prompt = f"""Analyze this document and provide a concise summary.
Note: This is NOT necessarily an academic paper — it may be a general document,
product brochure, technical documentation, blog post, or other non-academic content.
Summarize it accurately based on what it actually is.

Title: {title}

Content:
{pdf_content}

Provide:
1. **Document Type**: What kind of document is this? (e.g., technical report, product brochure, guide, etc.)
2. **Main Content**: What is the document about?
3. **Key Points**: What are the most important points or takeaways?

Keep each section concise (2-3 sentences). Do NOT assume this is a research paper."""

    messages = [{"role": "user", "content": prompt}]

    try:
        from .chat import _call_ai_complete
        summary = await _call_ai_complete(
            messages=messages,
            base_url=base_url,
            api_key=api_key,
            model=model
        )
        return summary
    except Exception as e:
        logger.error(f"Error summarizing PDF: {e}")
        return pdf_content[:max_length]


def format_reference_card(
    title: str,
    url: str,
    source_type: str = "web",
    is_academic: bool = False,
) -> str:
    source_icons = {
        "arxiv": "📄",
        "pubmed": "🏥",
        "nature": "🌿",
        "science": "🔬",
        "cell": "🧬",
        "lancet": "💉",
        "nejm": "🏥",
        "jama": "🏥",
        "bmj": "🏥",
        "modernpathology": "🔬",
        "springer": "📚",
        "ieee": "⚡",
        "acm": "💻",
        "biorxiv": "📄",
        "elsevier": "📚",
        "wiley": "📚",
        "frontiers": "📚",
        "mdpi": "📚",
        "oup": "📚",
        "plos": "📚",
        "taylor_francis": "📚",
        "huggingface": "🤗",
        "github": "💻",
        "blog": "📝",
        "documentation": "📖",
        "wikipedia": "🌐",
        "pdf": "📄",
        "web": "🌐",
    }

    # Determine display type: "paper" for academic content, "webpage" for everything else
    display_type = "paper" if is_academic else "webpage"

    icon = source_icons.get(source_type, "📚")
    source_id = _get_url_hash(url)

    if source_type == "arxiv":
        arxiv_id = ""
        match = re.search(r'(\d{4}\.\d{4,5}|[a-z-]+/\d+)', url)
        if match:
            arxiv_id = match.group(1)
        card = f"""[REFERENCE]
icon: {icon}
title: {title}
url: {url}
source_id: {source_id}
source: arXiv ({arxiv_id})
type: paper
[/REFERENCE]"""
    else:
        # Friendly source label for display
        source_labels = {
            "github": "GitHub",
            "blog": "Blog",
            "documentation": "Docs",
            "wikipedia": "Wikipedia",
            "openreview": "OpenReview",
        }
        source_label = source_labels.get(source_type, source_type.upper())
        card = f"""[REFERENCE]
icon: {icon}
title: {title}
url: {url}
source_id: {source_id}
source: {source_label}
type: {display_type}
[/REFERENCE]"""

    return card


def detect_source_type(url: str) -> str:
    url_lower = url.lower()

    # ── Academic sources ──────────────────────────────────────────────────────
    if 'arxiv.org' in url_lower:
        return "arxiv"
    elif 'openreview.net' in url_lower:
        return "openreview"
    elif 'ncbi.nlm.nih.gov' in url_lower or 'pubmed' in url_lower:
        return "pubmed"
    elif 'nature.com' in url_lower:
        return "nature"
    elif 'science.org' in url_lower or 'sciencemag.org' in url_lower:
        return "science"
    elif 'cell.com' in url_lower:
        return "cell"
    elif 'thelancet.com' in url_lower:
        return "lancet"
    elif 'nejm.org' in url_lower:
        return "nejm"
    elif 'jamanetwork.com' in url_lower:
        return "jama"
    elif 'bmj.com' in url_lower:
        return "bmj"
    elif 'modernpathology.org' in url_lower:
        return "modernpathology"
    elif 'springer.com' in url_lower or 'link.springer.com' in url_lower:
        return "springer"
    elif 'ieee' in url_lower:
        return "ieee"
    elif 'acm.org' in url_lower:
        return "acm"
    elif 'biorxiv.org' in url_lower or 'medrxiv.org' in url_lower:
        return "biorxiv"
    elif 'sciencedirect.com' in url_lower or 'elsevier.com' in url_lower:
        return "elsevier"
    elif 'wiley.com' in url_lower or 'onlinelibrary.wiley.com' in url_lower:
        return "wiley"
    elif 'frontiersin.org' in url_lower:
        return "frontiers"
    elif 'mdpi.com' in url_lower:
        return "mdpi"
    elif 'academic.oup.com' in url_lower:
        return "oup"
    elif 'journals.plos.org' in url_lower or 'plos.org' in url_lower:
        return "plos"
    elif 'tandfonline.com' in url_lower:
        return "taylor_francis"
    # ── Non-academic known sources ────────────────────────────────────────────
    elif 'huggingface.co' in url_lower or 'hf.co' in url_lower:
        return "huggingface"
    elif 'github.com' in url_lower or 'github.io' in url_lower:
        return "github"
    elif any(d in url_lower for d in (
        'medium.com', 'substack.com', 'dev.to', 'hashnode.dev',
        'wordpress.com', 'blogger.com', 'blogspot.com',
        'csdn.net', 'zhihu.com', 'jianshu.com', 'cnblogs.com',
        '/blog/', '/blogs/', '/posts/',
    )):
        return "blog"
    elif any(d in url_lower for d in (
        'readthedocs.io', 'readthedocs.org',
        'docs.', '/docs/', '/documentation/',
        'gitbook.io',
    )):
        return "documentation"
    elif 'wikipedia.org' in url_lower:
        return "wikipedia"
    # ── Generic PDF (may or may not be academic — caller should verify) ────
    elif '.pdf' in url_lower:
        return "pdf"
    else:
        return "web"


# Known academic source types — used to determine if a source is inherently academic.
_ACADEMIC_SOURCE_TYPES = frozenset({
    "arxiv", "openreview", "pubmed", "nature", "science", "cell", "lancet",
    "nejm", "jama", "bmj", "modernpathology", "springer", "ieee", "acm",
    "biorxiv", "elsevier", "wiley", "frontiers", "mdpi", "oup", "plos",
    "taylor_francis",
})


def is_academic_content(content: str, source_type: str) -> bool:
    """Determine whether parsed PDF/document content is academic in nature.

    Uses a two-tier approach:
      1. If the URL source is a known academic publisher → always True.
      2. For generic PDFs ("pdf") or "web" sources → heuristic keyword analysis.

    The heuristic checks for the presence of typical academic paper structural
    markers (abstract, methodology, references section, etc.).  A document must
    match at least 3 out of ~10 markers to be considered academic.

    Returns True for academic papers, False for brochures / ads / general docs.
    """
    # Tier 1: known academic domains are always academic
    if source_type in _ACADEMIC_SOURCE_TYPES:
        return True

    # Non-PDF, non-web sources (github, blog, docs, wikipedia) are never academic
    if source_type not in ("pdf", "web"):
        return False

    # Tier 2: heuristic analysis for generic PDFs / unknown web sources
    content_lower = content[:30000].lower()  # Only scan first ~30k chars for speed

    academic_markers = [
        # Structural sections typical of academic papers
        r'\babstract\b',
        r'\bintroduction\b',
        r'\bmethodology\b|\bmethods\b|\bmaterials and methods\b',
        r'\bresults\b',
        r'\bdiscussion\b',
        r'\bconclusion[s]?\b',
        r'\breferences\b',
        r'\backnowledgment[s]?\b|\backnowledgement[s]?\b',
        # Academic identifiers
        r'\bdoi:\s*10\.',
        r'\b10\.\d{4,}/\S+',  # DOI pattern
        r'\bISSN\b|\bISBN\b',
        # Academic vocabulary
        r'\bet al\.\b',
        r'\bpeer[- ]review',
        r'\bsupplementary\s+(material|data|figure|table)',
        r'\bfigure\s+\d+|fig\.\s*\d+',
        r'\btable\s+\d+',
    ]

    match_count = sum(1 for pat in academic_markers if re.search(pat, content_lower))

    # Require at least 3 markers for classification as academic
    is_academic = match_count >= 3
    logger.debug(
        f"Academic content detection: {match_count}/{len(academic_markers)} markers matched → "
        f"{'academic' if is_academic else 'non-academic'}"
    )
    return is_academic


async def process_pdf_url(
    url: str,
    title: str,
    base_url: str,
    api_key: str,
    model: str,
    use_cache: bool = True
) -> dict[str, Any]:
    """Process a PDF URL: download, parse, summarize, and format a reference card.

    Returns a dict with keys:
        url, title, source_type, success, summary, pdf_content (full markdown with page markers),
        error, error_detail, from_cache, reference_card, page_count, parse_method,
        structured_parse_method, high_quality_pending
    """
    result: dict[str, Any] = {
        "url": url,
        "title": title,
        "source_type": detect_source_type(url),
        "is_academic": False,  # Whether content is academic (paper) or general (webpage)
        "success": False,
        "summary": None,
        "pdf_content": None,   # Full markdown with page markers for AI citation
        "error": None,
        "error_detail": None,  # Human-readable error explanation
        "from_cache": False,
        "reference_card": None,
        "page_count": None,    # Total pages parsed (int), filled after parsing
        "parse_method": None,  # "docling" or "pymupdf"
        "structured_parse_method": None,
        "high_quality_pending": False,
        "image_count": 0,      # Number of extracted images on disk
        "images_ready": False, # Whether extracted images are available to reference
    }

    try:
        pdf_bytes = None
        cached_markdown = None

        if use_cache:
            cached = _get_cached_pdf(url)
            if cached:
                pdf_bytes, cache_meta, cached_markdown, cached_markdown_method = cached
                result["from_cache"] = True
                result["title"] = cache_meta.get('title', title)
                # Restore persisted metadata so callers always have it on cache hits
                if cache_meta.get('page_count'):
                    result["page_count"] = cache_meta['page_count']
                result["parse_method"] = cached_markdown_method or cache_meta.get('parse_method')
                result["structured_parse_method"] = cache_meta.get('structured_parse_method')
                result["high_quality_pending"] = bool(cache_meta.get('high_quality_parse_pending'))
                logger.info(f"Using cached PDF for {url}" + (" (with cached markdown)" if cached_markdown else ""))

        if not pdf_bytes:
            pdf_bytes = await download_pdf(url)
            if pdf_bytes and use_cache:
                _save_pdf_to_cache(url, pdf_bytes, title)

        if not pdf_bytes:
            result["error"] = "download_failed"
            result["error_detail"] = (
                f"Failed to download PDF from {url}. "
                "The publisher may block automated access (HTTP 403), "
                "the server may be unavailable, or the URL may require authentication."
            )
            return result

        # Use cached markdown if available, otherwise parse
        if cached_markdown:
            pdf_content = cached_markdown
            logger.info(f"Using cached parsed markdown for {url}")
            if result["parse_method"] == PDF_PARSE_METHOD_PYMUPDF and use_cache and pdf_bytes:
                schedule_docling_upgrade(url, str(result["title"] or title), pdf_bytes)
                result["high_quality_pending"] = not _has_docling_cache(url)
        else:
            url_hash = _get_url_hash(url)
            sync_images_output_dir = _get_pdf_cache_dir() / "images" / url_hash
            sync_images_url_prefix = f"{Config.GATEWAY_SERVICE_URL}/pdf-images/{url_hash}"

            parse_result = await parse_pdf(
                pdf_bytes, max_pages=0,
                images_output_dir=sync_images_output_dir,
                images_url_prefix=sync_images_url_prefix,
            )
            pdf_content = parse_result.markdown
            parse_method = parse_result.parse_method
            result["parse_method"] = parse_method
            result["page_count"] = parse_result.page_count
            result["structured_parse_method"] = parse_method
            if use_cache and not pdf_content.startswith("[Error"):
                if parse_method == PDF_PARSE_METHOD_DOCLING:
                    _save_docling_to_cache(
                        url,
                        pdf_content,
                        paper_title=title,
                        structured_content=parse_result.structured_content,
                    )
                else:
                    _save_markdown_to_cache(
                        url,
                        pdf_content,
                        paper_title=title,
                        structured_content=parse_result.structured_content,
                        high_quality_pending=True,
                    )
                    if pdf_bytes:
                        schedule_docling_upgrade(url, title, pdf_bytes)
                        result["high_quality_pending"] = True

        # Guard: empty result (not an [Error prefix but no content extracted)
        if not pdf_content or not pdf_content.strip():
            result["error"] = "parse_failed"
            result["error_detail"] = (
                f"PDF parsing produced no content for '{title}'. "
                "The file may be an image-only scan, empty, or in an unsupported format."
            )
            return result

        if pdf_content.startswith("[Error"):
            result["error"] = "parse_failed"
            result["error_detail"] = (
                f"PDF parsing failed for '{title}'. The file may be corrupted, "
                "scanned-only, or in an unsupported format."
            )
            return result

        # Extract page count from the raw content (before any appended status markers).
        # _extract_page_count scans '--- Page X ---' markers; 0 means no markers found.
        result["page_count"] = result["page_count"] or _extract_page_count(pdf_content)
        # parse_method may already be set from cache metadata or current parse.
        if not result["parse_method"]:
            result["parse_method"] = (
                PDF_PARSE_METHOD_DOCLING if _has_docling_cache(url) else PDF_PARSE_METHOD_PYMUPDF
            )
        if not result["structured_parse_method"]:
            structured_cached = get_cached_structured_content(url)
            if structured_cached:
                result["structured_parse_method"] = structured_cached.get("parse_method")
        if result["parse_method"] == PDF_PARSE_METHOD_DOCLING:
            result["high_quality_pending"] = False

        # ── Academic content detection ────────────────────────────────────────
        # Determines whether this PDF is an academic paper or a general document
        # (e.g., brochure, product guide, ad). This affects:
        #   - The summarization prompt (academic vs general)
        #   - The reference card type (paper vs webpage)
        #   - The label used in the supplement context (Paper vs Document)
        source_type = str(result["source_type"]) if result["source_type"] is not None else "web"
        academic = is_academic_content(pdf_content, source_type)
        result["is_academic"] = academic
        # Persist to cache so follow-up questions can read it without re-detection
        if use_cache:
            _update_meta_academic_flag(url, academic)

        # Determine whether extracted images are already available.
        # Both Docling and PyMuPDF write into the same per-document images dir.
        url_hash_for_images = _get_url_hash(url)
        images_dir_for_check = _get_pdf_cache_dir() / "images" / url_hash_for_images
        image_count_on_disk = 0
        if images_dir_for_check.exists() and images_dir_for_check.is_dir():
            image_count_on_disk = sum(1 for f in images_dir_for_check.iterdir() if f.is_file())
        images_ready = image_count_on_disk > 0
        result["image_count"] = image_count_on_disk
        result["images_ready"] = images_ready

        # Store full content with page markers so AI can cite specific pages.
        result["pdf_content"] = pdf_content

        summary = await summarize_pdf_content(
            pdf_content,
            str(result["title"]) if result["title"] is not None else title,
            base_url,
            api_key,
            model,
            is_academic=academic,
        )

        result["success"] = True
        result["summary"] = summary
        result["reference_card"] = format_reference_card(
            str(result["title"]) if result["title"] is not None else title,
            url,
            source_type,
            is_academic=academic,
        )

    except Exception as e:
        logger.error(f"Error processing PDF {url}: {e}")
        result["error"] = str(e)
        result["error_detail"] = f"An unexpected error occurred while processing '{title}': {str(e)[:100]}"

    return result

