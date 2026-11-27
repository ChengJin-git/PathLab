"""Report lifecycle on real SQLite, including ownership, revision races and exports."""

import io
import json
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from docx import Document
from fastapi import FastAPI
from sqlalchemy import Integer, MetaData, event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.auth.models import User
from backend.autoresearch.engine import budget, connector_scope, jobs, store, tools, worker
from backend.database.models import (
    AnalysisRun,
    AutoResearchEvent,
    AutoResearchExperiment,
    AutoResearchSession,
    DataGroup,
    Dataset,
    DatasetTask,
    Manuscript,
    ManuscriptGeneration,
    ResearchJob,
    ResultSource,
    ResultSourceDataset,
    TrainedModel,
    TrainingTask,
    TrainingTaskWSI,
    WSISlide,
)
from backend.services import manuscript_writer, manuscripts
from gateway.routes import reports


@pytest.fixture
async def api(monkeypatch, tmp_path):
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    for model in [
        User,
        AutoResearchSession,
        AutoResearchExperiment,
        AutoResearchEvent,
        ResearchJob,
        Manuscript,
        ManuscriptGeneration,
        DataGroup,
        TrainingTask,
        TrainedModel,
        TrainingTaskWSI,
        WSISlide,
        Dataset,
        DatasetTask,
        AnalysisRun,
        ResultSource,
        ResultSourceDataset,
    ]:
        table = model.__table__.to_metadata(metadata)
        if model is AutoResearchEvent:
            table.c.id.type = Integer()
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def safe_session():
        async with sessions() as db:
            yield db

    for module in [reports, manuscripts, store, jobs, worker, manuscript_writer, connector_scope]:
        monkeypatch.setattr(module, "safe_session", safe_session)
    monkeypatch.setattr(manuscripts.Config, "get_uploads_dir", lambda: tmp_path)
    monkeypatch.setattr(
        manuscript_writer,
        "resolve_model_config",
        AsyncMock(return_value=SimpleNamespace(model="test")),
    )
    monkeypatch.setattr(
        manuscript_writer,
        "retrieve_references",
        AsyncMock(
            return_value=[
                {
                    "number": i,
                    "title": f"Retrieved study {i}",
                    "authors": ["Author"],
                    "year": 2025,
                    "venue": "Journal",
                    "url": f"https://doi.org/10.test/{i}",
                    "doi": f"10.test/{i}",
                    "abstract": "Measured pathology performance.",
                    "source": "Test registry",
                    "verified_at": "2026-10-29",
                }
                for i in [1, 2]
            ]
        ),
    )

    async def complete(model, prompt, payload, **kwargs):
        if "JSON object" in prompt:
            return json.dumps(
                {
                    "title": "Evidence-grounded pathology study",
                    "literature_query": "pathology",
                    "argument": "exploratory validation",
                }
            )
        if "completed article" in prompt:
            return payload["article"].split("## References")[0]
        value = "0.77" if payload["evidence"]["source_type"] == "experiment" else "0.81"
        text = f"This exploratory study assessed pathology classification using recorded model configurations and validation results. The validation AUROC was {value}. Prior literature motivates methodological evaluation [1, 2]. The absence of an external test cohort limits conclusions about generalization. "
        if (
            "Write the Experiments and results" in prompt
            or "Write the Results" in prompt
        ):
            text += (
                f"\n\n| Metric | Value |\n| --- | --- |\n| validation.auc | {value} |"
            )
        return text * 2

    monkeypatch.setattr(manuscript_writer, "complete", AsyncMock(side_effect=complete))
    users = {
        name: User(
            id=uuid.uuid4(),
            username=name,
            role=role,
            hashed_password="test",
            is_active=True,
        )
        for name, role in [
            ("alice", "pathologist"),
            ("bob", "pathologist"),
            ("admin", "admin"),
            ("guest", "guest"),
        ]
    }
    async with sessions() as db:
        db.add_all(users.values())
        db.add(
            DataGroup(
                group_id="g",
                name="WSI",
                data_type="wsi",
                aggregation_level="file",
                task_type="wsi_classification",
            )
        )
        for owner in ["alice", "bob"]:
            root = tmp_path / owner
            root.mkdir()
            db.add(
                AutoResearchSession(
                    session_id=owner,
                    
                    user_id=str(users[owner].id),
                    research_question=f"{owner} private study",
                    status="completed",
                    phase="completed",
                    workspace_path=str(root),
                    final_report="Measured results",
                    recovery_metadata={'title': f'{owner} research', 'enabled_connectors': ['web_search', 'articles']},
                )
            )
            db.add(
                AutoResearchExperiment(
                    session_id=owner,
                    training_task_id=f"{owner}-run",
                    experiment_name="Baseline",
                    dataset_id="d1",
                    iteration=1,
                    status="completed",
                    metrics={"validation": {"auc": 0.81, "missing": None}},
                )
            )
            db.add(
                TrainingTask(
                    task_id=f"{owner}-task",
                    task_name=f"{owner} task",
                    group_id="g",
                    user_id=str(users[owner].id),
                    status="completed",
                    model_config={"epochs": 10},
                )
            )
            db.add(
                TrainedModel(
                    model_id=f"{owner}-model",
                    task_id=f"{owner}-task",
                    model_name="Baseline",
                    model_path="model.pth",
                    classes=["a", "b"],
                    train_metrics={"accuracy": 0.9},
                    val_metrics={"auc": 0.77},
                )
            )
        db.add(
            AutoResearchSession(
                session_id="download",
                
                user_id=str(users["alice"].id),
                research_question="Download only",
                status="running",
                phase="experiment",
                workspace_path=str(tmp_path),
                final_report="Downloaded data",
                recovery_metadata={'enabled_connectors': ['web_search', 'articles']},
            )
        )
        await db.commit()
    actor = SimpleNamespace(user=users["alice"], scope=None)
    app = FastAPI()
    app.include_router(reports.router)
    app.dependency_overrides[reports.current_active_user] = lambda: actor.user

    @app.middleware("http")
    async def workspace(request, call_next):
        request.state.workspace_scope = actor.scope
        return await call_next(request)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        yield SimpleNamespace(
            client=client, actor=actor, users=users, sessions=sessions, root=tmp_path
        )
    await engine.dispose()


