"""Worker entry point for paper-generation pipeline.

Paper jobs are CPU/LLM jobs. They must not enter PathLab's GPU TaskQueueManager;
the descriptor worker invokes the standalone paper agent CLI in a subprocess
and then mirrors success/failure back into the DB row.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pathlab_paper_agent.bootstrap import server_root

_DEFAULT_SUBPROCESS_TIMEOUT_S = 60 * 60
_STDIO_TAIL_LIMIT = 4000


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
    extra_args: list[str] | None = None,
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
    if extra_args:
        cmd.extend(extra_args)

    env = os.environ.copy()
    pythonpath_entries = [str(root), str(paper_agent_src)]
    if env.get("PYTHONPATH"):
        pythonpath_entries.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    if env_overrides:
        env.update(env_overrides)
    timeout_s = _subprocess_timeout_s(env, env_overrides)
    started_at = datetime.now(UTC)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(root.parent),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        proc.kill()
        stdout, stderr = await proc.communicate()
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        _write_subprocess_log(
            uploads_dir,
            paper_id,
            command=cmd,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            returncode=proc.returncode,
            status="timeout",
            stdout=stdout_text,
            stderr=stderr_text,
            timeout_s=timeout_s,
        )
        raise TimeoutError(f"paper agent subprocess timed out after {timeout_s}s") from exc
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    _write_subprocess_log(
        uploads_dir,
        paper_id,
        command=cmd,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        returncode=proc.returncode,
        status="completed" if proc.returncode == 0 else "failed",
        stdout=stdout_text,
        stderr=stderr_text,
        timeout_s=timeout_s,
    )
    if proc.returncode == 0:
        return

    message = (
        f"paper agent subprocess failed with exit {proc.returncode}\n"
        f"STDOUT:\n{stdout_text[-_STDIO_TAIL_LIMIT:]}\nSTDERR:\n{stderr_text[-_STDIO_TAIL_LIMIT:]}"
    )
    raise RuntimeError(message)


def _subprocess_timeout_s(env: dict[str, str], overrides: dict[str, str] | None) -> float:
    raw = (overrides or {}).get("PATHLAB_PAPER_AGENT_TIMEOUT_S") or env.get("PATHLAB_PAPER_AGENT_TIMEOUT_S")
    if not raw:
        return float(_DEFAULT_SUBPROCESS_TIMEOUT_S)
    try:
        return max(1.0, float(raw))
    except ValueError:
        return float(_DEFAULT_SUBPROCESS_TIMEOUT_S)


def _write_subprocess_log(
    uploads_dir: Path,
    paper_id: str,
    *,
    command: list[str],
    started_at: datetime,
    finished_at: datetime,
    returncode: int | None,
    status: str,
    stdout: str,
    stderr: str,
    timeout_s: float,
) -> None:
    log_path = uploads_dir / "paper_generation" / paper_id / "logs" / "task_worker_subprocess.private.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "paper_id": paper_id,
        "status": status,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_ms": max(0, int((finished_at - started_at).total_seconds() * 1000)),
        "timeout_s": timeout_s,
        "returncode": returncode,
        "command": command,
        "stdout_tail": stdout[-_STDIO_TAIL_LIMIT:],
        "stderr_tail": stderr[-_STDIO_TAIL_LIMIT:],
    }
    tmp = log_path.with_name(f"{log_path.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, log_path)


async def _run_pipeline_job(
    paper_id: str,
    kwargs: dict[str, Any],
    *,
    command: str,
    start_stage: str,
    success_status: str,
    success_stage: str,
    extra_args: list[str] | None = None,
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
        await _run_paper_agent_subprocess(command, paper_id, uploads_dir, config_path, extra_args=extra_args)
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


async def rerun_from_stage(paper_id: str, **kwargs: Any) -> None:
    """Rerun from one executable paper stage using successful upstream history."""
    stage = str(kwargs.get("stage") or "")
    if not stage:
        raise ValueError("stage is required for paper stage rerun")
    await _run_pipeline_job(
        paper_id,
        dict(kwargs),
        command="run-from-stage",
        start_stage=stage,
        success_status="completed" if stage not in {"collecting", "building_evidence", "outlining"} else "awaiting_outline_approval",
        success_stage="completed" if stage not in {"collecting", "building_evidence", "outlining"} else "outlining",
        extra_args=["--stage", stage],
    )
