"""Shared helpers used across PathLab paper-agent LLM agents.

These primitives were duplicated verbatim across outline / plotting /
literature_review / section_writing / content_refinement agents. Centralising
them here gives a single source of truth for: the no-network CI safeguard, the
``Input payload:`` reverse-parser used by every no-network fixture, the
generic LLM response unwrapper, and the JSON-object scanner that recovers a
``{...}`` blob from text the LLM may have wrapped in commentary.

Per-agent extras (e.g. agent-specific exception types or default LLM client
factories) intentionally stay inside their own module.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..llm import LLMResponse

_PAYLOAD_MARKER = "Input payload:"


def ci_should_disable_network_llm() -> bool:
    """Return True when pytest is running and network LLM calls are not opted in.

    Tests must opt into real provider calls explicitly via
    ``PAPER_GEN_LLM_ALLOW_NETWORK_IN_TESTS=1`` so a developer who exports
    ``PAPER_GEN_LLM_BASE_URL`` for smoke testing cannot accidentally let pytest
    reach a real provider.
    """
    if os.environ.get("PAPER_GEN_LLM_ALLOW_NETWORK_IN_TESTS") == "1":
        return False
    return "PYTEST_CURRENT_TEST" in os.environ


def payload_from_prompt(prompt: str) -> dict[str, Any]:
    """Reverse-parse the ``Input payload:`` JSON block produced by every prompt."""
    if _PAYLOAD_MARKER not in prompt:
        return {}
    raw = prompt.split(_PAYLOAD_MARKER, 1)[1].strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def response_text(response: Any) -> str:
    """Return the textual content from any LLM response shape."""
    raw_content = (
        response.content if isinstance(response, LLMResponse) else getattr(response, "content", response)
    )
    return raw_content if isinstance(raw_content, str) else str(raw_content)


def decode_first_json_object(text: str) -> Any | None:
    """Return the first ``{...}`` object the JSON decoder can recover from ``text``.

    Returns ``None`` when no object can be parsed; callers raise their own
    agent-specific error. This keeps the helper free of agent-level exception
    coupling while preserving the recovery behaviour the agents shared.
    """
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return value
    return None


__all__ = [
    "ci_should_disable_network_llm",
    "payload_from_prompt",
    "response_text",
    "decode_first_json_object",
]
