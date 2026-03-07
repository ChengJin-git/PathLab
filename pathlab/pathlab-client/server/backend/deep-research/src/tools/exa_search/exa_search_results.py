import json
import logging
from typing import Any, Dict, List, Literal, Optional, Tuple, Type, Union

import httpx
from langchain_core.callbacks import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ExaSearchInput(BaseModel):
    query: str = Field(description="search query to look up")


class ExaSearchResults(BaseTool):
    """Tool that queries Exa search and returns normalized web results."""

    name: str = "exa_search_results_json"
    description: str = (
        "A web search engine for current information. "
        "Useful when you need recent webpages or papers. Input should be a search query."
    )
    args_schema: Type[BaseModel] = ExaSearchInput
    response_format: Literal["content_and_artifact"] = "content_and_artifact"

    max_results: int = 5
    max_content_characters: int = 4000
    search_type: str = "auto"
    category: Optional[str] = None
    include_domains: Optional[List[str]] = None
    exclude_domains: Optional[List[str]] = None
    start_crawl_date: Optional[str] = None
    end_crawl_date: Optional[str] = None
    start_published_date: Optional[str] = None
    end_published_date: Optional[str] = None
    include_text: Optional[List[str]] = None
    exclude_text: Optional[List[str]] = None
    moderation: bool = False
    max_age_hours: Optional[int] = None
    livecrawl_timeout: Optional[int] = None
    exa_api_key: str = ""
    search_url: str = "https://api.exa.ai/search"

    def __init__(self, **kwargs: Any) -> None:
        if not kwargs.get("exa_api_key"):
            import os

            kwargs["exa_api_key"] = os.getenv("EXA_API_KEY", "")
        super().__init__(**kwargs)

    def _normalize_results(self, raw_results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        cleaned_results: List[Dict[str, str]] = []
        for item in raw_results:
            cleaned_results.append(
                {
                    "type": "page",
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": (item.get("text") or "")[: self.max_content_characters],
                }
            )
        return cleaned_results

    @staticmethod
    def _is_non_empty_string(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _normalize_string_list(value: Any) -> Optional[List[str]]:
        if isinstance(value, str):
            normalized = [value.strip()] if value.strip() else []
            return normalized or None
        if isinstance(value, list):
            normalized = [item.strip() for item in value if isinstance(item, str) and item.strip()]
            return normalized or None
        return None

    def _build_contents_payload(self) -> Dict[str, Any]:
        contents: Dict[str, Any] = {
            "text": {"maxCharacters": self.max_content_characters},
        }

        if self.max_age_hours is not None:
            contents["maxAgeHours"] = self.max_age_hours
        if self.livecrawl_timeout is not None:
            contents["livecrawlTimeout"] = self.livecrawl_timeout

        return contents

    def _request_payload(self, query: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "query": query,
            "numResults": self.max_results,
            "type": self.search_type,
            "contents": self._build_contents_payload(),
        }

        if self._is_non_empty_string(self.category):
            payload["category"] = self.category.strip()

        include_domains = self._normalize_string_list(self.include_domains)
        if include_domains:
            payload["includeDomains"] = include_domains

        exclude_domains = self._normalize_string_list(self.exclude_domains)
        if exclude_domains:
            payload["excludeDomains"] = exclude_domains

        if self._is_non_empty_string(self.start_crawl_date):
            payload["startCrawlDate"] = self.start_crawl_date.strip()
        if self._is_non_empty_string(self.end_crawl_date):
            payload["endCrawlDate"] = self.end_crawl_date.strip()
        if self._is_non_empty_string(self.start_published_date):
            payload["startPublishedDate"] = self.start_published_date.strip()
        if self._is_non_empty_string(self.end_published_date):
            payload["endPublishedDate"] = self.end_published_date.strip()

        include_text = self._normalize_string_list(self.include_text)
        if include_text:
            payload["includeText"] = include_text

        exclude_text = self._normalize_string_list(self.exclude_text)
        if exclude_text:
            payload["excludeText"] = exclude_text

        if self.moderation:
            payload["moderation"] = True

        return payload

    def _headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json", "x-api-key": self.exa_api_key}

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> Tuple[Union[List[Dict[str, str]], str], Dict]:
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self.search_url,
                    headers=self._headers(),
                    json=self._request_payload(query),
                )
                response.raise_for_status()
                raw_results = response.json()
        except Exception as e:
            logger.error("Exa search returned error: %s", e)
            error_result = json.dumps({"error": repr(e)}, ensure_ascii=False)
            return error_result, {}

        cleaned_results = self._normalize_results(raw_results.get("results", []))
        return json.dumps(cleaned_results, ensure_ascii=False), raw_results

    async def _arun(
        self,
        query: str,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> Tuple[Union[List[Dict[str, str]], str], Dict]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.search_url,
                    headers=self._headers(),
                    json=self._request_payload(query),
                )
                response.raise_for_status()
                raw_results = response.json()
        except Exception as e:
            logger.error("Exa search returned error: %s", e)
            error_result = json.dumps({"error": repr(e)}, ensure_ascii=False)
            return error_result, {}

        cleaned_results = self._normalize_results(raw_results.get("results", []))
        return json.dumps(cleaned_results, ensure_ascii=False), raw_results