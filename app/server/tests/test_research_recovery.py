from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from backend.autoresearch.engine import store, tools, worker
from backend.autoresearch.engine.handoff import conversation_context
from backend.autoresearch.engine.recovery import assess_help, classify_error
from gateway.routes.autoresearch import editable_source


@pytest.mark.asyncio
async def test_missing_data_preserves_work_and_becomes_recoverable(monkeypatch):
    runtime = SimpleNamespace(cleanup_orphan=AsyncMock(), stop=AsyncMock())
    monkeypatch.setattr(worker, "AgentRuntime", lambda sid: runtime)
    row = SimpleNamespace(
        status="preparing", recovery_metadata={"dataset_ids": ["missing"]}
    )
    monkeypatch.setattr(store, "get", AsyncMock(return_value=row))
    update = AsyncMock()
    monkeypatch.setattr(store, "update", update)
    monkeypatch.setattr(
        "backend.autoresearch.engine.datasets.prepare_pending_datasets",
        AsyncMock(side_effect=FileNotFoundError("labels.csv is missing")),
    )
    await worker.run_session("s")
    state = update.call_args.kwargs
    assert state["status"] == "blocked"
    assert state["meta"]["recovery"]["reason"] == "missing_data"
    assert state["meta"]["error"] == ""
    runtime.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_continue_atomically_keeps_context_and_appends_new_data(monkeypatch):
    row = SimpleNamespace(
        status="blocked",
        user_id='owner',
        max_iterations=1,
        event_sequence=7,
        recovery_metadata={
            "dataset_ids": ["old"],
            "recovery": {"reason": "missing_data"},
            "commands": [{"id": "stop", "kind": "stop", "text": ""}],
            "artifacts": [{"path": "report.md"}],
        },
    )
    db = SimpleNamespace(
        bind=None, scalar=AsyncMock(return_value=row), add=Mock(), commit=AsyncMock()
    )

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(store, "safe_session", session)
    command = await store.continue_session(
        "s", text="I fixed the script; continue.", dataset_ids=["new"], additional_experiments=2
    )
    assert row.status == "queued"
    assert row.max_iterations == 3
    assert row.recovery_metadata["dataset_ids"] == ["old", "new"]
    assert row.recovery_metadata["artifacts"] == [{"path": "report.md"}]
    assert row.recovery_metadata["commands"] == [
        {"id": command, "kind": "message", "text": "I fixed the script; continue."}
    ]
    assert row.recovery_metadata["recovery"] is None
    assert [call.args[0].sequence for call in db.add.call_args_list] == [8, 9]
    with pytest.raises(ValueError, match="already active"):
        await store.continue_session("s")


@pytest.mark.asyncio
async def test_historical_internal_prompts_are_not_public_but_keep_cursor(monkeypatch):
    events = [
        SimpleNamespace(
            event_data={
                "kind": "message",
                "seq": 1,
                "message": {
                    "type": "user",
                    "text": "Background jobs finished. PRIVATE JSON",
                },
            }
        ),
        SimpleNamespace(
            event_data={"kind": "command", "seq": 2, "text": "User addition"}
        ),
    ]

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(
            scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: events))
        )

    monkeypatch.setattr(store, "safe_session", session)
    result = await store.events("s")
    assert result[0] == {"kind": "internal", "seq": 1, "ts": None}
    assert result[1]["text"] == "User addition"
    assert "PRIVATE" not in str(result)


@pytest.mark.asyncio
async def test_completion_does_not_drop_a_just_submitted_instruction(monkeypatch):
    row = SimpleNamespace(status="running", recovery_metadata={"commands": [{"kind": "message", "text": "Also report confidence intervals."}]})
    db = SimpleNamespace(scalar=AsyncMock(return_value=row), add=Mock(), commit=AsyncMock())
    @asynccontextmanager
    async def session():
        yield db
    monkeypatch.setattr(store, "safe_session", session)
    result = await store.update("s", status="completed", event={"kind": "state", "status": "completed"})
    assert result == {}
    assert row.status == "running"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_only_can_finish_without_any_experiments(monkeypatch, tmp_path):
    monkeypatch.setattr(
        store,
        "get",
        AsyncMock(
            return_value=SimpleNamespace(status="running", workspace_path=str(tmp_path), recovery_metadata={}, session_id="s", research_question="Download", final_report=None)
        ),
    )
    monkeypatch.setattr(
        store,
        "jobs",
        AsyncMock(return_value=[{"job_id": "download-1", "kind": "download", "status": "completed"}]),
    )
    monkeypatch.setattr(store, "update", AsyncMock())
    monkeypatch.setattr(store, "experiments", AsyncMock(return_value=[]))
    await tools.call(
        "s", "finish_research", {"summary": "Data registered", "outcome": "completed"}
    )
    assert store.update.call_args.kwargs["meta"]["finish_requested"]


