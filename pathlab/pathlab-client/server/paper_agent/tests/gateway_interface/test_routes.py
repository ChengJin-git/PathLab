"""End-to-end route tests using FastAPI TestClient."""

from __future__ import annotations

import hashlib
import json

import pytest

from backend.database.repositories.paper_generation import PaperGenerationRunRepository
from pathlab_paper_agent.schemas import PaperRunStage, PaperRunStatus
from pathlab_paper_agent.storage import PaperRunPaths


def _valid_outline() -> dict:
    return {
        "plotting_plan": [
            {
                "figure_id": "fig:main",
                "kind": "empirical",
                "source": "experimental_log",
                "design_objective": "Summarize the primary finding.",
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
                "goal": "Describe the cohort, model, and evaluation.",
                "evidence_inputs": ["evidence_public"],
                "citation_hints": ["whole slide image classification"],
                "locked_block_inputs": ["locked_blocks/method_block.tex"],
            }
        ],
        "pathlab_extensions": {
            "templates": ["miccai"],
            "claim_plan": [{"claim": "Primary endpoint improved."}],
            "table_plan": [],
            "guard_requirements": ["metric", "identifier"],
            "template_styles": [{"template_id": "miccai"}],
        },
    }


async def _mark_awaiting_outline(db_session, paper_id: str) -> None:
    await PaperGenerationRunRepository.update(
        db_session,
        paper_id,
        status=PaperRunStatus.awaiting_outline_approval.value,
        current_stage=PaperRunStage.outlining.value,
        error_message=None,
        finished_at=None,
    )
    await db_session.commit()
    paths = PaperRunPaths.for_paper(paper_id)
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    manifest["status"] = PaperRunStatus.awaiting_outline_approval.value
    manifest["current_stage"] = PaperRunStage.outlining.value
    manifest["finished_at"] = None
    paths.manifest.write_text(json.dumps(manifest), encoding="utf-8")


def _register_artifact(
    paths: PaperRunPaths,
    rel_path: str,
    content: str | bytes,
    *,
    status: str = "ready",
    visibility: str = "public",
    downloadable: bool = True,
    label: str | None = None,
    content_type: str | None = None,
) -> None:
    target = paths.root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    artifact = {
        "status": status,
        "visibility": visibility,
        "downloadable": downloadable,
    }
    if label is not None:
        artifact["label"] = label
    if content_type is not None:
        artifact["content_type"] = content_type
    manifest["artifact_index"][rel_path] = artifact
    paths.manifest.write_text(json.dumps(manifest), encoding="utf-8")


def _register_public_section(paths: PaperRunPaths, section_name: str, text: str) -> None:
    _register_artifact(
        paths,
        f"drafts/sections/{section_name}.tex",
        text,
        label=f"Section: {section_name.replace('_', ' ').title()}",
        content_type="text/x-tex",
    )


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
    assert body["validation_summary"] == {
        "m10_guards": [],
        "refinement": None,
        "hybrid_score": None,
        "warnings_md_path": None,
    }
    assert body["stage_log"][0]["status"] == "completed"
    assert body["stage_log"][0]["duration_ms"] == 0


