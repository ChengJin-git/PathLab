# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
import os
from typing import Any, List, Literal, Optional, Type

from langchain_community.tools import (
    BraveSearch,
    DuckDuckGoSearchResults,
    GoogleSerperRun,
    SearxSearchRun,
    WikipediaQueryRun,
)
from langchain_community.tools.arxiv import ArxivQueryRun
from langchain_community.utilities import (
    ArxivAPIWrapper,
    BraveSearchWrapper,
    GoogleSerperAPIWrapper,
    SearxSearchWrapper,
    WikipediaAPIWrapper,
)
from langchain_core.callbacks import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from src.config import SearchEngine, get_selected_search_engine, load_yaml_config
from src.tools.decorators import create_logged_tool
from src.tools.exa_search.exa_search_results import ExaSearchResults
from src.tools.infoquest_search.infoquest_search_results import InfoQuestSearchResults
from src.tools.result_utils import build_tool_result, normalize_search_tool_result
from src.tools.tavily_search.tavily_search_results_with_images import (
    TavilySearchWithImages,
)

logger = logging.getLogger(__name__)

# Create logged versions of the search tools
LoggedExaSearch = create_logged_tool(ExaSearchResults)
LoggedTavilySearch = create_logged_tool(TavilySearchWithImages)
LoggedInfoQuestSearch = create_logged_tool(InfoQuestSearchResults)
LoggedDuckDuckGoSearch = create_logged_tool(DuckDuckGoSearchResults)
LoggedBraveSearch = create_logged_tool(BraveSearch)
LoggedSerperSearch = create_logged_tool(GoogleSerperRun)
LoggedArxivSearch = create_logged_tool(ArxivQueryRun)
LoggedSearxSearch = create_logged_tool(SearxSearchRun)
LoggedWikipediaSearch = create_logged_tool(WikipediaQueryRun)


class WebSearchInput(BaseModel):
    query: str = Field(description="search query to look up")


class NormalizedWebSearchTool(BaseTool):
    name: str = "web_search"
    description: str = "Perform a web search and return normalized structured results."
    args_schema: Type[BaseModel] = WebSearchInput
    response_format: Literal["content_and_artifact"] = "content_and_artifact"

    provider: str
    inner_tool: BaseTool = Field(exclude=True)

    def _invoke_sync(self, query: str) -> Any:
        try:
            return self.inner_tool.invoke({"query": query})
        except TypeError:
            return self.inner_tool.invoke(query)

    async def _invoke_async(self, query: str) -> Any:
        try:
            return await self.inner_tool.ainvoke({"query": query})
        except TypeError:
            return await self.inner_tool.ainvoke(query)

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ):
        try:
            raw_result = self._invoke_sync(query)
            normalized = normalize_search_tool_result(
                raw_result, query=query, provider=self.provider
            )
            return json.dumps(normalized, ensure_ascii=False), {
                "provider": self.provider,
                "raw_result": raw_result,
                "normalized": normalized,
            }
        except Exception as exc:
            error_payload = build_tool_result(
                tool="web_search",
                status="error",
                reason="provider_error",
                summary=f"Search provider failed: {exc}",
                valid_for_research=False,
                data={"query": query, "provider": self.provider, "results": []},
            )
            return error_payload, {"provider": self.provider, "error": repr(exc)}

    async def _arun(
        self,
        query: str,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ):
        try:
            raw_result = await self._invoke_async(query)
            normalized = normalize_search_tool_result(
                raw_result, query=query, provider=self.provider
            )
            return json.dumps(normalized, ensure_ascii=False), {
                "provider": self.provider,
                "raw_result": raw_result,
                "normalized": normalized,
            }
        except Exception as exc:
            error_payload = build_tool_result(
                tool="web_search",
                status="error",
                reason="provider_error",
                summary=f"Search provider failed: {exc}",
                valid_for_research=False,
                data={"query": query, "provider": self.provider, "results": []},
            )
            return error_payload, {"provider": self.provider, "error": repr(exc)}


def get_search_config():
    config = load_yaml_config("conf.yaml")
    search_config = config.get("SEARCH_ENGINE", {})
    return search_config


