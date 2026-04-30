"""End-of-session integrity checks for PathScientist research sessions.

This module is intentionally self-contained. All inputs are plain dicts and
paths so the guard can be unit-tested without instantiating live orchestrator,
tracker, or workspace objects.

Motivated by session ``session_142a4acaed08`` (2026-04-18) where the run
reported success even though git log was empty, ``.evidence/runs/`` was
empty, and every tracker entry had ``run_id=""`` — five invariants broken at
once with zero error surfaced to the user. See ``docs/plans/`` for the
Session Integrity Hardening plan.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class IntegrityIssue:
    """A single problem detected at session end.

    ``code`` is a stable string id so downstream code (CLI renderers, tests,
    logs) can switch on it without parsing the human-readable ``message``.
    """

    code: str
    severity: str  # "fatal" | "warning"
    message: str
    context: dict = field(default_factory=dict)


@dataclass
class IntegrityReport:
    """Aggregate result of running all checks."""

    passed: bool
    fatal_count: int
    warning_count: int
    issues: list[IntegrityIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "fatal_count": self.fatal_count,
            "warning_count": self.warning_count,
            "issues": [
                {
                    "code": i.code,
                    "severity": i.severity,
                    "message": i.message,
                    "context": i.context,
                }
                for i in self.issues
            ],
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def check_session_integrity(
    *,
    workspace_root: Path,
    evidence_root: Path,
    tracker_history: list[dict],
    iteration_history: list[dict],
    research_run_history: list[dict],
    max_iterations: int,
    iteration_index: int,
    stop_reason: str,
    evidence_skipped_runs: list[dict] | None = None,
    primary_metric: str = "auc",
) -> IntegrityReport:
    """Run all invariant checks against a finished session's state.

    All inputs are plain dicts / primitives so tests do not need to mock live
    OpenHands conversations or tracker objects.

    Arguments:
        workspace_root: Path to the session's workspace (git repo root).
        evidence_root: Path to the evidence directory. Typically
            ``workspace_root / ".evidence"``.
        tracker_history: ``MetricsTracker.history`` — entries shaped like
            ``{"iteration": int, "metrics": dict, "committed": bool,
              "run_id": str, "best_<metric>": float}``.
        iteration_history: ``IterationState.history`` — same rough shape as
            tracker_history.
        research_run_history: ``ResearchSessionState.run_history`` items as
            dicts (``RunRecord`` fields: run_id / iteration / metric_name /
            metric_value / committed / notes).
        max_iterations: Budget declared up front.
        iteration_index: Final iteration index reached.
        stop_reason: ``""`` if session ended naturally, or one of the
            ``ResearchSessionState.stop_reason`` codes (``stall_limit``,
            ``approval_rejected``, ``user_cancelled``, ...).
        evidence_skipped_runs: Optional list of ``{"run_id", "reason"}``
            dicts for runs the evidence collector deliberately skipped.
            Used to enrich the ``evidence_run_missing`` issue context.
        primary_metric: Name of the primary metric (default ``"auc"``).

    Returns:
        An :class:`IntegrityReport` containing every issue found, with
        ``passed=True`` iff no fatal issues were raised.
    """
    issues: list[IntegrityIssue] = []

    issues.extend(_check_no_git_commits(workspace_root, research_run_history))
    issues.extend(_check_tracker_run_id_blank(tracker_history))
    issues.extend(_check_tracker_metric_missing(tracker_history, primary_metric))
    issues.extend(
        _check_evidence_run_missing(
            evidence_root, research_run_history, evidence_skipped_runs
        )
    )
    issues.extend(
        _check_iteration_over_budget(iteration_index, max_iterations, stop_reason)
    )
    issues.extend(
        _check_history_length_mismatch(tracker_history, research_run_history)
    )
    issues.extend(_check_runs_all_identical_metric(research_run_history))
    issues.extend(
        _check_metrics_json_drift(workspace_root, tracker_history, primary_metric)
    )
    issues.extend(
        _check_tracker_vs_artifact_mismatch(
            workspace_root, evidence_root, tracker_history, primary_metric
        )
    )

    fatal_count = sum(1 for i in issues if i.severity == "fatal")
    warning_count = sum(1 for i in issues if i.severity == "warning")
    return IntegrityReport(
        passed=(fatal_count == 0),
        fatal_count=fatal_count,
        warning_count=warning_count,
        issues=issues,
    )


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _has_committed_runs(research_run_history: list[dict]) -> bool:
    return any(bool(r.get("committed")) for r in research_run_history or [])


def _git_log_is_empty(workspace_root: Path) -> bool:
    """Return True when ``git log --oneline`` produces no output.

    A non-zero exit (e.g. no repo, corrupt repo, no HEAD yet) is treated as
    "empty" — the premise of the check is that *something* should be there
    if the session claims to have committed runs.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return True
    if result.returncode != 0:
        return True
    return result.stdout.strip() == ""