@pytest.mark.asyncio
async def test_put_outline_save_only_response_shape(client, db_session, monkeypatch) -> None:
    from pathlab_paper_agent.api import routes as api_routes
    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "paper_dev_source"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    await _mark_awaiting_outline(db_session, paper_id)

    async def _unexpected_enqueue(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("save-only outline edit must not enqueue Job B")

    monkeypatch.setattr(api_routes, "_enqueue_paper_generation_job", _unexpected_enqueue)
    outline = _valid_outline()
    outline["section_plan"][0]["goal"] = "Updated goal from the user."
    response = client.put(
        f"/papers/{paper_id}/outline",
        json={"outline": outline, "approve": False},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "paper_id": paper_id,
        "approved": False,
        "current_stage": "outlining",
    }
    saved = json.loads(PaperRunPaths.for_paper(paper_id).outline_json.read_text())
    assert saved["section_plan"][0]["goal"] == "Updated goal from the user."
    detail = client.get(f"/papers/{paper_id}").json()
    assert detail["status"] == "awaiting_outline_approval"
    assert detail["current_stage"] == "outlining"


@pytest.mark.asyncio
async def test_put_outline_approve_enqueues_job_b_and_logs(client, db_session, monkeypatch) -> None:
    from pathlab_paper_agent.api import routes as api_routes
    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "paper_dev_source"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    await _mark_awaiting_outline(db_session, paper_id)

    enqueued: list[tuple[str, str]] = []

    async def _capture_enqueue(paper_id_arg: str, handler: str):
        enqueued.append((paper_id_arg, handler))
        return {"paper_id": paper_id_arg, "handler": handler}

    monkeypatch.setattr(api_routes, "_enqueue_paper_generation_job", _capture_enqueue)
    response = client.put(
        f"/papers/{paper_id}/outline",
        json={"outline": _valid_outline(), "approve": True},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "paper_id": paper_id,
        "approved": True,
        "current_stage": "plotting",
    }
    assert enqueued == [(paper_id, "paper_generation.run_after_outline")]
    detail = client.get(f"/papers/{paper_id}").json()
    assert detail["status"] == "running"
    assert detail["current_stage"] == "plotting"
    assert detail["stage_log"][-1]["status"] == "approved"
    assert detail["stage_log"][-1]["message"] == "Outline approved by user."


@pytest.mark.asyncio
async def test_put_outline_invalid_body_returns_422(client, db_session) -> None:
    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "paper_dev_source"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    await _mark_awaiting_outline(db_session, paper_id)

    response = client.put(
        f"/papers/{paper_id}/outline",
        json={"outline": {"plotting_plan": []}, "approve": False},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_outline_forbidden_for_non_owner(
    client,
    test_app,
    db_session,
    other_user,
) -> None:
    from backend.auth import current_active_user

    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "paper_dev_source"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    await _mark_awaiting_outline(db_session, paper_id)
    test_app.dependency_overrides[current_active_user] = lambda: other_user

    response = client.put(
        f"/papers/{paper_id}/outline",
        json={"outline": _valid_outline(), "approve": False},
    )

    assert response.status_code == 403


def test_get_paper_returns_validation_summary_from_reports(client) -> None:
    create = client.post(
        "/papers",
        json={
            "title": "Validation summary",
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    paths = PaperRunPaths.for_paper(paper_id)
    paths.validation_dir.mkdir(parents=True, exist_ok=True)
    (paths.validation_dir / "metric_guard.json").write_text(
        json.dumps(
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
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )
    (paths.validation_dir / "citation_guard.json").write_text(
        json.dumps(
            {
                "guard": "citation_guard",
                "status": "pass",
                "issues": [],
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )
    (paths.validation_dir / "warnings.md").write_text("# Validation Warnings\n", encoding="utf-8")
    (paths.validation_dir / "refinement_log.json").write_text(
        json.dumps(
            {
                "max_iterations": 3,
                "initial_score": {"total": 10, "rubric_total": 10},
                "iterations": [
                    {
                        "iteration": 1,
                        "score": {"total": 17, "rubric_total": 17},
                        "accepted": True,
                    }
                ],
                "accepted_iterations": [1],
                "final_status": "accepted",
            }
        ),
        encoding="utf-8",
    )

    response = client.get(f"/papers/{paper_id}")

    assert response.status_code == 200, response.text
    summary = response.json()["validation_summary"]
    assert summary["warnings_md_path"] == "validation/warnings.md"
    assert summary["hybrid_score"] == 17.0
    assert summary["refinement"]["final_status"] == "accepted"
    assert summary["refinement"]["iteration_count"] == 1
    assert summary["refinement"]["accepted_iterations"] == [1]
    by_guard = {item["guard"]: item for item in summary["m10_guards"]}
    assert by_guard["metric_guard"]["status"] == "fail"
    assert by_guard["metric_guard"]["issue_count"] == 2
    assert by_guard["metric_guard"]["error_count"] == 1
    assert by_guard["metric_guard"]["warning_count"] == 1
    assert by_guard["metric_guard"]["sample_issues"][0]["code"] == "raw_metric"
    assert by_guard["citation_guard"]["status"] == "pass"


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

    def fake_regenerate(paper_id_arg: str, section_name_arg: str, **kwargs):
        assert paper_id_arg == paper_id
        assert section_name_arg == "results"
        assert kwargs["mode"] == "section"
        manifest = api_routes._load_manifest(paths)
        assert manifest is not None
        return manifest

    monkeypatch.setattr(api_routes, "regenerate_section", fake_regenerate)
    monkeypatch.setattr(
        api_routes,
        "latest_regenerate_log_summary",
        lambda paper_id_arg: {
            "regen_id": "reg_sync",
            "regenerated_sections": ["results"],
            "refinement_log_summary": {"final_status": "accepted"},
        },
    )

    response = client.post(f"/papers/{paper_id}/sections/results/regenerate?sync=true")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "paper_id": paper_id,
        "status": "pending",
        "current_stage": "created",
        "regen_id": "reg_sync",
        "regenerated_sections": ["results"],
        "refinement_log_summary": {"final_status": "accepted"},
    }


def test_post_regenerate_async_returns_202_and_manifest_job(client, monkeypatch) -> None:
    from pathlab_paper_agent.api import routes as api_routes

    captured = []

    async def fake_enqueue(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(api_routes, "_enqueue_regenerate_descriptor", fake_enqueue)
    create = client.post(
        "/papers",
        json={
            "title": "Regenerate async",
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]

    response = client.post(
        f"/papers/{paper_id}/sections/results/regenerate",
        json={
            "mode": "selection",
            "selected_text": "A sufficiently long selected sentence from the PDF.",
            "source_hash": "abc",
            "target_paragraph": 0,
            "user_note": "Make it cautious.",
            "template_id": "miccai",
        },
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["paper_id"] == paper_id
    assert body["regen_id"].startswith("reg_")
    assert captured[0]["paper_id"] == paper_id
    assert captured[0]["section_name"] == "results"
    manifest = json.loads(PaperRunPaths.for_paper(paper_id).manifest.read_text(encoding="utf-8"))
    job = manifest["regenerate_jobs"][-1]
    assert job["regen_id"] == body["regen_id"]
    assert job["status"] == "queued"
    assert job["mode"] == "selection"


def test_get_and_cancel_regenerate_job_routes(client, monkeypatch) -> None:
    from pathlab_paper_agent.api import routes as api_routes

    async def fake_enqueue(**kwargs):
        del kwargs

    monkeypatch.setattr(api_routes, "_enqueue_regenerate_descriptor", fake_enqueue)
    create = client.post(
        "/papers",
        json={
            "title": "Regenerate poll",
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    accepted = client.post(f"/papers/{paper_id}/sections/results/regenerate", json={}).json()
    regen_id = accepted["regen_id"]

    get_response = client.get(f"/papers/{paper_id}/regen/{regen_id}")
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["regen_id"] == regen_id
    assert get_response.json()["status"] == "queued"

    cancel_response = client.post(f"/papers/{paper_id}/regen/{regen_id}:cancel")
    assert cancel_response.status_code == 200, cancel_response.text
    assert cancel_response.json() == {"regen_id": regen_id, "status": "cancelled"}


def test_reject_regenerate_job_route(client, monkeypatch) -> None:
    from pathlab_paper_agent.api import routes as api_routes

    captured = {}

    def fake_reject(paper_id_arg: str, regen_id_arg: str, **kwargs):
        captured.update({"paper_id": paper_id_arg, "regen_id": regen_id_arg, **kwargs})
        return None, {
            "regen_id": regen_id_arg,
            "status": "rejected",
            "restored_sections": ["results"],
            "final_pdf_path": "final/miccai/main.pdf",
        }

    monkeypatch.setattr(api_routes, "reject_regenerate", fake_reject)
    create = client.post(
        "/papers",
        json={
            "title": "Regenerate reject",
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]

    response = client.post(
        f"/papers/{paper_id}/regen/reg_reject:reject",
        json={"reason": "Keep the previous wording.", "template_id": "miccai"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "regen_id": "reg_reject",
        "status": "rejected",
        "restored_sections": ["results"],
        "final_pdf_path": "final/miccai/main.pdf",
    }
    assert captured["paper_id"] == paper_id
    assert captured["regen_id"] == "reg_reject"
    assert captured["reason"] == "Keep the previous wording."
    assert captured["template_id"].value == "miccai"


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


@pytest.mark.parametrize(
    ("rel_path", "content", "content_type"),
    [
        ("drafts/outline.json", b'{"plotting_plan":[]}', "application/json"),
        ("figures/manifest.json", b'{"figures":[]}', "application/json"),
        ("validation/warnings.md", b"# Validation Warnings\n", "text/markdown"),
        ("final/miccai/main.pdf", b"%PDF-1.4\n", "application/pdf"),
        ("exports/miccai_bundle.zip", b"PK\x03\x04", "application/zip"),
    ],
)
def test_get_files_returns_frontend_public_surfaces_when_registered(
    client,
    rel_path: str,
    content: bytes,
    content_type: str,
) -> None:
    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    paths = PaperRunPaths.for_paper(paper_id)
    _register_artifact(
        paths,
        rel_path,
        content,
        label=rel_path,
        content_type=content_type,
    )

    response = client.get(f"/papers/{paper_id}/files", params={"path": rel_path})

    assert response.status_code == 200, response.text
    assert response.content == content


def test_get_files_blocks_unregistered_allowlisted_file(client) -> None:
    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    paths = PaperRunPaths.for_paper(paper_id)
    target = paths.figures_dir / "unregistered.png"
    target.write_bytes(b"PNG")

    response = client.get(
        f"/papers/{paper_id}/files",
        params={"path": "figures/unregistered.png"},
    )

    assert response.status_code == 403


def test_get_files_blocks_private_manifest_entry_under_allowed_prefix(client) -> None:
    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    paths = PaperRunPaths.for_paper(paper_id)
    _register_artifact(
        paths,
        "figures/private_diagnostic.png",
        b"PNG",
        visibility="private_backend_only",
        downloadable=False,
        content_type="image/png",
    )

    response = client.get(
        f"/papers/{paper_id}/files",
        params={"path": "figures/private_diagnostic.png"},
    )

    assert response.status_code == 403


def test_get_files_blocks_guard_json_even_if_manifest_marks_public(client) -> None:
    create = client.post(
        "/papers",
        json={
            "source_tasks": [{"task_id": "tsk_x"}],
            "selected_templates": ["miccai"],
        },
    )
    paper_id = create.json()["paper_id"]
    paths = PaperRunPaths.for_paper(paper_id)
    _register_artifact(
        paths,
        "validation/metric_guard.json",
        b'{"guard":"metric_guard","issues":[]}',
        content_type="application/json",
    )

    response = client.get(
        f"/papers/{paper_id}/files",
        params={"path": "validation/metric_guard.json"},
    )

    assert response.status_code == 403


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
