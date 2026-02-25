"""
PDF Parsing utilities for AI chat - uses MinerU for academic paper processing

When Exa search returns PDF links (e.g., arXiv papers),
this module downloads, parses, and summarizes the content for the AI agent.

Features:
- Supports 30+ academic journal URL patterns
- File-based cache with 7-day TTL
- Reference card generation for AI responses
"""
import json
import os
import re
import shutil
import tempfile
import asyncio
import hashlib
import threading
from pathlib import Path
from typing import Any
from datetime import datetime, timedelta
import httpx

from ..dependencies import logger
from backend.common.config import Config
from backend.common.gpu_utils import select_optimal_gpu_for_task

# Serialize MinerU GPU access: only one parse at a time to avoid GPU memory conflicts
_mineru_gpu_lock = threading.Lock()

# Minimum free VRAM (MB) required to run MinerU hybrid_auto with VLM backend
MIN_VRAM_MB_FOR_MINERU = 8000


_pdf_cache_dir: Path | None = None
PDF_CACHE_TTL_DAYS = 7


def _get_pdf_cache_dir() -> Path:
    global _pdf_cache_dir
    if _pdf_cache_dir is None:
        uploads_dir = Config.get_uploads_dir()
        _pdf_cache_dir = uploads_dir / "pdf_cache"
        _pdf_cache_dir.mkdir(parents=True, exist_ok=True)
    return _pdf_cache_dir


def get_pdf_image_path(url_hash: str, filename: str) -> Path:
    """Return the persistent storage path for a MinerU-extracted PDF image.

    Used by the /pdf-images/{url_hash}/{filename} HTTP endpoint to locate files.
    Images are stored at: pdf_cache/images/{url_hash}/{filename}
    """
    return _get_pdf_cache_dir() / "images" / url_hash / filename


