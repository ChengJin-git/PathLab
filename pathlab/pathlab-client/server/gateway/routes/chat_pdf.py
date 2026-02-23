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


def _save_markdown_to_cache(url: str, markdown: str) -> None:
    """Save pymupdf-parsed markdown to cache (fast tier)."""
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        md_file = cache_dir / f"{url_hash}.md"
        md_file.write_text(markdown, encoding='utf-8')
        logger.info(f"Cached pymupdf markdown for {url}")
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


def _save_mineru_to_cache(url: str, markdown: str) -> None:
    """Save MinerU high-precision parse result to cache (slow/high-quality tier)."""
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        mineru_file = cache_dir / f"{url_hash}.mineru.md"
        mineru_file.write_text(markdown, encoding='utf-8')
        logger.info(f"Cached MinerU high-precision markdown for {url}")
    except Exception as e:
        logger.error(f"Error saving MinerU markdown to cache: {e}")


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

    original_cuda_devices = os.environ.get("CUDA_VISIBLE_DEVICES")
    try:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_idx)
        logger.info(f"[BG MinerU] Starting upgrade for {url} on cuda:{gpu_idx}")
        loop = asyncio.get_event_loop()
        markdown = await loop.run_in_executor(None, _parse_pdf_sync_inner, pdf_bytes, max_pages)
        if markdown and not markdown.startswith("[Error"):
            _save_mineru_to_cache(url, markdown)
            logger.info(f"[BG MinerU] Upgrade complete for {url} ({len(markdown)} chars)")
        else:
            logger.warning(f"[BG MinerU] Upgrade failed for {url}: {markdown[:80]}")
    except Exception as e:
        logger.error(f"[BG MinerU] Upgrade error for {url}: {e}")
    finally:
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
    pii_match = re.search(r'/pii/([A-Z0-9]+)', url)
    if pii_match:
        pii = pii_match.group(1)
        return f"https://reader.elsevier.com/reader/sd/pii/{pii}"
    return url


