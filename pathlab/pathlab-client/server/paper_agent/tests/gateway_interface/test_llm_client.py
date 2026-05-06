"""LLM provider tests (no actual API calls)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from pathlab_paper_agent.legacy_gateway.llm.client import (
    LLMImage,
    LLMRequest,
    LLMResponse,
    PathLabLLMProvider,
    get_default_provider,
    set_default_provider,
)


def test_llm_image_path_to_data_url(tmp_path: Path) -> None:
    f = tmp_path / "test.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n")
    img = LLMImage(path=f, mime_type="image/png")
    url = img.to_data_url()
    assert url.startswith("data:image/png;base64,")
    decoded = base64.b64decode(url.split(",", 1)[1])
    assert decoded == b"\x89PNG\r\n\x1a\n"


def test_llm_image_data_b64_to_data_url() -> None:
    img = LLMImage(data_b64="aGVsbG8=", mime_type="image/jpeg")
    url = img.to_data_url()
    assert url == "data:image/jpeg;base64,aGVsbG8="


def test_llm_image_requires_path_or_data_b64() -> None:
    img = LLMImage()
    with pytest.raises(ValueError):
        img.to_data_url()


def test_provider_builds_messages_text_only() -> None:
    p = PathLabLLMProvider()
    req = LLMRequest(system="you are a test", user="hello")
    msgs = p._build_messages(req)
    assert msgs[0] == {"role": "system", "content": "you are a test"}
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == [{"type": "text", "text": "hello"}]


def test_provider_builds_messages_with_image(tmp_path: Path) -> None:
    p = PathLabLLMProvider()
    f = tmp_path / "fig.png"
    f.write_bytes(b"PNG_BYTES")
    req = LLMRequest(
        system="vision tester",
        user="describe this",
        images=[LLMImage(path=f)],
    )
    msgs = p._build_messages(req)
    user_content = msgs[1]["content"]
    assert len(user_content) == 2
    assert user_content[0] == {"type": "text", "text": "describe this"}
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_provider_singleton_default() -> None:
    p1 = get_default_provider()
    p2 = get_default_provider()
    assert p1 is p2


def test_set_default_provider_swap() -> None:
    """Tests can override the singleton — important because the real provider
    would otherwise hit OpenRouter."""

    class StubProvider:
        name = "stub"

        async def complete(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(
                text="stub response",
                model="stub",
                provider_used="openrouter",
                finish_reason="stop",
            )

    stub = StubProvider()
    original = get_default_provider()
    try:
        set_default_provider(stub)
        assert get_default_provider() is stub
    finally:
        set_default_provider(original)


def test_llm_response_dataclass_fields() -> None:
    r = LLMResponse(
        text="hi",
        model="qwen/qwen3.5-plus",
        provider_used="openrouter",
        finish_reason="stop",
        prompt_tokens=10,
        completion_tokens=5,
    )
    assert r.text == "hi"
    assert r.provider_used == "openrouter"
    assert r.prompt_tokens == 10


# ---------------------------------------------------------------------------
# Endpoint resolution: PAPER_GEN_LLM_* env override
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_relay_override_takes_precedence(monkeypatch) -> None:
    monkeypatch.setenv("PAPER_GEN_LLM_BASE_URL", "https://relay.test/openai")
    monkeypatch.setenv("PAPER_GEN_LLM_API_KEY", "cr_testkey")
    monkeypatch.setenv("PAPER_GEN_LLM_MODEL", "claude-haiku-4-5")
    # Set OpenRouter too — relay should still win.
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter")

    p = PathLabLLMProvider()
    endpoint = await p._resolve_endpoint()
    assert endpoint.provider_name == "paper_gen_relay"
    assert endpoint.base_url == "https://relay.test/openai"
    assert endpoint.api_key == "cr_testkey"
    assert endpoint.model == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_relay_override_partial_config_fails_loud(monkeypatch) -> None:
    """If BASE_URL is set but API_KEY is missing, must error — no silent fallback."""
    monkeypatch.setenv("PAPER_GEN_LLM_BASE_URL", "https://relay.test/openai")
    monkeypatch.delenv("PAPER_GEN_LLM_API_KEY", raising=False)
    monkeypatch.delenv("PAPER_GEN_LLM_MODEL", raising=False)

    p = PathLabLLMProvider()
    with pytest.raises(RuntimeError, match="PAPER_GEN_LLM_API_KEY"):
        await p._resolve_endpoint()


@pytest.mark.asyncio
async def test_relay_override_missing_model_fails_loud(monkeypatch) -> None:
    monkeypatch.setenv("PAPER_GEN_LLM_BASE_URL", "https://relay.test/openai")
    monkeypatch.setenv("PAPER_GEN_LLM_API_KEY", "cr_x")
    monkeypatch.delenv("PAPER_GEN_LLM_MODEL", raising=False)

    p = PathLabLLMProvider()
    with pytest.raises(RuntimeError, match="PAPER_GEN_LLM_MODEL"):
        await p._resolve_endpoint()


@pytest.mark.asyncio
async def test_no_relay_no_openrouter_no_vllm_errors(monkeypatch) -> None:
    """If nothing is configured, complete() must error with a helpful message."""
    monkeypatch.delenv("PAPER_GEN_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("PAPER_GEN_LLM_API_KEY", raising=False)
    monkeypatch.delenv("PAPER_GEN_LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)

    # Force no settings either — force vLLM disabled and OpenRouter empty
    from backend.common.config import Config

    monkeypatch.setattr(
        Config,
        "get_global_settings",
        classmethod(lambda cls: {"local_vllm_enabled": False, "openrouter_api_key": ""}),
    )

    p = PathLabLLMProvider()
    with pytest.raises(RuntimeError, match="PAPER_GEN_LLM_BASE_URL"):
        await p._resolve_endpoint()


# ---------------------------------------------------------------------------
# Streaming aggregation (no real HTTP — feed bytes directly)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aggregate_stream_collects_text() -> None:
    """The SSE aggregator must collect content deltas across multiple chunks."""
    from pathlab_paper_agent.legacy_gateway.llm.client import _aggregate_stream

    # Build a fake response with `aiter_lines` returning known chunks.
    class _FakeResponse:
        async def aiter_lines(self):
            for line in [
                'data: {"model":"claude-haiku-4-5","choices":[{"delta":{"content":"Hello"}}]}',
                "",
                'data: {"choices":[{"delta":{"content":", "}}]}',
                "",
                'data: {"choices":[{"delta":{"content":"world!"}}]}',
                'data: {"choices":[{"finish_reason":"stop"}],"usage":{"prompt_tokens":12,"completion_tokens":3}}',
                "data: [DONE]",
            ]:
                yield line

    resp = await _aggregate_stream(
        _FakeResponse(),  # type: ignore[arg-type]
        provider_used="paper_gen_relay",
        fallback_model="fallback",
    )
    assert resp.text == "Hello, world!"
    assert resp.finish_reason == "stop"
    assert resp.model == "claude-haiku-4-5"
    assert resp.provider_used == "paper_gen_relay"
    assert resp.prompt_tokens == 12
    assert resp.completion_tokens == 3


@pytest.mark.asyncio
async def test_aggregate_stream_falls_back_to_default_model() -> None:
    """If no chunk reports a `model`, use fallback_model."""
    from pathlab_paper_agent.legacy_gateway.llm.client import _aggregate_stream

    class _FakeResponse:
        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"x"}}]}'
            yield "data: [DONE]"

    resp = await _aggregate_stream(
        _FakeResponse(),  # type: ignore[arg-type]
        provider_used="openrouter",
        fallback_model="my-default",
    )
    assert resp.text == "x"
    assert resp.model == "my-default"


@pytest.mark.asyncio
async def test_aggregate_stream_ignores_garbage_lines() -> None:
    """Bad JSON / blank lines / non-data lines are skipped without crashing."""
    from pathlab_paper_agent.legacy_gateway.llm.client import _aggregate_stream

    class _FakeResponse:
        async def aiter_lines(self):
            yield ""  # blank
            yield "event: ping"  # SSE event line, not data
            yield "data: not-json"
            yield 'data: {"choices":[{"delta":{"content":"OK"}}]}'
            yield "data: [DONE]"

    resp = await _aggregate_stream(
        _FakeResponse(),  # type: ignore[arg-type]
        provider_used="paper_gen_relay",
        fallback_model="fallback",
    )
    assert resp.text == "OK"
