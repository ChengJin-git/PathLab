"""Article retrieval and a single CPU PDF pipeline. No background reparsing.

Retrieval supplies evidence; Chat generates the one user-facing answer. Original
PDF downloads skip extraction and are copied into the conversation by its saver.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import tempfile
import time
from typing import Callable
from urllib.parse import urlparse

import httpx
from backend.common.config import Config
from backend.common.net_guard import (
    EgressDeniedError,
    guarded_get,
    validate_external_url,
)
from .document import (
    ParsedPdfResult,
    _build_document_graph_from_pymupdf_chunks,
    clean_extracted_content,
    clean_extracted_text,
    select_article_context,
)
from .identity import (
    ACADEMIC_SOURCE_TYPES,
    detect_source_type,
    format_reference_card,
    get_url_hash,
    is_academic_content,
    normalize_article_url,
)
from .sources import download_pdf
from .errors import ArticleDownloadError, failure_code

log = logging.getLogger(__name__)

CACHE_SCHEMA = 4
PDF_CACHE_TTL_DAYS = 7
PDF_PARSE_MAX_CONCURRENT = 2
PDF_PARSE_MAX_QUEUE = 4
PDF_PARSE_TIMEOUT = 90
PDF_PARSE_QUEUE_TIMEOUT = 10
ARTICLE_READ_TIMEOUT = 150
MAX_PDF_BYTES = 50 * 1024 * 1024
_pdf_cache_dir: Path | None = None
_parse_slots: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}
_parse_waiting: dict[asyncio.AbstractEventLoop, int] = {}
_article_locks: dict[tuple, list] = {}


class PdfParseBusyError(RuntimeError):
    pass


class PdfParseTimeoutError(TimeoutError):
    pass


def get_pdf_cache_dir() -> Path:
    directory = _pdf_cache_dir or Config.get_uploads_dir() / "pdf_cache"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _atomic_write(path: Path, data: bytes):
    fd, temporary = tempfile.mkstemp(prefix=".article-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def get_cached_pdf_meta(url: str) -> dict | None:
    try:
        meta = json.loads(
            (get_pdf_cache_dir() / f"{get_url_hash(url)}.json").read_text()
        )
        if (
            meta.get("schema_version") != CACHE_SCHEMA
            or time.time() - meta["cached_at"] > PDF_CACHE_TTL_DAYS * 86400
        ):
            return None
        return clean_extracted_content(meta)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def get_cached_markdown(url: str) -> str | None:
    meta = get_cached_pdf_meta(url)
    if not meta or not meta.get("parse_method"):
        return None
    try:
        return clean_extracted_text((get_pdf_cache_dir() / f"{get_url_hash(url)}.md").read_text(
            encoding="utf-8"
        ))
    except OSError:
        return None


def get_cached_structured_content(url: str) -> dict | None:
    if not get_cached_pdf_meta(url):
        return None
    try:
        return clean_extracted_content(json.loads(
            (get_pdf_cache_dir() / f"{get_url_hash(url)}.structured.json").read_text()
        ))
    except (OSError, ValueError):
        return None


def _save_cache(
    url: str,
    title: str,
    *,
    pdf: bytes | None = None,
    parsed: ParsedPdfResult | None = None,
    web: dict | None = None,
):
    title = clean_extracted_text(title)
    if web:
        web = clean_extracted_content(web)
    root, identity = get_pdf_cache_dir(), get_url_hash(url)
    meta = get_cached_pdf_meta(url) or {
        "schema_version": CACHE_SCHEMA,
        "url": normalize_article_url(url),
        "title": title,
        "cached_at": time.time(),
    }
    if pdf is not None:
        _atomic_write(root / f"{identity}.pdf", pdf)
        meta["pdf_bytes"] = len(pdf)
    if parsed:
        _atomic_write(root / f"{identity}.md", parsed.markdown.encode())
        _atomic_write(
            root / f"{identity}.structured.json",
            json.dumps(parsed.structured_content, ensure_ascii=False).encode(),
        )
        meta.update(
            parse_method=parsed.parse_method,
            page_count=parsed.page_count,
            content_scope="pdf",
            quality=parsed.structured_content.get("quality", {}),
        )
    if web:
        _atomic_write(root / f"{identity}.md", web["markdown"].encode())
        meta.update(
            parse_method="web",
            title=web["title"],
            content_scope=web["content_scope"],
            page_count=0,
        )
    _atomic_write(
        root / f"{identity}.json", json.dumps(meta, ensure_ascii=False).encode()
    )


def cleanup_expired_pdf_cache() -> int:
    """Remove expired cache entries, never conversation-owned downloaded copies."""
    root, count = get_pdf_cache_dir(), 0
    for path in root.glob("*.json"):
        if not re.fullmatch(r"[0-9a-f]{64}\.json", path.name):
            continue
        try:
            meta = json.loads(path.read_text())
            expired = (
                meta.get("schema_version") != CACHE_SCHEMA
                or time.time() - meta["cached_at"] > PDF_CACHE_TTL_DAYS * 86400
            )
        except (ValueError, TypeError, KeyError):
            expired = True
        if expired:
            for suffix in [
                ".json",
                ".pdf",
                ".md",
                ".structured.json",
                ".marker.md",
                ".pdf.partial",
            ]:
                (root / (path.stem + suffix)).unlink(missing_ok=True)
            shutil.rmtree(root / "images" / path.stem, ignore_errors=True)
            count += 1
    return count


async def parse_pdf(
    pdf_bytes: bytes,
    max_pages: int = 0,
    images_output_dir: Path | None = None,
    images_url_prefix: str | None = None,
    *,
    profile: str = "layout",
    on_progress: Callable[[dict], None] | None = None,
) -> ParsedPdfResult:
    """One isolated CPU layout/OCR pass with actual process cancellation."""
    if profile not in {"layout", "chat"}:
        raise ValueError("Unknown PDF extraction profile")
    if not pdf_bytes.lstrip().startswith(b"%PDF-") or len(pdf_bytes) > MAX_PDF_BYTES:
        raise ValueError("Invalid or oversized PDF")
    loop = asyncio.get_running_loop()
    semaphore = _parse_slots.setdefault(
        loop, asyncio.Semaphore(PDF_PARSE_MAX_CONCURRENT)
    )
    if semaphore.locked() and _parse_waiting.get(loop, 0) >= PDF_PARSE_MAX_QUEUE:
        raise PdfParseBusyError("PDF reader is busy. Retry shortly.")
    _parse_waiting[loop] = _parse_waiting.get(loop, 0) + 1
    acquired = False
    try:
        if semaphore.locked() and on_progress:
            on_progress({"status": "waiting"})
        try:
            await asyncio.wait_for(semaphore.acquire(), PDF_PARSE_QUEUE_TIMEOUT)
            acquired = True
        except TimeoutError as exc:
            raise PdfParseBusyError("PDF reader is busy. Retry shortly.") from exc
        if acquired:
            if on_progress:
                on_progress({"status": "parsing"})
            worker = Path(__file__).resolve().parents[3] / "main.py"
            with tempfile.TemporaryDirectory(prefix="pathlab-pdf-") as directory:
                source, output = (
                    Path(directory) / "input.pdf",
                    Path(directory) / "result.json",
                )
                source.write_bytes(pdf_bytes)
                command = (
                    [sys.executable]
                    if getattr(sys, "frozen", False)
                    else [sys.executable, str(worker)]
                ) + [
                    "--pdf-worker",
                    str(source),
                    str(output),
                    "--max-pages",
                    str(max_pages),
                    "--profile",
                    profile,
                ]
                if images_output_dir:
                    images_output_dir.mkdir(parents=True, exist_ok=True)
                    command += ["--images", str(images_output_dir)]
                env = {
                    **os.environ,
                    "CUDA_VISIBLE_DEVICES": "",
                    "OMP_NUM_THREADS": "2",
                    "OPENBLAS_NUM_THREADS": "2",
                    "MKL_NUM_THREADS": "2",
                }
                process = await asyncio.create_subprocess_exec(
                    *command,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )

                async def consume_progress():
                    async for line in process.stdout:
                        if on_progress and line.startswith(b"PDF_PROGRESS "):
                            try:
                                on_progress(json.loads(line[len(b"PDF_PROGRESS ") :]))
                            except (ValueError, TypeError):
                                continue

                stdout_task = asyncio.create_task(consume_progress())
                stderr_task = asyncio.create_task(process.stderr.read())
                try:
                    try:
                        await asyncio.wait_for(
                            process.wait(), timeout=PDF_PARSE_TIMEOUT
                        )
                    except TimeoutError as exc:
                        raise PdfParseTimeoutError(
                            "The PDF was downloaded, but text extraction exceeded its time limit."
                        ) from exc
                    await stdout_task
                    stderr = await stderr_task
                    if process.returncode:
                        raise ValueError(
                            "CPU PDF extraction failed: "
                            + stderr.decode(errors="replace")[-500:]
                        )
                    data = json.loads(output.read_text())
                finally:
                    if process.returncode is None:
                        try:
                            if os.name == 'nt':
                                process.kill()
                            else:
                                os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        await process.wait()
                    for task in (stdout_task, stderr_task):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(
                        stdout_task, stderr_task, return_exceptions=True
                    )
                chunks = clean_extracted_content(data["chunks"])
                markdown = "\n\n".join(
                    f"--- Page {chunk.get('metadata', {}).get('page', index + 1)} ---\n\n{chunk.get('text', '')}"
                    for index, chunk in enumerate(chunks)
                )
                meaningful = sum(
                    len(
                        re.sub(
                            r"!\[[^]]*\]\([^)]*\)", "", str(chunk.get("text") or "")
                        ).strip()
                    )
                    for chunk in chunks
                )
                if meaningful < 3:
                    raise ValueError(
                        "PDF contains no readable text after selective OCR"
                    )
                structured = _build_document_graph_from_pymupdf_chunks(
                    chunks, "pymupdf"
                )
                structured["quality"] = data["quality"]
                if images_output_dir and images_url_prefix:
                    # Page-box offsets refer to the original Markdown positions.
                    markdown = markdown.replace(
                        str(images_output_dir) + "/", images_url_prefix + "/"
                    )
                    structured = json.loads(
                        json.dumps(structured).replace(
                            str(images_output_dir) + "/", images_url_prefix + "/"
                        )
                    )
                return ParsedPdfResult(
                    markdown, "pymupdf", data["quality"]["parsed_pages"], structured
                )
    finally:
        _parse_waiting[loop] -= 1
        if acquired:
            semaphore.release()


def _extract_html(html: str, url: str, title: str) -> dict:
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    soup = BeautifulSoup(html, "html.parser")
    actual_title = soup.title.get_text(" ", strip=True) if soup.title else title
    parsed_url = urlparse(url)
    scope = "webpage"
    article_body = soup.select_one(".c-article-body")
    if article_body and (parsed_url.hostname or "").endswith("nature.com"):
        sections = {
            tag.get_text(" ", strip=True).lower() for tag in article_body.select("h2")
        }
        if len(sections & {"main", "results", "discussion", "methods"}) >= 2:
            scope = "fulltext_html"
    if parsed_url.hostname == "pubmed.ncbi.nlm.nih.gov" or (
        (parsed_url.hostname or "").endswith("arxiv.org")
        and parsed_url.path.startswith("/abs/")
    ):
        scope = "abstract"
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    container = (
        article_body
        or soup.select_one("article")
        or soup.select_one("main")
        or soup.body
        or soup
    )
    text = container.get_text(" ", strip=True)
    if len(text) < 160 or re.search(
        r"^(?:just a moment|access denied|checking your browser|captcha)",
        actual_title,
        re.I,
    ):
        raise ValueError("Page contains no accessible article body")
    content = markdownify(str(container), heading_style="ATX", strip=["img"])
    limit = 500000 if scope == "fulltext_html" else 120000
    if len(content) > limit:
        content = (
            content[:limit]
            + "\n\n[Remaining source content omitted by the reader's size limit.]"
        )
    return {"title": actual_title or title, "markdown": content, "content_scope": scope}


async def _fetch_lightweight_web_markdown(
    url: str,
    title: str,
    source_type: str = "web",
    timeout: float = 10,
    *,
    require_full_text: bool = False,
) -> dict:
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await guarded_get(
                    client,
                    url,
                    max_bytes=MAX_PDF_BYTES,
                    headers={
                        "User-Agent": "PathLab/1.0 article reader",
                        "Accept": "text/html,application/pdf,text/plain;q=0.8",
                    },
                )
            response.raise_for_status()
            if response.content.lstrip().startswith(b"%PDF-"):
                return {"success": False, "pdf_bytes": response.content}
            if len(response.content) > 5 * 1024 * 1024:
                raise ValueError("Webpage exceeds 5 MiB")
            if "text/plain" in response.headers.get("content-type", ""):
                web = {
                    "title": title,
                    "markdown": response.text[:120000],
                    "content_scope": "webpage",
                }
            else:
                web = await asyncio.to_thread(
                    _extract_html, response.text, str(response.url), title
                )
            if require_full_text and web["content_scope"] != "fulltext_html":
                raise ValueError("Landing page does not expose the article full text")
            return {"success": True, **clean_extracted_content(web)}
    except EgressDeniedError:
        return {
            "success": False,
            "error": "download_failed",
            "error_code": "blocked_url",
        }
    except (httpx.HTTPError, ValueError, TimeoutError) as exc:
        code = ('content_too_large' if 'size limit' in str(exc) or 'exceeds 5 MiB' in str(exc)
                else 'unreadable_page') if isinstance(exc, ValueError) else failure_code(exc)
        return {
            "success": False,
            "error": "download_failed",
            "error_code": code,
        }


async def process_pdf_url(
    url: str,
    title: str,
    use_cache: bool = True,
    *,
    action: str = "read",
    on_status: Callable[[str | dict], None] | None = None,
) -> dict:
    if action not in {"read", "download", "read_download"}:
        raise ValueError("Unknown article action")
    title = clean_extracted_text(title)
    started = time.monotonic()
    key = (asyncio.get_running_loop(), normalize_article_url(url))
    if key not in _article_locks and len(_article_locks) >= 16:
        return {
            "url": url,
            "success": False,
            "error": "parse_busy",
            "error_code": "parse_busy",
        }
    entry = _article_locks.setdefault(key, [asyncio.Lock(), 0])
    entry[1] += 1
    current_status = "downloading"

    def failed(code, stage):
        result = {'url': url, 'title': title, 'success': False, 'error': stage, 'error_code': code}
        # A combined download/read may have already obtained the requested PDF.
        # Its real bytes remain deliverable even if extraction fails afterward.
        if action == 'read_download':
            meta = get_cached_pdf_meta(url)
            path = (_pdf_cache_dir or Config.get_uploads_dir() / 'pdf_cache') / f'{get_url_hash(url)}.pdf'
            if meta and meta.get('pdf_bytes') and path.is_file():
                result['download_path'] = str(path)
        return result

    def status(update):
        nonlocal current_status
        current_status = (
            update if isinstance(update, str) else update.get("status", current_status)
        )
        if on_status:
            on_status(update)

    try:
        async with asyncio.timeout(ARTICLE_READ_TIMEOUT):
            await asyncio.to_thread(validate_external_url, url)
            if entry[0].locked():
                status("waiting")
            try:
                await asyncio.wait_for(entry[0].acquire(), PDF_PARSE_QUEUE_TIMEOUT)
            except TimeoutError as exc:
                raise PdfParseBusyError(
                    "Article reader is busy. Retry shortly."
                ) from exc
            try:
                result = await _read_article(url, title, use_cache, action, status)
                result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
                return result
            finally:
                entry[0].release()
    except PdfParseBusyError:
        return failed('parse_busy', 'parse_busy')
    except ArticleDownloadError as exc:
        return failed(exc.code, 'download_failed')
    except EgressDeniedError:
        return failed('blocked_url', 'download_failed')
    except TimeoutError:
        parsing = current_status == "parsing"
        return failed('parse_timeout' if parsing else 'request_timeout', 'parse_failed' if parsing else 'download_failed')
    except Exception as exc:
        log.warning('Article processing failed: %s', type(exc).__name__, exc_info=True)
        code = 'parse_failed' if isinstance(exc, ValueError) and current_status == 'parsing' else failure_code(exc)
        return failed(code, 'parse_failed' if current_status == 'parsing' else 'download_failed')
    finally:
        entry[1] -= 1
        if not entry[1]:
            _article_locks.pop(key, None)


async def _read_article(url, title, use_cache, action, status):
    source_type = detect_source_type(url)
    root, identity = get_pdf_cache_dir(), get_url_hash(url)
    pdf_path = root / f"{identity}.pdf"
    meta = await asyncio.to_thread(get_cached_pdf_meta, url) if use_cache else None
    markdown = (
        await asyncio.to_thread(get_cached_markdown, url)
        if meta and action != "download"
        else None
    )
    result = {
        "url": url,
        "title": (meta or {}).get("title") or title,
        "source_type": source_type,
        "success": False,
        "from_cache": bool(meta),
        "page_count": (meta or {}).get("page_count", 0),
        "parse_method": (meta or {}).get("parse_method"),
        "content_scope": (meta or {}).get("content_scope"),
        "quality": (meta or {}).get("quality", {}),
    }
    pdf = None
    needs_pdf = action in {"download", "read_download"}
    has_pdf = bool(meta and meta.get("pdf_bytes") and pdf_path.is_file())
    if markdown and (not needs_pdf or has_pdf):
        status("cached")
    else:
        if has_pdf:
            status("cached")
            if action != "download":
                pdf = await asyncio.to_thread(pdf_path.read_bytes)
        else:
            status("downloading")
            # Nature exposes the published full text as structured HTML. Read it
            # directly for landing-page questions rather than wait for a second,
            # often much larger PDF transfer. PDF URLs/download actions still use
            # the original bytes and page-numbered extraction.
            if (
                action == "read"
                and source_type == "nature"
                and not urlparse(url).path.lower().endswith(".pdf")
            ):
                status("fetching")
                web = await _fetch_lightweight_web_markdown(
                    url,
                    title,
                    source_type,
                    timeout=6,
                    require_full_text=True,
                )
                pdf = web.get("pdf_bytes")
                if web["success"]:
                    markdown = web["markdown"]
                    result.update(
                        title=web["title"],
                        parse_method="web",
                        content_scope=web["content_scope"],
                    )
                    if use_cache:
                        await asyncio.to_thread(_save_cache, url, title, web=web)
                else:
                    status("downloading")
            web_first = (
                not needs_pdf
                and source_type not in ACADEMIC_SOURCE_TYPES
                and source_type != "pdf"
            )
            if web_first:
                web = await _fetch_lightweight_web_markdown(url, title, source_type)
                pdf = web.get("pdf_bytes")
                if web["success"]:
                    markdown = web["markdown"]
                    result.update(
                        title=web["title"],
                        parse_method="web",
                        content_scope=web["content_scope"],
                    )
                    if use_cache:
                        await asyncio.to_thread(_save_cache, url, title, web=web)
                elif pdf is None:
                    return {**result, **web}
            if not pdf and (not markdown or needs_pdf):
                try:
                    pdf = await download_pdf(url, timeout=35,
                        on_progress=lambda received, total: status({'status': 'downloading', 'bytes_received': received, 'total_bytes': total}))
                except ArticleDownloadError as exc:
                    # A publisher cooldown also applies to its landing page.
                    # Preserve the download cause instead of immediately making
                    # another request to the same throttled source.
                    if needs_pdf or exc.code == "rate_limited":
                        raise
            if not pdf and not markdown and action == "read":
                status("fetching")
                web = await _fetch_lightweight_web_markdown(url, title, source_type)
                pdf = web.get("pdf_bytes")
                if web["success"]:
                    markdown = web["markdown"]
                    result.update(
                        title=web["title"],
                        parse_method="web",
                        content_scope=web["content_scope"],
                    )
                    if use_cache:
                        await asyncio.to_thread(_save_cache, url, title, web=web)
                elif pdf is None:
                    return {**result, **web}
            if pdf and (use_cache or needs_pdf):
                await asyncio.to_thread(_save_cache, url, title, pdf=pdf)
                has_pdf = True
        if action != "download" and not markdown and pdf:
            status({"status": "parsing", "bytes_received": len(pdf)})
            images = root / "images" / identity
            parsed = await parse_pdf(
                pdf,
                images_output_dir=images,
                images_url_prefix=f"{Config.GATEWAY_SERVICE_URL}/pdf-images/{identity}",
                profile="chat",
                on_progress=status,
            )
            markdown = parsed.markdown
            result.update(
                parse_method=parsed.parse_method,
                page_count=parsed.page_count,
                content_scope="pdf",
                quality=parsed.structured_content.get("quality"),
            )
            if use_cache:
                await asyncio.to_thread(_save_cache, url, title, parsed=parsed)
    if needs_pdf:
        if not has_pdf:
            return {
                **result,
                "error": "download_failed",
                "error_code": "no_pdf",
            }
        result["download_path"] = str(pdf_path)
    if action != "download" and not markdown:
        return {
            **result,
            "error": "parse_failed",
            "error_code": "empty_content",
        }
    result.update(
        success=True,
        pdf_content=markdown or "",
        is_academic=is_academic_content(markdown or "", source_type),
    )
    result["reference_card"] = format_reference_card(
        result["title"], url, source_type, result["is_academic"]
    )
    return result


def find_cached_articles_by_title(query: str, max_results: int = 5) -> list[dict]:
    """Bounded exact-title hints; never a fuzzy substitute for requested evidence."""
    normalize = lambda value: re.sub(r"\W+", " ", value.casefold()).strip()
    normalized = normalize(query)
    if len(normalized) < 8:
        return []
    matches = []
    for index, path in enumerate(get_pdf_cache_dir().glob("*.json")):
        if index >= 1000:
            break
        if not re.fullmatch(r"[0-9a-f]{64}\.json", path.name):
            continue
        try:
            meta = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if normalize(meta.get("title", "")) != normalized or not get_cached_pdf_meta(
            meta.get("url", "")
        ):
            continue
        if not (path.parent / (path.stem + ".md")).is_file():
            continue
        matches.append(
            {
                "url": meta["url"],
                "title": meta["title"],
                "snippet": "Previously retrieved source content.",
                "source_type": detect_source_type(meta["url"]),
            }
        )
        if len(matches) >= max_results:
            break
    return matches


def _replace_images_with_fig_aliases(markdown: str, url_hash: str) -> str:
    directory = get_pdf_cache_dir() / "images" / url_hash
    if not directory.is_dir():
        return markdown
    files = sorted(
        path.name
        for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(("_", "fig-"))
    )
    for number, name in enumerate(files, 1):
        markdown = markdown.replace(
            "/" + name + ")", f"/fig-{number}{Path(name).suffix})"
        )
    return markdown


def _build_merged_pdf_context(
    sources: list[dict], user_query: str, detected_lang: str = "en"
) -> str:
    parts = [
        "Retrieved source excerpts. Answer the user question using these excerpts; disclose missing evidence. HTML/abstract sources have no PDF page numbers."
    ]
    parts.append(
        "Stable conversation source registry (source numbers never change):\n"
        + json.dumps(sources, ensure_ascii=False)
    )
    selected = sorted(
        (source for source in sources if source.get("last_read_at")),
        key=lambda source: source["last_read_at"],
    )[-8:]
    budget = 48000 // max(1, len(selected))
    for source in selected:
        number, url = source["index"], source["url"]
        meta, markdown = get_cached_pdf_meta(url), get_cached_markdown(url)
        if not meta or not markdown:
            parts.append(
                f"[{number}] {url}: cached evidence is unavailable; retrieve it again before making source-specific claims."
            )
            continue
        markdown = _replace_images_with_fig_aliases(markdown, get_url_hash(url))
        query = (
            user_query
            + " "
            + " ".join(f"page {page}" for page in source.get("recent_pages", []))
        )
        parts.append(
            f"### [Paper {number}] {meta['title']}\n- **URL**: {url}\n- **Retrieved scope**: {meta.get('content_scope')}\n"
            + select_article_context(markdown, query, budget)
        )
    return "\n\n".join(parts)


def get_pdf_image_path(url_hash: str, filename: str) -> Path:
    directory = get_pdf_cache_dir() / "images" / url_hash
    match = re.fullmatch(r"fig-(\d+)\.[a-zA-Z]+", filename)
    if match and directory.is_dir():
        files = sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and not path.name.startswith(("_", "fig-"))
        )
        index = int(match[1]) - 1
        if 0 <= index < len(files):
            return files[index]
    return directory / filename
