"""Scientific decisions are bound to actual runs and reviewed source revisions."""

import json
from unittest.mock import AsyncMock

import pytest
from jsonschema.exceptions import ValidationError
from sqlalchemy import select
from test_manuscripts import api as api  # noqa: PLC0414 -- shared SQLite fixture.

from backend.autoresearch.engine import jobs, store, study, tools
from backend.database.models import AutoResearchExperiment, ResearchJob
from backend.services import manuscript_writer, manuscripts


def write(root, path, value):
    (root / path).write_text(json.dumps(value))


def pitch(identity, title):
    return {'id': identity, 'title': title, 'claim': f'{title} beats the closest method',
            'headline_result': f'{title} versus the closest method on the full cohort',
            'closest_work': 'Closest method', 'novelty_check': 'Searched recent work; no equivalent method',
            'expected_gain': 'At least 0.02 on the primary metric', 'cost': 'Two full-data runs', 'premise': None}


# Primary metric (delta, lower is better) per independent repeat.
SEEDS = {'baseline': {'seed-1': 0.05, 'seed-2': 0.052, 'seed-3': 0.048},
         'method': {'seed-1': 0.0, 'seed-2': 0.002, 'seed-3': -0.002}}


@pytest.fixture
async def scientific_case(api):
    root = api.root / "alice"
    await store.update(
        "alice",
        status="running",
        max_iterations=8,
        current_iteration=6,
        meta={
            "task_kind": "experiment",
            "report_policy": "manuscript",
            "research_standard": "scientific",
            "current_goal": "Explain conditional errors beyond the closest method",
        },
    )
    (root / "protocol.md").write_text(
        "Locked units, splits, closest method and rival predictions."
    )
    (root / "results.md").write_text(
        "Full-data comparison: the conditional method lowers delta by 0.05 versus the closest method."
    )
    (root / "figure.png").write_bytes(b"reviewed image")
    scale = {'dataset': 'cohort', 'unit': 'subject', 'train_units': 200, 'evaluation_units': 100,
             'repeats': 3, 'input_coverage': 'All available features',
             'optimization': 'Validation selected converged checkpoint'}
    protocol = {
        'directions': [pitch('conditional', 'Conditional error predictor'),
                       pitch('representation', 'Consistency-trained encoder'),
                       pitch('acquisition', 'Uncertainty-driven region acquisition')],
        'data': [{'name': 'cohort', 'unit': 'subject', 'train_units': 200, 'evaluation_units': 100}],
        'selected_direction': 'conditional',
        'selection_reason': 'Test residual signal before the costlier encoder experiment',
        'evaluation_files': ['protocol.md'],
        "question": "Is the extra signal useful after conditioning on confidence?",
        "hypothesis": "Conditional structure improves ranking.",
        "falsification": "No conditional signal under matched comparisons.",
        "contribution": "Test the boundary of conditional error information.",
        "baselines": [
            {
                "id": "closest",
                "name": "Closest method",
                "role": "closest",
                "source": "https://example.org/method",
                "rationale": "Same scientific target.",
                "reference": {"metric": "delta", "value": 0.05, "direction": "minimize",
                              "dataset": "cohort", "citation": "Closest method paper, Table 2"},
            }
        ],
        "evaluation": {'metric': 'delta', 'direction': 'minimize',
                       'primary_contrast': 'Candidate versus closest baseline',
                       'success_rule': 'Paired interval excludes a useful improvement of 0.02',
                       'uncertainty': 'Independent repeats and paired grouped intervals',
                       'split_policy': 'Train and development separate from held-out confirmation',
                       'minimum_gain': 0.02, 'resolution': 0.01, 'best_possible': None},
        'stages': [{'id': 'validation', 'kind': 'validation',
                    'max_experiments': 4, 'max_job_seconds': 3600,
                    'advance_when': 'Primary comparison and uncertainty measured',
                    'stop_when': 'Useful effect excluded with adequate precision'}],
        "steps": [
            {
                "id": "baseline",
                "role": "baseline",
                'stage_id': 'validation',
                'scale': dict(scale),
                "baseline_id": "closest",
                "question": "Does the closest method explain the signal?",
            },
            {
                "id": "method",
                "role": "method",
                'stage_id': 'validation', 'direction_id': 'conditional',
                'scale': dict(scale),
                "question": "Is there information beyond it?",
            },
        ],
        "budget_rationale": "Six attempts used plus two controls and two method repeats.",
        "evidence_files": ["protocol.md"],
    }
    write(root, "protocol.json", protocol)
    result = await tools.call(
        "alice", "record_study_protocol", {"path": "protocol.json"}
    )
    assert result["budget_sufficient"] is False
    assert (await store.get("alice")).max_iterations == 8
    session = await store.get('alice')
    async with api.sessions() as db:
        for step in ["baseline", "method"]:
            db.add(
                AutoResearchExperiment(
                    session_id="alice",
                    training_task_id=step,
                    experiment_name=step,
                    status="completed",
                    iteration=7,
                    metrics={"delta": 0.05 if step == "baseline" else 0.0},
                    hyperparams={
                        "config": {**study.experiment_config(session, {'study_step': step,
                            'candidate_id': step, 'operation': 'draft'}),
                            'study_measurement': {'unit': 'subject', 'train_units': 200,
                                'evaluation_units': 100, 'replicate_ids': list(SEEDS[step]),
                                'primary_by_replicate': SEEDS[step],
                                'input_coverage': 'All features', 'optimization': 'Converged'}},
                    },
                )
            )
        await db.commit()
    write(root, 'decision.json', {
        'id': 'conditional-1', 'direction_id': 'conditional', 'action': 'keep',
        'assessment': 'supported', 'scope': 'candidate', 'next_operation': 'finish',
        'run_ids': ['baseline', 'method'], 'observation': 'Method delta 0.0 versus baseline 0.05',
        'interpretation': 'The conditional method clears the publication bar on the full data',
        'next_action': 'Review the evidence before writing', 'evidence_files': ['results.md'],
    })
    await tools.call('alice', 'record_research_decision', {'path': 'decision.json'})
    review = {
        "decision": "write",
        "rationale": "The full-data comparison clears the protocol bar.",
        "goal_met": True,
        "conclusion": "Conditional prediction lowers delta by 0.05 versus the closest method.",
        "unresolved": [],
        "completed_steps": {"baseline": ["baseline"], "method": ["method"]},
        "evidence_files": ["results.md"],
        "figure_paths": ["figure.png"],
        "reviewer": "self-review, not peer review",
    }
    return api, root, protocol, review


