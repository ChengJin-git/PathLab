import re

import httpx

from ..dependencies import logger
from backend.common.net_guard import (
    EgressDeniedError,
    guarded_get,
    guarded_head,
    validate_external_url,
)


def get_arxiv_pdf_url(url: str) -> str:
    match = re.search(r"arxiv\.org/(abs|pdf|html)/([\w\.\-]+)", url)
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
    if url.lower().endswith(".pdf"):
        return url
    base = url.rstrip("/").split("?")[0]
    base = re.sub(r"\.(full|abstract|article-info|metrics)$", "", base)
    return base + ".full.pdf"


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


async def _resolve_pubmed_to_pdf_url(url: str) -> str:
    pmid_match = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", url)
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
    if doi is None:
        doi = _extract_doi(url)
    if not doi:
        return None
    try:
        api_url = f"https://api.unpaywall.org/v2/{doi}?email=cjinag@connect.ust.hk"
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
            pdf_resp = await guarded_get(client, pdf_url, headers=headers)
            if pdf_resp.status_code == 200:
                content = pdf_resp.content
                if (
                    content[:4] == b"%PDF"
                    or "pdf" in pdf_resp.headers.get("content-type", "").lower()
                ):
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
            pdf_resp = await guarded_get(client, pdf_url, headers=headers)
            if pdf_resp.status_code == 200:
                content = pdf_resp.content
                if (
                    content[:4] == b"%PDF"
                    or "pdf" in pdf_resp.headers.get("content-type", "").lower()
                ):
                    logger.info(
                        f"Semantic Scholar download successful: {len(content)} bytes"
                    )
                    return content
            return None
    except Exception as e:
        logger.warning(f"Semantic Scholar API error: {e}")
        return None


_MAX_PDF_DOWNLOAD_BYTES = 50 * 1024 * 1024


async def download_pdf(url: str, timeout: float = 60.0) -> bytes | None:
    try:
        url = validate_external_url(url)

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
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await guarded_get(client, url, headers=headers)

            if response.status_code == 200:
                content = response.content
                if len(content) > _MAX_PDF_DOWNLOAD_BYTES:
                    logger.warning(
                        f"PDF too large ({len(content) / 1024 / 1024:.1f} MB > "
                        f"{_MAX_PDF_DOWNLOAD_BYTES / 1024 / 1024:.0f} MB limit): {url}"
                    )
                    return None
                if content[:4] == b"%PDF":
                    return content
                content_type = response.headers.get("content-type", "")
                if "pdf" in content_type.lower():
                    return content
                cd = response.headers.get("content-disposition", "")
                if ".pdf" in cd.lower():
                    return content
                logger.info(f"Got 200 non-PDF from {url}, trying open access APIs...")
                try_oa_fallback = True
            elif response.status_code in (403, 401, 451):
                logger.info(
                    f"Got {response.status_code} from {url}, trying open access APIs..."
                )
                try_oa_fallback = True
            else:
                logger.warning(
                    f"Failed to download PDF from {url}: status {response.status_code}"
                )

        if not try_oa_fallback:
            return None

        doi = _extract_doi(url)
        if not doi and "sciencedirect.com" in url:
            pii_match = re.search(r"/pii/([A-Z0-9]+)", url, re.IGNORECASE)
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
    except EgressDeniedError as e:
        logger.warning(f"Blocked PDF download URL {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error downloading PDF from {url}: {e}")
        return None
