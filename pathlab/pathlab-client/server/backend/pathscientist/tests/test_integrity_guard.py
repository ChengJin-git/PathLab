"""Tests for the end-of-session IntegrityGuard."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from pathscientist.runtime.integrity import (
    IntegrityIssue,
    IntegrityReport,
    check_session_integrity,
)


# ---------- helpers ----------


def _init_git_repo(path: Path) -> None:
    """Initialize a git repository at ``path`` with no commits yet."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    # Configure local identity so any `git commit` we make later works.
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test Runner"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _make_git_commit(path: Path, filename: str = "README.md", content: str = "hi") -> None:
    """Create a real git commit in the repo so `git log` is non-empty."""
    (path / filename).write_text(content, encoding="utf-8")
    subprocess.run(
        ["git", "add", filename],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial", "--quiet"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _write_evidence_record(evidence_root: Path, run_id: str, committed: bool = True) -> None:
    """Write a minimal record.json under <evidence_root>/runs/<run_id>/."""
    run_dir = evidence_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "record.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "committed": committed,
                "primary_metric_name": "auc",
                "primary_metric_value": 0.8,
            }
        ),
        encoding="utf-8",
    )


def _tracker_entry(
    *,
    iteration: int,
    auc: float | None = 0.7,
    committed: bool = True,
    run_id: str = "run_xyz",
) -> dict:
    """Build a tracker history entry mirroring MetricsTracker.record()."""
    metrics: dict = {}
    if auc is not None:
        metrics["auc"] = auc
    return {
        "iteration": iteration,
        "metrics": metrics,
        "committed": committed,
        "run_id": run_id,
        "best_auc": auc if (committed and auc is not None) else 0.0,
    }


def _iteration_entry(
    *,
    iteration: int,
    committed: bool = True,
    run_id: str = "run_xyz",
    metrics: dict | None = None,
) -> dict:
    """Build an iteration history entry mirroring IterationState.record_iteration()."""
    return {
        "iteration": iteration,
        "file_hash": "hash_" + run_id,
        "metrics": metrics or {"auc": 0.7},
        "committed": committed,
        "run_id": run_id,
    }


def _run_record(
    *,
    run_id: str,
    iteration: int,
    committed: bool = True,
    metric_value: float = 0.7,
    metric_name: str = "auc",
) -> dict:
    """Build a research_run_history entry mirroring RunRecord."""
    return {
        "run_id": run_id,
        "iteration": iteration,
        "metric_name": metric_name,
        "metric_value": metric_value,
        "committed": committed,
        "notes": "",
    }


def _base_happy_inputs(tmp_path: Path) -> dict:
    """Build the kwargs for a session that should pass all checks."""
    workspace_root = tmp_path / "workspace"
    evidence_root = workspace_root / ".evidence"
    _init_git_repo(workspace_root)
    _make_git_commit(workspace_root)

    run_ids = ["run_a", "run_b"]
    for rid in run_ids:
        _write_evidence_record(evidence_root, rid, committed=True)

    tracker_history = [
        _tracker_entry(iteration=0, auc=0.70, committed=True, run_id="run_a"),
        _tracker_entry(iteration=1, auc=0.75, committed=True, run_id="run_b"),
    ]
    iteration_history = [
        _iteration_entry(iteration=0, committed=True, run_id="run_a", metrics={"auc": 0.70}),
        _iteration_entry(iteration=1, committed=True, run_id="run_b", metrics={"auc": 0.75}),
    ]
    research_run_history = [
        _run_record(run_id="run_a", iteration=0, committed=True, metric_value=0.70),
        _run_record(run_id="run_b", iteration=1, committed=True, metric_value=0.75),
    ]

    return {
        "workspace_root": workspace_root,
        "evidence_root": evidence_root,
        "tracker_history": tracker_history,
        "iteration_history": iteration_history,
        "research_run_history": research_run_history,
        "max_iterations": 3,
        "iteration_index": 2,
        "stop_reason": "",
    }


def _codes(report: IntegrityReport) -> list[str]:
    return [issue.code for issue in report.issues]


# ---------- happy path ----------


def test_happy_path_passes_all_checks(tmp_path):
    inputs = _base_happy_inputs(tmp_path)
    report = check_session_integrity(**inputs)

    assert isinstance(report, IntegrityReport)
    assert report.passed is True
    assert report.fatal_count == 0
    assert report.warning_count == 0
    assert report.issues == []
    # Serialization round-trips to a dict safely.
    as_dict = report.to_dict()
    assert as_dict["passed"] is True
    assert as_dict["issues"] == []


# ---------- fatal checks ----------


def test_no_git_commits_flagged_when_committed_runs_claimed(tmp_path):
    """Committed runs in history but empty git log → fatal."""
    inputs = _base_happy_inputs(tmp_path)
    # Wipe the git history: re-init a fresh empty repo at workspace_root.
    workspace_root = inputs["workspace_root"]
    # Remove old git dir, re-init bare (no commits).
    git_dir = workspace_root / ".git"
    if git_dir.exists():
        import shutil

        shutil.rmtree(git_dir)
    _init_git_repo(workspace_root)

    report = check_session_integrity(**inputs)

    codes = _codes(report)
    assert "no_git_commits" in codes
    assert report.passed is False
    assert report.fatal_count >= 1
    issue = next(i for i in report.issues if i.code == "no_git_commits")
    assert issue.severity == "fatal"


