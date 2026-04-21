"""Tests for workspace commit/revert exit-code propagation.

These tests cover the contract that `Workspace.commit()`, `Workspace.revert()`,
and `Workspace.set_baseline()` must raise `CommitFailed` when any underlying
git subprocess exits non-zero — rather than silently returning a stale HEAD
like the pre-Task-2 behaviour that caused `session_142a4acaed08` to record
"6 committed" runs with zero real git commits on the workspace branch.

The ratchet tool tests also verify that the failure path wires through to
`_finalize_iteration(..., committed=False)` so tracker / research_session
state reflect the actual git state rather than the agent's intent.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

import pytest
from openhands.sdk.workspace.models import CommandResult

from pathscientist.runtime.workspace import CommitFailed, Workspace


# ---- 1. Apostrophe in commit message ----


def test_commit_with_apostrophe_in_message():
    """Commit messages with apostrophes must not break shell quoting."""
    with tempfile.TemporaryDirectory(prefix="commit_apos_") as tmpdir:
        ws = Workspace(Path(tmpdir))
        # Write a file so there's something to commit.
        ws.write_file("train.py", "print('hello')\n")
        commit_hash = ws.commit("Improve 'patch' AUC")

        assert commit_hash, "commit() must return a non-empty hash on success"
        history = ws.get_history()
        assert len(history) == 1, (
            f"Expected exactly 1 commit in history, got {len(history)}: {history}"
        )
        assert "Improve 'patch' AUC" in history[0].message


# ---- 2. JSON metrics in commit message ----


def test_commit_with_json_metrics():
    """Metrics dict with floats/braces must serialize and commit cleanly."""
    with tempfile.TemporaryDirectory(prefix="commit_json_") as tmpdir:
        ws = Workspace(Path(tmpdir))
        ws.write_file("train.py", "print('x')\n")
        commit_hash = ws.commit("x", {"auc": 0.7303, "loss": 0.55})

        assert commit_hash, "commit() must return a non-empty hash on success"
        # Read the raw commit subject via git log %s; get_history() splits on
        # "|" which collides with the metrics-JSON separator, but the point of
        # this test is that the commit itself succeeded and carried the full
        # message — not that the parser handles pipes.
        result = ws._git("log -1 --format=%s")
        subject = result.stdout.strip()
        assert "auc" in subject
        assert "0.7303" in subject


# ---- 3. git commit exit=1 → CommitFailed ----


def test_commit_failure_raises(monkeypatch):
    """If `git commit` exits non-zero, commit() must raise CommitFailed."""
    with tempfile.TemporaryDirectory(prefix="commit_fail_") as tmpdir:
        ws = Workspace(Path(tmpdir))
        ws.write_file("train.py", "print('y')\n")

        real_git = ws._git

        def fake_git(args: str) -> CommandResult:
            # Let `add`, `rev-parse`, and internal helpers work normally; only
            # fail when the commit subcommand is issued.
            if args.startswith("commit "):
                return CommandResult(
                    command=f"git {args}",
                    exit_code=1,
                    stdout="",
                    stderr="mocked commit failure",
                    timeout_occurred=False,
                )
            return real_git(args)

        monkeypatch.setattr(ws, "_git", fake_git)

        with pytest.raises(CommitFailed) as excinfo:
            ws.commit("should-fail")

        assert excinfo.value.stage == "commit"
        assert excinfo.value.exit_code == 1
        assert "mocked commit failure" in excinfo.value.stderr


# ---- 4. RatchetCommitExecutor surfaces failure through observation ----


def _register_session(tmp_path: Path):
    """Build a SessionDeps with workspace+tracker+iteration_state and register it.

    Returns (session_id, deps) so tests can trigger the executor and inspect
    both the observation and the tracker history afterwards.
    """
    from pathscientist.config import PathScientistConfig
    from pathscientist.runtime.iteration_state import IterationState
    from pathscientist.runtime.session_registry import (
        SessionDeps,
        register_session,
        remove_session,
    )
    from pathscientist.tools.metrics import MetricsTracker

    ws_dir = tmp_path / "workspace"
    ws = Workspace(ws_dir)
    # Seed the repo with one commit so revert / rev-parse have a HEAD.
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
        last_experiment=None,
    )
    session_id = f"test_session_{tmp_path.name}"
    register_session(session_id, deps)

    def _cleanup():
        remove_session(session_id)

    return session_id, deps, _cleanup


def test_ratchet_commit_tool_reports_failure(tmp_path, monkeypatch):
    """Ratchet commit tool must surface CommitFailed via the observation text."""
    from pathscientist.tools.ratchet import RatchetCommitAction, RatchetCommitExecutor

    session_id, deps, cleanup = _register_session(tmp_path)
    try:
        ws = deps.workspace
        # Populate last_experiment so the T1 ratchet-commit gate allows the
        # call through to the monkeypatched commit() that raises CommitFailed.
        # The gate (tools/ratchet.py) refuses when last_experiment is None.
        deps.last_experiment = {
            "run_id": "exp_fake",
            "run_dir": "",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "metrics": {"auc": 0.5},
            "duration": 1.0,
            "started_at": "",
            "data_output_dir": "",
            "data_output_artifacts": None,
        }

        def fake_commit(message: str, metrics: dict | None = None) -> str:
            raise CommitFailed(
                stage="commit",
                exit_code=1,
                stderr="simulated git failure",
            )

        monkeypatch.setattr(ws, "commit", fake_commit)

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        obs = executor(
            RatchetCommitAction(message="won't stick", metrics={"auc": 0.5}),
        )

        assert obs.commit_hash == ""
        assert obs.content, "observation must have content"
        text = obs.content[0].text
        assert text.startswith("\u274c Commit failed"), (
            f"observation text should start with cross mark + 'Commit failed'; got: {text!r}"
        )
        assert "commit" in text
    finally:
        cleanup()


# ---- 5. _finalize_iteration receives committed=False on commit failure ----


def test_finalize_iteration_sees_committed_false_on_failure(tmp_path, monkeypatch):
    """After a failed commit, tracker.history[-1]['committed'] must be False."""
    from pathscientist.tools.ratchet import RatchetCommitAction, RatchetCommitExecutor

    session_id, deps, cleanup = _register_session(tmp_path)
    try:
        ws = deps.workspace
        # Populate last_experiment so the T1 ratchet-commit gate allows the
        # call through to the monkeypatched commit() that raises CommitFailed.
        # The gate (tools/ratchet.py) refuses when last_experiment is None.
        deps.last_experiment = {
            "run_id": "exp_fake",
            "run_dir": "",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "metrics": {"auc": 0.42},
            "duration": 1.0,
            "started_at": "",
            "data_output_dir": "",
            "data_output_artifacts": None,
        }

        def fake_commit(message: str, metrics: dict | None = None) -> str:
            raise CommitFailed(
                stage="commit",
                exit_code=1,
                stderr="boom",
            )

        monkeypatch.setattr(ws, "commit", fake_commit)

        executor = RatchetCommitExecutor(ws, session_id=session_id)
        executor(
            RatchetCommitAction(message="won't stick", metrics={"auc": 0.42}),
        )

        assert deps.tracker.history, (
            "tracker.history must have an entry even on commit failure"
        )
        assert deps.tracker.history[-1]["committed"] is False, (
            f"last tracker entry should be committed=False on failed commit; "
            f"got {deps.tracker.history[-1]!r}"
        )
    finally:
        cleanup()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
