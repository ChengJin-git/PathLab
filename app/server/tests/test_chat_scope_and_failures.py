"""Capability escalation and recoverable failures must survive streaming/persistence."""
# ruff: noqa: F811 -- shared pytest fixtures are injected by parameter name.

import errno
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from backend.database.models import ChatMessage
from backend.services.articles import reader
from gateway.chat.failures import operation_failure, failure_text
from gateway.chat.research_routing import ResearchGoal, research_decision
from gateway.routes import chat, autoresearch
from test_chat_workbench import api as api


def events(response):
    lines = response.splitlines() if isinstance(response, str) else response
    return [
        json.loads(line[6:])
        for line in lines
        if line.startswith("data: ") and line.strip() != "data: [DONE]"
    ]


def content(items):
    result = ""
    for item in items:
        result = (
            item["content"]
            if item.get("type") == "content_replace"
            else result + item.get("content", "")
        )
    return result


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(
        chat.Config,
        "get_global_settings",
        lambda: {
            "local_vllm_enabled": False,
            "openrouter_api_key": "fixture",
            "exa_api_key": "fixture",
        },
    )
    monkeypatch.setattr(chat, "get_cached_markdown", lambda *a: None)
    monkeypatch.setattr(chat, "find_cached_articles_by_title", lambda *a, **kw: [])


def generation(monkeypatch, first, then="已有材料会保留。"):
    calls = []

    async def run(**kwargs):
        calls.append(kwargs)
        if len(calls) > 1 and isinstance(then, Exception):
            raise then
        yield (
            "data: "
            + json.dumps({"content": first if len(calls) == 1 else then})
            + "\n\n"
        )
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "_stream_from_openai_compatible", run)
    return calls


@pytest.mark.parametrize(
    "error,code,expected",
    [
        (httpx.ReadTimeout("SECRET upstream token"), "request_timeout", "响应超时"),
        (
            RuntimeError("/private/credentials SECRET"),
            "unexpected_error",
            "未能完成操作",
        ),
    ],
)
async def test_search_failure_is_visible_without_a_successful_followup_model(
    model, monkeypatch, error, code, expected
):
    generation(
        monkeypatch,
        '[WEB_SEARCH]{"query":"latest result"}[/WEB_SEARCH]',
        chat.LLMStreamError("empty_completion"),
    )
    search = AsyncMock(side_effect=error)
    monkeypatch.setattr(chat, "execute_exa_search", search)
    output = [
        line
        async for line in chat.stream_ai_response(
            [{"role": "user", "content": "查最新结果"}],
            api_key="fixture",
            model="fixture",
            detected_lang="zh_CN",
        )
    ]
    text = content(events(output))
    assert expected in text and "SECRET" not in text and "/private" not in text
    assert "已有" in text or "稍后" in text or "重试" in text
    search.assert_awaited_once()


@pytest.mark.parametrize(
    "language,fragment",
    [("zh_CN", "原始 PDF"), ("zh_HK", "原始 PDF"), ("en", "original PDF")],
)
async def test_missing_pdf_has_action_specific_localized_recovery(
    model, monkeypatch, language, fragment
):
    generation(
        monkeypatch,
        '[READ_ARTICLE]{"url":"https://example.test/paper","title":"Paper","action":"download"}[/READ_ARTICLE]',
    )
    monkeypatch.setattr(
        chat,
        "process_pdf_url",
        AsyncMock(
            return_value={
                "success": False,
                "error": "download_failed",
                "error_code": "no_pdf",
                "error_detail": "SECRET raw error",
            }
        ),
    )
    output = events(
        [
            line
            async for line in chat.stream_ai_response(
                [], api_key="fixture", model="fixture", detected_lang=language
            )
        ]
    )
    result = next(
        item["result"] for item in output if item.get("type") == "pdf_parse_result"
    )
    assert result["action"] == "download" and fragment in result["message"]
    assert result["recovery_hint"] and "SECRET" not in str(output)
    assert result["message"] in content(output)