# Get the selected search tool
def get_web_search_tool(max_search_results: int, search_engine: Optional[str] = None):
    search_config = get_search_config()
    selected_search_engine = search_engine or get_selected_search_engine()
    tool: BaseTool

    if selected_search_engine == SearchEngine.EXA.value:
        tool = LoggedExaSearch(
            name="web_search",
            max_results=max_search_results,
            exa_api_key=os.getenv("EXA_API_KEY", ""),
        )
    elif selected_search_engine == SearchEngine.TAVILY.value:
        # Get all Tavily search parameters from configuration with defaults
        include_domains: Optional[List[str]] = search_config.get("include_domains", [])
        exclude_domains: Optional[List[str]] = search_config.get("exclude_domains", [])
        include_answer: bool = search_config.get("include_answer", False)
        search_depth: str = search_config.get("search_depth", "advanced")
        include_raw_content: bool = search_config.get("include_raw_content", False)
        include_images: bool = search_config.get("include_images", True)
        include_image_descriptions: bool = include_images and search_config.get(
            "include_image_descriptions", True
        )

        logger.info(
            f"Tavily search configuration loaded: include_domains={include_domains}, "
            f"exclude_domains={exclude_domains}, include_answer={include_answer}, "
            f"search_depth={search_depth}, include_raw_content={include_raw_content}, "
            f"include_images={include_images}, include_image_descriptions={include_image_descriptions}"
        )

        tool = LoggedTavilySearch(
            name="web_search",
            max_results=max_search_results,
            include_answer=include_answer,
            search_depth=search_depth,
            include_raw_content=include_raw_content,
            include_images=include_images,
            include_image_descriptions=include_image_descriptions,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )
    elif selected_search_engine == SearchEngine.INFOQUEST.value:
        time_range = search_config.get("time_range", -1)
        site = search_config.get("site", "")
        logger.info(
            f"InfoQuest search configuration loaded: time_range={time_range}, site={site}"
        )
        tool = LoggedInfoQuestSearch(
            name="web_search",
            time_range=time_range,
            site=site,
        )
    elif selected_search_engine == SearchEngine.DUCKDUCKGO.value:
        tool = LoggedDuckDuckGoSearch(
            name="web_search",
            num_results=max_search_results,
        )
    elif selected_search_engine == SearchEngine.BRAVE_SEARCH.value:
        tool = LoggedBraveSearch(
            name="web_search",
            search_wrapper=BraveSearchWrapper(
                api_key=os.getenv("BRAVE_SEARCH_API_KEY", ""),
                search_kwargs={"count": max_search_results},
            ),
        )
    elif selected_search_engine == SearchEngine.SERPER.value:
        tool = LoggedSerperSearch(
            name="web_search",
            api_wrapper=GoogleSerperAPIWrapper(
                k=max_search_results,
                serper_api_key=os.getenv("SERPER_API_KEY", ""),
            ),
        )
    elif selected_search_engine == SearchEngine.ARXIV.value:
        tool = LoggedArxivSearch(
            name="web_search",
            api_wrapper=ArxivAPIWrapper(
                top_k_results=max_search_results,
                load_max_docs=max_search_results,
                load_all_available_meta=True,
            ),
        )
    elif selected_search_engine == SearchEngine.SEARX.value:
        tool = LoggedSearxSearch(
            name="web_search",
            wrapper=SearxSearchWrapper(
                k=max_search_results,
            ),
        )
    elif selected_search_engine == SearchEngine.WIKIPEDIA.value:
        wiki_lang = search_config.get("wikipedia_lang", "en")
        wiki_doc_content_chars_max = search_config.get(
            "wikipedia_doc_content_chars_max", 4000
        )
        tool = LoggedWikipediaSearch(
            name="web_search",
            api_wrapper=WikipediaAPIWrapper(
                lang=wiki_lang,
                top_k_results=max_search_results,
                load_all_available_meta=True,
                doc_content_chars_max=wiki_doc_content_chars_max,
            ),
        )
    else:
        raise ValueError(f"Unsupported search engine: {selected_search_engine}")

    return NormalizedWebSearchTool(
        name="web_search",
        description=tool.description,
        provider=selected_search_engine,
        inner_tool=tool,
    )
