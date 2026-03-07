# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging

from bs4 import BeautifulSoup, Tag
from readabilipy import simple_json_from_html_string

from .article import Article

logger = logging.getLogger(__name__)

MIN_EXTRACTED_TEXT_LENGTH = 300
NOISE_TAGS = (
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "button",
    "dialog",
    "noscript",
    "template",
    "svg",
    "canvas",
)
NOISE_HINTS = (
    "nav",
    "menu",
    "header",
    "footer",
    "sidebar",
    "share",
    "social",
    "cookie",
    "banner",
    "advert",
    "promo",
    "related",
    "breadcrumb",
    "toolbar",
    "modal",
    "popup",
)
CONTENT_SELECTORS = (
    "article",
    "main",
    "[role='main']",
    "section[class*='article']",
    "section[class*='content']",
    "section[class*='body']",
    "div[class*='article']",
    "div[class*='content']",
    "div[class*='body']",
    "div[class*='main']",
    "div[id*='article']",
    "div[id*='content']",
    "div[id*='main']",
)


def _get_extracted_text_length(article: dict | None) -> int:
    if not isinstance(article, dict):
        return 0
    for key in ("plain_text", "plain_content", "content"):
        value = article.get(key)
        if isinstance(value, str) and value.strip():
            return len(value.strip())
    return 0


def _build_article_dict(
    title: str | None,
    content: str | None,
    plain_text: str | None = None,
) -> dict[str, str]:
    return {
        "title": title.strip() if isinstance(title, str) and title.strip() else "Untitled",
        "content": content.strip() if isinstance(content, str) and content.strip() else "",
        "plain_text": plain_text.strip() if isinstance(plain_text, str) and plain_text.strip() else "",
    }


def _extract_title_from_soup(soup: BeautifulSoup) -> str:
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        return title_tag.get_text(strip=True)

    h1_tag = soup.find("h1")
    if h1_tag and h1_tag.get_text(strip=True):
        return h1_tag.get_text(strip=True)

    return "Untitled"


def _remove_noise_nodes(soup: BeautifulSoup) -> None:
    for tag_name in NOISE_TAGS:
        for node in soup.find_all(tag_name):
            node.decompose()

    for node in soup.find_all(True):
        if not isinstance(node, Tag):
            continue
        hint_text = " ".join(
            value
            for value in (
                node.get("id"),
                " ".join(node.get("class", [])) if node.get("class") else None,
                node.get("role"),
                node.get("aria-label"),
            )
            if isinstance(value, str) and value.strip()
        ).lower()
        if hint_text and any(hint in hint_text for hint in NOISE_HINTS):
            node.decompose()


def _candidate_score(node: Tag) -> int:
    text_length = len(node.get_text(" ", strip=True))
    paragraph_count = len(node.find_all(["p", "li"]))
    heading_count = len(node.find_all(["h1", "h2", "h3"]))
    table_count = len(node.find_all("table"))
    return text_length + paragraph_count * 120 + heading_count * 80 + table_count * 40


def _extract_bs4_fallback_article(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    _remove_noise_nodes(soup)

    candidates: list[Tag] = []
    for selector in CONTENT_SELECTORS:
        candidates.extend(node for node in soup.select(selector) if isinstance(node, Tag))

    body = soup.body if isinstance(soup.body, Tag) else None
    if body is not None:
        candidates.append(body)

    if not candidates:
        root = soup.find("html")
        if isinstance(root, Tag):
            candidates.append(root)

    best_node = max(candidates, key=_candidate_score, default=None)
    if best_node is None:
        return _build_article_dict(_extract_title_from_soup(soup), "", "")

    for node in best_node.find_all(True):
        if node.name == "a" and not node.get_text(strip=True):
            node.decompose()

    return _build_article_dict(
        _extract_title_from_soup(soup),
        str(best_node),
        best_node.get_text(" ", strip=True),
    )


class ReadabilityExtractor:
    def extract_article(self, html: str) -> Article:
        article = simple_json_from_html_string(html, use_readability=True)
        article_length = _get_extracted_text_length(article)

        if article_length < MIN_EXTRACTED_TEXT_LENGTH:
            fallback_article = simple_json_from_html_string(html, use_readability=False)
            fallback_length = _get_extracted_text_length(fallback_article)
            if fallback_length > article_length:
                logger.info(
                    "Using non-readability fallback extraction because readability output was too short (%d -> %d chars)",
                    article_length,
                    fallback_length,
                )
                article = fallback_article
                article_length = fallback_length

        if article_length < MIN_EXTRACTED_TEXT_LENGTH:
            bs4_article = _extract_bs4_fallback_article(html)
            bs4_length = _get_extracted_text_length(bs4_article)
            if bs4_length > article_length:
                logger.info(
                    "Using bs4 fallback extraction because readability output was too short (%d -> %d chars)",
                    article_length,
                    bs4_length,
                )
                article = bs4_article

        content = article.get("content")
        if not content or not str(content).strip():
            logger.warning("Readability extraction returned empty content")
            content = "<p>No content could be extracted from this page</p>"
        
        title = article.get("title")
        if not title or not str(title).strip():
            title = "Untitled"
        
        return Article(
            title=title,
            html_content=content,
        )