async def test_failed_identical_search_cannot_loop(model, monkeypatch):
    tool = '[WEB_SEARCH]{"query":"same"}[/WEB_SEARCH]'
    generation(monkeypatch, tool, tool)
    search = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
    monkeypatch.setattr(chat, "execute_exa_search", search)
    output = events(
        [
            line
            async for line in chat.stream_ai_response(
                [], api_key="fixture", model="fixture"
            )
        ]
    )
    search.assert_awaited_once()
    assert content(output).count("Search incomplete") == 1


async def test_partial_download_survives_parse_and_model_failure_and_reload(
    api, model, monkeypatch
):
    import asyncio

    cache = api.root / "pdf-cache"
    cache.mkdir()
    pdf = cache / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 actual fixture")
    monkeypatch.setattr(reader, "get_pdf_cache_dir", lambda: cache)
    monkeypatch.setattr(
        "gateway.chat.context.build_context", AsyncMock(return_value="")
    )
    from backend.database.models import Workspace

    async with api.db() as db:
        ws = await db.scalar(select(Workspace))
        ws.enabled_connectors = ["articles"]
        await db.commit()
    generation(
        monkeypatch,
        '[READ_ARTICLE]{"url":"https://example.test/paper","title":"Paper","action":"read_download"}[/READ_ARTICLE]',
        chat.LLMStreamError("empty_completion"),
    )
    monkeypatch.setattr(
        chat,
        "process_pdf_url",
        AsyncMock(
            return_value={
                "success": False,
                "error": "parse_failed",
                "error_code": "parse_timeout",
                "download_path": str(pdf),
            }
        ),
    )
    response = await asyncio.wait_for(
        api.client.post(
            "/chat",
            headers={"X-Language": "zh-CN"},
            json={
                "conversation_id": "chat-a",
                "workspace_id": "ws",
                "messages": [{"role": "user", "content": "读原文并下载PDF"}],
            },
        ),
        10,
    )
    output = events(response.text)
    produced = next(
        item["files"] for item in output if item.get("type") == "files_created"
    )
    assert "FILE_DELIVERY" in content(output) and "解析超时" in content(output)
    download = await api.client.get(
        f"/workbench/conversations/chat-a/files/{produced[0]['id']}/download"
    )
    assert download.content == pdf.read_bytes()
    reloaded = (await api.client.get("/conversations/chat-a")).json()["messages"][-1]
    failure = reloaded["metadata"]["artifacts"]["search"]["pdfParseResults"][0]
    assert failure["error_code"] == "parse_timeout" and failure["recovery_hint"]


async def test_context_exception_is_not_reported_as_user_cancellation(api, monkeypatch):
    monkeypatch.setattr(
        "gateway.chat.context.build_context",
        AsyncMock(side_effect=RuntimeError("SECRET DB traceback")),
    )
    response = await api.client.post(
        "/chat",
        headers={"X-Language": "zh-CN"},
        json={
            "conversation_id": "chat-a",
            "workspace_id": "ws",
            "messages": [{"role": "user", "content": "查看任务"}],
        },
    )
    assert response.status_code == 200 and "data: [DONE]" in response.text
    text = content(events(response.text))
    assert "资源信息读取未完成" in text and "SECRET" not in text
    async with api.db() as db:
        saved = await db.scalar(
            select(ChatMessage).where(ChatMessage.role == "assistant")
        )
        assert "资源信息读取未完成" in saved.content and "取消" not in saved.content
        assert next(item['message_id'] for item in events(response.text) if 'message_id' in item) == saved.id
    assert response.text.index('"message_id"') < response.text.index('data: [DONE]')


