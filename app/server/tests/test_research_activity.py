"""Research progress is small, localized and independent of raw tool internals."""
# ruff: noqa: F811 -- pytest fixtures are injected by parameter name.

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.autoresearch.engine import tools, harness, store
from backend.autoresearch.engine.activity import project_event, project_tool, public_description
from backend.auth import dependencies as auth
from gateway.routes import autoresearch as routes
from test_research_privacy_and_refinement import research_api as research_api


def tool(name, **state):
    return {"type": "tool", "id": "t1", "name": name,
            "state": {"status": "completed", "input": {"query": "English retrieval keywords",
                "activity": "核查公开数据是否包含临床终点", "path": "/private/config.json"},
                "output": "PRIVATE_TOOL_OUTPUT", **state}}


@pytest.mark.parametrize("name,action", [
    ("search_web", "search_sources"), ("pathlab_search_verified_citations", "search_literature"),
    ("read_paper", "read_source"), ("webfetch", "read_source"),
    ("set_task_scope", None), ("get_research_context", None), ("skill", None),
    ("shell", None), ("subagent", None), ("unknown_private_tool", None),
])
def test_tool_projection_is_public_allowlist(name, action):
    result = project_tool(tool(name), "zh-CN")
    if action is None:
        assert result is None
        return
    assert result == {"id": "t1", "type": "activity", "action": action,
                      "status": "completed", "description": "核查公开数据是否包含临床终点", "language": "zh-CN"}
    assert "PRIVATE" not in str(result) and "query" not in result and "name" not in result


@pytest.mark.parametrize("value", [
    "Inspect /private/config.json", "LOAD_SKILL", "调用 get_research_context",
    "运行 search_web 获取信息", "打开 https://example.test/?token=secret",
    "Authorization=secret", "Read AGENTS.md", "加载技能", "<tool>raw</tool>",
    "核查疗效证据 · 核查公开数据 · 核查邻域证据",
    "x" * 241,
])
def test_technical_activity_description_is_dropped(value):
    assert public_description(value) == ""


@pytest.mark.parametrize("output", [
    {"success": False}, {"isError": True, "content": [{"type": "text", "text": "SECRET"}]},
    json.dumps({"success": False, "error": "PRIVATE_ERROR"}),
    {"content": [{"type": "text", "text": json.dumps({"success": False})}]},
])
def test_failed_result_is_not_claimed_as_success(output):
    result = project_tool(tool("read_paper", output=output), "zh-CN")
    assert result["status"] == "failed"
    assert "PRIVATE" not in str(result) and "SECRET" not in str(result)


def test_native_work_has_one_bounded_topic_and_no_runtime_state():
    raw = {"kind": "native_work", "seq": 9, "root_active": False, "inbox": 5,
           "children": [{"id": str(i), "title": "核查公开数据资源"} for i in range(100)],
           "shells": [{"id": "secret-shell"}]}
    projected = project_event(raw, "zh-CN")
    assert projected == {"kind": "native_work", "seq": 9, "status": "running", "action": "work",
                         "description": "核查公开数据资源", "language": "zh-CN"}
    assert len(json.dumps(projected)) < 250


async def test_activity_metadata_is_not_forwarded_to_business_adapter(monkeypatch):
    monkeypatch.setattr(tools.store, "get", AsyncMock(return_value=SimpleNamespace(
        session_id="s", status="running", workspace_path="/workspace", recovery_metadata={})))
    monkeypatch.setattr("backend.autoresearch.engine.connector_scope.require_connector", AsyncMock())
    search = AsyncMock(return_value=[])
    monkeypatch.setattr("backend.services.citations.search_verified", search)
    arguments = {"query": "Risom myoepithelial clinical endpoints", "activity": "核查患者队列的临床终点"}
    assert await tools.call("s", "search_verified_citations", arguments) == []
    search.assert_awaited_once_with(arguments["query"])
    assert arguments["activity"] == "核查患者队列的临床终点"
    assert "activity" not in next(item for item in tools.TOOLS if item["name"] == "get_research_context")["inputSchema"]["properties"]


async def test_language_is_present_in_live_context_and_continuation(monkeypatch):
    monkeypatch.setattr(harness.store, "experiments", AsyncMock(return_value=[]))
    monkeypatch.setattr(harness.store, "jobs", AsyncMock(return_value=[]))
    session = SimpleNamespace(session_id="s", research_question="核查数据资源", max_iterations=2,
                              current_iteration=0, recovery_metadata={"language": "zh-HK"})
    assert (await harness.context(session))["output_language"] == "zh-HK"
    prompt = await harness.continuation_prompt(session)
    assert '"output_language": "zh-HK"' in prompt and "every child" in prompt


async def test_snapshot_history_and_sse_share_public_schema(research_api, monkeypatch):
    api = research_api
    await store.update("alice", meta={"language": "zh-CN"}, event={"kind": "message", "message": {
        "id": "mixed", "type": "assistant", "content": [
            {"type": "reasoning", "text": "SECRET_REASONING"},
            {"type": "text", "text": "我会核查公开数据是否包含临床终点。"},
            tool("skill"), tool("get_research_context"), tool("search_web"),
        ], "native": {"secret": "PRIVATE_NATIVE"},
    }})
    await store.update("alice", event={"kind": "native_work", "children": [
        {"id": "secret-child", "title": "核查邻域状态证据"},
        {"id": "secret-child-2", "title": "核查疗效空间证据"},
    ], "shells": [], "inbox": 0})
    detail = (await api.client.get("/research/sessions/alice?compact=true")).json()
    page = (await api.client.get("/workbench/research/alice/activity")).json()
    assert detail["activity"] == page["items"]
    token, _ = auth.create_autoresearch_access_token(user=api.users["alice"], session_id="alice", purpose="events")
    claims = await auth.get_autoresearch_access_token_claims(token)
    request = SimpleNamespace(headers={}, query_params={"token": token}, is_disconnected=AsyncMock(return_value=False))
    response = await routes.events("alice", request, claims=claims)
    streamed = [json.loads((await anext(response.body_iterator)).split("data: ", 1)[1]) for _ in detail["events"]]
    await response.body_iterator.aclose()
    assert streamed == detail["events"]
    serialized = json.dumps({"detail": detail, "page": page, "sse": streamed}, ensure_ascii=False)
    for forbidden in ["SECRET_REASONING", "PRIVATE_NATIVE", "PRIVATE_TOOL_OUTPUT", "secret-child", "get_research_context", "English retrieval keywords", "/private/config.json"]:
        assert forbidden not in serialized
    progress = next(event for event in page["items"] if event.get("message", {}).get("id") == "mixed")
    assert progress["message"]["content"][-1]["description"] == "核查公开数据是否包含临床终点"
    assert progress["message"]["content"][-1]["language"] == "zh-CN"
