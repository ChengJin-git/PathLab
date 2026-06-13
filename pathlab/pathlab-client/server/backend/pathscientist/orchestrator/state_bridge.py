"""Serialize / deserialize ResearchSessionState through OpenHands agent_state."""
from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from uuid import UUID

from .types import ResearchObjective, ResearchSessionState, RunRecord
from .metrics_utils import resolve_primary_metric
from ..persistence.state_bridge import read_agent_state, update_agent_state

if TYPE_CHECKING:
    from openhands.sdk.conversation.impl.local_conversation import LocalConversation

RESEARCH_SESSION_KEY = "research_session"


def _repair_research_session_payload(
    payload: dict[str, Any],
    tracker_state: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Repair stale persisted run metrics from tracker history when possible."""
    repaired = dict(payload)
    run_history = [dict(r) for r in repaired.get("run_history", [])]
    tracker_history = (tracker_state or {}).get("history", [])
    metric_name = repaired.get("objective", {}).get("success_metric", "auc")
    changed = False

    for idx, run in enumerate(run_history):
        if idx >= len(tracker_history):
            break
        tracker_entry = tracker_history[idx]
        if not isinstance(tracker_entry, dict):
            continue
        metric_value = resolve_primary_metric(tracker_entry.get("metrics", {}), run.get("metric_name", metric_name))
        if metric_value and run.get("metric_value", 0.0) != metric_value:
            run["metric_value"] = metric_value
            changed = True
        tracker_run_id = tracker_entry.get("run_id", "")
        if tracker_run_id and not run.get("run_id", ""):
            run["run_id"] = tracker_run_id
            changed = True

    if changed:
        repaired["run_history"] = run_history

    best_run_id = ""
    best_metric_value = 0.0
    for run in run_history:
        if not run.get("committed", False):
            continue
        value = float(run.get("metric_value", 0.0) or 0.0)
        if value >= best_metric_value:
            best_metric_value = value
            best_run_id = run.get("run_id", "")

    if run_history and repaired.get("best_metric_value", 0.0) != best_metric_value:
        repaired["best_metric_value"] = best_metric_value
        changed = True
    if run_history and repaired.get("best_run_id", "") != best_run_id:
        repaired["best_run_id"] = best_run_id
        changed = True

    return repaired, changed


def dump_research_session_state(state: ResearchSessionState) -> dict[str, Any]:
    """Serialize ResearchSessionState to a JSON-safe dict."""
    payload = asdict(state)
    payload["conversation_id"] = str(state.conversation_id)
    return payload


def persist_research_session_state(
    conversation: LocalConversation,
    state: ResearchSessionState,
) -> None:
    """Write research session state into conversation's agent_state."""
    update_agent_state(
        conversation,
        **{RESEARCH_SESSION_KEY: dump_research_session_state(state)},
    )


def load_research_session_state(
    conversation: "LocalConversation | dict[str, Any]",
) -> ResearchSessionState | None:
    """Read research session state from a conversation or a raw payload dict.

    The historical signature took a ``LocalConversation`` and read the
    payload out of agent_state. To keep the contract usable from tests and
    from places that already hold the dict (plan 2026-04-25 T7 unit tests),
    a plain ``dict`` is also accepted — in that case no agent_state read /
    write happens. Returns ``None`` when nothing is persisted.
    """
    if isinstance(conversation, dict):
        payload = conversation
        if not payload:
            return None
    else:
        payload = read_agent_state(conversation, RESEARCH_SESSION_KEY)
        if not payload:
            return None
        tracker_state = read_agent_state(conversation, "tracker_state", {})
        payload, changed = _repair_research_session_payload(payload, tracker_state)
        if changed:
            update_agent_state(conversation, **{RESEARCH_SESSION_KEY: payload})
    objective_payload = dict(payload["objective"])
    # Back-compat: older persisted states lack target_* fields.
    for key in ("target_source", "target_confidence"):
        objective_payload.setdefault(key, "")
    objective_payload.setdefault("target_metric_value", 0.0)
    objective = ResearchObjective(**objective_payload)
    return ResearchSessionState(
        session_id=payload["session_id"],
        conversation_id=UUID(payload["conversation_id"]),
        objective=objective,
        stage=payload["stage"],
        stage_started_at=float(payload.get("stage_started_at") or 0.0),
        stage_history=list(payload.get("stage_history") or []),
        grounding=payload.get("grounding", {}),
        iteration_index=payload.get("iteration_index", 0),
        max_iterations=payload.get("max_iterations", 3),
        run_history=[RunRecord(**r) for r in payload.get("run_history", [])],
        best_run_id=payload.get("best_run_id", ""),
        best_metric_value=payload.get("best_metric_value", 0.0),
        approval_status=payload.get(
            "approval_status",
            "pending" if payload.get("pending_approval", False) else "none",
        ),
        stall_count=payload.get("stall_count", 0),
        consecutive_idle_turns=payload.get("consecutive_idle_turns", 0),
        consecutive_non_finalized_turns=payload.get("consecutive_non_finalized_turns", 0),
        stop_reason=payload.get("stop_reason", ""),
        final_summary=payload.get("final_summary", ""),
        ui_run_summary=dict(payload.get("ui_run_summary") or {}),
        latest_review=dict(payload.get("latest_review") or {}),
        review_history=list(payload.get("review_history") or []),
        review_decision=payload.get("review_decision", ""),
        report_json_path=payload.get("report_json_path", ""),
        report_markdown_path=payload.get("report_markdown_path", ""),
        paper_draft_path=payload.get("paper_draft_path", ""),
        claim_count=payload.get("claim_count", 0),
        paper_verification_path=payload.get("paper_verification_path", ""),
        paper_verification_passed=payload.get("paper_verification_passed", False),
        paper_verification_issue_count=payload.get("paper_verification_issue_count", 0),
        paper_critique_path=payload.get("paper_critique_path", ""),
        paper_critique_issue_count=payload.get("paper_critique_issue_count", 0),
        paper_ready=payload.get("paper_ready", False),
        execution_brief=payload.get("execution_brief", ""),
        execution_brief_path=payload.get("execution_brief_path", ""),
        integrity_report=payload.get("integrity_report", {}) or {},
        # Back-compat for plan 2026-04-25 (T7): older states lack
        # acquisition fields. Default everything to empty / "none".
        task_profile=dict(payload.get("task_profile") or {}),
        dataset_candidates=list(payload.get("dataset_candidates") or []),
        selected_dataset=dict(payload.get("selected_dataset") or {}),
        dataset_manifest_path=payload.get("dataset_manifest_path", ""),
        acquisition_status=payload.get("acquisition_status", "none"),
        acquisition_notes=payload.get("acquisition_notes", ""),
        # Plan-2026-04-30 data-readiness Task 6.
        data_readiness=dict(payload.get("data_readiness") or {}),
        execution_plan=dict(payload.get("execution_plan") or {}),
        external_test=dict(payload.get("external_test") or {}),
        external_test_history=list(payload.get("external_test_history") or []),
    )
