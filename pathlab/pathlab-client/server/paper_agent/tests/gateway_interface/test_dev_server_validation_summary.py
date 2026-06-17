from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from pathlab_paper_agent.dev_server import create_app
from pathlab_paper_agent.schemas import PaperManifest, PaperRunStage, PaperRunStatus
from pathlab_paper_agent.storage import PaperRunPaths


def _make_run(paper_id: str) -> PaperRunPaths:
    paths = PaperRunPaths.for_paper(paper_id)
    paths.ensure_dirs()
    now = datetime.now(UTC)
    manifest = PaperManifest(
        paper_id=paper_id,
        status=PaperRunStatus.completed,
        current_stage=PaperRunStage.completed,
        created_at=now,
        updated_at=now,
        finished_at=now,
    )
    paths.manifest.write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")
    return paths


def _write_json(path, payload: object) -> None:  # noqa: ANN001
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_dev_server_has_frontend_auth_stubs(tmp_path) -> None:
    client = TestClient(create_app(uploads_dir=tmp_path, auto_run=False))

    assert client.get("/settings/public").json() == {
        "turnstile_enabled": False,
        "turnstile_site_key": "",
    }
    login = client.post("/auth/secure-login", json={"username": "demo"}).json()
    assert login["access_token"]
    assert login["token_type"] == "bearer"
    assert client.get("/auth/me").json()["role"] == "admin"
    assert client.get("/wsi/my-grants").json()["elevated_dataset_ids"] == []
    assert client.get("/auth/maintenance-notice").json()["active"] is False


def test_dev_server_get_paper_includes_validation_summary(tmp_path) -> None:
    client = TestClient(create_app(uploads_dir=tmp_path, auto_run=False))
    paths = _make_run("paper_dev_validation_summary")
    _write_json(
        paths.validation_dir / "metric_guard.json",
        {
            "guard": "metric_guard",
            "status": "fail",
            "issues": [
                {
                    "code": "raw_metric",
                    "message": "Raw metric found.",
                    "severity": "error",
                    "path": "drafts/sections/results.tex",
                },
                {
                    "code": "rounding",
                    "message": "Rounded value detected.",
                    "severity": "warning",
                },
            ],
        },
    )
    _write_json(
        paths.validation_dir / "citation_guard.json",
        {"guard": "citation_guard", "status": "pass", "issues": []},
    )
    _write_json(
        paths.validation_dir / "refinement_log.json",
        {
            "max_iterations": 3,
            "initial_score": {"total": 10},
            "iterations": [{"iteration": 1, "score": {"total": 17}, "accepted": True}],
            "accepted_iterations": [1],
            "final_status": "accepted",
        },
    )
    (paths.validation_dir / "warnings.md").write_text("# Validation Warnings\n", encoding="utf-8")

    response = client.get("/papers/paper_dev_validation_summary")

    assert response.status_code == 200, response.text
    summary = response.json()["validation_summary"]
    assert summary["warnings_md_path"] == "validation/warnings.md"
    assert summary["hybrid_score"] == 17.0
    assert summary["refinement"]["final_status"] == "accepted"
    by_guard = {item["guard"]: item for item in summary["m10_guards"]}
    assert by_guard["metric_guard"]["status"] == "fail"
    assert by_guard["metric_guard"]["issue_count"] == 2
    assert by_guard["metric_guard"]["error_count"] == 1
    assert by_guard["metric_guard"]["warning_count"] == 1
    assert by_guard["metric_guard"]["sample_issues"][0]["code"] == "raw_metric"
    assert by_guard["citation_guard"]["status"] == "pass"


def test_dev_server_get_sections_returns_registered_public_section_text(tmp_path) -> None:
    client = TestClient(create_app(uploads_dir=tmp_path, auto_run=False))
    paths = _make_run("paper_dev_sections")
    paths.sections_dir.mkdir(parents=True, exist_ok=True)
    (paths.sections_dir / "abstract.tex").write_text("\\section{Abstract}\nA short abstract.\n", encoding="utf-8")
    (paths.sections_dir / "results.tex").write_text("\\section{Results}\nStrong results.\n", encoding="utf-8")
    (paths.sections_dir / "discussion.tex").write_text("\\section{Discussion}\nUnregistered text.\n", encoding="utf-8")
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    manifest["artifact_index"] = {
        "drafts/sections/abstract.tex": {
            "status": "ready",
            "visibility": "public",
            "downloadable": True,
            "content_type": "text/x-tex",
        },
        "drafts/sections/results.tex": {
            "status": "ready",
            "visibility": "public",
            "downloadable": True,
            "content_type": "text/x-tex",
        },
        "drafts/sections/discussion.tex": {
            "status": "ready",
            "visibility": "private",
            "downloadable": True,
            "content_type": "text/x-tex",
        },
    }
    paths.manifest.write_text(json.dumps(manifest), encoding="utf-8")

    response = client.get("/papers/paper_dev_sections/sections")

    assert response.status_code == 200, response.text
    sections = response.json()["sections"]
    assert [item["section_name"] for item in sections] == ["abstract", "results"]
    assert sections[0]["path"] == "drafts/sections/abstract.tex"
    assert sections[0]["text"] == "\\section{Abstract}\nA short abstract.\n"
    assert len(sections[0]["content_hash"]) == 64


def test_dev_server_put_section_replaces_text(tmp_path) -> None:
    client = TestClient(create_app(uploads_dir=tmp_path, auto_run=False))
    paths = _make_run("paper_dev_section_edit")
    original = "\\section{Results}\nOriginal dev results.\n"
    updated = "\\section{Results}\nEdited dev results.\n"
    paths.sections_dir.mkdir(parents=True, exist_ok=True)
    (paths.sections_dir / "results.tex").write_text(original, encoding="utf-8")
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    manifest["artifact_index"] = {
        "drafts/sections/results.tex": {
            "status": "ready",
            "visibility": "public",
            "downloadable": True,
            "content_type": "text/x-tex",
        },
        "final/miccai/main.pdf": {
            "status": "ready",
            "visibility": "public",
            "downloadable": True,
            "content_type": "application/pdf",
        },
    }
    paths.manifest.write_text(json.dumps(manifest), encoding="utf-8")

    response = client.put(
        "/papers/paper_dev_section_edit/sections/results",
        json={"text": updated, "source_hash": f"sha256:{sections_hash(original)}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["section"]["text"] == updated
    assert body["downstream_stale"] is True
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert manifest["artifact_index"]["final/miccai/main.pdf"]["stale"] is True


def test_dev_server_post_render_export_queues_background(tmp_path, monkeypatch) -> None:
    from pathlab_paper_agent import dev_server

    called: list[tuple[str, str]] = []
    monkeypatch.setattr(
        dev_server,
        "_run_render_export_for_dev",
        lambda paper_id, uploads_dir: called.append((paper_id, str(uploads_dir))),
    )
    client = TestClient(dev_server.create_app(uploads_dir=tmp_path, auto_run=False))
    paths = _make_run("paper_dev_render_export")
    paths.sections_dir.mkdir(parents=True, exist_ok=True)
    (paths.sections_dir / "results.tex").write_text("\\section{Results}\nEdited dev results.\n", encoding="utf-8")

    response = client.post("/papers/paper_dev_render_export/render-export")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"
    assert response.json()["current_stage"] == "rendering"
    assert called == [("paper_dev_render_export", str(tmp_path))]
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert manifest["status"] == "running"
    assert manifest["current_stage"] == "rendering"


def sections_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