async def make_report(api, source_type="research", source_id="alice"):
    response = await api.client.post(
        "/reports/documents", json={"source_type": source_type, "source_id": source_id}
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["generation"]["status"] == "queued" and report["content"] == ""
    await manuscript_writer.run(report["report_id"])
    result = await api.client.get(f"/reports/documents/{report['report_id']}")
    assert result.json()["generation"]["status"] == "completed", result.text
    return result.json()


async def test_manual_source_is_one_completed_experiment_not_all_slides(api):
    report = await make_report(api, "experiment", "alice-task")
    assert len(report["evidence"]["runs"]) == 1
    assert "0.77" in report["content"] and "0.81" not in report["content"]
    assert report["recommendation"] == {
        "template": "conference",
        "completed_runs": 1,
        "dataset_count": 0,
    }
    sources = (await api.client.get("/reports/sources")).json()["items"]
    assert {r["source_id"] for r in sources} == {"alice", "alice-task"}
    async with api.sessions() as db:
        job = await db.get(ManuscriptGeneration, report['report_id'])
        assert job.progress['skill_contexts']['section:Methods']['skills'] == ['nature-writing']
        assert job.progress['skill_contexts']['review:']['skills'] == ['nature-polishing', 'humanizer']
        assert len(job.progress['skill_contexts']['review:']['sha256']) == 64


async def test_templates_and_downloads_use_generic_conference_journal_contract(api):
    templates = (await api.client.get('/reports/templates')).json()['items']
    assert set(templates) == {'conference', 'journal'}
    assert templates['conference']['name'] == 'Conference template'
    for old in ['miccai', 'nature']:
        response = await api.client.post('/reports/documents', json={
            'source_type':'experiment','source_id':'alice-task','template':old})
        assert response.status_code == 422
    report = await make_report(api)
    response = await api.client.get(f"/reports/documents/{report['report_id']}/download/latex")
    assert 'conference-' in response.headers['content-disposition']
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    readme = archive.read('README.txt').decode()
    assert 'Conference template' in readme and 'Journal template' in readme
    assert 'MICCAI' not in readme and 'Nature follows' not in readme


@pytest.mark.parametrize("actor", ["bob", "guest"])
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", ""),
        ("GET", "/download/docx"),
        ("GET", "/download/latex"),
        ("PUT", ""),
        ("POST", "/polish"),
        ("DELETE", ""),
    ],
)
async def test_reports_editing_and_downloads_are_private(api, actor, method, path):
    report = await make_report(api)
    api.actor.user = api.users[actor]
    payload = (
        {"title": "Changed", "content": "Private", "template": "journal", "revision": 1}
        if method == "PUT"
        else {"instruction": "edit", "revision": 1}
    )
    response = await api.client.request(
        method,
        f"/reports/documents/{report['report_id']}{path}",
        json=payload if method != "GET" else None,
    )
    assert response.status_code == 403
    assert "alice private" not in response.text


