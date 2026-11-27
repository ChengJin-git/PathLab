"""Durable conversation deletion, executed by the research supervisor.

The HTTP transaction records deletion intent and returns immediately. Internal
cleanup records are not user-facing tasks. The worker first stops every writer,
then removes task-owned files and records, retrying after restarts or failures.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import time
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import delete, select, update

from backend.common.config import Config
from backend.database.database import safe_session
from backend.database.models import (
    AIResult,
    AnalysisRun,
    AutoResearchEvent,
    AutoResearchExperiment,
    AutoResearchSession,
    ChatConversation,
    Manuscript,
    ManuscriptGeneration,
    ResearchJob,
    StorageTask,
    TrainedModel,
    TrainingLog,
    TrainingTask,
    TrainingTaskWSI,
    WorkbenchFile,
    ResultSource,
    ResultSourceDataset,
    WSISlide,
    utc_now,
)

log = logging.getLogger(__name__)
_cancellations: dict[str, asyncio.Task] = {}


def schedule_cancellation(task_id: str):
    """Start promptly without making the response wait for process/network I/O.

    Strong references keep this best-effort accelerator alive after the request.
    The committed cleanup record remains authoritative if the Gateway exits.
    """
    if task_id in _cancellations:
        return

    async def stop():
        try:
            async with safe_session() as db:
                task = await db.scalar(
                    select(StorageTask).where(StorageTask.task_id == task_id)
                )
                if not task or task.status == "completed":
                    return
                rows = (
                    await db.scalars(
                        select(AutoResearchSession).where(
                            AutoResearchSession.session_id.in_(task.params["session_ids"])
                        )
                    )
                ).all()
            if rows:
                await cancel_immediately(rows)
        except Exception:
            log.exception("Conversation cancellation will be retried by the cleanup worker")
        finally:
            _cancellations.pop(task_id, None)

    _cancellations[task_id] = asyncio.create_task(stop())


async def cancel_immediately(rows):
    """Accelerate committed cancellation without waiting for a cleanup-queue turn.

    Durable DB cancellation also works when Redis is unavailable. Process identity
    checks let the Gateway stop local sandboxes without killing a recycled PID.
    """
    from backend.common.task_dispatch import publish_task_cancellation
    from backend.autoresearch.engine.processes import stop_session

    async def broadcast(identity):
        try:
            await asyncio.wait_for(publish_task_cancellation(identity), timeout=2)
        except Exception:
            log.warning(
                "Cancellation transport unavailable for %s; durable cancellation remains pending",
                identity,
            )

    async with safe_session() as db:
        jobs = (
            await db.scalars(
                select(ResearchJob).where(
                    ResearchJob.session_id.in_([row.session_id for row in rows]),
                    ResearchJob.status.in_({"cancelled", "cancelling"}),
                )
            )
        ).all()
    results = await asyncio.gather(
        *(broadcast(job.job_id) for job in jobs),
        *(stop_session(row) for row in rows),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception):
            log.warning(
                "Immediate process cleanup needs supervisor retry: %s",
                type(result).__name__,
            )


async def mark_jobs_cancelled(db, rows):
    ids = [row.session_id for row in rows]
    jobs = (
        await db.scalars(
            select(ResearchJob)
            .where(
                ResearchJob.session_id.in_(ids),
                ResearchJob.status.in_({"queued", "running", "cancelling"}),
            )
            .with_for_update()
        )
    ).all()
    for job in jobs:
        job.status = "cancelled" if job.status == "queued" else "cancelling"
        await db.execute(
            update(AutoResearchExperiment)
            .where(
                AutoResearchExperiment.session_id == job.session_id,
                AutoResearchExperiment.training_task_id == job.job_id,
            )
            .values(status=job.status)
        )


def deletion_id(conversation_id: str) -> str:
    return "chat_delete_" + hashlib.sha256(conversation_id.encode()).hexdigest()[:32]


async def request_deletion(db, conversation_id: str, user) -> dict:
    task_id = deletion_id(conversation_id)
    conversation = await db.scalar(
        select(ChatConversation)
        .where(ChatConversation.conversation_id == conversation_id)
        .with_for_update()
    )
    if not conversation:
        task = await db.scalar(select(StorageTask).where(StorageTask.task_id == task_id))
        if task and (task.user_id == str(user.id) or user.is_admin()):
            return {
                "conversation_id": conversation_id,
                "cleanup_task_id": task_id,
                "status": "deleted",
            }
        raise HTTPException(404, "Conversation not found")
    if conversation.user_id != str(user.id) and not user.is_admin():
        raise HTTPException(403, "Conversation access denied")
    task = await db.scalar(
        select(StorageTask).where(StorageTask.task_id == task_id).with_for_update()
    )
    if task:
        if task.status == "failed":
            task.status, task.error_message = "pending", None
            task.params = {**task.params, "retry_after": 0}
        await db.commit()
        schedule_cancellation(task_id)
        return {
            "conversation_id": conversation_id,
            "cleanup_task_id": task_id,
            "status": "deleted",
        }
    rows = (
        await db.scalars(
            select(AutoResearchSession)
            .where(AutoResearchSession.chat_conversation_id == conversation_id)
            .with_for_update()
        )
    ).all()
    for row in rows:
        row.recovery_metadata = {
            **(row.recovery_metadata or {}),
            "delete_requested": True,
            "commands": [],
        }
        row.status = "stopping"
    task = StorageTask(
        task_id=task_id,
        user_id=conversation.user_id,
        task_type="chat_delete",
        status="pending",
        total_items=len(rows),
        params={
            "conversation_id": conversation_id,
            "session_ids": [r.session_id for r in rows],
        },
    )
    db.add(task)
    await db.execute(
        update(WorkbenchFile)
        .where(
            (WorkbenchFile.conversation_id == conversation_id)
            | WorkbenchFile.session_id.in_([row.session_id for row in rows])
        )
        .values(deleted=True, index_status="deleted", indexed_revision=None)
    )
    await mark_jobs_cancelled(db, rows)
    await db.commit()
    if rows:
        schedule_cancellation(task_id)
    return {
        "conversation_id": conversation_id,
        "cleanup_task_id": task_id,
        "status": "deleted",
    }


def remove_owned_path(path: str, root: Path) -> None:
    candidate = Path(path)
    # Validate the parent without following a final symlink into input data.
    if candidate == root or not candidate.parent.resolve().is_relative_to(
        root.resolve()
    ):
        raise ValueError("Cleanup path is outside task-owned storage")
    if candidate.is_symlink() or candidate.is_file():
        candidate.unlink(missing_ok=True)
    elif candidate.exists():
        shutil.rmtree(candidate)


async def cleanup_records_and_files(task_id: str):
    """Called only after agent, compute and writing tasks acknowledged cancellation."""

    async with safe_session() as db:
        task = await db.scalar(
            select(StorageTask).where(StorageTask.task_id == task_id)
        )
        params = task.params
        ids, cid = params["session_ids"], params["conversation_id"]
        rows = (
            await db.scalars(
                select(AutoResearchSession).where(
                    AutoResearchSession.session_id.in_(ids)
                )
            )
        ).all()
        jobs = (
            await db.scalars(select(ResearchJob).where(ResearchJob.session_id.in_(ids)))
        ).all()
        if any(job.status in {"queued", "running", "cancelling"} for job in jobs):
            raise RuntimeError("Waiting for experiment cancellation acknowledgement")
        run_ids = [job.job_id for job in jobs]
        models = (
            await db.scalars(
                select(TrainedModel).where(TrainedModel.task_id.in_(run_ids))
            )
        ).all()
        reports = (
            await db.scalars(
                select(Manuscript).where(
                    (Manuscript.source_type == "research")
                    & Manuscript.source_id.in_(ids)
                    | (Manuscript.source_type == "experiment")
                    & Manuscript.source_id.in_(run_ids)
                )
            )
        ).all()
        feature_paths = []
        dataset_ids = {
            d["dataset_id"]
            for row in rows
            for d in (row.recovery_metadata or {}).get("datasets", [])
        }
        # Remove only feature registrations physically owned by these research runs.
        for dataset_id in dataset_ids:
            after = ""
            while True:
                slides = (
                    await db.scalars(
                        select(WSISlide)
                        .where(
                            WSISlide.dataset_id == dataset_id, WSISlide.wsi_id > after
                        )
                        .order_by(WSISlide.wsi_id)
                        .limit(200)
                    )
                ).all()
                if not slides:
                    break
                for slide in slides:
                    associated = dict(slide.associated_files or {})
                    features = dict(associated.get("autoresearch_features") or {})
                    kept = {}
                    for key, feature in features.items():
                        path = Path(feature.get("feature_path") or "")
                        directory = Path(feature.get("features_dir") or path.parent)
                        if any(
                            directory.name == f"research_{sid}_{dataset_id}"
                            for sid in ids
                        ):
                            feature_paths.append(str(directory))
                        else:
                            kept[key] = feature
                    if kept != features:
                        associated["autoresearch_features"] = kept
                        slide.associated_files = associated
                after = slides[-1].wsi_id
                await db.flush()
        from backend.services.file_library import file_cleanup_record

        files = (
            await db.scalars(
                select(WorkbenchFile).where(
                    (WorkbenchFile.conversation_id == cid)
                    | WorkbenchFile.session_id.in_(ids)
                )
            )
        ).all()
        # Save an immutable cleanup manifest before removing bytes or records.
        manifest = params.get("manifest") or {
            "run_ids": run_ids,
            "model_ids": {
                run: [m.model_id for m in models if m.task_id == run] for run in run_ids
            },
            "report_ids": [r.report_id for r in reports],
            "files": [file_cleanup_record(row) for row in files if row.kind == "file"],
            "feature_paths": list(set(feature_paths)),
            "workspace_paths": [
                row.workspace_path for row in rows if row.workspace_path
            ],
        }
        task.params = {**params, "manifest": manifest}
        await db.commit()
    from backend.services.file_library import purge_file

    for record in manifest["files"]:
        await asyncio.to_thread(purge_file, record)
    from gateway.routes.chat_patch_inference import cleanup_conversation_chat_patch_tasks

    await cleanup_conversation_chat_patch_tasks(cid)
    from backend.autoresearch.engine.input_files import cleanup_input_views

    for sid in ids:
        await asyncio.to_thread(cleanup_input_views, Config.get_autoresearch_dir() / 'runtime' / sid)
    async with safe_session() as db:
        runs = manifest["run_ids"]
        from backend.storage.deletion import enqueue, task_paths
        paths = [path for run in runs for path in task_paths(run, manifest['model_ids'].get(run, []))]
        paths.extend(manifest['feature_paths'])
        paths.extend(manifest['workspace_paths'])
        paths.extend(f'reports/{report}' for report in manifest['report_ids'])
        paths.extend(f'autoresearch/runtime/{sid}' for sid in ids)
        # Historical sessions may use a workspace identity distinct from session_id.
        for row in rows:
            if row.workspace_path:
                owner = Path(row.workspace_path).name.removeprefix('session_')
                paths.extend([f'autoresearch/autoresearch_sessions/model_artifacts/{owner}',
                              f'autoresearch/pathlab_datasets/session_inputs/{owner}'])
        await enqueue(db, task.user_id, paths=paths, task_ids=runs)
        source_ids = select(ResultSource.source_id).where(
            (ResultSource.session_id.in_(ids)) | (ResultSource.task_id.in_(runs))
        )
        await db.execute(
            delete(ResultSourceDataset).where(
                ResultSourceDataset.source_id.in_(source_ids)
            )
        )
        await db.execute(
            delete(ResultSource).where(
                (ResultSource.session_id.in_(ids)) | (ResultSource.task_id.in_(runs))
            )
        )
        await db.execute(
            delete(ManuscriptGeneration).where(
                ManuscriptGeneration.report_id.in_(manifest["report_ids"])
            )
        )
        await db.execute(
            delete(Manuscript).where(Manuscript.report_id.in_(manifest["report_ids"]))
        )
        for cls in [
            AIResult,
            AnalysisRun,
            TrainingLog,
            TrainedModel,
            TrainingTaskWSI,
            TrainingTask,
        ]:
            await db.execute(delete(cls).where(cls.task_id.in_(runs)))
        await db.execute(
            delete(WorkbenchFile).where(
                (WorkbenchFile.conversation_id == cid)
                | WorkbenchFile.session_id.in_(ids)
            )
        )
        for cls in [
            ResearchJob,
            AutoResearchEvent,
            AutoResearchExperiment,
            AutoResearchSession,
        ]:
            await db.execute(delete(cls).where(cls.session_id.in_(ids)))
        from backend.database.repositories import ChatRepository

        await ChatRepository.delete_conversation(db, cid)
        task = await db.scalar(
            select(StorageTask).where(StorageTask.task_id == task_id)
        )
        task.status, task.progress, task.completed_at = "completed", 100, utc_now()
        task.processed_items = task.success_count = len(ids)
        task.params = {"conversation_id": cid, "session_ids": ids}
        await db.commit()


class ChatDeletionQueue:
    def __init__(self, scheduler, writing):
        self.scheduler, self.writing = scheduler, writing
        self.tasks: dict[str, asyncio.Task] = {}

    async def run(self, task_id: str):
        from backend.autoresearch.engine.runtime import AgentRuntime
        from backend.autoresearch.engine.worker import stop_jobs

        try:
            async with safe_session() as db:
                task = await db.scalar(
                    select(StorageTask).where(StorageTask.task_id == task_id)
                )
                ids = task.params["session_ids"]
                task.status, task.started_at, task.error_message = (
                    "processing",
                    utc_now(),
                    None,
                )
                task.processed_items = 0
                await db.commit()
            for sid in ids:
                agent = self.scheduler.tasks.pop(sid, None)
                if agent:
                    agent.cancel()
                    await asyncio.gather(agent, return_exceptions=True)
                await AgentRuntime(sid).cleanup_orphan()
                from backend.common.task_dispatch import publish_task_cancellation
                from backend.autoresearch.engine import store

                # Republish on every cleanup attempt, including jobs whose first
                # cancellation transaction succeeded before Redis delivery failed.
                for job in await store.jobs(sid):
                    await asyncio.wait_for(
                        publish_task_cancellation(job["job_id"]), timeout=3
                    )
                await stop_jobs(sid)
                async with safe_session() as db:
                    task = await db.scalar(
                        select(StorageTask).where(StorageTask.task_id == task_id)
                    )
                    task.processed_items += 1
                    task.progress = min(
                        70, int(70 * task.processed_items / max(1, len(ids)))
                    )
                    await db.commit()
            async with safe_session() as db:
                run_ids = (
                    await db.scalars(
                        select(ResearchJob.job_id).where(
                            ResearchJob.session_id.in_(ids)
                        )
                    )
                ).all()
                report_ids = (
                    await db.scalars(
                        select(Manuscript.report_id).where(
                            (
                                (Manuscript.source_type == "research")
                                & Manuscript.source_id.in_(ids)
                            )
                            | (
                                (Manuscript.source_type == "experiment")
                                & Manuscript.source_id.in_(run_ids)
                            )
                        )
                    )
                ).all()
                await db.execute(
                    update(ManuscriptGeneration)
                    .where(ManuscriptGeneration.report_id.in_(report_ids))
                    .values(status="paused")
                )
                await db.commit()
            for report_id in report_ids:
                writer = self.writing.tasks.pop(report_id, None)
                if writer:
                    writer.cancel()
                    await asyncio.gather(writer, return_exceptions=True)
            await cleanup_records_and_files(task_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Conversation cleanup %s failed; retrying in 30 seconds", task_id)
            async with safe_session() as db:
                task = await db.scalar(
                    select(StorageTask).where(StorageTask.task_id == task_id)
                )
                task.status, task.error_message = "failed", str(exc)[:1000]
                task.params = {**task.params, "retry_after": time.time() + 30}
                await db.commit()

    async def tick(self):
        self.tasks = {key: task for key, task in self.tasks.items() if not task.done()}
        async with safe_session() as db:
            rows = (
                await db.scalars(
                    select(StorageTask)
                    .where(
                        StorageTask.task_type == "chat_delete",
                        StorageTask.status.in_(["pending", "processing", "failed"]),
                    )
                    .order_by(StorageTask.created_at)
                    .limit(50)
                )
            ).all()
        for row in rows:
            if len(self.tasks) >= 2:
                break
            if (
                row.task_id not in self.tasks
                and (row.params or {}).get("retry_after", 0) <= time.time()
            ):
                self.tasks[row.task_id] = asyncio.create_task(self.run(row.task_id))

    async def shutdown(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
