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
import traceback
import time
import uuid
import gc
import contextvars
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Literal
from datetime import datetime, timedelta
from urllib.parse import unquote, urlparse
import httpx

from ..dependencies import logger
from backend.common.config import Config
from .transformers_runtime import ensure_transformers_runtime_ready


_pdf_cache_dir: Path | None = None
PDF_CACHE_TTL_DAYS = 7
_marker_gpu_queue_override: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "marker_gpu_queue_override",
    default=None,
)


@contextmanager
def override_marker_gpu_queue(skip: bool):
    """Temporarily override whether Marker should bypass the shared GPU queue."""
    token = _marker_gpu_queue_override.set(bool(skip))
    try:
        yield
    finally:
        _marker_gpu_queue_override.reset(token)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _should_skip_marker_gpu_queue() -> tuple[bool, str]:
    override = _marker_gpu_queue_override.get()
    if override is not None:
        if override:
            return True, "Skipping Marker GPU queue because a call-scoped override is enabled"
        return False, "Using Marker GPU queue because a call-scoped override is disabled"
    if _env_flag("PDF_SKIP_MARKER_GPU_QUEUE", False):
        return True, "Skipping Marker GPU queue because PDF_SKIP_MARKER_GPU_QUEUE is enabled"
    return False, "Using GPU queue first for Marker best-effort parse"


PDF_PARSE_MAX_CONCURRENT = max(1, int(os.getenv("PDF_PARSE_MAX_CONCURRENT", "1")))
PDF_PARSE_MAX_QUEUE = max(0, int(os.getenv("PDF_PARSE_MAX_QUEUE", "2")))
PDF_BACKGROUND_UPGRADE_IDLE_GRACE_SECONDS = max(
    0.0,
    float(os.getenv("PDF_BACKGROUND_UPGRADE_IDLE_GRACE_SECONDS", "0.5")),
)
PDF_VECTOR_INDEX_MAX_CONCURRENT = max(1, int(os.getenv("PDF_VECTOR_INDEX_MAX_CONCURRENT", "1")))
PDF_ENABLE_BACKGROUND_MARKER_UPGRADE = _env_flag("PDF_ENABLE_BACKGROUND_MARKER_UPGRADE", True)
PDF_PARSE_METHOD_MARKER = "marker"
PDF_PARSE_METHOD_PYMUPDF = "pymupdf"
PDF_PARSE_METHOD_FAILED = "parse_failed"
PDF_PARSE_METHOD_WEB = "web"
PDF_UPGRADE_STATUS_SCHEDULED = "scheduled"
PDF_UPGRADE_STATUS_DISABLED = "disabled"
PDF_UPGRADE_STATUS_RUNNING = "running"
PDF_UPGRADE_STATUS_QUEUED_GPU = "queued_gpu"
PDF_UPGRADE_STATUS_RUNNING_GPU = "running_gpu"
PDF_UPGRADE_STATUS_DIRECT_CPU = "direct_cpu"
PDF_UPGRADE_STATUS_FALLBACK_CPU = "fallback_cpu"
PDF_UPGRADE_STATUS_SKIPPED = "skipped"
PDF_UPGRADE_STATUS_COMPLETED = "completed"
PDF_UPGRADE_STATUS_FAILED = "failed"
MARKER_CACHE_SUFFIX = ".marker.md"
PYMUPDF_CACHE_SUFFIX = ".md"
STRUCTURED_CACHE_SUFFIX = ".structured.json"
STRUCTURED_SCHEMA_VERSION = 2
PdfParseMethod = Literal["marker", "pymupdf", "parse_failed", "web"]

_MAX_WEB_DOWNLOAD_BYTES = 5 * 1024 * 1024
_MAX_WEB_TEXT_CHARS = 120_000
_REPOSITORY_SOURCE_TYPES = frozenset({"github", "gitlab", "gitee"})
_LIGHTWEIGHT_WEB_SOURCE_TYPES = frozenset({
    "github",
    "gitlab",
    "gitee",
    "zenodo",
    "documentation",
    "blog",
    "wikipedia",
    "huggingface",
})


@dataclass(frozen=True, slots=True)
class ParsedPdfResult:
    markdown: str
    parse_method: PdfParseMethod
    page_count: int
    structured_content: dict[str, Any]


HIGH_QUALITY_CACHE_SUFFIXES: tuple[tuple[str, str], ...] = (
    (MARKER_CACHE_SUFFIX, PDF_PARSE_METHOD_MARKER),
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
    *(suffix for suffix, _ in CACHED_MARKDOWN_CANDIDATES),
)
MARKER_SUBPROCESS_JOIN_TIMEOUT_SECONDS = 5.0
_marker_upgrade_tasks: dict[str, asyncio.Task[None]] = {}
_vector_index_tasks: dict[str, asyncio.Task[None]] = {}
_vector_index_pending: dict[str, dict[str, Any]] = {}
_pdf_parse_semaphore: asyncio.Semaphore | None = None
_vector_index_semaphore: asyncio.Semaphore | None = None


class MarkerGpuQueueTimeout(RuntimeError):
    """Raised when a Marker GPU task stays pending in the shared queue for too long."""


class PdfParseBusyError(RuntimeError):
    """Raised when the foreground PDF parse queue is saturated."""


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


def _get_pdf_parse_semaphore() -> asyncio.Semaphore:
    global _pdf_parse_semaphore
    if _pdf_parse_semaphore is None:
        _pdf_parse_semaphore = asyncio.Semaphore(PDF_PARSE_MAX_CONCURRENT)
    return _pdf_parse_semaphore


def _get_vector_index_semaphore() -> asyncio.Semaphore:
    global _vector_index_semaphore
    if _vector_index_semaphore is None:
        _vector_index_semaphore = asyncio.Semaphore(PDF_VECTOR_INDEX_MAX_CONCURRENT)
    return _vector_index_semaphore


def _get_pdf_parse_waiter_count(semaphore: asyncio.Semaphore) -> int:
    waiters = getattr(semaphore, "_waiters", None)
    if not waiters:
        return 0
    try:
        return sum(1 for waiter in waiters if waiter is not None and not waiter.done())
    except TypeError:
        return len(waiters)


def _get_pdf_parse_running_count(semaphore: asyncio.Semaphore) -> int:
    available_slots = max(0, int(getattr(semaphore, "_value", 0)))
    return max(0, PDF_PARSE_MAX_CONCURRENT - available_slots)


def _get_pdf_parse_load_snapshot(semaphore: asyncio.Semaphore | None = None) -> tuple[int, int]:
    active_semaphore = semaphore or _get_pdf_parse_semaphore()
    return (
        _get_pdf_parse_running_count(active_semaphore),
        _get_pdf_parse_waiter_count(active_semaphore),
    )


def _is_pdf_parse_idle(semaphore: asyncio.Semaphore | None = None) -> tuple[bool, str]:
    active_semaphore = semaphore or _get_pdf_parse_semaphore()
    running_count, waiter_count = _get_pdf_parse_load_snapshot(active_semaphore)
    if running_count > 0 or waiter_count > 0:
        return (
            False,
            f"foreground PDF parse activity detected (running={running_count}, waiting={waiter_count})",
        )
    return True, "foreground PDF parse capacity is idle"


def _raise_if_pdf_parse_queue_full(semaphore: asyncio.Semaphore, slot_label: str) -> None:
    waiter_count = _get_pdf_parse_waiter_count(semaphore)
    if waiter_count < PDF_PARSE_MAX_QUEUE:
        return

    running_count = _get_pdf_parse_running_count(semaphore)
    logger.warning(
        f"[PDFParse] Rejecting slot '{slot_label}' because queue is full "
        f"(running={running_count}, waiting={waiter_count}, "
        f"max_concurrent={PDF_PARSE_MAX_CONCURRENT}, max_queue={PDF_PARSE_MAX_QUEUE})"
    )
    raise PdfParseBusyError(
        "The system is currently busy and cannot parse this PDF right now. Please try again later."
    )


async def _run_with_pdf_parse_slot(
    slot_label: str,
    work: Callable[[], Any],
    *,
    reject_when_queue_full: bool = False,
) -> Any:
    semaphore = _get_pdf_parse_semaphore()
    if semaphore.locked():
        if reject_when_queue_full:
            _raise_if_pdf_parse_queue_full(semaphore, slot_label)
        logger.info(
            f"[PDFParse] Waiting for parse slot '{slot_label}' "
            f"(max_concurrent={PDF_PARSE_MAX_CONCURRENT}, waiting={_get_pdf_parse_waiter_count(semaphore)})"
        )
    async with semaphore:
        logger.info(
            f"[PDFParse] Acquired parse slot '{slot_label}' "
            f"(max_concurrent={PDF_PARSE_MAX_CONCURRENT})"
        )
        return await work()


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
                    if method == PDF_PARSE_METHOD_MARKER:
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
            'high_quality_upgrade_status': None,
            'high_quality_upgrade_detail': None,
            'high_quality_upgrade_updated_at': None,
            **_build_cached_article_meta_fields(url, title),
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


def _save_lightweight_markdown_to_cache(
    url: str,
    markdown: str,
    title: str,
    source_type: str,
    *,
    is_academic: bool,
) -> None:
    """Persist lightweight webpage / repository extraction using the existing markdown cache."""
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        meta_file = cache_dir / f"{url_hash}.json"
        md_file = cache_dir / f"{url_hash}{PYMUPDF_CACHE_SUFFIX}"
        now_iso = datetime.now().isoformat()
        page_count = max(1, _extract_page_count(markdown) or 1)

        md_file.write_text(markdown, encoding='utf-8')
        _save_structured_to_cache(url, _build_document_graph_from_markdown(markdown, PDF_PARSE_METHOD_WEB))

        meta = {
            'url': url,
            'title': title,
            'cached_at': now_iso,
            'size_bytes': len(markdown.encode('utf-8')),
            'page_count': page_count,
            'parse_method': PDF_PARSE_METHOD_WEB,
            'structured_parse_method': PDF_PARSE_METHOD_WEB,
            'structured_parse_ready': True,
            'high_quality_parse_pending': False,
            'high_quality_parse_ready': False,
            'high_quality_upgrade_status': PDF_UPGRADE_STATUS_SKIPPED,
            'high_quality_upgrade_detail': "Lightweight webpage extraction does not use PDF upgrade",
            'high_quality_upgrade_updated_at': now_iso,
            'is_academic': is_academic,
            'content_kind': 'webpage',
            **_build_cached_article_meta_fields(url, title),
        }
        meta['source_type'] = source_type or meta.get('source_type') or detect_source_type(url)
        with open(meta_file, 'w') as f:
            json.dump(meta, f, indent=2)

        logger.info(f"Cached lightweight page: {url} ({page_count} pseudo-pages)")
    except Exception as e:
        logger.error(f"Error saving lightweight page cache for {url}: {e}")


def _get_cached_lightweight_document(url: str) -> tuple[dict[str, Any], str] | None:
    meta = get_cached_pdf_meta(url)
    markdown = get_cached_markdown(url)
    if not meta or not markdown:
        return None

    parse_method = str(meta.get('parse_method') or '')
    content_kind = str(meta.get('content_kind') or '')
    if parse_method == PDF_PARSE_METHOD_WEB or content_kind == 'webpage':
        return meta, markdown
    return None


def _source_label_for_display(source_type: str) -> str:
    return {
        'github': 'GitHub',
        'gitlab': 'GitLab',
        'gitee': 'Gitee',
        'zenodo': 'Zenodo',
        'documentation': 'Docs',
        'blog': 'Blog',
        'wikipedia': 'Wikipedia',
        'huggingface': 'Hugging Face',
        'web': 'Web',
        'pdf': 'PDF',
    }.get(source_type, source_type.upper() if source_type else 'Web')


