from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pathlab_paper_agent import regenerate as regenerate_mod
from pathlab_paper_agent.agents.content_refinement_agent import ContentRefinementAgent, RUBRIC_DIMENSIONS
from pathlab_paper_agent.agents.section_writing_agent import SectionWritingResult
from pathlab_paper_agent.dev_server import create_app
from pathlab_paper_agent.llm import LLMResponse
from pathlab_paper_agent.pipeline import create_dev_run, load_manifest, save_manifest
from pathlab_paper_agent.regenerate import cancel_regenerate, get_regenerate_job, reject_regenerate, regenerate_section
from pathlab_paper_agent.schemas import CreatePaperRequest, SourceTaskRef
from pathlab_paper_agent.selection_locator import SelectionLocatorError, section_content_hash
from pathlab_paper_agent.stages.common import register_artifact, write_json

_SECTION_ORDER = (
    "abstract",
    "introduction",
    "related_work",
    "methods",
    "experiments",
    "results",
    "discussion",
    "conclusion",
)


class StubSectionAgent:
    def __init__(self, sections: dict[str, str]) -> None:
        self.sections = sections

    def generate(self, _inputs) -> SectionWritingResult:
        return SectionWritingResult(
            sections=dict(self.sections),
            raw_sections=dict(self.sections),
            used_citations=(),
        )


class MockRefinementLLM:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)

    def complete(
        self,
        messages,
        *,
        temperature: float = 0.2,
        response_format=None,
        stream=None,
    ) -> LLMResponse:
        del messages, temperature, response_format, stream
        return LLMResponse(
            content=json.dumps(self.responses.pop(0)),
            model="mock-refinement",
            provider="mock",
        )


class StubSelectionRewriteAgent:
    def __init__(self, replacement: str) -> None:
        self.replacement = replacement
        self.inputs = None

    def rewrite(self, inputs):
        from pathlab_paper_agent.agents.selection_rewrite_agent import SelectionRewriteResult

        self.inputs = inputs
        return SelectionRewriteResult(replacement_text=self.replacement, rationale="test replacement")


def _critic(score: int = 3) -> dict:
    return {
        "rubric": {
            dimension: {"score": score, "reason": "mock review"}
            for dimension in RUBRIC_DIMENSIONS
        },
        "overall": {"score": score * len(RUBRIC_DIMENSIONS), "reason": "mock overall"},
        "revise_sections": ["results"],
        "actionable_feedback": ["Keep the regenerated section evidence bounded."],
    }


def _raw_cite_revision() -> dict:
    return {
        "worklog": {"actions_taken": ["introduced a bad raw citation"]},
        "sections": {
            "results": (
                "\\section{Results}\n"
                "This rejected revision uses a raw citation \\cite{Ghost2026}.\n"
            )
        },
    }


def _non_target_raw_cite_revision() -> dict:
    return {
        "worklog": {"actions_taken": ["attempted to rewrite a locked section"]},
        "sections": {
            "discussion": (
                "\\section{Discussion}\n"
                "This non-target revision uses a raw citation \\cite{Ghost2026}.\n"
            )
        },
    }