async def test_admin_and_workspace_scope_and_source_access_recheck(api):
    report = await make_report(api)
    api.actor.user = api.users["admin"]
    assert (
        await api.client.get(f"/reports/documents/{report['report_id']}")
    ).status_code == 200
    api.actor.scope = SimpleNamespace(workspace_id="other")
    assert (
        await api.client.get(f"/reports/documents/{report['report_id']}")
    ).status_code == 403
    api.actor.scope = None
    api.actor.user = api.users["alice"]
    async with api.sessions() as db:
        row = await db.scalar(
            select(AutoResearchSession).where(AutoResearchSession.session_id == "alice")
        )
        row.user_id = str(api.users["bob"].id)
        await db.commit()
    assert (
        await api.client.get(f"/reports/documents/{report['report_id']}/download/docx")
    ).status_code == 403


async def test_revision_conflict_and_template_switch_keep_custom_prose(api):
    report = await make_report(api)
    path = f"/reports/documents/{report['report_id']}"
    payload = {
        "title": "Updated",
        "content": report["content"] + "\n\n## Additional analysis\n\nPreserve this.",
        "template": "journal",
        "revision": report["revision"],
    }
    response = await api.client.put(path, json=payload)
    assert response.status_code == 200
    assert response.json()["revision"] == report["revision"] + 1
    content = response.json()["content"]
    assert content.index("## Results") < content.index("## Methods")
    assert "Preserve this." in content and "0.81" in content
    assert (await api.client.put(path, json=payload)).status_code == 409
    assert (await api.client.get(path)).json()["evidence"] == report["evidence"]


@pytest.mark.parametrize("template", ["conference", "journal"])
async def test_exports_are_editable_and_latex_cannot_execute_document_text(
    api, template
):
    report = await make_report(api)
    path = f"/reports/documents/{report['report_id']}"
    await api.client.put(
        path,
        json={
            "title": "CRC & MSI 研究",
            "content": report["content"] + "\n\n\\input{/etc/passwd}",
            "template": template,
            "revision": report["revision"],
        },
    )
    response = await api.client.get(path + "/download/docx")
    assert response.status_code == 200
    doc = Document(io.BytesIO(response.content))
    assert doc.tables and "0.81" in " ".join(
        c.text for row in doc.tables[0].rows for c in row.cells
    )
    text = " ".join(p.text for p in doc.paragraphs)
    assert "CRC & MSI 研究" in text
    assert ("Anonymized Authors" in text) == (template == "conference")
    assert b"vbaProject" not in response.content
    response = await api.client.get(path + "/download/latex")
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert {"main.tex", "evidence.json", "report.md", "README.txt"} <= set(
        archive.namelist()
    )
    tex = archive.read("main.tex").decode()
    assert r"\input{/etc/passwd}" not in tex
    assert r"\textbackslash{}input" in tex
    assert ("llncs.cls" in archive.namelist()) == (template == "conference")
    assert "0.81" in tex


