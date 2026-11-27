import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services.workspaces import WorkspaceScope
from gateway.chat.capabilities import load_capability_context
from gateway.routes import chat


@pytest.mark.parametrize("always_empty", [False, True])
async def test_empty_upstream_completion_retries_once_without_replaying_actions(
    monkeypatch, always_empty
):
    from gateway.routes.chat_llm_client import LLMStreamError

    monkeypatch.setattr(
        chat.Config,
        "get_global_settings",
        lambda: {"local_vllm_enabled": False, "exa_api_key": ""},
    )
    calls = 0

    async def generate(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1 or always_empty:
            raise LLMStreamError("empty_completion")
        yield "data: " + json.dumps({"content": "Recovered response"}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "_stream_from_openai_compatible", generate)
    output = "".join(
        [
            line
            async for line in chat.stream_ai_response(
                [{"role": "user", "content": "Explain"}],
                api_key="fixture",
                model="fixture",
            )
        ]
    )
    assert calls == 2
    assert ("Recovered response" in output) is not always_empty
    assert "[DONE]" in output


async def test_complete_search_json_without_closing_tag_executes_once(monkeypatch):
    monkeypatch.setattr(
        chat.Config,
        "get_global_settings",
        lambda: {"local_vllm_enabled": False, "exa_api_key": "fixture"},
    )
    monkeypatch.setattr(
        chat, "find_cached_articles_by_title", lambda *args, **kwargs: []
    )
    search = AsyncMock(
        return_value={
            "query": "Hong Kong weather",
            "results": [
                {
                    "title": "Forecast",
                    "url": "https://www.hko.gov.hk/",
                    "snippet": "Verified forecast",
                }
            ],
        }
    )
    monkeypatch.setattr(chat, "execute_exa_search", search)
    count = 0

    async def generate(**kwargs):
        nonlocal count
        count += 1
        yield (
            "data: "
            + json.dumps(
                {
                    "content": '[WEB_SEARCH]{"query":"Hong Kong weather","num_results":5}'
                    if count == 1
                    else "Here is the verified forecast."
                }
            )
            + "\n\n"
        )
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "_stream_from_openai_compatible", generate)
    result = [
        value
        async for value in chat.stream_ai_response(
            [{"role": "user", "content": "Weather"}], api_key="test", model="fixture"
        )
    ]
    assert search.await_count == 1
    assert any("verified forecast." in value for value in result)
    assert not any("[WEB_SEARCH]" in value for value in result)


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setattr(
        chat.Config,
        "get_global_settings",
        lambda: {"local_vllm_enabled": False, "exa_api_key": ""},
    )


async def test_prefetched_evidence_does_not_force_a_second_generation(
    settings, monkeypatch
):
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        yield (
            "data: "
            + json.dumps(
                {"content": "Use the existing UNI baseline; no new search is needed."}
            )
            + "\n\n"
        )
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "_stream_from_openai_compatible", generate)
    output = [
        line
        async for line in chat.stream_ai_response(
            [
                {
                    "role": "user",
                    "content": "[TRAINING_RECOMMENDATION_CONTEXT]cached evidence[/TRAINING_RECOMMENDATION_CONTEXT]",
                },
                {
                    "role": "user",
                    "content": "Just explain the existing recommendation, don't search.",
                },
            ],
            api_key="fixture",
            base_url="https://example.test",
            model="fixture",
        )
    ]
    assert len(calls) == 1
    assert not any("__CLEAR_CONTENT__" in line for line in output)


async def test_unprepared_workflow_loads_only_when_model_requests_it(
    settings, monkeypatch
):
    calls = []
    loader = AsyncMock(return_value="TASKS contract and verified task train_1")

    async def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            for text in (
                "[LOAD_CAPABILI",
                "TY]",
                '{"skill":"tasks","query":"stop train_1"}',
                "[/LOAD_CAPABILITY]",
            ):
                yield "data: " + json.dumps({"content": text}) + "\n\n"
        else:
            assert any(
                "verified task train_1" in m["content"] for m in kwargs["messages"]
            )
            yield (
                "data: "
                + json.dumps(
                    {
                        "content": '[CANCEL_TASK]{"task_id":"train_1","task_name":"Baseline"}[/CANCEL_TASK]'
                    }
                )
                + "\n\n"
            )
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "_stream_from_openai_compatible", generate)
    output = [
        line
        async for line in chat.stream_ai_response(
            [{"role": "user", "content": "让刚才那个别再跑了"}],
            api_key="fixture",
            model="fixture",
            capability_loader=loader,
        )
    ]
    loader.assert_awaited_once_with({"skill": "tasks", "query": "stop train_1"})
    assert len(calls) == 2
    assert not any("LOAD_CAP" in line for line in output)
    assert any("CANCEL_TASK" in line for line in output)


