"""Worker entry point for paper-generation pipeline.

Paper jobs are CPU/LLM jobs. They must not enter PathLab's GPU TaskQueueManager;
the descriptor worker invokes the standalone uv-managed paper agent CLI as a
subprocess and then mirrors success/failure back into the DB row.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from pathlab_paper_agent.bootstrap import server_root


async def run_paper_generation(paper_id: str, **kwargs: Any) -> None:
    """Run one paper-generation job through `server/paper_agent`.

    M1 CLI only marks the scaffold as completed, but the subprocess boundary is
    already the production boundary that later phases will keep.
    """
    from backend.common.config import Config
    from backend.database import safe_session
    from backend.database.repositories.paper_generation import PaperGenerationRunRepository

    uploads_dir = Path(str(kwargs.get("uploads_dir") or Config.get_uploads_dir())).resolve()
    root = server_root()
    paper_agent_dir = root / "paper_agent"
    config_path = uploads_dir / "paper_generation" / paper_id / "config.json"

    cmd = [
        "uv",
        "run",
        "--project",
        str(paper_agent_dir),
        "pathlab-paper-agent",
        "run",
        "--paper-id",
        paper_id,
        "--uploads-dir",
        str(uploads_dir),
        "--config",
        str(config_path),
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{root}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else str(root)
    )

    async with safe_session() as db:
        await PaperGenerationRunRepository.mark_started(db, paper_id)
        await PaperGenerationRunRepository.update_stage(
            db, paper_id, "created", status="running"
        )
        await db.commit()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(root.parent),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")

    async with safe_session() as db:
        if proc.returncode == 0:
            await PaperGenerationRunRepository.mark_completed(db, paper_id)
            await db.commit()
            return

        message = (
            f"paper agent subprocess failed with exit {proc.returncode}\n"
            f"STDOUT:\n{stdout_text[-4000:]}\nSTDERR:\n{stderr_text[-4000:]}"
        )
        await PaperGenerationRunRepository.mark_failed(db, paper_id, message)
        await db.commit()

    raise RuntimeError(message)


async def regenerate_section(paper_id: str, **kwargs: Any) -> None:
    """Run one regenerate job in the descriptor worker process."""
    from backend.common.config import Config
    from pathlab_paper_agent.regenerate import regenerate_section as _regenerate

    uploads_dir = Path(str(kwargs.pop("uploads_dir", Config.get_uploads_dir()))).resolve()
    _regenerate(
        paper_id,
        str(kwargs.pop("section_name")),
        uploads_dir=uploads_dir,
        regen_id=str(kwargs.pop("regen_id")),
        mode=str(kwargs.pop("mode", "section")),
        target_section=kwargs.pop("target_section", None),
        target_paragraph=kwargs.pop("target_paragraph", None),
        target_sentence=kwargs.pop("target_sentence", None),
        selected_text=kwargs.pop("selected_text", None),
        source_hash=kwargs.pop("source_hash", None),
        char_start=kwargs.pop("char_start", None),
        char_end=kwargs.pop("char_end", None),
        user_note=kwargs.pop("user_note", None),
        template_id=kwargs.pop("template_id", None),
    )