PDF_URL_PATTERNS = [
    r'\.pdf$',
    
    r'arxiv\.org/(pdf|abs)/',
    r'arxiv\.org/pdf/',
    
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


def _get_cached_pdf(url: str) -> tuple[bytes, dict[str, Any], str | None] | None:
    """Returns (pdf_bytes, meta, cached_markdown_or_None) or None if not cached/expired."""
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
                pdf_file.unlink()
                meta_file.unlink()
                md_file = cache_dir / f"{url_hash}.md"
                if md_file.exists():
                    md_file.unlink()
            except:
                pass
            return None

        pdf_bytes = pdf_file.read_bytes()

        # Prefer MinerU high-precision cache; fall back to pymupdf cache.
        cached_md = None
        mineru_file = cache_dir / f"{url_hash}.mineru.md"
        pymupdf_file = cache_dir / f"{url_hash}.md"
        for md_candidate in (mineru_file, pymupdf_file):
            if md_candidate.exists():
                try:
                    cached_md = md_candidate.read_text(encoding='utf-8')
                    if md_candidate == mineru_file:
                        logger.info(f"PDF cache: using high-precision MinerU result for {url}")
                    break
                except Exception:
                    pass

        return pdf_bytes, meta, cached_md
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


def _update_meta_with_parse_info(url: str, page_count: int, parse_method: str) -> None:
    """Update the cached JSON metadata with page_count and parse_method.

    This is a best-effort update: failures are logged but never raised so that
    the caller (cache-save path) is never disrupted.
    """
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        meta_file = cache_dir / f"{url_hash}.json"
        if not meta_file.exists():
            return
        with open(meta_file, 'r') as f:
            meta = json.load(f)
        meta['page_count'] = page_count
        meta['parse_method'] = parse_method
        with open(meta_file, 'w') as f:
            json.dump(meta, f, indent=2)
    except Exception as e:
        logger.error(f"Error updating meta for {url}: {e}")


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


def _save_markdown_to_cache(url: str, markdown: str, paper_title: str = "") -> None:
    """Save pymupdf-parsed markdown to cache (fast tier)."""
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        md_file = cache_dir / f"{url_hash}.md"
        md_file.write_text(markdown, encoding='utf-8')
        # Update JSON metadata with page count from this parse
        page_count = _extract_page_count(markdown)
        _update_meta_with_parse_info(url, page_count, 'pymupdf')
        logger.info(f"Cached pymupdf markdown for {url} ({page_count} pages)")
        # Build vector index for semantic search
        _trigger_vector_index(url_hash, markdown, paper_title)
    except Exception as e:
        logger.error(f"Error saving markdown to cache: {e}")


def _has_mineru_cache(url: str) -> bool:
    """Return True if a high-precision MinerU result is already cached for this URL."""
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        return (cache_dir / f"{url_hash}.mineru.md").exists()
    except Exception:
        return False


def _save_mineru_to_cache(url: str, markdown: str, paper_title: str = "") -> None:
    """Save MinerU high-precision parse result to cache (slow/high-quality tier)."""
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        mineru_file = cache_dir / f"{url_hash}.mineru.md"
        mineru_file.write_text(markdown, encoding='utf-8')
        # MinerU supersedes pymupdf: update JSON meta with final page count
        page_count = _extract_page_count(markdown)
        _update_meta_with_parse_info(url, page_count, 'mineru')
        logger.info(f"Cached MinerU high-precision markdown for {url} ({page_count} pages)")
        # Rebuild vector index with higher-quality MinerU content
        _trigger_vector_index(url_hash, markdown, paper_title)
    except Exception as e:
        logger.error(f"Error saving MinerU markdown to cache: {e}")


# ── Vector Index Helper ─────────────────────────────────────────────────────

def _trigger_vector_index(url_hash: str, markdown: str, paper_title: str) -> None:
    """Index PDF content into the vector store (best-effort, non-blocking)."""
    try:
        from .chat_pdf_vectorstore import index_pdf_to_vectorstore
        index_pdf_to_vectorstore(url_hash, markdown, paper_title or "Unknown")
    except Exception as e:
        logger.error(f"[VectorIndex] Failed to index {url_hash}: {e}")


# ── BM25 Page-Level Search ──────────────────────────────────────────────────

def _tokenize_for_search(text: str) -> list[str]:
    """Simple tokenizer for BM25 search. Handles English, numbers, and CJK.

    - Lowercases all text
    - Keeps alphanumeric runs (e.g. ``bm25``, ``page3``) as single tokens
    - Splits each CJK character as an individual token
    """
    return re.findall(r'[a-z0-9]+|[\u4e00-\u9fff\u3400-\u4dbf]', text.lower())


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

    Prefers MinerU high-precision (``.mineru.md``) over PyMuPDF (``.md``).
    """
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        for suffix in ('.mineru.md', '.md'):
            md_file = cache_dir / f"{url_hash}{suffix}"
            if md_file.exists():
                return md_file.read_text(encoding='utf-8')
        return None
    except Exception:
        return None


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


async def _background_mineru_upgrade(url: str, pdf_bytes: bytes, max_pages: int = 0) -> None:
    """Background task: run MinerU on a PDF that was already served via pymupdf.

    Saves the high-precision result to {url_hash}.mineru.md so the *next* cache hit
    will automatically return the better parse.  Silently no-ops if:
    - A MinerU cache already exists for this URL
    - No GPU with sufficient VRAM is available
    - The MinerU GPU lock cannot be acquired without blocking (another parse is
      already in progress — we just skip rather than queue indefinitely)

    max_pages=0 means unlimited: this task runs in the background so there is no
    UX penalty for parsing all pages.  MinerU's value (tables, formulas, layout)
    is most visible in the later sections of a paper (results, conclusions, appendices).
    """
    if _has_mineru_cache(url):
        return  # already upgraded

    gpu_idx, free_mb = select_optimal_gpu_for_task(min_vram_mb=MIN_VRAM_MB_FOR_MINERU)
    if gpu_idx == -1:
        logger.info(
            f"[BG MinerU] Skipping upgrade for {url}: "
            f"no GPU with >= {MIN_VRAM_MB_FOR_MINERU} MB free (best: {free_mb:.0f} MB)"
        )
        return

    # Non-blocking lock attempt: if another MinerU parse is running, skip.
    acquired = _mineru_gpu_lock.acquire(blocking=False)
    if not acquired:
        logger.info(f"[BG MinerU] Skipping upgrade for {url}: MinerU GPU lock busy")
        return

    # Prepare persistent image directory so MinerU images survive temp-dir cleanup.
    url_hash = _get_url_hash(url)
    images_output_dir = _get_pdf_cache_dir() / "images" / url_hash
    images_url_prefix = f"{Config.GATEWAY_SERVICE_URL}/pdf-images/{url_hash}"

    original_cuda_devices = os.environ.get("CUDA_VISIBLE_DEVICES")
    try:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_idx)
        logger.info(f"[BG MinerU] Starting upgrade for {url} on cuda:{gpu_idx}")
        loop = asyncio.get_event_loop()
        markdown = await loop.run_in_executor(
            None, _parse_pdf_sync_inner, pdf_bytes, max_pages,
            images_output_dir, images_url_prefix,
        )
        if markdown and not markdown.startswith("[Error"):
            # Recover paper title from cached meta for vector re-indexing
            meta = get_cached_pdf_meta(url)
            title = (meta or {}).get("title", "")
            _save_mineru_to_cache(url, markdown, paper_title=title)
            logger.info(f"[BG MinerU] Upgrade complete for {url} ({len(markdown)} chars)")
        else:
            logger.warning(f"[BG MinerU] Upgrade failed for {url}: {markdown[:80]}")
    except Exception as e:
        logger.error(f"[BG MinerU] Upgrade error for {url}: {e}")
    finally:
        # Safety-net: ensure vLLM processes are cleaned up even if
        # _parse_pdf_sync_inner's own cleanup somehow failed.
        _shutdown_mineru_vlm_singleton()
        _mineru_gpu_lock.release()
        if original_cuda_devices is not None:
            os.environ["CUDA_VISIBLE_DEVICES"] = original_cuda_devices
        else:
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)


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
                    pdf_file = cache_dir / f"{url_hash}.pdf"
                    
                    if pdf_file.exists():
                        pdf_file.unlink()
                    # Remove pymupdf and MinerU cached markdown
                    for suffix in (".md", ".mineru.md"):
                        cached_file = cache_dir / f"{url_hash}{suffix}"
                        if cached_file.exists():
                            cached_file.unlink()
                    # Remove MinerU-extracted images directory
                    images_dir = cache_dir / "images" / url_hash
                    if images_dir.exists() and images_dir.is_dir():
                        shutil.rmtree(images_dir)
                    # Remove vector store entries
                    try:
                        from .chat_pdf_vectorstore import delete_pdf_from_vectorstore
                        delete_pdf_from_vectorstore(url_hash)
                    except Exception as ve:
                        logger.error(f"Error cleaning vector store for {url_hash}: {ve}")
                    meta_file.unlink()
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
    match = re.search(r'arxiv\.org/(abs|pdf)/([\w\.\-]+)', url)
    if match:
        paper_id = match.group(2)
        paper_id = paper_id.replace('.pdf', '')
        return f"https://arxiv.org/pdf/{paper_id}.pdf"
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


async def download_pdf(url: str, timeout: float = 60.0) -> bytes | None:
    try:
        # Step 1: Convert article page URLs to direct PDF download URLs.
        if 'arxiv.org' in url:
            url = get_arxiv_pdf_url(url)
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
    except Exception as e:
        logger.error(f"Error downloading PDF from {url}: {e}")
        return None


def _parse_pdf_with_pymupdf(pdf_bytes: bytes, max_pages: int = 10) -> str | None:
    """Fast PDF text extraction using PyMuPDF (fitz). No GPU required, <1 second.

    Returns markdown-formatted text with page markers, or None if:
    - PyMuPDF is not installed
    - Extraction quality is poor (too few characters, too much garbage)
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.info("PyMuPDF (fitz) not installed, skipping fast extraction")
        return None

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages_to_process = min(len(doc), max_pages) if max_pages > 0 else len(doc)

        page_sections = []
        total_chars = 0
        garbage_chars = 0

        for page_idx in range(pages_to_process):
            page = doc[page_idx]
            text = page.get_text("text").strip()
            if text:
                total_chars += len(text)
                # Count non-printable / garbage characters (excluding normal whitespace)
                garbage = sum(1 for c in text if ord(c) > 0xFFFF or (ord(c) < 32 and c not in '\n\r\t'))
                garbage_chars += garbage
                page_sections.append(f"--- Page {page_idx + 1} ---\n\n{text}")

        doc.close()

        # Quality checks
        if total_chars < 200:
            logger.info(f"PyMuPDF: too short ({total_chars} chars), need MinerU fallback")
            return None

        garbage_ratio = garbage_chars / total_chars if total_chars > 0 else 0
        if garbage_ratio > 0.1:
            logger.info(f"PyMuPDF: too much garbage ({garbage_ratio:.1%}), need MinerU fallback")
            return None

        md_content = "\n\n".join(page_sections)
        logger.info(f"PyMuPDF fast extraction OK: {total_chars} chars from {len(page_sections)} pages")
        return md_content

    except Exception as e:
        logger.warning(f"PyMuPDF extraction failed: {e}")
        return None


def _parse_pdf_sync(
    pdf_bytes: bytes,
    max_pages: int = 10,
    images_output_dir: Path | None = None,
    images_url_prefix: str | None = None,
) -> str:
    """Two-tier PDF parsing: fast PyMuPDF first, MinerU GPU fallback.

    Tier 1 (PyMuPDF): CPU-only, <1 second. Works for most academic PDFs with text layers.
    Tier 2 (MinerU):  GPU-based, 10-30 seconds. Handles scanned/image-only PDFs.

    Returns markdown with `--- Page X ---` markers between pages.
    images_output_dir / images_url_prefix are forwarded to MinerU tier only
    (PyMuPDF does not extract images).
    """
    # --- Tier 1: Fast PyMuPDF extraction (no GPU, <1s) ---
    pymupdf_result = _parse_pdf_with_pymupdf(pdf_bytes, max_pages)
    if pymupdf_result is not None:
        return pymupdf_result

    # --- Tier 2: MinerU GPU-based parsing (slow but handles scanned PDFs) ---
    logger.info("PyMuPDF extraction insufficient, falling back to MinerU GPU parsing")

    # --- GPU resource check (before acquiring heavy lock) ---
    gpu_idx, free_mb = select_optimal_gpu_for_task(min_vram_mb=MIN_VRAM_MB_FOR_MINERU)
    if gpu_idx == -1:
        logger.warning(
            f"No GPU with >= {MIN_VRAM_MB_FOR_MINERU} MB free VRAM available for PDF parsing. "
            f"Best available: {free_mb:.0f} MB."
        )
        return "[Error: GPU unavailable — no GPU with sufficient free memory for PDF parsing. Please try again later.]"

    logger.info(f"PDF parsing: selected GPU cuda:{gpu_idx} with {free_mb:.0f} MB free VRAM")

    # Acquire lock so only one MinerU parse runs at a time (GPU memory safety)
    with _mineru_gpu_lock:
        # Set CUDA_VISIBLE_DEVICES so MinerU/vLLM targets the selected GPU
        original_cuda_devices = os.environ.get("CUDA_VISIBLE_DEVICES")
        os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_idx)
        try:
            return _parse_pdf_sync_inner(pdf_bytes, max_pages, images_output_dir, images_url_prefix)
        finally:
            # Restore original CUDA_VISIBLE_DEVICES
            if original_cuda_devices is not None:
                os.environ["CUDA_VISIBLE_DEVICES"] = original_cuda_devices
            else:
                os.environ.pop("CUDA_VISIBLE_DEVICES", None)


