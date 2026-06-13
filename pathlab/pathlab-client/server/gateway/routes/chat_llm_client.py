import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

import httpx
from fastapi import Request

from ..dependencies import logger
from .chat_model_selector import extract_text_from_content
from .chat_pdf import detect_source_type, ACADEMIC_SOURCE_TYPES


_llm_http_client: httpx.AsyncClient | None = None


def _get_llm_http_client() -> httpx.AsyncClient:
    global _llm_http_client
    if _llm_http_client is None or _llm_http_client.is_closed:
        _llm_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
        )
    return _llm_http_client


_vllm_cache: dict[str, Any] = {
    "available": None,
    "model": None,
    "base_url": None,
    "checked_at": 0.0,
    "fail_count": 0,
}
_VLLM_CACHE_TTL_OK = 30.0
_VLLM_CACHE_TTL_FAIL_BASE = 5.0


def _truncate_error_detail(text: str, limit: int = 1200) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


async def _raise_for_status_with_detail(response: httpx.Response) -> None:
    if not response.is_error:
        return

    detail = ""
    with suppress(Exception):
        _ = await response.aread()
        detail = response.text or ""

    status_kind = "Client" if 400 <= response.status_code < 500 else "Server"
    message = (
        f"{status_kind} error '{response.status_code} {response.reason_phrase}' "
        f"for url '{response.request.url}'"
    )
    if detail.strip():
        message = f"{message} | response_body={_truncate_error_detail(detail)}"

    raise httpx.HTTPStatusError(message, request=response.request, response=response)


async def _stream_from_openai_compatible(
    messages: list[dict[str, Any]],
    base_url: str,
    api_key: str,
    model: str,
    source_name: str = "API",
) -> AsyncIterator[str]:
    logger.info(f"Using {source_name} with model: {model}")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    client = _get_llm_http_client()
    async with client.stream(
        "POST",
        f"{base_url}/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 2048,
        },
    ) as response:
        await _raise_for_status_with_detail(response)

        last_finish_reason = None
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    if last_finish_reason == "length":
                        yield f"data: {json.dumps({'response_truncated': True})}\n\n"
                    yield "data: [DONE]\n\n"
                    break
                try:
                    parsed = json.loads(data)
                    if "choices" in parsed and len(parsed["choices"]) > 0:
                        choice = parsed["choices"][0]
                        delta = choice.get("delta", {})
                        if "content" in delta and delta["content"] is not None:
                            yield f"data: {json.dumps({'content': delta['content']})}\n\n"
                        fr = choice.get("finish_reason")
                        if fr:
                            last_finish_reason = fr
                except json.JSONDecodeError:
                    continue
        if last_finish_reason == "length":
            yield f"data: {json.dumps({'response_truncated': True})}\n\n"


async def _check_local_vllm_available(
    base_url: str, api_key: str | None = None
) -> tuple[bool, str | None]:
    now = time.monotonic()
    cached = _vllm_cache

    if cached["base_url"] != base_url:
        cached.update(
            {
                "available": None,
                "model": None,
                "base_url": base_url,
                "checked_at": 0.0,
                "fail_count": 0,
            }
        )

    if cached["available"] is True and now - cached["checked_at"] < _VLLM_CACHE_TTL_OK:
        return True, cached["model"]

    if cached["available"] is False:
        fail_ttl = min(_VLLM_CACHE_TTL_FAIL_BASE * (2 ** cached["fail_count"]), 60.0)
        if now - cached["checked_at"] < fail_ttl:
            return False, None

    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        client = _get_llm_http_client()
        response = await client.get(f"{base_url}/models", headers=headers, timeout=3.0)
        if response.status_code == 200:
            data = response.json()
            model_name = None
            if "data" in data and len(data["data"]) > 0:
                model_name = data["data"][0].get("id")
            cached.update(
                {
                    "available": True,
                    "model": model_name,
                    "checked_at": now,
                    "fail_count": 0,
                }
            )
            return True, model_name
        cached.update(
            {
                "available": False,
                "checked_at": now,
                "fail_count": cached["fail_count"] + 1,
            }
        )
        return False, None
    except Exception:
        cached.update(
            {
                "available": False,
                "checked_at": now,
                "fail_count": cached["fail_count"] + 1,
            }
        )
        return False, None