async def test_polish_is_suggestion_only_uses_saved_evidence_and_utf16_selection(
    api, monkeypatch
):
    report = await make_report(api)
    path = f"/reports/documents/{report['report_id']}"
    await api.client.put(
        path,
        json={
            "title": "Study",
            "content": "😀原始结果 0.81",
            "template": "conference",
            "revision": report["revision"],
        },
    )
    editor = AsyncMock(return_value="明确的结果")
    monkeypatch.setattr(reports, "edit_text", editor)
    response = await api.client.post(
        path + "/polish",
        json={
            "instruction": "Clarify",
            "revision": report["revision"] + 1,
            "selection_start": 2,
            "selection_end": 6,
        },
    )
    assert response.status_code == 200
    assert editor.call_args.args[1]["selected_text"] == "原始结果"
    assert (
        editor.call_args.args[1]["evidence"]["runs"][0]["metrics"]["validation"]["auc"]
        == 0.81
    )
    assert (await api.client.get(path)).json()["content"] == "😀原始结果 0.81"
    assert (
        await api.client.post(
            path + "/polish", json={"instruction": "edit", "revision": 1}
        )
    ).status_code == 409
    assert (
        await api.client.post(
            path + "/polish",
            json={
                "instruction": "edit",
                "revision": report["revision"] + 1,
                "selection_start": 1,
                "selection_end": 2,
            },
        )
    ).status_code == 422


async def test_training_finish_requires_current_report_but_computations_do_not(api):
    await store.update("alice", status="running")
    with pytest.raises(ValueError, match="generate_article"):
        await tools.call("alice", "finish_research", {"summary": "Done"})
    published = await tools.call(
        "alice",
        "generate_article",
        {"instruction": "Discuss limitations"},
    )
    await manuscript_writer.run(published["report_id"])
    assert {
        a["name"] for a in (await store.get("alice")).recovery_metadata["artifacts"]
    } == {
        "report.md",
        "report.docx",
        "latex.zip",
    }
    assert (await tools.call("alice", "finish_research", {"summary": "Done"}))[
        "finished"
    ]
    await store.experiment_update(
        "alice", "alice-run", metrics={"validation": {"auc": 0.82}}
    )
    with pytest.raises(ValueError, match="generate_article"):
        await tools.call("alice", "finish_research", {"summary": "Changed"})
    assert (
        await tools.call(
            "download", "finish_research", {"summary": "Dataset registered"}
        )
    )["finished"]
    with pytest.raises(ValueError, match="completed model"):
        await tools.call(
            "download",
            "generate_article",
            {},
        )
    response = await api.client.post(
        "/reports/documents", json={"source_type": "research", "source_id": "download"}
    )
    assert response.status_code == 409


async def test_research_writer_respects_connector_scope_but_retains_completed_article(api):
    await store.update('alice', status='running', meta={'enabled_connectors': []})
    with pytest.raises(ValueError, match='disabled'):
        await manuscript_writer.generate_research(await store.get('alice'))
    await store.update('alice', meta={'enabled_connectors': ['web_search']})
    report = await manuscript_writer.generate_research(await store.get('alice'))
    await manuscript_writer.run(report['report_id'])
    await store.update('alice', meta={'enabled_connectors': []})
    retained = await manuscript_writer.generate_research(await store.get('alice'))
    assert retained['report_id'] == report['report_id'] and retained['status'] == 'completed'


def test_scale_recommendation_uses_completed_results_and_real_dataset_ids():
    runs = [{"status": "completed", "dataset_ids": [f"d{i % 2}"]} for i in range(6)]
    assert manuscripts.recommendation({"runs": runs})["template"] == "journal"
    runs[-1]["status"] = "failed"
    assert manuscripts.recommendation({"runs": runs})["template"] == "conference"
    assert (
        manuscripts.recommendation(
            {"runs": [{"status": "completed", "dataset_ids": ["d"]}] * 20}
        )["template"]
        == "conference"
    )


