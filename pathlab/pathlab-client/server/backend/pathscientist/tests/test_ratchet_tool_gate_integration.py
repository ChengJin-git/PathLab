"""Task 5: End-to-end integration coverage for the Tool-Gate Policy.

Unlike ``tests/test_ratchet_tool_gate.py`` which isolates each gate path,
this module exercises the full commit-finalization pipeline so regressions
that slip between the tool boundary, the evidence collector, and the
IntegrityGuard are caught together.

Three scenarios:

1. **Happy path** — ``RunExperimentTool`` populates
   ``deps.last_experiment`` (stubbed here for hermeticity) and then
   ``RatchetCommitExecutor`` commits. Evidence record lands on disk,
   tracker history grows, and no skip entries are recorded.
2. **Bare bypass** — agent calls ``ratchet_commit`` without a preceding
   ``run_experiment``. The gate refuses the call and nothing about the
   session mutates.
3. **External opt-in** — ``RatchetCommitAction(external=True)`` bypasses
   the gate. The commit proceeds, the skip reason is
   ``external_experiment_opt_in``, and feeding that state into
   ``check_session_integrity`` produces a *warning* (not a fatal) for the
   missing evidence record.

The "happy path" stubs ``deps.last_experiment`` directly rather than
invoking ``RunExperimentExecutor`` — that tool carries sandbox dependencies
(GPU scheduling, DATA_OUTPUT_DIR, Apptainer) irrelevant to the commit-side
gate contract this file is guarding.

Complements commits 57231463 (T1), f5208311 (T2), 40aaf4b3 (T3), and
01f59430 (T4).
"""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

import pytest

from pathscientist.config import PathScientistConfig
from pathscientist.runtime.integrity import check_session_integrity
from pathscientist.runtime.iteration_state import IterationState
from pathscientist.runtime.session_registry import (
    SessionDeps,
    register_session,
    remove_session,
)
from pathscientist.runtime.workspace import Workspace
from pathscientist.tools.metrics import MetricsTracker
from pathscientist.tools.ratchet import (
    RatchetCommitAction,
    RatchetCommitExecutor,
)


# ---------- helpers ----------


def _register_session(tmp_path: Path, *, last_experiment: dict | None = None):
    """Build a SessionDeps with a live git-backed workspace + tracker.

    Matches the setup used by ``tests/test_ratchet_tool_gate.py::_register_session``
    so failure modes stay comparable, but returns enough objects for
    integration assertions (history, evidence dir, IntegrityGuard wiring).
    """
    ws_dir = tmp_path / "workspace"
    ws = Workspace(ws_dir)
    # Seed repo so HEAD exists — required for the second commit to resolve.
    ws.write_file("train.py", "print('baseline')\n")
    ws.commit("baseline")

    tracker = MetricsTracker(primary_metric="auc")
    iteration_state = IterationState(max_iterations=5)
    config = PathScientistConfig(
        workspace_dir=str(ws_dir),
        output_dir=str(tmp_path / "output"),
        gpu_ids=[],
        sandbox_mode="local",
        max_iterations=5,
        primary_metric="auc",
        conversation_persistence_dir=str(tmp_path),
    )
    deps = SessionDeps(
        workspace=ws,
        tracker=tracker,
        config=config,
        iteration_state=iteration_state,
        conversation=None,
        last_experiment=(copy.deepcopy(last_experiment)
                         if last_experiment is not None else None),
    )
    session_id = f"test_gate_integration_{tmp_path.name}"
    register_session(session_id, deps)

    def _cleanup():
        remove_session(session_id)

    return session_id, deps, _cleanup


def _stub_last_experiment(run_id: str, *, auc: float, exit_code: int = 0) -> dict:
    """Return a last_experiment dict that mirrors the shape RunExperimentTool
    writes to ``SessionDeps.last_experiment`` (see ``tools/run_experiment.py``
    around the ``deps.last_experiment = {...}`` assignment).

    Kept in sync with the fields RunExperimentTool actually populates so this
    integration test behaves like a real commit-after-run_experiment.
    """
    return {
        "run_id": run_id,
        "run_dir": f"output/runs/{run_id}",
        "exit_code": exit_code,
        "stdout": f"run {run_id} stdout",
        "stderr": "",
        "metrics": {"auc": auc},
        "duration": 3.5,
        "started_at": "2026-04-18T00:00:00Z",
        "model_path": "",
        "data_output_dir": "",
        "data_output_artifacts": None,
    }


