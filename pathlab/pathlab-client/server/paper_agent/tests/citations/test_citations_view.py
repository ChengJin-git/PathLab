from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pathlab_paper_agent.bootstrap import ensure_server_on_path
from pathlab_paper_agent.citations import CitationReference
from pathlab_paper_agent.schemas import PaperManifest, PaperRunStage, PaperRunStatus
from pathlab_paper_agent.storage import PaperRunPaths

ensure_server_on_path()


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    from backend.auth import current_active_user
    from backend.common.config import Config
    from backend.database import get_db
    from pathlab_paper_agent.api import routes as api_routes

    monkeypatch.setattr(Config, "get_uploads_dir", classmethod(lambda cls: tmp_path))

    async def _load_or_404(_db, paper_id: str, _user):  # noqa: ANN001
        return SimpleNamespace(paper_id=paper_id, user_id=None)

    async def _db():
        yield None

    user = SimpleNamespace(id=uuid4(), role="admin", is_superuser=True)
    monkeypatch.setattr(api_routes, "_load_or_404", _load_or_404)
    app = FastAPI()
    app.include_router(api_routes.router)
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[current_active_user] = lambda: user
    return TestClient(app)


def _make_run(paper_id: str) -> PaperRunPaths:
    paths = PaperRunPaths.for_paper(paper_id)
    paths.ensure_dirs()
    now = datetime.now(UTC)
    manifest = PaperManifest(
        paper_id=paper_id,
        status=PaperRunStatus.running,
        current_stage=PaperRunStage.literature_review,
        created_at=now,
        updated_at=now,
    )
    paths.manifest.write_text(
        json.dumps(manifest.model_dump(mode="json")),
        encoding="utf-8",
    )
    return paths


def _write_json(path, payload: object) -> None:  # noqa: ANN001
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _selected_ref(key: str = "Smith2024") -> CitationReference:
    return CitationReference(
        key=key,
        title="Metadata-rich computational pathology reference",
        authors=("Smith J", "Lee K"),
        year=2024,
        venue="MICCAI",
        entry_type="inproceedings",
        doi="10.1000/pathlab",
        source="semantic_scholar",
    )


def test_get_citations_returns_full_metadata_for_selected_refs(client: TestClient) -> None:
    paths = _make_run("paper_citations_meta")
    ref = _selected_ref()
    _write_json(paths.citations_dir / "selected_refs.json", {"items": [ref.to_dict()]})

    response = client.get("/papers/paper_citations_meta/citations")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["paper_id"] == "paper_citations_meta"
    assert body["selected_refs"][0]["key"] == "Smith2024"
    assert body["selected_refs"][0]["title"] == ref.title
    assert body["selected_refs"][0]["authors"] == ["Smith J", "Lee K"]
    assert body["selected_refs"][0]["doi"] == "10.1000/pathlab"
    assert body["selected_refs"][0]["added_by"] == "agent"


def test_get_citations_aggregates_required_keys_from_outline_locations(client: TestClient) -> None:
    paths = _make_run("paper_citations_required")
    _write_json(paths.citations_dir / "selected_refs.json", {"items": []})
    _write_json(
        paths.outline_json,
        {
            "required_cites": ["Top2020"],
            "pathlab_extensions": {"required_cites": ["Ext2021"]},
            "section_plan": [
                {
                    "section": "Introduction",
                    "required_cites": ["Section2022"],
                    "citations": ["Hint2023", {"paperId": "Object2024"}],
                }
            ],
        },
    )

    response = client.get("/papers/paper_citations_required/citations")

    assert response.status_code == 200, response.text
    assert response.json()["required_keys"] == [
        "Ext2021",
        "Hint2023",
        "Object2024",
        "Section2022",
        "Top2020",
    ]


def test_get_citations_populates_verified_pool_summary(client: TestClient) -> None:
    paths = _make_run("paper_citations_pool")
    ref = _selected_ref()
    _write_json(paths.citations_dir / "selected_refs.json", {"items": [ref.to_dict()]})
    _write_json(paths.citations_dir / "discovery_pool.json", {"items": [{"title": "A"}, {"title": "B"}]})
    _write_json(
        paths.citations_dir / "verified_pool.json",
        {
            "verified": [{"title": "A"}],
            "rejected": [
                {
                    "candidate": {"title": "Duplicate paper", "year": 2023, "source": "pubmed"},
                    "reasons": ["duplicate"],
                },
                {
                    "candidate": {"title": "Future paper", "year": 2030, "source": "openalex"},
                    "reasons": ["after_cutoff_year", "duplicate"],
                },
            ],
        },
    )

    response = client.get("/papers/paper_citations_pool/citations")

    assert response.status_code == 200, response.text
    summary = response.json()["verified_pool_summary"]
    assert summary["discovery_total"] == 2
    assert summary["verified_total"] == 1
    assert summary["selected_total"] == 1
    assert summary["rejection_breakdown"] == {"after_cutoff_year": 1, "duplicate": 2}
    assert summary["sample_rejections"][0]["title"] == "Duplicate paper"


def test_get_citations_verified_pool_summary_is_none_when_inputs_missing(client: TestClient) -> None:
    paths = _make_run("paper_citations_no_pool")
    _write_json(paths.citations_dir / "selected_refs.json", {"items": []})
    _write_json(paths.citations_dir / "discovery_pool.json", {"items": [{"title": "A"}]})

    response = client.get("/papers/paper_citations_no_pool/citations")

    assert response.status_code == 200, response.text
    assert response.json()["verified_pool_summary"] is None


def test_get_citations_includes_coverage_report(client: TestClient) -> None:
    paths = _make_run("paper_citations_coverage")
    ref = _selected_ref()
    _write_json(paths.citations_dir / "selected_refs.json", {"items": [ref.to_dict()]})
    _write_json(
        paths.citations_dir / "coverage_report.json",
        {
            "selected_ref_keys": ["Smith2024", "Lee2024"],
            "used_cite_keys": ["Smith2024"],
            "selected_coverage": 0.5,
            "min_selected_coverage": 0.9,
            "status": "pass",
        },
    )

    response = client.get("/papers/paper_citations_coverage/citations")

    assert response.status_code == 200, response.text
    assert response.json()["coverage"] == {
        "selected_count": 2,
        "cited_count": 1,
        "coverage_ratio": 0.5,
        "threshold": 0.9,
        "status": "passed",
    }


def test_dev_server_get_citations_route_is_available(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    from backend.common.config import Config
    from pathlab_paper_agent.dev_server import create_app

    monkeypatch.setattr(Config, "get_uploads_dir", classmethod(lambda cls: tmp_path))
    app = create_app(auto_run=False)
    paths = _make_run("paper_dev_citations")
    ref = _selected_ref("Dev2024")
    _write_json(paths.citations_dir / "selected_refs.json", {"items": [ref.to_dict()]})
    _write_json(
        paths.outline_json,
        {"section_plan": [{"section": "Introduction", "required_cites": ["Dev2024"]}]},
    )

    response = TestClient(app).get("/papers/paper_dev_citations/citations")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["paper_id"] == "paper_dev_citations"
    assert body["selected_refs"][0]["key"] == "Dev2024"
    assert body["required_keys"] == ["Dev2024"]
