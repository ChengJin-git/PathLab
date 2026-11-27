"""Resolve the platform's effective model without mutating process environment."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Awaitable, Callable

import httpx

from .config import Config
from .settings_store import read_config


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    base_url: str
    api_key: str
    protocol: str = "chat"

    def public(self) -> dict:
        return {key: value for key, value in asdict(self).items() if key != "api_key"}

    def opencode_provider(self) -> dict:
        package = "@opencode/ai/providers/openai-compatible"
        if self.provider == "openrouter":
            package = "@opencode/ai/providers/openrouter"
        elif self.protocol == "responses":
            package += "/responses"
        return {
            "name": "PathLab Settings",
            "package": package,
            "settings": {"baseURL": self.base_url, "apiKey": "{env:PATHLAB_MODEL_KEY}"},
            "models": {
                "research": {
                    "name": self.model,
                    "modelID": self.model,
                    "capabilities": {"tools": True},
                    "limit": {"context": 128000, "output": 16000},
                }
            },
        }


async def resolve_model_config(
    settings: dict | None = None,
    probe: Callable[[str, str], Awaitable[tuple[bool, str | None]]] | None = None,
) -> ModelConfig:
    # Worker processes must see Settings changes saved by the Gateway.
    if settings is None:
        settings = Config._build_global_settings(
            read_config(Config.STORAGE_CONFIG_FILE)
        )
    if settings.get("local_vllm_enabled"):
        url = str(settings.get("local_vllm_base_url") or "").rstrip("/")
        key = str(settings.get("local_vllm_api_key") or "")
        try:
            if probe:
                available, detected = await probe(url, key)
            else:
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(
                        f"{url}/models", headers={"Authorization": f"Bearer {key}"}
                    )
                    response.raise_for_status()
                    models = response.json().get("data", [])
                available, detected = True, models[0]["id"] if models else None
            model = settings.get("local_vllm_model") or detected
            if model and available:
                return ModelConfig("vllm", model, url, key)
        except (httpx.HTTPError, ValueError, KeyError):
            pass
    model = str(settings.get("openrouter_model") or "").strip()
    url = str(settings.get("openrouter_base_url") or "").rstrip("/")
    key = str(settings.get("openrouter_api_key") or "")
    if not model or not url or not key:
        raise ValueError("Configure a model, endpoint and API key in Settings")
    provider = "openrouter" if "openrouter.ai" in url else "compatible"
    return ModelConfig(provider, model, url, key)
