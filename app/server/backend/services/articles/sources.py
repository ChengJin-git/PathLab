import os
import re
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit
from typing import Callable

import httpx
from .errors import ArticleDownloadError, failure_code, http_failure

from backend.common import get_logger
from backend.common.net_guard import (
    guarded_get,
    guarded_head,
    validate_external_url,
)

logger = get_logger("Articles")


def get_arxiv_pdf_url(url: str) -> str:
    match = re.search(r"arxiv\.org/(abs|pdf|html)/([\w.\-/]+)", url)
    if match:
        paper_id = match.group(2)
        paper_id = paper_id.replace(".pdf", "")
        return f"https://arxiv.org/pdf/{paper_id}.pdf"
    return url


def get_openreview_pdf_url(url: str) -> str:
    if "openreview.net/pdf?" in url:
        return url
    match = re.search(
        r"openreview\.net/(?:forum|note|pdf)\?id=([^&#]+)", url, re.IGNORECASE
    )
    if match:
        return f"https://openreview.net/pdf?id={match.group(1)}"
    return url


def get_sciencedirect_pdf_url(url: str) -> str:
    if "pdfft" in url or url.lower().endswith(".pdf"):
        return url
    pii_match = re.search(r"/pii/([A-Z0-9]+)", url, re.IGNORECASE)
    if pii_match:
        pii = pii_match.group(1).upper()
        return f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true"
    return url


def get_nature_pdf_url(url: str) -> str:
    if url.lower().endswith(".pdf"):
        return url
    base = url.split("?")[0].split("#")[0].rstrip("/")
    if re.search(r"nature\.com/articles/[a-z0-9\-]+$", base, re.IGNORECASE):
        return base + ".pdf"
    return url


def get_wiley_pdf_url(url: str) -> str:
    if "/doi/pdf/" in url or url.lower().endswith(".pdf"):
        return url
    for old in ("/doi/abs/", "/doi/full/"):
        if old in url:
            return url.replace(old, "/doi/pdf/")
    if re.search(r"/doi/10\.[0-9]{4,}", url) and "/doi/pdf/" not in url:
        return url.replace("/doi/", "/doi/pdf/", 1)
    return url


