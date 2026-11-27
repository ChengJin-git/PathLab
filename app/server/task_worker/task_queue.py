"""Worker-owned task lifecycle and one shared GPU lease queue.

CPU preparation and stages waiting for memory do not consume a GPU concurrency
slot. Whole jobs and pipeline stages use the same estimator, fairness and leases.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import import_module
from typing import Any


from backend.common.config import Config
from backend.common.gpu_resources import GpuWorkload, estimate_gpu, task_workload
from backend.common.task_types import TaskType
from backend.common.queue_lifecycle import interrupt_for_restart
from task_worker.gpu_scheduler import GpuScheduler

logger = logging.getLogger("task_queue")
TaskStatus = import_module("backend.ai.schemas.base").TaskStatus
User = import_module("backend.auth.models").User
async_session = import_module("backend.database").async_session
AITaskRepository = import_module("backend.database.repositories").AITaskRepository
TrainingTaskRepository = import_module(
    "backend.database.repositories"
).TrainingTaskRepository


@dataclass
class QueuedTask:
    task_id: str
    task_type: TaskType
    coro_func: Callable[..., Awaitable[Any]]
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resources: GpuWorkload | None = None
    staged: bool = False


class TaskQueueManager:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self, max_concurrent=1, min_vram_mb=None, vram_check_interval=5.0, gpu_count=1
    ):
        if type(self)._initialized:
            return
        self.max_concurrent = max_concurrent
        self.min_vram_mb = min_vram_mb or Config.DEFAULT_MIN_VRAM_MB
        self.gpu_count = gpu_count
        self._tasks: dict[str, asyncio.Task] = {}
        self._records: dict[str, QueuedTask] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._pending_tasks: dict[str, QueuedTask] = {}
        self._patching_tasks: dict[str, asyncio.Task] = {}
        self._gpu_assignments: dict[str, int] = {}
        self._shutdown = False
        self._started = False
        self._gpu = GpuScheduler(
            lambda: import_module("backend.common.gpu_utils").get_all_gpu_info(),
            lambda: import_module("backend.common.gpu_utils").get_gpu_process_memory(),
            limit=max_concurrent,
            interval=vram_check_interval,
            cuda_check=lambda: import_module("backend.common.gpu_utils").cuda_initializes(),
        )
        type(self)._initialized = True

    @property
    def _bad_gpus(self):
        return self._gpu.bad_gpus

    @property
    def _gpu_stage_details(self):
        return self._gpu.details()

    @property
    def gpu_capacity(self):
        return self._gpu.capacity()

    async def start(self):
        self._shutdown = False
        self._started = True
        self._gpu.start()

    async def stop(self):
        self._shutdown = True
        owned = set(self._tasks.values()) | set(self._patching_tasks.values())
        await interrupt_for_restart(owned)
        await self._gpu.stop()
        self._tasks.clear()
        self._records.clear()
        self._running_tasks.clear()
        self._pending_tasks.clear()
        self._patching_tasks.clear()
        self._gpu_assignments.clear()
        self._started = False

    async def submit(
        self,
        task_id,
        task_type,
        coro_func,
        *args,
        staged=False,
        resources=None,
        **kwargs,
    ):
        if task_id in self._tasks:
            return
        workload = (
            None
            if staged
            else (
                GpuWorkload.model_validate(resources)
                if resources
                else task_workload(task_type.value, kwargs)
            )
        )
        record = QueuedTask(
            task_id,
            task_type,
            coro_func,
            args,
            {"task_id": task_id, **kwargs},
            resources=workload,
            staged=staged,
        )
        self._records[task_id] = record
        self._pending_tasks[task_id] = record
        self._tasks[task_id] = asyncio.create_task(self._run_task(record))

    async def _run_task(self, record: QueuedTask):
        try:
            kwargs = dict(record.kwargs)
            if not record.staged:
                estimate = estimate_gpu(record.resources, self.min_vram_mb)
                kwargs["assigned_device"] = await self.acquire_gpu_stage(
                    record.task_id, "job", estimate.required_mb
                )
                # Inference coroutines execute in this worker. Research jobs bind
                # their child process group after spawning the isolated sandbox.
                if record.task_type != TaskType.RESEARCH:
                    import os

                    self.bind_gpu_process(record.task_id, os.getpid())
            await record.coro_func(*record.args, **kwargs)
            self._gpu.release_task(record.task_id)
            self._running_tasks.pop(record.task_id, None)
            self._gpu_assignments.pop(record.task_id, None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Task %s failed", record.task_id)
            await self._ensure_task_failed(record.task_id, record.task_type, str(exc))
        finally:
            self._gpu.release_task(record.task_id)
            self._running_tasks.pop(record.task_id, None)
            self._pending_tasks.pop(record.task_id, None)
            self._gpu_assignments.pop(record.task_id, None)
            self._tasks.pop(record.task_id, None)
            self._records.pop(record.task_id, None)
            await self._invalidate_context_for_task(record)

    async def acquire_gpu_stage(
        self, task_id: str, stage: str, required_vram_mb: float
    ) -> str:
        device = await self._gpu.acquire(task_id, stage, required_vram_mb)
        self._pending_tasks.pop(task_id, None)
        if task_id in self._tasks:
            self._running_tasks[task_id] = self._tasks[task_id]
        self._gpu_assignments[task_id] = 0 if device == 'mps' else int(device.split(":")[1])
        return device

    def bind_gpu_process(self, task_id: str, pid: int, *, process_group=False):
        self._gpu.bind_process(task_id, pid, process_group=process_group)

    def release_gpu_stage(self, task_id: str, stage: str):
        self._gpu.release(task_id, stage)
        self._running_tasks.pop(task_id, None)
        self._gpu_assignments.pop(task_id, None)
        if task_id in self._records:
            self._pending_tasks[task_id] = self._records[task_id]

    def mark_gpu_bad(self, gpu_index: int):
        self._gpu.bad_gpus.add(gpu_index)
        self._gpu.changed.set()

    def pause_for_cuda_outage(self):
        self._gpu.pause_for_cuda_outage()

    @property
    def cuda_outage(self) -> bool:
        return self._gpu.cuda_outage_since is not None

    def avoid_gpu(self, task_id: str, gpu_index: int):
        self._gpu.avoid.setdefault(task_id, set()).add(gpu_index)

    def get_bad_gpus(self):
        return frozenset(self._gpu.bad_gpus)

    async def set_max_concurrent(self, max_concurrent: int):
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self.max_concurrent = self._gpu.limit = max_concurrent
        self._gpu.changed.set()

    def register_patching_task(self, task_id: str, task: asyncio.Task):
        self._patching_tasks[task_id] = task

    def deregister_patching_task(self, task_id: str):
        self._patching_tasks.pop(task_id, None)

    def is_task_in_queue(self, task_id: str):
        return task_id in self._tasks or task_id in self._patching_tasks

    async def cancel_pending_task(self, task_id: str):
        if task_id not in self._pending_tasks:
            return False
        return await self.cancel_task(task_id)

    async def cancel_task(self, task_id: str):
        task = self._tasks.get(task_id) or self._patching_tasks.get(task_id)
        if task is None:
            return False
        if not task.cancelling():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        # Cancellation before the first coroutine step still needs cleanup.
        self._gpu.release_task(task_id)
        self._tasks.pop(task_id, None)
        self._records.pop(task_id, None)
        self._pending_tasks.pop(task_id, None)
        self._running_tasks.pop(task_id, None)
        self._patching_tasks.pop(task_id, None)
        self._gpu_assignments.pop(task_id, None)
        return True

    async def join(self):
        await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    def get_status(self):
        from backend.common.task_runtime import build_runtime_status_snapshot

        return build_runtime_status_snapshot(
            self, is_running=self._started and not self._shutdown
        )

    async def _invalidate_context_for_task(self, record):
        if record.task_type not in {TaskType.TRAINING, TaskType.INFERENCE}:
            return
        try:
            user_id = record.kwargs.get("user_id")
            if not user_id:
                repo = (
                    TrainingTaskRepository
                    if record.task_type == TaskType.TRAINING
                    else AITaskRepository
                )
                async with async_session() as db:
                    task = await repo.get_by_id(db, record.task_id)
                    user_id = str(task.user_id) if task else None
            if user_id:
                cache = import_module("backend.common.chat_context_cache")
                await cache.invalidate_chat_context(user_id)
                await cache.clear_training_snapshot(record.task_id)
        except Exception:
            logger.exception("Context invalidation failed for %s", record.task_id)

    async def _ensure_task_failed(self, task_id, task_type, error_msg):
        try:
            if task_type == TaskType.RESEARCH:
                from backend.autoresearch.engine import store
                from backend.database.models import ResearchJob

                async with async_session() as db:
                    job = await db.get(ResearchJob, task_id)
                if job is not None and job.status in {"queued", "running"}:
                    await store.job_update(task_id, "failed", {"error": error_msg})
                    if job.kind == "experiment":
                        await store.experiment_update(
                            job.session_id,
                            task_id,
                            status="failed",
                            metrics={"error": error_msg},
                        )
                return
            repo = (
                AITaskRepository
                if task_type == TaskType.INFERENCE
                else TrainingTaskRepository
            )
            async with async_session() as db:
                task = await repo.get_by_id(db, task_id)
                if task and task.status not in {"completed", "failed", "cancelled"}:
                    await repo.update_status(
                        db, task_id, TaskStatus.FAILED, error_message=error_msg
                    )
                    await db.commit()
        except Exception:
            logger.exception("Could not persist failure for %s", task_id)


def get_task_queue() -> TaskQueueManager:
    return TaskQueueManager()


async def init_task_queue(
    max_concurrent=1, min_vram_mb=None, vram_check_interval=5.0, gpu_count=1
):
    queue = TaskQueueManager(
        max_concurrent, min_vram_mb, vram_check_interval, gpu_count
    )
    await queue.start()
    return queue


async def shutdown_task_queue():
    await get_task_queue().stop()