async def test_disabled_capability_cannot_widen_scope(monkeypatch):
    build = AsyncMock()
    monkeypatch.setattr("gateway.chat.capabilities.build_context", build)
    scope = WorkspaceScope(enabled_skills=("data",), execution_mode="read_only")
    result = await load_capability_context(
        SimpleNamespace(), scope, {"skill": "training", "query": "all resources"}
    )
    assert "unavailable" in result
    build.assert_not_awaited()


async def test_capability_lookup_preserves_workspace_and_read_only(monkeypatch):
    build = AsyncMock(return_value="verified scoped facts")
    monkeypatch.setattr("gateway.chat.capabilities.build_context", build)
    scope = WorkspaceScope(
        workspace_id="private", dataset_ids=("ds_1",), execution_mode="read_only"
    )
    actor = SimpleNamespace()
    result = await load_capability_context(
        actor, scope, {"skill": "training", "query": "ds_1"}
    )
    build.assert_awaited_once_with(
        actor, scope, ("data", "training"), "ds_1", view="default"
    )
    assert "verified scoped facts" in result and "[TASK_CONFIG]" in result


async def test_explicit_overlay_lookup_recovers_evidence_without_keyword_gate(
    monkeypatch,
):
    build = AsyncMock(return_value="verified scoped facts")
    monkeypatch.setattr("gateway.chat.capabilities.build_context", build)
    scope = WorkspaceScope(workspace_id="private", dataset_ids=("ds_1",))
    actor = SimpleNamespace()
    await load_capability_context(
        actor, scope, {"skill": "annotation", "query": "ds_1"}
    )
    build.assert_awaited_once_with(
        actor, scope, ("data", "annotation"), "ds_1", view="results"
    )


async def test_no_connector_policy_does_not_invent_a_workflow(settings, monkeypatch):
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        text = (
            '[WEB_SEARCH]{"query":"papers"}[/WEB_SEARCH]'
            if len(calls) == 1
            else "Search is disabled."
        )
        yield "data: " + json.dumps({"content": text}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "_stream_from_openai_compatible", generate)
    _ = [
        line
        async for line in chat.stream_ai_response(
            [{"role": "user", "content": "Find papers"}],
            api_key="fixture",
            model="fixture",
            allowed_connectors=(),
        )
    ]
    assert len(calls) == 2
    assert "disabled" in calls[1]["messages"][-1]["content"]
    assert "ANALYSIS_CONFIG" not in calls[1]["messages"][-1]["content"]


async def test_repeated_context_requests_are_bounded(settings, monkeypatch):
    calls = []
    loader = AsyncMock(return_value="No matching task")

    async def generate(**kwargs):
        calls.append(kwargs)
        yield (
            "data: "
            + json.dumps(
                {
                    "content": '[LOAD_CAPABILITY]{"skill":"tasks","query":"unknown"}[/LOAD_CAPABILITY]'
                }
            )
            + "\n\n"
        )
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "_stream_from_openai_compatible", generate)
    output = [
        line
        async for line in chat.stream_ai_response(
            [{"role": "user", "content": "Stop the other one"}],
            api_key="fixture",
            model="fixture",
            capability_loader=loader,
        )
    ]
    assert loader.await_count == 2
    assert len(calls) == 3
    assert "Which dataset or task" in "".join(output)


async def test_previous_card_does_not_block_model_requested_search(
    settings, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        chat, "find_cached_articles_by_title", lambda *args, **kwargs: []
    )

    async def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            text = '[WEB_SEARCH]{"query":"gastric pathology papers"}[/WEB_SEARCH]'
        else:
            # Search reached connector configuration; it was not rejected by old card intent.
            assert "not been configured" in kwargs["messages"][-1]["content"]
            text = "Search is currently unavailable."
        yield "data: " + json.dumps({"content": text}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "_stream_from_openai_compatible", generate)
    _ = [
        line
        async for line in chat.stream_ai_response(
            [
                {
                    "role": "assistant",
                    "content": '[METRIC_CONFIG]{"task_id":"t1"}[/METRIC_CONFIG]',
                },
                {"role": "user", "content": "Instead, find related papers."},
            ],
            api_key="fixture",
            model="fixture",
            allowed_connectors=("web_search",),
        )
    ]
    assert len(calls) == 2


