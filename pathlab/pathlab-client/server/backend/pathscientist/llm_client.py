"""Shared chat LLM construction and invocation helpers.

The default path preserves the existing PathScientist behavior. The explicit
``codex-relay`` profile reads the user's Codex relay config/auth files and
uses Chat Completions for auxiliary LLM calls. The relay's streaming Responses
path can return ``output=[]`` even when output tokens were generated, which
breaks structured JSON parsing in grounding.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

from pydantic import SecretStr

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

from .config import (
    PathScientistConfig,
    resolve_llm_api_key,
    resolve_llm_base_url,
    resolve_llm_model,
    resolve_required_llm_model,
)


@dataclass(frozen=True)
class LLMRuntimeConfig:
    model: str
    api_key: str = ""
    base_url: str = ""
    profile: str = ""
    wire_api: str = ""


def _default_codex_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def _default_codex_auth_path() -> Path:
    return Path.home() / ".codex" / "auth.json"


def _normalize_openai_model(model: str) -> str:
    """Prefix bare Codex/OpenAI model ids for LiteLLM/OpenHands routing."""
    model = (model or "").strip()
    if not model:
        return model
    if "/" in model:
        return model
    return f"openai/{model}"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as e:
        raise RuntimeError(f"codex-relay profile requested but {path} is missing") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"codex-relay profile requested but {path} is not valid JSON") from e


def _normalize_codex_relay_wire_api(wire_api: str) -> str:
    """Map Codex relay wire settings to the safe PathScientist call path.

    Codex itself uses the relay's Responses endpoint, but PathScientist's
    auxiliary calls need text back synchronously for JSON parsing. The relay's
    streaming Responses path can complete with an empty ``response.output``;
    Chat Completions does not have that failure mode on the same relay/model.
    """
    wire = (wire_api or "responses").strip().lower()
    if wire in {
        "responses",
        "response",
        "completion",
        "chat",
        "chat_completion",
        "chat-completions",
    }:
        return "completion"
    raise RuntimeError(
        f"codex-relay profile supports responses/completion wire APIs, got {wire_api!r}"
    )


def _resolve_project_local_codex_relay_config(
    config: PathScientistConfig,
) -> LLMRuntimeConfig | None:
    model = resolve_llm_model(getattr(config, "llm_model", ""), default="")
    api_key = resolve_llm_api_key(getattr(config, "llm_api_key", ""))
    base_url = resolve_llm_base_url(getattr(config, "llm_base_url", ""))
    if not (model and api_key and base_url):
        return None

    wire_api = _normalize_codex_relay_wire_api(
        getattr(config, "llm_wire_api", "")
        or os.environ.get("PATHSCIENTIST_LLM_WIRE_API", "")
        or "responses"
    )

    # Same /v1 auto-append as the toml branch — see Fix G note in
    # `_resolve_codex_relay_config`. Applies even when the user explicitly
    # sets a project-local base_url that ends in `/openai`, so the env var
    # `PATHSCIENTIST_LLM_BASE_URL=https://relay.../openai` Just Works.
    base_url = base_url.rstrip("/")
    if base_url.endswith("/openai"):
        base_url = base_url + "/v1"

    return LLMRuntimeConfig(
        model=_normalize_openai_model(model),
        api_key=api_key,
        base_url=base_url,
        profile="codex-relay",
        wire_api=wire_api,
    )


def _resolve_codex_relay_config(config: PathScientistConfig) -> LLMRuntimeConfig:
    local_config = _resolve_project_local_codex_relay_config(config)
    if local_config is not None:
        return local_config

    config_path_raw = (
        config.codex_config_path
        or os.environ.get("PATHSCIENTIST_CODEX_CONFIG", "")
    )
    auth_path_raw = (
        config.codex_auth_path
        or os.environ.get("PATHSCIENTIST_CODEX_AUTH", "")
    )
    config_path = Path(config_path_raw).expanduser() if config_path_raw else _default_codex_config_path()
    auth_path = Path(auth_path_raw).expanduser() if auth_path_raw else _default_codex_auth_path()

    try:
        codex_config = tomllib.loads(config_path.read_text())
    except FileNotFoundError as e:
        raise RuntimeError(
            f"codex-relay profile requested but Codex config.toml at {config_path} is missing"
        ) from e
    except tomllib.TOMLDecodeError as e:
        raise RuntimeError(f"codex-relay profile requested but {config_path} is not valid TOML") from e

    model = str(codex_config.get("model") or "").strip()
    if not model:
        raise RuntimeError("codex-relay profile requested but Codex config has no model")

    provider_name = str(codex_config.get("model_provider") or "").strip()
    providers = codex_config.get("model_providers") or {}
    provider = providers.get(provider_name) if provider_name else None
    if not isinstance(provider, dict):
        raise RuntimeError(
            f"codex-relay profile requested but provider '{provider_name}' is missing"
        )

    base_url = str(provider.get("base_url") or "").strip()
    if not base_url:
        raise RuntimeError(
            f"codex-relay profile requested but provider '{provider_name}' has no base_url"
        )
    wire_api = _normalize_codex_relay_wire_api(
        getattr(config, "llm_wire_api", "")
        or os.environ.get("PATHSCIENTIST_LLM_WIRE_API", "")
        or str(provider.get("wire_api") or "responses")
    )

    auth = _read_json(auth_path)
    api_key = str(auth.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError(
            f"codex-relay profile requested but OPENAI_API_KEY is missing in {auth_path}"
        )

    # Allow PATHSCIENTIST_LLM_* env vars (and explicit config attrs) to
    # override individual fields pulled from ~/.codex/* without requiring
    # all three to be set (which is the bar the project-local resolver
    # checks). Lets users pin e.g. base_url=".../openai/v1" while still
    # reading model + api_key from the Codex config they keep up to date.
    base_url_override = resolve_llm_base_url(getattr(config, "llm_base_url", ""))
    if base_url_override:
        base_url = base_url_override
    model_override = resolve_llm_model(getattr(config, "llm_model", ""), default="")
    if model_override:
        model = model_override
    api_key_override = resolve_llm_api_key(getattr(config, "llm_api_key", ""))
    if api_key_override:
        api_key = api_key_override

    # Codex CLI's relay convention is to write `https://relay.../openai`
    # (no `/v1`), because Codex itself hits `/openai/responses`. PathScientist
    # routes through Chat Completions (see Fix F in build_chat_llm), which the
    # relay only serves at `/openai/v1/chat/completions`. Without `/v1` the
    # request hits `/openai/chat/completions` and 404s. Append `/v1` only
    # when the URL ends with `/openai` exactly, so URLs that already include
    # `/v1` or use a different layout pass through unchanged.
    base_url = base_url.rstrip("/")
    if base_url.endswith("/openai"):
        base_url = base_url + "/v1"

    return LLMRuntimeConfig(
        model=_normalize_openai_model(model),
        api_key=api_key,
        base_url=base_url,
        profile="codex-relay",
        wire_api=wire_api,
    )


def resolve_llm_runtime_config(
    config: PathScientistConfig | None,
    *,
    component: str,
) -> LLMRuntimeConfig:
    """Resolve chat LLM settings for a component."""
    config = config or PathScientistConfig()
    profile = (getattr(config, "llm_profile", "") or os.environ.get("PATHSCIENTIST_LLM_PROFILE", "")).strip()
    if profile == "codex-relay":
        return _resolve_codex_relay_config(config)
    if profile:
        raise RuntimeError(f"Unsupported LLM profile for {component}: {profile}")

    return LLMRuntimeConfig(
        model=resolve_required_llm_model(
            getattr(config, "llm_model", ""),
            component=component,
        ),
        api_key=resolve_llm_api_key(getattr(config, "llm_api_key", "")),
        base_url=resolve_llm_base_url(getattr(config, "llm_base_url", "")),
        profile="",
        wire_api=(getattr(config, "llm_wire_api", "") or os.environ.get("PATHSCIENTIST_LLM_WIRE_API", "")).strip().lower(),
    )


def make_llm_config(
    *,
    config: PathScientistConfig | None = None,
    llm_model: str = "",
    llm_api_key: str = "",
    llm_base_url: str = "",
) -> PathScientistConfig:
    """Return a config object with optional legacy LLM arguments applied."""
    base = config or PathScientistConfig()
    updates: dict[str, str] = {}
    if config is None or llm_model:
        updates["llm_model"] = llm_model
    if config is None or llm_api_key:
        updates["llm_api_key"] = llm_api_key
    if config is None or llm_base_url:
        updates["llm_base_url"] = llm_base_url
    return replace(base, **updates) if updates else base


def has_chat_llm_config(config: PathScientistConfig | None = None) -> bool:
    """Return whether chat LLM config is present without opening auth files."""
    cfg = config or PathScientistConfig()
    profile = (
        getattr(cfg, "llm_profile", "")
        or os.environ.get("PATHSCIENTIST_LLM_PROFILE", "")
    ).strip()
    if profile:
        return True
    return bool(resolve_llm_model(getattr(cfg, "llm_model", ""), default=""))


def _build_streaming_llm_class():
    """Return an LLM subclass that supplies a no-op ``on_token`` when
    streaming is required and the caller did not provide one.

    Codex relay (relay.1hui.wang) returns ``400 {"detail":"Stream must be
    set to true"}`` for non-streaming chat completions, so we set
    ``stream=True`` for the codex-relay profile. But OpenHands SDK's
    ``LLM.completion`` raises ``ValueError: Streaming requires an
    on_token callback`` when ``stream=True`` but no callback is provided
    — and PathScientist's ``LocalConversation`` is built without
    ``token_callbacks`` (no per-token UI hook is needed). Bridge the two:
    if the caller didn't pass ``on_token`` and streaming is on, inject a
    no-op so the SDK is satisfied. Token chunks are still aggregated and
    returned by the underlying litellm streaming path.
    """
    from openhands.sdk.llm import LLM

    class _StreamingDefaultLLM(LLM):
        def completion(self, *args, on_token=None, **kwargs):  # type: ignore[override]
            stream_enabled = bool(kwargs.get("stream", False)) or bool(self.stream)
            if stream_enabled and on_token is None:
                on_token = lambda _token: None  # noqa: E731
            return super().completion(*args, on_token=on_token, **kwargs)

        # Models that report ``uses_responses_api() == True`` (e.g. gpt-5.5)
        # are routed through ``llm.responses()`` by ``make_llm_completion``,
        # not ``llm.completion()``. Same on_token guard at llm.py:903 applies,
        # so override here too.
        def responses(self, *args, on_token=None, **kwargs):  # type: ignore[override]
            stream_enabled = bool(kwargs.get("stream", False)) or bool(self.stream)
            if stream_enabled and on_token is None:
                on_token = lambda _token: None  # noqa: E731
            return super().responses(*args, on_token=on_token, **kwargs)

        # Codex relay (relay.1hui.wang) has a bug in its Responses API
        # streaming: function_call items stream correctly through
        # ``ResponseOutputItemDoneEvent`` (with full name + args + call_id),
        # but the terminal ``ResponseCompletedEvent.response.output`` arrives
        # as an empty list. OpenHands trusts the completed event and so loses
        # all tool calls — the agent loop then sees no tool calls per turn
        # and stalls on "Please use a tool to proceed" reminders.
        #
        # Chat Completions API on the same relay + model does NOT have this
        # bug: tool_call deltas aggregate cleanly via litellm.stream_chunk_builder.
        # Force the codex-relay path through Chat Completions until the relay
        # is fixed. Tested: gpt-5.5 returns tool_calls fine via
        # /openai/v1/chat/completions.
        def uses_responses_api(self) -> bool:  # type: ignore[override]
            return False

    return _StreamingDefaultLLM


def build_chat_llm(
    config: PathScientistConfig | None,
    *,
    component: str,
    usage_id: str,
    temperature: float | None,
    **overrides: Any,
):
    """Build an OpenHands LLM from resolved runtime config."""
    from openhands.sdk.llm import LLM

    runtime = resolve_llm_runtime_config(config, component=component)
    llm_kwargs: dict[str, Any] = {
        "model": runtime.model,
        "temperature": temperature,
        "usage_id": usage_id,
    }
    if runtime.api_key:
        llm_kwargs["api_key"] = SecretStr(runtime.api_key)
    if runtime.base_url:
        llm_kwargs["base_url"] = runtime.base_url
    llm_kwargs.update(overrides)

    # Codex relay (relay.1hui.wang) rejects non-streaming chat completions
    # with `400 {"detail":"Stream must be set to true"}`. Default stream=True
    # for codex-relay profile so the main OpenHands agent loop (which goes
    # through chat completions, not Responses API) can talk to the relay.
    # An explicit `stream=...` in overrides still wins.
    if runtime.profile == "codex-relay" and "stream" not in llm_kwargs:
        llm_kwargs["stream"] = True

    # Codex CLI's toml sets `model_reasoning_effort = "xhigh"` for this same
    # relay+model. Match that for parity — gpt-5.5 reasons better at xhigh
    # and the relay supports the level. Caller-supplied override still wins.
    if runtime.profile == "codex-relay" and "reasoning_effort" not in llm_kwargs:
        llm_kwargs["reasoning_effort"] = "xhigh"

    # When streaming is on, OpenHands LLM.completion() raises ValueError
    # unless an on_token callback is provided. Pathscientist's LocalConversation
    # is built without token_callbacks, so use the streaming-default subclass
    # that injects a no-op on_token to bridge the contract.
    if llm_kwargs.get("stream"):
        llm_class = _build_streaming_llm_class()
    else:
        llm_class = LLM

    llm = llm_class(**llm_kwargs)
    # Keep wire API near the object so auxiliary call sites do not need to
    # resolve config twice. This is intentionally project-private metadata.
    setattr(llm, "_pathscientist_wire_api", runtime.wire_api)
    setattr(llm, "_pathscientist_llm_profile", runtime.profile)
    return llm


def invoke_chat_llm(
    llm,
    *,
    messages: list,
    tools: Sequence | None = None,
    wire_api: str = "",
    **kwargs: Any,
):
    """Call an OpenHands LLM through the correct wire API."""
    resolved_wire = (wire_api or getattr(llm, "_pathscientist_wire_api", "") or "").lower()
    profile = (getattr(llm, "_pathscientist_llm_profile", "") or "").lower()
    if profile == "codex-relay" and resolved_wire == "responses":
        # Historical configs advertise "responses" because that is what Codex
        # uses, but PathScientist's structured auxiliary calls must use Chat
        # Completions to avoid empty Responses output on the relay.
        resolved_wire = "completion"
    use_responses = resolved_wire == "responses"
    if not use_responses:
        try:
            use_responses = bool(llm.uses_responses_api())
        except Exception:
            use_responses = False

    if use_responses:
        response = llm.responses(
            messages=messages,
            tools=list(tools or []),
            include=None,
            store=False,
            **kwargs,
        )
        if _should_retry_empty_responses_with_completion(response):
            return llm.completion(
                messages=messages,
                tools=list(tools or []),
                **kwargs,
            )
        return response
    return llm.completion(
        messages=messages,
        tools=list(tools or []),
        **kwargs,
    )


def _field(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from dict-like or object-like response shapes."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _extract_content_text(content: Any) -> str:
    """Extract text from common OpenHands/LiteLLM/OpenAI content shapes."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for key in ("text", "output_text", "content"):
            value = content.get(key)
            if isinstance(value, str):
                return value
        return ""
    if isinstance(content, (list, tuple)):
        parts = [_extract_content_text(part).strip() for part in content]
        return "\n".join(part for part in parts if part)

    for key in ("text", "output_text", "content"):
        value = getattr(content, key, None)
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            nested = _extract_content_text(value)
            if nested:
                return nested
    return ""


def _extract_text_from_raw_response(raw_response: Any) -> str:
    """Fallback extraction for cases where OpenHands normalization drops text."""
    if raw_response is None:
        return ""

    direct = _extract_content_text(_field(raw_response, "output_text", None))
    if direct:
        return direct

    choices = _field(raw_response, "choices", None) or []
    if choices:
        first_choice = choices[0]
        message = _field(first_choice, "message", None)
        text = _extract_content_text(_field(message, "content", None))
        if text:
            return text

    output = _field(raw_response, "output", None) or []
    output_parts: list[str] = []
    for item in output:
        if _field(item, "type", "") != "message":
            continue
        text = _extract_content_text(_field(item, "content", None)).strip()
        if text:
            output_parts.append(text)
    return "\n".join(output_parts)


def extract_text(response) -> str:
    """Extract assistant text from OpenHands/LiteLLM response variants."""
    text = _extract_content_text(_field(_field(response, "message", None), "content", None))
    if text:
        return text

    text = _extract_content_text(_field(response, "content", None))
    if text:
        return text

    return _extract_text_from_raw_response(_field(response, "raw_response", None))


def _should_retry_empty_responses_with_completion(response) -> bool:
    """Detect the Responses-API empty-output failure and retry via chat.

    The relay failure mode is specific: the call reports generated output
    tokens, but the normalized response has no assistant text, no choices, and
    an empty ``output`` list. Retrying via Chat Completions recovers the text
    without changing the prompt.
    """
    if extract_text(response).strip():
        return False
    raw_response = _field(response, "raw_response", None)
    if raw_response is None:
        return False
    output = _field(raw_response, "output", None)
    choices = _field(raw_response, "choices", None)
    usage = _field(raw_response, "usage", {}) or {}
    output_tokens = _field(usage, "output_tokens", 0) or 0
    try:
        output_token_count = int(output_tokens)
    except (TypeError, ValueError):
        output_token_count = 0
    return output_token_count > 0 and not output and not choices
