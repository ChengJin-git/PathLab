"""Tests for the end-of-session IntegrityGuard."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from autoresearch.runtime.integrity import (
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


def test_tracker_metric_missing_tolerates_test_prefix(tmp_path):
    """Committed tracker entry with test_/val_ prefixed metrics must not be flagged.

    Regression for session_b14b074d2268 (2026-04-20): tracker entries recorded
    metrics={"test_auc": 0.85, "val_auc": 0.92} and the strict .get("auc") check
    produced 11 false-positive fatal issues. The fix delegates to
    resolve_primary_metric which handles the test_/val_/best_val_/best_ prefixes.
    """
    workspace_root = tmp_path / "workspace"
    evidence_root = workspace_root / ".evidence"
    _init_git_repo(workspace_root)
    _make_git_commit(workspace_root)

    _write_evidence_record(evidence_root, "run_abc12345", committed=True)

    tracker_history = [
        {
            "iteration": 0,
            "run_id": "run_abc12345",
            "metrics": {"test_auc": 0.85, "val_auc": 0.92},
            "committed": True,
            "best_auc": 0.85,
        }
    ]
    research_run_history = [
        _run_record(run_id="run_abc12345", iteration=0, committed=True, metric_value=0.85),
    ]

    report = check_session_integrity(
        workspace_root=workspace_root,
        evidence_root=evidence_root,
        tracker_history=tracker_history,
        iteration_history=[],
        research_run_history=research_run_history,
        max_iterations=5,
        iteration_index=1,
        stop_reason="budget_exhausted",
        primary_metric="auc",
    )

    codes = _codes(report)
    assert "tracker_metric_missing" not in codes, f"False positive: {codes}"


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


def test_external_opt_in_is_warning_not_fatal(tmp_path):
    """When a committed run's evidence is missing because the agent opted into
    external mode (``reason == "external_experiment_opt_in"``), the check must
    emit ``severity="warning"`` not ``"fatal"``.

    Rationale: ``external=True`` is the documented escape hatch for experiments
    run outside ``RunExperimentTool``. A deliberate external run without an
    evidence record is a known trade-off — still surfaced in the report so
    downstream readers notice it, but not a reason to block ``paper_ready``.
    """
    inputs = _base_happy_inputs(tmp_path)
    # Remove the evidence record for run_b so a committed run has no record.json.
    missing_run = inputs["research_run_history"][1]["run_id"]
    (inputs["evidence_root"] / "runs" / missing_run / "record.json").unlink()

    report = check_session_integrity(
        **inputs,
        evidence_skipped_runs=[
            {"run_id": missing_run, "reason": "external_experiment_opt_in"}
        ],
    )

    codes = _codes(report)
    assert "evidence_run_missing" in codes
    issue = next(i for i in report.issues if i.code == "evidence_run_missing")
    assert issue.severity == "warning", (
        f"external_experiment_opt_in must downgrade to warning; "
        f"got severity={issue.severity!r}"
    )
    assert issue.context.get("skip_reason") == "external_experiment_opt_in"

    # This specific issue must count toward warnings, not fatals.
    fatal_evidence_issues = [
        i
        for i in report.issues
        if i.code == "evidence_run_missing" and i.severity == "fatal"
    ]
    warning_evidence_issues = [
        i
        for i in report.issues
        if i.code == "evidence_run_missing" and i.severity == "warning"
    ]
    assert fatal_evidence_issues == [], (
        f"no evidence_run_missing issue should be fatal here; got {fatal_evidence_issues!r}"
    )
    assert len(warning_evidence_issues) == 1
    # Aggregate counters must agree.
    assert report.warning_count >= 1
    # The external-opt-in issue is the only fatal-or-warning evidence issue;
    # a session that is otherwise healthy must still pass (no fatals).
    assert report.passed is True, (
        f"external-opt-in alone must not fail integrity; "
        f"fatal_count={report.fatal_count}, issues={[i.code for i in report.issues]}"
    )


def test_fatal_evidence_missing_still_fatal_for_no_last_experiment_reason(tmp_path):
    """Regression guard: the pre-T3 fatal behavior must be preserved for
    ``no_last_experiment`` (and any other non-external-opt-in reason)."""
    inputs = _base_happy_inputs(tmp_path)
    missing_run = inputs["research_run_history"][1]["run_id"]
    (inputs["evidence_root"] / "runs" / missing_run / "record.json").unlink()

    report = check_session_integrity(
        **inputs,
        evidence_skipped_runs=[
            {"run_id": missing_run, "reason": "no_last_experiment"}
        ],
    )

    codes = _codes(report)
    assert "evidence_run_missing" in codes
    issue = next(i for i in report.issues if i.code == "evidence_run_missing")
    assert issue.severity == "fatal", (
        f"no_last_experiment must stay fatal; got severity={issue.severity!r}"
    )
    assert report.passed is False


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


# ---------- metrics_drift_unrecorded (Finding 2 of 2026-04-22 review) ----------


def _write_disk_metrics(workspace_root: Path, payload: dict) -> Path:
    """Write ``output/metrics.json`` under the given workspace and return its path."""
    output_dir = workspace_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = output_dir / "metrics.json"
    metrics_path.write_text(json.dumps(payload), encoding="utf-8")
    return metrics_path


def test_metrics_drift_unrecorded_flagged_as_fatal(tmp_path):
    """Disk metrics.json materially better than tracker.best_value → fatal.

    Mirrors the session_3f1795098784 failure mode: the agent ran
    `python train.py` from a terminal, wrote test_auc=0.85 to
    output/metrics.json, but only the earlier 0.80 run ever passed through
    run_experiment + ratchet_commit, so tracker.best_value stayed at 0.80
    while the workspace held a much better result.
    """
    inputs = _base_happy_inputs(tmp_path)
    # Tracker history's best is 0.75 (from happy fixtures). Drop one to make
    # the math obvious: best=0.80 in tracker, 0.85 on disk.
    inputs["tracker_history"] = [
        _tracker_entry(iteration=0, auc=0.80, committed=True, run_id="run_a"),
    ]
    inputs["research_run_history"] = [
        _run_record(run_id="run_a", iteration=0, committed=True, metric_value=0.80),
    ]
    inputs["iteration_history"] = inputs["iteration_history"][:1]
    _write_disk_metrics(inputs["workspace_root"], {"test_auc": 0.85})

    report = check_session_integrity(**inputs)

    codes = _codes(report)
    assert "metrics_drift_unrecorded" in codes, f"expected drift fatal; got {codes}"
    issue = next(i for i in report.issues if i.code == "metrics_drift_unrecorded")
    assert issue.severity == "fatal"
    assert report.passed is False
    assert report.fatal_count >= 1
    # Context should pinpoint both sides of the split.
    assert issue.context["disk_value"] == pytest.approx(0.85)
    assert issue.context["tracker_best_value"] == pytest.approx(0.80)
    assert issue.context["tracker_best_run_id"] == "run_a"


def test_metrics_drift_not_flagged_when_disk_matches_tracker(tmp_path):
    """Disk and tracker both at 0.82 → no drift issue."""
    inputs = _base_happy_inputs(tmp_path)
    inputs["tracker_history"] = [
        _tracker_entry(iteration=0, auc=0.82, committed=True, run_id="run_a"),
    ]
    inputs["research_run_history"] = [
        _run_record(run_id="run_a", iteration=0, committed=True, metric_value=0.82),
    ]
    inputs["iteration_history"] = inputs["iteration_history"][:1]
    _write_disk_metrics(inputs["workspace_root"], {"auc": 0.82})

    report = check_session_integrity(**inputs)

    assert "metrics_drift_unrecorded" not in _codes(report)


def test_metrics_drift_not_flagged_when_disk_worse_than_tracker(tmp_path):
    """Disk 0.75, tracker best 0.82 → no issue (tracker recorded the good one)."""
    inputs = _base_happy_inputs(tmp_path)
    inputs["tracker_history"] = [
        _tracker_entry(iteration=0, auc=0.82, committed=True, run_id="run_a"),
    ]
    inputs["research_run_history"] = [
        _run_record(run_id="run_a", iteration=0, committed=True, metric_value=0.82),
    ]
    inputs["iteration_history"] = inputs["iteration_history"][:1]
    _write_disk_metrics(inputs["workspace_root"], {"auc": 0.75})

    report = check_session_integrity(**inputs)

    assert "metrics_drift_unrecorded" not in _codes(report)


def test_metrics_drift_tolerates_test_prefix(tmp_path):
    """metrics.json uses test_auc; primary_metric is 'auc' — drift still flagged.

    resolve_primary_metric must surface test_auc when only the bare 'auc'
    name is configured. Otherwise this whole defense is silent the moment a
    workspace writes test_auc instead of auc.
    """
    inputs = _base_happy_inputs(tmp_path)
    inputs["tracker_history"] = [
        _tracker_entry(iteration=0, auc=0.80, committed=True, run_id="run_a"),
    ]
    inputs["research_run_history"] = [
        _run_record(run_id="run_a", iteration=0, committed=True, metric_value=0.80),
    ]
    inputs["iteration_history"] = inputs["iteration_history"][:1]
    _write_disk_metrics(
        inputs["workspace_root"], {"test_auc": 0.85, "val_auc": 0.92}
    )

    report = check_session_integrity(**inputs)

    codes = _codes(report)
    assert "metrics_drift_unrecorded" in codes, f"expected drift fatal; got {codes}"
    issue = next(i for i in report.issues if i.code == "metrics_drift_unrecorded")
    assert issue.severity == "fatal"
    assert issue.context["disk_value"] == pytest.approx(0.85)


def test_metrics_drift_silent_when_metrics_json_missing(tmp_path):
    """No output/metrics.json → no issue (normal for sessions without runs)."""
    inputs = _base_happy_inputs(tmp_path)
    metrics_path = inputs["workspace_root"] / "output" / "metrics.json"
    assert not metrics_path.exists()  # sanity: fixture doesn't create it

    report = check_session_integrity(**inputs)

    assert "metrics_drift_unrecorded" not in _codes(report)


# ---------- tracker_vs_artifact_mismatch (Finding 5 of 2026-04-22 review) ----------


def _write_artifact_metrics(
    evidence_root: Path, run_id: str, payload: dict
) -> Path:
    """Write ``<evidence_root>/runs/<run_id>/artifacts/metrics.json``."""
    artifact_dir = evidence_root / "runs" / run_id / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "metrics.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    return artifact_path


def test_tracker_vs_artifact_mismatch_flagged_as_fatal(tmp_path):
    """Tracker says auc=0.86, artifact metrics.json says test_auc=0.84 → fatal.

    Mirrors the session_8e48c15d38cb Finding 5 scenario: tracker records
    run_c5135625 as auc=0.8643 while its own .evidence/runs/.../metrics.json
    records test.auc=0.8414. Paper verifier passed because it only checks
    that claimed metrics have SUPPORT somewhere — not that tracker matches
    the actual run artifact.
    """
    inputs = _base_happy_inputs(tmp_path)
    # Tracker history claims auc=0.86 for run_a...
    inputs["tracker_history"] = [
        _tracker_entry(iteration=0, auc=0.86, committed=True, run_id="run_a"),
    ]
    inputs["research_run_history"] = [
        _run_record(run_id="run_a", iteration=0, committed=True, metric_value=0.86),
    ]
    inputs["iteration_history"] = inputs["iteration_history"][:1]
    # Remove extra evidence record for run_b to keep the fixture tidy.
    (inputs["evidence_root"] / "runs" / "run_b" / "record.json").unlink()
    # ...but the artifact under .evidence/runs/run_a/artifacts/metrics.json
    # only recorded test_auc=0.84.
    _write_artifact_metrics(inputs["evidence_root"], "run_a", {"test_auc": 0.84})

    report = check_session_integrity(**inputs)

    codes = _codes(report)
    assert "tracker_vs_artifact_mismatch" in codes, (
        f"expected mismatch fatal; got {codes}"
    )
    issue = next(
        i for i in report.issues if i.code == "tracker_vs_artifact_mismatch"
    )
    assert issue.severity == "fatal"
    assert report.passed is False
    assert report.fatal_count >= 1
    # Context should pinpoint both sides of the split.
    assert issue.context["run_id"] == "run_a"
    assert issue.context["tracker_value"] == pytest.approx(0.86)
    assert issue.context["artifact_value"] == pytest.approx(0.84)
    assert issue.context["primary_metric"] == "auc"
    assert "artifact_path" in issue.context


def test_tracker_vs_artifact_match_passes(tmp_path):
    """Tracker and artifact both at 0.86 → no mismatch issue."""
    inputs = _base_happy_inputs(tmp_path)
    inputs["tracker_history"] = [
        _tracker_entry(iteration=0, auc=0.86, committed=True, run_id="run_a"),
    ]
    inputs["research_run_history"] = [
        _run_record(run_id="run_a", iteration=0, committed=True, metric_value=0.86),
    ]
    inputs["iteration_history"] = inputs["iteration_history"][:1]
    (inputs["evidence_root"] / "runs" / "run_b" / "record.json").unlink()
    _write_artifact_metrics(inputs["evidence_root"], "run_a", {"auc": 0.86})

    report = check_session_integrity(**inputs)

    assert "tracker_vs_artifact_mismatch" not in _codes(report)


def test_tracker_vs_artifact_small_drift_accepted(tmp_path):
    """Drift 0.002 < 0.005 threshold → no mismatch issue."""
    inputs = _base_happy_inputs(tmp_path)
    inputs["tracker_history"] = [
        _tracker_entry(iteration=0, auc=0.864, committed=True, run_id="run_a"),
    ]
    inputs["research_run_history"] = [
        _run_record(run_id="run_a", iteration=0, committed=True, metric_value=0.864),
    ]
    inputs["iteration_history"] = inputs["iteration_history"][:1]
    (inputs["evidence_root"] / "runs" / "run_b" / "record.json").unlink()
    _write_artifact_metrics(inputs["evidence_root"], "run_a", {"auc": 0.862})

    report = check_session_integrity(**inputs)

    assert "tracker_vs_artifact_mismatch" not in _codes(report)


def test_tracker_vs_artifact_tolerates_prefix_mismatch(tmp_path):
    """Artifact has test_auc=0.85, tracker has auc=0.85, primary_metric 'auc'.

    resolve_primary_metric must surface test_auc when only the bare 'auc'
    name is configured. Otherwise the check would false-positive the moment
    an artifact writes test_auc instead of auc.
    """
    inputs = _base_happy_inputs(tmp_path)
    inputs["tracker_history"] = [
        _tracker_entry(iteration=0, auc=0.85, committed=True, run_id="run_a"),
    ]
    inputs["research_run_history"] = [
        _run_record(run_id="run_a", iteration=0, committed=True, metric_value=0.85),
    ]
    inputs["iteration_history"] = inputs["iteration_history"][:1]
    (inputs["evidence_root"] / "runs" / "run_b" / "record.json").unlink()
    _write_artifact_metrics(
        inputs["evidence_root"], "run_a", {"test_auc": 0.85, "val_auc": 0.92}
    )

    report = check_session_integrity(**inputs)

    codes = _codes(report)
    assert "tracker_vs_artifact_mismatch" not in codes, (
        f"False positive from prefix mismatch: {codes}"
    )


def test_tracker_vs_artifact_silent_when_artifact_missing(tmp_path):
    """Tracker references run_abc12345 but artifacts/metrics.json doesn't exist.

    No issue from this check — ``evidence_run_missing`` handles the absent
    evidence directory. This check should be silent.
    """
    workspace_root = tmp_path / "workspace"
    evidence_root = workspace_root / ".evidence"
    _init_git_repo(workspace_root)
    _make_git_commit(workspace_root)

    # record.json present (so evidence_run_missing stays silent) but no
    # artifacts/metrics.json file.
    _write_evidence_record(evidence_root, "run_abc12345", committed=True)
    # Sanity: the artifact path does NOT exist.
    assert not (
        evidence_root / "runs" / "run_abc12345" / "artifacts" / "metrics.json"
    ).exists()

    tracker_history = [
        _tracker_entry(iteration=0, auc=0.86, committed=True, run_id="run_abc12345"),
    ]
    research_run_history = [
        _run_record(run_id="run_abc12345", iteration=0, committed=True, metric_value=0.86),
    ]

    report = check_session_integrity(
        workspace_root=workspace_root,
        evidence_root=evidence_root,
        tracker_history=tracker_history,
        iteration_history=[],
        research_run_history=research_run_history,
        max_iterations=3,
        iteration_index=1,
        stop_reason="",
        primary_metric="auc",
    )

    assert "tracker_vs_artifact_mismatch" not in _codes(report)


def test_tracker_vs_artifact_silent_for_uncommitted_entries(tmp_path):
    """Uncommitted tracker entries must not trigger the check.

    Even if an uncommitted entry disagrees with its artifact, we only care
    about entries that were committed (and therefore might be cited in the
    paper / report).
    """
    inputs = _base_happy_inputs(tmp_path)
    # Uncommitted entry with mismatched metrics against the artifact.
    inputs["tracker_history"] = [
        _tracker_entry(iteration=0, auc=0.86, committed=False, run_id="run_a"),
    ]
    inputs["research_run_history"] = [
        _run_record(run_id="run_a", iteration=0, committed=False, metric_value=0.86),
    ]
    inputs["iteration_history"] = inputs["iteration_history"][:1]
    (inputs["evidence_root"] / "runs" / "run_b" / "record.json").unlink()
    _write_artifact_metrics(inputs["evidence_root"], "run_a", {"auc": 0.70})

    report = check_session_integrity(**inputs)

    assert "tracker_vs_artifact_mismatch" not in _codes(report)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
