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
                    "content": (item.get("text") or "")[:4000],
                }
            )
        return cleaned_results

    def _request_payload(self, query: str) -> Dict[str, Any]:
        return {
            "query": query,
            "num_results": self.max_results,
            "type": "auto",
            "contents": {"text": True},
        }

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