async def record_review(case, **changes):
    _, root, _, review = case
    write(root, "review.json", {**review, **changes})
    return await tools.call("alice", "record_study_review", {"path": "review.json"})


async def test_review_uses_only_reviewed_runs_sources_and_figures(
    scientific_case,
):
    _, root, _, _ = scientific_case
    (root / "research-plan.md").write_text("Unrelated old BCFC plan")
    await store.update("alice", meta={"artifacts": [{"path": "old-bcfc.png"}]})
    assert (await record_review(scientific_case))["ready_to_write"]
    evidence = await manuscripts.research_evidence(
        await store.get("alice"), reviewed=True
    )
    assert {r["run_id"] for r in evidence["runs"]} == {"baseline", "method"}
    assert set(evidence["research_notes"]) == {"protocol.md", "results.md"}
    assert evidence["figure_sources"] == [{"path": "figure.png", "name": ""}]
    assert evidence["summary"].startswith("Conditional prediction lowers delta")
    assert evidence["title"] == "Explain conditional errors beyond the closest method"


@pytest.mark.parametrize(
    "changes",
    [
        {"completed_steps": {"method": ["method"]}},
        {"completed_steps": {"baseline": ["alice-run"], "method": ["method"]}},
        {"completed_steps": {"baseline": ["method"], "method": ["method"]}},
        {"unresolved": ["Critical comparator is not faithful."]},
        {"goal_met": False},
    ],
)
async def test_incomplete_or_misbound_evidence_cannot_release_writing(
    scientific_case, changes
):
    with pytest.raises(ValueError):
        await record_review(scientific_case, **changes)
    with pytest.raises(ValueError):
        await manuscript_writer.generate_research(await store.get("alice"))


@pytest.mark.parametrize(
    "change",
    [
        "results",
        "protocol",
        "protocol_json",
        "figure",
        "run",
        "goal",
        "new_instruction",
    ],
)
async def test_review_expires_when_scientific_inputs_change(scientific_case, change):
    api, root, _, _ = scientific_case
    await record_review(scientific_case)
    if change == "run":
        async with api.sessions() as db:
            run = await db.scalar(
                select(AutoResearchExperiment).where(
                    AutoResearchExperiment.training_task_id == "method"
                )
            )
            run.metrics = {"delta": 0.1}
            await db.commit()
    elif change == "goal":
        await tools.call(
            "alice",
            "set_task_scope",
            {
                "task_kind": "experiment",
                "report_policy": "manuscript",
                "research_standard": "scientific",
                "current_goal": "A different discovery",
            },
        )
    elif change == "new_instruction":
        await store.command("alice", "message", "Add a claim-critical ablation")
    elif change == "protocol_json":
        protocol = json.loads((root / "protocol.json").read_text())
        protocol["evaluation"]['metric'] = "Changed primary endpoint"
        write(root, "protocol.json", protocol)
    else:
        (
            root
            / {
                "results": "results.md",
                "protocol": "protocol.md",
                "figure": "figure.png",
            }[change]
        ).write_text("Changed evidence")
    with pytest.raises(ValueError):
        await study.writing_evidence(await store.get("alice"))


