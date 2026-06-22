"""Tests for Task 4: Evidence collection — surface failures, never silent.

Motivating defect: session_142a4acaed08 had ``.evidence/runs/`` empty despite 6
"committed" runs, and no log evidence of why. The previous implementation
swallowed every ``EvidenceCollector.finalize()`` exception behind
``logging.warning`` with no surfacing of *why* a run was skipped.

This test module guarantees that the three failure modes
(no ``last_experiment``, no ``workspace``, underlying store exception) each
append a structured ``{run_id, reason}`` entry to
``deps.evidence_skipped_runs`` so the IntegrityGuard can flag committed runs
whose evidence is missing with an actionable reason.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

import pytest

from pathscientist.evidence.collector import (
    EvidenceCollector,
    EvidenceFinalizeResult,
)
from pathscientist.evidence.store import EvidenceStore
from pathscientist.runtime.iteration_state import IterationState
from pathscientist.runtime.session_registry import (
    SessionDeps,
    register_session,
    remove_session,
)
from pathscientist.tools.metrics import MetricsTracker
from pathscientist.tools.ratchet import _finalize_iteration


# ---------- helpers ----------


class _FakeWorkspace:
    """Minimal workspace stub exposing a ``root`` Path like the real thing."""

    def __init__(self, root: Path):
        self.root = Path(root)


def _init_git_repo(path: Path) -> None:
    """Initialize a git repository with an initial commit so git_diff works."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "train.py").write_text("print('hello')\n", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test Runner"],
        cwd=path, check=True, capture_output=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial", "--quiet"],
        cwd=path, check=True, capture_output=True,
    )


def _make_session(
    session_id: str,
    *,
    workspace: object | None = None,
    last_experiment: dict | None = None,
) -> SessionDeps:
    """Build a minimal SessionDeps for the registry."""
    tracker = MetricsTracker(primary_metric="auc")
    iteration_state = IterationState(max_iterations=5)
    deps = SessionDeps(
        workspace=workspace,
        tracker=tracker,
        config=None,
        iteration_state=iteration_state,
        conversation=None,
        last_experiment=last_experiment,
    )
    register_session(session_id, deps)
    return deps


# ---------- skip-reason surfacing in _finalize_iteration ----------


def test_missing_last_experiment_records_skip_reason():
    """When deps.last_experiment is None, finalization must record
    ``no_last_experiment`` on ``deps.evidence_skipped_runs``."""
    session_id = "test_missing_last_experiment_session"
    deps = _make_session(session_id, workspace=_FakeWorkspace(Path("/tmp")))
    try:
        assert deps.last_experiment is None
        assert deps.evidence_skipped_runs == []

        _finalize_iteration(session_id, metrics={"auc": 0.6}, committed=True)

        assert len(deps.evidence_skipped_runs) == 1
        entry = deps.evidence_skipped_runs[-1]
        assert entry["reason"] == "no_last_experiment"
        assert entry["run_id"]  # canonical run_id must be attached
        assert entry["run_id"] == deps.iteration_state.finalized_run_ids[-1]
    finally:
        remove_session(session_id)


def test_external_flag_records_opt_in_reason():
    """When ``deps.last_experiment`` is None and the caller opted in via
    ``action_external=True``, the skip reason must be
    ``"external_experiment_opt_in"`` rather than ``"no_last_experiment"``.
    This distinguishes a deliberate out-of-band experiment (warning) from a
    silent policy bypass (fatal) in the IntegrityGuard."""
    session_id = "test_external_opt_in_session"
    deps = _make_session(session_id, workspace=_FakeWorkspace(Path("/tmp")))
    try:
        assert deps.last_experiment is None
        assert deps.evidence_skipped_runs == []

        _finalize_iteration(
            session_id,
            metrics={"auc": 0.8},
            committed=True,
            action_external=True,
        )

        assert len(deps.evidence_skipped_runs) == 1
        entry = deps.evidence_skipped_runs[-1]
        assert entry["reason"] == "external_experiment_opt_in", (
            f"external=True must tag the skip as external_experiment_opt_in; "
            f"got {entry['reason']!r}"
        )
        assert entry["run_id"]  # canonical run_id still attached
        assert entry["run_id"] == deps.iteration_state.finalized_run_ids[-1]
    finally:
        remove_session(session_id)


def test_external_flag_default_false_keeps_no_last_experiment_reason():
    """Regression guard: without action_external (or action_external=False),
    the existing ``no_last_experiment`` reason must still be written — the
    new kwarg is additive, not a behavior-change for the default path."""
    session_id = "test_external_default_false_session"
    deps = _make_session(session_id, workspace=_FakeWorkspace(Path("/tmp")))
    try:
        _finalize_iteration(
            session_id,
            metrics={"auc": 0.6},
            committed=True,
            action_external=False,
        )

        assert len(deps.evidence_skipped_runs) == 1
        assert deps.evidence_skipped_runs[-1]["reason"] == "no_last_experiment"
    finally:
        remove_session(session_id)


