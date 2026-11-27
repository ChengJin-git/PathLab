"""Activity receipts describe public work without exposing tool internals."""
# ruff: noqa: F811 -- shared pytest fixtures are injected by parameter name.

import json
from unittest.mock import AsyncMock

import pytest

from gateway.chat.activity import public_activity_subject
from gateway.routes import chat
from test_chat_workbench import api as api


@pytest.mark.parametrize("operation,value,expected", [
    ("search", "spatial proteomics  cross panel", "spatial proteomics cross panel"),
    ("read", "Spatium: A Protein Language Foundation Model", "Spatium: A Protein Language Foundation Model"),
    ("save_file", "review.md", "review.md"),
    ("tool", "LOAD_CAPABILITY", ""),
    ("context", "Internal workspace instructions", ""),
    ("read", "https://example.test/paper?token=secret", ""),
    ("read", "/srv/private/report.pdf", ""),
    ("search", "open /home/owner/settings", ""),
    ("search", "api_key=secret", ""),
    ("search", "load_skill nature-review", ""),
    ("read", {"title": "Paper", "token": "secret"}, ""),
    ("read", "<script>private</script>", ""),
])
def test_only_safe_public_subjects(operation, value, expected):
    assert public_activity_subject(operation, value) == expected


async def test_public_subject_survives_stream_and_reload_without_extra_generation(api, monkeypatch):
    calls = []
    url = "https://example.test/paper"
    title = "Spatium: A Protein Language Foundation Model"

    async def stream(*args, **kwargs):
        calls.append(1)
        for event in [
            {"type": "connector_status", "status": "completed", "detail": "INTERNAL_SENTINEL"},
            {"type": "search_status", "query": "spatial proteomics cross panel"},
            {"type": "web_search_result", "result": {"query": "spatial proteomics cross panel", "results": []}},
            {"type": "pdf_status", "url": url, "title": title},
            {"type": "pdf_parse_result", "result": {"url": url, "title": title, "status": "completed"}},
            {"content": "Review complete."},
        ]:
            yield "data: " + json.dumps(event) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "stream_ai_response", stream)
    monkeypatch.setattr("gateway.chat.context.build_context", AsyncMock(return_value=""))
    response = await api.client.post("/chat", json={
        "conversation_id": "chat-a", "workspace_id": "ws",
        "messages": [{"role": "user", "content": "Review these sources"}],
    })
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines()
              if line.startswith("data: ") and line[6:] != "[DONE]"]
    activities = [event["activity"] for event in events if event.get("type") == "activity"]
    assert any(item["subject"] == title and item["status"] == "completed" for item in activities)
    assert all(item["subject"] == "" for item in activities if item["operation"] in {"context", "tool"})
    assert all("detail" not in item for item in activities)
    assert "INTERNAL_SENTINEL" not in json.dumps(activities)
    reloaded = await api.client.get("/conversations/chat-a")
    saved = next(message for message in reloaded.json()["messages"] if message["role"] == "assistant")
    assert any(item["subject"] == title for item in saved["metadata"]["artifacts"]["activity"])
    assert calls == [1]