async def test_article_cache_with_control_glyphs_survives_chat_persistence(api, monkeypatch, tmp_path):
    import time
    from sqlalchemy import event
    from backend.database.models import Workspace
    from backend.services.articles.identity import get_url_hash

    async with api.db() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.workspace_id == 'ws'))
        workspace.enabled_connectors = ['articles']
        await db.commit()
    url = 'https://example.test/paper.pdf'
    identity = get_url_hash(url)
    (tmp_path / f'{identity}.json').write_text(json.dumps({
        'schema_version': reader.CACHE_SCHEMA, 'cached_at': time.time(), 'parse_method': 'pymupdf',
        'page_count': 28, 'title': 'Paper', 'content_scope': 'pdf',
    }))
    (tmp_path / f'{identity}.md').write_text('--- Page 6 ---\nFormula x\x00y\x13z. AUC 0.934.')
    monkeypatch.setattr(reader, '_pdf_cache_dir', tmp_path)
    monkeypatch.setattr(reader, 'validate_external_url', lambda url: url)
    monkeypatch.setattr(chat.Config, 'get_global_settings', lambda: {'local_vllm_enabled': False, 'openrouter_api_key': 'fixture'})
    monkeypatch.setattr('gateway.chat.context.build_context', AsyncMock(return_value=''))

    # SQLite accepts NUL; enforce the production PostgreSQL restriction here.
    def reject_nul(conn, cursor, statement, params, context, many):
        assert '\\u0000' not in json.dumps(params), 'PostgreSQL rejects NUL text'
    event.listen(api.db.kw['bind'].sync_engine, 'before_cursor_execute', reject_nul)
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            text = '[READ_ARTICLE]' + json.dumps({'url': url, 'title': 'Paper'}) + '[/READ_ARTICLE]'
        else:
            assert 'Formula x\ufffdy\ufffdz' in str(kwargs['messages'])
            assert '\\x00' not in str(kwargs['messages'])
            text = 'The paper reports AUC 0.934 [1, p.6].'
        yield 'data: ' + json.dumps({'content': text}) + '\n\n'
        yield 'data: [DONE]\n\n'
    monkeypatch.setattr(chat, '_stream_from_openai_compatible', generate)
    response = await api.client.post('/chat', json={
        'conversation_id': 'chat-a', 'workspace_id': 'ws',
        'messages': [{'role': 'user', 'content': 'Read the paper methods.'}],
    })
    output = events(response.text)
    assert len(calls) == 2 and '0.934' in content(output)
    assert not any(item.get('activity', {}).get('status') == 'failed' for item in output)
    async with api.db() as db:
        rows = (await db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == 'chat-a'))).all()
        assistant = [row for row in rows if row.role == 'assistant']
        assert len(assistant) == 1
        assert any('Formula x\ufffdy\ufffdz' in row.content for row in rows)
        assert next(item['message_id'] for item in output if 'message_id' in item) == assistant[0].id


async def test_midstream_exception_publishes_saved_message_id_before_done(api, monkeypatch):
    monkeypatch.setattr('gateway.chat.context.build_context', AsyncMock(return_value=''))
    async def broken_stream(*args, **kwargs):
        yield 'data: ' + json.dumps({'content': 'Reading completed.'}) + '\n\n'
        raise RuntimeError('SECRET DB details')
    monkeypatch.setattr(chat, 'stream_ai_response', broken_stream)
    response = await api.client.post('/chat', headers={'X-Language': 'zh-CN'}, json={
        'conversation_id': 'chat-a', 'workspace_id': 'ws',
        'messages': [{'role': 'user', 'content': '阅读论文'}],
    })
    output = events(response.text)
    async with api.db() as db:
        rows = (await db.scalars(select(ChatMessage).where(ChatMessage.role == 'assistant'))).all()
    assert len(rows) == 1 and 'Reading completed.' in rows[0].content
    assert '工具操作未完成' in rows[0].content and 'SECRET' not in response.text
    assert next(item['message_id'] for item in output if 'message_id' in item) == rows[0].id
    assert response.text.index('"message_id"') < response.text.index('data: [DONE]')
    assert response.text.count('data: [DONE]') == 1


