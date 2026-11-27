"""Configured public web search shared by Chat and Research."""

from typing import Any

import httpx


async def execute_exa_search(
    query: str, exa_api_key: str, num_results: int = 5
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "x-api-key": exa_api_key}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.exa.ai/search",
            headers=headers,
            json={
                "query": query,
                "num_results": num_results,
                "type": "auto",
                "contents": {"text": True},
            },
        )
        response.raise_for_status()
        data = response.json()

    return {
        "query": query,
        "results": [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("text", "")[:2000],
            }
            for item in data.get("results", [])
            if isinstance(item, dict)
        ],
    }