async def _setup_run(tmp_path: Path, paper_id: str):
    request = CreatePaperRequest(
        title="M12b Regenerate Fixture",
        source_tasks=[SourceTaskRef(task_id="main_task")],
    )
    _paper_id, paths = await create_dev_run(request, paper_id=paper_id, uploads_dir=tmp_path)
    paths.outline_json.write_text(
        json.dumps(
            {
                "section_plan": [
                    {"section": "Abstract"},
                    {"section": "Introduction"},
                    {"section": "Related Work"},
                    {"section": "Methods"},
                    {"section": "Experimental Setup"},
                    {"section": "Results"},
                    {"section": "Discussion"},
                    {"section": "Conclusion"},
                ]
            }
        ),
        encoding="utf-8",
    )
    paths.evidence_lock_private.write_text(
        json.dumps(
            {
                "source_tasks": [{"task_id": "main_task", "role": "main"}],
                "external_validation": [],
                "metrics": {
                    "main.metrics.test_accuracy": {
                        "formatted": "0.9123",
                        "value": 0.9123,
                        "role": "main",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    paths.experimental_log.write_text(
        "# Experimental Log\n\nMetrics are referenced only through locked evidence.\n",
        encoding="utf-8",
    )
    paths.idea.write_text("# Idea\nRegenerate a single section.\n", encoding="utf-8")
    paths.refs_bib.write_text("", encoding="utf-8")
    (paths.citations_dir / "selected_refs.json").write_text(json.dumps({"items": []}), encoding="utf-8")
    (paths.citations_dir / "required_cites.json").write_text(json.dumps({"items": []}), encoding="utf-8")
    paths.figures_manifest.write_text(json.dumps({"figures": []}), encoding="utf-8")
    for name in ("method_block", "dataset_block", "results_block", "evidence_gaps", "metrics_macros"):
        (paths.locked_blocks_dir / f"{name}.tex").write_text(f"% locked {name}\n", encoding="utf-8")
    (paths.tables_dir / "table_2_main_results.tex").write_text(
        "\\begin{tabular}{ll}Metric & Value\\\\\\end{tabular}\n",
        encoding="utf-8",
    )
    for section in _SECTION_ORDER:
        text = f"\\section{{{section.replace('_', ' ').title()}}}\nOriginal {section} text.\n"
        if section == "results":
            text = "\\section{Results}\nOriginal results report the test set metric 0.9123.\n"
        (paths.sections_dir / f"{section}.tex").write_text(text, encoding="utf-8")
    return paths


def _candidate_sections(paths) -> dict[str, str]:
    sections = {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(paths.sections_dir.glob("*.tex"))
        if path.is_file()
    }
    sections["results"] = "\\section{Results}\nRegenerated results report the test set metric 0.9123.\n"
    return sections


def _patch_section_agent(monkeypatch: pytest.MonkeyPatch, sections: dict[str, str]) -> None:
    monkeypatch.setattr(regenerate_mod, "SectionWritingAgent", lambda: StubSectionAgent(sections))


def _patch_accepting_refinement(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_refining(paths, manifest, *, agent=None, max_iterations=3, guard_runner=None, snapshots_subdir=None):
        del agent, max_iterations, guard_runner
        assert snapshots_subdir is not None
        snapshot_dir = snapshots_subdir / "iter_1" / "sections"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(paths.sections_dir.glob("*.tex")):
            shutil.copy2(path, snapshot_dir / path.name)
        (paths.sections_dir / "results.tex").write_text(
            "\\section{Results}\nRefined regenerated results report the test set metric 0.9123.\n",
            encoding="utf-8",
        )
        (paths.sections_dir / "discussion.tex").write_text(
            "\\section{Discussion}\nThis illegal touch must be restored by M12b.\n",
            encoding="utf-8",
        )
        write_json(
            paths.validation_dir / "refinement_log.json",
            {
                "final_status": "accepted",
                "accepted_iterations": [1],
                "iterations": [
                    {
                        "iteration": 1,
                        "accepted": True,
                        "revision": {"changed_sections": ["discussion", "results"]},
                    }
                ],
                "initial_score": {"total": 15},
            },
        )
        register_artifact(
            manifest,
            "validation/refinement_log.json",
            visibility="private_backend_only",
            downloadable=False,
            label="Refinement log",
            content_type="application/json",
        )

    monkeypatch.setattr(regenerate_mod, "run_refining", fake_run_refining)


def _latest_log(paths) -> dict:
    logs = sorted((paths.drafts_dir / "regenerate_runs").glob("*/log.json"))
    assert logs
    return json.loads(logs[-1].read_text(encoding="utf-8"))


def _section_bytes(paths) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(paths.sections_dir.glob("*.tex"))}


@pytest.mark.asyncio
async def test_regenerate_happy_path_changes_only_requested_section_and_keeps_before_snapshot(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = await _setup_run(tmp_path, "paper_regenerate_happy")
    before = _section_bytes(paths)
    _patch_section_agent(monkeypatch, _candidate_sections(paths))
    _patch_accepting_refinement(monkeypatch)

    manifest = regenerate_section(paths.paper_id, "results", uploads_dir=tmp_path)

    after = _section_bytes(paths)
    assert after["results.tex"] != before["results.tex"]
    for name, payload in before.items():
        if name != "results.tex":
            assert after[name] == payload
    assert "Refined regenerated results" in (paths.sections_dir / "results.tex").read_text(encoding="utf-8")
    log = _latest_log(paths)
    before_dir = paths.root / log["before_dir"]
    assert (before_dir / "results.tex").read_bytes() == before["results.tex"]
    assert log["status"] == "accepted"
    assert manifest.artifact_index[f"drafts/regenerate_runs/{log['run_id']}/log.json"]["visibility"] == (
        "private_backend_only"
    )


@pytest.mark.asyncio
async def test_regenerate_restores_locked_section_mtimes_after_refinement_touches_them(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = await _setup_run(tmp_path, "paper_regenerate_mtime_lock")
    watched = ["methods.tex", "discussion.tex", "conclusion.tex"]
    before_mtimes = {name: (paths.sections_dir / name).stat().st_mtime_ns for name in watched}
    _patch_section_agent(monkeypatch, _candidate_sections(paths))
    _patch_accepting_refinement(monkeypatch)

    regenerate_section(paths.paper_id, "results", uploads_dir=tmp_path)

    after_mtimes = {name: (paths.sections_dir / name).stat().st_mtime_ns for name in watched}
    assert after_mtimes == before_mtimes


@pytest.mark.asyncio
async def test_regenerate_namespaces_refinement_snapshots_without_touching_existing_snapshots(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = await _setup_run(tmp_path, "paper_regenerate_snapshot_namespace")
    sentinel = paths.snapshots_dir / "iter_1" / "sections" / "foo.tex"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("original sentinel", encoding="utf-8")
    _patch_section_agent(monkeypatch, _candidate_sections(paths))
    _patch_accepting_refinement(monkeypatch)

    regenerate_section(paths.paper_id, "results", uploads_dir=tmp_path)

    assert sentinel.read_text(encoding="utf-8") == "original sentinel"
    log = _latest_log(paths)
    namespaced_snapshot = paths.root / log["snapshots_dir"] / "iter_1" / "sections" / "results.tex"
    assert namespaced_snapshot.is_file()
    assert not str(namespaced_snapshot).startswith(str(paths.snapshots_dir / "iter_1"))


@pytest.mark.asyncio
async def test_unknown_section_raises_value_error_and_endpoint_returns_422(tmp_path) -> None:
    paths = await _setup_run(tmp_path, "paper_regenerate_unknown")

    with pytest.raises(ValueError):
        regenerate_section(paths.paper_id, "nonexistent", uploads_dir=tmp_path)

    client = TestClient(create_app(uploads_dir=tmp_path))
    response = client.post(f"/papers/{paths.paper_id}/sections/nonexistent/regenerate")
    assert response.status_code == 422
    assert "Unknown section" in response.json()["detail"]


@pytest.mark.asyncio
async def test_force_reject_restores_sections_and_marks_manifest_rejected(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = await _setup_run(tmp_path, "paper_regenerate_force_reject")
    before = _section_bytes(paths)
    _patch_section_agent(monkeypatch, _candidate_sections(paths))
    monkeypatch.setattr(
        regenerate_mod,
        "ContentRefinementAgent",
        lambda: ContentRefinementAgent(MockRefinementLLM([_critic(3), _raw_cite_revision()])),
    )

    with pytest.raises(RuntimeError, match="refinement rejected"):
        regenerate_section(paths.paper_id, "results", uploads_dir=tmp_path)

    assert _section_bytes(paths) == before
    manifest_payload = json.loads(paths.manifest.read_text(encoding="utf-8"))
    log_paths = [
        path
        for path, artifact in manifest_payload["artifact_index"].items()
        if path.startswith("drafts/regenerate_runs/") and artifact.get("label") == "Section regenerate log"
    ]
    assert len(log_paths) == 1
    artifact = manifest_payload["artifact_index"][log_paths[0]]
    assert artifact["status"] == "rejected"
    assert artifact["visibility"] == "private_backend_only"
    assert artifact["downloadable"] is False
    log = json.loads((paths.root / log_paths[0]).read_text(encoding="utf-8"))
    assert log["restored_from_before"] is True
    assert log["regenerated_sections"] == []


@pytest.mark.asyncio
async def test_refinement_ignores_invalid_non_target_section_revisions(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = await _setup_run(tmp_path, "paper_regenerate_target_only_refinement")
    before = _section_bytes(paths)
    _patch_section_agent(monkeypatch, _candidate_sections(paths))
    monkeypatch.setattr(
        regenerate_mod,
        "ContentRefinementAgent",
        lambda: ContentRefinementAgent(
            MockRefinementLLM(
                [
                    _critic(3),
                    _non_target_raw_cite_revision(),
                    _critic(3),
                    {"worklog": {"actions_taken": []}, "sections": {}},
                    _critic(3),
                    {"worklog": {"actions_taken": []}, "sections": {}},
                    _critic(3),
                ]
            )
        ),
    )

    regenerate_section(paths.paper_id, "results", uploads_dir=tmp_path)

    after = _section_bytes(paths)
    assert after["results.tex"] != before["results.tex"]
    assert after["discussion.tex"] == before["discussion.tex"]
    log = _latest_log(paths)
    assert log["status"] == "accepted"
    assert log["refinement_log"]["iterations"][0]["revision"]["changed_sections"] == []
    assert log["refinement_log"]["iterations"][0]["revision"]["worklog"]["ignored_non_target_sections"] == [
        "discussion"
    ]


@pytest.mark.asyncio
async def test_candidate_guard_fail_log_preserves_rejected_candidate_reports(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = await _setup_run(tmp_path, "paper_regenerate_candidate_guard_fail")
    before = _section_bytes(paths)
    candidate = _candidate_sections(paths)
    candidate["results"] = "\\section{Results}\nThis bad candidate cites \\cite{Ghost2026}.\n"
    _patch_section_agent(monkeypatch, candidate)

    with pytest.raises(RuntimeError, match="validation rejected"):
        regenerate_section(paths.paper_id, "results", uploads_dir=tmp_path)

    assert _section_bytes(paths) == before
    log = _latest_log(paths)
    assert log["status"] == "rejected"
    citation_report = next(report for report in log["initial_guard_reports"] if report["guard"] == "citation_guard")
    assert citation_report["status"] == "fail"
    assert any(issue.get("context") == "Ghost2026" for issue in citation_report["issues"])
    final_citation_report = next(report for report in log["final_guard_reports"] if report["guard"] == "citation_guard")
    assert final_citation_report["status"] == "pass"


@pytest.mark.asyncio
async def test_endpoint_distinguishes_missing_section_draft_from_missing_paper(tmp_path) -> None:
    paths = await _setup_run(tmp_path, "paper_regenerate_missing_section_draft")
    (paths.sections_dir / "results.tex").unlink()
    client = TestClient(create_app(uploads_dir=tmp_path))

    response = client.post(f"/papers/{paths.paper_id}/sections/results/regenerate")

    assert response.status_code == 404
    assert "section draft missing" in response.json()["detail"]


@pytest.mark.asyncio
async def test_endpoint_smoke_returns_regenerated_section_summary(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = await _setup_run(tmp_path, "paper_regenerate_endpoint")
    _patch_section_agent(monkeypatch, _candidate_sections(paths))
    _patch_accepting_refinement(monkeypatch)
    client = TestClient(create_app(uploads_dir=tmp_path))

    response = client.post(f"/papers/{paths.paper_id}/sections/results/regenerate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["paper_id"] == paths.paper_id
    assert payload["regenerated_sections"] == ["results"]
    assert payload["refinement_log_summary"]["final_status"] == "accepted"


@pytest.mark.asyncio
async def test_regenerate_log_records_non_target_revisions_discarded(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Refinement claims it changed both results and discussion, but M12b restores
    # discussion from the before snapshot. The regenerate log must surface that
    # discrepancy so audits can explain why disk does not match the refinement_log.
    paths = await _setup_run(tmp_path, "paper_regenerate_audit_field")
    _patch_section_agent(monkeypatch, _candidate_sections(paths))
    _patch_accepting_refinement(monkeypatch)

    regenerate_section(paths.paper_id, "results", uploads_dir=tmp_path)

    log = _latest_log(paths)
    assert log["status"] == "accepted"
    assert log["regenerated_sections"] == ["results"]
    assert log["non_target_revisions_discarded"] == ["discussion"]


@pytest.mark.asyncio
async def test_selection_mode_only_modifies_selected_span_and_records_diff(tmp_path) -> None:
    paths = await _setup_run(tmp_path, "paper_regenerate_selection")
    before = _section_bytes(paths)
    original_results = (
        "\\section{Results}\n"
        "Opening context remains unchanged.\n\n"
        "Original results report the test set metric 0.9123.\n\n"
        "Closing interpretation remains unchanged.\n"
    )
    (paths.sections_dir / "results.tex").write_text(original_results, encoding="utf-8")
    rewrite_agent = StubSelectionRewriteAgent("The test-set result is described cautiously using locked evidence.")

    manifest = regenerate_section(
        paths.paper_id,
        "results",
        uploads_dir=tmp_path,
        regen_id="reg_selection",
        mode="selection",
        selected_text="Original results report the test set metric 0.9123.",
        source_hash=section_content_hash(original_results),
        user_note="Make it more cautious.",
        rewrite_agent=rewrite_agent,
    )

    after_text = (paths.sections_dir / "results.tex").read_text(encoding="utf-8")
    assert "Opening context remains unchanged." in after_text
    assert "Closing interpretation remains unchanged." in after_text
    assert "The test-set result is described cautiously" in after_text
    for name, payload in before.items():
        if name != "results.tex":
            assert (paths.sections_dir / name).read_bytes() == payload
    job = get_regenerate_job(paths.paper_id, "reg_selection", uploads_dir=tmp_path)
    assert job.status == "completed"
    assert job.mode == "selection"
    assert job.locator is not None
    assert job.before_path == "drafts/regenerate_runs/reg_selection/before/results.tex"
    assert job.after_path == "drafts/regenerate_runs/reg_selection/after/results.tex"
    assert job.diff_summary is not None
    assert job.diff_summary.paragraphs_changed == [1]
    assert job.export_bundle_path == "exports/miccai_bundle.zip"
    assert manifest.artifact_index[job.before_path]["visibility"] == "public"
    assert rewrite_agent.inputs.user_note == "Make it more cautious."


@pytest.mark.asyncio
async def test_paragraph_mode_preserves_non_target_paragraphs_byte_for_byte(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = await _setup_run(tmp_path, "paper_regenerate_paragraph")
    original_results = (
        "\\section{Results}\n"
        "Paragraph zero remains exactly the same.\n\n"
        "Paragraph one is the only paragraph to replace.\n\n"
        "Paragraph two remains exactly the same.\n"
    )
    candidate_results = (
        "\\section{Results}\n"
        "Paragraph zero from the candidate must be ignored.\n\n"
        "Replacement paragraph one uses cautious language.\n\n"
        "Paragraph two from the candidate must be ignored.\n"
    )
    (paths.sections_dir / "results.tex").write_text(original_results, encoding="utf-8")
    candidate = _candidate_sections(paths)
    candidate["results"] = candidate_results
    _patch_section_agent(monkeypatch, candidate)

    def fake_run_refining(paths_arg, manifest, *, agent=None, max_iterations=3, guard_runner=None, snapshots_subdir=None):
        del manifest, agent, max_iterations, guard_runner
        assert snapshots_subdir is not None
        write_json(
            paths_arg.validation_dir / "refinement_log.json",
            {"final_status": "accepted", "accepted_iterations": [], "iterations": [], "initial_score": {}},
        )

    monkeypatch.setattr(regenerate_mod, "run_refining", fake_run_refining)

    regenerate_section(
        paths.paper_id,
        "results",
        uploads_dir=tmp_path,
        regen_id="reg_paragraph",
        mode="paragraph",
        target_paragraph=1,
        user_note="Only rewrite paragraph one.",
    )

    paragraphs = (paths.sections_dir / "results.tex").read_text(encoding="utf-8").split("\n\n")
    assert paragraphs[0] == "\\section{Results}\nParagraph zero remains exactly the same."
    assert paragraphs[1] == "Replacement paragraph one uses cautious language."
    assert paragraphs[2] == "Paragraph two remains exactly the same.\n"


@pytest.mark.asyncio
async def test_selection_stale_hash_fails_without_modifying_section(tmp_path) -> None:
    paths = await _setup_run(tmp_path, "paper_regenerate_selection_stale")
    before = _section_bytes(paths)

    with pytest.raises(SelectionLocatorError) as exc_info:
        regenerate_section(
            paths.paper_id,
            "results",
            uploads_dir=tmp_path,
            regen_id="reg_stale",
            mode="selection",
            selected_text="Original results report the test set metric 0.9123.",
            source_hash="sha256:stale",
            rewrite_agent=StubSelectionRewriteAgent("replacement"),
        )

    assert exc_info.value.code == "stale_selection"
    assert _section_bytes(paths) == before
    job = get_regenerate_job(paths.paper_id, "reg_stale", uploads_dir=tmp_path)
    assert job.status == "failed"
    assert job.error_code == "stale_selection"


@pytest.mark.asyncio
async def test_reject_regenerate_restores_before_snapshot(tmp_path) -> None:
    paths = await _setup_run(tmp_path, "paper_regenerate_reject")
    before_results = (paths.sections_dir / "results.tex").read_text(encoding="utf-8")
    rewrite_agent = StubSelectionRewriteAgent("The result is now phrased conservatively.")

    regenerate_section(
        paths.paper_id,
        "results",
        uploads_dir=tmp_path,
        regen_id="reg_reject_me",
        mode="selection",
        selected_text="Original results report the test set metric 0.9123.",
        source_hash=section_content_hash(before_results),
        rewrite_agent=rewrite_agent,
    )
    assert (paths.sections_dir / "results.tex").read_text(encoding="utf-8") != before_results

    _manifest, response = reject_regenerate(
        paths.paper_id,
        "reg_reject_me",
        uploads_dir=tmp_path,
        reason="User preferred the previous wording.",
    )

    assert response["status"] == "rejected"
    assert response["restored_sections"] == ["results"]
    assert (paths.sections_dir / "results.tex").read_text(encoding="utf-8") == before_results
    job = get_regenerate_job(paths.paper_id, "reg_reject_me", uploads_dir=tmp_path)
    assert job.status == "rejected"
    assert job.rejection_reason == "User preferred the previous wording."


@pytest.mark.asyncio
async def test_cancelled_queued_regenerate_is_noop_when_worker_arrives(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = await _setup_run(tmp_path, "paper_regenerate_queued_cancel")
    before = _section_bytes(paths)
    manifest = load_manifest(paths.paper_id, uploads_dir=tmp_path)
    manifest.regenerate_jobs.append(
        {
            "regen_id": "reg_cancel_before_start",
            "mode": "section",
            "section_name": "results",
            "status": "queued",
            "enqueued_at": manifest.created_at.isoformat(),
        }
    )
    save_manifest(manifest, uploads_dir=tmp_path)
    cancel_response = cancel_regenerate(paths.paper_id, "reg_cancel_before_start", uploads_dir=tmp_path)
    assert cancel_response == {"regen_id": "reg_cancel_before_start", "status": "cancelled"}

    monkeypatch.setattr(
        regenerate_mod,
        "SectionWritingAgent",
        lambda: pytest.fail("cancelled queued regenerate should not call the section writer"),
    )
    regenerate_section(
        paths.paper_id,
        "results",
        uploads_dir=tmp_path,
        regen_id="reg_cancel_before_start",
    )

    assert _section_bytes(paths) == before
    job = get_regenerate_job(paths.paper_id, "reg_cancel_before_start", uploads_dir=tmp_path)
    assert job.status == "cancelled"
