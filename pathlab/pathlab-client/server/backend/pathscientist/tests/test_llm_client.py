from __future__ import annotations

from backend.pathscientist.llm_client import sanitize_messages_for_chat_completion


def test_sanitize_messages_for_chat_completion_flattens_content_parts_and_nulls():
    messages = [
        {
            "role": "system",
            "content": [{"type": "text", "text": "System prompt"}],
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": [
                {"type": "text", "text": "line 1"},
                {"type": "text", "text": "line 2"},
            ],
        },
    ]

    sanitized = sanitize_messages_for_chat_completion(messages)

    assert sanitized[0]["content"] == "System prompt"
    assert sanitized[1]["content"] == ""
    assert sanitized[1]["tool_calls"] == messages[1]["tool_calls"]
    assert sanitized[2]["content"] == "line 1\nline 2"
    assert messages[0]["content"] == [{"type": "text", "text": "System prompt"}]
