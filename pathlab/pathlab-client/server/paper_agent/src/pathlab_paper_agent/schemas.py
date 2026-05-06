"""
Pydantic request/response schemas for the paper-generation API.

Kept thin in M1 — extends as later milestones add fields (role tags, refinement
options, regenerate scope, ...).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class TemplateId(str, Enum):
    miccai = "miccai"
    nature_scientific_reports = "nature_scientific_reports"


class TaskRole(str, Enum):
    main = "main"
    ablation = "ablation"
    baseline = "baseline"
    external_validation = "external_validation"


class SourceTaskRef(BaseModel):
    task_id: str
    role: TaskRole = TaskRole.main
    label: Optional[str] = Field(
        default=None,
        description="Human-readable label, e.g. 'no-attention' for ablation_no_attention.",
    )


class CreatePaperRequest(BaseModel):
    """POST /papers body."""

    title: Optional[str] = None
    paper_type: str = "research_paper"
    language: str = "en"
    source_tasks: list[SourceTaskRef] = Field(default_factory=list)
    selected_templates: list[TemplateId] = Field(
        default_factory=lambda: [TemplateId.miccai],
        description=(
            "User-selected target template. The public API expects exactly one "
            "template per paper-writing run."
        ),
    )
    include_external_validation: bool = True
    user_idea: Optional[str] = Field(
        default=None,
        description=(
            "User-provided idea.md content. If absent the agent must prompt the "
            "user before invoking any LLM."
        ),
    )


class PaperRunStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class PaperRunStage(str, Enum):
    """Pipeline stage labels used by manifest and front-end polling.

    These names intentionally mirror the Phase 01 plan state machine so the
    standalone paper agent and Gateway do not drift.
    """

    created = "created"
    collecting = "collecting"
    building_evidence = "building_evidence"
    outlining = "outlining"
    plotting = "plotting"
    literature_review = "literature_review"
    section_writing = "section_writing"
    validating = "validating"
    refining = "refining"
    rendering = "rendering"
    exporting = "exporting"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class PaperRunSummary(BaseModel):
    """Returned by GET /papers and GET /papers/{id}."""

    paper_id: str
    status: PaperRunStatus
    current_stage: PaperRunStage
    title: Optional[str]
    selected_templates: list[TemplateId]
    source_task_ids: list[str]
    created_at: datetime
    finished_at: Optional[datetime]
    error_message: Optional[str]


class PaperRunArtifact(BaseModel):
    """Public artifact metadata shown in the UI."""

    path: str
    status: str = "ready"
    visibility: str = "public"
    downloadable: bool = True
    label: Optional[str] = None
    content_type: Optional[str] = None


class PaperArtifactIndexEntry(BaseModel):
    """Manifest artifact_index entry without the path key."""

    status: str = "ready"
    visibility: str = "public"
    downloadable: bool = True
    label: Optional[str] = None
    content_type: Optional[str] = None
    stale: bool = False


class OutlinePlottingPlanItem(BaseModel):
    """Public schema for one `drafts/outline.json` plotting plan item."""

    model_config = ConfigDict(extra="allow")

    figure_id: str
    kind: str
    source: str
    design_objective: str
    backend: str
    plot_spec: dict[str, Any] = Field(default_factory=dict)


class OutlineMicroLitCluster(BaseModel):
    """Public schema for focused literature-search clusters in an outline."""

    model_config = ConfigDict(extra="allow")

    cluster: str
    queries: list[str] = Field(min_length=1)


class OutlineSectionPlanItem(BaseModel):
    """Public schema for one planned manuscript section."""

    model_config = ConfigDict(extra="allow")

    section: str
    goal: str
    evidence_inputs: list[str] = Field(default_factory=list)
    citation_hints: list[str] = Field(default_factory=list)
    locked_block_inputs: list[str] = Field(default_factory=list)


class OutlinePathLabExtensions(BaseModel):
    """PathLab-specific outline metadata used by downstream agents."""

    model_config = ConfigDict(extra="allow")

    templates: list[str] = Field(default_factory=list)
    claim_plan: list[dict[str, Any]] = Field(default_factory=list)
    table_plan: list[dict[str, Any]] = Field(default_factory=list)
    guard_requirements: list[str] = Field(default_factory=list)
    template_styles: list[dict[str, Any]] = Field(default_factory=list)


class OutlineDocument(BaseModel):
    """Frontend-facing schema for `drafts/outline.json`."""

    model_config = ConfigDict(extra="allow")

    plotting_plan: list[OutlinePlottingPlanItem]
    macro_lit_search: list[str]
    micro_lit_clusters: list[OutlineMicroLitCluster]
    section_plan: list[OutlineSectionPlanItem]
    pathlab_extensions: OutlinePathLabExtensions


class FigureManifestItem(BaseModel):
    """Frontend-facing schema for one figure entry in `figures/manifest.json`."""

    model_config = ConfigDict(extra="allow")

    figure_id: str
    path: Optional[str] = None
    status: str
    source: Optional[str] = None
    generator: Optional[str] = None
    caption: Optional[str] = None
    content_type: Optional[str] = None
    kind: Optional[str] = None
    backend: Optional[str] = None
    error: Optional[str] = None


class FigureManifest(BaseModel):
    """Frontend-facing schema for `figures/manifest.json`."""

    model_config = ConfigDict(extra="allow")

    figures: list[FigureManifestItem] = Field(default_factory=list)


class PaperStageLogEntry(BaseModel):
    """Frontend-facing stage log entry with backwards-compatible fields."""

    model_config = ConfigDict(extra="allow")

    stage: str
    status: str = "completed"
    ts: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    message: Optional[str] = None
    error_message: Optional[str] = None


class GuardIssueSummary(BaseModel):
    """Public-safe preview of one guard issue."""

    code: str
    message: str
    severity: str = "error"
    path: Optional[str] = None
    context: Optional[str] = None


class GuardResultSummary(BaseModel):
    """Compact validation guard status for the frontend."""

    guard: str
    status: str = "not_run"
    issue_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    path: Optional[str] = None
    sample_issues: list[GuardIssueSummary] = Field(default_factory=list)


class RefinementSummary(BaseModel):
    """Compact M11 refinement-loop status."""

    final_status: Optional[str] = None
    max_iterations: Optional[int] = None
    accepted_iterations: list[int] = Field(default_factory=list)
    iteration_count: int = 0
    initial_score: Optional[dict[str, Any]] = None
    final_score: Optional[dict[str, Any]] = None
    log_path: Optional[str] = None


class ValidationSummary(BaseModel):
    """Aggregated validation/refinement state returned by GET /papers/{id}."""

    m10_guards: list[GuardResultSummary] = Field(default_factory=list)
    refinement: Optional[RefinementSummary] = None
    hybrid_score: Optional[float] = None
    warnings_md_path: Optional[str] = None


class PaperRunDetail(PaperRunSummary):
    """Detailed run view returned by GET /papers/{id}."""

    artifacts: list[PaperRunArtifact] = Field(default_factory=list)
    stage_log: list[PaperStageLogEntry] = Field(default_factory=list)
    validation_summary: ValidationSummary = Field(default_factory=ValidationSummary)


class PaperRunCreateResponse(BaseModel):
    paper_id: str
    status: PaperRunStatus = PaperRunStatus.pending
    message: str = "Paper run accepted; processing in background."


class PaperRunListResponse(BaseModel):
    items: list[PaperRunSummary]
    total: int


class PaperSection(BaseModel):
    """Editable public section text for the manuscript workbench."""

    section_name: str
    path: str
    content_hash: str
    text: str
    editable: bool = True
    updated_at: Optional[datetime] = None


class PaperSectionListResponse(BaseModel):
    sections: list[PaperSection] = Field(default_factory=list)


class SelectionLocatorResult(BaseModel):
    section_name: str
    paragraph_index: int
    sentence_index: Optional[int] = None
    char_start: int
    char_end: int
    matched_source_text: str
    normalized_selected_text: str
    normalized_source_text: str
    confidence: float
    ambiguous: bool = False


class DiffSummary(BaseModel):
    chars_added: int
    chars_removed: int
    paragraphs_changed: list[int] = Field(default_factory=list)
    sentences_changed: list[int] = Field(default_factory=list)
    preview_unified: str = ""


class RegenerateProgress(BaseModel):
    step: Literal[
        "queued",
        "locating",
        "drafting",
        "guarding",
        "refining",
        "compiling",
        "finalizing",
    ]
    detail: Optional[str] = None
    percent: Optional[int] = Field(default=None, ge=0, le=100)
    updated_at: datetime


class RegenerateJobEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    regen_id: str
    mode: Literal["section", "paragraph", "selection"] = "section"
    section_name: str
    target_paragraph: Optional[int] = None
    target_sentence: Optional[int] = None
    selected_text: Optional[str] = None
    source_hash: Optional[str] = None
    user_note: Optional[str] = None
    template_id: Optional[TemplateId] = None
    status: Literal[
        "queued",
        "running",
        "completed",
        "failed",
        "rejected",
        "cancelled",
        "cancelling",
    ]
    enqueued_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    locator: Optional[SelectionLocatorResult] = None
    replacement_text_preview: Optional[str] = None
    before_path: Optional[str] = None
    after_path: Optional[str] = None
    diff_summary: Optional[DiffSummary] = None
    guard_summary: list[GuardResultSummary] = Field(default_factory=list)
    refinement_summary: Optional[dict[str, Any]] = None
    final_pdf_path: Optional[str] = None
    export_bundle_path: Optional[str] = None
    progress: Optional[RegenerateProgress] = None


class RegenerateSectionRequest(BaseModel):
    mode: Literal["section", "paragraph", "selection"] = "section"
    target_section: Optional[str] = None
    target_paragraph: Optional[int] = Field(default=None, ge=0)
    target_sentence: Optional[int] = Field(default=None, ge=0)
    selected_text: Optional[str] = None
    source_hash: Optional[str] = None
    char_start: Optional[int] = Field(default=None, ge=0)
    char_end: Optional[int] = Field(default=None, ge=0)
    user_note: Optional[str] = None
    template_id: Optional[TemplateId] = None


class PaperSectionRegenerateAcceptedResponse(BaseModel):
    paper_id: str
    regen_id: str
    enqueued_at: datetime


class PaperSectionRegenerateResponse(BaseModel):
    paper_id: str
    status: PaperRunStatus
    current_stage: PaperRunStage
    regen_id: Optional[str] = None
    regenerated_sections: list[str] = Field(default_factory=list)
    refinement_log_summary: dict[str, Any] = Field(default_factory=dict)


class RegenerateRejectRequest(BaseModel):
    reason: Optional[str] = None
    template_id: Optional[TemplateId] = None


class RegenerateRejectResponse(BaseModel):
    regen_id: str
    status: Literal["rejected"]
    restored_sections: list[str] = Field(default_factory=list)
    final_pdf_path: Optional[str] = None


class PaperConfig(BaseModel):
    """Persisted to `config.json`. Everything the pipeline needs to resume."""

    paper_id: str
    title: Optional[str]
    paper_type: str
    language: str
    source_tasks: list[SourceTaskRef]
    selected_templates: list[TemplateId]
    include_external_validation: bool
    user_idea: Optional[str]


class PaperManifest(BaseModel):
    """Persisted to `manifest.json`. Mutable; updated as pipeline progresses.

    Each milestone appends to `stage_log` so the front-end can show progress
    history. `artifact_index` is the source of truth for which files are
    available for download under §3.7 allowlist.
    """

    paper_id: str
    status: PaperRunStatus
    current_stage: PaperRunStage
    stage_log: list[dict[str, Any]] = Field(default_factory=list)
    artifact_index: dict[str, Any] = Field(default_factory=dict)
    regenerate_jobs: list[dict[str, Any]] = Field(default_factory=list)
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime] = None
