"""Tests for Tasks 1 & 2: Gate ``ratchet_commit`` / ``ratchet_revert`` on a
preceding ``run_experiment``.

Motivating defect: session_b14b074d2268 (2026-04-20) had 11 committed runs
whose evidence entries all carried ``reason == "no_last_experiment"``. The
agent had called ``terminal`` + ``python train.py`` + ``ratchet_commit``
directly, bypassing ``RunExperimentTool``, so ``deps.last_experiment`` was
never populated and the evidence store never received a record.

The revert path has the same shape — the agent runs the experiment via
``terminal``, sees it crash, and calls ``ratchet_revert`` directly. The
evidence collector then has no stderr / error_type / error_hint to record
for the failed run.

The gates enforced here refuse the tool call when ``deps.last_experiment``
is ``None`` — unless the caller explicitly opts in via ``external=True``,
which Task 3 of the Tool-Gate Policy plan will later use to tag the evidence
skip reason as ``"external_experiment_opt_in"``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

import pytest

from autoresearch.config import AutoResearchConfig
from autoresearch.runtime.iteration_state import IterationState
from autoresearch.runtime.session_registry import (
    SessionDeps,
    register_session,
    remove_session,
)
from autoresearch.runtime.workspace import Workspace
from autoresearch.tools.metrics import MetricsTracker
from autoresearch.tools.ratchet import (
    RatchetCommitAction,
    RatchetCommitExecutor,
    RatchetRevertAction,
    RatchetRevertExecutor,
    _pre_revert_external_core_artifacts,
)


def _register_session(tmp_path: Path, *, last_experiment: dict | None = None):
    """Build a SessionDeps with workspace+tracker+iteration_state and register it."""
    ws_dir = tmp_path / "workspace"
    ws = Workspace(ws_dir)
    # Seed repo so HEAD exists — required for the second commit to resolve.
    ws.write_file("train.py", "print('baseline')\n")
    ws.commit("baseline")

    tracker = MetricsTracker(primary_metric="auc")
    iteration_state = IterationState(max_iterations=5)
    config = AutoResearchConfig(
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
        last_experiment=last_experiment,
    )
    session_id = f"test_gate_session_{tmp_path.name}"
    register_session(session_id, deps)

    def _cleanup():
        remove_session(session_id)

    return session_id, deps, _cleanup


def test_pre_revert_external_core_artifacts_collects_large_predictions(tmp_path):
    session_id, deps, cleanup = _register_session(tmp_path)
    try:
        run_dir = deps.workspace.root / "output" / "runs" / "run_ext"
        run_dir.mkdir(parents=True)
        (run_dir / "metrics.json").write_text("{}", encoding="utf-8")
        (run_dir / "external_test_report.json").write_text("{}", encoding="utf-8")
        predictions = run_dir / "predictions.csv"
        predictions.write_text("sample_id,score\n" + "s,0.5\n" * 10000, encoding="utf-8")
        (run_dir / "debug.tmp").write_text("ignore", encoding="utf-8")

        artifacts = _pre_revert_external_core_artifacts(
            deps.workspace,
            {"run_kind": "external_test", "run_dir": "output/runs/run_ext"},
        )

        artifact_paths = {Path(path).name: Path(path) for path in artifacts}
        assert {"metrics.json", "external_test_report.json", "predictions.csv"} <= set(artifact_paths)
        assert "debug.tmp" not in artifact_paths

        staged_predictions = artifact_paths["predictions.csv"]
        assert staged_predictions.resolve(strict=False) != predictions.resolve(strict=False)
        assert not str(staged_predictions.resolve(strict=False)).startswith(
            str(deps.workspace.root.resolve(strict=False))
        )
        assert staged_predictions.read_text(encoding="utf-8") == predictions.read_text(encoding="utf-8")
        predictions.unlink()
        assert staged_predictions.is_file()
    finally:
        cleanup()


# ---------- gate: refuse commit when last_experiment is None ----------


def test_commit_refused_without_run_experiment(tmp_path):
    """Without a preceding run_experiment, the executor must refuse the commit,
    return an actionable observation, and leave git history untouched."""
    session_id, deps, cleanup = _register_session(tmp_path, last_experiment=None)
    try:
        ws = deps.workspace
        history_before = ws.get_history()

        # Stage an uncommitted change so the only reason a commit would fail
        # (or succeed!) is the gate — not an empty-working-tree.
        ws.write_file("train.py", "print('changed')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(RatchetCommitAction(message="x"))

        assert obs.commit_hash == "", (
            f"gate must refuse commit; got commit_hash={obs.commit_hash!r}"
        )
        assert obs.content, "observation must carry explanatory content"
        text = obs.content[0].text
        assert text.startswith("\u274c ratchet_commit requires a preceding run_experiment"), (
            f"observation must start with the canonical gate message; got: {text!r}"
        )

        history_after = ws.get_history()
        assert history_after == history_before, (
            f"gate must not create a commit; "
            f"before={history_before!r} after={history_after!r}"
        )
    finally:
        cleanup()


# ---------- opt-in: external=True bypasses the gate ----------


def test_commit_allowed_when_external_flag_set(tmp_path):
    """With ``external=True``, the executor must proceed even when
    ``deps.last_experiment`` is None — this is the documented escape hatch
    for long-running jobs run outside RunExperimentTool."""
    session_id, deps, cleanup = _register_session(tmp_path, last_experiment=None)
    try:
        ws = deps.workspace
        ws.write_file("train.py", "print('external run')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(RatchetCommitAction(message="x", external=True))

        assert obs.commit_hash, (
            f"external=True must allow the commit; got commit_hash={obs.commit_hash!r}, "
            f"content={obs.content!r}"
        )
    finally:
        cleanup()


# ---------- normal path: last_experiment populated allows commit ----------


def test_commit_allowed_when_last_experiment_present(tmp_path):
    """When ``run_experiment`` has populated ``deps.last_experiment``, the
    gate must let the commit through without needing ``external=True``."""
    last_experiment = {
        "run_id": "exp_test_001",
        "run_dir": "output/runs/exp_test_001",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "metrics": {"auc": 0.85},
        "duration": 1.0,
        "started_at": "2026-04-18T00:00:00Z",
        "data_output_dir": "",
        "data_output_artifacts": None,
    }
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        ws = deps.workspace
        ws.write_file("train.py", "print('improved')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(
            RatchetCommitAction(message="x", metrics={"auc": 0.85})
        )

        assert obs.commit_hash, (
            f"a preceding run_experiment must unlock the commit; "
            f"got commit_hash={obs.commit_hash!r}, content={obs.content!r}"
        )
    finally:
        cleanup()


# ---------- observation text is actionable ----------


def test_commit_observation_is_actionable(tmp_path):
    """The refusal message must point the agent at ``run_experiment`` and
    must NOT advertise the ``external=true`` escape hatch in agent-facing
    text: we don't want the LLM to reach for the bypass as its first
    recovery move. The escape hatch stays documented on the action schema
    only (for human / tool-author reference)."""
    session_id, deps, cleanup = _register_session(tmp_path, last_experiment=None)
    try:
        ws = deps.workspace
        ws.write_file("train.py", "print('changed')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(RatchetCommitAction(message="x"))

        assert obs.content, "observation must carry explanatory content"
        text = obs.content[0].text
        assert "run_experiment" in text, (
            f"observation must point at run_experiment; got: {text!r}"
        )
        assert "external=true" not in text, (
            f"refusal text must NOT advertise external=true escape hatch "
            f"(keeps the bypass off the agent's primary recovery path); "
            f"got: {text!r}"
        )
    finally:
        cleanup()


# ---------- gate: refuse revert when last_experiment is None ----------


def test_revert_refused_without_run_experiment(tmp_path):
    """Without a preceding run_experiment, the revert executor must refuse,
    return an actionable observation, and leave workspace state untouched.

    The motivating shape: agent runs ``python train.py`` via ``terminal``,
    sees it crash, and calls ``ratchet_revert`` directly — the evidence
    collector has no stderr/error_type/error_hint to capture.
    """
    session_id, deps, cleanup = _register_session(tmp_path, last_experiment=None)
    try:
        ws = deps.workspace
        # Stage an uncommitted change so there's something that WOULD be
        # reverted if the gate didn't fire.
        ws.write_file("train.py", "print('broken')\n")
        head_before = ws.get_current_commit()
        train_contents_before = (ws.root / "train.py").read_text(encoding="utf-8")

        executor = RatchetRevertExecutor(ws, session_id=session_id)
        obs = executor(RatchetRevertAction(reason="x"))

        assert obs.reverted_to == "", (
            f"gate must refuse revert; got reverted_to={obs.reverted_to!r}"
        )
        assert obs.content, "observation must carry explanatory content"
        text = obs.content[0].text
        assert text.startswith("\u274c ratchet_revert requires a preceding run_experiment"), (
            f"observation must start with the canonical gate message; got: {text!r}"
        )

        # Workspace state must be unchanged — the revert did NOT fire.
        head_after = ws.get_current_commit()
        assert head_after == head_before, (
            f"gate must not change HEAD; before={head_before!r} after={head_after!r}"
        )
        train_contents_after = (ws.root / "train.py").read_text(encoding="utf-8")
        assert train_contents_after == train_contents_before, (
            "gate must not revert the uncommitted change; "
            f"before={train_contents_before!r} after={train_contents_after!r}"
        )
    finally:
        cleanup()


# ---------- opt-in: external=True bypasses the revert gate ----------


def test_revert_allowed_when_external_flag_set(tmp_path):
    """With ``external=True``, the revert executor must proceed even when
    ``deps.last_experiment`` is None — mirroring the commit escape hatch."""
    session_id, deps, cleanup = _register_session(tmp_path, last_experiment=None)
    try:
        ws = deps.workspace
        # Stage an uncommitted change so revert has something to undo.
        ws.write_file("train.py", "print('broken')\n")

        executor = RatchetRevertExecutor(ws, session_id=session_id)
        obs = executor(RatchetRevertAction(reason="x", external=True))

        assert obs.reverted_to, (
            f"external=True must allow the revert; got reverted_to={obs.reverted_to!r}, "
            f"content={obs.content!r}"
        )
        # The uncommitted change must have been undone.
        train_after = (ws.root / "train.py").read_text(encoding="utf-8")
        assert train_after == "print('baseline')\n", (
            f"revert must have restored the baseline contents; got {train_after!r}"
        )
    finally:
        cleanup()


# ---------- normal path: last_experiment populated allows revert ----------


def test_revert_allowed_when_last_experiment_present(tmp_path):
    """When ``run_experiment`` has populated ``deps.last_experiment``, the
    gate must let the revert through without needing ``external=True``."""
    last_experiment = {
        "run_id": "exp_test_002",
        "run_dir": "output/runs/exp_test_002",
        "exit_code": 1,  # failed run — typical revert scenario
        "stdout": "",
        "stderr": "RuntimeError: boom",
        "metrics": {},
        "duration": 0.5,
        "started_at": "2026-04-18T00:00:00Z",
        "data_output_dir": "",
        "data_output_artifacts": None,
    }
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        ws = deps.workspace
        ws.write_file("train.py", "print('broken')\n")

        executor = RatchetRevertExecutor(ws, session_id=session_id)
        obs = executor(RatchetRevertAction(reason="x"))

        assert obs.reverted_to, (
            f"a preceding run_experiment must unlock the revert; "
            f"got reverted_to={obs.reverted_to!r}, content={obs.content!r}"
        )
    finally:
        cleanup()


# ---------- revert observation text is actionable ----------


def test_revert_observation_is_actionable(tmp_path):
    """The refusal message must point the agent at ``run_experiment`` and
    must NOT advertise the ``external=true`` escape hatch. Symmetric to
    the commit-side test: we don't want the LLM reaching for the bypass
    as its first recovery move."""
    session_id, deps, cleanup = _register_session(tmp_path, last_experiment=None)
    try:
        ws = deps.workspace
        ws.write_file("train.py", "print('broken')\n")

        executor = RatchetRevertExecutor(ws, session_id=session_id)
        obs = executor(RatchetRevertAction(reason="x"))

        assert obs.content, "observation must carry explanatory content"
        text = obs.content[0].text
        assert "run_experiment" in text, (
            f"observation must point at run_experiment; got: {text!r}"
        )
        assert "external=true" not in text, (
            f"refusal text must NOT advertise external=true escape hatch "
            f"(keeps the bypass off the agent's primary recovery path); "
            f"got: {text!r}"
        )
    finally:
        cleanup()


# ---------- Fix A (2026-04-21 post-fix review, Finding 1): stale last_experiment ----------
#
# The recent tool-gate only checks that *some* ``deps.last_experiment`` exists.
# It does not verify that this experiment record matches the current
# ``iteration_state.last_run_id``. Concrete local reproduction from the review:
#
#   deps.last_experiment["run_id"] = "run_old1111"
#   deps.iteration_state.last_run_id = "run_new2222"
#   edited train.py
#   called RatchetCommitExecutor(...)
#
# Observed: tracker recorded run_new2222, evidence landed under
# .evidence/runs/run_old1111/ — tracker vs. evidence lineage split.
#
# The fix: refuse ratchet when ``last_experiment["run_id"]`` and
# ``iteration_state.last_run_id`` are both populated but differ. ``external=True``
# bypasses the mismatch gate (external runs don't carry a matching iteration
# state run_id, they went through their own flow).


def test_commit_refused_when_last_experiment_run_id_is_stale(tmp_path):
    """Reproduces the review's Finding 1 scenario: last_experiment["run_id"]
    differs from iteration_state.last_run_id — commit must refuse so evidence
    and tracker don't split lineage."""
    last_experiment = {
        "run_id": "run_old1111",
        "run_dir": "output/runs/run_old1111",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "metrics": {"auc": 0.80},
        "duration": 1.0,
        "started_at": "2026-04-18T00:00:00Z",
        "data_output_dir": "",
        "data_output_artifacts": None,
    }
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        # Simulate that a newer run_experiment has bumped the canonical run_id
        # without refreshing last_experiment.
        deps.iteration_state.last_run_id = "run_new2222"

        ws = deps.workspace
        history_before = ws.get_history()
        tracker_len_before = len(deps.tracker.history)

        # Stage an uncommitted change so the only reason a commit would
        # fail (or succeed!) is the stale-run_id gate.
        ws.write_file("train.py", "print('changed')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(RatchetCommitAction(message="x"))

        assert obs.commit_hash == "", (
            f"stale-run_id gate must refuse commit; got commit_hash={obs.commit_hash!r}"
        )
        assert obs.content, "observation must carry explanatory content"
        text = obs.content[0].text
        assert text.startswith(
            "\u274c ratchet_commit refused: last_experiment is stale"
        ), (
            f"observation must start with the canonical stale-gate message; got: {text!r}"
        )
        assert "run_old1111" in text, (
            f"observation must mention the stale last_experiment run_id; got: {text!r}"
        )
        assert "run_new2222" in text, (
            f"observation must mention the current iteration_state run_id; got: {text!r}"
        )

        # Workspace history unchanged — no commit was created.
        history_after = ws.get_history()
        assert history_after == history_before, (
            f"gate must not create a commit; "
            f"before={history_before!r} after={history_after!r}"
        )
        # Tracker history unchanged — no record appended.
        assert len(deps.tracker.history) == tracker_len_before, (
            f"gate must not record a tracker entry; "
            f"before={tracker_len_before} after={len(deps.tracker.history)}"
        )
    finally:
        cleanup()


def test_commit_allowed_when_last_experiment_matches_iteration_state(tmp_path):
    """Happy path — last_experiment["run_id"] matches
    iteration_state.last_run_id — commit proceeds normally."""
    last_experiment = {
        "run_id": "run_abcdef01",
        "run_dir": "output/runs/run_abcdef01",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "metrics": {"auc": 0.87},
        "duration": 1.0,
        "started_at": "2026-04-18T00:00:00Z",
        "data_output_dir": "",
        "data_output_artifacts": None,
    }
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        # run_ids match — typical state after RunExperimentTool completes.
        deps.iteration_state.last_run_id = "run_abcdef01"

        ws = deps.workspace
        tracker_len_before = len(deps.tracker.history)

        ws.write_file("train.py", "print('improved')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(
            RatchetCommitAction(message="x", metrics={"auc": 0.87})
        )

        assert obs.commit_hash, (
            f"matched run_ids must unlock the commit; "
            f"got commit_hash={obs.commit_hash!r}, content={obs.content!r}"
        )
        # Tracker history grew by exactly one entry.
        assert len(deps.tracker.history) == tracker_len_before + 1, (
            f"commit must append exactly one tracker entry; "
            f"before={tracker_len_before} after={len(deps.tracker.history)}"
        )
    finally:
        cleanup()


def test_commit_bypassed_on_stale_when_external_set(tmp_path):
    """With ``external=True`` the mismatch gate is bypassed — documented
    escape hatch for commits that didn't go through run_experiment."""
    last_experiment = {
        "run_id": "run_old1111",
        "run_dir": "output/runs/run_old1111",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "metrics": {"auc": 0.80},
        "duration": 1.0,
        "started_at": "2026-04-18T00:00:00Z",
        "data_output_dir": "",
        "data_output_artifacts": None,
    }
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        deps.iteration_state.last_run_id = "run_new2222"

        ws = deps.workspace
        ws.write_file("train.py", "print('external')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(RatchetCommitAction(message="x", external=True))

        assert obs.commit_hash, (
            f"external=True must bypass the stale-run_id gate; "
            f"got commit_hash={obs.commit_hash!r}, content={obs.content!r}"
        )
    finally:
        cleanup()


def test_revert_refused_when_last_experiment_run_id_is_stale(tmp_path):
    """Symmetric: revert must also refuse the stale-run_id shape so a failed
    experiment's evidence doesn't land under the wrong run_id."""
    last_experiment = {
        "run_id": "run_old1111",
        "run_dir": "output/runs/run_old1111",
        "exit_code": 1,
        "stdout": "",
        "stderr": "RuntimeError: boom",
        "metrics": {},
        "duration": 0.5,
        "started_at": "2026-04-18T00:00:00Z",
        "data_output_dir": "",
        "data_output_artifacts": None,
    }
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        deps.iteration_state.last_run_id = "run_new2222"

        ws = deps.workspace
        # Stage uncommitted change that WOULD be reverted if the gate didn't fire.
        ws.write_file("train.py", "print('broken')\n")
        head_before = ws.get_current_commit()
        train_contents_before = (ws.root / "train.py").read_text(encoding="utf-8")
        tracker_len_before = len(deps.tracker.history)

        executor = RatchetRevertExecutor(ws, session_id=session_id)
        obs = executor(RatchetRevertAction(reason="x"))

        assert obs.reverted_to == "", (
            f"stale-run_id gate must refuse revert; got reverted_to={obs.reverted_to!r}"
        )
        assert obs.content, "observation must carry explanatory content"
        text = obs.content[0].text
        assert text.startswith(
            "\u274c ratchet_revert refused: last_experiment is stale"
        ), (
            f"observation must start with the canonical stale-gate message; got: {text!r}"
        )
        assert "run_old1111" in text, (
            f"observation must mention the stale last_experiment run_id; got: {text!r}"
        )
        assert "run_new2222" in text, (
            f"observation must mention the current iteration_state run_id; got: {text!r}"
        )

        # Workspace state unchanged — the revert did NOT fire.
        head_after = ws.get_current_commit()
        assert head_after == head_before, (
            f"gate must not change HEAD; before={head_before!r} after={head_after!r}"
        )
        train_contents_after = (ws.root / "train.py").read_text(encoding="utf-8")
        assert train_contents_after == train_contents_before, (
            "gate must not revert the uncommitted change; "
            f"before={train_contents_before!r} after={train_contents_after!r}"
        )
        # Tracker history unchanged.
        assert len(deps.tracker.history) == tracker_len_before, (
            f"gate must not record a tracker entry; "
            f"before={tracker_len_before} after={len(deps.tracker.history)}"
        )
    finally:
        cleanup()


# ---------- Findings 1, 2, 3, 6 (2026-04-22 session review): artifact metrics ----------
#
# Root cause: ratchet_commit trusts the LLM-supplied action.metrics dict as
# authoritative, instead of reading from the actual experiment artifact captured
# by RunExperimentTool. Consequences in session 8e48c15d38cb:
#   - tracker/report says auc=0.8643, real artifact says auc=0.8414
#   - "best result" 0.8643 was a 2-epoch quick_check, not a full run
#   - run_f32a1b74 had exit_code=-1 / error_type="Unknown" but was committed
#   - 3 runs with byte-identical code produced 3 different real AUCs — stale
#     quick_check numbers being copy-pasted into action.metrics
#
# Fix: three new gates on RatchetCommitExecutor:
#   A. refuse when deps.last_experiment.quick_check is True
#   B. refuse when exit_code != 0 OR error_type is non-empty
#   C. source tracker / _finalize_iteration metrics from
#      deps.last_experiment["metrics"] (artifact) instead of action.metrics.
#      Warn if the two disagree by > 0.5pp on the primary metric.
# external=True bypasses A and B (same contract as existing gates).


def test_commit_refused_when_last_experiment_was_quick_check(tmp_path):
    """Gate A: quick_check runs are 2-epoch sanity checks and must not be
    committed as scientific results. The gate fires BEFORE the
    last_experiment-None / stale-run_id gates."""
    last_experiment = {
        "run_id": "run_quick001",
        "run_dir": "output/runs/run_quick001",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "metrics": {"auc": 0.85},
        "duration": 1.0,
        "started_at": "2026-04-22T00:00:00Z",
        "data_output_dir": "",
        "data_output_artifacts": None,
        "quick_check": True,   # <-- the signal the gate reads
        "error_type": "",
    }
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        deps.iteration_state.last_run_id = "run_quick001"
        ws = deps.workspace
        history_before = ws.get_history()
        tracker_len_before = len(deps.tracker.history)

        ws.write_file("train.py", "print('changed')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(RatchetCommitAction(message="x", metrics={"auc": 0.85}))

        assert obs.commit_hash == "", (
            f"quick_check gate must refuse commit; got commit_hash={obs.commit_hash!r}"
        )
        text = obs.content[0].text
        assert text.startswith(
            "❌ ratchet_commit refused: last_experiment was a quick_check run"
        ), (
            f"observation must start with the canonical quick_check-gate message; got: {text!r}"
        )
        assert "quick_check=false" in text, (
            f"observation must tell the agent how to recover (quick_check=false); got: {text!r}"
        )
        # Workspace history unchanged.
        assert ws.get_history() == history_before, (
            "gate must not create a commit"
        )
        # Tracker unchanged.
        assert len(deps.tracker.history) == tracker_len_before, (
            "gate must not record a tracker entry"
        )
    finally:
        cleanup()


def test_commit_refused_when_last_experiment_failed(tmp_path):
    """Gate B: runs with non-zero exit_code or non-empty error_type did not
    complete cleanly — they must be reverted, not committed. The gate fires
    BEFORE the last_experiment-None / stale-run_id gates."""
    # Scenario 1: non-zero exit_code (even with empty error_type).
    last_experiment = {
        "run_id": "run_fail001",
        "run_dir": "output/runs/run_fail001",
        "exit_code": -1,
        "stdout": "",
        "stderr": "RuntimeError: boom",
        "metrics": {},
        "duration": 0.5,
        "started_at": "2026-04-22T00:00:00Z",
        "data_output_dir": "",
        "data_output_artifacts": None,
        "quick_check": False,
        "error_type": "Unknown",
    }
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        deps.iteration_state.last_run_id = "run_fail001"
        ws = deps.workspace
        history_before = ws.get_history()
        tracker_len_before = len(deps.tracker.history)

        ws.write_file("train.py", "print('changed')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(RatchetCommitAction(message="x"))

        assert obs.commit_hash == "", (
            f"failed-run gate must refuse commit; got commit_hash={obs.commit_hash!r}"
        )
        text = obs.content[0].text
        assert text.startswith(
            "❌ ratchet_commit refused: last_experiment did not complete cleanly"
        ), (
            f"observation must start with the canonical failed-run-gate message; got: {text!r}"
        )
        assert "-1" in text, (
            f"observation must include exit_code; got: {text!r}"
        )
        assert "Unknown" in text, (
            f"observation must include error_type; got: {text!r}"
        )
        assert "ratchet_revert" in text, (
            f"observation must point the agent at ratchet_revert; got: {text!r}"
        )
        assert ws.get_history() == history_before, (
            "gate must not create a commit"
        )
        assert len(deps.tracker.history) == tracker_len_before, (
            "gate must not record a tracker entry"
        )
    finally:
        cleanup()


def test_commit_refused_when_exit_code_zero_but_error_type_set(tmp_path):
    """Gate B variant: exit_code == 0 but error_type non-empty (shouldn't
    happen in practice, but we treat it as a failure for defense-in-depth)."""
    last_experiment = {
        "run_id": "run_fail002",
        "run_dir": "output/runs/run_fail002",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "metrics": {"auc": 0.5},
        "duration": 0.5,
        "started_at": "2026-04-22T00:00:00Z",
        "data_output_dir": "",
        "data_output_artifacts": None,
        "quick_check": False,
        "error_type": "ShapeMismatch",  # non-empty → treat as failure
    }
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        deps.iteration_state.last_run_id = "run_fail002"
        ws = deps.workspace
        ws.write_file("train.py", "print('changed')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(RatchetCommitAction(message="x"))

        assert obs.commit_hash == "", (
            f"non-empty error_type must refuse commit; got commit_hash={obs.commit_hash!r}"
        )
        text = obs.content[0].text
        assert "ShapeMismatch" in text, (
            f"observation must include error_type; got: {text!r}"
        )
    finally:
        cleanup()


def test_commit_uses_artifact_metrics_not_action_metrics(tmp_path):
    """Gate C: the tracker must record deps.last_experiment["metrics"]
    (artifact values) instead of action.metrics (LLM-supplied). Reproduces
    the review's Finding 1 scenario: action.metrics.auc=0.8643 but
    artifact.metrics.auc=0.8414 → tracker must show 0.8414."""
    last_experiment = {
        "run_id": "run_truth01",
        "run_dir": "output/runs/run_truth01",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "metrics": {"auc": 0.8414, "f1": 0.80},   # <-- truth
        "duration": 1.0,
        "started_at": "2026-04-22T00:00:00Z",
        "data_output_dir": "",
        "data_output_artifacts": None,
        "quick_check": False,
        "error_type": "",
    }
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        deps.iteration_state.last_run_id = "run_truth01"
        ws = deps.workspace
        ws.write_file("train.py", "print('improved')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        # LLM-supplied metrics lie — this is the whole point of the gate.
        obs = executor(
            RatchetCommitAction(message="x", metrics={"auc": 0.8643})
        )

        assert obs.commit_hash, (
            f"well-formed last_experiment must unlock the commit; "
            f"got commit_hash={obs.commit_hash!r}, content={obs.content!r}"
        )

        # Tracker must carry the artifact value, not the action-supplied lie.
        assert deps.tracker.history, "tracker must have at least one entry"
        last_entry = deps.tracker.history[-1]
        recorded_metrics = last_entry.get("metrics", {})
        assert recorded_metrics.get("auc") == 0.8414, (
            f"tracker must record artifact auc=0.8414, not action.metrics auc=0.8643; "
            f"got {recorded_metrics!r}"
        )
    finally:
        cleanup()


def test_commit_warns_on_metric_disagreement(tmp_path):
    """Gate C warning: when action.metrics disagrees with artifact.metrics
    by > 0.5pp on the primary metric, the observation must carry a warning
    line so the agent sees the discrepancy."""
    last_experiment = {
        "run_id": "run_warn001",
        "run_dir": "output/runs/run_warn001",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "metrics": {"auc": 0.8414},
        "duration": 1.0,
        "started_at": "2026-04-22T00:00:00Z",
        "data_output_dir": "",
        "data_output_artifacts": None,
        "quick_check": False,
        "error_type": "",
    }
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        deps.iteration_state.last_run_id = "run_warn001"
        ws = deps.workspace
        ws.write_file("train.py", "print('improved')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(
            # Discrepancy: 0.8643 vs 0.8414 = 2.29pp > 0.5pp threshold.
            RatchetCommitAction(message="x", metrics={"auc": 0.8643})
        )

        assert obs.commit_hash, "commit should still succeed (warning, not refusal)"
        text = obs.content[0].text
        assert "⚠" in text or "warning" in text.lower() or "differs" in text.lower(), (
            f"observation must carry a warning about the metric disagreement; got: {text!r}"
        )
        assert "0.8643" in text and "0.8414" in text, (
            f"observation must include both values; got: {text!r}"
        )
    finally:
        cleanup()


def test_commit_no_warning_when_metrics_agree(tmp_path):
    """No warning when action.metrics and artifact.metrics agree within 0.5pp."""
    last_experiment = {
        "run_id": "run_agree01",
        "run_dir": "output/runs/run_agree01",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "metrics": {"auc": 0.8643},
        "duration": 1.0,
        "started_at": "2026-04-22T00:00:00Z",
        "data_output_dir": "",
        "data_output_artifacts": None,
        "quick_check": False,
        "error_type": "",
    }
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        deps.iteration_state.last_run_id = "run_agree01"
        ws = deps.workspace
        ws.write_file("train.py", "print('improved')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(
            # Well within 0.5pp — values match.
            RatchetCommitAction(message="x", metrics={"auc": 0.8643})
        )

        assert obs.commit_hash, "commit should succeed"
        text = obs.content[0].text
        assert "differs" not in text.lower(), (
            f"observation must NOT carry a disagreement warning; got: {text!r}"
        )
    finally:
        cleanup()


def test_commit_external_flag_bypasses_quick_check_gate(tmp_path):
    """external=True must bypass Gate A: quick_check refusal."""
    last_experiment = {
        "run_id": "run_quick002",
        "run_dir": "output/runs/run_quick002",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "metrics": {"auc": 0.85},
        "duration": 1.0,
        "started_at": "2026-04-22T00:00:00Z",
        "data_output_dir": "",
        "data_output_artifacts": None,
        "quick_check": True,
        "error_type": "",
    }
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        deps.iteration_state.last_run_id = "run_quick002"
        ws = deps.workspace
        ws.write_file("train.py", "print('external quick check')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(
            RatchetCommitAction(message="x", metrics={"auc": 0.85}, external=True)
        )

        assert obs.commit_hash, (
            f"external=True must bypass the quick_check gate; "
            f"got commit_hash={obs.commit_hash!r}, content={obs.content!r}"
        )
    finally:
        cleanup()


def test_commit_external_flag_bypasses_failed_run_gate(tmp_path):
    """external=True must bypass Gate B: failed-run refusal."""
    last_experiment = {
        "run_id": "run_fail003",
        "run_dir": "output/runs/run_fail003",
        "exit_code": -1,
        "stdout": "",
        "stderr": "RuntimeError: boom",
        "metrics": {},
        "duration": 0.5,
        "started_at": "2026-04-22T00:00:00Z",
        "data_output_dir": "",
        "data_output_artifacts": None,
        "quick_check": False,
        "error_type": "Unknown",
    }
    session_id, deps, cleanup = _register_session(
        tmp_path, last_experiment=last_experiment
    )
    try:
        deps.iteration_state.last_run_id = "run_fail003"
        ws = deps.workspace
        ws.write_file("train.py", "print('external, human knows what they are doing')\n")

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(
            RatchetCommitAction(message="x", external=True)
        )

        assert obs.commit_hash, (
            f"external=True must bypass the failed-run gate; "
            f"got commit_hash={obs.commit_hash!r}, content={obs.content!r}"
        )
    finally:
        cleanup()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
