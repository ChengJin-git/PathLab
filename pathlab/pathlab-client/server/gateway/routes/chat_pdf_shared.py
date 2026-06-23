from __future__ import annotations

import re


def tokenize_for_search(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9]{2,}|[\u4e00-\u9fff]{1,4}", (text or "").lower())


def split_md_into_pages(markdown: str) -> list[tuple[int, str]]:
    page_pattern = re.compile(r"---\s*Page\s+(\d+)\s*---")
    parts = page_pattern.split(markdown)
    pages: list[tuple[int, str]] = []
    if parts[0].strip():
        pages.append((0, parts[0].strip()))
    for i in range(1, len(parts) - 1, 2):
        page_num = int(parts[i])
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            pages.append((page_num, content))
    if not pages:
        pages = [(0, markdown.strip())]
    return pages


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
        "science_direct",
        "wiley",
        "biorxiv",
        "openreview",
        "science",
        "pdf",
    }
)


def format_reference_card(
    title: str,
    url: str,
    source_type: str,
    is_academic: bool,
    *,
    page_count: int | None = None,
    parse_method: str | None = None,
) -> str:
    icon = "[ACADEMIC]" if is_academic else "[WEB]"
    lines = [f"{icon} {title}", f"URL: {url}", f"Source: {source_type}"]
    if page_count is not None:
        lines.append(f"Pages: {page_count}")
    if parse_method:
        lines.append(f"Parse method: {parse_method}")
    return "\n".join(lines)


def detect_source_type(url: str) -> str:
    lower = (url or "").lower()
    if "arxiv.org" in lower:
        return "arxiv"
    if "pubmed.ncbi.nlm.nih.gov" in lower:
        return "pubmed"
    if "pmc.ncbi.nlm.nih.gov" in lower:
        return "pmc"
    if "aclanthology.org" in lower:
        return "acl"
    if "ieeexplore.ieee.org" in lower:
        return "ieee"
    if "dl.acm.org" in lower:
        return "acm"
    if "springer.com" in lower or "link.springer.com" in lower:
        return "springer"
    if "plos.org" in lower:
        return "plos"
    if "jamanetwork.com" in lower:
        return "jama"
    if "nejm.org" in lower:
        return "nejm"
    if "thelancet.com" in lower:
        return "lancet"
    if "cell.com" in lower:
        return "cell"
    if "oup.com" in lower or "academic.oup.com" in lower:
        return "oup"
    if "frontiersin.org" in lower:
        return "frontiers"
    if "mdpi.com" in lower:
        return "mdpi"
    if "royalsocietypublishing.org" in lower:
        return "royal_society"
    if "pnas.org" in lower:
        return "pnas"
    if "nature.com" in lower:
        return "nature"
    if "sciencedirect.com" in lower:
        return "science_direct"
    if "wiley.com" in lower or "onlinelibrary.wiley.com" in lower:
        return "wiley"
    if "biorxiv.org" in lower:
        return "biorxiv"
    if "openreview.net" in lower:
        return "openreview"
    if "science.org" in lower:
        return "science"
    if lower.endswith(".pdf"):
        return "pdf"
    if "github.com" in lower:
        return "github"
    if "gitlab.com" in lower:
        return "gitlab"
    if "gitee.com" in lower:
        return "gitee"
    if "huggingface.co" in lower:
        return "huggingface"
    if "wikipedia.org" in lower:
        return "wikipedia"
    if any(host in lower for host in ("readthedocs", "docs.", "/docs/")):
        return "documentation"
    return "web"


def is_academic_content(content: str, source_type: str) -> bool:
    if source_type in ACADEMIC_SOURCE_TYPES:
        return True
    normalized = (content or "").lower()
    academic_markers = (
        "abstract",
        "introduction",
        "methods",
        "results",
        "discussion",
        "references",
        "doi",
        "supplementary",
    )
    return sum(1 for marker in academic_markers if marker in normalized) >= 3
