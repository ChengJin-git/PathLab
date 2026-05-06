"""Integration coverage for the Phase 2.1 outline approval gate."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pathlab_paper_agent.pipeline import complete_run, run_after_outline, run_until_outline

from backend.database.repositories.paper_generation import PaperGenerationRunRepository
from pathlab_paper_agent.schemas import PaperRunStage, PaperRunStatus
from pathlab_paper_agent.storage import PaperRunPaths

_RUN_UNTIL_OUTLINE = "paper_generation.run_until_outline"
_RUN_AFTER_OUTLINE = "paper_generation.run_after_outline"


@pytest.fixture(autouse=True)
def isolated_uploads(tmp_path: Path, monkeypatch) -> Path:
    from backend.common.config import Config

    monkeypatch.setattr(Config, "get_uploads_dir", classmethod(lambda cls: tmp_path))
    return tmp_path


@pytest_asyncio.fixture
async def db_engine() -> AsyncGenerator:
    from backend.database.models import Base, PaperGenerationRun  # noqa: F401

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as session:
        yield session


@pytest.fixture
def admin_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.role = "admin"
    user.is_active = True
    user.is_superuser = True
    return user


@pytest.fixture
def test_app(db_session, admin_user) -> Iterator[FastAPI]:
    from backend.auth import current_active_user
    from backend.database import get_db
    from gateway.paper_generation.routes import router as paper_router

    app = FastAPI()
    app.include_router(paper_router)

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_active_user] = lambda: admin_user
    yield app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    return TestClient(test_app)


def _valid_outline() -> dict:
    return {
        "plotting_plan": [
            {
                "figure_id": "fig:main",
                "kind": "empirical",
                "source": "experimental_log",
                "design_objective": "Summarize the locked primary result.",
                "backend": "deterministic_plotting",
                "plot_spec": {"generator": "summary"},
            }
        ],
        "macro_lit_search": ["computational pathology validation"],
        "micro_lit_clusters": [
            {
                "cluster": "weakly supervised WSI",
                "queries": ["multiple instance learning whole slide images"],
            }
        ],
        "section_plan": [
            {
                "section": "Methods",
                "goal": "Describe cohort, model, evaluation, and reproducibility.",
                "evidence_inputs": ["evidence_public"],
                "citation_hints": ["whole slide image classification"],
                "locked_block_inputs": ["locked_blocks/method_block.tex"],
            }
        ],
        "pathlab_extensions": {
            "templates": ["miccai"],
            "claim_plan": [{"claim": "Locked evidence supports the primary result."}],
            "table_plan": [],
            "guard_requirements": ["metric", "identifier"],
            "template_styles": [{"template_id": "miccai"}],
        },
    }


def _create_payload() -> dict:
    return {
        "title": "Outline Gate Smoke",
        "source_tasks": [{"task_id": "paper_dev_source"}],
        "selected_templates": ["miccai"],
    }


async def _sync_row_to_manifest(db_session, manifest) -> None:
    await PaperGenerationRunRepository.update(
        db_session,
        manifest.paper_id,
        status=manifest.status.value,
        current_stage=manifest.current_stage.value,
        error_message=manifest.error_message,
        finished_at=manifest.finished_at,
    )
    await db_session.commit()


async def _set_row_status(
    db_session,
    paper_id: str,
    *,
    status: PaperRunStatus,
    current_stage: PaperRunStage,
) -> None:
    await PaperGenerationRunRepository.update(
        db_session,
        paper_id,
        status=status.value,
        current_stage=current_stage.value,
        error_message=None,
        finished_at=None,
    )
    await db_session.commit()


def _install_inline_worker(
    monkeypatch,
    db_session,
    *,
    run_job_b: bool = False,
) -> list[tuple[str, str]]:
    from pathlab_paper_agent.api import routes as api_routes

    enqueued: list[tuple[str, str]] = []

    async def _enqueue(paper_id: str, handler: str):
        enqueued.append((paper_id, handler))
        if handler == _RUN_UNTIL_OUTLINE:
            manifest = run_until_outline(paper_id)
            await _sync_row_to_manifest(db_session, manifest)
        elif handler == _RUN_AFTER_OUTLINE and run_job_b:
            manifest = run_after_outline(paper_id)
            await _sync_row_to_manifest(db_session, manifest)
        return {"paper_id": paper_id, "handler": handler}

    monkeypatch.setattr(api_routes, "_enqueue_paper_generation_job", _enqueue)
    return enqueued


def _outline_body(*, approve: bool, outline: dict | None = None) -> dict:
    return {"outline": outline or _valid_outline(), "approve": approve}


@pytest.mark.asyncio
async def test_run_pauses_after_outlining(client, monkeypatch, db_session) -> None:
    _install_inline_worker(monkeypatch, db_session)

    create = client.post("/papers", json=_create_payload())

    assert create.status_code == 200, create.text
    paper_id = create.json()["paper_id"]
    detail = client.get(f"/papers/{paper_id}").json()
    assert detail["status"] == PaperRunStatus.awaiting_outline_approval.value
    assert detail["current_stage"] == PaperRunStage.outlining.value
    assert PaperRunPaths.for_paper(paper_id).outline_json.is_file()


@pytest.mark.asyncio
async def test_put_outline_save_only(client, monkeypatch, db_session) -> None:
    enqueued = _install_inline_worker(monkeypatch, db_session)
    create = client.post("/papers", json=_create_payload())
    paper_id = create.json()["paper_id"]
    enqueued.clear()

    outline = _valid_outline()
    outline["section_plan"][0]["goal"] = "User-edited outline goal."
    response = client.put(
        f"/papers/{paper_id}/outline",
        json=_outline_body(approve=False, outline=outline),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "paper_id": paper_id,
        "approved": False,
        "current_stage": PaperRunStage.outlining.value,
    }
    assert enqueued == []
    detail = client.get(f"/papers/{paper_id}").json()
    assert detail["status"] == PaperRunStatus.awaiting_outline_approval.value
    saved = json.loads(PaperRunPaths.for_paper(paper_id).outline_json.read_text())
    assert saved["section_plan"][0]["goal"] == "User-edited outline goal."


@pytest.mark.asyncio
async def test_put_outline_approve_resumes(client, monkeypatch, db_session) -> None:
    enqueued = _install_inline_worker(monkeypatch, db_session, run_job_b=True)
    create = client.post("/papers", json=_create_payload())
    paper_id = create.json()["paper_id"]
    enqueued.clear()
    generated_outline = json.loads(PaperRunPaths.for_paper(paper_id).outline_json.read_text())

    response = client.put(
        f"/papers/{paper_id}/outline",
        json=_outline_body(approve=True, outline=generated_outline),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "paper_id": paper_id,
        "approved": True,
        "current_stage": PaperRunStage.plotting.value,
    }
    assert enqueued == [(paper_id, _RUN_AFTER_OUTLINE)]
    detail = client.get(f"/papers/{paper_id}").json()
    assert detail["status"] == PaperRunStatus.completed.value
    assert detail["current_stage"] == PaperRunStage.completed.value
    paths = PaperRunPaths.for_paper(paper_id)
    assert paths.figures_manifest.is_file()
    assert (paths.sections_dir / "methods.tex").is_file()
    assert (paths.exports_dir / "miccai_bundle.zip").is_file()
    assert detail["stage_log"][-1]["stage"] == PaperRunStage.completed.value


@pytest.mark.asyncio
async def test_put_outline_invalid_schema_returns_422(client, monkeypatch, db_session) -> None:
    _install_inline_worker(monkeypatch, db_session)
    create = client.post("/papers", json=_create_payload())
    paper_id = create.json()["paper_id"]

    response = client.put(
        f"/papers/{paper_id}/outline",
        json={"outline": {"plotting_plan": []}, "approve": False},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_outline_wrong_status_rejected(client, db_session) -> None:
    create = client.post("/papers", json=_create_payload())
    paper_id = create.json()["paper_id"]
    await _set_row_status(
        db_session,
        paper_id,
        status=PaperRunStatus.completed,
        current_stage=PaperRunStage.completed,
    )

    response = client.put(
        f"/papers/{paper_id}/outline",
        json=_outline_body(approve=False),
    )

    assert response.status_code == 422
    assert "outline cannot be edited at status completed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_complete_run_full_bypass_works_for_existing_e2e(tmp_path: Path) -> None:
    from pathlab_paper_agent.pipeline import create_dev_run

    paper_id, paths = await create_dev_run(paper_id="paper_full_bypass", uploads_dir=tmp_path)

    manifest = complete_run(paper_id, uploads_dir=tmp_path, bypass_approval=True)

    assert manifest.status == PaperRunStatus.completed
    assert manifest.current_stage == PaperRunStage.completed
    assert paths.outline_json.is_file()
    assert paths.figures_manifest.is_file()
    assert (paths.sections_dir / "methods.tex").is_file()
    assert (paths.exports_dir / "miccai_bundle.zip").is_file()
