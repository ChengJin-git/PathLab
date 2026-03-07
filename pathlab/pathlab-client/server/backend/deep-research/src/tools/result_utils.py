import json
import logging
from typing import Any


logger = logging.getLogger(__name__)

TOOL_RESULT_SCHEMA = "pathlab.tool_result.v1"
TOOL_STATUS_SUCCESS = "success"
TOOL_STATUS_NO_RESULTS = "no_results"
TOOL_STATUS_NO_USEFUL_INFORMATION = "no_useful_information"
TOOL_STATUS_ERROR = "error"

MIN_SEARCH_SNIPPET_LENGTH = 40
MIN_CRAWL_CONTENT_LENGTH = 300
MIN_RETRIEVER_CONTENT_LENGTH = 120


def build_tool_result(
    *,
    tool: str,
    status: str,
    summary: str,
    data: dict[str, Any] | None = None,
    reason: str | None = None,
    valid_for_research: bool | None = None,
) -> str:
    return json.dumps(
        {
            "meta": {
                "schema": TOOL_RESULT_SCHEMA,
                "tool": tool,
                "status": status,
                "reason": reason,
                "summary": summary,
                "valid_for_research": valid_for_research,
            },
            "data": data or {},
        },
        ensure_ascii=False,
    )


def safe_json_loads(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return value
    return value


def is_tool_result_envelope(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("meta"), dict)
        and data["meta"].get("schema") == TOOL_RESULT_SCHEMA
    )


def _get_text_length(value: Any) -> int:
    if isinstance(value, str):
        return len(value.strip())
    return 0


