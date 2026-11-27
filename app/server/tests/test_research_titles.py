import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.autoresearch.engine import titles
from backend.common.model_config import ModelConfig


@pytest.mark.parametrize('output,expected', [
    ('胃癌活检跨中心泛化', '胃癌活检跨中心泛化'),
    ('请研究胃癌' * 30, '自主探索'),
    ('标题\n说明', '自主探索'),
    ('', '自主探索'),
])
async def test_titles_summarize_full_goal_and_reject_unbounded_output(monkeypatch, output, expected):
    request_payloads = []
    def handler(request):
        request_payloads.append(json.loads(request.content))
        return httpx.Response(200, text='data: ' + json.dumps({'choices': [{'delta': {'content': output}}]}) + '\n\ndata: [DONE]\n')
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(titles.httpx, 'AsyncClient', lambda **kwargs: client)
    goal = '背景说明' * 100 + '真正的目标是胃癌活检跨中心泛化'
    assert await titles.generate_title(goal, 'zh-CN', ModelConfig('vllm', 'local', 'http://model', 'key')) == expected
    assert request_payloads[0]['messages'][1]['content'] == goal
    assert request_payloads[0]['chat_template_kwargs'] == {'enable_thinking': False}


@pytest.mark.parametrize('current,expected', [('自主探索', '胃癌泛化'), ('用户自定义标题', '用户自定义标题')])
async def test_title_persistence_syncs_placeholder_but_preserves_user_rename(monkeypatch, current, expected):
    session = SimpleNamespace(chat_conversation_id='chat', recovery_metadata={
        'title': '自主探索', 'title_pending': True, 'chat_title_placeholder': '自主探索', 'datasets': ['cohort'],
    })
    chat = SimpleNamespace(title=current)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[chat, session]), commit=AsyncMock())
    @asynccontextmanager
    async def database():
        yield db
    monkeypatch.setattr(titles, 'safe_session', database)
    await titles.assign_title('session', '胃癌泛化')
    assert session.recovery_metadata == {'title': '胃癌泛化', 'title_pending': False, 'datasets': ['cohort']}
    assert chat.title == expected
    db.commit.assert_awaited_once()
