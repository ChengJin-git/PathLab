"""LLM helper for selection-level manuscript rewrites."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..llm import LLMClient, LLMMessage, LLMResponse, OpenAICompatibleLLMClient
from . import _common

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)
_SECTION_COMMAND_RE = re.compile(r"\\(?:section|subsection|subsubsection)\*?\{", re.IGNORECASE)


class SelectionRewriteError(RuntimeError):
    """Raised when the selection rewrite agent returns an unsafe patch."""


@dataclass(frozen=True)
class SelectionRewriteInputs:
    section_name: str
    selected_source_text: str
    selected_rendered_text: str | None
    paragraph_context: str
    user_note: str | None = None
    template_id: str | None = None
    evidence_context: str | None = None


@dataclass(frozen=True)
class SelectionRewriteResult:
    replacement_text: str
    rationale: str = ""


class SelectionRewriteAgent:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or _default_llm_client()

    def rewrite(self, inputs: SelectionRewriteInputs) -> SelectionRewriteResult:
        response = self.llm_client.complete(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "You edit one sentence/span in a scientific manuscript. "
                        "Rewrite only the selected source span. Do not add new metrics, citations, "
                        "cohorts, datasets, or claims. Preserve LaTeX commands/placeholders when present. "
                        'Return JSON only: {"replacement_text": "...", "rationale": "..."}'
                    ),
                ),
                LLMMessage(role="user", content=self._build_prompt(inputs)),
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        return parse_selection_rewrite_response(_response_text(response))

    def _build_prompt(self, inputs: SelectionRewriteInputs) -> str:
        payload = {
            "section_name": inputs.section_name,
            "template_id": inputs.template_id,
            "selected_source_span": inputs.selected_source_text,
            "selected_rendered_text": inputs.selected_rendered_text,
            "paragraph_context": inputs.paragraph_context,
            "evidence_context": inputs.evidence_context,
            "user_note": inputs.user_note,
            "rules": [
                "Return a replacement for the selected source span only.",
                "Do not return a full paragraph or a LaTeX section heading.",
                "Do not introduce raw \\cite{} commands or new metric values.",
            ],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


def parse_selection_rewrite_response(text: str) -> SelectionRewriteResult:
    stripped = text.strip()
    if not stripped:
        raise SelectionRewriteError("Selection rewrite LLM returned an empty response")
    fence_match = _JSON_FENCE_RE.search(stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise SelectionRewriteError(f"Selection rewrite LLM returned invalid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise SelectionRewriteError("Selection rewrite LLM response must be a JSON object")
    replacement = payload.get("replacement_text")
    if not isinstance(replacement, str) or not replacement.strip():
        raise SelectionRewriteError("Selection rewrite replacement_text must be non-empty")
    if _SECTION_COMMAND_RE.search(replacement) or "\n\n" in replacement.strip():
        raise SelectionRewriteError("Selection rewrite replacement must not contain full sections or paragraphs")
    return SelectionRewriteResult(
        replacement_text=replacement.strip(),
        rationale=str(payload.get("rationale") or ""),
    )


class _NoNetworkSelectionRewriteLLMClient:
    """CI fallback: deterministic and never contacts a provider."""

    def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float = 0.2,
        response_format: Mapping[str, Any] | None = None,
        stream: bool | None = None,
    ) -> LLMResponse:
        del temperature, response_format, stream
        prompt = messages[-1].content if messages else "{}"
        try:
            payload = json.loads(prompt)
        except json.JSONDecodeError:
            payload = {}
        selected = str(payload.get("selected_source_span") or "").strip()
        note = str(payload.get("user_note") or "").strip()
        replacement = selected
        if note:
            replacement = f"{selected} % revised: {note[:80]}"
        return LLMResponse(
            content=json.dumps(
                {
                    "replacement_text": replacement,
                    "rationale": "No-network deterministic selection rewrite.",
                }
            ),
            model="no-network-selection-rewrite-fixture",
            provider="ci_no_network",
        )


def _default_llm_client() -> LLMClient:
    if _common.ci_should_disable_network_llm():
        return _NoNetworkSelectionRewriteLLMClient()
    return OpenAICompatibleLLMClient()


def _response_text(response: Any) -> str:
    raw_content = getattr(response, "content", response)
    return raw_content if isinstance(raw_content, str) else str(raw_content)
