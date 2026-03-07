# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import enum
import os

from dotenv import load_dotenv

load_dotenv()


class SearchEngine(enum.Enum):
    EXA = "exa"
    TAVILY = "tavily"
    INFOQUEST = "infoquest"
    DUCKDUCKGO = "duckduckgo"
    BRAVE_SEARCH = "brave_search"
    ARXIV = "arxiv"
    SEARX = "searx"
    WIKIPEDIA = "wikipedia"
    SERPER = "serper"


class CrawlerEngine(enum.Enum):
    JINA = "jina"
    INFOQUEST = "infoquest"


# Tool configuration
SELECTED_SEARCH_ENGINE = os.getenv("SEARCH_API", SearchEngine.TAVILY.value)


def get_selected_search_engine(default: str = SearchEngine.TAVILY.value) -> str:
    configured = os.getenv("SEARCH_API", default)
    valid = {engine.value for engine in SearchEngine}
    return configured if configured in valid else default

class RAGProvider(enum.Enum):
    DIFY = "dify"
    RAGFLOW = "ragflow"
    VIKINGDB_KNOWLEDGE_BASE = "vikingdb_knowledge_base"
    MOI = "moi"
    MILVUS = "milvus"
    QDRANT = "qdrant"


SELECTED_RAG_PROVIDER = os.getenv("RAG_PROVIDER")