def test_new_handoff_contract_requires_explicit_scope_and_rejects_extra_fields():
    state = {
        "researchGoal": "Investigate robustness",
        "handoffReason": "Custom encoder objective",
        "datasetIds": [],
        "references": [],
        "taskKind": "experiment",
        "reportPolicy": "manuscript",
        "researchStandard": "scientific",
    }
    assert ResearchGoal.model_validate(state).researchStandard == "scientific"
    for field in state:
        with pytest.raises(ValueError):
            ResearchGoal.model_validate({k: v for k, v in state.items() if k != field})
    with pytest.raises(ValueError):
        ResearchGoal.model_validate({**state, "auto_submit": True})


@pytest.mark.parametrize(
    "incomplete",
    [
        '[NAVIGATE]{"type":"research","execute":true,"state":{"researchGoal":"incomplete"}}[/NAVIGATE]',
        '[NAVIGATE]{"type":"research","execute":true,"state":',
    ],
)
async def test_invalid_handoff_gets_one_repair_then_validates_scope(
    model, monkeypatch, incomplete
):
    valid = (
        "[NAVIGATE]"
        + json.dumps(
            {
                "type": "research",
                "execute": True,
                "state": {
                    "researchGoal": "Custom regression",
                    "handoffReason": "Regression needs custom training code",
                    "datasetIds": [],
                    "references": [],
                    "taskKind": "experiment",
                    "reportPolicy": "summary",
                    "researchStandard": "standard",
                },
            }
        )
        + "[/NAVIGATE]"
    )
    calls = generation(monkeypatch, incomplete, valid)
    output = events(
        [
            line
            async for line in chat.stream_ai_response(
                [], api_key="fixture", model="fixture"
            )
        ]
    )
    assert len(calls) == 2 and "has NOT started" in str(calls[1]["messages"])
    assert research_decision(content(output)).taskKind == "experiment"


async def test_handoff_preserves_scientific_standard_and_connector_scope(
    api, monkeypatch
):
    goal = ResearchGoal(
        researchGoal="Original robust representation research",
        handoffReason="Custom multi-experiment objectives",
        datasetIds=[],
        references=[],
        taskKind="experiment",
        reportPolicy="manuscript",
        researchStandard="scientific",
    )

    async def stream(*args, **kwargs):
        yield (
            "data: "
            + json.dumps(
                {
                    "content": "[NAVIGATE]"
                    + json.dumps(
                        {
                            "type": "research",
                            "execute": True,
                            "state": goal.model_dump(),
                        }
                    )
                    + "[/NAVIGATE]"
                }
            )
            + "\n\n"
        )
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "stream_ai_response", stream)
    monkeypatch.setattr(
        "gateway.chat.context.build_context", AsyncMock(return_value="")
    )
    create = AsyncMock(return_value={"session_id": "new", "status": "queued"})
    monkeypatch.setattr(autoresearch, "create_session", create)
    response = await api.client.post(
        "/chat",
        json={
            "conversation_id": "chat-a",
            "workspace_id": "ws",
            "messages": [{"role": "user", "content": "请开始这个原创方法研究"}],
        },
    )
    assert "research_started" in response.text
    body = create.call_args.args[0]
    assert body.research_standard == "scientific" and body.enabled_connectors == []
    async with api.db() as db:
        saved = await db.scalar(
            select(ChatMessage).where(ChatMessage.role == "assistant")
        )
        assert (
            saved.extra_metadata["research_decision"]["handoffReason"]
            == "Custom multi-experiment objectives"
        )


def test_storage_failure_does_not_expose_filesystem_details():
    from gateway.chat.failures import exception_code

    error = OSError(errno.ENOSPC, "/private/SECRET")
    text = failure_text(operation_failure("save", "zh_CN", exception_code(error)))
    assert "存储空间不足" in text and "/private" not in text


