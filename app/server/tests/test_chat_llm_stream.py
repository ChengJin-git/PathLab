import json
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from gateway.routes import chat, chat_llm_client as llm


async def test_disconnect_cancels_owned_work_and_finishes_watcher():
    started, stopped = asyncio.Event(), asyncio.Event()
    async def work():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    async def disconnected():
        await started.wait()
        return True
    with pytest.raises(llm.ClientDisconnectedError):
        await asyncio.wait_for(llm._run_or_cancel_on_disconnect(work(), SimpleNamespace(is_disconnected=disconnected)), 2)
    assert stopped.is_set()


async def test_finished_work_stops_a_cancellation_swallowing_disconnect_watcher():
    entered, release = asyncio.Event(), asyncio.Event()
    async def check():
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            return False
    async def work():
        await entered.wait()
        return 'cached result'
    assert await asyncio.wait_for(llm._run_or_cancel_on_disconnect(work(), SimpleNamespace(is_disconnected=check)), 2) == 'cached result'


class Chunks(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body.encode()
        self.closed = False

    async def __aiter__(self):
        # Arbitrary TCP boundaries, including inside UTF-8 and SSE field names.
        for start in range(0, len(self.body), 7):
            yield self.body[start : start + 7]

    async def aclose(self):
        self.closed = True


def frame(delta=None, finish=None, space=True):
    return (
        "data:"
        + (" " if space else "")
        + json.dumps(
            {
                "choices": [
                    {"index": 0, "delta": delta or {}, "finish_reason": finish}
                ],
            },
            ensure_ascii=False,
        )
        + "\n\n"
    )


async def consume(monkeypatch, body, *, content_type="text/event-stream", status=200):
    stream = Chunks(body)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status,
            headers={"content-type": content_type, "x-request-id": "fixture-request"},
            stream=stream,
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        monkeypatch.setattr(llm, "_get_llm_http_client", lambda: client)
        return [
            json.loads(line[6:]) if not line.startswith("data: [DONE]") else "[DONE]"
            async for line in llm._stream_from_openai_compatible(
                [], "https://example.test/v1", "fixture-key", "gpt-6"
            )
        ]


async def test_actual_concurrency_error_is_not_an_empty_success(monkeypatch):
    body = ':\n\n:\n\nevent: error\ndata: {"error":{"code":"gateway_concurrency_limit","message":"Concurrency limit exceeded for user, please retry later","type":"rate_limit_error"}}\n\n'
    with pytest.raises(llm.LLMStreamError) as error:
        await consume(monkeypatch, body)
    assert error.value.kind == "upstream_error"
    assert error.value.code == "gateway_concurrency_limit"
    assert error.value.request_id == "fixture-request"


async def test_sse_optional_space_crlf_and_text_parts(monkeypatch):
    body = (
        ": keepalive\r\n\r\n"
        + frame({"content": "你"}, space=False)
        + frame({"content": [{"type": "text", "text": "好"}]})
        + frame(finish="stop")
        + "data:[DONE]\r\n\r\n"
    )
    assert await consume(monkeypatch, body) == [
        {"content": "你"},
        {"content": "好"},
        "[DONE]",
    ]


async def test_multiline_sse_error_and_eof(monkeypatch):
    body = 'event: error\ndata: {"error":\ndata: {"code":"rate_limit_error"}}'
    with pytest.raises(llm.LLMStreamError, match="rate_limit_error"):
        await consume(monkeypatch, body)


async def test_json_error_with_http_200_is_reported(monkeypatch):
    with pytest.raises(llm.LLMStreamError, match="gateway_concurrency_limit"):
        await consume(
            monkeypatch,
            '{"error":{"code":"gateway_concurrency_limit"}}',
            content_type="application/json",
        )


@pytest.mark.parametrize(
    "body,kind",
    [
        ("data: [DONE]\n\n", "empty_completion"),
        (": heartbeat\n\n", "incomplete_stream"),
        (frame({"role": "assistant"}) + "data: [DONE]\n\n", "empty_completion"),
        (
            frame({"reasoning_content": "private reasoning"}, finish="length")
            + "data: [DONE]\n\n",
            "output_limit",
        ),
        (frame({"content": "Partial"}), "incomplete_stream"),
    ],
)
async def test_empty_or_unfinished_streams_have_explicit_failure(
    monkeypatch, body, kind
):
    with pytest.raises(llm.LLMStreamError) as error:
        await consume(monkeypatch, body)
    assert error.value.kind == kind


async def test_truncation_is_emitted_once_before_done(monkeypatch):
    result = await consume(
        monkeypatch, frame({"content": "Partial"}, finish="length") + "data: [DONE]\n\n"
    )
    assert result == [{"content": "Partial"}, {"response_truncated": True}, "[DONE]"]


async def test_finish_reason_without_done_still_completes(monkeypatch):
    assert await consume(monkeypatch, frame({"content": "OK"}, finish="stop")) == [
        {"content": "OK"},
        "[DONE]",
    ]


async def test_diagnostics_do_not_log_reasoning_or_prompt(monkeypatch):
    logs = []
    monkeypatch.setattr(llm.logger, "info", lambda message: logs.append(message))
    body = (
        frame({"reasoning": "private-reasoning-secret"})
        + frame({"content": "visible-answer-secret"}, finish="stop")
        + "data: [DONE]\n\n"
    )
    result = await consume(monkeypatch, body)
    assert result[0]["type"] == "thinking_pulse"
    assert "private-reasoning-secret" not in str(result)
    assert not any(
        secret in str(logs)
        for secret in (
            "private-reasoning-secret",
            "visible-answer-secret",
            "fixture-key",
        )
    )
    assert "fixture-request" in str(logs)
    assert '"finish_reason": "stop"' in str(logs)


async def test_gateway_reports_concurrency_limit_without_retry_or_empty_fallback(
    monkeypatch,
):
    calls = []
    stream = Chunks(
        'event: error\ndata: {"error":{"code":"gateway_concurrency_limit"}}\n\n'
    )

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            headers={
                "content-type": "text/event-stream",
                "x-request-id": "fixture-request",
            },
            stream=stream,
        )

    monkeypatch.setattr(
        chat.Config, "get_global_settings", lambda: {"local_vllm_enabled": False}
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(llm, "_get_llm_http_client", lambda: client)
        output = [
            line
            async for line in chat.stream_ai_response(
                [{"role": "user", "content": "测试"}],
                api_key="fixture",
                base_url="https://example.test/v1",
                model="gpt-6",
                detected_lang="zh_CN",
            )
        ]
    answer = "".join(
        json.loads(line[6:]).get("content", "")
        for line in output
        if not line.startswith("data: [DONE]")
    )
    assert "并发请求已满" in answer
    assert "这次没能生成回答" not in answer
    assert len(calls) == 1
    assert stream.closed
