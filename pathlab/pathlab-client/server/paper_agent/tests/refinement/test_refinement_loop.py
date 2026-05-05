from __future__ import annotations

import json

import pytest

from pathlab_paper_agent.agents.content_refinement_agent import (
    ContentRefinementAgent,
    ContentRefinementAgentError,
    RefinementInputs,
)
from pathlab_paper_agent.llm import LLMResponse
from pathlab_paper_agent.pipeline import create_dev_run
from pathlab_paper_agent.schemas import PaperManifest
from pathlab_paper_agent.stages.refining import run as run_refining


class MockRefinementLLM:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(
        self,
        messages,
        *,
        temperature: float = 0.2,
        response_format=None,
        stream=None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "response_format": response_format,
                "stream": stream,
            }
        )
        response = self.responses.pop(0)
        return LLMResponse(content=json.dumps(response), model="mock-refinement", provider="mock")


def _critic(score: int, reason: str = "mock reason") -> dict:
    return {
        "rubric": {
            "medical_accuracy": {"score": score, "reason": reason},
            "statistical_rigor": {"score": score, "reason": reason},
            "clinical_relevance": {"score": score, "reason": reason},
            "technical_novelty": {"score": score, "reason": reason},
            "presentation": {"score": score, "reason": reason},
        },
        "overall": {"score": score * 5, "reason": reason},
        "revise_sections": ["results"],
        "actionable_feedback": ["Tighten presentation without changing evidence."],
    }


def _revise_results(sentence: str) -> dict:
    return {
        "worklog": {"actions_taken": [sentence]},
        "sections": {
            "results": (
                "\\section{Results}\n"
                f"On the test set, {sentence} {{{{m:main.metrics.test_accuracy}}}}.\n"
            )
        },
    }


def _revise_discussion(sentence: str) -> dict:
    return {
        "worklog": {"actions_taken": [sentence]},
        "sections": {"discussion": f"\\section{{Discussion}}\n{sentence}\n"},
    }


async def _setup_run(tmp_path, paper_id: str):
    _paper_id, paths = await create_dev_run(paper_id=paper_id, uploads_dir=tmp_path)
    paths.ensure_dirs()
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
    paths.experimental_log.write_text("# Experimental Log\n\nMetrics are rendered from evidence lock.\n", encoding="utf-8")
    paths.refs_bib.write_text("", encoding="utf-8")
    (paths.citations_dir / "selected_refs.json").write_text(json.dumps({"items": []}), encoding="utf-8")
    (paths.citations_dir / "required_cites.json").write_text(json.dumps({"items": []}), encoding="utf-8")
    (paths.sections_dir / "results.tex").write_text(
        "\\section{Results}\nOn the test set, the original accuracy was 0.9123.\n",
        encoding="utf-8",
    )
    (paths.sections_dir / "discussion.tex").write_text(
        "\\section{Discussion}\nThe original discussion stays within the available evidence.\n",
        encoding="utf-8",
    )
    manifest = PaperManifest.model_validate(json.loads(paths.manifest.read_text(encoding="utf-8")))
    return paths, manifest