def _check_no_git_commits(
    workspace_root: Path, research_run_history: list[dict]
) -> list[IntegrityIssue]:
    """Fatal: research claims committed runs but git log is empty."""
    if not _has_committed_runs(research_run_history):
        return []
    if not _git_log_is_empty(workspace_root):
        return []
    committed_run_ids = [
        r.get("run_id", "") for r in research_run_history if r.get("committed")
    ]
    return [
        IntegrityIssue(
            code="no_git_commits",
            severity="fatal",
            message=(
                "Research run history records committed runs "
                f"({len(committed_run_ids)}) but git log in "
                f"{workspace_root} is empty."
            ),
            context={
                "workspace_root": str(workspace_root),
                "committed_run_count": len(committed_run_ids),
                "committed_run_ids": committed_run_ids,
            },
        )
    ]


def _check_tracker_run_id_blank(tracker_history: list[dict]) -> list[IntegrityIssue]:
    """Fatal: a committed tracker entry has ``run_id == ""``."""
    issues: list[IntegrityIssue] = []
    for idx, entry in enumerate(tracker_history or []):
        if not isinstance(entry, dict):
            continue
        if not entry.get("committed"):
            continue
        if entry.get("run_id", "") == "":
            issues.append(
                IntegrityIssue(
                    code="tracker_run_id_blank",
                    severity="fatal",
                    message=(
                        f"Tracker history entry #{idx} (iteration "
                        f"{entry.get('iteration', '?')}) is marked committed "
                        "but has an empty run_id."
                    ),
                    context={
                        "index": idx,
                        "iteration": entry.get("iteration"),
                    },
                )
            )
    return issues


def _metric_value(entry_metrics: Any, primary_metric: str) -> Any:
    """Return the primary metric value from a metrics dict, or ``None``.

    Delegates to ``orchestrator.metrics_utils.resolve_primary_metric`` so
    prefixed keys such as ``test_auc`` / ``val_auc`` / ``best_val_auc`` are
    resolved to the primary metric (``auc``). The resolver returns ``0.0``
    when nothing matches, which this helper treats as missing for the
    purposes of the integrity check.

    This breaks the "no imports from orchestrator/" self-containment goal
    for ``runtime/integrity.py``, but the duplication would be worse. The
    import is scoped to this one helper.
    """
    if not isinstance(entry_metrics, dict):
        return None
    # Narrow, function-scoped import: avoid dragging orchestrator internals
    # into the integrity module's import-time surface.
    from ..orchestrator.metrics_utils import resolve_primary_metric

    value = resolve_primary_metric(entry_metrics, primary_metric)
    if not isinstance(value, (int, float)):
        return None
    # resolve_primary_metric returns 0.0 when nothing is found; treat as
    # missing. A real 0.0 metric is indistinguishable here, but a truly
    # zero AUC/accuracy/F1 is not a plausible committed experiment run.
    if value == 0.0:
        return None
    return float(value)


def _check_tracker_metric_missing(
    tracker_history: list[dict], primary_metric: str
) -> list[IntegrityIssue]:
    """Fatal: a committed tracker entry has no primary-metric value."""
    issues: list[IntegrityIssue] = []
    for idx, entry in enumerate(tracker_history or []):
        if not isinstance(entry, dict):
            continue
        if not entry.get("committed"):
            continue
        value = _metric_value(entry.get("metrics"), primary_metric)
        if value is None:
            issues.append(
                IntegrityIssue(
                    code="tracker_metric_missing",
                    severity="fatal",
                    message=(
                        f"Tracker history entry #{idx} (iteration "
                        f"{entry.get('iteration', '?')}, run_id "
                        f"{entry.get('run_id', '')!r}) is committed but has "
                        f"no '{primary_metric}' value in its metrics dict."
                    ),
                    context={
                        "index": idx,
                        "iteration": entry.get("iteration"),
                        "run_id": entry.get("run_id", ""),
                        "primary_metric": primary_metric,
                    },
                )
            )
    return issues