async def test_budget_shutdown_checkpoints_then_resumes_same_draft(api):
    await store.update(
        "alice",
        status="running",
        conversation_id="native-alice",
        meta={"started_at": 10, "time_budget_seconds": 60, "research_phase": "writing"},
    )
    client = SimpleNamespace(prompt=AsyncMock(), interrupt=AsyncMock())
    assert not await budget.checkpoint_stop(
        await store.get("alice"), client, "native-alice", True, [], now=80
    )
    client.interrupt.assert_not_awaited()
    assert "save_report_draft" in client.prompt.call_args.args[1]
    draft = await tools.call(
        "alice",
        "save_report_draft",
        {"title": "Study", "content": "## Abstract\n\nComplete first section."},
    )
    assert draft["status"] == "draft"
    assert not (api.root / "alice/reports").exists()
    with pytest.raises(ValueError, match="Budget reached"):
        await tools.call("alice", "generate_article", {})
    assert await budget.checkpoint_stop(
        await store.get("alice"), client, "native-alice", False, [], now=90
    )
    client.interrupt.assert_not_awaited()
    stopped = await store.get("alice")
    assert (
        stopped.status == "blocked"
        and stopped.recovery_metadata["recovery"]["reason"] == "budget"
    )
    assert (api.root / "alice/budget-checkpoint.json").is_file()
    await store.continue_session(
        "alice", additional_time_seconds=1800, additional_experiments=2
    )
    resumed = await store.get("alice")
    assert resumed.conversation_id == "native-alice"
    assert resumed.recovery_metadata["budget_shutdown"] is None
    assert (
        resumed.recovery_metadata["started_at"] is None
    )  # Queue wait is not research time.
    assert resumed.recovery_metadata["time_budget_seconds"] == 1800
    assert resumed.recovery_metadata["report_draft_id"] == draft["report_id"]
    assert "Complete first section." in await worker.resume_context(
        resumed.recovery_metadata
    )


async def test_unresponsive_writer_is_bounded_and_preserves_partial_output(api):
    await store.update(
        "alice", status="running", meta={"started_at": 10, "time_budget_seconds": 60}
    )
    client = SimpleNamespace(prompt=AsyncMock(), interrupt=AsyncMock())
    await budget.checkpoint_stop(
        await store.get("alice"), client, "native", True, [], now=80
    )
    messages = [
        {"type": "assistant", "text": "Unfinished section, retained for recovery"}
    ]
    assert await budget.checkpoint_stop(
        await store.get("alice"), client, "native", True, messages, now=201
    )
    client.interrupt.assert_awaited_once()
    assert (
        "Unfinished section" in (api.root / "alice/budget-checkpoint.json").read_text()
    )
    assert not (api.root / "alice/reports").exists()


async def test_exceeded_experiment_attempts_request_recoverable_checkpoint(api):
    await store.update("alice", status="running", current_iteration=3, max_iterations=3)
    with pytest.raises(ValueError, match="Experiment budget reached"):
        await jobs.submit(
            "alice",
            "experiment",
            {"name": "too many", "command": ["python", "train.py"]},
        )
    row = await store.get("alice")
    assert row.recovery_metadata["budget_stop_requested"] == "experiments"
    assert row.current_iteration == 3
    assert await store.jobs("alice") == []


async def test_budget_expiring_during_export_leaves_only_a_draft(api, monkeypatch):
    from backend.services import report_export

    await store.update(
        "alice", status="running", meta={"started_at": 10, "time_budget_seconds": 60}
    )
    monkeypatch.setattr(report_export, "word", lambda report: b"docx")
    monkeypatch.setattr(report_export, "latex", lambda report: b"latex")
    evidence = await manuscripts.research_evidence(await store.get("alice"))
    report = await manuscript_writer.enqueue(
        str(api.users["alice"].id), evidence, autonomous=True
    )
    with pytest.raises(manuscript_writer.WritingPaused):
        await manuscripts.publish_document(
            await store.get("alice"), report["report_id"]
        )
    assert not (api.root / "alice/reports").exists()
    assert not (await store.get("alice")).recovery_metadata.get("manuscript_id")


