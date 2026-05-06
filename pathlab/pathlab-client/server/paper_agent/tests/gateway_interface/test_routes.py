"""End-to-end route tests using FastAPI TestClient."""

from __future__ import annotations

import hashlib
import json

from pathlab_paper_agent.storage import PaperRunPaths


def _register_public_section(paths: PaperRunPaths, section_name: str, text: str) -> None:
    target = paths.sections_dir / f"{section_name}.tex"
    target.write_text(text, encoding="utf-8")
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    manifest["artifact_index"][f"drafts/sections/{section_name}.tex"] = {
        "status": "ready",
        "visibility": "public",
        "downloadable": True,
        "label": f"Section: {section_name.replace('_', ' ').title()}",
        "content_type": "text/x-tex",
    }
    paths.manifest.write_text(json.dumps(manifest), encoding="utf-8")


def test_post_papers_creates_run(client) -> None:
    response = client.post(
        "/papers",
        json={
            "title": "Demo paper",
            "source_tasks": [{"task_id": "tsk_main", "role": "main"}],
            "selected_templates": ["miccai"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["paper_id"].startswith("paper_")
    assert body["status"] == "pending"


def test_post_papers_rejects_empty_source_tasks(client) -> None:
    response = client.post(
        "/papers",
        json={
            "source_tasks": [],
            "selected_templates": ["miccai"],
        },
    )
    assert response.status_code == 400


def test_post_papers_rejects_empty_templates(client) -> None:
    response = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": [],
        },
    )
    assert response.status_code == 400


def test_post_papers_rejects_multiple_templates(client) -> None:
    response = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai", "nature_scientific_reports"],
        },
    )
    assert response.status_code == 400
    assert "exactly one" in response.json()["detail"]


def test_post_papers_writes_scaffold_to_disk(client) -> None:
    response = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    body = response.json()
    paper_id = body["paper_id"]
    paths = PaperRunPaths.for_paper(paper_id)
    assert paths.root.is_dir()
    assert paths.manifest.is_file()
    assert paths.config.is_file()


def test_get_papers_lists_runs(client) -> None:
    # Create two runs
    for title in ["First", "Second"]:
        client.post(
            "/papers",
            json={
                "title": title,
                "source_tasks": [{"task_id": "tsk_x"}],
                "selected_templates": ["miccai"],
            },
        )
    response = client.get("/papers")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_get_paper_returns_summary(client) -> None:
    create = client.post(
        "/papers",
        json={
            "title": "Detail",
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["nature_scientific_reports"],
        },
    )
    paper_id = create.json()["paper_id"]

    response = client.get(f"/papers/{paper_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["paper_id"] == paper_id
    assert body["title"] == "Detail"
    assert body["selected_templates"] == ["nature_scientific_reports"]


def test_get_paper_404_when_missing(client) -> None:
    response = client.get("/papers/paper_doesnotexist")
    assert response.status_code == 404


def test_get_paper_sections_returns_registered_public_section_text(client) -> None:
    create = client.post(
        "/papers",
        json={
            "title": "Section detail",
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    paths = PaperRunPaths.for_paper(paper_id)
    text = "\\section{Results}\nThe model reached the locked test metric.\n"
    _register_public_section(paths, "results", text)

    response = client.get(f"/papers/{paper_id}/sections")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sections"] == [
        {
            "section_name": "results",
            "path": "drafts/sections/results.tex",
            "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "text": text,
            "editable": True,
            "updated_at": body["sections"][0]["updated_at"],
        }
    ]


def test_post_regenerate_section_official_route_returns_summary(
    client,
    monkeypatch,
) -> None:
    from pathlab_paper_agent.api import routes as api_routes

    create = client.post(
        "/papers",
        json={
            "title": "Regenerate",
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    paths = PaperRunPaths.for_paper(paper_id)

    def fake_regenerate(paper_id_arg: str, section_name_arg: str):
        assert paper_id_arg == paper_id
        assert section_name_arg == "results"
        manifest = api_routes._load_manifest(paths)
        assert manifest is not None
        return manifest

    monkeypatch.setattr(api_routes, "regenerate_section", fake_regenerate)
    monkeypatch.setattr(
        api_routes,
        "latest_regenerate_log_summary",
        lambda paper_id_arg: {
            "regenerated_sections": ["results"],
            "refinement_log_summary": {"final_status": "accepted"},
        },
    )

    response = client.post(f"/papers/{paper_id}/sections/results/regenerate")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "paper_id": paper_id,
        "status": "pending",
        "current_stage": "created",
        "regenerated_sections": ["results"],
        "refinement_log_summary": {"final_status": "accepted"},
    }


def test_delete_paper_removes_db_and_disk(client) -> None:
    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    paths = PaperRunPaths.for_paper(paper_id)
    assert paths.root.is_dir()

    delete = client.delete(f"/papers/{paper_id}")
    assert delete.status_code == 200

    # Both DB and disk gone
    follow = client.get(f"/papers/{paper_id}")
    assert follow.status_code == 404
    assert not paths.root.exists()


def test_get_files_returns_manifest(client) -> None:
    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]

    response = client.get(f"/papers/{paper_id}/files/manifest.json")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["paper_id"] == paper_id


def test_get_files_blocks_evidence_lock_private(client) -> None:
    """§3.7: evidence_lock.private.json must NEVER be downloadable."""
    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    paths = PaperRunPaths.for_paper(paper_id)
    paths.evidence_lock_private.write_text("{\"secret\": true}", encoding="utf-8")

    response = client.get(
        f"/papers/{paper_id}/files/evidence/evidence_lock.private.json"
    )
    assert response.status_code == 403


def test_get_files_blocks_intro_rw_draft(client) -> None:
    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    paths = PaperRunPaths.for_paper(paper_id)
    (paths.intro_rw_draft_dir / "introduction.tex").write_text("DRAFT", encoding="utf-8")

    response = client.get(
        f"/papers/{paper_id}/files/drafts/intro_rw_draft/introduction.tex"
    )
    assert response.status_code == 403


def test_get_files_blocks_path_traversal(client) -> None:
    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]

    # Allowlisted prefix tables/, but with traversal
    response = client.get(
        f"/papers/{paper_id}/files/tables/../../../etc/passwd"
    )
    # Multiple defense layers can reject this:
    #   - 404: Starlette URL normalization (no route match after `..` collapse)
    #   - 403: allowlist
    #   - 400: safe_resolve raises ValueError (wrapped to 400)
    # All acceptable; never 200.
    assert response.status_code in (400, 403, 404)
    # Defense check: NEVER 200 (means we'd have served /etc/passwd or worse).
    assert response.status_code != 200


def test_get_files_404_when_file_missing(client) -> None:
    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]

    # tables/ is allowlisted, but no file exists
    response = client.get(f"/papers/{paper_id}/files/tables/never_made.tex")
    assert response.status_code in (403, 404)


def test_get_files_returns_404_for_unknown_paper(client) -> None:
    response = client.get("/papers/paper_nopaper/files/manifest.json")
    assert response.status_code == 404


def test_get_files_blocks_evidence_lock_for_existing_paper_via_traversal(
    client,
) -> None:
    """Defense-in-depth: even if files/{path} parsing tried to construct
    a private-evidence path via traversal, allowlist + safe_resolve must
    still reject it."""
    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]

    # User tries to reach evidence/evidence_lock.private.json via tables/..
    response = client.get(
        f"/papers/{paper_id}/files/tables/../evidence/evidence_lock.private.json"
    )
    assert response.status_code in (400, 403)