@pytest.mark.parametrize('tag, arguments, expected', [
    ('LOAD_CONNECTOR', {'id':'fixture'}, '工具操作未完成'),
    ('LOAD_CAPABILITY', {'skill':'tasks','query':'fixture'}, '资源信息读取未完成'),
])
async def test_unexpected_tool_failure_keeps_a_localized_actionable_response(model, monkeypatch, tag, arguments, expected):
    generation(monkeypatch, f'[{tag}]'+json.dumps(arguments)+f'[/{tag}]')
    failed=AsyncMock(side_effect=RuntimeError('SECRET /private/service'))
    output=events([line async for line in chat.stream_ai_response([],api_key='fixture',model='fixture',detected_lang='zh_CN',
                  connector_handler=failed,capability_loader=failed)])
    text=content(output)
    assert expected in text and '重试' in text and 'SECRET' not in text and '/private' not in text
    failed.assert_awaited_once()


async def test_completed_brief_does_not_keep_blocking_future_delegated_work(
    api, monkeypatch
):
    async with api.db() as db:
        db.add(
            ChatMessage(
                conversation_id="chat-a",
                role="user",
                content="Prepare a brief",
                extra_metadata={
                    "research_brief": True,
                    "research_options": {
                        "effort": "low",
                        "advanced": {},
                        "allow_downloads": False,
                        "selected_skill": "pathlab-research",
                    },
                },
            )
        )
        db.add(
            ChatMessage(
                conversation_id="chat-a",
                role="assistant",
                content="Earlier brief",
                extra_metadata={"research_brief": True},
            )
        )
        db.add(
            ChatMessage(
                conversation_id="chat-a",
                role="assistant",
                content="Later completed work",
                extra_metadata={"research_brief": False},
            )
        )
        await db.commit()
    prompts = []

    async def stream(messages, *args, **kwargs):
        prompts.append(messages[0]["content"])
        yield 'data: {"content":"Proceeding with the new goal."}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "stream_ai_response", stream)
    monkeypatch.setattr(
        "gateway.chat.context.build_context", AsyncMock(return_value="")
    )
    await api.client.post(
        "/chat",
        json={
            "conversation_id": "chat-a",
            "workspace_id": "ws",
            "messages": [{"role": "user", "content": "Now implement a new analysis"}],
        },
    )
    assert "brief awaiting user confirmation" not in prompts[0]
    assert '"effort": "low"' in prompts[0]


@pytest.mark.parametrize(
    "task_connectors, workspace_connectors, accepted",
    [
        ([], ["web_search"], False),
        (["web_search"], [], False),
        (["web_search"], ["web_search"], True),
    ],
)
async def test_research_cannot_widen_chat_connector_restrictions(
    monkeypatch, tmp_path, task_connectors, workspace_connectors, accepted
):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from backend.autoresearch.engine import connector_scope, tools

    row = SimpleNamespace(
        session_id="isolated",
        user_id="00000000-0000-0000-0000-000000000001",
        status="running",
        workspace_path=str(tmp_path),
        recovery_metadata={"enabled_connectors": task_connectors},
    )
    monkeypatch.setattr(tools.store, "get", AsyncMock(return_value=row))

    @asynccontextmanager
    async def database():
        yield SimpleNamespace(get=AsyncMock(return_value=object()))

    monkeypatch.setattr(connector_scope, "safe_session", database)
    monkeypatch.setattr(
        "backend.autoresearch.engine.connector_scope.resolve_scope",
        AsyncMock(
            return_value=SimpleNamespace(enabled_connectors=workspace_connectors)
        ),
    )
    monkeypatch.setattr(
        tools.Config, "get_global_settings", lambda: {"exa_api_key": "fixture"}
    )
    search = AsyncMock(return_value={"results": []})
    monkeypatch.setattr("backend.services.web_search.execute_exa_search", search)
    if accepted:
        assert await tools.call("isolated", "search_web", {"query": "test"}) == {
            "results": []
        }
        search.assert_awaited_once()
    else:
        with pytest.raises(ValueError, match="disabled"):
            await tools.call("isolated", "search_web", {"query": "test"})
        search.assert_not_awaited()
