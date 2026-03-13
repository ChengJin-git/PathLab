# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Citation management module for Deep Research.

This module provides structured citation/source metadata handling
for research reports, enabling proper attribution and inline citations.
"""

from .extractor import (
    extract_citations_from_messages,
    merge_citations,
)
from .models import Citation, CitationMetadata

__all__ = [
    "Citation",
    "CitationMetadata",
    "extract_citations_from_messages",
    "merge_citations",
]
