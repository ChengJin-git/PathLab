"""Worker entry point for paper-generation pipeline.

Paper jobs are CPU/LLM jobs. They must not enter PathLab's GPU TaskQueueManager;
the descriptor worker invokes the standalone paper agent CLI in a subprocess
and then mirrors success/failure back into the DB row.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from pathlab_paper_agent.bootstrap import server_root


def _runtime_paths(paper_id: str, kwargs: dict[str, Any]) -> tuple[Path, Path]:
    from backend.common.config import Config

    uploads_dir = Path(str(kwargs.get("uploads_dir") or Config.get_uploads_dir())).resolve()
    config_path = Path(
        str(
            kwargs.get("config_path")
            or uploads_dir / "paper_generation" / paper_id / "config.json"
        )
    ).resolve()
    return uploads_dir, config_path


async def _run_paper_agent_subprocess(
    command: str,
    paper_id: str,
    uploads_dir: Path,
    config_path: Path,
    *,
    env_overrides: dict[str, str] | None = None,
) -> None:
    root = server_root()
    paper_agent_dir = root / "paper_agent"
    paper_agent_src = paper_agent_dir / "src"
    cmd = [
        sys.executable,
        "-m",
        "pathlab_paper_agent.cli",
        command,
        "--paper-id",
        paper_id,
        "--uploads-dir",
        str(uploads_dir),
        "--config",
        str(config_path),
    ]

    env = os.environ.copy()
    pythonpath_entries = [str(root), str(paper_agent_src)]
    if env.get("PYTHONPATH"):
        pythonpath_entries.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    if env_overrides:
        env.update(env_overrides)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(root.parent),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        return

    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    message = (
        f"paper agent subprocess failed with exit {proc.returncode}\n"
        f"STDOUT:\n{stdout_text[-4000:]}\nSTDERR:\n{stderr_text[-4000:]}"
    )
    raise RuntimeError(message)


async def _run_pipeline_job(
    paper_id: str,
    kwargs: dict[str, Any],
    *,
    command: str,
    start_stage: str,
    success_status: str,
    success_stage: str,
) -> None:
    from backend.database import safe_session
    from backend.database.repositories.paper_generation import PaperGenerationRunRepository

    uploads_dir, config_path = _runtime_paths(paper_id, kwargs)

    async with safe_session() as db:
        await PaperGenerationRunRepository.mark_started(db, paper_id)
        await PaperGenerationRunRepository.update_stage(
            db, paper_id, start_stage, status="running"
        )
        await db.commit()

    try:
        await _run_paper_agent_subprocess(command, paper_id, uploads_dir, config_path)
    except Exception as exc:
        async with safe_session() as db:
            await PaperGenerationRunRepository.mark_failed(db, paper_id, str(exc))
            await db.commit()
        raise

    async with safe_session() as db:
        if success_status == "completed":
            await PaperGenerationRunRepository.mark_completed(db, paper_id)
        else:
            await PaperGenerationRunRepository.update(
                db,
                paper_id,
                status=success_status,
                current_stage=success_stage,
                error_message=None,
                finished_at=None,
            )
        await db.commit()


async def run_paper_generation(paper_id: str, **kwargs: Any) -> None:
    """Run one paper-generation job through `server/paper_agent`.

    M1 CLI only marks the scaffold as completed, but the subprocess boundary is
    already the production boundary that later phases will keep.
    """
    from backend.common.config import Config
    from backend.database import safe_session
    from backend.database.repositories.paper_generation import PaperGenerationRunRepository

    uploads_dir = Path(str(kwargs.get("uploads_dir") or Config.get_uploads_dir())).resolve()
    config_path = uploads_dir / "paper_generation" / paper_id / "config.json"

    async with safe_session() as db:
        await PaperGenerationRunRepository.mark_started(db, paper_id)
        await PaperGenerationRunRepository.update_stage(
            db, paper_id, "created", status="running"
        )
        await db.commit()

    try:
        await _run_paper_agent_subprocess(
            "run",
            paper_id,
            uploads_dir,
            config_path,
            env_overrides={"PATHLAB_PAPER_AGENT_NO_APPROVAL_GATE": "1"},
        )
    except Exception as exc:
        message = str(exc)
        async with safe_session() as db:
            await PaperGenerationRunRepository.mark_failed(db, paper_id, message)
            await db.commit()
        raise

    async with safe_session() as db:
        await PaperGenerationRunRepository.mark_completed(db, paper_id)
        await db.commit()


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


async def run_until_outline(paper_id: str, **kwargs: Any) -> None:
    """Run the pre-approval paper job and leave the DB row awaiting approval."""
    await _run_pipeline_job(
        paper_id,
        dict(kwargs),
        command="run-until-outline",
        start_stage="collecting",
        success_status="awaiting_outline_approval",
        success_stage="outlining",
    )


async def run_after_outline(paper_id: str, **kwargs: Any) -> None:
    """Run the post-approval paper job and mark the DB row completed."""
    await _run_pipeline_job(
        paper_id,
        dict(kwargs),
        command="run-after-outline",
        start_stage="plotting",
        success_status="completed",
        success_stage="completed",
    )


async def run_render_export(paper_id: str, **kwargs: Any) -> None:
    """Re-render PDFs/exports after a user-edited section source."""
    await _run_pipeline_job(
        paper_id,
        dict(kwargs),
        command="render-export",
        start_stage="rendering",
        success_status="completed",
        success_stage="completed",
    )