def _check_evidence_run_missing(
    evidence_root: Path,
    research_run_history: list[dict],
    evidence_skipped_runs: list[dict] | None,
) -> list[IntegrityIssue]:
    """A committed run has no ``<evidence_root>/runs/<id>/record.json``.

    Severity is ``fatal`` in the general case (a real invariant violation)
    but ``warning`` when the skip reason is ``"external_experiment_opt_in"`` —
    the documented escape hatch for experiments run outside
    ``RunExperimentTool``. A deliberate external run without an evidence
    record is a known trade-off: still surfaced in the report so readers
    notice it, but not a reason to block ``paper_ready``.
    """
    skipped_by_id: dict[str, str] = {}
    for skip in evidence_skipped_runs or []:
        if not isinstance(skip, dict):
            continue
        run_id = skip.get("run_id", "")
        if run_id:
            skipped_by_id[run_id] = str(skip.get("reason", ""))

    runs_dir = Path(evidence_root) / "runs"
    issues: list[IntegrityIssue] = []
    for record in research_run_history or []:
        if not isinstance(record, dict) or not record.get("committed"):
            continue
        run_id = record.get("run_id", "")
        if not run_id:
            # A blank run_id is already surfaced by the tracker/lineage
            # checks; still flag the missing evidence so it appears in
            # context.
            run_id_display = "<blank>"
            record_path_exists = False
        else:
            run_id_display = run_id
            record_path_exists = (runs_dir / run_id / "record.json").exists()
        if record_path_exists:
            continue
        context: dict[str, Any] = {
            "run_id": run_id,
            "iteration": record.get("iteration"),
            "expected_path": str(runs_dir / run_id / "record.json")
            if run_id
            else "",
        }
        skip_reason = skipped_by_id.get(run_id, "") if run_id else ""
        if skip_reason:
            context["skip_reason"] = skip_reason
        is_external_opt_in = skip_reason == "external_experiment_opt_in"
        if is_external_opt_in:
            message = (
                f"Committed run {run_id_display!r} was marked external "
                "(opt-in); no evidence record at "
                f"{context['expected_path'] or '<evidence_root>/runs/.../record.json'}. "
                "Deliberate out-of-band experiment — prefer running through "
                "run_experiment when possible."
            )
            severity = "warning"
        else:
            message = (
                f"Committed run {run_id_display!r} has no evidence record at "
                f"{context['expected_path'] or '<evidence_root>/runs/.../record.json'}."
            )
            if skip_reason:
                message += f" Evidence collector reported: {skip_reason}."
            severity = "fatal"
        issues.append(
            IntegrityIssue(
                code="evidence_run_missing",
                severity=severity,
                message=message,
                context=context,
            )
        )
    return issues


def _check_iteration_over_budget(
    iteration_index: int, max_iterations: int, stop_reason: str
) -> list[IntegrityIssue]:
    """Fatal: iterated past the declared budget with no stop_reason set."""
    if iteration_index <= max_iterations:
        return []
    if stop_reason:
        # An explicit stop reason (stall_limit, approval_rejected, etc.)
        # accounts for the overrun.
        return []
    return [
        IntegrityIssue(
            code="iteration_over_budget",
            severity="fatal",
            message=(
                f"iteration_index={iteration_index} exceeded "
                f"max_iterations={max_iterations} with no stop_reason set."
            ),
            context={
                "iteration_index": iteration_index,
                "max_iterations": max_iterations,
            },
        )
    ]


def _check_history_length_mismatch(
    tracker_history: list[dict], research_run_history: list[dict]
) -> list[IntegrityIssue]:
    """Warning: tracker and research run histories differ in length."""
    tracker_len = len(tracker_history or [])
    research_len = len(research_run_history or [])
    if tracker_len == research_len:
        return []
    return [
        IntegrityIssue(
            code="history_length_mismatch",
            severity="warning",
            message=(
                f"Tracker history has {tracker_len} entries but research run "
                f"history has {research_len}. They should stay in lockstep."
            ),
            context={
                "tracker_length": tracker_len,
                "research_run_length": research_len,
            },
        )
    ]


