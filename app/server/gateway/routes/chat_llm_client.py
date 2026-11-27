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

from backend.services.articles.identity import ACADEMIC_SOURCE_TYPES, detect_source_type


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


class LLMStreamError(httpx.RemoteProtocolError):
    """A 2xx response which did not contain a successful text completion."""

    def __init__(
        self, kind: str, *, code: str | None = None, request_id: str | None = None
    ):
        self.kind = kind
        self.code = code
        self.request_id = request_id
        super().__init__(
            f"LLM stream failed: {kind}; code={code or '-'}; request_id={request_id or '-'}"
        )


async def _sse_events(response: httpx.Response) -> AsyncIterator[tuple[str, str]]:
    """SSE permits optional spaces after ':', multiline data, comments and CRLF."""
    event = "message"
    data: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
        elif not line.startswith(":"):
            field, separator, value = line.partition(":")
            if separator and value.startswith(" "):
                value = value[1:]
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
    if data:
        yield event, "\n".join(data)


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
    started = time.monotonic()
    async with client.stream(
        "POST",
        f"{base_url}/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 8192,
        },
    ) as response:
        await _raise_for_status_with_detail(response)
        request_id = response.headers.get("x-request-id") or response.headers.get(
            "request-id"
        )
        headers_ms = round((time.monotonic() - started) * 1000, 1)
        last_finish_reason = None
        thinking_start: float | None = None
        last_pulse_at: float = 0.0
        _THINKING_PULSE_INTERVAL = 0.6
        events = 0
        malformed = 0
        text_chars = 0
        reasoning_chars = 0
        first_event_ms = None
        first_text_ms = None
        done = False
        usage = {}
        failure = None
        failure_code = None
        try:
            if "application/json" in response.headers.get("content-type", ""):
                body = json.loads(await response.aread())
                error = body.get("error") if isinstance(body, dict) else None
                code = error.get("code") if isinstance(error, dict) else None
                raise LLMStreamError(
                    "upstream_error" if error else "expected_sse",
                    code=str(code) if code else None,
                    request_id=request_id,
                )
            async for event, data in _sse_events(response):
                events += 1
                if first_event_ms is None:
                    first_event_ms = round((time.monotonic() - started) * 1000, 1)
                if data.strip() == "[DONE]":
                    done = True
                    break
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    malformed += 1
                    if event == "error":
                        raise LLMStreamError("upstream_error", request_id=request_id)
                    continue
                if not isinstance(parsed, dict):
                    malformed += 1
                    continue
                if (
                    event == "error"
                    or parsed.get("error")
                    or parsed.get("type") in {"error", "response.failed"}
                ):
                    nested = parsed.get("response")
                    error = (
                        parsed.get("error")
                        or (nested.get("error") if isinstance(nested, dict) else None)
                        or parsed
                    )
                    code = (
                        (error.get("code") or error.get("type"))
                        if isinstance(error, dict)
                        else None
                    )
                    raise LLMStreamError(
                        "upstream_error",
                        code=str(code) if code else None,
                        request_id=request_id,
                    )
                if isinstance(parsed.get("usage"), dict):
                    usage = {
                        key: value
                        for key, value in parsed["usage"].items()
                        if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                        and isinstance(value, int)
                    }
                if "choices" in parsed and len(parsed["choices"]) > 0:
                    choice = parsed["choices"][0]
                    delta = choice.get("delta", {})
                    content = extract_text_from_content(delta.get("content"))
                    if content:
                        text_chars += len(content.strip())
                        if first_text_ms is None and content.strip():
                            first_text_ms = round(
                                (time.monotonic() - started) * 1000, 1
                            )
                        yield f"data: {json.dumps({'content': content})}\n\n"
                    # Handle reasoning_content from thinking models (e.g. Qwen3,
                    # DeepSeek-R1). The reasoning text itself is sensitive and
                    # must not be forwarded to the client. We emit a metadata
                    # pulse with elapsed time only so the frontend can keep its
                    # silence-abort timer alive.
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning is not None:
                        reasoning_chars += len(str(reasoning))
                        now = time.monotonic()
                        first_pulse = thinking_start is None
                        if thinking_start is None:
                            thinking_start = now
                            last_pulse_at = now - _THINKING_PULSE_INTERVAL
                        if first_pulse or now - last_pulse_at >= _THINKING_PULSE_INTERVAL:
                            last_pulse_at = now
                            elapsed_ms = int((now - thinking_start) * 1000)
                            yield f"data: {json.dumps({'type': 'thinking_pulse', 'elapsed_ms': elapsed_ms})}\n\n"
                    fr = choice.get("finish_reason")
                    if fr:
                        last_finish_reason = fr
            if not text_chars:
                kind = (
                    "output_limit"
                    if last_finish_reason == "length"
                    else (
                        "empty_completion"
                        if done or last_finish_reason
                        else "incomplete_stream"
                    )
                )
                raise LLMStreamError(
                    kind, code=last_finish_reason, request_id=request_id
                )
            if not done and not last_finish_reason:
                raise LLMStreamError("incomplete_stream", request_id=request_id)
            if last_finish_reason == "length":
                yield f"data: {json.dumps({'response_truncated': True})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            failure = (
                exc.kind if isinstance(exc, LLMStreamError) else type(exc).__name__
            )
            failure_code = exc.code if isinstance(exc, LLMStreamError) else None
            raise
        finally:
            logger.info(
                "[LLMStream] "
                + json.dumps(
                    {
                        "model": model,
                        "request_id": request_id,
                        "status": response.status_code,
                        "headers_ms": headers_ms,
                        "first_event_ms": first_event_ms,
                        "first_text_ms": first_text_ms,
                        "total_ms": round((time.monotonic() - started) * 1000, 1),
                        "events": events,
                        "malformed": malformed,
                        "text_chars": text_chars,
                        "reasoning_chars": reasoning_chars,
                        "finish_reason": last_finish_reason,
                        "done": done,
                        "usage": usage,
                        "failure": failure,
                        "error_code": failure_code,
                    },
                    ensure_ascii=False,
                )
            )


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