def _cleanup_vllm_processes() -> None:
    """Force-kill any orphaned vLLM EngineCore subprocesses spawned by this process.

    This is a safety-net fallback called after the normal ModelSingleton
    shutdown path.  It uses the OS process tree to find and kill children
    whose command-line contains ``vllm`` or ``EngineCore``.
    """
    import signal
    import subprocess as _sp

    my_pid = os.getpid()
    try:
        # Find all child processes of the current process
        result = _sp.run(
            ["pgrep", "-P", str(my_pid), "-a"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return  # no children or pgrep not available

        for line in result.stdout.strip().splitlines():
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            child_pid_str, cmdline = parts
            # Match vLLM EngineCore worker processes
            if "vllm" in cmdline.lower() or "enginecore" in cmdline.lower():
                child_pid = int(child_pid_str)
                try:
                    os.kill(child_pid, signal.SIGKILL)
                    logger.info(
                        f"[MinerU] Force-killed orphaned vLLM process "
                        f"PID={child_pid}: {cmdline[:80]}"
                    )
                except ProcessLookupError:
                    pass  # already dead
                except Exception as _e:
                    logger.warning(
                        f"[MinerU] Failed to kill PID={child_pid}: {_e}"
                    )
    except Exception as e:
        logger.debug(f"[MinerU] _cleanup_vllm_processes fallback error: {e}")


def _shutdown_mineru_vlm_singleton() -> None:
    """Shutdown all vLLM engines tracked by MinerU's ModelSingleton and
    release GPU memory.  Always safe to call (no-ops if nothing to clean)."""
    try:
        from mineru.backend.vlm.vlm_analyze import ModelSingleton
        from mineru.utils.model_utils import clean_memory
        import gc

        if not ModelSingleton._models:
            return

        # 1) Explicitly shutdown each vLLM engine so EngineCore
        #    subprocesses are terminated (terminate → join → kill).
        for _key, _client in list(ModelSingleton._models.items()):
            # Sync vLLM engine (backend == "vllm-engine")
            _llm = getattr(_client, 'vllm_llm', None)
            if _llm is not None:
                try:
                    _llm.llm_engine.engine_core.shutdown()
                    logger.info(f"[MinerU] vLLM sync engine shutdown OK (key={_key})")
                except Exception as _e:
                    logger.warning(f"[MinerU] vLLM sync engine shutdown warning: {_e}")
            # Async vLLM engine (backend == "vllm-async-engine")
            _allm = getattr(_client, 'vllm_async_llm', None)
            if _allm is not None:
                try:
                    _allm.engine_core.shutdown()
                    logger.info(f"[MinerU] vLLM async engine shutdown OK (key={_key})")
                except Exception as _e:
                    logger.warning(f"[MinerU] vLLM async engine shutdown warning: {_e}")

        # 2) Clear singleton dict & free CUDA memory.
        ModelSingleton._models.clear()
        clean_memory('cuda')
        gc.collect()
        logger.info("[MinerU] VLM singleton cleared — EngineCore processes terminated")
    except Exception as _cleanup_err:
        logger.warning(f"[MinerU] VLM singleton cleanup warning: {_cleanup_err}")

    # 3) Fallback: kill any remaining vLLM child processes by PID.
    _cleanup_vllm_processes()


def _parse_pdf_sync_inner(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir: Path | None = None,
    images_url_prefix: str | None = None,
) -> str:
    """Inner parsing logic, called with GPU lock held and CUDA_VISIBLE_DEVICES set.

    Args:
        pdf_bytes: Raw PDF bytes to parse.
        max_pages: Maximum pages to parse (0 = unlimited).
        images_output_dir: If provided, MinerU-extracted images are copied here
            (persistent storage) before the temporary directory is cleaned up.
        images_url_prefix: If provided, relative image references in the markdown
            (e.g. ``images/fig1.jpg``) are rewritten to absolute HTTP URLs using
            this prefix (e.g. ``http://127.0.0.1:6100/pdf-images/{hash}``).
    """
    try:
        from mineru.cli.common import convert_pdf_bytes_to_bytes_by_pypdfium2, prepare_env
        from mineru.data.data_reader_writer import FileBasedDataWriter
        from mineru.backend.hybrid.hybrid_analyze import doc_analyze as hybrid_doc_analyze
        from mineru.backend.vlm.vlm_middle_json_mkcontent import union_make
        from mineru.utils.enum_class import MakeMode
        from mineru.utils.engine_utils import get_vlm_engine

        md_content = ""
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                pdf_path = temp_path / "input.pdf"
                pdf_path.write_bytes(pdf_bytes)

                output_dir = temp_path / "output"
                local_image_dir, local_md_dir = prepare_env(output_dir, "input", "hybrid_auto")

                backend = get_vlm_engine(inference_engine='auto', is_async=False)

                start_page_id = 0
                end_page_id = max_pages - 1 if max_pages > 0 else None

                pdf_bytes_limited = convert_pdf_bytes_to_bytes_by_pypdfium2(
                    pdf_bytes, start_page_id, end_page_id
                )

                middle_json, _, _ = hybrid_doc_analyze(
                    pdf_bytes_limited,
                    image_writer=FileBasedDataWriter(local_image_dir),
                    backend=backend,
                    parse_method="hybrid_auto",
                    language="en",
                    inline_formula_enable=True,
                    server_url=None,
                )

                pdf_info = middle_json["pdf_info"]
                image_dir = str(os.path.basename(local_image_dir))
                pdf_info_list = pdf_info if isinstance(pdf_info, list) else []

                # Build page-aware markdown: iterate per page and add page markers
                if not pdf_info_list:
                    return ""

                page_sections = []
                for page_info in pdf_info_list:
                    page_idx = page_info.get('page_idx', len(page_sections))
                    page_num = page_idx + 1

                    page_md = str(union_make([page_info], MakeMode.MM_MD, image_dir) or "").strip()
                    if page_md:
                        page_sections.append(f"--- Page {page_num} ---\n\n{page_md}")

                md_content = "\n\n".join(page_sections)

                # ── Image persistence ────────────────────────────────────────
                local_image_path = Path(local_image_dir)
                if images_output_dir is not None and local_image_path.is_dir():
                    images_output_dir.mkdir(parents=True, exist_ok=True)
                    copied = 0
                    for img_file in local_image_path.iterdir():
                        if img_file.is_file():
                            shutil.copy2(img_file, images_output_dir / img_file.name)
                            copied += 1
                    logger.info(f"[MinerU] Copied {copied} images to {images_output_dir}")

                if images_url_prefix is not None and image_dir:
                    md_content = re.sub(
                        r'\(' + re.escape(image_dir) + r'/([^)\s]+)\)',
                        f'({images_url_prefix}/\\1)',
                        md_content,
                    )
        finally:
            # ── VLM singleton cleanup (ALWAYS runs) ──────────────────────
            # Must run even if parsing raised an exception, otherwise the
            # vLLM EngineCore subprocess leaks GPU VRAM permanently.
            _shutdown_mineru_vlm_singleton()

        return md_content

    except ImportError as e:
        logger.error(f"MinerU not available: {e}")
        return "[Error: MinerU not installed or import failed]"
    except Exception as e:
        logger.error(f"Error parsing PDF with MinerU: {e}")
        return f"[Error parsing PDF: {str(e)}]"


async def parse_pdf(
    pdf_bytes: bytes,
    max_pages: int = 10,
    images_output_dir: Path | None = None,
    images_url_prefix: str | None = None,
) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _parse_pdf_sync, pdf_bytes, max_pages, images_output_dir, images_url_prefix,
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

    if source_type == "arxiv":
        arxiv_id = ""
        match = re.search(r'(\d{4}\.\d{4,5}|[a-z-]+/\d+)', url)
        if match:
            arxiv_id = match.group(1)
        card = f"""[REFERENCE]
icon: {icon}
title: {title}
url: {url}
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
        }
        source_label = source_labels.get(source_type, source_type.upper())
        card = f"""[REFERENCE]
icon: {icon}
title: {title}
url: {url}
source: {source_label}
type: {display_type}
[/REFERENCE]"""

    return card


def detect_source_type(url: str) -> str:
    url_lower = url.lower()

    # ── Academic sources ──────────────────────────────────────────────────────
    if 'arxiv.org' in url_lower:
        return "arxiv"
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
    "arxiv", "pubmed", "nature", "science", "cell", "lancet",
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
    """Process a PDF URL: download, parse with MinerU, summarize, and format reference card.

    Returns a dict with keys:
        url, title, source_type, success, summary, pdf_content (full markdown with page markers),
        error, error_detail, from_cache, reference_card, page_count, parse_method
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
        "parse_method": None,  # "pymupdf" or "mineru" — indicates quality tier
    }

    try:
        pdf_bytes = None
        cached_markdown = None

        if use_cache:
            cached = _get_cached_pdf(url)
            if cached:
                pdf_bytes, cache_meta, cached_markdown = cached
                result["from_cache"] = True
                result["title"] = cache_meta.get('title', title)
                # Restore persisted metadata so callers always have it on cache hits
                if cache_meta.get('page_count'):
                    result["page_count"] = cache_meta['page_count']
                if cache_meta.get('parse_method'):
                    result["parse_method"] = cache_meta['parse_method']
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
        else:
            # ── Two-tier parsing ──────────────────────────────────────────────
            # Tier 1: Fast pymupdf (CPU, <1 s).  Returns immediately.
            # max_pages=0 means unlimited: PyMuPDF is pure text extraction and
            # processes 50 pages just as fast as 10 pages (no OCR / GPU needed).
            pymupdf_result = _parse_pdf_with_pymupdf(pdf_bytes, max_pages=0)

            # Pre-compute image storage paths for the sync MinerU fallback path.
            url_hash = _get_url_hash(url)
            sync_images_output_dir = _get_pdf_cache_dir() / "images" / url_hash
            sync_images_url_prefix = f"{Config.GATEWAY_SERVICE_URL}/pdf-images/{url_hash}"

            if pymupdf_result is not None:
                pdf_content = pymupdf_result
                if use_cache:
                    _save_markdown_to_cache(url, pdf_content, paper_title=title)
                # Tier 2 (background): Schedule MinerU upgrade for the *next*
                # request if no high-precision cache exists yet and GPU is free.
                if use_cache and not _has_mineru_cache(url):
                    asyncio.create_task(
                        _background_mineru_upgrade(url, pdf_bytes)  # max_pages=0: unlimited in background
                    )
                    logger.info(f"[BG MinerU] Background upgrade scheduled for {url}")
            else:
                # pymupdf insufficient — fall back to MinerU synchronously now.
                # Pass image params so extracted figures are persisted immediately.
                # Use max_pages=0 (unlimited) since MinerU is the high-precision tier
                # and can extract tables, formulas, and images from all pages.
                pdf_content = await parse_pdf(
                    pdf_bytes,
                    max_pages=0,
                    images_output_dir=sync_images_output_dir,
                    images_url_prefix=sync_images_url_prefix,
                )
                # Successful MinerU result goes to the high-precision cache slot
                if not pdf_content.startswith("[Error") and use_cache:
                    _save_mineru_to_cache(url, pdf_content, paper_title=title)

        if pdf_content.startswith("[Error"):
            # Distinguish GPU unavailable from other parse errors
            if "GPU unavailable" in pdf_content:
                result["error"] = "gpu_unavailable"
                result["error_detail"] = (
                    f"No GPU resources available to parse '{title}'. "
                    "All GPUs are currently busy or lack sufficient free memory. "
                    "Please try again later when GPU resources are freed."
                )
            else:
                result["error"] = "parse_failed"
                result["error_detail"] = f"PDF parsing failed for '{title}'. The file may be corrupted, scanned-only, or in an unsupported format."
            return result

        # Extract page count from the raw content (before any appended status markers).
        # _extract_page_count scans '--- Page X ---' markers; 0 means no markers found.
        result["page_count"] = result["page_count"] or _extract_page_count(pdf_content)
        # parse_method may already be set from cache_meta; set it from current parse if not.
        if not result["parse_method"]:
            result["parse_method"] = "mineru" if _has_mineru_cache(url) else "pymupdf"

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

        # Determine whether MinerU images are already available.
        # Images are only present when content comes from a MinerU parse (.mineru.md cache
        # or the synchronous MinerU fallback above).  PyMuPDF is text-only.
        images_ready = _has_mineru_cache(url)

        # Build the content blob for the AI.  Append a [PDF_IMAGES_STATUS] marker when
        # images are still being extracted (background MinerU upgrade not yet complete).
        # The supplement prompt tells the AI how to handle this marker.
        if images_ready:
            ai_pdf_content = pdf_content
        else:
            ai_pdf_content = (
                pdf_content
                + "\n\n[PDF_IMAGES_STATUS: pending — High-precision figure/image extraction "
                "is running in the background (MinerU upgrade). If the user asks about specific "
                "figures, tables, or images in this paper, inform them that image extraction is "
                "not yet complete and they can ask again after refreshing the page.]"
            )

        # Store full content with page markers so AI can cite specific pages
        result["pdf_content"] = ai_pdf_content

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