async def test_worker_uses_budget_checkpoint_and_existing_blocked_recovery(
    api, monkeypatch
):
    await store.update(
        "alice",
        status="running",
        conversation_id="native-alice",
        meta={"started_at": 10, "time_budget_seconds": 60, "research_phase": "writing"},
    )

    async def prompt(conversation_id, text, *args, **kwargs):
        if text == budget.CHECKPOINT_PROMPT:
            await tools.call(
                "alice",
                "save_report_draft",
                {"title": "Study", "content": "## Abstract\n\nSaved progress."},
            )
            await tools.call(
                "alice",
                "request_help",
                {
                    "reason": "budget",
                    "blocker": "external_dependency",
                    "attempts": [{"action": "Checked remaining budget and saved the draft", "result": "Time budget exhausted; draft checkpoint saved."}],
                    "why_user": "Additional writing time requires user authorization.",
                    "summary": "Results saved; discussion remains.",
                    "next_steps": ["Add time and continue writing."],
                },
            )

    client = SimpleNamespace(
        ensure_research_tools=AsyncMock(return_value=False),
        prompt=AsyncMock(side_effect=prompt),
        messages=AsyncMock(return_value=[]),
        active=AsyncMock(return_value=False),
        work_state=AsyncMock(return_value={'root_active': False, 'children': [], 'shells': [], 'inbox': 0}),
        interrupted_children=AsyncMock(return_value=[]),
        forms=AsyncMock(return_value=[]),
        interrupt=AsyncMock(),
    )
    runtime = SimpleNamespace(
        cleanup_orphan=AsyncMock(),
        start=AsyncMock(return_value=client),
        stop=AsyncMock(),
    )
    monkeypatch.setattr(worker, "AgentRuntime", lambda sid: runtime)
    monkeypatch.setattr(
        worker,
        "resolve_model_config",
        AsyncMock(return_value=SimpleNamespace(public=dict, model="test")),
    )
    monkeypatch.setattr(
        "backend.autoresearch.engine.datasets.validate_access", AsyncMock()
    )
    monkeypatch.setattr(worker, "watch_events", AsyncMock())
    await worker.run_session("alice")
    row = await store.get("alice")
    assert row.status == "blocked"
    assert (
        row.recovery_metadata["recovery"]["summary"]
        == "Results saved; discussion remains."
    )
    assert row.recovery_metadata["report_draft_id"]
    assert not row.recovery_metadata.get("finish_requested")
    runtime.stop.assert_awaited_once()


async def test_recent_reports_visibility_and_empty_queued_document(api):
    created = await api.client.post(
        "/reports/documents",
        json={"source_type": "experiment", "source_id": "alice-task"},
    )
    assert created.status_code == 200
    assert (
        created.json()["content"] == ""
        and created.json()["generation"]["status"] == "queued"
    )
    api.actor.user = api.users["bob"]
    await api.client.post(
        "/reports/documents", json={"source_type": "research", "source_id": "bob"}
    )
    own = (await api.client.get("/reports/documents")).json()["items"]
    assert len(own) == 1 and own[0]["user_id"] == str(api.users["bob"].id)
    api.actor.user = api.users["admin"]
    assert len((await api.client.get("/reports/documents")).json()["items"]) == 2
    api.actor.user = api.users["guest"]
    for path in ["/reports/documents", "/reports/sources", "/reports/templates"]:
        assert (await api.client.get(path)).status_code == 403
    assert (
        await api.client.post(
            "/reports/documents",
            json={"source_type": "experiment", "source_id": "alice-task"},
        )
    ).status_code == 403


async def test_citation_failure_keeps_draft_and_retry_generates_real_sections(
    api, monkeypatch
):
    from backend.services.citations import CitationRetrievalError

    lookup = manuscript_writer.retrieve_references
    monkeypatch.setattr(
        manuscript_writer,
        "retrieve_references",
        AsyncMock(side_effect=CitationRetrievalError("citations_unavailable")),
    )
    response = await api.client.post(
        "/reports/documents",
        json={"source_type": "experiment", "source_id": "alice-task"},
    )
    report_id = response.json()["report_id"]
    await manuscript_writer.run(report_id)
    result = (await api.client.get(f"/reports/documents/{report_id}")).json()
    assert (
        result["status"] == "draft"
        and result["generation"]["error_code"] == "citations_unavailable"
    )
    assert result["content"] == ""
    monkeypatch.setattr(manuscript_writer, "retrieve_references", lookup)
    assert (
        await api.client.post(f"/reports/documents/{report_id}/resume")
    ).status_code == 200
    await manuscript_writer.run(report_id)
    result = (await api.client.get(f"/reports/documents/{report_id}")).json()
    assert result["status"] == "ready"
    assert "## References" in result["content"] and "[1, 2]" in result["content"]
    assert result["figures"] and "figures/figure-" in result["content"]


