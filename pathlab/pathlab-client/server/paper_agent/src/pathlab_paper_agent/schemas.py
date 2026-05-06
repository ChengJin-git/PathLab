"""
Pydantic request/response schemas for the paper-generation API.

Kept thin in M1 — extends as later milestones add fields (role tags, refinement
options, regenerate scope, ...).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


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


class PaperRunDetail(PaperRunSummary):
    """Detailed run view returned by GET /papers/{id}."""

    artifacts: list[PaperRunArtifact] = Field(default_factory=list)
    stage_log: list[dict[str, Any]] = Field(default_factory=list)
    validation_summary: Optional[dict[str, Any]] = None


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


class PaperSectionRegenerateResponse(BaseModel):
    paper_id: str
    status: PaperRunStatus
    current_stage: PaperRunStage
    regenerated_sections: list[str] = Field(default_factory=list)
    refinement_log_summary: dict[str, Any] = Field(default_factory=dict)


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
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime] = None