async def _call_ai_complete(
    messages: list[dict[str, Any]], base_url: str, api_key: str, model: str
) -> str:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    client = _get_llm_http_client()
    response = await client.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": 0.7,
            "max_tokens": 2048,
        },
    )
    await _raise_for_status_with_detail(response)
    data = response.json()

    if "choices" in data and len(data["choices"]) > 0:
        return extract_text_from_content(data["choices"][0]["message"].get("content"))
    return ""


async def _execute_exa_search(
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
        _ = response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("results", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("text", "")[:2000],
                }
            )

        return {"query": query, "results": results}


class ClientDisconnectedError(Exception):
    pass


def _consume_task_exception(task: asyncio.Task[object]) -> None:
    try:
        _ = task.exception()
    except (asyncio.CancelledError, Exception):
        pass


async def _wait_for_disconnect(request: Request) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(0.25)


async def _run_or_cancel_on_disconnect(coro, request: Request | None):
    if request is None:
        return await coro

    task = asyncio.ensure_future(coro)
    disconnect_task = asyncio.ensure_future(_wait_for_disconnect(request))

    done, pending = await asyncio.wait(
        {task, disconnect_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    for p in pending:
        _ = p.cancel()
        try:
            await p
        except (asyncio.CancelledError, Exception):
            pass

    if disconnect_task in done:
        raise ClientDisconnectedError()

    return task.result()


def _deduplicate_search_results(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not results:
        return results

    _bracket_re = re.compile(r"\[.*?\]")
    _word_re = re.compile(r"[a-zA-Z0-9]{3,}")

    def _title_words(title: str) -> set[str]:
        title = _bracket_re.sub("", title)
        return set(w.lower() for w in _word_re.findall(title))

    def _source_priority(result: dict[str, Any]) -> int:
        source_type = detect_source_type(str(result.get("url", "")))
        if source_type in ACADEMIC_SOURCE_TYPES:
            return 50
        if source_type == "pdf":
            return 40
        if source_type == "web":
            return 20
        if source_type in {"documentation", "github", "huggingface", "wikipedia"}:
            return 10
        if source_type == "blog":
            return 0
        return 5

    seen: list[dict[str, Any]] = []
    deduplicated: list[dict[str, Any]] = []

    for result in results:
        words = _title_words(result.get("title", ""))
        if not words:
            deduplicated.append(result)
            continue

        duplicate_idx: int | None = None
        for idx, seen_entry in enumerate(seen):
            seen_words = seen_entry["words"]
            intersection = words & seen_words
            union = words | seen_words
            if union and len(intersection) / len(union) > 0.6:
                duplicate_idx = idx
                break

        if duplicate_idx is None:
            seen.append({"words": words, "result_index": len(deduplicated)})
            deduplicated.append(result)
            continue

        existing_result_index = seen[duplicate_idx]["result_index"]
        existing_result = deduplicated[existing_result_index]
        if _source_priority(result) > _source_priority(existing_result):
            deduplicated[existing_result_index] = result
            seen[duplicate_idx]["words"] = words

    return deduplicated


def _format_search_results_for_ai(search_results: dict[str, Any]) -> str:
    query = str(search_results.get("query", "") or "")
    source = str(search_results.get("source", "web") or "web")
    results_text = "\n\nSEARCH_RESULTS_CONTEXT\n"
    if query:
        results_text += f"Query: {query}\n"
    results_text += f"Source: {source}\n"
    results_text += "Search results:\n"
    for idx, result in enumerate(search_results.get("results", []), 1):
        r_url = str(result.get("url", "") or "")
        src_type = str(result.get("source_type") or detect_source_type(r_url))
        is_academic_src = src_type in ACADEMIC_SOURCE_TYPES
        ref_type = "paper" if is_academic_src else "webpage"
        results_text += (
            f"{idx}. {result.get('title', '')}\n"
            f"   URL: {r_url}\n"
            f"   Source: {src_type} (reference type: {ref_type})\n"
            f"   {result.get('snippet', '')}\n\n"
        )
    return results_text
