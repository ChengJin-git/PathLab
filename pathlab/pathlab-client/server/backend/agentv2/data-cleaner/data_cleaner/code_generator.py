"""LLM-based pandas cleaning code generator.

All prompts are maintained in prompts.py. This module handles:
- LLM API calls
- Code extraction from LLM responses
- Helper function injection
- Error classification and typed fix generation
"""

import json
import logging
from typing import Optional

from openai import OpenAI

from data_cleaner.analyzer import TableAnalysis
from data_cleaner.prompts import (
    HELPER_FUNCTIONS,
    CODEGEN_SYSTEM_PROMPT,
    CODEGEN_USER_TEMPLATE,
    TEMPLATE_SYSTEM_PROMPT,
    TEMPLATE_USER_TEMPLATE,
    FIX_PARSE_ERROR_PROMPT,
    FIX_TYPE_ERROR_PROMPT,
    FIX_KEY_ERROR_PROMPT,
    FIX_GENERIC_ERROR_PROMPT,
)

logger = logging.getLogger(__name__)


# ─── LLM Call Helpers ─────────────────────────────────────────

def _call_llm(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_message: str,
    temperature: float = 0.1,
) -> str:
    """Call LLM and extract code from response."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=temperature,
        max_tokens=8192,
    )
    code = response.choices[0].message.content.strip()
    code = _extract_code(code)
    return code


def _prepend_helpers(code: str) -> str:
    """Prepend helper functions to generated code."""
    return HELPER_FUNCTIONS + "\n\n# ── Generated cleaning code ──\n\n" + code


# ─── Code Generation Functions ────────────────────────────────

def generate_cleaning_code(
    sample_markdown: str,
    analysis: TableAnalysis,
    input_path: str,
    output_path: str,
    schema_text: str = "",
    api_url: str = "http://127.0.0.1:8000/v1",
    api_key: str = "sk-pathlab",
    model: str = "Qwen/Qwen3-235B-A22B-Instruct-2507",
    **kwargs,
) -> str:
    """Generate a pandas cleaning script using LLM."""
    client = OpenAI(base_url=api_url, api_key=api_key)

    analysis_json = json.dumps(analysis.raw_json, indent=2, ensure_ascii=False)

    user_message = CODEGEN_USER_TEMPLATE.format(
        input_path=input_path,
        output_path=output_path,
        schema_text=schema_text or "(schema not available)",
        analysis_json=analysis_json,
        sample_markdown=sample_markdown,
    )

    logger.info("Requesting LLM to generate cleaning code...")
    code = _call_llm(client, model, CODEGEN_SYSTEM_PROMPT, user_message)
    code = _prepend_helpers(code)
    logger.info(f"Generated cleaning script: {len(code)} chars")
    return code


def generate_template_code(
    sample_markdown: str,
    template_markdown: str,
    analysis: TableAnalysis,
    input_path: str,
    output_path: str,
    template_path: str = "",
    extra_rules: str = "",
    schema_text: str = "",
    template_schema_text: str = "",
    api_url: str = "http://127.0.0.1:8000/v1",
    api_key: str = "sk-pathlab",
    model: str = "Qwen/Qwen3-235B-A22B-Instruct-2507",
    **kwargs,
) -> str:
    """Generate a transformation script that maps input to template format."""
    client = OpenAI(base_url=api_url, api_key=api_key)

    analysis_json = json.dumps(analysis.raw_json, indent=2, ensure_ascii=False)
    rules_text = extra_rules.strip() if extra_rules else "(no additional rules)"

    user_message = TEMPLATE_USER_TEMPLATE.format(
        input_path=input_path,
        output_path=output_path,
        template_schema=template_schema_text or "(template schema not available)",
        template_markdown=template_markdown,
        schema_text=schema_text or "(schema not available)",
        sample_markdown=sample_markdown,
        analysis_json=analysis_json,
        extra_rules=rules_text,
    )

    logger.info("Requesting LLM to generate template transformation code...")
    code = _call_llm(client, model, TEMPLATE_SYSTEM_PROMPT, user_message)
    code = _prepend_helpers(code)
    logger.info(f"Generated template transformation script: {len(code)} chars")
    return code


def generate_fix(
    previous_code: str,
    error: str,
    analysis: TableAnalysis,
    available_columns: list[str] = None,
    api_url: str = "http://127.0.0.1:8000/v1",
    api_key: str = "sk-pathlab",
    model: str = "Qwen/Qwen3-235B-A22B-Instruct-2507",
    **kwargs,
) -> str:
    """Generate a fixed version of a failed script with error-type-specific prompts."""
    client = OpenAI(base_url=api_url, api_key=api_key)

    error_text = error[:3000]
    analysis_json = json.dumps(analysis.raw_json, indent=2, ensure_ascii=False)

    # Strip helper functions from previous code for cleaner prompt
    clean_code = _strip_helpers(previous_code)

    # Classify error type and pick appropriate fix prompt
    error_type = _classify_error(error_text)
    logger.info(f"Error classified as: {error_type}")

    if error_type == "parse":
        user_message = FIX_PARSE_ERROR_PROMPT.format(
            error=error_text,
            previous_code=clean_code,
        )
    elif error_type == "type":
        user_message = FIX_TYPE_ERROR_PROMPT.format(
            error=error_text,
            previous_code=clean_code,
        )
    elif error_type == "key":
        cols_str = ", ".join(available_columns) if available_columns else "(unknown)"
        user_message = FIX_KEY_ERROR_PROMPT.format(
            error=error_text,
            previous_code=clean_code,
            available_columns=cols_str,
        )
    else:
        user_message = FIX_GENERIC_ERROR_PROMPT.format(
            error=error_text,
            previous_code=clean_code,
            analysis_json=analysis_json,
        )

    logger.info(f"Requesting LLM to fix code ({error_type} error)...")
    code = _call_llm(client, model, CODEGEN_SYSTEM_PROMPT, user_message, temperature=0.2)
    code = _prepend_helpers(code)
    logger.info(f"Generated fix: {len(code)} chars")
    return code


# ─── Utility Functions ────────────────────────────────────────

def _classify_error(error_text: str) -> str:
    """Classify error into categories for targeted fix prompts."""
    error_lower = error_text.lower()

    if any(kw in error_lower for kw in [
        "parsererror", "tokenizing data", "expected.*fields",
        "unicodedecodeerror", "no columns to parse",
    ]):
        return "parse"

    if any(kw in error_lower for kw in [
        "typeerror", "valueerror", "cannot convert",
        "could not convert", "invalid literal",
        "unsupported operand", "truth value",
    ]):
        return "type"

    if any(kw in error_lower for kw in [
        "keyerror", "not in index", "column not found",
        "undefined column",
    ]):
        return "key"

    return "generic"


def _strip_helpers(code: str) -> str:
    """Remove the prepended helper functions block from code for cleaner error prompts."""
    marker = "# ── Generated cleaning code ──"
    if marker in code:
        idx = code.index(marker)
        return code[idx + len(marker):].strip()
    return code


def _extract_code(raw: str) -> str:
    """Extract Python code from LLM response, stripping markdown fences."""
    text = raw.strip()

    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline >= 0:
            text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:text.rindex("```")]

    text = text.strip()

    if not text:
        raise ValueError("LLM returned empty code")

    if not any(kw in text for kw in ["import", "pd.", "pandas", "read_csv", "read_excel", "save_result"]):
        logger.warning("Generated code may not be valid Python (missing expected keywords)")

    return text
