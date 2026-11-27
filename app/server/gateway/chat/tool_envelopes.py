"""Validate streamed tool envelopes without executing or guessing arguments."""

import json
import re

TOOLS = ("WEB_SEARCH", "READ_ARTICLE", "LOAD_CAPABILITY", 'LOAD_CONNECTOR','CONNECTOR_TOOL','LOAD_SKILL','SEARCH_FILES')


def close_complete_tool_envelope(content: str) -> str:
    """An intact JSON object with a missing closing tag has an unambiguous end."""
    for tag in TOOLS:
        start = content.rfind(f"[{tag}]")
        if start < 0 or f"[/{tag}]" in content[start:]:
            continue
        body = content[start + len(tag) + 2 :].strip()
        try:
            value, end = json.JSONDecoder().raw_decode(body)
        except ValueError:
            continue
        if isinstance(value, dict) and not body[end:].strip():
            content = content.rstrip() + f"[/{tag}]"
    return content


def has_unclosed_tool_envelope(content: str) -> bool:
    return any(
        f"[{tag}]" in content
        and f"[/{tag}]" not in content[content.rfind(f"[{tag}]") :]
        for tag in TOOLS
    )


def strip_tool_envelopes(content: str) -> str:
    for tag in TOOLS:
        content = re.sub(rf"\[{tag}\][\s\S]*?\[/{tag}\]", "", content)
        if f"[{tag}]" in content:
            content = content.split(f"[{tag}]", 1)[0]
    return content.strip()