# ---------- 1. happy path: commit after a simulated run_experiment ----------


def test_happy_path_commit_after_run_experiment(tmp_path):
    """Register session with ``last_experiment`` populated as if
    RunExperimentTool just finished, then call RatchetCommitExecutor.

    Invariants on the whole pipeline:
    - ``workspace.get_history()`` grows by exactly one commit.
    - ``.evidence/runs/<run_id>/record.json`` is written on disk.
    - ``deps.evidence_skipped_runs`` stays empty (no skips on happy path).
    - The tracker's last entry is marked ``committed=True``.
    - ``deps.last_experiment`` is cleared (consumed by the collector).
    """
    last_experiment = _stub_last_experiment("run_happy01", auc=0.87)
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        # RunExperimentTool normally writes ``iteration_state.last_run_id``
        # at tool entry (see ``tools/run_experiment.py``, around
        # ``iteration_state.last_run_id = run_id``). Reproduce that here
        # so ``_finalize_iteration``'s ``ensure_run_id()`` returns the
        # same canonical run_id as the stubbed ``last_experiment`` dict.
        deps.iteration_state.last_run_id = last_experiment["run_id"]

        ws = deps.workspace
        history_before = ws.get_history()
        tracker_len_before = len(deps.tracker.history)

        # A committable change so `git commit` has content to write.
        ws.write_file("train.py", "print('improved baseline')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(RatchetCommitAction(message="improve auc", metrics={"auc": 0.87}))

        assert obs.commit_hash, (
            f"happy-path commit must produce a commit_hash; "
            f"got commit_hash={obs.commit_hash!r}, content={obs.content!r}"
        )

        # 1. git history grew by exactly one commit.
        history_after = ws.get_history()
        assert len(history_after) == len(history_before) + 1, (
            f"expected one new commit; "
            f"before={len(history_before)} after={len(history_after)}"
        )

        # 2. evidence record is on disk at the canonical location.
        evidence_record = (
            ws.root / ".evidence" / "runs" / "run_happy01" / "record.json"
        )
        assert evidence_record.exists(), (
            f"expected evidence record at {evidence_record}; "
            f"runs dir contents: "
            f"{list((ws.root / '.evidence' / 'runs').glob('*')) if (ws.root / '.evidence' / 'runs').exists() else '(missing)'}"
        )

        # 3. no skip entries on the happy path.
        assert deps.evidence_skipped_runs == [], (
            f"happy path must not skip anything; "
            f"got {deps.evidence_skipped_runs!r}"
        )

        # 4. tracker recorded the committed run.
        assert len(deps.tracker.history) == tracker_len_before + 1
        last_entry = deps.tracker.history[-1]
        assert last_entry["committed"] is True, (
            f"tracker must mark the entry committed; got {last_entry!r}"
        )
        assert last_entry["run_id"] == "run_happy01", (
            f"tracker must record the canonical run_id; got {last_entry!r}"
        )

        # 5. last_experiment was consumed.
        assert deps.last_experiment is None, (
            f"collector must consume last_experiment; "
            f"still set to {deps.last_experiment!r}"
        )
    finally:
        cleanup()


# ---------- 2. bare bypass: gate refuses and nothing mutates ----------


def test_bypass_is_refused_and_state_unchanged(tmp_path):
    """Register session with ``last_experiment=None`` (the motivating shape
    from session_b14b074d2268 — agent called terminal + python + commit
    directly). The executor must refuse and every piece of session state
    must be untouched.

    Invariants:
    - Observation text starts with the canonical refusal marker.
    - ``workspace.get_history()`` is byte-for-byte unchanged.
    - ``tracker.history`` is unchanged.
    - No ``.evidence/runs/`` entries get created.
    """
    session_id, deps, cleanup = _register_session(tmp_path, last_experiment=None)
    try:
        ws = deps.workspace
        history_before = ws.get_history()
        tracker_history_before = list(deps.tracker.history)
        evidence_runs_dir = ws.root / ".evidence" / "runs"
        evidence_runs_before = (
            sorted(p.name for p in evidence_runs_dir.iterdir())
            if evidence_runs_dir.exists()
            else []
        )

        # Stage an uncommitted change — the gate is the only reason a commit
        # would be blocked here, not an empty working tree.
        ws.write_file("train.py", "print('would-be bypass')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(RatchetCommitAction(message="bypass attempt"))

        # Observation shape — canonical refusal message.
        assert obs.commit_hash == "", (
            f"gate must refuse; got commit_hash={obs.commit_hash!r}"
        )
        assert obs.content, "observation must carry explanatory content"
        text = obs.content[0].text
        assert text.startswith("\u274c ratchet_commit requires a preceding"), (
            f"refusal must use the canonical marker; got: {text!r}"
        )

        # Git history — unchanged.
        history_after = ws.get_history()
        assert history_after == history_before, (
            f"gate must not create a commit; "
            f"before={history_before!r} after={history_after!r}"
        )

        # Tracker history — unchanged (the gate fires before _finalize_iteration).
        assert deps.tracker.history == tracker_history_before, (
            f"tracker must not record a refused commit; "
            f"before={tracker_history_before!r} after={deps.tracker.history!r}"
        )

        # Evidence runs dir — no new entries.
        evidence_runs_after = (
            sorted(p.name for p in evidence_runs_dir.iterdir())
            if evidence_runs_dir.exists()
            else []
        )
        assert evidence_runs_after == evidence_runs_before, (
            f"gate must not write an evidence record; "
            f"before={evidence_runs_before!r} after={evidence_runs_after!r}"
        )

        # Skip log — unchanged. The gate fires before _finalize_iteration, so
        # no skip entry should be recorded for a refused call.
        assert deps.evidence_skipped_runs == [], (
            f"refused calls must not log a skip; "
            f"got {deps.evidence_skipped_runs!r}"
        )
    finally:
        cleanup()


# ---------- 3. external opt-in: commits as warning-severity in integrity ----------


def test_external_opt_in_commits_with_warning_severity(tmp_path):
    """Register session with ``last_experiment=None`` but call
    ``RatchetCommitAction(external=True)``. The commit must proceed and be
    tagged ``external_experiment_opt_in`` in the skip log; the IntegrityGuard
    must emit severity=``warning`` for the missing evidence record, and the
    session-level counters must reflect that.
    """
    session_id, deps, cleanup = _register_session(tmp_path, last_experiment=None)
    try:
        ws = deps.workspace

        # Stage a real change so the external commit has something to land.
        ws.write_file("train.py", "print('external run')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(
            RatchetCommitAction(
                message="external-run commit",
                metrics={"auc": 0.82},
                external=True,
            )
        )

        # Commit proceeded.
        assert obs.commit_hash, (
            f"external=True must allow the commit; "
            f"got commit_hash={obs.commit_hash!r}, content={obs.content!r}"
        )

        # Skip log tagged with external_experiment_opt_in, NOT no_last_experiment.
        assert len(deps.evidence_skipped_runs) == 1, (
            f"external-opt-in must append exactly one skip entry; "
            f"got {deps.evidence_skipped_runs!r}"
        )
        skip_entry = deps.evidence_skipped_runs[-1]
        assert skip_entry["reason"] == "external_experiment_opt_in", (
            f"external=True must tag the skip as external_experiment_opt_in; "
            f"got {skip_entry!r}"
        )
        external_run_id = skip_entry["run_id"]
        assert external_run_id, (
            f"skip entry must carry a canonical run_id; got {skip_entry!r}"
        )

        # Sanity: the committed tracker entry shares the same run_id.
        assert deps.tracker.history, (
            f"tracker must have recorded the external commit; "
            f"got {deps.tracker.history!r}"
        )
        tracker_last = deps.tracker.history[-1]
        assert tracker_last["committed"] is True
        assert tracker_last["run_id"] == external_run_id

        # ---- Feed the resulting state into check_session_integrity. ----
        #
        # The evidence/ tree has no record.json for external_run_id (by
        # construction — the opt-in bypassed RunExperimentTool). The guard
        # must see this and downgrade the missing-evidence issue to warning.
        research_run_history = [
            {
                "run_id": external_run_id,
                "iteration": tracker_last["iteration"],
                "metric_name": "auc",
                "metric_value": 0.82,
                "committed": True,
                "notes": "",
            }
        ]
        tracker_history_for_check = [dict(e) for e in deps.tracker.history]
        iteration_history_for_check = [dict(e) for e in deps.iteration_state.history]

        report = check_session_integrity(
            workspace_root=ws.root,
            evidence_root=ws.root / ".evidence",
            tracker_history=tracker_history_for_check,
            iteration_history=iteration_history_for_check,
            research_run_history=research_run_history,
            max_iterations=5,
            iteration_index=deps.iteration_state.iteration_index,
            stop_reason="",
            evidence_skipped_runs=list(deps.evidence_skipped_runs),
            primary_metric="auc",
        )

        # There must be an evidence_run_missing issue for this run.
        matching = [
            i
            for i in report.issues
            if i.code == "evidence_run_missing"
            and (i.context.get("run_id") == external_run_id)
        ]
        assert len(matching) == 1, (
            f"exactly one evidence_run_missing issue expected for the "
            f"external run; got {[i.context for i in report.issues]!r}"
        )
        issue = matching[0]
        assert issue.severity == "warning", (
            f"external_experiment_opt_in must downgrade to warning; "
            f"got severity={issue.severity!r}"
        )
        assert issue.context.get("skip_reason") == "external_experiment_opt_in"

        # Aggregate counters: this issue counts as warning, not fatal.
        fatal_for_run = [
            i
            for i in report.issues
            if i.code == "evidence_run_missing"
            and i.context.get("run_id") == external_run_id
            and i.severity == "fatal"
        ]
        warning_for_run = [
            i
            for i in report.issues
            if i.code == "evidence_run_missing"
            and i.context.get("run_id") == external_run_id
            and i.severity == "warning"
        ]
        assert fatal_for_run == [], (
            f"no fatal evidence_run_missing should exist for external run; "
            f"got {[i.context for i in fatal_for_run]!r}"
        )
        assert len(warning_for_run) == 1
        assert report.warning_count >= 1, (
            f"report.warning_count must include the external-opt-in issue; "
            f"got {report.warning_count}"
        )
        # With only the external-opt-in issue, the session is healthy.
        assert report.passed is True, (
            f"external-opt-in alone must not fail integrity; "
            f"fatal_count={report.fatal_count}, issues={[i.code for i in report.issues]}"
        )
    finally:
        cleanup()


# ---------- 4. external opt-in: paper_ready is forced False in synthesis ----------


def test_external_opt_in_forces_paper_ready_false(tmp_path):
    """Review Fix C (2026-04-21 post-fix code review, Finding 3).

    IntegrityGuard keeps ``external_experiment_opt_in`` as a warning
    (``test_external_opt_in_is_warning_not_fatal`` locks that in, and the
    reviewer explicitly asked us NOT to re-escalate it to fatal). But the
    review identified a second risk: even with a passing integrity report,
    a paper built on a run without an evidence record can still ship as
    ``paper_ready=True`` — a "supported bypass via ``external=True``".

    The synthesis-layer gate in ``_run_synthesis_stage`` must force
    ``state.paper_ready = False`` when ``deps.evidence_skipped_runs``
    contains any entry with ``reason == "external_experiment_opt_in"``,
    regardless of what verification/critique decided.
    """
    from types import SimpleNamespace
    from uuid import uuid4

    from pathscientist.orchestrator.runner import _run_synthesis_stage
    from pathscientist.orchestrator.types import (
        ResearchObjective,
        ResearchSessionState,
        RunRecord,
    )

    # Seed a minimal session state with one committed run. The grounding +
    # runs are only needed so synthesis produces any artifacts at all; the
    # contract we care about is the paper_ready gate.
    state = ResearchSessionState.create(
        session_id="sess_external_paper_gate",
        conversation_id=uuid4(),
        objective=ResearchObjective(
            question="Improve AUC on BRACS",
            success_metric="auc",
        ),
    )
    state.grounding = {
        "selected_skill": "mil_classification",
        "route": "skill",
        "reason": "stub",
        "baselines": [],
        "papers": [],
    }
    state.record_run(
        RunRecord(
            run_id="run_ext_01",
            iteration=0,
            metric_value=0.82,
            committed=True,
            notes="external run",
        )
    )

    workspace = SimpleNamespace(root=tmp_path / "workspace")
    workspace.root.mkdir(parents=True, exist_ok=True)

    config = PathScientistConfig(
        workspace_dir=str(workspace.root),
        output_dir=str(tmp_path / "output"),
        gpu_ids=[],
        sandbox_mode="local",
        max_iterations=3,
        primary_metric="auc",
        conversation_persistence_dir=str(tmp_path),
        llm_model="",  # deterministic fallback for paper writer
        llm_api_key="",
        llm_base_url="",
    )

    # deps carries the external-opt-in skip entry that the synthesis gate
    # should observe. This is exactly what the RatchetCommitExecutor logs
    # when ``external=True`` is used (see
    # ``test_external_opt_in_commits_with_warning_severity`` above for the
    # matching shape).
    deps = SimpleNamespace(
        evidence_skipped_runs=[
            {"run_id": "run_ext_01", "reason": "external_experiment_opt_in"}
        ],
    )

    # Precondition: force paper_ready=True beforehand to prove the gate
    # actively downgrades rather than just happening to leave it False.
    state.paper_ready = True

    _run_synthesis_stage(
        state,
        workspace=workspace,
        session=None,
        config=config,
        deps=deps,
    )

    assert state.paper_ready is False, (
        "external_experiment_opt_in in deps.evidence_skipped_runs must "
        "force paper_ready=False after synthesis, regardless of whether "
        "verification/critique would have passed. This closes the "
        "'supported bypass via external=True' gap flagged by the "
        "2026-04-21 post-fix code review (Finding 3)."
    )


def test_external_opt_in_leaves_paper_ready_alone_when_absent(tmp_path):
    """Control case for test_external_opt_in_forces_paper_ready_false.

    Without any ``external_experiment_opt_in`` skip entry, the synthesis
    gate must NOT touch ``paper_ready`` — the final value is whatever
    verification + critique + fatal-integrity decided.
    """
    from types import SimpleNamespace
    from uuid import uuid4

    from pathscientist.orchestrator.runner import _run_synthesis_stage
    from pathscientist.orchestrator.types import (
        ResearchObjective,
        ResearchSessionState,
        RunRecord,
    )

    state = ResearchSessionState.create(
        session_id="sess_no_external_paper_gate",
        conversation_id=uuid4(),
        objective=ResearchObjective(
            question="Improve AUC on BRACS",
            success_metric="auc",
        ),
    )
    state.grounding = {
        "selected_skill": "mil_classification",
        "route": "skill",
        "reason": "stub",
        "baselines": [],
        "papers": [],
    }
    state.record_run(
        RunRecord(
            run_id="run_normal_01",
            iteration=0,
            metric_value=0.82,
            committed=True,
        )
    )

    workspace = SimpleNamespace(root=tmp_path / "workspace")
    workspace.root.mkdir(parents=True, exist_ok=True)

    config = PathScientistConfig(
        workspace_dir=str(workspace.root),
        output_dir=str(tmp_path / "output"),
        gpu_ids=[],
        sandbox_mode="local",
        max_iterations=3,
        primary_metric="auc",
        conversation_persistence_dir=str(tmp_path),
        llm_model="",
        llm_api_key="",
        llm_base_url="",
    )

    # Unrelated skip reason — must NOT trigger the gate.
    deps = SimpleNamespace(
        evidence_skipped_runs=[
            {"run_id": "run_other", "reason": "snapshot_failed"}
        ],
    )

    _run_synthesis_stage(
        state,
        workspace=workspace,
        session=None,
        config=config,
        deps=deps,
    )

    # state.paper_ready is now whatever verification/critique decided. The
    # gate must not have forced it — we only assert that if it was True
    # before reaching the gate, it stays True through the gate. Since the
    # deterministic verifier may or may not pass for this stub state we
    # assert the weaker invariant: no external-opt-in means no forced
    # downgrade. Specifically, a run that produced paper_ready=True via
    # verification would not be downgraded by our new gate.
    #
    # We re-drive the gate path directly to isolate this: force paper_ready
    # True, then feed a deps with no external-opt-in entry through the
    # post-synthesis re-check. The easiest way is to rely on the fact that
    # _run_synthesis_stage calls the gate inline; check that if we pass
    # deps with a NON-matching reason, paper_ready is not forced False
    # by the gate itself. Verification may still have set it False, so we
    # check by comparing to the deps=None case.
    state_with_no_deps = ResearchSessionState.create(
        session_id="sess_no_external_paper_gate_control",
        conversation_id=uuid4(),
        objective=state.objective,
    )
    state_with_no_deps.grounding = dict(state.grounding)
    state_with_no_deps.record_run(
        RunRecord(
            run_id="run_normal_01",
            iteration=0,
            metric_value=0.82,
            committed=True,
        )
    )
    _run_synthesis_stage(
        state_with_no_deps,
        workspace=SimpleNamespace(root=tmp_path / "workspace_control"),
        session=None,
        config=config,
        deps=None,
    )
    # Setting deps with an unrelated skip reason must produce the same
    # paper_ready as omitting deps entirely — the gate only fires on the
    # external_experiment_opt_in reason.
    assert state.paper_ready == state_with_no_deps.paper_ready, (
        "Gate must ignore skip reasons other than "
        "external_experiment_opt_in; got "
        f"{state.paper_ready=} vs {state_with_no_deps.paper_ready=}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
