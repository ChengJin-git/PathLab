"""Durable analysis jobs, isolated CPU execution, and native output publication."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import defer

from backend.auth.models import User
from backend.common.config import Config
from backend.common.task_dispatch import (
    build_task_descriptor,
    enqueue_task_descriptor,
    is_worker_healthy,
)
from backend.database.database import safe_session
from backend.database.models import ResultAnalysis, AutoResearchSession, utc_now
from backend.services.workspaces import resolve_scope
from .contracts import AnalysisConfig, validate_selection
from .sources import authorized_sources, public_source


def run_directory(analysis_id):
    return Config.get_uploads_dir() / "analysis-workbench" / analysis_id


def public_run(row, detail=False):
    item = {
        "analysis_id": row.analysis_id,
        "title": row.title,
        "status": row.status,
        "progress": row.progress,
        "phase": row.phase,
        "error": row.error,
        "created_at": row.created_at.isoformat() + "Z",
        "finished_at": row.finished_at.isoformat() + "Z" if row.finished_at else None,
        "source_ids": [s["source_id"] for s in row.sources],
    }
    if detail:
        item.update(config=row.config, sources=row.sources, result=row.result)
    return item


async def submit(db, user, config, workspace_id=None, title=""):
    if not user.can_use_gpu():
        raise HTTPException(
            403, "Analysis execution requires pathologist or administrator access"
        )
    scope = await resolve_scope(db, user, workspace_id)
    if scope.execution_mode == "read_only" or "analysis" not in scope.enabled_skills:
        raise HTTPException(403, "Workspace does not permit analysis execution")
    sources = await authorized_sources(db, user, config.source_ids, workspace_id)
    try:
        validate_selection(config, sources)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    # Exact owner/workspace/config/revision matches can reuse finished or active
    # work. Authorization above is performed even on a cache hit.
    candidates = (await db.execute(select(ResultAnalysis).options(defer(ResultAnalysis.result)).where(
        ResultAnalysis.user_id == str(user.id), ResultAnalysis.workspace_id == workspace_id,
        ResultAnalysis.status.in_(["queued", "running", "completed"]),
    ).order_by(ResultAnalysis.created_at.desc()).limit(30))).scalars().all()
    revisions = {source.source_id: source.revision for source in sources}
    for existing in candidates:
        if existing.config == config.model_dump() and {s["source_id"]: s["revision"] for s in existing.sources} == revisions:
            await db.refresh(existing, ["result"])
            if existing.status != "completed" or (existing.result or {}).get("method_version") == "2":
                return existing
    if not await is_worker_healthy():
        raise HTTPException(503, "Task worker unavailable")
    row = ResultAnalysis(
        analysis_id="analysis_" + uuid4().hex,
        user_id=str(user.id),
        workspace_id=workspace_id,
        title=(title or " / ".join(s.title for s in sources))[:200],
        config=config.model_dump(),
        sources=[public_source(s) for s in sources],
        status="queued",
    )
    db.add(row)
    await db.commit()
    try:
        await enqueue_task_descriptor(
            build_task_descriptor(
                job_id=row.analysis_id,
                job_kind="analysis",
                handler="results.analysis",
                payload={"task_id": row.analysis_id},
            )
        )
    except Exception:
        row.status, row.error = "failed", "Unable to enqueue analysis"
        await db.commit()
        raise HTTPException(503, row.error) from None
    return row


async def owned_run(db, user, identity, workspace_id=None):
    row = await db.get(ResultAnalysis, identity)
    if row is None or (row.user_id != str(user.id) and not user.is_admin()):
        raise HTTPException(404, "Analysis not found")
    await authorized_sources(
        db, user, [s["source_id"] for s in row.sources], workspace_id
    )
    if not user.is_admin() or workspace_id:
        from backend.database.models import Dataset

        scope = await resolve_scope(db, user, workspace_id)
        original_datasets = {
            identity
            for source in row.sources
            for identity in source.get("dataset_ids", [])
        }
        allowed = set(
            (
                await db.execute(
                    scope.datasets(user).where(
                        Dataset.dataset_id.in_(original_datasets)
                    )
                )
            ).scalars()
        )
        if original_datasets - allowed:
            raise HTTPException(
                403, "Original analysis datasets are no longer accessible"
            )
    return row


async def execute_run(task_id: str):
    from .inputs import load_predictions

    process = None
    try:
        async with safe_session() as db:
            row = (
                await db.execute(
                    select(ResultAnalysis)
                    .where(ResultAnalysis.analysis_id == task_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None or row.status != "queued":
                return
            row.status = "running"
            row.phase, row.progress = "preparing", 2
            await db.commit()
            if db.bind.dialect.name == "postgresql":
                from sqlalchemy import text

                await db.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                )
            config = AnalysisConfig.model_validate(row.config)
            user = await db.get(User, UUID(row.user_id))
            if not user or not user.is_active or not user.can_use_gpu():
                raise ValueError("Analysis owner is no longer permitted to execute")
            scope = await resolve_scope(db, user, row.workspace_id)
            if (
                scope.execution_mode == "read_only"
                or "analysis" not in scope.enabled_skills
            ):
                raise ValueError("Workspace no longer permits analysis")
            sources = await authorized_sources(
                db, user, config.source_ids, row.workspace_id
            )
            validate_selection(config, sources)
            old_revisions = {s["source_id"]: s["revision"] for s in row.sources}
            inputs = []
            for source in sources:
                if old_revisions[source.source_id] != source.revision:
                    raise ValueError(
                        "Input results changed after submission; submit a new analysis"
                    )
                predictions = (
                    await load_predictions(db, source, config)
                    if source.task_id and source.details.get("prediction_count")
                    else []
                )
                if source.details.get("prediction_artifact"):
                    from .artifacts import read_predictions

                    session = await db.scalar(
                        select(AutoResearchSession).where(
                            AutoResearchSession.session_id == source.session_id
                        )
                    )
                    artifact = await asyncio.to_thread(
                        read_predictions,
                        Path(session.workspace_path),
                        source.details["prediction_artifact"],
                        config=config,
                    )
                    if (
                        artifact["prediction_sha256"]
                        != source.details["prediction_sha256"]
                    ):
                        raise ValueError(
                            "Published prediction artifact changed; publish the updated result before analysis"
                        )
                    predictions = artifact["rows"]
                    for prediction in predictions:
                        if prediction["dataset_id"] == "artifact":
                            prediction["dataset_id"] = source.source_id
                history = None
                if any(
                    chart.id == "loss" for chart in config.charts
                ) and source.details.get("history_path"):
                    path = Path(source.details["history_path"])

                    def read_history():
                        if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
                            return None
                        return json.loads(path.read_text())

                    history = await asyncio.to_thread(read_history)
                inputs.append(
                    {
                        "source_id": source.source_id,
                        "task_id": source.task_id,
                        "title": source.title,
                        "task_type": source.task_type,
                        "revision": source.revision,
                        "details": source.details,
                        "rows": predictions,
                        "training_history": history,
                    }
                )
        directory = run_directory(task_id)
        directory.mkdir(parents=True, exist_ok=True)

        def snapshot_code():
            import shutil

            code = directory / "analysis_code"
            code.mkdir(exist_ok=True)
            for path in Path(__file__).parent.glob("*.py"):
                shutil.copy2(path, code / path.name)

        await asyncio.to_thread(snapshot_code)
        await asyncio.to_thread(
            lambda: (directory / "input.json").write_text(
                json.dumps(
                    {"config": config.model_dump(), "sources": inputs},
                    ensure_ascii=False,
                )
            )
        )
        env = {
            **os.environ,
            "CUDA_VISIBLE_DEVICES": "",
            "OMP_NUM_THREADS": "2",
            "OPENBLAS_NUM_THREADS": "2",
            "MKL_NUM_THREADS": "2",
            "PYTHONPATH": str(Path(__file__).resolve().parents[3])
            + os.pathsep
            + os.environ.get("PYTHONPATH", ""),
        }
        with (directory / "compute.log").open("wb") as log:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "analysis_code.runner",
                str(directory),
                env=env,
                cwd=directory,
                stdout=log,
                stderr=log,
            )
            async def forward_progress():
                last = None
                while process.returncode is None:
                    await asyncio.sleep(1)
                    path = directory / "progress.json"
                    if not path.exists():
                        continue
                    progress = await asyncio.to_thread(lambda: json.loads(path.read_text()))
                    if progress == last:
                        continue
                    last = progress
                    from sqlalchemy import update
                    async with safe_session() as progress_db:
                        await progress_db.execute(update(ResultAnalysis).where(
                            ResultAnalysis.analysis_id == task_id, ResultAnalysis.status == "running",
                        ).values(progress=min(99, int(progress["progress"])), phase=progress["phase"]))
                        await progress_db.commit()
            monitor = asyncio.create_task(forward_progress())
            try:
                await asyncio.wait_for(process.wait(), timeout=3600)
            finally:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
        if process.returncode:
            error_path = directory / "error.json"
            raise ValueError(
                json.loads(error_path.read_text())["error"]
                if error_path.exists()
                else "Analysis computation failed"
            )
        result = await asyncio.to_thread(
            lambda: json.loads((directory / "result.json").read_text())
        )
        async with safe_session() as db:
            row = (
                await db.execute(
                    select(ResultAnalysis)
                    .where(ResultAnalysis.analysis_id == task_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row and row.status == "running":
                row.result, row.status, row.finished_at = result, "completed", utc_now()
                row.progress, row.phase = 100, "completed"
                await db.commit()
            elif row and row.status == "cancelling":
                row.status, row.finished_at = "cancelled", utc_now()
                await db.commit()
    except BaseException as exc:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        async with safe_session() as db:
            row = await db.get(ResultAnalysis, task_id)
            if row and row.status in {"running", "queued", "cancelling"}:
                row.status = (
                    "cancelled"
                    if isinstance(exc, asyncio.CancelledError)
                    or row.status == "cancelling"
                    else "failed"
                )
                row.error = (
                    "Analysis cancelled"
                    if row.status == "cancelled"
                    else str(exc)[:1000] or "Analysis timed out"
                )
                row.finished_at = utc_now()
                await db.commit()
        if isinstance(exc, asyncio.CancelledError):
            raise


async def recover():
    async with safe_session() as db:
        rows = (
            (
                await db.execute(
                    select(ResultAnalysis).where(
                        ResultAnalysis.status.in_(["running", "queued", "cancelling"])
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            if row.status in {"running", "cancelling"}:
                row.status, row.error, row.finished_at = (
                    "cancelled" if row.status == "cancelling" else "failed",
                    "Worker restarted during analysis; rerun the saved configuration",
                    utc_now(),
                )
        await db.commit()
        queued = [row.analysis_id for row in rows if row.status == "queued"]
    for identity in queued:
        await enqueue_task_descriptor(
            build_task_descriptor(
                job_id=identity,
                job_kind="analysis",
                handler="results.analysis",
                payload={"task_id": identity},
            )
        )


async def redispatch_pending():
    """Recover the commit/enqueue window without depending on an open browser."""
    from datetime import timedelta
    from backend.common.redis_client import get_redis

    async with safe_session() as db:
        identities = list(
            (
                await db.execute(
                    select(ResultAnalysis.analysis_id)
                    .where(
                        ResultAnalysis.status == "queued",
                        ResultAnalysis.created_at < utc_now() - timedelta(seconds=30),
                    )
                    .order_by(ResultAnalysis.created_at)
                    .limit(20)
                )
            ).scalars()
        )
    redis = get_redis()
    for identity in identities:
        if await redis.set(
            f"pathlab:result_redispatch:{identity}", "1", nx=True, ex=30
        ):
            await enqueue_task_descriptor(
                build_task_descriptor(
                    job_id=identity,
                    job_kind="analysis",
                    handler="results.analysis",
                    payload={"task_id": identity},
                )
            )