def _check_runs_all_identical_metric(
    research_run_history: list[dict],
) -> list[IntegrityIssue]:
    """Warning: 3+ consecutive committed runs produced the same metric.

    Signals cached or frozen re-runs — a plausible failure mode is that the
    experiment script never actually trained and kept echoing the baseline
    value.
    """
    committed = [r for r in research_run_history or [] if r.get("committed")]
    if len(committed) < 3:
        return []

    # Scan for any run of 3+ consecutive identical metric values.
    streak_start = 0
    for i in range(1, len(committed)):
        prev = committed[i - 1].get("metric_value")
        curr = committed[i].get("metric_value")
        if prev == curr:
            if i - streak_start + 1 >= 3:
                streak = committed[streak_start : i + 1]
                return [
                    IntegrityIssue(
                        code="runs_all_identical_metric",
                        severity="warning",
                        message=(
                            f"{len(streak)} consecutive committed runs produced "
                            f"the identical metric value {curr}; this often "
                            "indicates cached or un-executed re-runs."
                        ),
                        context={
                            "metric_value": curr,
                            "run_ids": [r.get("run_id", "") for r in streak],
                            "iterations": [r.get("iteration") for r in streak],
                        },
                    )
                ]
        else:
            streak_start = i
    return []


def _check_metrics_json_drift(
    workspace_root: Path,
    tracker_history: list[dict],
    primary_metric: str,
    drift_threshold: float = 0.005,  # 0.5 percentage points of absolute improvement
) -> list[IntegrityIssue]:
    """Fatal: workspace ``output/metrics.json`` shows a better primary-metric
    value than anything recorded in ``tracker_history``.

    Indicates direct-execution runs (``python train.py`` from a terminal
    inside the workspace) that bypassed ``RunExperimentTool``, producing a
    tracker/report/workspace split where the official tracker entry
    materially under-reports the best result the agent actually observed.

    Returns empty list when:

    - ``output/metrics.json`` doesn't exist (normal for sessions without runs)
    - ``primary_metric`` can't be resolved from the metrics file
    - ``tracker_history`` is empty (nothing to compare against)
    - the disk value is NOT meaningfully better than the tracker's best

    Uses :func:`orchestrator.metrics_utils.resolve_primary_metric` for the
    same ``test_``/``val_``/``best_val_``/``best_`` prefix tolerance applied
    by :func:`_check_tracker_metric_missing`.

    Catches the ``session_3f1795098784`` failure mode where the agent ran
    ``python train.py`` via terminal repeatedly, wrote ``test_auc=0.843`` /
    ``0.857`` / ``0.859`` to ``output/metrics.json``, but only the first
    ``0.8217`` run ever went through ``run_experiment`` + ratchet_commit —
    so ``tracker.best_value`` stayed at ``0.8217`` and the final report
    claimed the session was stuck at a metric that had been exceeded many
    times.
    """
    metrics_path = Path(workspace_root) / "output" / "metrics.json"
    if not metrics_path.exists():
        return []
    try:
        raw = metrics_path.read_text(encoding="utf-8")
        disk_metrics = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(disk_metrics, dict):
        return []

    # Narrow, function-scoped import to keep the orchestrator out of
    # integrity.py's import-time surface.
    from ..orchestrator.metrics_utils import resolve_primary_metric

    disk_value = resolve_primary_metric(disk_metrics, primary_metric)
    # resolve_primary_metric returns 0.0 when nothing matches. We treat that
    # as "could not resolve" — there's nothing to compare against.
    if not isinstance(disk_value, (int, float)) or disk_value == 0.0:
        return []
    disk_value = float(disk_value)

    # Find the best primary-metric value across committed tracker entries.
    best_tracker_value: float | None = None
    best_run_id: str = ""
    best_iteration: Any = None
    for entry in tracker_history or []:
        if not isinstance(entry, dict) or not entry.get("committed"):
            continue
        value = resolve_primary_metric(entry.get("metrics") or {}, primary_metric)
        if not isinstance(value, (int, float)) or value == 0.0:
            continue
        value = float(value)
        if best_tracker_value is None or value > best_tracker_value:
            best_tracker_value = value
            best_run_id = str(entry.get("run_id", "") or "")
            best_iteration = entry.get("iteration")

    if best_tracker_value is None:
        # Nothing committed yet — leave the rest of the integrity report to
        # surface the missing-tracker situation.
        return []

    drift = disk_value - best_tracker_value
    if drift <= drift_threshold:
        return []

    return [
        IntegrityIssue(
            code="metrics_drift_unrecorded",
            severity="fatal",
            message=(
                f"Workspace output/metrics.json shows {primary_metric}="
                f"{disk_value:.4f} but tracker.best_value is "
                f"{best_tracker_value:.4f} from run_id "
                f"{best_run_id!r}. At least one experiment produced better "
                "results than the official tracker state. Likely cause: "
                "direct terminal execution bypassed run_experiment."
            ),
            context={
                "metrics_path": str(metrics_path),
                "primary_metric": primary_metric,
                "disk_value": disk_value,
                "tracker_best_value": best_tracker_value,
                "tracker_best_run_id": best_run_id,
                "tracker_best_iteration": best_iteration,
                "drift": drift,
                "drift_threshold": drift_threshold,
            },
        )
    ]