def _derive_title_from_url(url: str, fallback: str = "") -> str:
    if fallback:
        return fallback
    try:
        parsed = urlparse(url)
        segments = [unquote(part) for part in parsed.path.split('/') if part]
        if segments:
            return segments[-1].replace('-', ' ').replace('_', ' ')
    except Exception:
        pass
    return url


def _normalize_lightweight_web_text(text: str) -> str:
    normalized_lines: list[str] = []
    previous_blank = True
    for raw_line in str(text or '').splitlines():
        line = re.sub(r'\s+', ' ', raw_line).strip()
        if not line:
            if not previous_blank and normalized_lines:
                normalized_lines.append('')
            previous_blank = True
            continue
        normalized_lines.append(line)
        previous_blank = False
    return "\n".join(normalized_lines).strip()


def _clean_lightweight_metadata_value(text: str, max_len: int = 280) -> str:
    normalized = _normalize_lightweight_web_text(text).replace("\n", " ").strip(" -:|\t")
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 3].rstrip() + "..."


def _collect_selector_texts(
    soup: Any,
    selectors: tuple[str, ...] | list[str],
    *,
    max_items: int = 4,
    max_len: int = 280,
    min_len: int = 3,
) -> list[str]:
    collected: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        try:
            nodes = soup.select(selector)
        except Exception:
            continue
        for node in nodes:
            value = _clean_lightweight_metadata_value(node.get_text(" ", strip=True), max_len=max_len)
            if len(value) < min_len:
                continue
            dedupe_key = value.lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            collected.append(value)
            if len(collected) >= max_items:
                return collected
    return collected