def get_science_pdf_url(url: str) -> str:
    if '/doi/full/' in url:
        return url.replace('/doi/full/', '/doi/pdf/')
    elif '/doi/' in url and '/pdf' not in url:
        return url.replace('/doi/', '/doi/pdf/')
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
    # Generic DOI pattern in URL
    match = re.search(r'(10\.[0-9]{4,}/[^\s?#&]+)', url)
    if match:
        return match.group(1).rstrip('/')
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
        if 'arxiv.org' in url:
            url = get_arxiv_pdf_url(url)
        elif 'science.org' in url:
            url = get_science_pdf_url(url)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/pdf,application/x-pdf,*/*",
        }

        if 'sciencedirect.com' in url or 'elsevier.com' in url:
            headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

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
            elif response.status_code in (403, 401, 451):
                # Publisher blocked direct download — try open access APIs
                logger.info(f"Got {response.status_code} from {url}, trying open access APIs...")
                doi = _extract_doi(url)
                # Try Unpaywall first (most comprehensive OA database)
                oa_bytes = await _try_unpaywall_download(url, doi)
                if oa_bytes:
                    return oa_bytes
                # Try Semantic Scholar
                oa_bytes = await _try_semantic_scholar_download(url, doi)
                if oa_bytes:
                    return oa_bytes
                logger.warning(f"All download attempts failed for {url} (original: {response.status_code})")
            else:
                logger.warning(f"Failed to download PDF from {url}: status {response.status_code}")
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


def _parse_pdf_sync(pdf_bytes: bytes, max_pages: int = 10) -> str:
    """Two-tier PDF parsing: fast PyMuPDF first, MinerU GPU fallback.

    Tier 1 (PyMuPDF): CPU-only, <1 second. Works for most academic PDFs with text layers.
    Tier 2 (MinerU):  GPU-based, 10-30 seconds. Handles scanned/image-only PDFs.

    Returns markdown with `--- Page X ---` markers between pages.
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
            return _parse_pdf_sync_inner(pdf_bytes, max_pages)
        finally:
            # Restore original CUDA_VISIBLE_DEVICES
            if original_cuda_devices is not None:
                os.environ["CUDA_VISIBLE_DEVICES"] = original_cuda_devices
            else:
                os.environ.pop("CUDA_VISIBLE_DEVICES", None)


def _parse_pdf_sync_inner(pdf_bytes: bytes, max_pages: int) -> str:
    """Inner parsing logic, called with GPU lock held and CUDA_VISIBLE_DEVICES set."""
    try:
        from mineru.cli.common import convert_pdf_bytes_to_bytes_by_pypdfium2, prepare_env
        from mineru.data.data_reader_writer import FileBasedDataWriter
        from mineru.backend.hybrid.hybrid_analyze import doc_analyze as hybrid_doc_analyze
        from mineru.backend.vlm.vlm_middle_json_mkcontent import union_make
        from mineru.utils.enum_class import MakeMode
        from mineru.utils.engine_utils import get_vlm_engine

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
                # page_idx is 0-based from MinerU
                page_idx = page_info.get('page_idx', len(page_sections))
                page_num = page_idx + 1  # 1-based for human readability

                # Use union_make on a single-page list to get that page's markdown
                page_md = str(union_make([page_info], MakeMode.MM_MD, image_dir) or "").strip()
                if page_md:
                    page_sections.append(f"--- Page {page_num} ---\n\n{page_md}")

            md_content = "\n\n".join(page_sections)
            return md_content

    except ImportError as e:
        logger.error(f"MinerU not available: {e}")
        return "[Error: MinerU not installed or import failed]"
    except Exception as e:
        logger.error(f"Error parsing PDF with MinerU: {e}")
        return f"[Error parsing PDF: {str(e)}]"


async def parse_pdf(pdf_bytes: bytes, max_pages: int = 10) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _parse_pdf_sync, pdf_bytes, max_pages)


async def summarize_pdf_content(
    pdf_content: str,
    title: str,
    base_url: str,
    api_key: str,
    model: str,
    max_length: int = 3000
) -> str:
    # Head + tail strategy: preserve both the beginning (abstract / intro) and the
    # end of the document (conclusions / author contributions / references).
    # 15 000 chars total budget: 10 000 head + 5 000 tail.
    if len(pdf_content) > 15000:
        head = pdf_content[:10000]
        tail = pdf_content[-5000:]
        pdf_content = head + "\n\n...[middle content omitted for length]...\n\n" + tail
    
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
    pdf_summary: str | None = None
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
        "springer": "📚",
        "ieee": "⚡",
        "acm": "💻",
        "pdf": "📄",
        "web": "🌐",
    }

    icon = source_icons.get(source_type, "📚")
    # logo key matches image filename in /images/journal-logos/{logo}.png
    logo = source_type if source_type != "web" else ""

    if source_type == "arxiv":
        arxiv_id = ""
        match = re.search(r'(\d{4}\.\d{4,5}|[a-z-]+/\d+)', url)
        if match:
            arxiv_id = match.group(1)
        card = f"""[REFERENCE]
icon: {icon}
logo: {logo}
title: {title}
url: {url}
source: arXiv ({arxiv_id})
type: paper
[/REFERENCE]"""
    else:
        card = f"""[REFERENCE]
icon: {icon}
logo: {logo}
title: {title}
url: {url}
source: {source_type.upper()}
type: {"paper" if source_type != "web" else "article"}
[/REFERENCE]"""
    
    return card


def detect_source_type(url: str) -> str:
    url_lower = url.lower()
    
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
    elif 'springer.com' in url_lower or 'link.springer.com' in url_lower:
        return "springer"
    elif 'ieee' in url_lower:
        return "ieee"
    elif 'acm.org' in url_lower:
        return "acm"
    elif '.pdf' in url_lower:
        return "pdf"
    else:
        return "web"


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
        error, error_detail, from_cache, reference_card
    """
    result: dict[str, Any] = {
        "url": url,
        "title": title,
        "source_type": detect_source_type(url),
        "success": False,
        "summary": None,
        "pdf_content": None,   # Full markdown with page markers for AI citation
        "error": None,
        "error_detail": None,  # Human-readable error explanation
        "from_cache": False,
        "reference_card": None
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

            if pymupdf_result is not None:
                pdf_content = pymupdf_result
                if use_cache:
                    _save_markdown_to_cache(url, pdf_content)
                # Tier 2 (background): Schedule MinerU upgrade for the *next*
                # request if no high-precision cache exists yet and GPU is free.
                if use_cache and not _has_mineru_cache(url):
                    asyncio.create_task(
                        _background_mineru_upgrade(url, pdf_bytes)  # max_pages=0: unlimited in background
                    )
                    logger.info(f"[BG MinerU] Background upgrade scheduled for {url}")
            else:
                # pymupdf insufficient — fall back to MinerU synchronously now
                pdf_content = await parse_pdf(pdf_bytes, max_pages=10)
                # Successful MinerU result goes to the high-precision cache slot
                if not pdf_content.startswith("[Error") and use_cache:
                    _save_mineru_to_cache(url, pdf_content)

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

        # Store full content with page markers so AI can cite specific pages
        result["pdf_content"] = pdf_content

        summary = await summarize_pdf_content(
            pdf_content,
            str(result["title"]) if result["title"] is not None else title,
            base_url,
            api_key,
            model
        )

        result["success"] = True
        result["summary"] = summary
        result["reference_card"] = format_reference_card(
            str(result["title"]) if result["title"] is not None else title,
            url,
            str(result["source_type"]) if result["source_type"] is not None else "web",
            summary
        )

    except Exception as e:
        logger.error(f"Error processing PDF {url}: {e}")
        result["error"] = str(e)
        result["error_detail"] = f"An unexpected error occurred while processing '{title}': {str(e)[:100]}"

    return result

