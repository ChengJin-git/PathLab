"""Bounded text-editing calls, shared by research briefs and manuscripts."""

import json
import os
import re
from decimal import Decimal

import httpx

from backend.common.config import Config


class EditingError(Exception):
    """Safe public error; provider responses and credentials must not escape."""


def manuscript_editing_prompt(
    prompt: str, text: str, instruction: str, language: str | None = None
) -> str:
    from backend.autoresearch.engine.builtin_skills import writing_context

    # Explicit translation intent overrides source language; normal edits follow
    # the passage rather than the UI's display language.
    if re.search(
        r"(?:translate|rewrite|render).{0,35}(?:into|in|to)\s+(?:academic\s+)?English|(?:译|譯|改|写|寫).{0,6}(?:英文|英语|英語)",
        instruction,
        re.IGNORECASE,
    ):
        target = "en-US"
    elif re.search(
        r"(?:into|to)\s+(?:simplified |traditional )?Chinese|(?:译|譯|改).{0,6}(?:中文|汉语|漢語)",
        instruction,
        re.IGNORECASE,
    ):
        target = (
            "zh-HK"
            if re.search(r"traditional|繁", instruction, re.IGNORECASE)
            else "zh-CN"
        )
    elif re.search(r"[\u3400-\u9fff]", text):
        target = language if language in {"zh-CN", "zh-HK"} else "zh-CN"
    else:
        target = "en-US"
    return (
        writing_context("polish", target)["text"]
        + "\n\nCURRENT EDITING TASK:\n"
        + prompt
    )


def validate_manuscript_edit(original: str, edited: str) -> None:
    """Style editing must retain numbers, citations and protected document syntax."""
    from .citations import citation_numbers

    def numbers(text):
        return {
            Decimal(value)
            for value in re.findall(
                r"(?<!\d)[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?", text
            )
        }

    protected = r"(?m)^#{1,6} .+$|```[\s\S]*?```|`[^`\n]+`|!?\[[^\]]*\]\([^)]*\)|https?://[^\s)]+"
    if (
        numbers(original) != numbers(edited)
        or citation_numbers(original) != citation_numbers(edited)
        or any(token not in edited for token in re.findall(protected, original))
    ):
        raise EditingError(
            "Edited text changed protected manuscript facts or structure"
        )


async def edit_text(
    prompt: str, payload: dict, *, max_chars: int, max_tokens: int
) -> str:
    settings = Config.get_global_settings()
    base_url = str(settings.get("openrouter_base_url") or "").rstrip("/")
    api_key = str(settings.get("openrouter_api_key") or "")
    model = os.getenv("PATHLAB_RESEARCH_POLISH_MODEL", "gpt-6-luna")
    if not base_url or not api_key or not model.strip():
        raise EditingError()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": json.dumps(payload, ensure_ascii=False),
                        },
                    ],
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                    "stream": False,
                },
            )
            response.raise_for_status()
            choice = response.json()["choices"][0]
            content = choice["message"]["content"]
            if choice.get("finish_reason") != "stop" or not isinstance(content, str):
                raise EditingError()
            if not content.strip() or len(content.strip()) > max_chars:
                raise EditingError()
            return content.strip()
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise EditingError() from exc
