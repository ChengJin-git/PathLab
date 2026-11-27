import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.autoresearch.engine import requirements
from backend.services import text_editor
from backend.database.repositories import ChatRepository
from gateway.routes import autoresearch as routes


@pytest.fixture
def editor_api(monkeypatch):
    user = SimpleNamespace(id="alice", role="pathologist", is_admin=lambda: False)
    edit = AsyncMock(return_value="Clear request")
    monkeypatch.setattr(routes, "polish_requirements", edit)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.current_active_user] = lambda: user

    @asynccontextmanager
    async def db():
        yield SimpleNamespace(scalar=AsyncMock(return_value=None))

    monkeypatch.setattr(routes, "safe_session", db)
    return SimpleNamespace(client=TestClient(app), user=user, edit=edit)


def test_polish_returns_only_text_and_never_creates_a_session(editor_api, monkeypatch):
    create = AsyncMock()
    monkeypatch.setattr(routes.store, "update", create)
    response = editor_api.client.post("/research/polish-goal", json={"question": " CRC-MSI ", "language": "zh-CN"})
    assert response.status_code == 200
    assert response.json() == {"question": "Clear request"}
    editor_api.edit.assert_awaited_once_with("CRC-MSI", "zh-CN", "")
    create.assert_not_awaited()


def test_guest_cannot_polish(editor_api):
    editor_api.user.role = "guest"
    response = editor_api.client.post("/research/polish-goal", json={"question": "CRC-MSI", "language": "zh-CN"})
    assert response.status_code == 403
    editor_api.edit.assert_not_awaited()


@pytest.mark.parametrize("owner,expected", [("alice", 200), ("bob", 403)])
def test_polish_context_rechecks_conversation_ownership(editor_api, monkeypatch, owner, expected):
    conversation = SimpleNamespace(user_id=owner, workspace_id=None, messages=[
        SimpleNamespace(id=1, role="user", content="Only design; no training", variant_group_id=None, is_active_variant=True)
    ])
    monkeypatch.setattr(ChatRepository, "get_conversation", AsyncMock(return_value=conversation))
    response = editor_api.client.post("/research/polish-goal", json={
        "question": "CRC-MSI", "language": "en-US", "source_conversation_id": "chat"
    })
    assert response.status_code == expected
    if expected == 200:
        assert "Only design; no training" in editor_api.edit.call_args.args[2]
    else:
        editor_api.edit.assert_not_awaited()


@pytest.mark.parametrize("payload", [
    {"question": "   ", "language": "zh-CN"},
    {"question": "x" * 12001, "language": "zh-CN"},
    {"question": "CRC-MSI", "language": "other"},
    {"question": "CRC-MSI", "language": "zh-CN", "model": "user-selected"},
    {"question": "CRC-MSI", "language": "zh-CN", "context": "unverified conversation"},
])
def test_polish_rejects_invalid_or_client_supplied_internal_fields(editor_api, payload):
    assert editor_api.client.post("/research/polish-goal", json=payload).status_code == 422
    editor_api.edit.assert_not_awaited()


def test_provider_failure_does_not_expose_model_or_endpoint(editor_api):
    editor_api.edit.side_effect = text_editor.EditingError("secret-provider/model api-key")
    response = editor_api.client.post("/research/polish-goal", json={"question": "CRC-MSI", "language": "zh-CN"})
    assert response.status_code == 502
    assert response.json()["detail"] == "Research request editing is temporarily unavailable."


@pytest.mark.parametrize("content,finish_reason,valid", [
    ("  保留原意的需求。  ", "stop", True),
    ("", "stop", False),
    ("partial", "length", False),
    (None, "stop", False),
    ("x" * 12001, "stop", False),
])
async def test_editor_uses_separate_lightweight_model_and_rejects_incomplete_results(monkeypatch, content, finish_reason, valid):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(text_editor.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(text_editor.Config, "get_global_settings", lambda: {
        "openrouter_base_url": "https://editor.test/v1", "openrouter_api_key": "secret", "openrouter_model": "expensive-research-model"
    })
    monkeypatch.setenv("PATHLAB_RESEARCH_POLISH_MODEL", "lightweight-editor")
    if valid:
        assert await requirements.polish_requirements("只设计，不训练", "zh-CN") == content.strip()
    else:
        with pytest.raises(text_editor.EditingError):
            await requirements.polish_requirements("只设计，不训练", "zh-CN")
    assert requests[0]["model"] == "lightweight-editor"
    assert "Simplified Chinese" in requests[0]["messages"][0]["content"]
    assert json.loads(requests[0]["messages"][1]["content"])["request"] == "只设计，不训练"
