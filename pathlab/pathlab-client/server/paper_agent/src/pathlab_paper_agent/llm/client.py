"""OpenAI-compatible LLM provider for paper-generation agents."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

_ENV_OVERRIDE = {
    "base_url": "PAPER_GEN_LLM_BASE_URL",
    "api_key": "PAPER_GEN_LLM_API_KEY",
    "model": "PAPER_GEN_LLM_MODEL",
}
_ENV_REASONING_EFFORT = "PAPER_GEN_LLM_REASONING_EFFORT"
_ENV_TIMEOUT_S = "PAPER_GEN_LLM_TIMEOUT_S"
_ENV_MAX_COMPLETION_TOKENS = "PAPER_GEN_LLM_MAX_COMPLETION_TOKENS"
# httpx errors that are likely transient (network blip, temporary timeout). One
# retry buys resilience against single packet loss without masking real outages.
_TRANSIENT_HTTP_ERRORS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
)
_MAX_TRANSIENT_RETRIES = 1
_DEFAULT_VLLM_BASE_URL = "http://pathlab-vllm:8000/v1"
_DEFAULT_VLLM_MODEL = "gpt-5.5"
_DEFAULT_REASONING_EFFORT = "xhigh"
_DEFAULT_TIMEOUT_S = 300.0
_DEFAULT_MAX_COMPLETION_TOKENS = 16_384
_DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_OPENROUTER_MODEL = "openai/gpt-5.5"
_LOCAL_ENV_LOADED = False


class LLMConfigurationError(RuntimeError):
    """Raised when provider environment variables are incomplete."""


class LLMProviderError(RuntimeError):
    """Raised when an LLM provider returns an invalid or failed response."""


@dataclass(frozen=True)
class LLMMessage:
    """One chat-completion message."""

    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class LLMResponse:
    """Aggregated text returned by an LLM call."""

    content: str
    model: str | None = None
    provider: str | None = None
    raw: Mapping[str, Any] | None = None


class LLMClient(Protocol):
    """Minimal chat-completion interface used by agents."""

    def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float = 0.2,
        response_format: Mapping[str, Any] | None = None,
        stream: bool | None = None,
    ) -> LLMResponse:
        """Return a single aggregated response for a chat completion."""


@dataclass(frozen=True)
class LLMConfig:
    """Resolved OpenAI-compatible provider settings."""

    base_url: str
    api_key: str
    model: str
    provider: str
    reasoning_effort: str | None = _DEFAULT_REASONING_EFFORT
    timeout_s: float = _DEFAULT_TIMEOUT_S
    max_completion_tokens: int | None = _DEFAULT_MAX_COMPLETION_TOKENS

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Resolve provider config in the documented three-level order.

        Order:
        1. Explicit PAPER_GEN_LLM_BASE_URL / _API_KEY / _MODEL override.
        2. Internal vLLM-compatible endpoint.
        3. OpenRouter is configured as a runtime fallback when a key exists.
        """
        _load_local_env_once()
        override = {key: os.environ.get(env_name) for key, env_name in _ENV_OVERRIDE.items()}
        if any(override.values()):
            missing = [env_name for key, env_name in _ENV_OVERRIDE.items() if not override[key]]
            if missing:
                missing_list = ", ".join(missing)
                raise LLMConfigurationError(
                    f"Incomplete PAPER_GEN_LLM_* override; missing {missing_list}"
                )
            return cls(
                base_url=str(override["base_url"]).rstrip("/"),
                api_key=str(override["api_key"]),
                model=str(override["model"]),
                provider="env_override",
                reasoning_effort=_reasoning_effort_from_env(_ENV_REASONING_EFFORT),
                timeout_s=_timeout_from_env(_ENV_TIMEOUT_S),
                max_completion_tokens=_max_completion_tokens_from_env(
                    _ENV_MAX_COMPLETION_TOKENS
                ),
            )

        return cls(
            base_url=os.environ.get("PAPER_GEN_VLLM_BASE_URL", _DEFAULT_VLLM_BASE_URL).rstrip("/"),
            api_key=os.environ.get("PAPER_GEN_VLLM_API_KEY", "EMPTY"),
            model=os.environ.get("PAPER_GEN_VLLM_MODEL", _DEFAULT_VLLM_MODEL),
            provider="vllm_internal",
            reasoning_effort=_reasoning_effort_from_env("PAPER_GEN_VLLM_REASONING_EFFORT"),
            timeout_s=_timeout_from_env("PAPER_GEN_VLLM_TIMEOUT_S"),
            max_completion_tokens=_max_completion_tokens_from_env(
                "PAPER_GEN_VLLM_MAX_COMPLETION_TOKENS"
            ),
        )

    @classmethod
    def openrouter_from_env(cls) -> "LLMConfig | None":
        """Return an OpenRouter fallback config when an API key is available."""
        _load_local_env_once()
        api_key = os.environ.get("PAPER_GEN_OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return None
        return cls(
            base_url=os.environ.get(
                "PAPER_GEN_OPENROUTER_BASE_URL",
                _DEFAULT_OPENROUTER_BASE_URL,
            ).rstrip("/"),
            api_key=api_key,
            model=os.environ.get("PAPER_GEN_OPENROUTER_MODEL", _DEFAULT_OPENROUTER_MODEL),
            provider="openrouter",
            reasoning_effort=_reasoning_effort_from_env("PAPER_GEN_OPENROUTER_REASONING_EFFORT"),
            timeout_s=_timeout_from_env("PAPER_GEN_OPENROUTER_TIMEOUT_S"),
            max_completion_tokens=_max_completion_tokens_from_env(
                "PAPER_GEN_OPENROUTER_MAX_COMPLETION_TOKENS"
            ),
        )

    @property
    def requires_streaming(self) -> bool:
        return _requires_streaming_model(self.model)

    @property
    def supports_reasoning_effort(self) -> bool:
        return _supports_reasoning_effort(self.model)

    @property
    def supports_max_completion_tokens(self) -> bool:
        return _supports_max_completion_tokens(self.model)


def _requires_streaming_model(model: str) -> bool:
    normalized = model.lower()
    return (
        normalized.startswith("gpt-5")
        or "gpt-5" in normalized
        or normalized.startswith(("o1", "o3", "o4"))
        or "reasoning" in normalized
    )


def _supports_reasoning_effort(model: str) -> bool:
    return _requires_streaming_model(model)


def _supports_max_completion_tokens(model: str) -> bool:
    return _requires_streaming_model(model)


def _reasoning_effort_from_env(env_name: str) -> str | None:
    value = (
        os.environ.get(env_name)
        or os.environ.get(_ENV_REASONING_EFFORT)
        or _DEFAULT_REASONING_EFFORT
    )
    cleaned = value.strip().lower()
    if cleaned in {"", "none", "off", "false", "0"}:
        return None
    return cleaned


def _timeout_from_env(env_name: str) -> float:
    value = os.environ.get(env_name) or os.environ.get(_ENV_TIMEOUT_S)
    if value is None or not value.strip():
        return _DEFAULT_TIMEOUT_S
    try:
        timeout_s = float(value)
    except ValueError as exc:
        raise LLMConfigurationError(f"{env_name} must be a numeric timeout in seconds") from exc
    if timeout_s <= 0:
        raise LLMConfigurationError(f"{env_name} must be positive")
    return timeout_s


def _max_completion_tokens_from_env(env_name: str) -> int | None:
    value = os.environ.get(env_name) or os.environ.get(_ENV_MAX_COMPLETION_TOKENS)
    if value is None:
        return _DEFAULT_MAX_COMPLETION_TOKENS
    cleaned = value.strip().lower()
    if cleaned in {"", "none", "off", "false", "0"}:
        return None
    try:
        max_tokens = int(cleaned)
    except ValueError as exc:
        raise LLMConfigurationError(f"{env_name} must be an integer max token count") from exc
    if max_tokens <= 0:
        raise LLMConfigurationError(f"{env_name} must be positive")
    return max_tokens


def _load_local_env_once() -> None:
    """Load paper_agent/.env for local CLI/dev-server runs without shell sourcing."""
    global _LOCAL_ENV_LOADED
    if _LOCAL_ENV_LOADED:
        return
    _LOCAL_ENV_LOADED = True
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(env_path, override=False)


class OpenAICompatibleLLMClient:
    """Small httpx client for OpenAI-compatible chat completions.

    Reasoning models are streamed by default; SSE deltas are aggregated before
    returning so downstream agents always receive one `LLMResponse`.
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        *,
        http_client: httpx.Client | None = None,
        fallback_config: LLMConfig | None = None,
    ) -> None:
        self.config = config or LLMConfig.from_env()
        self._client = http_client
        self._owns_client = http_client is None
        self._fallback_config = fallback_config
        if config is None and fallback_config is None and self.config.provider == "vllm_internal":
            self._fallback_config = LLMConfig.openrouter_from_env()

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()

    def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float = 0.2,
        response_format: Mapping[str, Any] | None = None,
        stream: bool | None = None,
    ) -> LLMResponse:
        use_stream = self.config.requires_streaming if stream is None else stream
        try:
            return self._complete_with_config(
                self.config,
                messages,
                temperature=temperature,
                response_format=response_format,
                stream=use_stream,
            )
        except (httpx.HTTPError, LLMProviderError):
            if self._fallback_config is None:
                raise
            fallback_stream = self._fallback_config.requires_streaming if stream is None else stream
            return self._complete_with_config(
                self._fallback_config,
                messages,
                temperature=temperature,
                response_format=response_format,
                stream=fallback_stream,
            )

    def _complete_with_config(
        self,
        config: LLMConfig,
        messages: Sequence[LLMMessage],
        *,
        temperature: float,
        response_format: Mapping[str, Any] | None,
        stream: bool,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": [message.to_dict() for message in messages],
            "temperature": temperature,
            "stream": stream,
        }
        if config.reasoning_effort and config.supports_reasoning_effort:
            payload["reasoning_effort"] = config.reasoning_effort
        if config.max_completion_tokens and config.supports_max_completion_tokens:
            payload["max_completion_tokens"] = config.max_completion_tokens
        if response_format is not None:
            payload["response_format"] = dict(response_format)

        endpoint = f"{config.base_url}/chat/completions"
        attempts = 0
        while True:
            try:
                if stream:
                    return self._stream_completion(config, endpoint, payload)
                return self._blocking_completion(config, endpoint, payload)
            except _TRANSIENT_HTTP_ERRORS:
                attempts += 1
                if attempts > _MAX_TRANSIENT_RETRIES:
                    raise

    def _http_client(self, timeout_s: float) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=timeout_s)
        return self._client

    @staticmethod
    def _headers(config: LLMConfig) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }

    def _blocking_completion(
        self,
        config: LLMConfig,
        endpoint: str,
        payload: Mapping[str, Any],
    ) -> LLMResponse:
        response = self._http_client(config.timeout_s).post(
            endpoint,
            headers=self._headers(config),
            json=payload,
        )
        response.raise_for_status()
        data = _json_mapping_from_response(response)
        return LLMResponse(
            content=_content_from_completion_payload(data),
            model=data.get("model") or config.model,
            provider=config.provider,
            raw=data,
        )

    def _stream_completion(
        self,
        config: LLMConfig,
        endpoint: str,
        payload: Mapping[str, Any],
    ) -> LLMResponse:
        chunks: list[str] = []
        last_model: str | None = None
        saw_reasoning = False
        finish_reason: str | None = None
        with self._http_client(config.timeout_s).stream(
            "POST",
            endpoint,
            headers=self._headers(config),
            json=payload,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                chunk = _content_from_sse_line(line)
                if chunk is None:
                    continue
                if isinstance(chunk, _SSEMeta):
                    last_model = chunk.model or last_model
                    saw_reasoning = saw_reasoning or chunk.saw_reasoning
                    finish_reason = chunk.finish_reason or finish_reason
                    continue
                chunks.append(chunk)
        if not chunks and saw_reasoning:
            token_hint = (
                f"max_completion_tokens={config.max_completion_tokens}"
                if config.max_completion_tokens
                else "max_completion_tokens is disabled"
            )
            reason_hint = f", finish_reason={finish_reason}" if finish_reason else ""
            raise LLMProviderError(
                "LLM stream ended without assistant content after emitting reasoning chunks "
                f"({token_hint}{reason_hint}). Increase max completion tokens or lower "
                "reasoning_effort."
            )
        return LLMResponse(
            content="".join(chunks),
            model=last_model or config.model,
            provider=config.provider,
            raw=None,
        )


@dataclass(frozen=True)
class _SSEMeta:
    model: str | None = None
    saw_reasoning: bool = False
    finish_reason: str | None = None


def _json_mapping_from_response(response: httpx.Response) -> Mapping[str, Any]:
    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise LLMProviderError("LLM response was not valid JSON") from exc
    if not isinstance(data, Mapping):
        raise LLMProviderError("LLM response must be a JSON object")
    return data


def _content_from_completion_payload(data: Mapping[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMProviderError("LLM response missing choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise LLMProviderError("LLM response choice is not an object")
    message = first.get("message")
    if isinstance(message, Mapping) and isinstance(message.get("content"), str):
        return message["content"]
    if isinstance(first.get("text"), str):
        return first["text"]
    raise LLMProviderError("LLM response missing message content")


def _content_from_sse_line(line: str) -> str | _SSEMeta | None:
    if not line:
        return None
    if line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None
    raw = line.removeprefix("data:").strip()
    if not raw or raw == "[DONE]":
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMProviderError("Invalid SSE JSON chunk from LLM provider") from exc
    if not isinstance(payload, Mapping):
        return None

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return _SSEMeta(model=payload.get("model") if isinstance(payload.get("model"), str) else None)
    first = choices[0]
    if not isinstance(first, Mapping):
        return None
    finish_reason = first.get("finish_reason")
    finish_reason_text = finish_reason if isinstance(finish_reason, str) else None
    delta = first.get("delta")
    if isinstance(delta, Mapping) and isinstance(delta.get("content"), str):
        return delta["content"]
    if isinstance(delta, Mapping) and isinstance(delta.get("reasoning_content"), str):
        return _SSEMeta(
            model=payload.get("model") if isinstance(payload.get("model"), str) else None,
            saw_reasoning=True,
            finish_reason=finish_reason_text,
        )
    message = first.get("message")
    if isinstance(message, Mapping) and isinstance(message.get("content"), str):
        return message["content"]
    if isinstance(first.get("text"), str):
        return first["text"]
    return _SSEMeta(
        model=payload.get("model") if isinstance(payload.get("model"), str) else None,
        finish_reason=finish_reason_text,
    )
