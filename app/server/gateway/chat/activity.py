"""Public subjects for activity receipts, derived only from user-facing operations."""

import re


def public_activity_subject(operation: str, value: object) -> str:
    if operation not in {"search", "read", "summarize", "save_file"} or not isinstance(value, str):
        return ""
    value = value[:1000]
    # Omit technical payloads rather than partially masking them into prose.
    if re.search(
        r"(?:https?|file)://|(?:^|\s)(?:/|~/|[A-Za-z]:[\\/])|"
        r"(?:api[_ -]?key|token|authorization|password|secret)\s*[:=]|"
        r"\b(?:pathlab_\w+|LOAD_CAPABILITY|LOAD_SKILL|CONNECTOR_TOOL|"
        r"load_capability|load_skill|connectors?[_/]\w+|system_prompt|traceback)\b|"
        r"[{}<>`\x00-\x08\x0b\x0c\x0e-\x1f\u202a-\u202e\u2066-\u2069]",
        value, re.I,
    ):
        return ""
    value = re.sub(r"\s+", " ", value).strip()
    return value[:157] + "…" if len(value) > 160 else value
