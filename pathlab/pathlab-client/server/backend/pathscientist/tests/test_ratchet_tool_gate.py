"""Tests for Task 1: Gate ``ratchet_commit`` on a preceding ``run_experiment``.

Motivating defect: session_b14b074d2268 (2026-04-20) had 11 committed runs
whose evidence entries all carried ``reason == "no_last_experiment"``. The
agent had called ``terminal`` + ``python train.py`` + ``ratchet_commit``
directly, bypassing ``RunExperimentTool``, so ``deps.last_experiment`` was
never populated and the evidence store never received a record.

The gate enforced here refuses the commit when ``deps.last_experiment`` is
``None`` — unless the caller explicitly opts in via ``external=True``, which
Task 3 of the Tool-Gate Policy plan will later use to tag the evidence skip
reason as ``"external_experiment_opt_in"``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

import pytest

from pathscientist.config import PathScientistConfig
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


def _register_session(tmp_path: Path, *, last_experiment: dict | None = None):
    """Build a SessionDeps with workspace+tracker+iteration_state and register it."""
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
        last_experiment=last_experiment,
    )
    session_id = f"test_gate_session_{tmp_path.name}"
    register_session(session_id, deps)

    def _cleanup():
        remove_session(session_id)

    return session_id, deps, _cleanup


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
    """The refusal message must name both the required tool (``run_experiment``)
    and the documented escape hatch (``external=true``) so the agent can
    self-recover without reading the plan."""
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
        assert "external=true" in text, (
            f"observation must document the external=true escape hatch; got: {text!r}"
        )
    finally:
        cleanup()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
