"""Research session contracts and stage state for the PathScientist orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


STAGE_INTAKE = "intake"
STAGE_GROUNDING = "grounding"
STAGE_ACQUISITION = "acquisition"
STAGE_EXECUTION = "execution"
STAGE_REVIEW = "review"
STAGE_SYNTHESIS = "synthesis"
STAGE_COMPLETED = "completed"

# Two-counter stall detection thresholds (Finding 6, 2026-04-22 review).
#
# Before: ``stall_count`` incremented on every turn that failed to ratchet,
# even productive turns that ran ``validate_script`` / ``file_editor`` /
# ``think`` back-to-back. With the old ``MAX_CONSECUTIVE_STALLS = 2`` a
# single post-commit "think → edit" pair tripped the guard and killed
# session_3f1795098784 at ``iteration_index=1`` of a 5-iteration budget.
#
# Now: two separate counters distinguish "frozen" from "working":
#   - ``consecutive_idle_turns`` — turns with ZERO ``ActionEvent`` emissions
#     (agent emitted nothing but a reply, not calling any tool). Threshold
#     ``MAX_IDLE_TURNS`` is kept tight — a truly idle agent is stuck.
#   - ``consecutive_non_finalized_turns`` — turns with tool calls but no
#     successful ``ratchet_commit`` / ``ratchet_revert``. Threshold
#     ``MAX_NON_FINALIZED_TURNS`` is deliberately generous so a normal
#     ``validate → quick_check → think → edit → validate → run`` sequence
#     has headroom.
#
# ``MAX_CONSECUTIVE_STALLS`` is preserved as the name of the legacy combined
# threshold; the runner still honours it when comparing the max of both
# counters so callers / tests that read ``state.stall_count`` keep working.
MAX_IDLE_TURNS = 2
MAX_NON_FINALIZED_TURNS = 6
MAX_CONSECUTIVE_STALLS = MAX_NON_FINALIZED_TURNS

ALLOWED_STAGE_TRANSITIONS: dict[str, set[str]] = {
    STAGE_INTAKE: {STAGE_GROUNDING},
    STAGE_GROUNDING: {STAGE_EXECUTION, STAGE_ACQUISITION, STAGE_COMPLETED},
    STAGE_ACQUISITION: {STAGE_EXECUTION, STAGE_COMPLETED},
    STAGE_EXECUTION: {STAGE_REVIEW},
    STAGE_REVIEW: {STAGE_EXECUTION, STAGE_SYNTHESIS},
    STAGE_SYNTHESIS: {STAGE_COMPLETED},
    STAGE_COMPLETED: set(),
}


@dataclass
class ResearchObjective:
    """What the user wants to achieve."""
    question: str
    success_metric: str = "auc"
    dataset_hint: str = ""
    preferred_skill: str = ""
    constraints: list[str] = field(default_factory=list)
    # Target set by grounding.SotaLookup. target_metric_value == 0.0 means
    # "no target" (no literature SOTA found, or lookup disabled).
    target_metric_value: float = 0.0
    target_source: str = ""           # human-readable "paper_id — paper_title"
    target_confidence: str = ""       # "high" | "medium" | "low"


@dataclass
class RunRecord:
    """Record of a single experiment run."""
    run_id: str
    iteration: int
    metric_name: str = "auc"
    metric_value: float = 0.0
    committed: bool = False
    notes: str = ""


@dataclass
class ResearchSessionState:
    """Mutable state for one research session managed by the orchestrator."""
    session_id: str
    conversation_id: UUID
    objective: ResearchObjective
    stage: str = STAGE_INTAKE
    grounding: dict = field(default_factory=dict)
    iteration_index: int = 0
    max_iterations: int = 3
    run_history: list[RunRecord] = field(default_factory=list)
    best_run_id: str = ""
    best_metric_value: float = 0.0
    approval_status: str = "none"  # "none" | "pending" | "approved" | "rejected"
    stall_count: int = 0
    # Two-counter stall tracking (Finding 6). ``stall_count`` above is
    # preserved as ``max(consecutive_idle_turns, consecutive_non_finalized_turns)``
    # so older persisted state / consumers keep reading a meaningful value.
    consecutive_idle_turns: int = 0
    consecutive_non_finalized_turns: int = 0
    stop_reason: str = ""  # "" | "stall_limit" | "approval_rejected" | "user_cancelled"
    final_summary: str = ""
    report_json_path: str = ""
    report_markdown_path: str = ""
    paper_draft_path: str = ""
    claim_count: int = 0
    paper_verification_path: str = ""
    paper_verification_passed: bool = False
    paper_verification_issue_count: int = 0
    paper_critique_path: str = ""
    paper_critique_issue_count: int = 0
    paper_ready: bool = False
    # IntegrityGuard report dumped by ``_run_integrity_check`` at session end.
    # Shape mirrors ``runtime.integrity.IntegrityReport.to_dict()`` —
    # ``{"passed", "fatal_count", "warning_count", "issues": [...]}``.
    # Present so downstream CLI surfaces and ``synthesis.report_builder`` can
    # render the invariants that failed without re-running the checks.
    integrity_report: dict = field(default_factory=dict)
    # Dataset acquisition fields (plan 2026-04-25 T7). Populated when the
    # orchestrator routes through ``STAGE_ACQUISITION``. ``task_profile`` is
    # the dict emitted by grounding (T1); ``selected_dataset`` summarizes the
    # winning candidate; ``dataset_manifest_path`` is the on-disk manifest
    # written by ``DatasetAcquisitionService``.
    task_profile: dict = field(default_factory=dict)
    dataset_candidates: list[dict] = field(default_factory=list)
    selected_dataset: dict = field(default_factory=dict)
    dataset_manifest_path: str = ""
    acquisition_status: str = "none"  # "none" | "prepared" | "skipped" | "skipped_policy" | "failed"
    acquisition_notes: str = ""

    @classmethod
    def create(
        cls,
        session_id: str,
        conversation_id: UUID,
        objective: ResearchObjective,
    ) -> ResearchSessionState:
        return cls(
            session_id=session_id,
            conversation_id=conversation_id,
            objective=objective,
        )

    @property
    def pending_approval(self) -> bool:
        """Backward-compat read-only alias for approval_status == 'pending'."""
        return self.approval_status == "pending"

    def advance(self, next_stage: str) -> None:
        """Advance to the next stage. Raises ValueError on invalid transition."""
        allowed = ALLOWED_STAGE_TRANSITIONS.get(self.stage, set())
        if next_stage not in allowed:
            raise ValueError(
                f"Invalid stage transition: {self.stage} -> {next_stage}. "
                f"Allowed: {allowed}"
            )
        self.stage = next_stage

    def record_run(self, record: RunRecord) -> None:
        """Record a completed experiment run. Updates best if committed and higher."""
        self.run_history.append(record)
        if record.committed and record.metric_value >= self.best_metric_value:
            self.best_run_id = record.run_id
            self.best_metric_value = record.metric_value