def test_tracker_run_id_blank_on_committed_entry(tmp_path):
    inputs = _base_happy_inputs(tmp_path)
    # Blank out run_id on a committed tracker entry.
    inputs["tracker_history"][0]["run_id"] = ""

    report = check_session_integrity(**inputs)

    codes = _codes(report)
    assert "tracker_run_id_blank" in codes
    issue = next(i for i in report.issues if i.code == "tracker_run_id_blank")
    assert issue.severity == "fatal"
    # Context should identify which entry was bad (index or iteration).
    assert issue.context  # non-empty


def test_tracker_metric_missing_on_committed_entry(tmp_path):
    inputs = _base_happy_inputs(tmp_path)
    # Commit an entry with no primary metric value.
    inputs["tracker_history"][1] = _tracker_entry(
        iteration=1, auc=None, committed=True, run_id="run_b"
    )

    report = check_session_integrity(
        **inputs,
    )

    codes = _codes(report)
    assert "tracker_metric_missing" in codes
    issue = next(i for i in report.issues if i.code == "tracker_metric_missing")
    assert issue.severity == "fatal"


def test_evidence_run_missing_for_committed_run(tmp_path):
    inputs = _base_happy_inputs(tmp_path)
    # Remove the evidence record for run_b so a committed run has no record.json.
    missing_run = inputs["research_run_history"][1]["run_id"]
    record_path = inputs["evidence_root"] / "runs" / missing_run / "record.json"
    record_path.unlink()

    report = check_session_integrity(**inputs)

    codes = _codes(report)
    assert "evidence_run_missing" in codes
    issue = next(i for i in report.issues if i.code == "evidence_run_missing")
    assert issue.severity == "fatal"
    assert missing_run in (issue.context.get("run_id") or "")


def test_evidence_run_missing_includes_skip_reason_when_provided(tmp_path):
    """When evidence_skipped_runs is passed, the issue context should include the skip reason."""
    inputs = _base_happy_inputs(tmp_path)
    missing_run = inputs["research_run_history"][1]["run_id"]
    (inputs["evidence_root"] / "runs" / missing_run / "record.json").unlink()

    report = check_session_integrity(
        **inputs,
        evidence_skipped_runs=[{"run_id": missing_run, "reason": "snapshot_failed"}],
    )

    codes = _codes(report)
    assert "evidence_run_missing" in codes
    issue = next(i for i in report.issues if i.code == "evidence_run_missing")
    assert issue.context.get("skip_reason") == "snapshot_failed"


def test_iteration_over_budget_flagged_without_stop_reason(tmp_path):
    inputs = _base_happy_inputs(tmp_path)
    inputs["iteration_index"] = inputs["max_iterations"] + 1  # over budget
    inputs["stop_reason"] = ""  # no explicit stop

    report = check_session_integrity(**inputs)

    codes = _codes(report)
    assert "iteration_over_budget" in codes
    issue = next(i for i in report.issues if i.code == "iteration_over_budget")
    assert issue.severity == "fatal"


def test_iteration_over_budget_not_flagged_when_stop_reason_set(tmp_path):
    """If stop_reason is set, going over budget is acceptable."""
    inputs = _base_happy_inputs(tmp_path)
    inputs["iteration_index"] = inputs["max_iterations"] + 1
    inputs["stop_reason"] = "stall_limit"

    report = check_session_integrity(**inputs)

    assert "iteration_over_budget" not in _codes(report)


# ---------- warnings ----------


def test_history_length_mismatch_warning(tmp_path):
    inputs = _base_happy_inputs(tmp_path)
    # Tracker has 2 entries, research_run_history has only 1 → mismatch.
    inputs["research_run_history"] = inputs["research_run_history"][:1]

    report = check_session_integrity(**inputs)

    codes = _codes(report)
    assert "history_length_mismatch" in codes
    issue = next(i for i in report.issues if i.code == "history_length_mismatch")
    assert issue.severity == "warning"
    assert report.warning_count >= 1


def test_runs_all_identical_metric_warning(tmp_path):
    """3+ consecutive committed runs with identical metric → warning."""
    inputs = _base_happy_inputs(tmp_path)
    # Replace with 3 committed runs at exactly 0.7303 AUC.
    workspace_root = inputs["workspace_root"]
    evidence_root = inputs["evidence_root"]

    run_ids = ["run_1", "run_2", "run_3"]
    for rid in run_ids:
        _write_evidence_record(evidence_root, rid, committed=True)
    # Remove old evidence.
    for rid in ("run_a", "run_b"):
        rec = evidence_root / "runs" / rid / "record.json"
        if rec.exists():
            rec.unlink()

    inputs["tracker_history"] = [
        _tracker_entry(iteration=i, auc=0.7303, committed=True, run_id=run_ids[i])
        for i in range(3)
    ]
    inputs["iteration_history"] = [
        _iteration_entry(
            iteration=i, committed=True, run_id=run_ids[i], metrics={"auc": 0.7303}
        )
        for i in range(3)
    ]
    inputs["research_run_history"] = [
        _run_record(run_id=run_ids[i], iteration=i, committed=True, metric_value=0.7303)
        for i in range(3)
    ]
    inputs["max_iterations"] = 5
    inputs["iteration_index"] = 3

    assert workspace_root.exists()  # sanity

    report = check_session_integrity(**inputs)

    codes = _codes(report)
    assert "runs_all_identical_metric" in codes
    issue = next(i for i in report.issues if i.code == "runs_all_identical_metric")
    assert issue.severity == "warning"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