class ClientDisconnectedError(Exception):
    pass


def _consume_task_exception(task: asyncio.Task[object]) -> None:
    try:
        _ = task.exception()
    except (asyncio.CancelledError, Exception):
        pass


async def _wait_for_disconnect(request: Request, stopped: asyncio.Event) -> bool:
    while not stopped.is_set():
        if await request.is_disconnected():
            return True
        try:
            await asyncio.wait_for(stopped.wait(), .25)
        except asyncio.TimeoutError:
            pass
    return False


async def _run_or_cancel_on_disconnect(coro, request: Request | None):
    if request is None:
        return await coro

    task = asyncio.ensure_future(coro)
    stopped = asyncio.Event()
    disconnect_task = asyncio.ensure_future(_wait_for_disconnect(request, stopped))

    try:
        done, _ = await asyncio.wait({task, disconnect_task},return_when=asyncio.FIRST_COMPLETED)
        if disconnect_task in done and disconnect_task.result():
            raise ClientDisconnectedError()
        return task.result()
    finally:
        # Request.is_disconnected uses an AnyIO cancellation scope, which can
        # consume Task.cancel during its receive check. The explicit stop event
        # guarantees this watcher exits when a fast/cached operation completes.
        stopped.set()
        for pending in (task,disconnect_task):
            if not pending.done(): pending.cancel()
        await asyncio.gather(task,disconnect_task,return_exceptions=True)


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
            f"{result.get('source_index',idx)}. {result.get('title', '')}\n"
            f"   URL: {r_url}\n"
            f"   Source: {src_type} (reference type: {ref_type})\n"
            f"   {result.get('snippet', '')}\n\n"
        )
    return results_text
