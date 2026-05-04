"""Schema re-exports used by the standalone runtime.

The source of truth remains `gateway.paper_generation.schemas` during Phase 01
so Gateway and the standalone dev service cannot drift.
"""

from __future__ import annotations

from .bootstrap import ensure_server_on_path

ensure_server_on_path()

from gateway.paper_generation.schemas import (  # noqa: E402,F401
    CreatePaperRequest,
    PaperConfig,
    PaperManifest,
    PaperRunArtifact,
    PaperRunCreateResponse,
    PaperRunDetail,
    PaperRunListResponse,
    PaperRunStage,
    PaperRunStatus,
    PaperRunSummary,
    SourceTaskRef,
    TaskRole,
    TemplateId,
)

__all__ = [
    "CreatePaperRequest",
    "PaperConfig",
    "PaperManifest",
    "PaperRunArtifact",
    "PaperRunCreateResponse",
    "PaperRunDetail",
    "PaperRunListResponse",
    "PaperRunStage",
    "PaperRunStatus",
    "PaperRunSummary",
    "SourceTaskRef",
    "TaskRole",
    "TemplateId",
]
