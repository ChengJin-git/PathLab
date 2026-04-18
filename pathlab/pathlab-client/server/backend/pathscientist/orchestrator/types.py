"""Research session contracts and stage state for the PathScientist orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


STAGE_INTAKE = "intake"
STAGE_GROUNDING = "grounding"
STAGE_EXECUTION = "execution"
STAGE_REVIEW = "review"
STAGE_SYNTHESIS = "synthesis"
STAGE_COMPLETED = "completed"

MAX_CONSECUTIVE_STALLS = 2

ALLOWED_STAGE_TRANSITIONS: dict[str, set[str]] = {
    STAGE_INTAKE: {STAGE_GROUNDING},
    STAGE_GROUNDING: {STAGE_EXECUTION, STAGE_COMPLETED},
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