def _extract_result_text(item: dict[str, Any]) -> str:
    for key in ("content", "desc", "description", "snippet", "summary", "text"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalize_search_result_item(item: dict[str, Any]) -> dict[str, Any] | None:
    item_type = item.get("type")
    if item_type in ("image", "image_url"):
        image_url = item.get("image_url")
        if isinstance(image_url, dict):
            image_url = image_url.get("url")
        return {
            "type": "image",
            "image_url": image_url,
            "image_description": item.get("image_description") or item.get("title") or "",
        }

    url = item.get("url") or item.get("link")
    title = item.get("title") or item.get("name") or "Untitled"
    content = _extract_result_text(item)
    result_type = item_type if isinstance(item_type, str) and item_type else "page"
    if not url and not content:
        return None
    return {
        "type": result_type,
        "title": title,
        "url": url,
        "content": content,
        "source": item.get("source"),
        "score": item.get("score"),
        "time_frame": item.get("time_frame"),
    }


def _unwrap_search_results(parsed: Any) -> list[Any]:
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("results", "items", "data"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
    return []


def normalize_search_tool_result(raw_payload: Any, *, query: str, provider: str) -> dict[str, Any]:
    parsed = safe_json_loads(raw_payload)
    if is_tool_result_envelope(parsed):
        return parsed

    if isinstance(parsed, dict) and parsed.get("error"):
        return {
            "meta": {
                "schema": TOOL_RESULT_SCHEMA,
                "tool": "web_search",
                "status": TOOL_STATUS_ERROR,
                "reason": "provider_error",
                "summary": str(parsed.get("error")),
                "valid_for_research": False,
            },
            "data": {"query": query, "provider": provider, "results": []},
        }

    raw_results = _unwrap_search_results(parsed)
    normalized_results = []
    for item in raw_results:
        if isinstance(item, dict):
            normalized = normalize_search_result_item(item)
            if normalized:
                normalized_results.append(normalized)

    textual_results = [
        item
        for item in normalized_results
        if item.get("type") != "image" and item.get("url")
    ]
    useful_results = [
        item
        for item in textual_results
        if _get_text_length(item.get("content")) >= MIN_SEARCH_SNIPPET_LENGTH
    ]

    if normalized_results:
        if useful_results:
            status = TOOL_STATUS_SUCCESS
            reason = None
            valid_for_research = True
            summary = f"Collected {len(useful_results)} useful search result(s)."
        elif textual_results:
            status = TOOL_STATUS_NO_USEFUL_INFORMATION
            reason = "missing_snippets"
            valid_for_research = False
            summary = "Search returned links, but they did not include enough useful text."
        else:
            status = TOOL_STATUS_NO_USEFUL_INFORMATION
            reason = "only_images"
            valid_for_research = False
            summary = "Search returned image-only results without usable textual evidence."
    elif isinstance(parsed, str) and parsed.strip():
        status = TOOL_STATUS_NO_USEFUL_INFORMATION
        reason = "unstructured_response"
        valid_for_research = False
        summary = "Search returned unstructured text without usable sources."
    else:
        status = TOOL_STATUS_NO_RESULTS
        reason = "empty_response"
        valid_for_research = False
        summary = "Search returned no results."

    return {
        "meta": {
            "schema": TOOL_RESULT_SCHEMA,
            "tool": "web_search",
            "status": status,
            "reason": reason,
            "summary": summary,
            "valid_for_research": valid_for_research,
        },
        "data": {
            "query": query,
            "provider": provider,
            "results": normalized_results,
            "counts": {
                "total": len(normalized_results),
                "textual": len(textual_results),
                "useful_textual": len(useful_results),
                "images": len([item for item in normalized_results if item.get("type") == "image"]),
            },
            **({"raw_text": parsed} if isinstance(parsed, str) and parsed.strip() else {}),
        },
    }


def parse_tool_result(content: Any, tool_name: str | None = None) -> dict[str, Any] | None:
    parsed = safe_json_loads(content)
    if is_tool_result_envelope(parsed):
        return parsed

    tool_name = (tool_name or "").lower()
    if tool_name == "web_search":
        query = ""
        return normalize_search_tool_result(parsed, query=query, provider="unknown")

    if tool_name == "crawl_tool" and isinstance(parsed, dict):
        content_text = parsed.get("crawled_content") or parsed.get("content") or ""
        status = TOOL_STATUS_SUCCESS
        reason = None
        valid = _get_text_length(content_text) >= MIN_CRAWL_CONTENT_LENGTH
        if parsed.get("error"):
            status = TOOL_STATUS_ERROR
            reason = "crawl_failed"
            valid = False
        elif parsed.get("is_pdf"):
            status = TOOL_STATUS_NO_USEFUL_INFORMATION
            reason = "pdf_not_supported"
            valid = False
        elif not content_text:
            status = TOOL_STATUS_NO_USEFUL_INFORMATION
            reason = "empty_content"
            valid = False
        elif not valid:
            status = TOOL_STATUS_NO_USEFUL_INFORMATION
            reason = "insufficient_content"
        return {
            "meta": {
                "schema": TOOL_RESULT_SCHEMA,
                "tool": "crawl_tool",
                "status": status,
                "reason": reason,
                "summary": parsed.get("error") or "Crawl result processed.",
                "valid_for_research": valid,
            },
            "data": parsed,
        }

    if tool_name == "local_search_tool":
        documents = parsed if isinstance(parsed, list) else []
        useful_documents = [
            doc for doc in documents if isinstance(doc, dict) and _get_text_length(doc.get("content")) >= MIN_RETRIEVER_CONTENT_LENGTH
        ]
        status = TOOL_STATUS_SUCCESS if useful_documents else TOOL_STATUS_NO_RESULTS
        reason = None if useful_documents else "no_matches"
        if isinstance(parsed, str) and parsed.strip():
            status = TOOL_STATUS_NO_RESULTS
            reason = "no_matches"
            documents = []
        return {
            "meta": {
                "schema": TOOL_RESULT_SCHEMA,
                "tool": "local_search_tool",
                "status": status,
                "reason": reason,
                "summary": "Local retrieval completed." if useful_documents else "No relevant local documents were found.",
                "valid_for_research": bool(useful_documents),
            },
            "data": {"documents": documents, "counts": {"total": len(documents), "useful": len(useful_documents)}},
        }

    return parsed if isinstance(parsed, dict) else None
