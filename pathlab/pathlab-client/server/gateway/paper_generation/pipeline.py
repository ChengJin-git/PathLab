"""
Paper-generation orchestration pipeline.

M1: only sets up the run scaffold (directory tree + manifest.json + config.json).
M2-M12 each replace `run_paper_generation` step-by-step. By design the function
signature does NOT change as milestones land — each milestone fills in one
stage of the pipeline and is responsible for advancing `manifest.current_stage`
and writing its own artifact files.

This module deliberately avoids importing any LLM / collector / agent code at
the top level: the function is callable from the worker queue without dragging
the entire dependency graph in.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import utc_now
from backend.database.repositories.paper_generation import (
    PaperGenerationRunRepository,
)

from .schemas import (
    PaperConfig,
    PaperManifest,
    PaperRunStage,
    PaperRunStatus,
)
from .storage import PaperRunPaths

logger = logging.getLogger(__name__)


def _serialize(payload: Any) -> str:
    """JSON dump with stable formatting and timezone-aware datetimes."""

    def default(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, "value"):
            return obj.value
        raise TypeError(f"Cannot serialize {type(obj).__name__}")

    return json.dumps(payload, indent=2, ensure_ascii=False, default=default)


async def initialize_paper_run(
    db: AsyncSession,
    config: PaperConfig,
) -> PaperRunPaths:
    """Create on-disk scaffold for a new paper run.

    M1 entry point. Idempotent: if the directory already exists, files are
    overwritten with the latest config/manifest.
    """
    paths = PaperRunPaths.for_paper(config.paper_id)
    paths.ensure_dirs()

    paths.config.write_text(
        _serialize(config.model_dump(mode="json")), encoding="utf-8"
    )

    now = utc_now()
    manifest = PaperManifest(
        paper_id=config.paper_id,
        status=PaperRunStatus.pending,
        current_stage=PaperRunStage.created,
        stage_log=[
            {
                "stage": PaperRunStage.created.value,
                "ts": now.isoformat(),
                "message": "Paper run scaffold created.",
            }
        ],
        artifact_index={
            "config.json": {
                "status": "ready",
                "visibility": "public",
                "downloadable": True,
                "label": "Run config",
                "content_type": "application/json",
            },
            "manifest.json": {
                "status": "ready",
                "visibility": "public",
                "downloadable": True,
                "label": "Run manifest",
                "content_type": "application/json",
            },
        },
        created_at=now,
        updated_at=now,
    )
    paths.manifest.write_text(
        _serialize(manifest.model_dump(mode="json")), encoding="utf-8"
    )

    logger.info(
        "paper_generation: initialized run %s with %d source tasks, templates=%s",
        config.paper_id,
        len(config.source_tasks),
        [t.value for t in config.selected_templates],
    )

    return paths


async def run_paper_generation(db: AsyncSession, paper_id: str) -> None:
    """Worker entrypoint. Stub for M1 — does NOT yet run any agents.

    M2+ will each fill in their own stage. The function MUST advance the DB
    row's status/stage so the front-end and `GET /papers/{id}` reflect
    reality.
    """
    repo = PaperGenerationRunRepository
    run = await repo.get_by_id(db, paper_id)
    if run is None:
        logger.error("paper_generation: paper_id %s not found in DB", paper_id)
        return

    # M1 stub: mark as running, record that no actual work was done yet, and
    # leave the run in `pending` so the front-end shows it's awaiting M2 work.
    await repo.update(
        db,
        paper_id,
        status=PaperRunStatus.pending.value,
        current_stage=PaperRunStage.created.value,
    )
    logger.info(
        "paper_generation: M1 stub invoked for %s; no agents implemented yet",
        paper_id,
    )
