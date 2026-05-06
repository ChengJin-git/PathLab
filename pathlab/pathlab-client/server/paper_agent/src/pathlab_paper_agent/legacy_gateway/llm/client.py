"""
LLM provider abstraction for the paper-generation pipeline.

Aligned 1:1 with PathLab's main chat assistant (`gateway.routes.chat_llm_client`)
to avoid having two competing LLM provider configurations:

  - Same settings source: `Config.get_global_settings()` (admin Settings UI)
  - Same env var fallback chain: OPENROUTER_API_KEY / _BASE_URL / _MODEL
  - Same provider selection: local vLLM preferred when enabled & online,
    OpenRouter fallback otherwise
  - Same vLLM probe cache: reuses `_check_local_vllm_available` so paper-gen
    and chat don't probe the same endpoint twice
  - Same shared httpx connection pool (via `_get_llm_http_client`)
  - Same retryable-error fallback semantics

Differences from chat:
  - Non-streaming (paper-gen does single-shot multimodal calls; streaming
    will arrive with the M11 refinement loop optimization)
  - Settings are re-read on each call so admin updates take effect without
    process restart (matches chat behavior)
  - PHI scrub is the caller's responsibility — this layer assumes inputs
    are already PHI-clean.

Why a separate file instead of reusing the chat client:
  - chat_llm_client is streaming-first (SSE) and tied to chat history schema
  - paper-gen needs single-shot full-response calls
  - Tests need to mock LLM cleanly without dragging chat dependencies in
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

import httpx

from backend.common.config import Config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LLMImage:
    """An image attached to an LLM request.

    Either `path` or `data_b64` must be set. `mime_type` defaults to png.
    """

    path: Optional[Path] = None
    data_b64: Optional[str] = None
    mime_type: str = "image/png"

    def to_data_url(self) -> str:
        if self.data_b64:
            return f"data:{self.mime_type};base64,{self.data_b64}"
        if self.path is None:
            raise ValueError("LLMImage requires path or data_b64.")
        encoded = base64.b64encode(self.path.read_bytes()).decode("ascii")
        return f"data:{self.mime_type};base64,{encoded}"


@dataclass
class LLMRequest:
    """A single LLM call.

    `system` and `user` are plain text. `images` are attached to the user
    message. `model` overrides the resolved default for this call.
    """

    system: str
    user: str
    images: list[LLMImage] = field(default_factory=list)
    model: Optional[str] = None
    temperature: float = 0.4
    max_output_tokens: int = 4096


@dataclass
class LLMResponse:
    text: str
    model: str
    provider_used: str  # "paper_gen_relay" | "local_vllm" | "openrouter"
    finish_reason: Optional[str]
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


@dataclass
class _ResolvedEndpoint:
    """A concrete (base_url, api_key, model, provider_name) tuple ready to call."""

    base_url: str
    api_key: str
    model: str
    provider_name: str  # "paper_gen_relay" | "local_vllm" | "openrouter"


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def complete(self, request: LLMRequest) -> LLMResponse:
        ...


# ---------------------------------------------------------------------------
# PathLabLLMProvider — aligned with chat assistant
# ---------------------------------------------------------------------------

_RETRYABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}
_DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_DEFAULT_OPENROUTER_MODEL = "qwen/qwen3.5-plus-02-15"
_DEFAULT_LOCAL_VLLM_BASE = "http://127.0.0.1:8000/v1"


class PathLabLLMProvider:
    """LLM provider for paper-generation pipeline.

    Selection order on every `complete()` call (highest precedence first):

      1. **Paper-gen relay override** — if `PAPER_GEN_LLM_BASE_URL` env var is
         set, use it as the relay endpoint. Designed for development where
         the dev wants paper-gen to hit a private OpenAI-compatible relay
         (e.g. ~/.codex relay) without touching PathLab Settings UI which
         the main chat assistant relies on.
      2. **Local vLLM** — if `local_vllm_enabled` in PathLab Settings AND
         probe succeeds, use local vLLM. Same as chat assistant.
      3. **OpenRouter** — read OpenRouter creds from PathLab Settings or
         `OPENROUTER_*` env vars. Same as chat assistant.

    On local vLLM upstream HTTP failure (httpx.HTTPError) the provider
    transparently falls back to OpenRouter for the **current** request.
    The relay path does NOT fall back (if relay is configured and fails,
    the call fails — fail-loud beats silently switching backends).

    Always uses `stream=true` on the wire because reasoning models
    (gpt-5.x, claude reasoning) require it. The streaming response is
    aggregated into a single string before returning, so callers see the
    same `LLMResponse` shape regardless of model.
    """

    name = "pathlab"

    def __init__(
        self,
        *,
        timeout_seconds: float = 180.0,  # bumped from 90 — reasoning models stream slowly
        max_retries: int = 3,
        prefer_local_vllm: bool = True,
    ) -> None:
        self._timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        self._max_retries = max_retries
        self._prefer_local_vllm = prefer_local_vllm
        self._http_client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------ I/O

    def _client(self) -> httpx.AsyncClient:
        """Return the provider's own httpx client.

        Used to be shared with `gateway.routes.chat_llm_client`, but that
        module transitively pulls torch + segmentation_models_pytorch via
        `gateway/routes/__init__.py` → `gateway.models`. Paper-gen runs in a
        minimal venv (no torch) and must work standalone, so we keep our own
        connection pool. Trivial overhead — paper-gen does single-shot calls
        anyway; sharing a pool barely mattered.
        """
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._http_client

    async def aclose(self) -> None:
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def _probe_local_vllm(
        self, base_url: str, api_key: str
    ) -> tuple[bool, Optional[str]]:
        """Probe local vLLM `/models` endpoint. Equivalent to chat client's
        `_check_local_vllm_available` but standalone (doesn't import chat).
        """
        try:
            client = self._client()
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            response = await client.get(
                f"{base_url.rstrip('/')}/models", headers=headers, timeout=3.0
            )
            if response.status_code != 200:
                return False, None
            data = response.json()
            model_name = None
            if isinstance(data, dict):
                items = data.get("data") or []
                if items and isinstance(items[0], dict):
                    model_name = items[0].get("id")
            return True, model_name
        except Exception:
            return False, None

    # ----------------------------------------------------- endpoint resolve

    async def _resolve_endpoint(self) -> _ResolvedEndpoint:
        """Pick which backend to use for this call.

        Re-reads settings + env on every call so admin updates take effect
        without restart. Precedence: relay override → local vLLM → OpenRouter.
        """
        # Step 0 — paper-gen relay override (highest precedence; dev-only)
        relay = self._resolve_relay_override()
        if relay is not None:
            return relay

        settings = Config.get_global_settings()
        local_enabled = bool(settings.get("local_vllm_enabled", False))
        local_base = settings.get("local_vllm_base_url", _DEFAULT_LOCAL_VLLM_BASE)
        local_model = settings.get("local_vllm_model", "")
        local_key = settings.get("local_vllm_api_key", "")

        openrouter_key = (
            settings.get("openrouter_api_key", "")
            or os.environ.get("OPENROUTER_API_KEY", "")
        )
        openrouter_base = (
            settings.get("openrouter_base_url", "")
            or os.environ.get("OPENROUTER_BASE_URL", _DEFAULT_OPENROUTER_BASE)
        )
        openrouter_model = (
            settings.get("openrouter_model", "")
            or os.environ.get("OPENROUTER_MODEL", _DEFAULT_OPENROUTER_MODEL)
        )

        # Step 1 — try local vLLM if enabled
        if self._prefer_local_vllm and local_enabled and local_base:
            available, detected_model = await self._probe_local_vllm(local_base, local_key)
            if available:
                resolved_model = local_model or detected_model
                if resolved_model:
                    return _ResolvedEndpoint(
                        base_url=local_base.rstrip("/"),
                        api_key=local_key,
                        model=resolved_model,
                        provider_name="local_vllm",
                    )
                logger.warning(
                    "paper_gen LLM: local vLLM online but no model resolved; "
                    "falling back to OpenRouter."
                )
            else:
                logger.info("paper_gen LLM: local vLLM offline; using OpenRouter.")

        # Step 2 — OpenRouter
        if not openrouter_key:
            raise RuntimeError(
                "No LLM provider available. Either set PAPER_GEN_LLM_BASE_URL + "
                "PAPER_GEN_LLM_API_KEY for the dev relay, or configure OpenRouter "
                "API key / enable local vLLM via PathLab Settings UI."
            )
        return _ResolvedEndpoint(
            base_url=openrouter_base.rstrip("/"),
            api_key=openrouter_key,
            model=openrouter_model,
            provider_name="openrouter",
        )

    def _resolve_relay_override(self) -> Optional[_ResolvedEndpoint]:
        """Look for paper-gen-specific relay env vars.

        All three of `PAPER_GEN_LLM_BASE_URL`, `PAPER_GEN_LLM_API_KEY`,
        `PAPER_GEN_LLM_MODEL` must be set for the override to activate.
        Partial config is treated as un-set (don't silently fall back to
        random defaults — fail loud during setup).
        """
        base = os.environ.get("PAPER_GEN_LLM_BASE_URL", "").strip()
        key = os.environ.get("PAPER_GEN_LLM_API_KEY", "").strip()
        model = os.environ.get("PAPER_GEN_LLM_MODEL", "").strip()
        if not base:
            return None
        if not key:
            raise RuntimeError(
                "PAPER_GEN_LLM_BASE_URL is set but PAPER_GEN_LLM_API_KEY is empty. "
                "Set both, or unset BASE_URL to use OpenRouter / vLLM fallback."
            )
        if not model:
            raise RuntimeError(
                "PAPER_GEN_LLM_BASE_URL is set but PAPER_GEN_LLM_MODEL is empty. "
                "Set the model name (e.g. 'claude-haiku-4-5' or 'gpt-5.5')."
            )
        return _ResolvedEndpoint(
            base_url=base.rstrip("/"),
            api_key=key,
            model=model,
            provider_name="paper_gen_relay",
        )

    # ----------------------------------------------------- payload building

    def _build_messages(self, request: LLMRequest) -> list[dict]:
        user_content: list[dict] = [{"type": "text", "text": request.user}]
        for img in request.images:
            user_content.append(
                {"type": "image_url", "image_url": {"url": img.to_data_url()}}
            )
        return [
            {"role": "system", "content": request.system},
            {"role": "user", "content": user_content},
        ]

    # ------------------------------------------------------- public surface

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Single-shot non-streaming call with vLLM-preferred fallback."""
        endpoint = await self._resolve_endpoint()
        try:
            return await self._call_endpoint(endpoint, request)
        except httpx.HTTPError as exc:
            if endpoint.provider_name == "local_vllm":
                logger.warning(
                    "paper_gen LLM: local vLLM call failed (%s); falling back to OpenRouter.",
                    exc,
                )
                # Force OpenRouter resolution on retry by disabling local pref temporarily.
                openrouter_endpoint = await self._resolve_openrouter_only()
                return await self._call_endpoint(openrouter_endpoint, request)
            raise

    async def _resolve_openrouter_only(self) -> _ResolvedEndpoint:
        settings = Config.get_global_settings()
        api_key = (
            settings.get("openrouter_api_key", "")
            or os.environ.get("OPENROUTER_API_KEY", "")
        )
        if not api_key:
            raise RuntimeError(
                "Local vLLM failed and no OpenRouter API key configured for fallback."
            )
        base = (
            settings.get("openrouter_base_url", "")
            or os.environ.get("OPENROUTER_BASE_URL", _DEFAULT_OPENROUTER_BASE)
        ).rstrip("/")
        model = (
            settings.get("openrouter_model", "")
            or os.environ.get("OPENROUTER_MODEL", _DEFAULT_OPENROUTER_MODEL)
        )
        return _ResolvedEndpoint(
            base_url=base,
            api_key=api_key,
            model=model,
            provider_name="openrouter",
        )

    # ----------------------------------------------- single endpoint caller

    async def _call_endpoint(
        self, endpoint: _ResolvedEndpoint, request: LLMRequest
    ) -> LLMResponse:
        """Stream the chat completion from `endpoint`, aggregate to a single string.

        Uses `stream=true` unconditionally because:
          - the user's relay forces streaming for reasoning models (gpt-5.x)
          - non-reasoning models (claude-haiku-4-5) accept streaming fine
          - keeping a single code path simplifies retries and error handling
        """
        model = request.model or endpoint.model
        payload = {
            "model": model,
            "messages": self._build_messages(request),
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "stream": True,
        }
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if endpoint.api_key:
            headers["Authorization"] = f"Bearer {endpoint.api_key}"
        if endpoint.provider_name == "openrouter":
            # OpenRouter requests these for analytics; harmless on relay too.
            headers["HTTP-Referer"] = "https://pathlab.local"
            headers["X-Title"] = "PathLab Paper Generation"

        client = self._client()
        last_exc: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 1):
            try:
                async with client.stream(
                    "POST",
                    f"{endpoint.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self._timeout,
                ) as response:
                    if (
                        response.status_code in _RETRYABLE_STATUSES
                        and attempt < self._max_retries
                    ):
                        logger.warning(
                            "paper_gen LLM HTTP %s (provider=%s, attempt %d/%d); retrying",
                            response.status_code,
                            endpoint.provider_name,
                            attempt,
                            self._max_retries,
                        )
                        await response.aclose()
                        await asyncio.sleep(_backoff_delay(attempt))
                        continue

                    if response.is_error:
                        body = await _read_error_body(response)
                        raise httpx.HTTPStatusError(
                            f"LLM call failed: HTTP {response.status_code}; body={body!r}",
                            request=response.request,
                            response=response,
                        )

                    return await _aggregate_stream(
                        response,
                        provider_used=endpoint.provider_name,
                        fallback_model=model,
                    )
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "paper_gen LLM transport error (provider=%s, attempt %d/%d): %s",
                    endpoint.provider_name, attempt, self._max_retries, exc,
                )
                if attempt == self._max_retries:
                    raise
                await asyncio.sleep(_backoff_delay(attempt))
                continue

        raise RuntimeError(
            f"LLM call failed after {self._max_retries} attempts: {last_exc!r}"
        )


