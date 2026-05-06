"""Worker entry point for paper-generation pipeline.

Paper jobs are CPU/LLM jobs. They must not enter PathLab's GPU TaskQueueManager;
the descriptor worker invokes the standalone uv-managed paper agent CLI as a
subprocess and then mirrors success/failure back into the DB row.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Callable

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


async def _run_pipeline_job(
    paper_id: str,
    kwargs: dict[str, Any],
    *,
    start_stage: str,
    success_status: str,
    success_stage: str,
    runner: Callable[[str, Path, Path], object],
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
        await asyncio.to_thread(runner, paper_id, uploads_dir, config_path)
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
    env["PATHLAB_PAPER_AGENT_NO_APPROVAL_GATE"] = "1"

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


async def run_until_outline(paper_id: str, **kwargs: Any) -> None:
    """Run the pre-approval paper job and leave the DB row awaiting approval."""
    from pathlab_paper_agent.pipeline import run_until_outline as _run_until_outline

    def _runner(paper_id_arg: str, uploads_dir: Path, config_path: Path) -> object:
        return _run_until_outline(
            paper_id_arg,
            uploads_dir=uploads_dir,
            config_path=config_path,
        )

    await _run_pipeline_job(
        paper_id,
        dict(kwargs),
        start_stage="collecting",
        success_status="awaiting_outline_approval",
        success_stage="outlining",
        runner=_runner,
    )


async def run_after_outline(paper_id: str, **kwargs: Any) -> None:
    """Run the post-approval paper job and mark the DB row completed."""
    from pathlab_paper_agent.pipeline import run_after_outline as _run_after_outline

    def _runner(paper_id_arg: str, uploads_dir: Path, config_path: Path) -> object:
        return _run_after_outline(
            paper_id_arg,
            uploads_dir=uploads_dir,
            config_path=config_path,
        )

    await _run_pipeline_job(
        paper_id,
        dict(kwargs),
        start_stage="plotting",
        success_status="completed",
        success_stage="completed",
        runner=_runner,
    )
