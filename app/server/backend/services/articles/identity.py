"""Shared article identity and reference format; no parser/model imports."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse, urlunparse

HOST_TYPES = {
    "arxiv.org": "arxiv",
    "openreview.net": "openreview",
    "pubmed.ncbi.nlm.nih.gov": "pubmed",
    "pmc.ncbi.nlm.nih.gov": "pmc",
    "aclanthology.org": "acl",
    "ieeexplore.ieee.org": "ieee",
    "dl.acm.org": "acm",
    "springer.com": "springer",
    "plos.org": "plos",
    "jamanetwork.com": "jama",
    "nejm.org": "nejm",
    "thelancet.com": "lancet",
    "cell.com": "cell",
    "oup.com": "oup",
    "frontiersin.org": "frontiers",
    "mdpi.com": "mdpi",
    "royalsocietypublishing.org": "royal_society",
    "pnas.org": "pnas",
    "nature.com": "nature",
    "sciencedirect.com": "elsevier",
    "wiley.com": "wiley",
    "biorxiv.org": "biorxiv",
    "medrxiv.org": "biorxiv",
    "science.org": "science",
    "github.com": "github",
    "gitlab.com": "gitlab",
    "gitee.com": "gitee",
    "huggingface.co": "huggingface",
    "wikipedia.org": "wikipedia",
    "zenodo.org": "zenodo",
}
ACADEMIC_SOURCE_TYPES = frozenset(
    {
        "arxiv",
        "pubmed",
        "pmc",
        "acl",
        "ieee",
        "acm",
        "springer",
        "plos",
        "jama",
        "nejm",
        "lancet",
        "cell",
        "oup",
        "frontiers",
        "mdpi",
        "royal_society",
        "pnas",
        "nature",
        "elsevier",
        "wiley",
        "biorxiv",
        "openreview",
        "science",
    }
)


def normalize_article_url(url: str) -> str:
    parsed = urlparse(str(url).strip())
    host = (parsed.hostname or "").lower()
    if host in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
        match = re.fullmatch(r"/(?:abs|pdf|html)/(.+?)(?:\.pdf)?/?", parsed.path)
        if match:
            return "https://arxiv.org/abs/" + match[1]
    return urlunparse(parsed._replace(fragment=""))


def get_url_hash(url: str) -> str:
    return hashlib.sha256(normalize_article_url(url).encode()).hexdigest()


def detect_source_type(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    for domain, kind in HOST_TYPES.items():
        if host == domain or host.endswith("." + domain):
            return kind
    if parsed.path.lower().endswith(".pdf"):
        return "pdf"
    if host.startswith("docs.") or "/docs/" in parsed.path:
        return "documentation"
    return "web"


def is_academic_content(content: str, source_type: str) -> bool:
    if source_type in ACADEMIC_SOURCE_TYPES:
        return True
    markers = [
        "abstract",
        "introduction",
        "methods",
        "results",
        "discussion",
        "references",
        "doi",
        "supplementary",
    ]
    return sum(word in content.lower() for word in markers) >= 3


def format_reference_card(
    title: str,
    url: str,
    source_type: str = "web",
    is_academic: bool = False,
    *,
    source_index: int | None = None,
) -> str:
    title = re.sub(r"[\r\n\[\]]", " ", title)[:500]
    index = f"\nsource_index: {source_index}" if source_index is not None else ""
    return f"[REFERENCE]\nicon: {'📄' if is_academic else '🌐'}\ntitle: {title}\nurl: {url}\nsource_id: {get_url_hash(url)}{index}\nsource: {source_type}\ntype: {'paper' if is_academic else 'webpage'}\n[/REFERENCE]"