def _extract_definition_list_metadata(
    soup: Any,
    selectors: tuple[str, ...] | list[str],
    *,
    max_items: int = 8,
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for selector in selectors:
        try:
            roots = soup.select(selector)
        except Exception:
            roots = []
        for root in roots:
            for dt in root.select('dt'):
                dd = dt.find_next_sibling('dd')
                if dd is None:
                    continue
                key = _clean_lightweight_metadata_value(dt.get_text(" ", strip=True), max_len=64)
                value = _clean_lightweight_metadata_value(dd.get_text(" ", strip=True), max_len=320)
                if not key or not value:
                    continue
                dedupe_key = (key.lower(), value.lower())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                pairs.append((key, value))
                if len(pairs) >= max_items:
                    return pairs
    return pairs


def _extract_lightweight_metadata_items(soup: Any, source_type: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []

    if source_type in _REPOSITORY_SOURCE_TYPES:
        overview_selectors = {
            'github': (
                'p.f4.my-3',
                'div.BorderGrid-cell p.f4',
                'div[data-testid="repository-description"]',
            ),
            'gitlab': (
                'div.project-page-layout p.gl-text-subtle',
                'div.project-description',
                'div.home-panel-title + p',
            ),
            'gitee': (
                'div.project-desc',
                'div.project-intro',
                'div.repository-description',
            ),
        }
        topic_selectors = {
            'github': ('a[href*="/topics/"]',),
            'gitlab': ('a.topic-badge', 'span.gl-badge'),
            'gitee': ('a.topic-tag', 'span.ui-label'),
        }
        overviews = _collect_selector_texts(soup, overview_selectors.get(source_type, ()), max_items=1, max_len=320)
        topics = _collect_selector_texts(soup, topic_selectors.get(source_type, ()), max_items=8, max_len=40, min_len=2)
        if overviews:
            items.append(("Repository overview", overviews[0]))
        if topics:
            items.append(("Topics", ", ".join(topics[:8])))
        return items

    if source_type == 'zenodo':
        metadata = _extract_definition_list_metadata(
            soup,
            (
                'section#record-detail',
                'div.record-main',
                'div#record-page',
                'body',
            ),
            max_items=8,
        )
        preferred_order = ['doi', 'publication date', 'published', 'type', 'version', 'license', 'keywords', 'communities']
        ranked = sorted(
            metadata,
            key=lambda pair: next(
                (idx for idx, marker in enumerate(preferred_order) if marker in pair[0].lower()),
                len(preferred_order),
            ),
        )
        return ranked[:8]

    return items


def _build_lightweight_platform_note(source_type: str) -> str:
    if source_type in _REPOSITORY_SOURCE_TYPES:
        return (
            'This is a lightweight repository-page extraction focused on the landing page / README. '
            'For file trees, source code, or deeper implementation details, open the repository link directly and use page navigation.'
        )
    if source_type == 'zenodo':
        return (
            'This is a lightweight Zenodo record extraction. '
            'For full metadata, attached files, or downloads, open the record page directly.'
        )
    return (
        'This is a lightweight page extraction. '
        'If you need interactive elements or more detail, open the page directly.'
    )


def _select_primary_html_container(soup: Any, source_type: str) -> Any:
    selector_map = {
        'github': ('div#readme', 'div[data-testid="readme-content"]', 'article.markdown-body', 'main'),
        'gitlab': ('div.readme-holder', 'section.md', 'div.file-content', 'div.blob-content', 'main'),
        'gitee': ('div#readme', 'div.repository-readme', 'div.file_content', 'div.markdown-body', 'main'),
        'zenodo': ('div#collapse-description', 'div.record-main', 'section#record-detail', 'main'),
        'documentation': ('article', 'main', '[role="main"]'),
        'blog': ('article', 'main', '[role="main"]'),
        'huggingface': ('main', 'article'),
    }
    selectors = [*selector_map.get(source_type, ()), 'article', 'main', '[role="main"]', 'body']
    seen: set[str] = set()
    for selector in selectors:
        if selector in seen:
            continue
        seen.add(selector)
        try:
            node = soup.select_one(selector)
        except Exception:
            node = None
        if node is not None:
            return node
    return soup.body or soup


def _build_lightweight_page_markdown(
    title: str,
    *,
    url: str,
    source_type: str,
    extracted_text: str,
    description: str = "",
    metadata_items: list[tuple[str, str]] | None = None,
) -> str:
    body = extracted_text[:_MAX_WEB_TEXT_CHARS].strip()
    lines = [
        '--- Page 1 ---',
        f'# {title}',
        '',
        f'- **URL**: {url}',
        f'- **Source**: {_source_label_for_display(source_type)}',
    ]
    if description:
        lines.extend(['', '## Overview', description.strip()])
    if metadata_items:
        lines.append('')
        lines.append('## Metadata')
        for key, value in metadata_items:
            lines.append(f'- **{key}**: {value}')
    lines.extend([
        '',
        '## Note',
        _build_lightweight_platform_note(source_type),
    ])
    lines.extend(['', '## Extracted Content', body])
    return "\n".join(lines).strip()


def _extract_lightweight_markdown_from_html(
    html_content: str,
    *,
    url: str,
    title: str,
    source_type: str,
) -> tuple[str, str] | None:
    if not html_content.strip():
        return None

    try:
        from bs4 import BeautifulSoup
    except Exception:
        BeautifulSoup = None  # type: ignore[assignment]

    if BeautifulSoup is None:
        extracted_text = _normalize_lightweight_web_text(_extract_marker_text_from_html(html_content))
        final_title = _derive_title_from_url(url, fallback=title)
        if len(extracted_text) < 160:
            return None
        return final_title, _build_lightweight_page_markdown(
            final_title,
            url=url,
            source_type=source_type,
            extracted_text=extracted_text,
        )

    soup = BeautifulSoup(html_content, 'html.parser')
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    def _meta_content(**attrs: str) -> str:
        node = soup.find('meta', attrs=attrs)
        if node is None:
            return ''
        return str(node.get('content') or '').strip()

    extracted_title = (
        _meta_content(property='og:title')
        or _meta_content(name='twitter:title')
        or (soup.title.get_text(' ', strip=True) if soup.title else '')
    )
    content_root = _select_primary_html_container(soup, source_type)
    extracted_text = _normalize_lightweight_web_text(_extract_marker_text_from_html(str(content_root)))
    if len(extracted_text) < 240 and content_root is not (soup.body or soup):
        extracted_text = _normalize_lightweight_web_text(_extract_marker_text_from_html(str(soup.body or soup)))

    if len(extracted_text) < 160:
        return None

    description = (
        _meta_content(name='description')
        or _meta_content(property='og:description')
        or _meta_content(name='twitter:description')
    )
    metadata_items = _extract_lightweight_metadata_items(soup, source_type)
    final_title = _derive_title_from_url(url, fallback=extracted_title or title)
    markdown = _build_lightweight_page_markdown(
        final_title,
        url=url,
        source_type=source_type,
        extracted_text=extracted_text,
        description=description,
        metadata_items=metadata_items,
    )
    return final_title, markdown


def _should_try_lightweight_web_first(source_type: str) -> bool:
    return source_type in _LIGHTWEIGHT_WEB_SOURCE_TYPES


def _should_try_lightweight_web_fallback(url: str, source_type: str) -> bool:
    return source_type in _LIGHTWEIGHT_WEB_SOURCE_TYPES or (source_type == 'web' and not is_pdf_url(url))


async def _fetch_lightweight_web_markdown(
    url: str,
    title: str,
    source_type: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        'success': False,
        'title': title,
        'markdown': None,
        'error': 'download_failed',
        'error_code': None,
        'error_detail': None,
    }
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,text/plain,text/markdown;q=0.9,*/*;q=0.8',
        }
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)

        if response.status_code != 200:
            result['error_code'] = 'http_status'
            result['error_detail'] = (
                f"This page returned HTTP {response.status_code}, so automatic reading is unavailable right now. "
                "It may require login, anti-bot checks, or interactive navigation. Please open the page directly."
            )
            return result

        content = response.content
        if len(content) > _MAX_WEB_DOWNLOAD_BYTES:
            result['error'] = 'parse_failed'
            result['error_code'] = 'page_too_large'
            result['error_detail'] = (
                "This page is too large for lightweight extraction. Please open it directly for the full content."
            )
            return result

        content_type = (response.headers.get('content-type') or '').lower()
        if content[:4] == b'%PDF' or 'application/pdf' in content_type:
            result['error_code'] = 'points_to_pdf'
            result['error_detail'] = (
                "This link points to a PDF document. Please use the PDF read flow or open the PDF directly."
            )
            return result

        final_title = title
        markdown: str | None = None
        if any(kind in content_type for kind in ('text/plain', 'text/markdown')):
            plain_text = _normalize_lightweight_web_text(response.text)
            if len(plain_text) >= 160:
                final_title = _derive_title_from_url(str(response.url), fallback=title)
                markdown = _build_lightweight_page_markdown(
                    final_title,
                    url=str(response.url),
                    source_type=source_type,
                    extracted_text=plain_text,
                )
        else:
            extracted = _extract_lightweight_markdown_from_html(
                response.text,
                url=str(response.url),
                title=title,
                source_type=source_type,
            )
            if extracted is not None:
                final_title, markdown = extracted

        if not markdown:
            result['error'] = 'parse_failed'
            result['error_code'] = 'unreadable_page'
            result['error_detail'] = (
                "I could not extract enough readable content from this page. "
                "It may rely on heavy client-side rendering or interactive browsing. Please open the link directly for details."
            )
            return result

        result.update({
            'success': True,
            'title': final_title,
            'markdown': markdown,
            'error': None,
            'error_detail': None,
        })
        return result
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        result['error_code'] = 'network_unreachable'
        result['error_detail'] = "The page could not be reached because of a network connection problem. Please try again later or open it directly."
        return result
    except httpx.TimeoutException as e:
        result['error_code'] = 'request_timeout'
        result['error_detail'] = "The page took too long to respond. Please try again later or open it directly."
        return result
    except Exception as e:
        result['error'] = 'parse_failed'
        result['error_code'] = 'unexpected_error'
        result['error_detail'] = "An unexpected error occurred while preparing this page. Please open the link directly for more detail."
        return result


async def _process_lightweight_web_url(
    url: str,
    title: str,
    base_url: str,
    api_key: str,
    model: str,
    use_cache: bool = True,
) -> dict[str, Any]:
    source_type = detect_source_type(url)
    result: dict[str, Any] = {
        'url': url,
        'title': title,
        'source_type': source_type,
        'is_academic': False,
        'success': False,
        'summary': None,
        'pdf_content': None,
        'error': None,
        'error_code': None,
        'error_detail': None,
        'from_cache': False,
        'reference_card': None,
        'page_count': 1,
        'parse_method': PDF_PARSE_METHOD_WEB,
        'structured_parse_method': PDF_PARSE_METHOD_WEB,
        'high_quality_pending': False,
        'image_count': 0,
        'images_ready': False,
    }

    try:
        markdown: str | None = None
        cache_meta: dict[str, Any] | None = None
        cached = _get_cached_lightweight_document(url) if use_cache else None
        if cached is not None:
            cache_meta, markdown = cached
            result['from_cache'] = True
            result['title'] = str(cache_meta.get('title') or title)
            result['page_count'] = int(cache_meta.get('page_count') or 1)
            result['parse_method'] = str(cache_meta.get('parse_method') or PDF_PARSE_METHOD_WEB)
            result['structured_parse_method'] = str(cache_meta.get('structured_parse_method') or PDF_PARSE_METHOD_WEB)

        if not markdown:
            fetch_result = await _fetch_lightweight_web_markdown(url, title, source_type)
            if not fetch_result.get('success'):
                result['error'] = str(fetch_result.get('error') or 'download_failed')
                result['error_code'] = fetch_result.get('error_code')
                result['error_detail'] = str(fetch_result.get('error_detail') or 'Unable to fetch page content.')
                return result
            markdown = str(fetch_result.get('markdown') or '')
            result['title'] = str(fetch_result.get('title') or title)

        if not markdown.strip():
            result['error'] = 'parse_failed'
            result['error_code'] = 'empty_content'
            result['error_detail'] = (
                "Lightweight extraction returned no readable content. Please open the page directly for more detail."
            )
            return result

        academic = bool(cache_meta.get('is_academic')) if cache_meta else is_academic_content(markdown, source_type)
        result['is_academic'] = academic
        result['pdf_content'] = markdown
        result['page_count'] = max(1, _extract_page_count(markdown) or int(result.get('page_count') or 1))

        if use_cache and not result['from_cache']:
            await asyncio.to_thread(
                _save_lightweight_markdown_to_cache,
                url,
                markdown,
                str(result['title'] or title),
                source_type,
                is_academic=academic,
            )

        summary = await summarize_pdf_content(
            markdown,
            str(result['title']) if result['title'] is not None else title,
            base_url,
            api_key,
            model,
            is_academic=academic,
        )
        result['success'] = True
        result['summary'] = summary
        result['reference_card'] = format_reference_card(
            str(result['title']) if result['title'] is not None else title,
            url,
            source_type,
            is_academic=academic,
        )
        return result
    except Exception as e:
        logger.error(f"Error processing lightweight page {url}: {e}")
        result['error'] = 'parse_failed'
        result['error_code'] = 'unexpected_error'
        result['error_detail'] = "An unexpected error occurred while processing this page. Please open the link directly for more detail."
        return result


def _extract_page_count(markdown: str) -> int:
    """Return the total page count from markdown with '--- Page X ---' markers.

    Scans all '--- Page X ---' markers and returns the maximum X found, which
    equals the total number of pages parsed.  Returns 0 if no markers are found.
    """
    page_nums = [int(m) for m in re.findall(r'--- Page (\d+) ---', markdown)]
    return max(page_nums) if page_nums else 0


def _extract_arxiv_id(url: str) -> str | None:
    match = re.search(r'arxiv\.org/(?:abs|pdf|html)/([\w\.\-]+)', url, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).replace('.pdf', '')


def _extract_openreview_id(url: str) -> str | None:
    match = re.search(r'openreview\.net/(?:forum|note|pdf)\?id=([^&#]+)', url, re.IGNORECASE)
    if not match:
        return None
    return match.group(1)


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
        title_for_lookup = str(meta.get('title') or '')
        source_type = str(meta.get('source_type') or detect_source_type(url))
        meta['source_type'] = source_type
        meta['source_priority'] = _cached_article_source_priority_for_source(source_type)
        meta['normalized_title'] = _normalize_cached_article_lookup_text(title_for_lookup)
        meta['doi'] = _extract_doi(url)
        meta['arxiv_id'] = _extract_arxiv_id(url)
        meta['openreview_id'] = _extract_openreview_id(url)
        with open(meta_file, 'w') as f:
            json.dump(meta, f, indent=2)
    except Exception as e:
        logger.error(f"Error updating meta for {url}: {e}")


def _record_high_quality_upgrade_state(
    url: str,
    status: str,
    detail: str,
    *,
    level: str = "info",
    **extra_fields: Any,
) -> None:
    """Record internal high-quality upgrade state to backend logs and cache meta."""
    _update_meta_fields(
        url,
        high_quality_upgrade_status=status,
        high_quality_upgrade_detail=detail,
        high_quality_upgrade_updated_at=datetime.now().isoformat(),
        **extra_fields,
    )
    log_fn = getattr(logger, level, logger.info)
    log_fn(f"[PDFUpgrade] {status} | {url} | {detail}")


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
        structured_content = json.loads(structured_file.read_text(encoding='utf-8'))
        if not isinstance(structured_content, dict):
            return None
        schema_version = _safe_int(structured_content.get("schema_version"), 0)
        if schema_version < STRUCTURED_SCHEMA_VERSION:
            logger.info(
                f"Ignoring stale structured cache for {url}: "
                f"schema_version={schema_version}, expected>={STRUCTURED_SCHEMA_VERSION}"
            )
            return None
        if not isinstance(structured_content.get("blocks"), list):
            return None
        return structured_content
    except Exception:
        return None


def _save_markdown_to_cache(
    url: str,
    markdown: str,
    _paper_title: str = "",
    structured_content: dict[str, Any] | None = None,
    *,
    high_quality_pending: bool = False,
) -> None:
    """Save pymupdf-parsed markdown to cache (fast tier)."""
    del _paper_title
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
    except Exception as e:
        logger.error(f"Error saving markdown to cache: {e}")


def _get_high_quality_cache_method(url: str) -> str | None:
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        for suffix, method in HIGH_QUALITY_CACHE_SUFFIXES:
            if (cache_dir / f"{url_hash}{suffix}").exists():
                return method
        return None
    except Exception:
        return None


def _has_high_quality_cache(url: str) -> bool:
    return _get_high_quality_cache_method(url) is not None


def _save_marker_to_cache(
    url: str,
    markdown: str,
    _paper_title: str = "",
    structured_content: dict[str, Any] | None = None,
) -> None:
    """Save Marker high-quality parse result to cache."""
    del _paper_title
    try:
        cache_dir = _get_pdf_cache_dir()
        url_hash = _get_url_hash(url)
        marker_file = cache_dir / f"{url_hash}{MARKER_CACHE_SUFFIX}"
        marker_file.write_text(markdown, encoding='utf-8')
        page_count = _extract_page_count(markdown)
        _save_structured_to_cache(
            url,
            structured_content or _build_document_graph_from_markdown(markdown, PDF_PARSE_METHOD_MARKER),
        )
        _update_meta_fields(
            url,
            page_count=page_count,
            parse_method=PDF_PARSE_METHOD_MARKER,
            structured_parse_method=PDF_PARSE_METHOD_MARKER,
            structured_parse_ready=True,
            high_quality_parse_pending=False,
            high_quality_parse_ready=True,
            high_quality_upgrade_status=PDF_UPGRADE_STATUS_COMPLETED,
            high_quality_upgrade_detail="High-quality Marker cache is ready",
            high_quality_upgrade_updated_at=datetime.now().isoformat(),
        )
        logger.info(f"Cached Marker markdown for {url} ({page_count} pages)")
    except Exception as e:
        logger.error(f"Error saving Marker markdown to cache: {e}")


# ── Vector Index Helper ─────────────────────────────────────────────────────

def _run_vector_index_sync(
    url_hash: str,
    markdown: str,
    paper_title: str,
    structured_content: dict[str, Any] | None = None,
) -> int:
    """Index PDF content into the vector store in a worker thread."""
    from .chat_pdf_vectorstore import index_pdf_to_vectorstore
    return index_pdf_to_vectorstore(
        url_hash,
        markdown,
        paper_title or "Unknown",
        structured_content=structured_content,
    )


def _register_vector_index_task(url_hash: str, task: asyncio.Task[None]) -> None:
    _vector_index_tasks[url_hash] = task

    def _cleanup(completed_task: asyncio.Task[None]) -> None:
        current_task = _vector_index_tasks.get(url_hash)
        if current_task is completed_task:
            _vector_index_tasks.pop(url_hash, None)
        try:
            completed_task.result()
        except asyncio.CancelledError:
            logger.info(f"[VectorIndex] Background indexing cancelled for {url_hash}")
        except Exception as e:
            logger.error(f"[VectorIndex] Background indexing failed for {url_hash}: {e}")

        if url_hash in _vector_index_pending and url_hash not in _vector_index_tasks:
            logger.info(f"[VectorIndex] Rescheduling pending background index for {url_hash}")
            next_task = asyncio.create_task(_run_vector_index_worker(url_hash))
            _register_vector_index_task(url_hash, next_task)

    task.add_done_callback(_cleanup)


async def _run_vector_index_worker(url_hash: str) -> None:
    semaphore = _get_vector_index_semaphore()
    while True:
        async with semaphore:
            payload = _vector_index_pending.pop(url_hash, None)
            if payload is None:
                logger.info(f"[VectorIndex] No pending job found for {url_hash}; worker exiting")
                return

            parse_method = str(payload.get("parse_method") or "unknown")
            logger.info(
                f"[VectorIndex] Starting background index for {url_hash} "
                f"(parse_method={parse_method}, max_concurrent={PDF_VECTOR_INDEX_MAX_CONCURRENT})"
            )
            try:
                indexed = await asyncio.to_thread(
                    _run_vector_index_sync,
                    url_hash,
                    str(payload.get("markdown") or ""),
                    str(payload.get("paper_title") or "Unknown"),
                    payload.get("structured_content") if isinstance(payload, dict) else None,
                )
                logger.info(
                    f"[VectorIndex] Finished background index for {url_hash}: "
                    f"{indexed} chunks (parse_method={parse_method})"
                )
            except Exception as e:
                logger.error(f"[VectorIndex] Failed background index for {url_hash}: {e}")

        if url_hash not in _vector_index_pending:
            return


def _trigger_vector_index(
    url_hash: str,
    markdown: str,
    paper_title: str,
    structured_content: dict[str, Any] | None = None,
) -> None:
    """Schedule PDF vector indexing in the background, coalescing repeated requests per URL."""
    try:
        parse_method = "unknown"
        if isinstance(structured_content, dict):
            parse_method = str(structured_content.get("parse_method") or parse_method)

        _vector_index_pending[url_hash] = {
            "markdown": markdown,
            "paper_title": paper_title or "Unknown",
            "structured_content": structured_content,
            "parse_method": parse_method,
        }

        existing_task = _vector_index_tasks.get(url_hash)
        if existing_task is not None and not existing_task.done():
            logger.info(
                f"[VectorIndex] Updated pending background index for {url_hash} "
                f"(parse_method={parse_method})"
            )
            return

        task = asyncio.create_task(_run_vector_index_worker(url_hash))
        _register_vector_index_task(url_hash, task)
        logger.info(
            f"[VectorIndex] Scheduled background index for {url_hash} "
            f"(parse_method={parse_method})"
        )
    except RuntimeError as e:
        logger.warning(f"[VectorIndex] No running event loop for {url_hash}: {e}")
    except Exception as e:
        logger.error(f"[VectorIndex] Failed to schedule index for {url_hash}: {e}")


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


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_bbox(raw_bbox: Any) -> dict[str, Any] | None:
    if raw_bbox is None:
        return None

    coord_origin = None
    values: tuple[Any, Any, Any, Any] | None = None

    if isinstance(raw_bbox, dict):
        if all(key in raw_bbox for key in ("l", "t", "r", "b")):
            values = (raw_bbox.get("l"), raw_bbox.get("t"), raw_bbox.get("r"), raw_bbox.get("b"))
        elif all(key in raw_bbox for key in ("x0", "y0", "x1", "y1")):
            values = (raw_bbox.get("x0"), raw_bbox.get("y0"), raw_bbox.get("x1"), raw_bbox.get("y1"))
        coord_origin = raw_bbox.get("coord_origin")
    elif isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) >= 4:
        values = (raw_bbox[0], raw_bbox[1], raw_bbox[2], raw_bbox[3])
    else:
        if hasattr(raw_bbox, "as_tuple"):
            try:
                values = tuple(raw_bbox.as_tuple())[:4]  # type: ignore[assignment]
            except Exception:
                values = None
        if values is None:
            l = getattr(raw_bbox, "l", getattr(raw_bbox, "x0", None))
            t = getattr(raw_bbox, "t", getattr(raw_bbox, "y0", None))
            r = getattr(raw_bbox, "r", getattr(raw_bbox, "x1", None))
            b = getattr(raw_bbox, "b", getattr(raw_bbox, "y1", None))
            if None not in (l, t, r, b):
                values = (l, t, r, b)
        coord_origin = getattr(raw_bbox, "coord_origin", coord_origin)

    if values is None:
        return None

    try:
        left, top, right, bottom = (float(v) for v in values)
    except (TypeError, ValueError):
        return None

    coord_value = getattr(coord_origin, "value", coord_origin)
    return {
        "l": left,
        "t": top,
        "r": right,
        "b": bottom,
        "coord_origin": _coerce_text(coord_value) or "TOPLEFT",
    }


def _build_markdown_table_from_rows(rows: list[list[str]]) -> str:
    normalized_rows = [
        [str(cell).strip() for cell in row]
        for row in rows
        if isinstance(row, list) and any(str(cell).strip() for cell in row)
    ]
    if not normalized_rows:
        return ""

    header = normalized_rows[0]
    separator = ["---"] * len(header)
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in normalized_rows[1:]:
        padded = row + [""] * max(0, len(header) - len(row))
        lines.append("| " + " | ".join(padded[:len(header)]) + " |")
    return "\n".join(lines)


def _extract_markdown_image(markdown_text: str) -> tuple[str, str]:
    match = re.search(r'!\[([^\]]*)\]\(([^)]+)\)', markdown_text)
    if not match:
        return "", ""
    return match.group(1).strip(), match.group(2).strip()


def _make_page_node(page_num: int) -> dict[str, Any]:
    return {
        "id": f"page-{page_num}",
        "type": "section",
        "title": f"Page {page_num}",
        "page_start": page_num,
        "page_end": page_num,
        "children": [],
    }


def _append_blocks_from_markdown_text(
    *,
    page_num: int,
    page_text: str,
    page_node: dict[str, Any],
    blocks: list[dict[str, Any]],
    next_block_id: Callable[[str, int], str],
    current_path: list[str] | None = None,
    base_payload: dict[str, Any] | None = None,
) -> list[str]:
    if not page_text.strip():
        return list(current_path or [])

    working_path = list(current_path or [])
    common_payload = dict(base_payload or {})
    paragraph_buffer: list[str] = []
    table_buffer: list[str] = []
    equation_buffer: list[str] = []
    in_equation = False

    def _append_block(block_type: str, **payload: Any) -> None:
        block_id = next_block_id(block_type, page_num)
        merged_payload = {
            **common_payload,
            **payload,
        }
        merged_payload.setdefault("section_path", working_path.copy())
        block = {
            "id": block_id,
            "type": block_type,
            "page": page_num,
            "parent_id": page_node["id"],
            **merged_payload,
        }
        blocks.append(block)
        page_node["children"].append(block_id)

    def _flush_paragraph() -> None:
        if not paragraph_buffer:
            return
        text = "\n".join(paragraph_buffer).strip()
        paragraph_buffer.clear()
        if text:
            _append_block("paragraph", text=text, section_path=working_path.copy())

    def _flush_table() -> None:
        if not table_buffer:
            return
        table_markdown = "\n".join(table_buffer).strip()
        rows = _parse_markdown_table_rows(table_buffer)
        table_buffer.clear()
        if table_markdown:
            _append_block(
                "table",
                markdown=table_markdown,
                cells=rows,
                caption="",
                section_path=working_path.copy(),
            )

    def _flush_equation() -> None:
        if not equation_buffer:
            return
        latex = "\n".join(equation_buffer).strip()
        equation_buffer.clear()
        if latex:
            _append_block(
                "equation",
                latex=latex,
                surrounding_text="",
                section_path=working_path.copy(),
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
            working_path = working_path[: max(level - 1, 0)]
            working_path.append(title)
            _append_block(
                "section",
                text=title,
                level=level,
                section_path=working_path.copy(),
            )
            continue

        if image_match:
            _flush_paragraph()
            _flush_table()
            _append_block(
                "figure",
                image=image_match.group(2).strip(),
                caption=image_match.group(1).strip(),
                vision_summary="",
                section_path=working_path.copy(),
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
    return working_path


def _build_document_graph_from_markdown(markdown: str, parse_method: PdfParseMethod) -> dict[str, Any]:
    """Normalize markdown into a lightweight Document Graph / Block Graph sidecar."""
    page_entries = _split_md_into_pages(markdown)
    blocks: list[dict[str, Any]] = []
    section_nodes: list[dict[str, Any]] = []
    block_counter = 0
    current_path: list[str] = []

    def _next_block_id(prefix: str, page_num: int) -> str:
        nonlocal block_counter
        block_counter += 1
        return f"{prefix}-p{page_num}-{block_counter}"

    for page_num, page_text in page_entries:
        page_node = _make_page_node(page_num)
        section_nodes.append(page_node)
        current_path = _append_blocks_from_markdown_text(
            page_num=page_num,
            page_text=page_text,
            page_node=page_node,
            blocks=blocks,
            next_block_id=_next_block_id,
            current_path=current_path,
            base_payload={
                "source_backend": parse_method,
                "native_label": "markdown",
                "native_ref": f"markdown-page-{page_num}",
            },
        )

    return {
        "schema_version": STRUCTURED_SCHEMA_VERSION,
        "type": "document",
        "parse_method": parse_method,
        "page_count": _extract_page_count(markdown),
        "children": section_nodes,
        "blocks": blocks,
    }


def _marker_image_block_id_from_name(image_name: str) -> str:
    stem = Path(image_name).stem
    if not stem:
        return ""
    return stem.replace("_", "/")


def _normalize_marker_markdown(markdown: str, first_page_id: int | None) -> str:
    page_offset = 1 if first_page_id == 0 else 0

    def _replace_page_marker(match: re.Match[str]) -> str:
        page_num = int(match.group(1)) + page_offset
        return f"--- Page {page_num} ---"

    return re.sub(r"\{(\d+)\}<<<PATHLAB_MARKER_PAGE_BREAK>>>", _replace_page_marker, markdown).strip()


def _extract_marker_text_from_html(html_content: str) -> str:
    if not html_content:
        return ""
    try:
        from bs4 import BeautifulSoup

        text = BeautifulSoup(html_content, "html.parser").get_text("\n", strip=True)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html_content)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _extract_marker_table_rows(html_content: str) -> list[list[str]]:
    if not html_content:
        return []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, "html.parser")
        table = soup.find("table")
        if table is None:
            return []
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        return rows
    except Exception:
        return []


def _collect_marker_section_titles(node: dict[str, Any], title_map: dict[str, str]) -> None:
    block_type = _coerce_text(node.get("block_type")).lower()
    node_id = _coerce_text(node.get("id"))
    if block_type == "sectionheader" and node_id:
        title_text = _extract_marker_text_from_html(_coerce_text(node.get("html")))
        if title_text:
            title_map[node_id] = title_text
    for child in node.get("children") or []:
        if isinstance(child, dict):
            _collect_marker_section_titles(child, title_map)


def _resolve_marker_section_path(section_hierarchy: Any, title_map: dict[str, str]) -> list[str]:
    if not isinstance(section_hierarchy, dict):
        return []
    resolved: list[str] = []
    def _sort_key(item: tuple[Any, Any]) -> tuple[int, str]:
        key_text = _coerce_text(item[0])
        try:
            return (0, f"{int(key_text):06d}")
        except Exception:
            return (1, key_text)

    for value in (item[1] for item in sorted(section_hierarchy.items(), key=_sort_key)):
        title = title_map.get(_coerce_text(value), _coerce_text(value))
        if title and title not in resolved:
            resolved.append(title)
    return resolved


def _find_marker_image_url(node: dict[str, Any], image_url_map: dict[str, str]) -> str:
    node_id = _coerce_text(node.get("id"))
    if node_id and image_url_map.get(node_id):
        return image_url_map[node_id]
    for child in node.get("children") or []:
        if isinstance(child, dict):
            image_url = _find_marker_image_url(child, image_url_map)
            if image_url:
                return image_url
    return ""


def _collect_marker_caption_text(node: dict[str, Any]) -> str:
    parts: list[str] = []
    self_text = _extract_marker_text_from_html(_coerce_text(node.get("html")))
    if self_text:
        parts.append(self_text)
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        child_type = _coerce_text(child.get("block_type")).lower()
        if child_type == "caption":
            caption_text = _extract_marker_text_from_html(_coerce_text(child.get("html")))
            if caption_text:
                parts.append(caption_text)
    deduped: list[str] = []
    for part in parts:
        if part not in deduped:
            deduped.append(part)
    return "\n".join(deduped).strip()


def _build_document_graph_from_marker_document(
    rendered_json: dict[str, Any],
    parse_method: PdfParseMethod,
    *,
    max_pages: int = 0,
    page_count_hint: int = 0,
    image_url_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    section_nodes: list[dict[str, Any]] = []
    page_node_map: dict[int, dict[str, Any]] = {}
    block_counter = 0
    image_url_map = image_url_map or {}
    section_title_map: dict[str, str] = {}

    for child in rendered_json.get("children") or []:
        if isinstance(child, dict):
            _collect_marker_section_titles(child, section_title_map)

    initial_page_count = page_count_hint if page_count_hint > 0 else max_pages
    for page_num in range(1, max(initial_page_count, 0) + 1):
        page_node = _make_page_node(page_num)
        section_nodes.append(page_node)
        page_node_map[page_num] = page_node

    def _next_block_id(prefix: str, page_num: int) -> str:
        nonlocal block_counter
        block_counter += 1
        return f"{prefix}-p{page_num}-{block_counter}"

    def _get_page_node(page_num: int) -> dict[str, Any]:
        if page_num not in page_node_map:
            page_node = _make_page_node(page_num)
            page_node_map[page_num] = page_node
            section_nodes.append(page_node)
        return page_node_map[page_num]

    def _append_block(page_num: int, block_type: str, **payload: Any) -> None:
        page_node = _get_page_node(page_num)
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

    def _walk(node: dict[str, Any], page_num: int, current_path: list[str], parent_type: str = "") -> None:
        raw_type = _coerce_text(node.get("block_type"))
        normalized_type = raw_type.lower()
        if not normalized_type or normalized_type == "page":
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    _walk(child, page_num, current_path, normalized_type)
            return

        if normalized_type in {"pageheader", "pagefooter", "footnote", "reference"}:
            return

        node_id = _coerce_text(node.get("id"))
        html_content = _coerce_text(node.get("html"))
        text = _extract_marker_text_from_html(html_content)
        bbox = _normalize_bbox(node.get("bbox"))
        resolved_path = _resolve_marker_section_path(node.get("section_hierarchy"), section_title_map) or current_path.copy()
        base_payload = {
            "bbox": bbox,
            "section_path": resolved_path.copy(),
            "source_backend": PDF_PARSE_METHOD_MARKER,
            "native_label": raw_type,
            "native_ref": node_id,
        }

        next_path = resolved_path.copy()
        if normalized_type == "sectionheader":
            title_text = text
            if title_text:
                next_path = resolved_path or [title_text]
                if next_path[-1] != title_text:
                    next_path = [*next_path, title_text]
                _append_block(
                    page_num,
                    "section",
                    text=title_text,
                    level=max(1, len(next_path)),
                    **{**base_payload, "section_path": next_path.copy()},
                )
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    _walk(child, page_num, next_path, normalized_type)
            return

        if normalized_type == "table":
            cells = _extract_marker_table_rows(html_content)
            table_markdown = _build_markdown_table_from_rows(cells)
            _append_block(
                page_num,
                "table",
                caption=_collect_marker_caption_text(node),
                markdown=table_markdown,
                cells=cells,
                image=_find_marker_image_url(node, image_url_map),
                **base_payload,
            )
            for child in node.get("children") or []:
                if isinstance(child, dict) and _coerce_text(child.get("block_type")).lower() not in {"caption", "picture", "table"}:
                    _walk(child, page_num, next_path, normalized_type)
            return

        if normalized_type in {"picture", "figure"}:
            image_url = _find_marker_image_url(node, image_url_map)
            caption = _collect_marker_caption_text(node)
            if image_url or caption:
                _append_block(
                    page_num,
                    "figure",
                    image=image_url,
                    caption=caption,
                    vision_summary="",
                    **base_payload,
                )
            for child in node.get("children") or []:
                if isinstance(child, dict) and _coerce_text(child.get("block_type")).lower() not in {"caption", "picture", "figure"}:
                    _walk(child, page_num, next_path, normalized_type)
            return

        if normalized_type in {"equation", "formula"} and text:
            _append_block(
                page_num,
                "equation",
                latex=text,
                surrounding_text="",
                **base_payload,
            )
        elif normalized_type == "code" and text:
            _append_block(page_num, "code", text=text, **base_payload)
        elif normalized_type.startswith("list") and text:
            _append_block(page_num, "list", text=text, **base_payload)
        elif normalized_type == "caption" and parent_type in {"picture", "figure", "table"}:
            return
        elif text:
            _append_block(page_num, "paragraph", text=text, **base_payload)

        for child in node.get("children") or []:
            if isinstance(child, dict):
                _walk(child, page_num, next_path, normalized_type)

    pages = [child for child in rendered_json.get("children") or [] if isinstance(child, dict)]
    for page_index, page in enumerate(pages, start=1):
        if max_pages > 0 and page_index > max_pages:
            break
        _get_page_node(page_index)
        for child in page.get("children") or []:
            if isinstance(child, dict):
                _walk(child, page_index, [], "page")

    section_nodes.sort(key=lambda node: int(node.get("page_start") or 0))
    total_pages = page_count_hint or len(pages)
    page_count = min(total_pages, max_pages) if max_pages > 0 else total_pages
    return {
        "schema_version": STRUCTURED_SCHEMA_VERSION,
        "type": "document",
        "parse_method": parse_method,
        "page_count": page_count,
        "children": section_nodes,
        "blocks": blocks,
    }


def _build_document_graph_from_pymupdf_chunks(
    page_chunks: list[dict[str, Any]],
    parse_method: PdfParseMethod,
) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    section_nodes: list[dict[str, Any]] = []
    block_counter = 0
    current_path: list[str] = []

    def _next_block_id(prefix: str, page_num: int) -> str:
        nonlocal block_counter
        block_counter += 1
        return f"{prefix}-p{page_num}-{block_counter}"

    for chunk in page_chunks:
        metadata = chunk.get("metadata", {}) if isinstance(chunk, dict) else {}
        page_num = _safe_int(metadata.get("page", metadata.get("page_number", 0)), 0)
        if page_num <= 0:
            continue
        page_text = str(chunk.get("text") or "")
        page_node = _make_page_node(page_num)
        section_nodes.append(page_node)

        page_boxes = chunk.get("page_boxes")
        if not isinstance(page_boxes, list) or not page_boxes:
            current_path = _append_blocks_from_markdown_text(
                page_num=page_num,
                page_text=page_text,
                page_node=page_node,
                blocks=blocks,
                next_block_id=_next_block_id,
                current_path=current_path,
                base_payload={
                    "source_backend": PDF_PARSE_METHOD_PYMUPDF,
                    "native_label": "text",
                    "native_ref": f"pymupdf-page-{page_num}",
                },
            )
            continue

        block_count_before = len(blocks)
        for page_box in page_boxes:
            if not isinstance(page_box, dict):
                continue
            position = page_box.get("pos")
            box_text = ""
            if isinstance(position, (list, tuple)) and len(position) >= 2:
                start = _safe_int(position[0], 0)
                stop = _safe_int(position[1], 0)
                box_text = page_text[start:stop].strip()

            native_label = (_coerce_text(page_box.get("class")) or "text").lower()
            bbox = _normalize_bbox(page_box.get("bbox"))
            native_ref = f"page-box-{page_num}-{_safe_int(page_box.get('index'), len(blocks))}"
            base_payload = {
                "bbox": bbox,
                "source_backend": PDF_PARSE_METHOD_PYMUPDF,
                "native_label": native_label,
                "native_ref": native_ref,
            }

            if native_label == "table":
                rows = _parse_markdown_table_rows(box_text.splitlines())
                blocks.append({
                    "id": _next_block_id("table", page_num),
                    "type": "table",
                    "page": page_num,
                    "parent_id": page_node["id"],
                    "caption": "",
                    "markdown": box_text,
                    "cells": rows,
                    "section_path": current_path.copy(),
                    **base_payload,
                })
                page_node["children"].append(blocks[-1]["id"])
                continue

            if native_label in {"picture", "image"}:
                caption, image = _extract_markdown_image(box_text)
                if image or caption or box_text:
                    blocks.append({
                        "id": _next_block_id("figure", page_num),
                        "type": "figure",
                        "page": page_num,
                        "parent_id": page_node["id"],
                        "image": image,
                        "caption": caption or box_text,
                        "vision_summary": "",
                        "section_path": current_path.copy(),
                        **base_payload,
                    })
                    page_node["children"].append(blocks[-1]["id"])
                continue

            current_path = _append_blocks_from_markdown_text(
                page_num=page_num,
                page_text=box_text,
                page_node=page_node,
                blocks=blocks,
                next_block_id=_next_block_id,
                current_path=current_path,
                base_payload=base_payload,
            )

        if len(blocks) == block_count_before and page_text:
            current_path = _append_blocks_from_markdown_text(
                page_num=page_num,
                page_text=page_text,
                page_node=page_node,
                blocks=blocks,
                next_block_id=_next_block_id,
                current_path=current_path,
                base_payload={
                    "source_backend": PDF_PARSE_METHOD_PYMUPDF,
                    "native_label": "text",
                    "native_ref": f"pymupdf-page-{page_num}",
                },
            )

    section_nodes.sort(key=lambda node: int(node.get("page_start") or 0))
    return {
        "schema_version": STRUCTURED_SCHEMA_VERSION,
        "type": "document",
        "parse_method": parse_method,
        "page_count": max((int(node.get("page_start") or 0) for node in section_nodes), default=0),
        "children": section_nodes,
        "blocks": blocks,
    }


def _to_parsed_pdf_result(
    markdown: str,
    parse_method: PdfParseMethod,
    structured_content: dict[str, Any] | None = None,
) -> ParsedPdfResult:
    structured_content = structured_content or _build_document_graph_from_markdown(markdown, parse_method)
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
        for suffix, _ in CACHED_MARKDOWN_CANDIDATES:
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


async def _parse_pdf_with_marker_best_effort(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir: Path | None,
    images_url_prefix: str | None,
    upgrade_url: str | None = None,
) -> ParsedPdfResult | None:
    """Run Marker via GPU queue when possible.

    Foreground parses may fall back to CPU. Background upgrades skip CPU fallback
    so they do not consume the only foreground PDF parse slot under load.
    """
    skip_gpu_queue, routing_detail = _should_skip_marker_gpu_queue()
    fallback_detail = "GPU Marker path unavailable or failed; retrying high-quality upgrade on CPU"
    logger.info(f"[Marker] Best-effort routing decision: {routing_detail}")
    marker_result: ParsedPdfResult | None = None
    if not skip_gpu_queue:
        try:
            marker_result = await _parse_pdf_with_marker_via_gpu_queue(
                pdf_bytes,
                max_pages,
                images_output_dir,
                images_url_prefix,
                upgrade_url=upgrade_url,
            )
        except MarkerGpuQueueTimeout as e:
            fallback_detail = str(e)
            marker_result = None
    else:
        fallback_detail = routing_detail
        marker_result = await _parse_pdf_with_marker_direct_gpu_if_available(
            pdf_bytes,
            max_pages,
            images_output_dir,
            images_url_prefix,
        )

    if marker_result is None:
        if upgrade_url:
            _record_high_quality_upgrade_state(
                upgrade_url,
                PDF_UPGRADE_STATUS_SKIPPED,
                f"{fallback_detail}; skipping CPU fallback for background upgrade to protect foreground PDF parsing capacity",
                high_quality_parse_pending=False,
                high_quality_parse_ready=False,
            )
            return None
        marker_result = await _parse_pdf_with_marker_on_cpu(
            pdf_bytes,
            max_pages,
            images_output_dir,
            images_url_prefix,
        )
    if marker_result is None:
        return None
    return marker_result


def _register_marker_upgrade_task(url_hash: str, task: asyncio.Task[None]) -> None:
    _marker_upgrade_tasks[url_hash] = task

    def _cleanup(completed_task: asyncio.Task[None]) -> None:
        current_task = _marker_upgrade_tasks.get(url_hash)
        if current_task is completed_task:
            _marker_upgrade_tasks.pop(url_hash, None)
        try:
            completed_task.result()
        except asyncio.CancelledError:
            logger.info(f"Background Marker upgrade cancelled for {url_hash}")
        except Exception as e:
            logger.error(f"Background Marker upgrade failed for {url_hash}: {e}")

    task.add_done_callback(_cleanup)


async def _run_marker_background_upgrade(url: str, title: str, pdf_bytes: bytes) -> None:
    """Upgrade a fast PyMuPDF parse opportunistically in the background.

    Background upgrades must never queue behind foreground parses. They only run
    when the shared PDF parse capacity is fully idle.
    """
    if _has_high_quality_cache(url):
        _record_high_quality_upgrade_state(
            url,
            PDF_UPGRADE_STATUS_COMPLETED,
            "High-quality cache already exists; skipping background upgrade",
            high_quality_parse_pending=False,
            high_quality_parse_ready=True,
        )
        return

    url_hash = _get_url_hash(url)
    images_output_dir = _get_pdf_cache_dir() / "images" / url_hash
    images_url_prefix = f"{Config.GATEWAY_SERVICE_URL}/pdf-images/{url_hash}"
    try:
        if PDF_BACKGROUND_UPGRADE_IDLE_GRACE_SECONDS > 0:
            logger.info(
                f"[PDFUpgrade] Waiting {PDF_BACKGROUND_UPGRADE_IDLE_GRACE_SECONDS:.3f}s idle grace window "
                f"before background Marker upgrade for {url_hash}"
            )
            await asyncio.sleep(PDF_BACKGROUND_UPGRADE_IDLE_GRACE_SECONDS)

        if _has_high_quality_cache(url):
            _record_high_quality_upgrade_state(
                url,
                PDF_UPGRADE_STATUS_COMPLETED,
                "High-quality cache became available during the idle grace window; skipping background upgrade",
                high_quality_parse_pending=False,
                high_quality_parse_ready=True,
            )
            return

        is_idle, idle_detail = _is_pdf_parse_idle()
        if not is_idle:
            _record_high_quality_upgrade_state(
                url,
                PDF_UPGRADE_STATUS_SKIPPED,
                f"Background Marker upgrade skipped to preserve foreground priority: {idle_detail}",
                level="warning",
                high_quality_parse_pending=False,
                high_quality_parse_ready=False,
            )
            return

        _record_high_quality_upgrade_state(
            url,
            PDF_UPGRADE_STATUS_RUNNING,
            "Background Marker upgrade started after confirming foreground PDF parse capacity is idle; it will not queue on the foreground parse semaphore",
            high_quality_parse_pending=True,
            high_quality_parse_ready=False,
        )

        async def _run_upgrade_parse() -> ParsedPdfResult | None:
            return await _parse_pdf_with_marker_best_effort(
                pdf_bytes,
                0,
                images_output_dir,
                images_url_prefix,
                upgrade_url=url,
            )

        result = await _run_upgrade_parse()

        if result is None:
            logger.info(f"Background Marker upgrade skipped for {url_hash} due to current system load")
            return
        if not result.markdown or result.markdown.startswith("[Error"):
            _record_high_quality_upgrade_state(
                url,
                PDF_UPGRADE_STATUS_FAILED,
                "Background Marker upgrade produced no usable result",
                level="warning",
                high_quality_parse_pending=False,
                high_quality_parse_ready=False,
            )
            return

        await _save_marker_to_cache_async(
            url,
            result.markdown,
            paper_title=title,
            structured_content=result.structured_content,
        )
        _record_high_quality_upgrade_state(
            url,
            PDF_UPGRADE_STATUS_COMPLETED,
            "Background Marker upgrade completed; high-quality Marker cache is ready",
            high_quality_parse_pending=False,
            high_quality_parse_ready=True,
        )
    except Exception as e:
        _record_high_quality_upgrade_state(
            url,
            PDF_UPGRADE_STATUS_FAILED,
            f"Background Marker upgrade error: {e}",
            level="error",
            high_quality_parse_pending=False,
            high_quality_parse_ready=False,
        )


def schedule_marker_upgrade(url: str, title: str, pdf_bytes: bytes) -> bool:
    """Schedule a background Marker upgrade unless one is already cached or running."""
    url_hash = _get_url_hash(url)
    if not PDF_ENABLE_BACKGROUND_MARKER_UPGRADE:
        _record_high_quality_upgrade_state(
            url,
            PDF_UPGRADE_STATUS_DISABLED,
            "Background Marker upgrade disabled by config (PDF_ENABLE_BACKGROUND_MARKER_UPGRADE=false)",
            high_quality_parse_pending=False,
            high_quality_parse_ready=False,
        )
        logger.info(
            f"[PDFUpgrade] disabled by config for {url_hash}; "
            "skip scheduling background Marker upgrade"
        )
        return False

    if _has_high_quality_cache(url):
        _record_high_quality_upgrade_state(
            url,
            PDF_UPGRADE_STATUS_COMPLETED,
            "High-quality cache already exists; no background upgrade needed",
            high_quality_parse_pending=False,
            high_quality_parse_ready=True,
        )
        return False

    existing_task = _marker_upgrade_tasks.get(url_hash)
    if existing_task is not None and not existing_task.done():
        _record_high_quality_upgrade_state(
            url,
            PDF_UPGRADE_STATUS_SCHEDULED,
            "Background Marker upgrade already scheduled or running",
            high_quality_parse_pending=True,
            high_quality_parse_ready=False,
        )
        return False

    _record_high_quality_upgrade_state(
        url,
        PDF_UPGRADE_STATUS_SCHEDULED,
        f"Scheduled background Marker upgrade for '{title}' after fast parse",
        high_quality_parse_pending=True,
        high_quality_parse_ready=False,
    )
    task = asyncio.create_task(_run_marker_background_upgrade(url, title, pdf_bytes))
    _register_marker_upgrade_task(url_hash, task)
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
) -> tuple[str, list[dict[str, Any]]] | None:
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
        logger.info(
            f"[PyMuPDF] Starting fast parse: bytes={len(pdf_bytes)}, max_pages={max_pages}, "
            f"image_export={images_output_dir is not None}"
        )
        tmp_file.write(pdf_bytes)
        tmp_file.close()

        logger.info(f"[PyMuPDF] Opening temporary PDF file: {tmp_file.name}")
        doc = pymupdf.open(tmp_file.name)
        total_pages = len(doc)
        pages_to_process = min(total_pages, max_pages) if max_pages > 0 else total_pages
        page_list = list(range(pages_to_process))
        logger.info(
            f"[PyMuPDF] Document opened: total_pages={total_pages}, pages_to_process={pages_to_process}"
        )

        # Determine whether to extract images
        write_images = images_output_dir is not None
        image_path = str(images_output_dir) if write_images else ""
        if write_images:
            images_output_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"[PyMuPDF] Image export enabled: {image_path}")

        logger.info("[PyMuPDF] Calling pymupdf4llm.to_markdown(page_chunks=True)")
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
        logger.info(f"[PyMuPDF] to_markdown completed: page_chunks={len(md_text)}")

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
        logger.info("[PyMuPDF] Building structured content from page chunks")
        structured_content = _build_document_graph_from_pymupdf_chunks(md_text, PDF_PARSE_METHOD_PYMUPDF)
        logger.info(
            f"PyMuPDF fast extraction OK: {total_chars} chars, "
            f"{len(page_sections)} pages, {img_count} images, "
            f"{len(structured_content.get('blocks', []))} structured blocks"
        )
        return md_content, md_text

    except Exception as e:
        logger.error(f"PyMuPDF extraction failed: {e}\n{traceback.format_exc()}")
        return None
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_file.name)
        except OSError:
            pass


def _parse_pdf_with_pymupdf_result(
    pdf_bytes: bytes,
    max_pages: int = 10,
    images_output_dir: Path | None = None,
    images_url_prefix: str | None = None,
) -> ParsedPdfResult | None:
    """Run PyMuPDF extraction and normalization in one worker-thread job."""
    parsed = _parse_pdf_with_pymupdf(
        pdf_bytes,
        max_pages,
        images_output_dir=images_output_dir,
        images_url_prefix=images_url_prefix,
    )
    if parsed is None:
        return None
    markdown, page_chunks = parsed
    structured_content = _build_document_graph_from_pymupdf_chunks(page_chunks, PDF_PARSE_METHOD_PYMUPDF)
    return _to_parsed_pdf_result(markdown, PDF_PARSE_METHOD_PYMUPDF, structured_content)


async def _parse_pdf_with_pymupdf_in_worker_thread(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir: Path | None,
    images_url_prefix: str | None,
) -> ParsedPdfResult | None:
    """Run PyMuPDF parsing off the event loop so SSE heartbeats keep flowing."""
    try:
        return await asyncio.to_thread(
            _parse_pdf_with_pymupdf_result,
            pdf_bytes,
            max_pages,
            images_output_dir,
            images_url_prefix,
        )
    except Exception as e:
        logger.warning(f"PyMuPDF worker-thread parse failed: {e}")
        return None



def _extract_gpu_index_from_device(assigned_device: str | None) -> int | None:
    """Extract the physical GPU index from strings like ``cuda:1``."""
    if not assigned_device:
        return None
    match = re.fullmatch(r'cuda:(\d+)', assigned_device.strip().lower())
    if not match:
        return None
    return int(match.group(1))


def _save_marker_rendered_images(
    rendered_markdown: Any,
    images_output_dir: Path | None,
    images_url_prefix: str | None,
) -> tuple[dict[str, str], dict[str, str]]:
    raw_image_url_map: dict[str, str] = {}
    block_image_url_map: dict[str, str] = {}
    if images_output_dir is None:
        return raw_image_url_map, block_image_url_map

    images_output_dir.mkdir(parents=True, exist_ok=True)
    for image_index, (raw_name, image_obj) in enumerate((rendered_markdown.images or {}).items(), start=1):
        suffix = Path(raw_name).suffix or ".png"
        filename = f"figure-{image_index:03d}{suffix}"
        image_path = images_output_dir / filename
        image_obj.save(image_path)
        image_url = f"{images_url_prefix}/{filename}" if images_url_prefix is not None else str(image_path)
        raw_image_url_map[raw_name] = image_url
        block_id = _marker_image_block_id_from_name(raw_name)
        if block_id:
            block_image_url_map[block_id] = image_url
    return raw_image_url_map, block_image_url_map


def _rewrite_marker_markdown_image_refs(markdown: str, raw_image_url_map: dict[str, str]) -> str:
    normalized_markdown = markdown
    for raw_name, image_url in raw_image_url_map.items():
        normalized_markdown = normalized_markdown.replace(f"]({raw_name})", f"]({image_url})")
    return normalized_markdown


def _trim_paginated_markdown(markdown: str, max_pages: int) -> str:
    if max_pages <= 0:
        return markdown.strip()
    page_sections: list[str] = []
    for match in re.finditer(
        r'--- Page (\d+) ---\n\n([\s\S]*?)(?=\n\n--- Page \d+ ---|\Z)',
        markdown,
    ):
        if int(match.group(1)) > max_pages:
            break
        page_sections.append(f"--- Page {match.group(1)} ---\n\n{match.group(2).strip()}")
    return "\n\n".join(section for section in page_sections if section.strip()).strip()


def _marker_subprocess_entry(
    result_conn,
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir_str: str | None,
    images_url_prefix: str | None,
    accelerator_device: str,
    physical_gpu_index: int | None,
) -> None:
    """Child-process entrypoint for isolated Marker parsing."""
    try:
        if accelerator_device == "cuda":
            if physical_gpu_index is not None:
                os.environ["CUDA_VISIBLE_DEVICES"] = str(physical_gpu_index)
                device_detail = f"physical_gpu_index={physical_gpu_index}"
            else:
                device_detail = "cuda(default-visible-device)"
        else:
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            device_detail = "cpu"
        logger.info(
            f"[MarkerSubprocess] Starting child parse on {device_detail}, "
            f"max_pages={max_pages}, image_export={bool(images_output_dir_str)}"
        )
        result = _parse_pdf_with_marker(
            pdf_bytes,
            max_pages,
            images_output_dir=Path(images_output_dir_str) if images_output_dir_str else None,
            images_url_prefix=images_url_prefix,
            accelerator_device=accelerator_device,
        )
        logger.info(
            f"[MarkerSubprocess] Child parse finished on {device_detail}, "
            f"success={result is not None}"
        )
        result_conn.send(
            {
                "ok": True,
                "result": {
                    "markdown": result.markdown if result is not None else None,
                    "parse_method": result.parse_method if result is not None else None,
                    "page_count": result.page_count if result is not None else 0,
                    "structured_content": result.structured_content if result is not None else None,
                },
            }
        )
    except Exception as e:
        logger.error(
            f"[MarkerSubprocess] Child parse crashed on {accelerator_device}"
            f"{f':{physical_gpu_index}' if physical_gpu_index is not None else ''}: {e}\n"
            f"{traceback.format_exc()}"
        )
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


def _run_marker_in_isolated_process(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir_str: str | None,
    images_url_prefix: str | None,
    accelerator_device: str,
) -> ParsedPdfResult | None:
    """Run Marker in a short-lived isolated subprocess."""
    normalized_device = accelerator_device.strip().lower()
    physical_gpu_index: int | None = None
    if normalized_device.startswith("cuda"):
        if normalized_device != "cuda":
            physical_gpu_index = _extract_gpu_index_from_device(accelerator_device)
            if physical_gpu_index is None:
                raise RuntimeError(f"Invalid assigned GPU device for Marker parse: {accelerator_device}")
        normalized_device = "cuda"
    elif normalized_device != "cpu":
        raise RuntimeError(f"Unsupported Marker accelerator device: {accelerator_device}")

    ctx = multiprocessing.get_context('spawn')
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_marker_subprocess_entry,
        args=(
            child_conn,
            pdf_bytes,
            max_pages,
            images_output_dir_str,
            images_url_prefix,
            normalized_device,
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

        process.join(timeout=MARKER_SUBPROCESS_JOIN_TIMEOUT_SECONDS)

        if payload is None:
            raise RuntimeError(
                f"Marker subprocess exited without returning a result "
                f"(exitcode={process.exitcode})"
            )
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error") or "Unknown Marker subprocess error")
        result_payload = payload.get("result") or {}
        markdown = result_payload.get("markdown")
        if markdown is None:
            return None
        return ParsedPdfResult(
            markdown=markdown,
            parse_method=result_payload.get("parse_method") or PDF_PARSE_METHOD_MARKER,
            page_count=_safe_int(result_payload.get("page_count"), 0),
            structured_content=result_payload.get("structured_content") or {},
        )
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
            process.join(timeout=MARKER_SUBPROCESS_JOIN_TIMEOUT_SECONDS)
        if process.is_alive():
            process.kill()
            process.join(timeout=MARKER_SUBPROCESS_JOIN_TIMEOUT_SECONDS)


async def _parse_pdf_with_marker_on_assigned_gpu(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir: Path | None,
    images_url_prefix: str | None,
    assigned_device: str,
) -> ParsedPdfResult | None:
    """Run Marker in an isolated subprocess on the queue-assigned GPU."""
    loop = asyncio.get_running_loop()
    try:
        logger.info(
            f"[Marker] Starting GPU parse on assigned_device={assigned_device}, "
            f"max_pages={max_pages}, image_export={images_output_dir is not None}"
        )
        result = await loop.run_in_executor(
            None,
            _run_marker_in_isolated_process,
            pdf_bytes,
            max_pages,
            str(images_output_dir) if images_output_dir else None,
            images_url_prefix,
            assigned_device,
        )
        if result is not None:
            logger.info(
                f"Marker GPU parse completed on {assigned_device}: "
                f"{len(result.structured_content.get('blocks', []))} native blocks"
            )
        return result
    except Exception as e:
        logger.warning(
            f"Marker GPU parse failed on {assigned_device}: {type(e).__name__}: {e!r}"
        )
        return None


async def _parse_pdf_with_marker_direct_gpu_if_available(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir: Path | None,
    images_url_prefix: str | None,
) -> ParsedPdfResult | None:
    """Run Marker directly on the best currently-available GPU without using the shared queue."""
    try:
        from backend.common.gpu_utils import select_optimal_gpu_for_task
    except ImportError as e:
        logger.warning(f"[Marker] GPU utilities unavailable for direct GPU parse: {e}")
        return None

    min_vram_mb = max(0.0, float(Config.DEFAULT_MIN_VRAM_MB))
    gpu_index, free_mb = select_optimal_gpu_for_task(min_vram_mb)
    if gpu_index < 0:
        logger.info(
            f"[Marker] No GPU currently satisfies direct Marker parse requirement "
            f"({min_vram_mb:.0f} MB free VRAM minimum); falling back from standalone direct-GPU path"
        )
        return None

    assigned_device = f"cuda:{gpu_index}"
    logger.info(
        f"[Marker] Skipping queue and using direct GPU parse on {assigned_device} "
        f"with ~{free_mb:.0f} MB free VRAM"
    )
    return await _parse_pdf_with_marker_on_assigned_gpu(
        pdf_bytes,
        max_pages,
        images_output_dir,
        images_url_prefix,
        assigned_device,
    )


async def _parse_pdf_with_marker_via_gpu_queue(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir: Path | None,
    images_url_prefix: str | None,
    upgrade_url: str | None = None,
) -> ParsedPdfResult | None:
    """Submit Marker parsing to the shared GPU queue and await the result."""
    from ..task_queue import TaskType, get_task_queue

    logger.info(
        f"[Marker] Preparing GPU queue parse: max_pages={max_pages}, "
        f"image_export={images_output_dir is not None}, upgrade_url={bool(upgrade_url)}"
    )
    queue = get_task_queue()
    worker_task = getattr(queue, "_worker_task", None)
    if worker_task is None or worker_task.done():
        logger.warning("Task queue is not running; skipping Marker GPU parse")
        return None

    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[ParsedPdfResult | None] = loop.create_future()
    task_id = f"pdf-parse-{uuid.uuid4().hex}"

    if upgrade_url:
        _record_high_quality_upgrade_state(
            upgrade_url,
            PDF_UPGRADE_STATUS_QUEUED_GPU,
            f"Waiting in GPU queue for Marker upgrade task {task_id}",
            high_quality_parse_pending=True,
            high_quality_parse_ready=False,
        )

    async def _queued_marker_job(
        *,
        assigned_device: str,
        task_id: str | None = None,
        **_: Any,
    ) -> None:
        try:
            if result_future.cancelled():
                if task_id:
                    logger.info(f"Skipping cancelled Marker queued job {task_id} before GPU parse starts")
                return
            if upgrade_url:
                _record_high_quality_upgrade_state(
                    upgrade_url,
                    PDF_UPGRADE_STATUS_RUNNING_GPU,
                    f"Marker upgrade started on {assigned_device} via GPU queue task {task_id or 'unknown'}",
                    high_quality_parse_pending=True,
                    high_quality_parse_ready=False,
                )
            result = await _parse_pdf_with_marker_on_assigned_gpu(
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
                logger.warning(f"Marker queued job {task_id} failed on {assigned_device}: {e}")
            if not result_future.done():
                result_future.set_exception(e)
            raise

    await queue.submit(task_id, TaskType.INFERENCE, _queued_marker_job)
    try:
        wait_timeout_seconds = max(0.0, float(Config.MARKER_GPU_QUEUE_WAIT_TIMEOUT_SECONDS))
        if wait_timeout_seconds > 0:
            try:
                return await asyncio.wait_for(
                    asyncio.shield(result_future),
                    timeout=wait_timeout_seconds,
                )
            except asyncio.TimeoutError:
                removed = await queue.cancel_pending_task(task_id)
                if removed:
                    detail = (
                        f"Marker GPU result not ready after {wait_timeout_seconds:.1f}s and task {task_id} "
                        f"had not started on GPU; "
                        + (
                            "skipping CPU fallback for background upgrade"
                            if upgrade_url
                            else "falling back to CPU"
                        )
                    )
                    logger.warning(detail)
                    if not result_future.done():
                        result_future.cancel()
                    raise MarkerGpuQueueTimeout(detail)

                logger.info(
                    f"Marker GPU result not ready after {wait_timeout_seconds:.1f}s; "
                    f"task {task_id} already started on GPU, continue waiting without CPU fallback"
                )
        return await result_future
    except asyncio.CancelledError:
        removed = await queue.cancel_pending_task(task_id)
        if removed:
            logger.info(f"Cancelled pending Marker GPU queue task {task_id}")
        if not result_future.done():
            result_future.cancel()
        raise


async def _parse_pdf_with_marker_on_cpu(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir: Path | None,
    images_url_prefix: str | None,
) -> ParsedPdfResult | None:
    """Run Marker on CPU in an isolated subprocess when GPU parsing is unavailable."""
    loop = asyncio.get_running_loop()
    try:
        logger.info(
            f"[Marker] Starting CPU parse: max_pages={max_pages}, "
            f"image_export={images_output_dir is not None}"
        )
        result = await loop.run_in_executor(
            None,
            _run_marker_in_isolated_process,
            pdf_bytes,
            max_pages,
            str(images_output_dir) if images_output_dir else None,
            images_url_prefix,
            "cpu",
        )
        if result is not None:
            logger.info(
                "Marker CPU parse completed: "
                f"{len(result.structured_content.get('blocks', []))} native blocks"
            )
        return result
    except Exception as e:
        logger.warning(f"Marker CPU parse failed: {type(e).__name__}: {e!r}")
        return None


def _parse_pdf_with_marker(
    pdf_bytes: bytes,
    max_pages: int,
    images_output_dir: Path | None = None,
    images_url_prefix: str | None = None,
    accelerator_device: str = "cpu",
) -> ParsedPdfResult | None:
    """High-quality PDF extraction using Marker."""
    try:
        ensure_transformers_runtime_ready("Marker PDF parse")
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.renderers.json import JSONRenderer
        from marker.renderers.markdown import MarkdownRenderer
    except ImportError as e:
        logger.info(f"Marker not available for structured fallback parse: {e}")
        return None

    tmp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        parse_started_at = time.perf_counter()
        logger.info(
            f"[Marker] Starting native parse: accelerator={accelerator_device}, "
            f"bytes={len(pdf_bytes)}, max_pages={max_pages}, image_export={images_output_dir is not None}"
        )
        tmp_file.write(pdf_bytes)
        tmp_file.close()
        logger.info(f"[Marker] Temporary PDF created at {tmp_file.name}")

        converter_started_at = time.perf_counter()
        converter = PdfConverter(artifact_dict=create_model_dict(device=accelerator_device))
        logger.info(
            f"[Marker] PdfConverter created in {time.perf_counter() - converter_started_at:.2f}s"
        )

        convert_started_at = time.perf_counter()
        document = converter.build_document(tmp_file.name)
        logger.info(
            f"[Marker] build_document completed in {time.perf_counter() - convert_started_at:.2f}s; exporting markdown/json"
        )

        markdown_renderer = MarkdownRenderer(
            {
                "paginate_output": True,
                "page_separator": "<<<PATHLAB_MARKER_PAGE_BREAK>>>",
            }
        )
        markdown_output = markdown_renderer(document)
        raw_image_url_map, block_image_url_map = _save_marker_rendered_images(
            markdown_output,
            images_output_dir,
            images_url_prefix,
        )
        first_page_id = _safe_int(getattr(document.pages[0], "page_id", 0), 0) if getattr(document, "pages", None) else 0
        markdown = _normalize_marker_markdown(markdown_output.markdown, first_page_id)
        markdown = _rewrite_marker_markdown_image_refs(markdown, raw_image_url_map)
        markdown = _trim_paginated_markdown(markdown, max_pages)

        rendered_json = JSONRenderer()(document).model_dump(mode="json")
        page_count_hint = len(rendered_json.get("children") or [])
        logger.info(
            f"[Marker] Building structured content from rendered JSON: page_count_hint={page_count_hint}"
        )
        structured_content = _build_document_graph_from_marker_document(
            rendered_json,
            PDF_PARSE_METHOD_MARKER,
            max_pages=max_pages,
            page_count_hint=page_count_hint,
            image_url_map=block_image_url_map,
        )
        logger.info(
            f"Marker extraction OK ({accelerator_device}): {len(markdown)} chars, "
            f"{len(raw_image_url_map)} extracted images, "
            f"{len(structured_content.get('blocks', []))} native blocks, "
            f"elapsed={time.perf_counter() - parse_started_at:.2f}s"
        )
        return _to_parsed_pdf_result(markdown, PDF_PARSE_METHOD_MARKER, structured_content)
    except Exception as e:
        elapsed = time.perf_counter() - parse_started_at if 'parse_started_at' in locals() else -1.0
        logger.error(
            f"Marker extraction failed ({accelerator_device}) after {elapsed:.2f}s: "
            f"{type(e).__name__}: {e!r}\n{traceback.format_exc()}"
        )
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
    """Parse PDF with PyMuPDF first; fall back to Marker only if fast parse fails.

    Normal flow returns quickly with a PyMuPDF parse. Callers can schedule a
    background Marker upgrade separately to improve fidelity and structure.
    """
    async def _run_parse() -> ParsedPdfResult:
        pymupdf_result = await _parse_pdf_with_pymupdf_in_worker_thread(
            pdf_bytes,
            max_pages,
            images_output_dir,
            images_url_prefix,
        )
        if pymupdf_result is not None:
            logger.info(
                "parse_pdf returning PyMuPDF fast-path result: "
                f"{pymupdf_result.page_count} pages, "
                f"{len(pymupdf_result.structured_content.get('blocks', []))} structured blocks"
            )
            return pymupdf_result

        logger.info("parse_pdf falling back to Marker native parse after PyMuPDF fast path miss")
        marker_result = await _parse_pdf_with_marker_best_effort(
            pdf_bytes,
            max_pages,
            images_output_dir,
            images_url_prefix,
        )
        if marker_result is not None:
            logger.info(
                "parse_pdf returning Marker native result: "
                f"{marker_result.page_count} pages, "
                f"{len(marker_result.structured_content.get('blocks', []))} structured blocks"
            )
            return marker_result

        return _to_parsed_pdf_result(
            "[Error parsing PDF: PyMuPDF and Marker both failed]",
            PDF_PARSE_METHOD_FAILED,
        )

    return await _run_with_pdf_parse_slot(
        "foreground-parse",
        _run_parse,
        reject_when_queue_full=True,
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
        "gitlab": "🦊",
        "gitee": "🧭",
        "zenodo": "🗂️",
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
            "gitlab": "GitLab",
            "gitee": "Gitee",
            "zenodo": "Zenodo",
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
    elif 'gitlab.com' in url_lower:
        return "gitlab"
    elif 'gitee.com' in url_lower:
        return "gitee"
    elif 'zenodo.org' in url_lower:
        return "zenodo"
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

    # Clearly non-academic sources are never academic.
    if source_type in {"github", "gitlab", "gitee", "blog", "documentation", "wikipedia", "huggingface"}:
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


def _normalize_cached_article_lookup_text(text: str) -> str:
    """Normalize a paper/article lookup string for conservative cache matching."""
    normalized = str(text or "").strip().lower()
    if not normalized:
        return ""

    normalized = normalized.strip('"\'`“”‘’《》〈〉「」『』[]()')
    normalized = re.sub(r'^(?:please\s+)?(?:read|open|view|show\s+me|look(?:\s+at)?)\s+', '', normalized)
    normalized = re.sub(r'\s+(?:paper|article|pdf)\s*$', '', normalized)
    normalized = re.sub(r'https?://\S+', ' ', normalized)
    tokens = _tokenize_for_search(normalized)
    return " ".join(tokens)


def _cached_article_source_priority_for_source(source_type: str) -> int:
    if source_type in _ACADEMIC_SOURCE_TYPES:
        return 50
    if source_type == "pdf":
        return 40
    if source_type == "web":
        return 20
    if source_type in {"documentation", "github", "gitlab", "gitee", "huggingface", "wikipedia", "zenodo"}:
        return 10
    if source_type == "blog":
        return 0
    return 5


def _cached_article_source_priority(url: str) -> int:
    return _cached_article_source_priority_for_source(detect_source_type(url))


def _cached_article_variant_kind(source_type: str) -> str:
    if source_type in {"arxiv", "biorxiv"}:
        return "preprint"
    if source_type == "openreview":
        return "openreview"
    if source_type in _ACADEMIC_SOURCE_TYPES:
        return "formal"
    return "generic"


def _detect_cached_article_query_preference(query: str) -> str | None:
    query_lower = str(query or "").lower()
    if not query_lower:
        return None

    if any(keyword in query_lower for keyword in (
        "arxiv", "preprint", "预印本", "預印本", "bioarxiv", "biorxiv", "medrxiv",
    )):
        return "preprint"
    if "openreview" in query_lower:
        return "openreview"
    if any(keyword in query_lower for keyword in (
        "journal", "publisher", "published", "official version",
        "正式版", "期刊版", "出版版", "正式发表", "正式發表",
    )):
        return "formal"
    return None


def _build_cached_article_meta_fields(url: str, title: str) -> dict[str, Any]:
    source_type = detect_source_type(url)
    return {
        "source_type": source_type,
        "source_priority": _cached_article_source_priority_for_source(source_type),
        "normalized_title": _normalize_cached_article_lookup_text(title),
        "doi": _extract_doi(url),
        "arxiv_id": _extract_arxiv_id(url),
        "openreview_id": _extract_openreview_id(url),
    }


def find_cached_articles_by_title(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Return strong local cache matches for a paper/article title query.

    This is intentionally conservative: only exact matches on normalized title are
    returned, so callers can safely skip external web search when a local hit is
    found.
    """
    normalized_query = _normalize_cached_article_lookup_text(query)
    if not normalized_query:
        return []

    query_tokens = _tokenize_for_search(normalized_query)
    if len(query_tokens) < 2 and len(normalized_query) < 8:
        return []

    cache_dir = _get_pdf_cache_dir()
    matches: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    now = datetime.now()
    query_preference = _detect_cached_article_query_preference(query)

    for meta_file in cache_dir.glob("*.json"):
        if meta_file.name.endswith(STRUCTURED_CACHE_SUFFIX):
            continue

        try:
            meta = json.loads(meta_file.read_text(encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(meta, dict):
            continue

        url = str(meta.get("url") or "").strip()
        title = str(meta.get("title") or "").strip()
        if not url or not title or url in seen_urls:
            continue

        normalized_title = str(meta.get("normalized_title") or "").strip()
        if not normalized_title:
            normalized_title = _normalize_cached_article_lookup_text(title)
        if not normalized_title or normalized_title != normalized_query:
            continue

        cached_at_raw = str(meta.get("cached_at") or "").strip()
        cached_at_dt: datetime | None = None
        if cached_at_raw:
            try:
                cached_at_dt = datetime.fromisoformat(cached_at_raw)
            except Exception:
                cached_at_dt = None
        if cached_at_dt is not None and now - cached_at_dt > timedelta(days=PDF_CACHE_TTL_DAYS):
            continue

        url_hash = meta_file.stem
        has_markdown_cache = any((cache_dir / f"{url_hash}{suffix}").exists() for suffix, _ in CACHED_MARKDOWN_CANDIDATES)
        if not has_markdown_cache:
            continue

        source_type = str(meta.get("source_type") or detect_source_type(url))
        variant_kind = _cached_article_variant_kind(source_type)
        matches.append({
            "title": title,
            "url": url,
            "snippet": f"Local cache hit — {variant_kind} version already downloaded and parsed.",
            "source_type": source_type,
            "is_academic": bool(meta.get("is_academic", source_type in _ACADEMIC_SOURCE_TYPES)),
            "cached_at": cached_at_raw,
            "match_type": "exact_normalized_title",
            "variant_kind": variant_kind,
            "normalized_title": normalized_title,
            "doi": meta.get("doi"),
            "arxiv_id": meta.get("arxiv_id"),
            "openreview_id": meta.get("openreview_id"),
            "source_priority": int(meta.get("source_priority", _cached_article_source_priority_for_source(source_type))),
        })
        seen_urls.add(url)

    if query_preference:
        preferred_matches = [match for match in matches if match.get("variant_kind") == query_preference]
        if preferred_matches:
            matches = preferred_matches

    matches.sort(
        key=lambda item: (
            int(item.get("source_priority", 0)),
            str(item.get("cached_at") or ""),
        ),
        reverse=True,
    )
    return matches[:max(1, max_results)]


async def _save_markdown_to_cache_async(
    url: str,
    markdown: str,
    paper_title: str,
    structured_content: dict[str, Any] | None,
    *,
    high_quality_pending: bool,
) -> None:
    """Persist PyMuPDF cache artifacts off the event loop."""
    await asyncio.to_thread(
        _save_markdown_to_cache,
        url,
        markdown,
        paper_title,
        structured_content,
        high_quality_pending=high_quality_pending,
    )
    _trigger_vector_index(
        _get_url_hash(url),
        markdown,
        paper_title,
        structured_content,
    )


async def _save_marker_to_cache_async(
    url: str,
    markdown: str,
    paper_title: str,
    structured_content: dict[str, Any] | None,
) -> None:
    """Persist Marker cache artifacts off the event loop."""
    await asyncio.to_thread(
        _save_marker_to_cache,
        url,
        markdown,
        paper_title,
        structured_content,
    )
    _trigger_vector_index(
        _get_url_hash(url),
        markdown,
        paper_title,
        structured_content,
    )


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
        "parse_method": None,  # "marker" or "pymupdf"
        "structured_parse_method": None,
        "high_quality_pending": False,
        "image_count": 0,      # Number of extracted images on disk
        "images_ready": False, # Whether extracted images are available to reference
    }

    try:
        if _should_try_lightweight_web_first(str(result["source_type"])):
            return await _process_lightweight_web_url(url, title, base_url, api_key, model, use_cache=use_cache)

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
            if _should_try_lightweight_web_fallback(url, str(result["source_type"])):
                lightweight_result = await _process_lightweight_web_url(
                    url,
                    title,
                    base_url,
                    api_key,
                    model,
                    use_cache=use_cache,
                )
                if lightweight_result.get("success"):
                    return lightweight_result
                result["error"] = lightweight_result.get("error")
                result["error_detail"] = lightweight_result.get("error_detail")
                return result

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
                schedule_marker_upgrade(url, str(result["title"] or title), pdf_bytes)
                result["high_quality_pending"] = bool(
                    (get_cached_pdf_meta(url) or {}).get("high_quality_parse_pending")
                )
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
                if parse_method == PDF_PARSE_METHOD_MARKER:
                    await _save_marker_to_cache_async(
                        url,
                        pdf_content,
                        paper_title=title,
                        structured_content=parse_result.structured_content,
                    )
                else:
                    await _save_markdown_to_cache_async(
                        url,
                        pdf_content,
                        paper_title=title,
                        structured_content=parse_result.structured_content,
                        high_quality_pending=True,
                    )
                    if pdf_bytes:
                        schedule_marker_upgrade(url, title, pdf_bytes)
                        result["high_quality_pending"] = bool(
                            (get_cached_pdf_meta(url) or {}).get("high_quality_parse_pending")
                        )

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
            result["parse_method"] = _get_high_quality_cache_method(url) or PDF_PARSE_METHOD_PYMUPDF
        if not result["structured_parse_method"]:
            structured_cached = get_cached_structured_content(url)
            if structured_cached:
                result["structured_parse_method"] = structured_cached.get("parse_method")
        if result["parse_method"] == PDF_PARSE_METHOD_MARKER:
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
        # Both Marker and PyMuPDF write into the same per-document images dir.
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

    except PdfParseBusyError as e:
        logger.warning(f"PDF processing rejected due to load for {url}: {e}")
        result["error"] = "parse_busy"
        result["error_detail"] = str(e)
    except Exception as e:
        logger.error(f"Error processing PDF {url}: {e}")
        result["error"] = str(e)
        result["error_detail"] = f"An unexpected error occurred while processing '{title}': {str(e)[:100]}"

    return result