def _join_content(parts: list[dict]) -> str:
    """Some providers return content as list[{type, text}]. Concatenate text parts."""
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text":
            chunks.append(part.get("text", ""))
    return "".join(chunks)


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with jitter (matches chat client's retry curve)."""
    base = min(8.0, 0.5 * (2 ** (attempt - 1)))
    return base + random.uniform(0.0, 0.5)


async def _read_error_body(response: httpx.Response) -> str:
    """Read the (possibly partial) body of an erroring streamed response."""
    try:
        await response.aread()
        return (response.text or "")[:500]
    except Exception:
        return ""


async def _aggregate_stream(
    response: httpx.Response,
    *,
    provider_used: str,
    fallback_model: str,
) -> LLMResponse:
    """Consume an OpenAI-style SSE stream and return a single LLMResponse.

    Each `data:` line is a JSON chunk shaped roughly like::

        {"choices":[{"delta":{"content":"..."},"finish_reason":null}]}

    Final chunks add `finish_reason="stop"` and may include a `usage` dict.
    The relay's response also embeds `model` on each chunk; we capture it
    from whichever chunk first reports it.
    """
    import json as _json

    text_parts: list[str] = []
    last_finish_reason: Optional[str] = None
    last_model: Optional[str] = None
    last_usage: dict = {}

    async for raw in response.aiter_lines():
        if not raw or not raw.startswith("data:"):
            continue
        chunk = raw[5:].lstrip()
        if chunk == "[DONE]":
            break
        try:
            payload = _json.loads(chunk)
        except _json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        # capture model + usage if present
        if not last_model and isinstance(payload.get("model"), str):
            last_model = payload["model"]
        if isinstance(payload.get("usage"), dict):
            last_usage = payload["usage"]

        choices = payload.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        if not isinstance(choice, dict):
            continue

        delta = choice.get("delta") or {}
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                text_parts.append(_join_content(content))

        # Some providers also send `message.content` on a non-streamed-style
        # final chunk; cover that too.
        message = choice.get("message")
        if isinstance(message, dict):
            mc = message.get("content")
            if isinstance(mc, str):
                text_parts.append(mc)

        fr = choice.get("finish_reason")
        if isinstance(fr, str):
            last_finish_reason = fr

    return LLMResponse(
        text="".join(text_parts),
        model=last_model or fallback_model,
        provider_used=provider_used,
        finish_reason=last_finish_reason,
        prompt_tokens=last_usage.get("prompt_tokens"),
        completion_tokens=last_usage.get("completion_tokens"),
    )


# ---------------------------------------------------------------------------
# Factory + test injection
# ---------------------------------------------------------------------------

_DEFAULT_PROVIDER: Optional[LLMProvider] = None


def get_default_provider() -> LLMProvider:
    """Return the process-wide default provider.

    Settings are re-read on every `complete()` call inside the provider, so
    holding a singleton is safe.
    """
    global _DEFAULT_PROVIDER
    if _DEFAULT_PROVIDER is None:
        _DEFAULT_PROVIDER = PathLabLLMProvider()
    return _DEFAULT_PROVIDER


def set_default_provider(provider: LLMProvider) -> None:
    """Override the default (used in tests)."""
    global _DEFAULT_PROVIDER
    _DEFAULT_PROVIDER = provider
