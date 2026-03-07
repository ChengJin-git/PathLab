# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
from typing import Annotated, Optional
from urllib.parse import urlparse

from langchain_core.tools import tool

from src.crawler.article import Article
from src.tools.result_utils import (
    MIN_CRAWL_CONTENT_LENGTH,
    TOOL_STATUS_ERROR,
    TOOL_STATUS_NO_USEFUL_INFORMATION,
    TOOL_STATUS_SUCCESS,
    build_tool_result,
)
from src.crawler import Crawler
from .decorators import log_io

logger = logging.getLogger(__name__)

def is_pdf_url(url: Optional[str]) -> bool:
    """Check if the URL points to a PDF file."""
    if not url:
        return False
    parsed_url = urlparse(url)
    # Check if the path ends with .pdf (case insensitive)
    return parsed_url.path.lower().endswith('.pdf')


@tool
@log_io
def crawl_tool(
    url: Annotated[str, "The url to crawl."],
) -> str:
    """Use this to crawl a url and get a readable content in markdown format."""
    # Special handling for PDF URLs
    if is_pdf_url(url):
        logger.info(f"PDF URL detected, skipping crawling: {url}")
        return build_tool_result(
            tool="crawl_tool",
            status=TOOL_STATUS_NO_USEFUL_INFORMATION,
            reason="pdf_not_supported",
            summary="PDF files cannot be crawled directly.",
            valid_for_research=False,
            data={
                "url": url,
                "is_pdf": True,
                "crawled_content": None,
            },
        )
    
    try:
        crawler = Crawler()
        article = crawler.crawl(url)
        article_content = compress_crawl_content(article)
        content_length = len(article_content.strip())
        if article.extraction_reason == "anti_bot_challenge":
            return build_tool_result(
                tool="crawl_tool",
                status=TOOL_STATUS_NO_USEFUL_INFORMATION,
                reason="anti_bot_challenge",
                summary="The site returned an anti-bot or browser verification page, so the crawler could not access the article body.",
                valid_for_research=False,
                data={
                    "url": url,
                    "crawled_content": article_content,
                    "content_length": content_length,
                },
            )
        is_valid = content_length >= MIN_CRAWL_CONTENT_LENGTH
        return build_tool_result(
            tool="crawl_tool",
            status=TOOL_STATUS_SUCCESS if is_valid else TOOL_STATUS_NO_USEFUL_INFORMATION,
            reason=None if is_valid else "insufficient_content",
            summary="Crawl succeeded." if is_valid else "The page was reachable, but the extracted body text was too short to be useful.",
            valid_for_research=is_valid,
            data={
                "url": url,
                "crawled_content": article_content,
                "content_length": content_length,
            },
        )
    except BaseException as e:
        error_msg = f"Failed to crawl. Error: {repr(e)}"
        logger.error(error_msg)
        return build_tool_result(
            tool="crawl_tool",
            status=TOOL_STATUS_ERROR,
            reason="crawl_failed",
            summary=error_msg,
            valid_for_research=False,
            data={"url": url, "crawled_content": None},
        )


def compress_crawl_content(article: Article) -> str:
    """
    Compress user-defined function for article content.
    We can customize this function to implement different compression strategies.
    Currently, it truncates the markdown content to the first 4000 characters.
    """
    return article.to_markdown()[:4000]
