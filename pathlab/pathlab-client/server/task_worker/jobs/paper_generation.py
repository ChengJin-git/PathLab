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


async def regenerate_section(paper_id: str, **kwargs: Any) -> None:
    """Run a section/paragraph/selection regenerate job."""
    _ensure_paper_agent_src_on_path()
    from pathlab_paper_agent.integrations.task_worker import regenerate_section as _run

    await _run(paper_id, **kwargs)


async def run_until_outline(paper_id: str, **kwargs: Any) -> None:
    """Run Job A: stop after producing drafts/outline.json."""
    _ensure_paper_agent_src_on_path()
    from pathlab_paper_agent.integrations.task_worker import run_until_outline as _run

    await _run(paper_id, **kwargs)


async def run_after_outline(paper_id: str, **kwargs: Any) -> None:
    """Run Job B: resume after the approved outline."""
    _ensure_paper_agent_src_on_path()
    from pathlab_paper_agent.integrations.task_worker import run_after_outline as _run

    await _run(paper_id, **kwargs)
