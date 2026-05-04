"""Worker entry point for paper-generation pipeline.

Paper jobs are CPU/LLM jobs. They must not enter PathLab's GPU TaskQueueManager;
the descriptor worker invokes the standalone uv-managed paper agent CLI as a
subprocess and then mirrors success/failure back into the DB row.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any


async def run_paper_generation(paper_id: str, **kwargs: Any) -> None:
    """Run one paper-generation job through `server/paper_agent`.

    M1 CLI only marks the scaffold as completed, but the subprocess boundary is
    already the production boundary that later phases will keep.
    """
    from backend.common.config import Config
    from backend.database import safe_session
    from backend.database.repositories.paper_generation import PaperGenerationRunRepository

    uploads_dir = Path(str(kwargs.get("uploads_dir") or Config.get_uploads_dir())).resolve()
    server_root = Path(__file__).resolve().parents[2]
    paper_agent_dir = server_root / "paper_agent"
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
    env["PYTHONPATH"] = f"{server_root}{os.pathsep}{env.get('PYTHONPATH', '')}" if env.get("PYTHONPATH") else str(server_root)

    async with safe_session() as db:
        await PaperGenerationRunRepository.mark_started(db, paper_id)
        await PaperGenerationRunRepository.update_stage(db, paper_id, "created", status="running")
        await db.commit()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(server_root.parent),
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