def test_missing_workspace_records_skip_reason():
    """When deps.workspace is None but last_experiment exists, finalization must
    record ``no_workspace`` on ``deps.evidence_skipped_runs``."""
    session_id = "test_missing_workspace_session"
    deps = _make_session(
        session_id,
        workspace=None,
        last_experiment={
            "run_id": "exp_abc123",
            "run_dir": "output/runs/exp_abc123",
            "metrics": {"auc": 0.7},
        },
    )
    try:
        _finalize_iteration(session_id, metrics={"auc": 0.7}, committed=True)

        assert len(deps.evidence_skipped_runs) == 1
        entry = deps.evidence_skipped_runs[-1]
        assert entry["reason"] == "no_workspace"
        assert entry["run_id"]
    finally:
        remove_session(session_id)


def test_evidence_finalize_exception_records_skip_reason(monkeypatch, tmp_path):
    """When EvidenceStore.save raises, _finalize_iteration must capture the
    exception into deps.evidence_skipped_runs with ``exception:<Type>:<msg>``."""
    workspace_dir = tmp_path / "workspace"
    _init_git_repo(workspace_dir)

    session_id = "test_evidence_exception_session"
    deps = _make_session(
        session_id,
        workspace=_FakeWorkspace(workspace_dir),
        last_experiment={
            "run_id": "exp_xyz789",
            "run_dir": "output/runs/exp_xyz789",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "metrics": {"auc": 0.8},
            "duration": 1.0,
            "started_at": "2026-04-18T00:00:00Z",
            "data_output_dir": "",
            "data_output_artifacts": None,
        },
    )

    def _boom(self, record):
        raise OSError("disk full")

    monkeypatch.setattr(EvidenceStore, "save", _boom)

    # Pre-seed iteration_state.last_run_id so we can assert the skip entry
    # uses the same canonical run_id as the tracker / finalized_run_ids list.
    deps.iteration_state.last_run_id = "exp_xyz789"

    try:
        _finalize_iteration(session_id, metrics={"auc": 0.8}, committed=True)

        assert len(deps.evidence_skipped_runs) == 1
        entry = deps.evidence_skipped_runs[-1]
        assert entry["reason"].startswith("exception:OSError:")
        assert "disk full" in entry["reason"]
        # The skip entry must tag the canonical run_id so IntegrityGuard can
        # cross-reference it against tracker.history / finalized_run_ids.
        assert entry["run_id"] == "exp_xyz789"
        assert deps.iteration_state.finalized_run_ids[-1] == "exp_xyz789"
    finally:
        remove_session(session_id)


# ---------- happy path returns a record path ----------


def test_happy_path_writes_record(tmp_path):
    """A healthy finalize() must return EvidenceFinalizeResult with a
    non-empty record_path pointing to the written record.json."""
    workspace_dir = tmp_path / "workspace"
    _init_git_repo(workspace_dir)
    store = EvidenceStore(tmp_path / ".evidence")

    collector = EvidenceCollector(
        workspace_root=workspace_dir,
        store=store,
        session_id="s_happy",
        primary_metric="auc",
    )
    collector.record_experiment_output(
        run_id="run_happy_1",
        run_dir="output/runs/run_happy_1",
        exit_code=0,
        stdout="done",
        stderr="",
        metrics={"auc": 0.87},
        duration=10.0,
    )

    result = collector.finalize(committed=True, iteration=0)

    assert isinstance(result, EvidenceFinalizeResult)
    assert result.skipped is False
    assert result.skipped_reason == ""
    assert result.record_path
    assert Path(result.record_path).exists()
    # Path must end with .../runs/run_happy_1/record.json
    assert Path(result.record_path).name == "record.json"
    assert Path(result.record_path).parent.name == "run_happy_1"


def test_happy_path_through_finalize_iteration_does_not_log_skip(tmp_path):
    """Integration: the full _finalize_iteration happy path must NOT append
    anything to evidence_skipped_runs, and must write an on-disk record."""
    workspace_dir = tmp_path / "workspace"
    _init_git_repo(workspace_dir)

    session_id = "test_finalize_happy_session"
    deps = _make_session(
        session_id,
        workspace=_FakeWorkspace(workspace_dir),
        last_experiment={
            "run_id": "exp_happy_int",
            "run_dir": "output/runs/exp_happy_int",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "metrics": {"auc": 0.9},
            "duration": 2.0,
            "started_at": "2026-04-18T00:00:00Z",
            "data_output_dir": "",
            "data_output_artifacts": None,
        },
    )

    try:
        _finalize_iteration(session_id, metrics={"auc": 0.9}, committed=True)

        assert deps.evidence_skipped_runs == []
        # Evidence record should exist on disk.
        evidence_record = (
            workspace_dir / ".evidence" / "runs" / "exp_happy_int" / "record.json"
        )
        assert evidence_record.exists()
        # last_experiment must be cleared after collection.
        assert deps.last_experiment is None
    finally:
        remove_session(session_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
