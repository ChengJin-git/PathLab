"""
Auto Research Agent — Structured Output Enforcement

Pydantic schema validation + retry with error feedback.
Works with any LLM (no guided decoding required).

Usage:
    from .structured_output import llm_generate_structured

    result = await llm_generate_structured(
        prompt="Design 3 experiments...",
        output_model=ExperimentPlan,
        max_retries=2,
    )
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# =============================================================================
# Qwen3 Thinking Mode Handling
# =============================================================================

_THINK_PATTERN = re.compile(
    r"<think>.*?</think>|Thinking Process:.*?(?=\n\n```|\n\n\{|\n\n\[|$)",
    re.DOTALL,
)


def strip_thinking(text: str) -> str:
    """Remove Qwen3's <think> blocks and 'Thinking Process:' sections."""
    # Remove <think>...</think>
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Remove "Thinking Process:" blocks (ends at first JSON-like content or double newline + content)
    text = _THINK_PATTERN.sub("", text)
    return text.strip()


# =============================================================================
# JSON Extraction
# =============================================================================

def extract_json(text: str) -> Any:
    """
    Extract JSON from LLM output. Handles:
    - Raw JSON
    - JSON inside ```json ... ``` blocks
    - JSON after thinking/reasoning text
    - Qwen3 thinking mode output
    """
    # Strip thinking content first
    cleaned = strip_thinking(text)

    # Try direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code blocks
    patterns = [
        r"```json\s*\n(.*?)```",
        r"```\s*\n(.*?)```",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, cleaned, re.DOTALL)
        if matches:
            for match in matches:
                try:
                    return json.loads(match.strip())
                except json.JSONDecodeError:
                    continue

    # Try finding first JSON object or array
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start_idx = cleaned.find(start_char)
        if start_idx == -1:
            continue
        # Find matching closing bracket
        depth = 0
        for i, c in enumerate(cleaned[start_idx:], start_idx):
            if c == start_char:
                depth += 1
            elif c == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start_idx:i + 1])
                    except json.JSONDecodeError:
                        break

    # Last resort: try json_repair if available
    try:
        from json_repair import repair_json
        return json.loads(repair_json(cleaned))
    except Exception:
        pass

    return None


# =============================================================================
# Structured Output with Validation + Retry
# =============================================================================

async def llm_generate_structured(
    prompt: str,
    output_model: Type[T],
    system_prompt: str = "",
    max_retries: int = 2,
    temperature: float = 0.0,
    schema_hint: bool = True,
) -> tuple[T, str]:
    """
    Generate structured output from LLM with Pydantic validation and retry.

    Args:
        prompt: User prompt.
        output_model: Pydantic model class for output validation.
        system_prompt: Optional system prompt.
        max_retries: Number of retries on validation failure.
        temperature: LLM temperature.
        schema_hint: If True, append JSON schema to the prompt.

    Returns:
        (validated_model_instance, raw_llm_response)

    Raises:
        StructuredOutputError: If all retries fail.
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from .nodes import _get_llm

    llm = _get_llm(temperature=temperature)

    # Build schema hint
    schema_text = ""
    if schema_hint:
        schema = output_model.model_json_schema()
        # Simplify schema for prompt (remove definitions, titles)
        simplified = _simplify_schema(schema)
        schema_text = (
            f"\n\nYou MUST output a JSON object matching this schema:\n"
            f"```json\n{json.dumps(simplified, indent=2)}\n```\n"
            f"Output ONLY the JSON, no other text."
        )

    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=prompt + schema_text))

    last_error = ""
    raw_response = ""

    for attempt in range(max_retries + 1):
        if attempt > 0 and last_error:
            messages.append(HumanMessage(
                content=(
                    f"Your previous output failed validation:\n{last_error}\n\n"
                    f"Please fix and output ONLY valid JSON matching the schema. "
                    f"No explanation, no markdown, just the JSON."
                )
            ))

        response = await llm.ainvoke(messages)
        raw_response = response.content
        messages.append(AIMessage(content=raw_response))

        # Parse JSON
        parsed = extract_json(raw_response)
        if parsed is None:
            last_error = (
                f"Could not extract valid JSON from your response. "
                f"Your response started with: {raw_response[:100]!r}"
            )
            logger.warning(
                f"[structured_output] JSON extraction failed (attempt {attempt + 1}): "
                f"{last_error}"
            )
            continue

        # Validate with Pydantic
        try:
            result = output_model.model_validate(parsed)
            return result, raw_response

        except ValidationError as e:
            last_error = str(e)
            logger.warning(
                f"[structured_output] Validation failed (attempt {attempt + 1}): "
                f"{last_error[:200]}"
            )

    raise StructuredOutputError(
        f"Failed to generate valid structured output after {max_retries + 1} attempts. "
        f"Last error: {last_error}",
        raw_response=raw_response,
    )


class StructuredOutputError(Exception):
    """Raised when structured output generation fails after all retries."""

    def __init__(self, message: str, raw_response: str = ""):
        super().__init__(message)
        self.raw_response = raw_response


# =============================================================================
# Schema Helpers
# =============================================================================

def _simplify_schema(schema: dict) -> dict:
    """Simplify a JSON schema for use in prompts (remove noise)."""
    remove_keys = {"title", "$defs", "definitions", "description"}
    result = {}
    for k, v in schema.items():
        if k in remove_keys:
            continue
        if isinstance(v, dict):
            result[k] = _simplify_schema(v)
        elif isinstance(v, list):
            result[k] = [
                _simplify_schema(item) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


# =============================================================================
# Pre-defined Schemas for Auto Research
# =============================================================================

class ExperimentPlanItem(BaseModel):
    """Single experiment in a plan."""
    id: Any = ""  # Accept int or str
    name: str
    dataset_id: str = ""
    feature_extractor: str = ""
    aggregator: str = ""
    hyperparams: dict = {}
    rationale: str = ""
    mode: str = "api"  # "api" or "code"
    task_type: str = "classification"

    def model_post_init(self, __context: Any) -> None:
        # Coerce id to string
        self.id = str(self.id) if self.id else f"exp_{id(self)}"


class ExperimentPlan(BaseModel):
    """Validated experiment plan output. Accepts either {experiments: [...]} or bare [...]."""
    experiments: list[ExperimentPlanItem]

    @classmethod
    def model_validate(cls, obj: Any, **kwargs) -> "ExperimentPlan":
        if isinstance(obj, list):
            obj = {"experiments": obj}
        return super().model_validate(obj, **kwargs)


class IterationDecision(BaseModel):
    """Iteration router decision."""
    decision: str  # "STOP" or "CONTINUE"
    reason: str
    next_direction: str = ""


class CoordinatorOutput(BaseModel):
    """Coordinator node output."""
    locale: str = "en-US"
    task_type: str = "classification"
    organ: str = ""
    feasible: bool = True
    reason: str = ""
    refined_question: str = ""
    task_route: str = "research"  # "research" | "direct" | "simple"
    skill_name: str = ""         # matched skill, or "none" for free experiment mode
    simple_command: str = ""     # shell command for simple route


class LiteratureFinding(BaseModel):
    """Single literature finding."""
    title: str
    url: str = ""
    methods: list[dict] = []
    summary: str = ""


class LiteratureFindings(BaseModel):
    """Validated literature review output."""
    findings: list[LiteratureFinding]