def _check_tracker_vs_artifact_mismatch(
    workspace_root: Path,
    evidence_root: Path,
    tracker_history: list[dict],
    primary_metric: str,
    drift_threshold: float = 0.005,  # 0.5 percentage points of absolute disagreement
) -> list[IntegrityIssue]:
    """Fatal: a committed tracker entry's primary metric disagrees with the
    value recorded in its own evidence artifact ``metrics.json``.

    Per-tracker-entry counterpart to :func:`_check_metrics_json_drift`: while
    that check compares workspace ``output/metrics.json`` against the best
    tracker entry (catching direct-execution runs that bypassed
    ``run_experiment``), this check compares each tracker entry against the
    specific artifact produced by the run it references — catching the split
    where the tracker was populated from agent-supplied ``action.metrics``
    instead of the actual run output.

    Concrete motivation: ``session_8e48c15d38cb`` (2026-04-22) had
    ``run_c5135625`` with tracker ``auc=0.8643`` but its own
    ``.evidence/runs/run_c5135625/artifacts/metrics.json`` said
    ``test.auc=0.8414``. Paper verification passed because verifier only
    checks that claimed metrics have SUPPORT somewhere — not that they match
    the artifact the run actually produced.

    Fixed going forward by commit ``e9b37652`` (RatchetCommitExecutor now
    sources tracker metrics from ``deps.last_experiment["metrics"]``), but
    this guard catches the same class of bug for older sessions and for any
    future regression of the ratchet path.

    For each committed tracker entry with a non-empty ``run_id``:

    1. Locate ``<evidence_root>/runs/<run_id>/artifacts/metrics.json``.
       Skip when missing — ``evidence_run_missing`` handles that case.
    2. Load it. Extract the primary-metric value via
       :func:`orchestrator.metrics_utils.resolve_primary_metric` (same prefix
       tolerance as the existing ``tracker_metric_missing`` check).
    3. Extract the tracker entry's primary metric the same way.
    4. If both resolve to non-zero values and their absolute difference
       exceeds ``drift_threshold``, emit a fatal issue.
    """
    if not tracker_history:
        return []

    # Narrow, function-scoped import to keep the orchestrator out of
    # integrity.py's import-time surface.
    from ..orchestrator.metrics_utils import resolve_primary_metric

    runs_dir = Path(evidence_root) / "runs"
    issues: list[IntegrityIssue] = []

    for idx, entry in enumerate(tracker_history):
        if not isinstance(entry, dict) or not entry.get("committed"):
            continue
        run_id = str(entry.get("run_id", "") or "")
        if not run_id:
            continue  # tracker_run_id_blank handles this

        artifact_path = runs_dir / run_id / "artifacts" / "metrics.json"
        if not artifact_path.exists():
            # evidence_run_missing handles absent evidence dirs; don't
            # double-flag here.
            continue

        try:
            raw = artifact_path.read_text(encoding="utf-8")
            artifact_metrics = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(artifact_metrics, dict):
            continue

        artifact_value = resolve_primary_metric(artifact_metrics, primary_metric)
        if not isinstance(artifact_value, (int, float)) or artifact_value == 0.0:
            continue
        artifact_value = float(artifact_value)

        tracker_value = resolve_primary_metric(
            entry.get("metrics") or {}, primary_metric
        )
        if not isinstance(tracker_value, (int, float)) or tracker_value == 0.0:
            continue
        tracker_value = float(tracker_value)

        if abs(tracker_value - artifact_value) <= drift_threshold:
            continue

        issues.append(
            IntegrityIssue(
                code="tracker_vs_artifact_mismatch",
                severity="fatal",
                message=(
                    f"tracker_vs_artifact_mismatch — run {run_id!r} tracker "
                    f"records {primary_metric}={tracker_value:.4f} but its "
                    f"evidence artifact ({artifact_path}) records "
                    f"{primary_metric}={artifact_value:.4f}. Tracker may have "
                    "been populated from agent-supplied action.metrics rather "
                    "than the run's actual output. Fixed for new sessions in "
                    "commit e9b37652; old sessions retain the inconsistency."
                ),
                context={
                    "run_id": run_id,
                    "iteration": entry.get("iteration"),
                    "tracker_value": tracker_value,
                    "artifact_value": artifact_value,
                    "artifact_path": str(artifact_path),
                    "primary_metric": primary_metric,
                },
            )
        )
    return issues