def get_biorxiv_pdf_url(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if not path.lower().endswith(".pdf"):
        path = re.sub(r"\.(full|abstract|article-info|metrics)$", "", path)
        path += ".full.pdf"
    return urlunsplit(parts._replace(path=path, fragment=""))


def get_science_pdf_url(url: str) -> str:
    if "/doi/full/" in url:
        return url.replace("/doi/full/", "/doi/pdf/")
    elif "/doi/" in url and "/pdf" not in url:
        return url.replace("/doi/", "/doi/pdf/")
    return url


def get_pmc_pdf_url(url: str) -> str:
    if url.rstrip("/").endswith("/pdf") or "/pdf/" in url:
        return url
    match = re.search(r"/(PMC[0-9]+)/?", url, re.IGNORECASE)
    if match:
        pmc_id = match.group(1).upper()
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/pdf/"
    return url


def _contact_email() -> str:
    """Polite-pool contact for NCBI, Crossref and Unpaywall; set by the operator."""
    return (os.getenv("PATHLAB_CONTACT_EMAIL") or os.getenv("UNPAYWALL_EMAIL") or "").strip()


async def _resolve_pubmed_to_pdf_url(url: str) -> str:
    pmid_match = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", url)
    if not pmid_match:
        return url
    pmid = pmid_match.group(1)
    try:
        api_url = (
            f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
            f"?ids={pmid}&format=json&tool=pathlab"
            + (f"&email={_contact_email()}" if _contact_email() else "")
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                logger.warning(
                    f"NCBI ID converter returned {resp.status_code} for PMID {pmid}"
                )
                return url
            data = resp.json()
            records = data.get("records", [])
            if not records:
                logger.info(f"NCBI ID converter: no records for PMID {pmid}")
                return url
            record = records[0]
            pmcid = record.get("pmcid")
            if pmcid:
                pdf_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/"
                logger.info(f"PubMed {pmid} → PMC PDF: {pdf_url}")
                return pdf_url
            doi = record.get("doi")
            if doi:
                return await _follow_doi_redirect(doi, pmid)
    except Exception as e:
        logger.warning(f"NCBI ID converter error for PMID {pmid}: {e}")
    return url


async def _follow_doi_redirect(doi: str, pmid: str | None = None) -> str:
    doi_url = f"https://doi.org/{doi}"
    label = f"PMID {pmid}" if pmid else f"DOI {doi}"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            head_resp = await guarded_head(
                client,
                doi_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,*/*",
                },
            )
            final_url = validate_external_url(str(head_resp.url))
            if final_url and final_url != doi_url:
                logger.info(f"{label} → DOI redirect → {final_url}")
                return final_url
    except Exception as e:
        logger.warning(f"DOI redirect failed for {label} ({doi_url}): {e}")
    logger.info(f"{label} → DOI (no redirect): {doi_url}")
    return doi_url


def get_acl_pdf_url(url: str) -> str:
    if url.lower().endswith(".pdf"):
        return url
    base = url.split("?")[0].split("#")[0].rstrip("/")
    return base + ".pdf"


def get_ieee_pdf_url(url: str) -> str:
    if url.lower().endswith(".pdf") or "stamp.jsp" in url:
        return url
    match = re.search(r"/document/([0-9]+)", url)
    if match:
        return f"https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber={match.group(1)}"
    return url


def get_acm_pdf_url(url: str) -> str:
    if "/doi/pdf/" in url or url.lower().endswith(".pdf"):
        return url
    if "/doi/" in url:
        return url.replace("/doi/", "/doi/pdf/", 1)
    return url


def get_springer_pdf_url(url: str) -> str:
    if "/content/pdf/" in url or url.lower().endswith(".pdf"):
        return url
    match = re.search(r"springer\.com/(?:article|chapter)/(10\.[0-9]{4,}[^\s?#]+)", url)
    if match:
        doi = match.group(1).rstrip("/")
        return f"https://link.springer.com/content/pdf/{doi}.pdf"
    return url


def get_plos_pdf_url(url: str) -> str:
    if "type=printable" in url or "article/file" in url:
        return url
    doi_match = re.search(r"[?&]id=(10\.[0-9]{4,}/[^\s?#&]+)", url)
    if doi_match:
        doi = doi_match.group(1)
        journal_match = re.search(r"journals\.plos\.org/([^/?#]+)", url)
        journal = journal_match.group(1) if journal_match else "plosone"
        return (
            f"https://journals.plos.org/{journal}/article/file?id={doi}&type=printable"
        )
    return url


def get_jama_pdf_url(url: str) -> str:
    if "articlepdf" in url or url.lower().endswith(".pdf"):
        return url
    return url.replace("/fullarticle/", "/articlepdf/")


def get_nejm_pdf_url(url: str) -> str:
    if "/doi/pdf/" in url or url.lower().endswith(".pdf"):
        return url
    for old in ("/doi/full/", "/doi/abs/"):
        if old in url:
            return url.replace(old, "/doi/pdf/")
    if re.search(r"/doi/10\.[0-9]{4,}", url) and "/doi/pdf/" not in url:
        return url.replace("/doi/", "/doi/pdf/", 1)
    return url


def get_lancet_pdf_url(url: str) -> str:
    if "/pdf" in url or url.lower().endswith(".pdf"):
        return url
    base = url.rstrip("/")
    if base.endswith("/fulltext"):
        return base[: -len("/fulltext")] + "/pdf"
    return url


def get_cell_pdf_url(url: str) -> str:
    if url.lower().endswith(".pdf") or "/pdf/" in url:
        return url
    match = re.search(
        r"(https?://(?:www\.)?cell\.com/[^/]+)/fulltext/([^\s?#]+)", url, re.IGNORECASE
    )
    if match:
        base, pii = match.group(1), match.group(2)
        return f"{base}/pdf/{pii.lower()}.pdf"
    return url


def get_oup_pdf_url(url: str) -> str:
    if "article-pdf" in url or "pdf-lookup" in url or url.lower().endswith(".pdf"):
        return url
    doi_match = re.search(r"(10\.[0-9]{4,}/[^\s?#&]+)", url)
    if doi_match:
        doi = doi_match.group(1).rstrip("/")
        return f"https://academic.oup.com/pdf-lookup/doi/{doi}"
    return url


def get_frontiers_pdf_url(url: str) -> str:
    if url.lower().endswith(".pdf") or url.rstrip("/").endswith("/pdf"):
        return url
    base = url.rstrip("/")
    if base.endswith("/full"):
        return base[:-5] + "/pdf"
    return base + "/pdf"


def get_mdpi_pdf_url(url: str) -> str:
    if url.lower().endswith(".pdf") or url.rstrip("/").endswith("/pdf"):
        return url
    return url.rstrip("/") + "/pdf"


def get_rsp_pdf_url(url: str) -> str:
    if "/doi/pdf/" in url or url.lower().endswith(".pdf"):
        return url
    for old in ("/doi/full/", "/doi/abs/"):
        if old in url:
            return url.replace(old, "/doi/pdf/")
    if re.search(r"/doi/10\.[0-9]{4,}", url) and "/doi/pdf/" not in url:
        return url.replace("/doi/", "/doi/pdf/", 1)
    return url


def get_pnas_pdf_url(url: str) -> str:
    if "/doi/pdf/" in url or url.lower().endswith(".pdf"):
        return url
    if "/doi/full/" in url:
        return url.replace("/doi/full/", "/doi/pdf/")
    if re.search(r"/doi/10\.[0-9]{4,}", url) and "/doi/pdf/" not in url:
        return url.replace("/doi/", "/doi/pdf/", 1)
    return url


def _extract_doi(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.hostname in {"biorxiv.org", "www.biorxiv.org", "medrxiv.org", "www.medrxiv.org"}:
        match = re.fullmatch(
            r"/content/(10\.\d{4,}/[\d.]+?)(?:v\d+)?(?:\.(?:full(?:\.pdf)?|abstract|article-info|metrics))?/?",
            parts.path,
        )
        if match:
            return match.group(1)
    match = re.search(r"doi\.org/(10\.[0-9]{4,}[^\s?#]+)", url)
    if match:
        return match.group(1).rstrip("/")
    match = re.search(
        r"nature\.com/articles/(s[0-9]+-[0-9]+-[0-9]+-[a-z0-9]+)", url, re.IGNORECASE
    )
    if match:
        return f"10.1038/{match.group(1)}"
    match = re.search(
        r"science\.org/doi/(?:full/|abs/|pdf/)?(10\.[0-9]{4,}[^\s?#]+)", url
    )
    if match:
        return match.group(1).rstrip("/")
    match = re.search(r"nejm\.org/doi/(?:full/|pdf/)?(10\.[0-9]{4,}[^\s?#]+)", url)
    if match:
        return match.group(1).rstrip("/")
    match = re.search(
        r"wiley\.com/doi/(?:full/|abs/|pdf/)?(10\.[0-9]{4,}[^\s?#]+)", url
    )
    if match:
        return match.group(1).rstrip("/")
    match = re.search(
        r"springer\.com/(?:article|chapter)/?(10\.[0-9]{4,}[^\s?#]+)", url
    )
    if match:
        return match.group(1).rstrip("/")
    match = re.search(
        r"frontiersin\.org/(?:journals/[^/]+/)?articles/(10\.[0-9]{4,}/[^\s?#&/]+)", url
    )
    if match:
        return match.group(1).rstrip("/")
    match = re.search(r"(10\.[0-9]{4,}/[^\s?#&]+)", url)
    if match:
        return match.group(1).rstrip("/")
    return None


async def _try_crossref_doi_from_pii(pii: str) -> str | None:
    try:
        api_url = f"https://api.crossref.org/works?filter=alternative-id:{pii}&rows=1"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                api_url,
                headers={
                    "User-Agent": "PathLab/1.0"
                    + (f" (mailto:{_contact_email()})" if _contact_email() else "")
                },
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
    if doi is None:
        doi = _extract_doi(url)
    if not doi or not _contact_email():
        return None
    try:
        api_url = f"https://api.unpaywall.org/v2/{doi}?email={_contact_email()}"
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
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
            pdf_resp = await guarded_get(
                client, pdf_url, headers=headers, max_bytes=_MAX_PDF_DOWNLOAD_BYTES
            )
            if pdf_resp.status_code == 200:
                content = pdf_resp.content
                if content.lstrip()[:5] == b"%PDF-":
                    logger.info(f"Unpaywall download successful: {len(content)} bytes")
                    return content
            return None
    except Exception as e:
        logger.warning(f"Unpaywall API error: {e}")
        return None


async def _try_semantic_scholar_download(
    url: str, doi: str | None = None
) -> bytes | None:
    if doi is None:
        doi = _extract_doi(url)
    if not doi:
        return None
    try:
        api_url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf"
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
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
            pdf_resp = await guarded_get(
                client, pdf_url, headers=headers, max_bytes=_MAX_PDF_DOWNLOAD_BYTES
            )
            if pdf_resp.status_code == 200:
                content = pdf_resp.content
                if content.lstrip()[:5] == b"%PDF-":
                    logger.info(
                        f"Semantic Scholar download successful: {len(content)} bytes"
                    )
                    return content
            return None
    except Exception as e:
        logger.warning(f"Semantic Scholar API error: {e}")
        return None


_MAX_PDF_DOWNLOAD_BYTES = 50 * 1024 * 1024


def _retry_after_seconds(value: str) -> float | None:
    """Only honor bounded server-directed retries, never retry immediately."""
    try:
        if value.strip().isdigit():
            delay = float(value.strip())
        else:
            date = parsedate_to_datetime(value)
            delay = (date - datetime.now(timezone.utc)).total_seconds()
        return max(1.0, delay) if 0 <= delay <= 10 else None
    except (ValueError, TypeError, OverflowError):
        return None


async def _get_article_bytes(client, url, **kwargs):
    response = await guarded_get(client, url, **kwargs)
    if response.status_code in {429, 503}:
        delay = _retry_after_seconds(response.headers.get("retry-after", ""))
        if delay is not None:
            # download_pdf's total deadline also covers this wait and retry.
            await asyncio.sleep(delay)
            response = await guarded_get(client, str(response.url), **kwargs)
    return response


async def download_pdf(
    url: str,
    timeout: float = 30.0,
    *,
    on_progress: Callable[[int, int | None], None] | None = None,
) -> bytes:
    """One total deadline covers redirects, landing pages and OA fallbacks."""
    try:
        async with asyncio.timeout(timeout):
            return await _download_pdf(url, min(timeout, 12.0), on_progress=on_progress)
    except TimeoutError:
        logger.warning(f"PDF download deadline exceeded: {url}")
        raise ArticleDownloadError('request_timeout') from None


async def _download_pdf(url: str, timeout: float, *, on_progress=None) -> bytes:
    try:
        url = await asyncio.to_thread(validate_external_url, url)
        original_url = url

        if "pubmed.ncbi.nlm.nih.gov" in url:
            url = await _resolve_pubmed_to_pdf_url(url)

        if "arxiv.org" in url:
            url = get_arxiv_pdf_url(url)
        elif "openreview.net" in url:
            url = get_openreview_pdf_url(url)
        elif "nature.com" in url:
            url = get_nature_pdf_url(url)
        elif "sciencedirect.com" in url or "elsevier.com" in url:
            url = get_sciencedirect_pdf_url(url)
        elif "science.org" in url:
            url = get_science_pdf_url(url)
        elif "onlinelibrary.wiley.com" in url:
            url = get_wiley_pdf_url(url)
        elif "biorxiv.org" in url or "medrxiv.org" in url:
            url = get_biorxiv_pdf_url(url)
        elif "pmc.ncbi.nlm.nih.gov" in url or "ncbi.nlm.nih.gov/pmc" in url:
            url = get_pmc_pdf_url(url)
        elif "aclanthology.org" in url:
            url = get_acl_pdf_url(url)
        elif "ieeexplore.ieee.org" in url:
            url = get_ieee_pdf_url(url)
        elif "dl.acm.org" in url:
            url = get_acm_pdf_url(url)
        elif "link.springer.com" in url or (
            "springer.com" in url and "content/pdf" not in url
        ):
            url = get_springer_pdf_url(url)
        elif "plos.org" in url:
            url = get_plos_pdf_url(url)
        elif "jamanetwork.com" in url:
            url = get_jama_pdf_url(url)
        elif "nejm.org" in url:
            url = get_nejm_pdf_url(url)
        elif "thelancet.com" in url:
            url = get_lancet_pdf_url(url)
        elif "cell.com" in url:
            url = get_cell_pdf_url(url)
        elif "academic.oup.com" in url:
            url = get_oup_pdf_url(url)
        elif "frontiersin.org" in url:
            url = get_frontiers_pdf_url(url)
        elif "mdpi.com" in url:
            url = get_mdpi_pdf_url(url)
        elif "royalsocietypublishing.org" in url:
            url = get_rsp_pdf_url(url)
        elif "pnas.org" in url:
            url = get_pnas_pdf_url(url)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/pdf,application/x-pdf,*/*",
        }

        try_oa_fallback = False
        error_code = 'no_pdf'
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await _get_article_bytes(
                client,
                url,
                headers=headers,
                max_bytes=_MAX_PDF_DOWNLOAD_BYTES,
                on_progress=on_progress,
            )

            if response.status_code == 200:
                content = response.content
                if len(content) > _MAX_PDF_DOWNLOAD_BYTES:
                    logger.warning(
                        f"PDF too large ({len(content) / 1024 / 1024:.1f} MB > "
                        f"{_MAX_PDF_DOWNLOAD_BYTES / 1024 / 1024:.0f} MB limit): {url}"
                    )
                    raise ArticleDownloadError('content_too_large')
                if content.lstrip()[:5] == b"%PDF-":
                    return content
                # Publishers often serve a landing page at /pdf/ or a DOI URL.
                # Only verified PDF bytes count; MIME/filename alone is not proof.
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(response.text[:2_000_000], "html.parser")
                links = [
                    tag.get("content")
                    for tag in soup.select(
                        'meta[name="citation_pdf_url"],meta[name="eprints.document_url"]'
                    )
                ]
                # Do not download the first arbitrary PDF reference or supplement
                # and misidentify it as this paper's original full text.
                links += [
                    tag.get("href")
                    for tag in soup.select("a[href]")
                    if ".pdf" in (tag.get("href") or "").lower()
                    and re.search(
                        r"^(?:download\s+)?(?:full[ -]?text\s+)?pdf(?:\s*\([^)]*\))?$",
                        tag.get_text(" ", strip=True),
                        re.I,
                    )
                ]
                for candidate in list(
                    dict.fromkeys(
                        urljoin(str(response.url), link) for link in links if link
                    )
                )[:2]:
                    if candidate == str(response.url):
                        continue
                    linked = await _get_article_bytes(
                        client,
                        candidate,
                        headers=headers,
                        max_bytes=_MAX_PDF_DOWNLOAD_BYTES,
                        on_progress=on_progress,
                    )
                    if linked.status_code == 200 and linked.content.lstrip().startswith(
                        b"%PDF-"
                    ):
                        return linked.content
                logger.info(f"Got 200 non-PDF from {url}, trying open access APIs...")
                try_oa_fallback = True
            elif response.status_code in (403, 401, 404, 429, 451):
                error_code = http_failure(response.status_code)
                logger.info(
                    f"Got {response.status_code} from {url}, trying open access APIs..."
                )
                try_oa_fallback = True
            else:
                error_code = http_failure(response.status_code)
                logger.warning(
                    f"Failed to download PDF from {url}: status {response.status_code}"
                )

        if not try_oa_fallback:
            raise ArticleDownloadError(error_code)

        doi = _extract_doi(original_url) or _extract_doi(url)
        if not doi and "sciencedirect.com" in url:
            pii_match = re.search(r"/pii/([A-Z0-9]+)", url, re.IGNORECASE)
            if pii_match:
                doi = await _try_crossref_doi_from_pii(pii_match.group(1).upper())

        if doi:
            tasks = [
                asyncio.create_task(_try_unpaywall_download(url, doi)),
                asyncio.create_task(_try_semantic_scholar_download(url, doi)),
            ]
            try:
                for task in asyncio.as_completed(tasks):
                    oa_bytes = await task
                    if oa_bytes:
                        return oa_bytes
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        logger.warning(f"All download attempts failed for {url}")
        raise ArticleDownloadError(error_code)
    except ArticleDownloadError:
        raise
    except Exception as e:
        logger.error(f"Error downloading PDF from {url}: {e}")
        code = 'content_too_large' if isinstance(e, ValueError) and 'size limit' in str(e) else failure_code(e)
        raise ArticleDownloadError(code) from None