async def test_new_experiment_is_bound_and_invalidates_review(
    scientific_case, monkeypatch
):
    await record_review(scientific_case)
    monkeypatch.setattr(jobs, "enqueue_task_descriptor", AsyncMock())
    with pytest.raises(ValueError, match="study_step"):
        await jobs.submit(
            "alice", "experiment", {"command": ["python", "train.py"], "device": "cpu"}
        )
    baseline = await jobs.submit("alice", "experiment", {"command": ["python", "train.py"], "device": "cpu",
        "config": {"study_step": "baseline", 'candidate_id': 'new-baseline', 'operation': 'draft'}})
    async with scientific_case[0].sessions() as db:
        job = await db.get(ResearchJob, baseline['job_id'])
        job.status, job.result = 'completed', {'metrics': {'delta': 0.05}}
        await db.commit()
    result = await jobs.submit(
        "alice",
        "experiment",
        {
            "command": ["python", "train.py"],
            "device": "cpu",
            "config": {"study_step": "method", 'candidate_id': 'new-method', 'operation': 'draft'},
        },
    )
    run = next(
        r for r in await store.experiments("alice") if r["run_id"] == result["job_id"]
    )
    assert run["config"]["config"]["study_revision"]
    assert run["config"]["config"]["study_role"] == "method"
    assert (await store.get("alice")).recovery_metadata["study"]["review"] is None


async def test_unreviewed_draft_and_historical_report_stay_readable(scientific_case):
    api, _, _, _ = scientific_case
    draft = await manuscripts.checkpoint_research(
        await store.get("alice"),
        title="Exploratory checkpoint",
        content="Complete exploratory sections",
    )
    response = await api.client.get(f"/reports/documents/{draft['report_id']}")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "draft"
    response = await api.client.post(
        "/reports/documents", json={"source_type": "research", "source_id": "alice"}
    )
    assert response.status_code == 409 and "write decision" in response.text
    with pytest.raises(ValueError):
        await tools.call(
            "alice", "finish_research", {"summary": "Done", "outcome": "completed"}
        )
    with pytest.raises(ValueError, match="Untested pitches"):
        await tools.call("alice", "finish_research",
                         {"summary": "Pilot complete; scientific goal unmet", "outcome": "partial"})
    await store.command("alice", "message", "Stop here and keep the pilot report")
    assert (
        await tools.call(
            "alice",
            "finish_research",
            {"summary": "Pilot complete; scientific goal unmet", "outcome": "partial", "user_stop": "Stop here"},
        )
    )["finished"]


async def test_scope_requires_new_contract_and_standard_analysis_stays_lightweight(api):
    await store.update("alice", status="running")
    with pytest.raises(ValidationError):
        await tools.call(
            "alice",
            "set_task_scope",
            {"task_kind": "analysis", "report_policy": "summary"},
        )
    await tools.call(
        "alice",
        "set_task_scope",
        {
            "task_kind": "analysis",
            "report_policy": "summary",
            "research_standard": "standard",
            "current_goal": "Summarize saved metrics",
        },
    )
    assert await study.writing_evidence(await store.get("alice")) is None
    assert (
        await tools.call(
            "alice", "finish_research", {"summary": "Saved metrics summarized"}
        )
    )["finished"]


async def test_protocol_source_edit_changes_revision_and_rejects_old_runs(
    scientific_case,
):
    _, root, _, _ = scientific_case
    old = (await store.get("alice")).recovery_metadata["study"]["revision"]
    (root / "protocol.md").write_text("A revised comparison and endpoint")
    result = await tools.call(
        "alice", "record_study_protocol", {"path": "protocol.json"}
    )
    assert result["revision"] != old
    with pytest.raises(ValueError, match="completed runs"):
        await record_review(scientific_case)


async def test_workspace_escape_is_not_evidence(scientific_case):
    _, root, _, _ = scientific_case
    (root.parent / "outside.md").write_text("Private outside file")
    (root / "escape.md").symlink_to(root.parent / "outside.md")
    for path in ["../outside.md", "escape.md", str(root / "results.md")]:
        with pytest.raises(ValueError, match="workspace-relative"):
            study.read_evidence(root, path)


async def test_stale_review_cannot_overwrite_a_new_instruction(scientific_case):
    _, root, _, review = scientific_case
    write(root, "review.json", review)
    stale = await store.get("alice")
    await store.command("alice", "message", "Test an additional rival explanation")
    with pytest.raises(ValueError, match="Research changed"):
        await study.record_review(stale, "review.json")
    assert (await store.get("alice")).recovery_metadata["study"]["review"] is None


async def test_writer_reuses_current_review_but_rebuilds_after_source_revision(
    scientific_case,
):
    _, root, _, _ = scientific_case
    await record_review(scientific_case)
    first = await manuscript_writer.generate_research(await store.get("alice"))
    again = await manuscript_writer.generate_research(await store.get("alice"))
    assert again["report_id"] == first["report_id"]
    # The measurements are identical; changing the reviewed method description
    # must still create a new evidence snapshot rather than reuse the old article.
    (root / "results.md").write_text(
        "Clarified exact method implementation and unchanged measurements."
    )
    await record_review(scientific_case)
    current = await manuscript_writer.generate_research(await store.get("alice"))
    assert current["report_id"] != first["report_id"]
    report, job = await manuscript_writer.read_job(first["report_id"])
    with pytest.raises(manuscript_writer.WritingPaused, match="evidence_changed"):
        await manuscript_writer.guard(report, job)
