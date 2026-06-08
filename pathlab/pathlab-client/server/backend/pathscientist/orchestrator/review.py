"""Deterministic review stage for PathScientist execution loops."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .types import ResearchSessionState, RunRecord


@dataclass
class ReviewRecord:
    """Structured post-execution review persisted for UI and routing."""

    iteration_index: int
    status: str
    decision: str
    summary: str
    diagnosis: str
    next_action: str
    latest_run_id: str = ""
    latest_metric_name: str = ""
    latest_metric_value: float | None = None
    previous_best_value: float | None = None
    best_value_after: float | None = None
    committed: bool = False
    metric_delta: float | None = None
    validity: dict[str, Any] = field(default_factory=dict)
    action_events: int = 0
    dropped_entries: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _metric_name(state: ResearchSessionState, latest: RunRecord | None) -> str:
    return latest.metric_name if latest and latest.metric_name else state.objective.success_metric or "metric"


def _fmt_metric(name: str, value: float | None) -> str:
    if value is None:
        return f"{name.upper()} --"
    return f"{name.upper()} {value:.4f}" if abs(value) < 10 else f"{name.upper()} {value:.2f}"


def _round_delta(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)


def _decision(state: ResearchSessionState) -> str:
    if _current_execution_skill(state) == "external_test" and not state.stop_reason:
        return "continue_execution"
    return "enter_synthesis" if state.stop_reason or state.iteration_index >= state.max_iterations else "continue_execution"


def _ensure_budget_stop_reason(state: ResearchSessionState) -> None:
    if _current_execution_skill(state) == "external_test" and not state.stop_reason:
        return
    if state.iteration_index >= state.max_iterations and not state.stop_reason:
        state.stop_reason = "budget_exhausted"


def _current_execution_skill(state: ResearchSessionState) -> str:
    plan = state.execution_plan or (state.grounding or {}).get("execution_plan") or {}
    steps = plan.get("steps") or []
    current = int(plan.get("current_step", 0) or 0)
    if 0 <= current < len(steps):
        step = steps[current]
        if isinstance(step, dict):
            return str(step.get("skill") or "")
    return ""


def _new_latest_run(state: ResearchSessionState, previous_run_count: int) -> RunRecord | None:
    if previous_run_count < 0:
        previous_run_count = 0
    new_runs = state.run_history[previous_run_count:]
    return new_runs[-1] if new_runs else None


def _build_no_finalized_review(
    state: ResearchSessionState,
    *,
    previous_best_value: float | None,
    action_events: int,
    dropped_entries: int,
) -> ReviewRecord:
    _ensure_budget_stop_reason(state)
    decision = _decision(state)
    metric_name = state.objective.success_metric or "metric"
    if action_events > 0:
        diagnosis = f"No finalized run was recorded after {action_events} tool action(s)."
    else:
        diagnosis = "No finalized run was recorded and no tool activity was detected."
    if state.stop_reason:
        next_action = f"Enter synthesis because stop_reason={state.stop_reason}."
    else:
        next_action = "Continue execution and require the agent to finalize a run with ratchet_commit or ratchet_revert."
    summary = (
        f"No finalized run for iteration {state.iteration_index}; {next_action}"
        if decision == "continue_execution"
        else f"Stopping review without a finalized run; {next_action}"
    )
    return ReviewRecord(
        iteration_index=state.iteration_index,
        status="no_finalized_run",
        decision=decision,
        summary=summary,
        diagnosis=diagnosis,
        next_action=next_action,
        latest_metric_name=metric_name,
        previous_best_value=previous_best_value,
        best_value_after=state.best_metric_value,
        validity={
            "finalized_run": False,
            "metric_present": False,
            "committed": False,
        },
        action_events=action_events,
        dropped_entries=dropped_entries,
    )


def _build_finalized_review(
    state: ResearchSessionState,
    latest: RunRecord,
    *,
    previous_best_value: float | None,
    action_events: int,
    dropped_entries: int,
) -> ReviewRecord:
    _ensure_budget_stop_reason(state)
    decision = _decision(state)
    metric_name = _metric_name(state, latest)
    metric_value = latest.metric_value
    metric_present = metric_value is not None and metric_value > 0
    previous_best = previous_best_value if previous_best_value is not None else 0.0
    delta = metric_value - previous_best if metric_present else None
    improved = bool(latest.committed and metric_present and metric_value >= previous_best)
    if not metric_present:
        status = "failed"
    elif improved:
        status = "improved"
    else:
        status = "not_improved"

    latest_label = _fmt_metric(metric_name, metric_value if metric_present else None)
    best_label = _fmt_metric(metric_name, state.best_metric_value if state.best_metric_value else previous_best)
    if status == "improved":
        diagnosis = (
            f"Run {latest.run_id} improved {metric_name.upper()} "
            f"from {previous_best:.4f} to {metric_value:.4f}."
        )
    elif status == "not_improved":
        diagnosis = (
            f"Run {latest.run_id} reached {latest_label}, which did not beat "
            f"the previous best {previous_best:.4f}."
        )
    else:
        diagnosis = f"Run {latest.run_id} did not provide a valid positive {metric_name.upper()} metric."

    if state.stop_reason:
        next_action = f"Enter synthesis because stop_reason={state.stop_reason}."
    elif decision == "enter_synthesis":
        next_action = "Enter synthesis because the iteration budget is exhausted."
    elif status == "improved":
        next_action = "Continue execution from the new best run and test one targeted improvement."
    elif status == "not_improved":
        next_action = "Continue execution while keeping the previous best and trying a different targeted change."
    else:
        next_action = "Continue execution after fixing metric/artifact generation."

    if decision == "enter_synthesis":
        summary = (
            f"Stopping after {state.iteration_index}/{state.max_iterations} iterations; "
            f"latest run {latest.run_id} has {latest_label}; best is {best_label}."
        )
    elif status == "improved":
        summary = (
            f"Iter {latest.iteration + 1} improved {metric_name.upper()} "
            f"to {metric_value:.4f}; continue with run {latest.run_id} as best."
        )
    elif status == "not_improved":
        summary = (
            f"Iter {latest.iteration + 1} reached {latest_label}, below best {best_label}; "
            "keep the previous best."
        )
    else:
        summary = f"Iter {latest.iteration + 1} failed review: {diagnosis}"

    return ReviewRecord(
        iteration_index=state.iteration_index,
        status=status,
        decision=decision,
        summary=summary,
        diagnosis=diagnosis,
        next_action=next_action,
        latest_run_id=latest.run_id,
        latest_metric_name=metric_name,
        latest_metric_value=metric_value if metric_present else None,
        previous_best_value=previous_best,
        best_value_after=state.best_metric_value,
        committed=bool(latest.committed),
        metric_delta=_round_delta(delta),
        validity={
            "finalized_run": True,
            "metric_present": metric_present,
            "committed": bool(latest.committed),
        },
        action_events=action_events,
        dropped_entries=dropped_entries,
    )


def run_review_stage(
    state: ResearchSessionState,
    *,
    previous_best_value: float | None,
    previous_run_count: int,
    action_events: int = 0,
    dropped_entries: int = 0,
) -> ReviewRecord:
    """Review the latest execution turn and persist a routing decision."""
    latest = _new_latest_run(state, previous_run_count)
    if latest is None:
        review = _build_no_finalized_review(
            state,
            previous_best_value=previous_best_value,
            action_events=action_events,
            dropped_entries=dropped_entries,
        )
    else:
        review = _build_finalized_review(
            state,
            latest,
            previous_best_value=previous_best_value,
            action_events=action_events,
            dropped_entries=dropped_entries,
        )

    payload = review.to_dict()
    state.latest_review = payload
    state.review_history.append(payload)
    state.review_decision = review.decision
    return review