def _log(paths) -> dict:
    return json.loads((paths.validation_dir / "refinement_log.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_score_increase_accepts_revision_and_snapshots_previous_sections(tmp_path) -> None:
    paths, manifest = await _setup_run(tmp_path, "paper_refine_accept_increase")
    llm = MockRefinementLLM([_critic(3), _revise_results("the refined accuracy remains"), _critic(4)])

    run_refining(paths, manifest, agent=ContentRefinementAgent(llm), max_iterations=1)

    results = (paths.sections_dir / "results.tex").read_text(encoding="utf-8")
    assert "the refined accuracy remains 0.9123" in results
    snapshot = paths.snapshots_dir / "iter_1" / "sections" / "results.tex"
    assert snapshot.is_file()
    assert "original accuracy" in snapshot.read_text(encoding="utf-8")
    payload = _log(paths)
    assert payload["iterations"][0]["accepted"] is True
    assert payload["iterations"][0]["reason"] == "score_increased"
    assert payload["accepted_iterations"] == [1]
    assert "validation/refinement_log.json" in manifest.artifact_index
    assert len(llm.calls) == 3
    assert payload["iterations"][0]["candidate_critic"]["total"] == 20


@pytest.mark.asyncio
async def test_score_tie_with_no_subaxis_regression_accepts(tmp_path) -> None:
    paths, manifest = await _setup_run(tmp_path, "paper_refine_accept_tie")
    llm = MockRefinementLLM(
        [
            _critic(3),
            _revise_results("the first refinement reports"),
            _critic(3),
            _revise_results("the tie refinement preserves"),
            _critic(3),
        ]
    )

    run_refining(paths, manifest, agent=ContentRefinementAgent(llm), max_iterations=2)

    results = (paths.sections_dir / "results.tex").read_text(encoding="utf-8")
    assert "the tie refinement preserves 0.9123" in results
    payload = _log(paths)
    assert [item["accepted"] for item in payload["iterations"]] == [True, True]
    assert payload["iterations"][1]["reason"] == "score_tied_no_subaxis_regression"
    assert payload["accepted_iterations"] == [1, 2]


@pytest.mark.asyncio
async def test_score_decrease_rejects_and_physically_reverts_to_previous_snapshot(tmp_path) -> None:
    paths, manifest = await _setup_run(tmp_path, "paper_refine_reject_decrease")
    llm = MockRefinementLLM(
        [
            _critic(3),
            _revise_results("the accepted refinement reports"),
            _critic(4),
            _revise_results("the rejected refinement reports"),
            _critic(3),
        ]
    )

    run_refining(paths, manifest, agent=ContentRefinementAgent(llm), max_iterations=2)

    results = (paths.sections_dir / "results.tex").read_text(encoding="utf-8")
    assert "the accepted refinement reports 0.9123" in results
    assert "the rejected refinement reports" not in results
    iter_2_snapshot = paths.snapshots_dir / "iter_2" / "sections" / "results.tex"
    assert "the accepted refinement reports" in iter_2_snapshot.read_text(encoding="utf-8")
    payload = _log(paths)
    assert [item["accepted"] for item in payload["iterations"]] == [True, False]
    assert payload["iterations"][1]["reason"] == "score_decreased"
    assert payload["final_status"] == "rejected"


@pytest.mark.asyncio
async def test_guard_fail_force_rejects_and_reverts_candidate(tmp_path) -> None:
    paths, manifest = await _setup_run(tmp_path, "paper_refine_force_reject_guard")
    llm = MockRefinementLLM(
        [
            _critic(3),
            _revise_discussion("This outperforms state-of-the-art systems despite no baseline evidence."),
        ]
    )

    run_refining(paths, manifest, agent=ContentRefinementAgent(llm), max_iterations=1)

    discussion = (paths.sections_dir / "discussion.tex").read_text(encoding="utf-8")
    assert "original discussion" in discussion
    assert "outperforms" not in discussion
    payload = _log(paths)
    iteration = payload["iterations"][0]
    assert iteration["accepted"] is False
    assert iteration["reason"] == "force_reject_guard_fail"
    assert "claim_guard" in iteration["score"]["guard_failures"]
    final_claim_report = json.loads((paths.validation_dir / "claim_guard.json").read_text(encoding="utf-8"))
    assert final_claim_report["status"] == "pass"


@pytest.mark.asyncio
async def test_candidate_critic_score_controls_acceptance(tmp_path) -> None:
    paths, manifest = await _setup_run(tmp_path, "paper_refine_candidate_critic_reject")
    llm = MockRefinementLLM([_critic(5), _revise_results("the candidate gets worse"), _critic(2)])

    run_refining(paths, manifest, agent=ContentRefinementAgent(llm), max_iterations=1)

    results = (paths.sections_dir / "results.tex").read_text(encoding="utf-8")
    assert "original accuracy" in results
    assert "candidate gets worse" not in results
    payload = _log(paths)
    iteration = payload["iterations"][0]
    assert iteration["baseline_critic"]["total"] == 25
    assert iteration["candidate_critic"]["total"] == 10
    assert iteration["reason"] == "score_decreased"


@pytest.mark.asyncio
async def test_locked_figure_table_structure_changes_are_rejected_and_reverted(tmp_path) -> None:
    paths, manifest = await _setup_run(tmp_path, "paper_refine_reject_structure")
    (paths.locked_blocks_dir / "results_block.tex").write_text(
        "Locked narrative facts live here.\n",
        encoding="utf-8",
    )
    (paths.tables_dir / "table_2_main_results.tex").write_text(
        "\\begin{tabular}{ll}Metric & Value\\\\\\end{tabular}\n",
        encoding="utf-8",
    )
    (paths.figures_dir / "fig_ready.png").write_bytes(b"not-a-real-png")
    (paths.sections_dir / "results.tex").write_text(
        "\\section{Results}\n"
        "\\input{locked_blocks/results_block.tex}\n"
        "\\input{tables/table_2_main_results.tex}\n"
        "\\begin{figure}\n"
        "\\includegraphics{figures/fig_ready.png}\n"
        "\\caption{Ready figure}\\label{fig:ready}\n"
        "\\end{figure}\n"
        "On the test set, the original accuracy was 0.9123.\n",
        encoding="utf-8",
    )
    llm = MockRefinementLLM(
        [
            _critic(3),
            _revise_results("the rewrite deletes structure but reports"),
        ]
    )

    run_refining(paths, manifest, agent=ContentRefinementAgent(llm), max_iterations=1)

    results = (paths.sections_dir / "results.tex").read_text(encoding="utf-8")
    assert "\\input{locked_blocks/results_block.tex}" in results
    assert "\\includegraphics{figures/fig_ready.png}" in results
    assert "\\label{fig:ready}" in results
    payload = _log(paths)
    iteration = payload["iterations"][0]
    assert iteration["accepted"] is False
    assert iteration["reason"] == "force_reject_refinement_error"
    assert "modifies locked block input" in iteration["error"]


@pytest.mark.asyncio
async def test_refinement_prompt_rejects_phi_in_validation_context(tmp_path) -> None:
    paths, _manifest = await _setup_run(tmp_path, "paper_refine_prompt_phi_guard")
    inputs = RefinementInputs.from_paths(
        paths,
        validation_reports=[
            {
                "guard": "identifier_guard",
                "status": "fail",
                "issues": [
                    {
                        "code": "raw_path_leak",
                        "severity": "error",
                        "context": "/Users/research/private/raw_slide.svs",
                    }
                ],
            }
        ],
    )
    agent = ContentRefinementAgent(MockRefinementLLM([]))

    with pytest.raises(ContentRefinementAgentError, match="PHI/private identifiers"):
        agent.build_critic_prompt(inputs)