async def test_figure_access_and_editable_font_exports(api):
    report = await make_report(api, "experiment", "alice-task")
    assert report["figures"][0]["font"] == "Liberation Sans"
    path = f"/reports/documents/{report['report_id']}"
    assert (await api.client.get(path + "/figures/figure-1.png")).status_code == 200
    doc = Document(io.BytesIO((await api.client.get(path + "/download/docx")).content))
    assert len(doc.inline_shapes) >= 1
    archive = zipfile.ZipFile(
        io.BytesIO((await api.client.get(path + "/download/latex")).content)
    )
    svg = archive.read("figures/figure-1.svg").decode()
    assert (
        "<text" in svg and "Liberation Sans" in svg and "data:font/ttf;base64," in svg
    )
    assert {
        "figures/figure-1.pdf",
        "figures/figure-1.json",
        "references.bib",
        "fonts/LICENSE.txt",
    } <= set(archive.namelist())
    api.actor.user = api.users["bob"]
    assert (await api.client.get(path + "/figures/figure-1.png")).status_code == 403


def test_unverified_citation_numbers_and_template_prose_are_rejected():
    with pytest.raises(manuscript_writer.WritingError, match="invalid_citations"):
        manuscript_writer.validate_prose(
            "A measured study reports limitations [99]. " * 10, [{"number": 1}]
        )
    with pytest.raises(manuscript_writer.WritingError, match="incomplete_response"):
        manuscript_writer.validate_prose("[TODO] Complete the study. " * 10, [])


async def test_writer_preserves_completed_section_when_budget_expires(api, monkeypatch):
    await store.update("alice", status="running")
    response = await manuscript_writer.generate_research(await store.get("alice"))
    original = manuscript_writer.complete

    async def expires_after_section(model, prompt, payload, **kwargs):
        result = await original(model, prompt, payload, **kwargs)
        if "Write the Introduction" in prompt:
            await store.update(
                "alice", meta={"started_at": 1, "time_budget_seconds": 1}
            )
        return result

    monkeypatch.setattr(manuscript_writer, "complete", expires_after_section)
    await manuscript_writer.run(response["report_id"])
    report, job = await manuscript_writer.read_job(response["report_id"])
    assert job.status == "paused" and job.error_code == "budget"
    assert "## Introduction" in report.content and report.status == "draft"
    assert not (api.root / "alice/reports").exists()


@pytest.mark.parametrize("status", ["draft", "ready"])
async def test_delete_report_removes_own_assets_but_preserves_experiment(api, status):
    report = await make_report(api, "experiment", "alice-task")
    async with api.sessions() as db:
        row = await db.get(Manuscript, report["report_id"])
        row.status = status
        await db.commit()
    folder = api.root / "reports" / report["report_id"]
    assert folder.exists()
    result = await api.client.delete(f"/reports/documents/{report['report_id']}")
    assert result.status_code == 200
    assert not folder.exists()
    assert (
        await api.client.get(f"/reports/documents/{report['report_id']}")
    ).status_code == 404
    async with api.sessions() as db:
        assert await db.get(ManuscriptGeneration, report["report_id"]) is None
        assert (
            await db.scalar(
                select(TrainingTask).where(TrainingTask.task_id == "alice-task")
            )
            is not None
        )


async def test_admin_delete_clears_research_report_links_only(api):
    await store.update("alice", status="running")
    queued = await manuscript_writer.generate_research(await store.get("alice"))
    await manuscript_writer.run(queued["report_id"])
    report_id = queued["report_id"]
    untouched = api.root / "alice" / "findings.md"
    untouched.write_text("Experiment findings retained")
    await store.update("alice", status="completed")
    api.actor.user = api.users["admin"]
    response = await api.client.delete(f"/reports/documents/{report_id}")
    assert response.status_code == 200
    meta = (await store.get("alice")).recovery_metadata
    assert not any(
        meta.get(key) == report_id
        for key in ["manuscript_id", "report_draft_id", "report_generation_id"]
    )
    assert not any(
        a["path"].startswith(f"reports/{report_id}/") for a in meta["artifacts"]
    )
    assert not (api.root / "alice" / "reports" / report_id).exists()
    assert untouched.read_text() == "Experiment findings retained"
    assert len(await store.experiments("alice")) == 1