@pytest.mark.asyncio
async def test_agent_can_request_help_without_fabricating_a_report(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        store,
        "get",
        AsyncMock(
            return_value=SimpleNamespace(status="running", workspace_path=str(tmp_path), recovery_metadata={})
        ),
    )
    monkeypatch.setattr(store, "update", AsyncMock())
    monkeypatch.setattr(store, "jobs", AsyncMock(return_value=[]))
    await tools.call(
        "s",
        "request_help",
        {
            "reason": "data_access",
            "blocker": "external_dependency",
            "attempts": [{"action": "Checked the dataset provider", "result": "Download requires an approved account."}],
            "why_user": "Only the user can obtain the required account approval.",
            "summary": "Download requires an approved account.",
            "next_steps": [
                "Download with your approved account and register the files in Data Repo."
            ],
        },
    )
    fields = store.update.call_args.kwargs
    assert "final_report" not in fields
    assert fields["meta"]["recovery_requested"]["reason"] == "data_access"


def test_source_editor_rejects_input_data_run_snapshots_and_escape(tmp_path):
    assert editable_source(tmp_path, "analysis.py") == tmp_path / "analysis.py"
    for path in [
        "runs/r/source.py",
        "datasets/labels.csv",
        "opencode.json",
        ".opencode/secret.json",
        "../outside.py",
    ]:
        with pytest.raises((HTTPException, ValueError)):
            editable_source(tmp_path, path)
    assert classify_error(PermissionError("restricted")) == "data_access"
    assert classify_error(TimeoutError('Dataset preparation exceeded its deadline')) == 'service'
    from backend.autoresearch.engine.dataset_files import DatasetPreparationTimeout
    assert classify_error(DatasetPreparationTimeout('Remote cohort', 'resolve_sources', 10, 100)) == 'data_preparation'
    assert classify_error(RuntimeError('model.py: RuntimeError invalid tensor dimensions')) == 'code_error'


@pytest.mark.parametrize('change,error', [
    ('one_attempt', 'Continue autonomously'),
    ('same_attempt', 'Continue autonomously'),
    ('external_code', 'Ordinary code errors'),
    ('active_job', 'still pending'),
    ('stale_failure', 'predates'),
    ('wrong_job', 'failed job in this session'),
])
async def test_premature_help_does_not_pause_research(monkeypatch, tmp_path, change, error):
    row = SimpleNamespace(status='running', workspace_path=str(tmp_path), recovery_metadata={'recovery_check_after': 100})
    arguments = {
        'reason': 'code_error', 'blocker': 'repair_exhausted', 'summary': 'Operation failed',
        'attempts': [{'action': 'Corrected the import and reran', 'result': 'Missing system library'},
                     {'action': 'Tried the installed alternative reader', 'result': 'Required format unsupported'}],
        'why_user': 'The required native library is absent and cannot be installed in this sandbox.',
        'next_steps': ['Provide the required system library in the sandbox image.'], 'job_ids': ['failed'],
    }
    jobs = [{'job_id': 'failed', 'status': 'failed', 'updated_at': 101}]
    if change == 'one_attempt': arguments['attempts'] = arguments['attempts'][:1]
    elif change == 'same_attempt': arguments['attempts'] = [arguments['attempts'][0]] * 2
    elif change == 'external_code': arguments['blocker'] = 'external_dependency'
    elif change == 'active_job': jobs.append({'job_id': 'retry', 'status': 'running'})
    elif change == 'stale_failure': jobs[0]['updated_at'] = 99
    elif change == 'wrong_job': arguments['job_ids'] = ['someone-else']
    monkeypatch.setattr(store, 'get', AsyncMock(return_value=row))
    monkeypatch.setattr(store, 'jobs', AsyncMock(return_value=jobs))
    monkeypatch.setattr(store, 'update', AsyncMock())
    with pytest.raises(ValueError, match=error):
        await tools.call('s', 'request_help', arguments)
    store.update.assert_not_awaited()


def test_exhausted_distinct_repairs_keep_observed_evidence():
    issue = assess_help(SimpleNamespace(recovery_metadata={'recovery_check_after': 100}), {
        'reason': 'service', 'blocker': 'repair_exhausted', 'summary': 'Both authorized endpoints are unavailable',
        'attempts': [{'action': 'Retried the primary endpoint', 'result': 'Current request returned 503'},
                     {'action': 'Tried the configured alternate endpoint', 'result': 'Connection refused'}],
        'why_user': 'Service administration is outside the sandbox; no alternative remains.',
        'next_steps': ['Restore the provider service.'], 'job_ids': ['current'],
    }, [{'job_id': 'current', 'status': 'failed', 'updated_at': 101}])
    assert '503' in issue['detail'] and 'Connection refused' in issue['detail']
    assert issue['reason'] == 'service'


def test_handoff_retains_original_goal_recent_corrections_and_active_variant():
    messages = [
        SimpleNamespace(
            id=i,
            role="user" if i % 2 == 0 else "assistant",
            content=f"turn {i}",
            variant_group_id=None,
            is_active_variant=True,
        )
        for i in range(40)
    ]
    messages[0].content = "Use patient-level splits and never tune on test data."
    messages[-2].content = "Correction: only compute metrics; no training."
    messages[-1].variant_group_id = "v"
    messages[-1].is_active_variant = False
    result = conversation_context(messages)
    assert "patient-level splits" in result["context"]
    assert "only compute metrics; no training" in result["context"]
    assert "turn 39" not in result["context"]
