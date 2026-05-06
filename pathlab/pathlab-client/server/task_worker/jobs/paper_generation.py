"""TaskWorker compatibility entry point for the relocated paper agent."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _ensure_paper_agent_src_on_path() -> None:
    server_root = Path(__file__).resolve().parents[2]
    paper_agent_src = server_root / "paper_agent" / "src"
    src_str = str(paper_agent_src)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


async def run_paper_generation(paper_id: str, **kwargs: Any) -> None:
    """Run one paper-generation job through `server/paper_agent`."""
    _ensure_paper_agent_src_on_path()
    from pathlab_paper_agent.integrations.task_worker import run_paper_generation as _run

    await _run(paper_id, **kwargs)


async def regenerate_section(
    paper_id: str,
    regen_id: str,
    section_name: str,
    *,
    target_paragraph: int | None = None,
    user_note: str | None = None,
    target_section: str | None = None,
    uploads_dir: str | Path | None = None,
    **_kwargs: Any,
) -> None:
    """Run one queued section-regenerate job through `server/paper_agent`."""
    _ensure_paper_agent_src_on_path()
    from backend.common.config import Config
    from pathlab_paper_agent.regenerate import (
        mark_regenerate_job_completed,
        mark_regenerate_job_failed,
        mark_regenerate_job_running,
        regenerate_section as _regenerate_section,
    )

    resolved_uploads_dir = uploads_dir or Config.get_uploads_dir()
    mark_regenerate_job_running(
        paper_id,
        regen_id,
        section_name=section_name,
        uploads_dir=resolved_uploads_dir,
    )
    try:
        _regenerate_section(
            paper_id,
            section_name,
            uploads_dir=resolved_uploads_dir,
            target_paragraph=target_paragraph,
            user_note=user_note,
            target_section=target_section,
            regen_id=regen_id,
        )
    except Exception as exc:
        mark_regenerate_job_failed(
            paper_id,
            regen_id,
            str(exc),
            section_name=section_name,
            uploads_dir=resolved_uploads_dir,
        )
        raise
    mark_regenerate_job_completed(
        paper_id,
        regen_id,
        section_name=target_section or section_name,
        uploads_dir=resolved_uploads_dir,
    )
