from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pathlab_paper_agent.bootstrap import ensure_server_on_path
from pathlab_paper_agent.citations import CitationReference, generate_bibtex
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


def _make_run(paper_id: str, refs: list[CitationReference] | None = None) -> PaperRunPaths:
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
    paths.manifest.write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")
    refs = refs or []
    (paths.citations_dir / "selected_refs.json").write_text(
        json.dumps({"items": [ref.to_dict() for ref in refs]}),
        encoding="utf-8",
    )
    paths.refs_bib.write_text(generate_bibtex(refs), encoding="utf-8")
    paths.outline_json.write_text(
        json.dumps(
            {
                "required_cites": [],
                "pathlab_extensions": {},
                "section_plan": [],
            }
        ),
        encoding="utf-8",
    )
    return paths


def _read_selected(paths: PaperRunPaths) -> list[dict]:
    return json.loads((paths.citations_dir / "selected_refs.json").read_text(encoding="utf-8"))["items"]


def _mock_httpx_client(monkeypatch, handler) -> None:  # noqa: ANN001
    from pathlab_paper_agent.citations import manual_add

    real_client = manual_add.httpx.Client

    def _factory(*args, **kwargs):  # noqa: ANN002, ANN003
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(manual_add.httpx, "Client", _factory)


def test_manual_add_doi_fetches_bibtex_and_persists_ref(client: TestClient, monkeypatch) -> None:
    paths = _make_run("paper_manual_doi")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://doi.org/10.1038/test"
        assert request.headers["accept"] == "application/x-bibtex"
        return httpx.Response(
            200,
            text=(
                "@article{Crossref2024,"
                "title={Computational pathology at scale},"
                "author={Smith J and Lee K},"
                "journal={Nature Medicine},"
                "year={2024},"
                "doi={10.1038/test}}"
            ),
        )

    _mock_httpx_client(monkeypatch, handler)

    response = client.post(
        "/papers/paper_manual_doi/citations",
        json={"mode": "doi", "doi": "10.1038/test"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["key"] == "J2024_computational_pathology_at"
    assert body["ref"]["entry_type"] == "article"
    assert body["ref"]["doi"] == "10.1038/test"
    assert body["ref"]["added_by"] == "user"
    assert _read_selected(paths)[0]["key"] == body["key"]
    assert "@article{J2024_computational_pathology_at" in paths.refs_bib.read_text(encoding="utf-8")
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert manifest["stage_log"][-1]["status"] == "user_added"


def test_manual_add_arxiv_fetches_atom_and_renders_misc(client: TestClient, monkeypatch) -> None:
    paths = _make_run("paper_manual_arxiv")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/query"
        assert request.url.params["id_list"] == "2401.01234v2"
        return httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
            <feed xmlns="http://www.w3.org/2005/Atom">
              <entry>
                <id>http://arxiv.org/abs/2401.01234v2</id>
                <title>Arxiv pathology preprint</title>
                <summary>A short abstract.</summary>
                <published>2024-01-02T00:00:00Z</published>
                <author><name>Doe A</name></author>
              </entry>
            </feed>""",
        )

    _mock_httpx_client(monkeypatch, handler)

    response = client.post(
        "/papers/paper_manual_arxiv/citations",
        json={"mode": "arxiv", "arxiv_id_or_url": "https://arxiv.org/abs/2401.01234v2"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["ref"]["entry_type"] == "misc"
    assert body["ref"]["arxiv_id"] == "2401.01234v2"
    bibtex = paths.refs_bib.read_text(encoding="utf-8")
    assert "@misc{" in bibtex
    assert "eprint = {2401.01234v2}" in bibtex


def test_manual_add_bibtex_paste_parses_inproceedings(client: TestClient) -> None:
    paths = _make_run("paper_manual_bibtex")
    raw = (
        "@inproceedings{Smith2020,"
        "title={MIL for WSI},"
        "author={Smith J and Doe A},"
        "booktitle={MICCAI},"
        "year={2020}}"
    )

    response = client.post(
        "/papers/paper_manual_bibtex/citations",
        json={"mode": "bibtex", "bibtex_raw": raw},
    )

    assert response.status_code == 201, response.text
    ref = response.json()["ref"]
    assert ref["entry_type"] == "inproceedings"
    assert ref["booktitle"] == "MICCAI"
    assert ref["authors"] == ["Smith J", "Doe A"]
    assert _read_selected(paths)[0]["source"] == "bibtex"


def test_manual_add_manual_fields_persist(client: TestClient) -> None:
    paths = _make_run("paper_manual_fields")

    response = client.post(
        "/papers/paper_manual_fields/citations",
        json={
            "mode": "manual",
            "manual": {
                "title": "Manual reference for pathology",
                "authors": ["Curator C"],
                "year": 2022,
                "venue": "Journal of Pathology",
                "entry_type": "article",
            },
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["ref"]["source"] == "manual"
    assert _read_selected(paths)[0]["title"] == "Manual reference for pathology"


def test_manual_add_dry_run_returns_preview_without_mutating(client: TestClient) -> None:
    paths = _make_run("paper_manual_preview")
    before = (paths.citations_dir / "selected_refs.json").read_text(encoding="utf-8")

    response = client.post(
        "/papers/paper_manual_preview/citations",
        json={
            "mode": "manual",
            "dry_run": True,
            "manual": {"title": "Preview only reference", "authors": ["Preview P"], "year": 2025},
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["proposed_key"] == "P2025_preview_only_reference"
    assert (paths.citations_dir / "selected_refs.json").read_text(encoding="utf-8") == before


def test_manual_add_duplicate_doi_returns_409(client: TestClient) -> None:
    existing = CitationReference(
        key="Existing2024",
        title="Existing reference",
        doi="10.1000/existing",
        added_by="agent",
    )
    _make_run("paper_manual_duplicate_doi", [existing])

    response = client.post(
        "/papers/paper_manual_duplicate_doi/citations",
        json={
            "mode": "manual",
            "manual": {"title": "Different title", "doi": "10.1000/existing"},
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "duplicate"
    assert response.json()["duplicate_of"] == "Existing2024"


def test_manual_add_duplicate_normalized_title_returns_409(client: TestClient) -> None:
    existing = CitationReference(
        key="Title2024",
        title="Whole slide pathology with robust validation",
        added_by="agent",
    )
    _make_run("paper_manual_duplicate_title", [existing])

    response = client.post(
        "/papers/paper_manual_duplicate_title/citations",
        json={
            "mode": "manual",
            "manual": {"title": "Whole-slide pathology with robust validation"},
        },
    )

    assert response.status_code == 409
    assert response.json()["duplicate_of"] == "Title2024"


def test_manual_add_phi_in_title_returns_422(client: TestClient) -> None:
    _make_run("paper_manual_phi")

    response = client.post(
        "/papers/paper_manual_phi/citations",
        json={
            "mode": "manual",
            "manual": {"title": "Outcome study for patient case-12345"},
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "phi_detected"


def test_manual_add_invalid_bibtex_returns_422(client: TestClient) -> None:
    _make_run("paper_manual_bad_bibtex")

    response = client.post(
        "/papers/paper_manual_bad_bibtex/citations",
        json={"mode": "bibtex", "bibtex_raw": "garbage"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_bibtex"


def test_manual_add_crossref_failure_returns_502(client: TestClient, monkeypatch) -> None:
    _make_run("paper_manual_fetch_failed")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    _mock_httpx_client(monkeypatch, handler)

    response = client.post(
        "/papers/paper_manual_fetch_failed/citations",
        json={"mode": "doi", "doi": "10.1000/fail"},
    )

    assert response.status_code == 502
    assert response.json()["code"] == "fetch_failed"


def test_delete_user_added_ref_regenerates_bibtex(client: TestClient) -> None:
    user_ref = CitationReference(
        key="User2024",
        title="User removable reference",
        authors=("User U",),
        year=2024,
        added_by="user",
    )
    agent_ref = CitationReference(key="Agent2024", title="Agent reference", added_by="agent")
    paths = _make_run("paper_manual_delete_user", [user_ref, agent_ref])

    response = client.delete("/papers/paper_manual_delete_user/citations/User2024")

    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": True, "key": "User2024"}
    assert [item["key"] for item in _read_selected(paths)] == ["Agent2024"]
    bibtex = paths.refs_bib.read_text(encoding="utf-8")
    assert "User2024" not in bibtex
    assert "Agent2024" in bibtex


def test_delete_agent_added_ref_is_forbidden(client: TestClient) -> None:
    agent_ref = CitationReference(key="Agent2024", title="Agent reference", added_by="agent")
    _make_run("paper_manual_delete_agent", [agent_ref])

    response = client.delete("/papers/paper_manual_delete_agent/citations/Agent2024")

    assert response.status_code == 403
    assert response.json()["code"] == "not_user_added"


def test_delete_required_ref_returns_409(client: TestClient) -> None:
    user_ref = CitationReference(key="User2024", title="User required reference", added_by="user")
    paths = _make_run("paper_manual_delete_required", [user_ref])
    paths.outline_json.write_text(
        json.dumps({"required_cites": ["User2024"], "pathlab_extensions": {}, "section_plan": []}),
        encoding="utf-8",
    )

    response = client.delete("/papers/paper_manual_delete_required/citations/User2024")

    assert response.status_code == 409
    assert response.json()["code"] == "still_required"
