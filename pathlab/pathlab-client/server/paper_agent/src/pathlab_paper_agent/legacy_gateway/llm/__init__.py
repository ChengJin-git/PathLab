"""LLM provider abstraction for the paper-generation pipeline.

Aligned with the main chat assistant: vLLM-preferred / OpenRouter-fallback,
shared settings + probe cache + httpx pool. See `client.py` docstring.
"""

from .client import (
    LLMProvider,
    PathLabLLMProvider,
    LLMRequest,
    LLMResponse,
    LLMImage,
    get_default_provider,
    set_default_provider,
)

__all__ = [
    "LLMProvider",
    "PathLabLLMProvider",
    "LLMRequest",
    "LLMResponse",
    "LLMImage",
    "get_default_provider",
    "set_default_provider",
]