def stream_events(output):
    return [json.loads(line[6:]) for line in output if line != 'data: [DONE]\n\n']


@pytest.mark.parametrize('tool', ['LOAD_SKILL', 'LOAD_CAPABILITY', 'WEB_SEARCH', 'READ_ARTICLE'])
async def test_tool_steps_keep_prose_and_hide_split_envelopes(settings, monkeypatch, tool):
    initial = '我先检查已有结果。'
    final = '结果已核查，接下来分析不确定性。'
    bodies = {
        'LOAD_SKILL': '{"id":"nature-statistics"}',
        'LOAD_CAPABILITY': '{"skill":"tasks","query":"BCFC"}',
        'WEB_SEARCH': '{"query":"BCFC"}',
        'READ_ARTICLE': '{"url":"https://example.test/paper","title":"BCFC"}',
    }
    monkeypatch.setattr(chat, 'find_cached_articles_by_title', lambda *a, **kw: [])
    monkeypatch.setattr(chat, 'get_cached_markdown', lambda *a: None)
    monkeypatch.setattr(chat, 'process_pdf_url', AsyncMock(return_value={'success': False, 'error': 'network_unreachable'}))
    calls = 0

    async def generate(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield 'data: {"type":"thinking_pulse","elapsed_ms":1}\n\n'
        text = initial + f'[{tool}]' + bodies[tool] + f'[/{tool}]' if calls == 1 else final
        for char in text:
            yield 'data: ' + json.dumps({'content': char}) + '\n\n'
        yield 'data: [DONE]\n\n'

    monkeypatch.setattr(chat, '_stream_from_openai_compatible', generate)
    output = [line async for line in chat.stream_ai_response(
        [{'role': 'user', 'content': '体液细胞那个你看看吧'}], api_key='fixture', model='fixture',
        capability_loader=AsyncMock(return_value='Verified BCFC task'),
        connector_handler=AsyncMock(return_value='Statistical guidance'),
    )]
    events = stream_events(output)
    assert events[0]['type'] == 'thinking_pulse'
    visible = ''.join(event.get('content', '') for event in events)
    assert visible.startswith(initial) and visible.endswith(final)
    if tool in {'WEB_SEARCH', 'READ_ARTICLE'}:
        assert 'incomplete' in visible
    assert not any(event.get('type') == 'content_replace' for event in events)
    assert calls == 2


async def test_research_handoff_is_terminal_even_with_a_trailing_skill_call(settings, monkeypatch):
    from gateway.chat.research_routing import research_decision

    decision = '[NAVIGATE]{"type":"research","execute":true,"state":{"researchGoal":"分析体液细胞任务并保存报告","handoffReason":"Custom statistical code","researchStandard":"standard","datasetIds":[],"taskKind":"analysis","reportPolicy":"summary","references":[{"kind":"task","id":"bcfc-task"}]}}[/NAVIGATE]'
    calls = 0
    connector = AsyncMock()

    async def generate(**kwargs):
        nonlocal calls
        calls += 1
        assert calls == 1, 'The accepted handoff must not request another completion'
        for text in ['准备分析已有结果。', decision, '[LOAD_SKILL]{"id":"nature-statistics"}[/LOAD_SKILL]']:
            yield 'data: ' + json.dumps({'content': text}) + '\n\n'
        yield 'data: [DONE]\n\n'

    monkeypatch.setattr(chat, '_stream_from_openai_compatible', generate)
    events = stream_events([line async for line in chat.stream_ai_response(
        [{'role': 'user', 'content': '做完给我个报告'}], api_key='fixture', model='fixture', connector_handler=connector,
    )])
    text = ''.join(event.get('content', '') for event in events)
    assert research_decision(text).references[0].id == 'bcfc-task'
    assert text.startswith('准备分析已有结果。') and 'LOAD_SKILL' not in text
    connector.assert_not_awaited()


@pytest.mark.parametrize('recover', [True, False])
async def test_empty_completion_after_skill_load_retains_progress_and_retries_with_guidance(settings, monkeypatch, recover):
    calls = 0
    connector = AsyncMock(return_value='Use submit_computation to calculate risk coverage.')

    async def generate(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            text = '我先检查已有预测，再给你报告。[LOAD_SKILL]{"id":"nature-statistics"}[/LOAD_SKILL]'
        else:
            assert 'You are still in Chat' in str(kwargs['messages'])
            if calls == 2 or not recover:
                raise chat.LLMStreamError('empty_completion')
            assert 'previous generation returned no answer' in kwargs['messages'][-1]['content']
            text = '[NAVIGATE]{"type":"research","execute":true,"state":{"researchGoal":"分析并保存报告","handoffReason":"Custom calculation","researchStandard":"standard","taskKind":"analysis","reportPolicy":"summary","datasetIds":[],"references":[]}}[/NAVIGATE]'
        yield 'data: ' + json.dumps({'content': text}) + '\n\n'
        yield 'data: [DONE]\n\n'

    monkeypatch.setattr(chat, '_stream_from_openai_compatible', generate)
    events = stream_events([line async for line in chat.stream_ai_response(
        [{'role': 'user', 'content': '做完给我个报告'}], api_key='fixture', model='fixture', connector_handler=connector,
    )])
    assert ''.join(e.get('content', '') for e in events).startswith('我先检查已有预测，再给你报告。')
    assert any(e.get('type') == 'generation_error' for e in events) is not recover
    assert calls == 3
    connector.assert_awaited_once()


async def test_citation_cleanup_does_not_replay_or_erase_a_streamed_answer(settings, monkeypatch):
    source = {'index': 1, 'source_id': 'known', 'url': 'https://example.test/paper', 'title': 'Paper', 'last_read_at': 0}
    async def generate(**kwargs):
        for part in ['完整回答 [1]。', '[REF', 'ERENCE]model-authored card[/REFERENCE]']:
            yield 'data: ' + json.dumps({'content': part}) + '\n\n'
        yield 'data: [DONE]\n\n'
    monkeypatch.setattr(chat, '_stream_from_openai_compatible', generate)
    events = stream_events([line async for line in chat.stream_ai_response(
        [], api_key='fixture', model='fixture', article_sources=[source],
    )])
    assert ''.join(e.get('content', '') for e in events) == '完整回答 [1]。'
    assert not any(e.get('type') == 'content_replace' for e in events)


async def test_normalization_snapshot_preserves_earlier_tool_step_prose(settings, monkeypatch):
    calls = 0
    async def generate(**kwargs):
        nonlocal calls
        calls += 1
        text = ('先核查数据。[LOAD_CAPABILITY]{"skill":"training","query":"BCFC"}[/LOAD_CAPABILITY]'
                if calls == 1 else '建议如下。[TASK_CONFIG]{"task_type":"patch_classification"}[/TASK_CONFIG]')
        yield 'data: ' + json.dumps({'content': text}) + '\n\n'
        yield 'data: [DONE]\n\n'
    monkeypatch.setattr(chat, '_stream_from_openai_compatible', generate)
    events = stream_events([line async for line in chat.stream_ai_response(
        [], api_key='fixture', model='fixture', capability_loader=AsyncMock(return_value='verified'),
    )])
    snapshots = [e['content'] for e in events if e.get('type') == 'content_replace']
    assert snapshots == ['先核查数据。\n\n建议如下。[TASK_CONFIG]\n{\n  "task_type": "patch_classification"\n}\n[/TASK_CONFIG]']


async def test_output_continuation_survives_an_empty_retry_without_breaking_sentence(settings, monkeypatch):
    calls = 0
    async def generate(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise chat.LLMStreamError('empty_completion')
        yield 'data: ' + json.dumps({'content': 'This sentence ' if calls == 1 else 'continues.'}) + '\n\n'
        if calls == 1:
            yield 'data: {"response_truncated":true}\n\n'
        yield 'data: [DONE]\n\n'
    monkeypatch.setattr(chat, '_stream_from_openai_compatible', generate)
    events = stream_events([line async for line in chat.stream_ai_response([], api_key='fixture', model='fixture')])
    assert ''.join(e.get('content', '') for e in events) == 'This sentence continues.'
    assert not any(e.get('response_truncated') or e.get('type') == 'generation_error' for e in events)