@pytest.mark.parametrize("status", ["queued", "running"])
async def test_active_writer_cannot_be_deleted_or_race_a_resume(api, status):
    response = await api.client.post(
        "/reports/documents",
        json={"source_type": "experiment", "source_id": "alice-task"},
    )
    report_id = response.json()["report_id"]
    async with api.sessions() as db:
        row = await db.get(ManuscriptGeneration, report_id)
        row.status = status
        await db.commit()
    assert (
        await api.client.delete(f"/reports/documents/{report_id}")
    ).status_code == 409
    assert (await api.client.get(f"/reports/documents/{report_id}")).status_code == 200


async def test_recent_report_cursor_paging_is_lightweight_stable_and_private(api):
    # Large bodies and progress objects must never be loaded just to render a list.
    start = datetime(2026, 10, 29)
    evidence = {"runs": [], "private_blob": "private evidence " * 20000}
    async with api.sessions() as db:
        for i in range(63):
            report_id = f"{i:032x}"
            db.add(
                Manuscript(
                    report_id=report_id,
                    user_id=str(api.users["alice"].id),
                    source_type="experiment",
                    source_id="alice-task",
                    title=f"Report {i}",
                    template="conference",
                    status="ready",
                    content="Article text " * 16000,
                    evidence=evidence,
                    # Ties exercise the ID tiebreaker as well as the date boundary.
                    created_at=start + timedelta(seconds=i // 3),
                    updated_at=start,
                )
            )
            db.add(
                ManuscriptGeneration(
                    report_id=report_id,
                    status="completed",
                    stage="completed",
                    options={},
                    progress={
                        "current_section": "",
                        "sections": {
                            "Introduction": "Private generation prose " * 20000
                        },
                    },
                )
            )
        db.add(
            Manuscript(
                report_id="f" * 32,
                user_id=str(api.users["bob"].id),
                source_type="research",
                source_id="bob",
                title="Bob private report",
                template="journal",
                status="draft",
                content="Private",
                evidence={"runs": []},
                created_at=start + timedelta(days=1),
                updated_at=start,
            )
        )
        await db.commit()
    queries = []
    engine = api.sessions.kw["bind"].sync_engine

    def capture(connection, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = await api.client.get("/reports/documents")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["page_size"] == 20 and len(first["items"]) == 20
    assert len(response.content) < 20000
    assert all(
        not {"content", "evidence", "recommendation", "word_count"} & item.keys()
        for item in first["items"]
    )
    assert (
        "private_blob" not in response.text
        and "Private generation prose" not in response.text
    )
    assert len(queries) == 2  # bounded page projection + only the page's owner names
    assert (
        "OFFSET" not in queries[0].upper() or "OFFSET ?" in queries[0]
    )  # SQLite renders implicit zero offset.
    assert "manuscripts.evidence" not in queries[0]
    assert "substr(manuscripts.content" in queries[0]
    assert ", manuscript_generations.progress," not in queries[0]
    assert "JSON_EXTRACT(manuscript_generations.progress" in queries[0]
    assert "users.hashed_password" not in queries[1]
    seen = [item["report_id"] for item in first["items"]]
    # Finishing/editing an article between requests must not move it across page boundaries.
    async with api.sessions() as db:
        row = await db.get(Manuscript, f"{2:032x}")
        row.updated_at = start + timedelta(days=2)
        await db.commit()
    cursor = first["next_cursor"]
    while cursor:
        page = (
            await api.client.get("/reports/documents", params={"cursor": cursor})
        ).json()
        assert len(page["items"]) <= 20
        seen += [item["report_id"] for item in page["items"]]
        cursor = page["next_cursor"]
    assert seen == [f"{i:032x}" for i in reversed(range(63))]
    api.actor.user = api.users["admin"]
    assert (await api.client.get("/reports/documents")).json()["items"][0][
        "title"
    ] == "Bob private report"
    api.actor.user = api.users["guest"]
    assert (
        await api.client.get(
            "/reports/documents", params={"cursor": first["next_cursor"]}
        )
    ).status_code == 403


@pytest.mark.parametrize(
    "cursor", ["garbage", "W10", "WyJub3QtYS1kYXRlIiwiYSJd", "x" * 257]
)
async def test_invalid_report_cursors_are_rejected(api, cursor):
    assert (
        await api.client.get("/reports/documents", params={"cursor": cursor})
    ).status_code == 422
