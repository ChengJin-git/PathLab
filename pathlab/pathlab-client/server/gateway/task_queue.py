"""
GPU Task Queue Manager

Centralized task queue management to control GPU task concurrency and prevent GPU overload.
Supports:
- Maximum concurrency control (default: 1 GPU task at a time)
- FIFO task scheduling
- Task recovery after power outage/restart
- Unified management for both TrainingTask and AITask (inference)
- VRAM pre-check before task execution (prevents OOM from queued tasks)
"""

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from importlib import import_module
from typing import Dict, Callable, Awaitable, Any, Optional, List, Tuple, cast
from enum import Enum
from datetime import datetime

_SOFT_RESERVATION_TTL_SEC: float = 600.0
_DEFAULT_MODEL_VRAM_MB: float = 1000.0
_BATCH_BUFFER_MB: float = 768.0
from sqlalchemy import select

from .email_notifications import send_templated_email

TaskStatus = import_module("backend.ai.schemas.base").TaskStatus
User = import_module("backend.auth.models").User
Config = import_module("backend.common.config").Config
async_session = import_module("backend.database").async_session
AITaskRepository = import_module("backend.database.repositories").AITaskRepository
TrainingTaskRepository = import_module(
    "backend.database.repositories"
).TrainingTaskRepository


def _get_gpu_utils_module():
    return import_module("backend.common.gpu_utils")


def _get_context_cache_module():
    return import_module("gateway.chat.context_cache")


logger = logging.getLogger("task_queue")


class TaskType(str, Enum):
    """Task types managed by the queue"""

    TRAINING = "training"
    INFERENCE = "inference"
    EXTERNAL_VALIDATION = "external_validation"
    ANALYSIS = "analysis"
    BATCH_INFERENCE = "batch_inference"


@dataclass
class QueuedTask:
    """Represents a task in the queue"""

    task_id: str
    task_type: TaskType
    coro_func: Callable[..., Awaitable[Any]]
    args: tuple[Any, ...] = field(default_factory=tuple[Any, ...])
    kwargs: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    assigned_gpu: Optional[int] = None  # GPU index assigned to this task

    def __hash__(self):
        return hash(self.task_id)


class TaskQueueManager:
    """
    Singleton manager for GPU task queue.

    Controls the number of concurrent GPU tasks to prevent GPU memory exhaustion.
    Tasks are executed in FIFO order.

    Features:
    - Concurrency control (default: 1 GPU task at a time)
    - Multi-GPU support with intelligent GPU assignment
    - VRAM pre-check before task execution
    - Automatic waiting for GPU memory to be released
    """

    _instance: Optional["TaskQueueManager"] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        max_concurrent: int = 1,
        min_vram_mb: float | None = None,
        vram_check_interval: float = 5.0,
        gpu_count: int = 1,
    ):
        """
        Initialize the TaskQueueManager.

        Args:
            max_concurrent: Maximum number of concurrent GPU tasks (default: 1)
            min_vram_mb: Minimum free VRAM required to start a task (default: 2000 MB)
            vram_check_interval: Interval in seconds between VRAM checks (default: 5.0)
            gpu_count: Number of available GPUs (default: 1)
        """
        # Prevent re-initialization
        if TaskQueueManager._initialized:
            return

        self.max_concurrent = max_concurrent
        self.min_vram_mb = (
            min_vram_mb if min_vram_mb is not None else Config.DEFAULT_MIN_VRAM_MB
        )
        self.vram_check_interval = vram_check_interval
        self.gpu_count = gpu_count
        self._queue: asyncio.Queue[QueuedTask] = asyncio.Queue()
        self._running_tasks: Dict[str, asyncio.Task[Any]] = {}
        self._pending_tasks: Dict[str, QueuedTask] = {}  # task_id -> QueuedTask
        self._gpu_assignments: Dict[
            str, int
        ] = {}  # task_id -> GPU index for running tasks
        self._bad_gpus: set[int] = (
            set()
        )  # GPU indices confirmed to have hardware failures
        self._patching_tasks: Dict[
            str, asyncio.Task[Any]
        ] = {}  # pre-queue patching tasks
        self._soft_vram_reservations: Dict[str, Tuple[int, float, float | None]] = {}
        self._gpu_stage_details: Dict[str, Dict[str, Any]] = {}
        self._condition: Optional[asyncio.Condition] = (
            None  # For dynamic concurrency control
        )
        self._vram_condition: Optional[asyncio.Condition] = (
            None  # For VRAM availability notification
        )
        self._worker_task: Optional[asyncio.Task[Any]] = None
        self._shutdown: bool = False

        TaskQueueManager._initialized = True
        logger.info(
            f"TaskQueueManager initialized with max_concurrent={max_concurrent}, "
            f"min_vram_mb={min_vram_mb}, vram_check_interval={vram_check_interval}s, "
            f"gpu_count={gpu_count}"
        )

    async def start(self):
        """Start the queue worker"""
        if self._worker_task is not None:
            return

        self._condition = asyncio.Condition()
        self._vram_condition = asyncio.Condition()
        self._shutdown = False
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("TaskQueueManager worker started")

    async def stop(self):
        """Stop the queue worker gracefully"""
        self._shutdown = True
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        logger.info("TaskQueueManager worker stopped")

    async def submit(
        self,
        task_id: str,
        task_type: TaskType,
        coro_func: Callable[..., Awaitable[Any]],
        *args,
        **kwargs,
    ) -> None:
        """
        Submit a task to the queue.

        Args:
            task_id: Unique task identifier
            task_type: Type of task (training or inference)
            coro_func: Async function to execute
            *args, **kwargs: Arguments to pass to the function
        """
        # Ensure task_id is passed to coro_func via kwargs
        # (coro_func typically expects task_id as its first argument)
        kwargs_with_task_id = {"task_id": task_id, **kwargs}

        queued_task = QueuedTask(
            task_id=task_id,
            task_type=task_type,
            coro_func=coro_func,
            args=args,
            kwargs=kwargs_with_task_id,
        )

        self._pending_tasks[task_id] = queued_task
        await self._queue.put(queued_task)

        logger.info(
            f"Task {task_id} ({task_type.value}) submitted to queue. "
            f"Queue size: {self._queue.qsize()}, Running: {len(self._running_tasks)}"
        )

    def mark_gpu_bad(self, gpu_index: int) -> None:
        """Mark a GPU as unhealthy so it is excluded from future task scheduling."""
        if gpu_index not in self._bad_gpus:
            self._bad_gpus.add(gpu_index)
            logger.warning(
                f"GPU {gpu_index} marked as unhealthy and excluded from task scheduling. "
                f"Total bad GPUs: {sorted(self._bad_gpus)}"
            )

    def get_bad_gpus(self) -> frozenset[int]:
        """Return a snapshot of GPU indices currently marked as unhealthy."""
        return frozenset(self._bad_gpus)

    def register_patching_task(self, task_id: str, task: asyncio.Task[Any]) -> None:
        self._patching_tasks[task_id] = task
        logger.info(
            f"Pre-queue patching task {task_id} registered. "
            f"Active patching tasks: {len(self._patching_tasks)}"
        )

    def deregister_patching_task(self, task_id: str) -> None:
        removed = self._patching_tasks.pop(task_id, None)
        if removed is not None:
            logger.debug(f"Pre-queue patching task {task_id} deregistered")

    def _reserve_soft_vram(
        self, task_id: str, cuda_idx: int, mb: float, ttl_sec: float | None = None
    ) -> None:
        self._soft_vram_reservations[task_id] = (
            cuda_idx,
            mb,
            time.monotonic() + ttl_sec if ttl_sec is not None else None,
        )

    def _release_soft_vram(self, task_id: str) -> None:
        self._soft_vram_reservations.pop(task_id, None)

    def _get_soft_reserved_mb(self, cuda_idx: int) -> float:
        now = time.monotonic()
        expired = [
            tid
            for tid, (idx, mb, exp) in self._soft_vram_reservations.items()
            if exp is not None and exp <= now
        ]
        for tid in expired:
            del self._soft_vram_reservations[tid]
        return sum(
            mb
            for idx, mb, exp in self._soft_vram_reservations.values()
            if idx == cuda_idx
        )

    def _estimate_task_vram_mb(self, task_id: str) -> float:
        queued_task = self._pending_tasks.get(task_id)
        if queued_task is None:
            return float(self.min_vram_mb)

        kwargs = queued_task.kwargs
        preprocessing_config = kwargs.get("preprocessing_config")
        if not isinstance(preprocessing_config, dict):
            preprocessing_config = {}
        model_config = kwargs.get("model_config")
        if not isinstance(model_config, dict):
            model_config = {}

        model_name = self._task_model_name(kwargs, preprocessing_config, model_config)
        if not model_name:
            return float(self.min_vram_mb)

        model_size_mb = self._model_vram_estimate_mb(model_name)
        batch_size = self._task_batch_size(kwargs, preprocessing_config, model_config)
        required_mb = (
            model_size_mb
            + float(Config.MIN_INFERENCE_OVERHEAD_MB)
            + batch_size * _BATCH_BUFFER_MB
        )
        return max(float(self.min_vram_mb), required_mb)

    def _task_model_name(
        self,
        kwargs: Dict[str, Any],
        preprocessing_config: Dict[str, Any],
        model_config: Dict[str, Any],
    ) -> str | None:
        candidates = (
            preprocessing_config.get("feature_extractor"),
            model_config.get("feature_extractor"),
            model_config.get("backbone"),
            model_config.get("architecture"),
            kwargs.get("feature_extractor"),
            kwargs.get("backbone"),
        )
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None

    def _task_batch_size(
        self,
        kwargs: Dict[str, Any],
        preprocessing_config: Dict[str, Any],
        model_config: Dict[str, Any],
    ) -> int:
        default_batch_size = 64
        candidates = (
            preprocessing_config.get("feature_batch_size"),
            preprocessing_config.get("batch_size"),
            model_config.get("batch_size"),
            kwargs.get("batch_size"),
        )
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                value = int(candidate)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        return default_batch_size

    def _model_vram_estimate_mb(self, model_name: str) -> float:
        try:
            estimates = import_module(
                "backend.ai.utils.vram_guard"
            ).MODEL_SIZE_ESTIMATES_MB
        except Exception:
            estimates = {}
        normalized_model = model_name.strip().lower()
        for estimate_name, estimate_mb in estimates.items():
            if str(estimate_name).strip().lower() == normalized_model:
                return float(estimate_mb)
        return _DEFAULT_MODEL_VRAM_MB

    def _select_optimal_gpu(
        self, required_vram_mb: float | None = None
    ) -> Tuple[int, float]:
        """
        Select the GPU with the most effective free VRAM that meets the minimum requirement.

        Effective free VRAM = pynvml free VRAM minus any active soft reservations.
        Multiple tasks may share a GPU when the remaining effective free VRAM is above
        the next task's estimated startup VRAM budget.
        """
        required_mb = (
            float(required_vram_mb)
            if required_vram_mb is not None and math.isfinite(required_vram_mb)
            else float(self.min_vram_mb)
        )
        try:
            gpu_utils = _get_gpu_utils_module()
            get_all_gpu_info = gpu_utils.get_all_gpu_info
        except ImportError:
            logger.warning("Could not import gpu_utils, defaulting to GPU 0")
            return (0, 0.0)

        gpu_info_list = get_all_gpu_info()
        if not gpu_info_list:
            return (-1, 0.0)

        best_gpu = -1
        best_free_mb = 0.0
        for info in gpu_info_list:
            gpu_idx = info["index"]
            if gpu_idx in self._bad_gpus:
                continue
            soft_reserved = self._get_soft_reserved_mb(gpu_idx)
            effective_free = max(0.0, info["free_mb"] - soft_reserved)
            if effective_free >= required_mb and effective_free > best_free_mb:
                best_free_mb = effective_free
                best_gpu = gpu_idx

        if best_gpu >= 0:
            logger.debug(
                f"Selected GPU {best_gpu} with {best_free_mb:.0f} MB effective free VRAM "
                f"(bad GPUs: {sorted(self._bad_gpus)})"
            )
        else:
            logger.warning(
                f"_select_optimal_gpu: no suitable GPU found. "
                f"Checked {len(gpu_info_list)} GPU(s), required {required_mb:.0f} MB effective free. "
                f"Bad GPUs: {sorted(self._bad_gpus)}"
            )
        return (best_gpu, best_free_mb)

    async def _wait_for_gpu_vram(self, task_id: str, gpu_index: int) -> bool:
        """
        Wait until sufficient VRAM is available on a specific GPU.

        Args:
            task_id: Task ID for logging and cancellation check
            gpu_index: GPU index to check

        Returns:
            True if VRAM is available, False if task was cancelled during wait
        """
        try:
            gpu_utils = _get_gpu_utils_module()
            check_gpu_vram_available = gpu_utils.check_gpu_vram_available
            get_total_vram_mb = gpu_utils.get_total_vram_mb
        except ImportError:
            logger.warning("Could not import gpu_utils, skipping VRAM check")
            return True

        # Check if GPU total VRAM is less than threshold (small GPU scenario)
        total_vram = get_total_vram_mb()
        if total_vram > 0 and total_vram < self.min_vram_mb:
            logger.warning(
                f"GPU total VRAM ({total_vram:.0f} MB) is less than min_vram_mb ({self.min_vram_mb:.0f} MB). "
                f"Proceeding anyway, but OOM errors may occur."
            )
            return True

        wait_count = 0
        while not self._shutdown:
            if task_id not in self._pending_tasks:
                logger.info(f"Task {task_id} was cancelled while waiting for VRAM")
                return False

            is_available, current_free_mb, message = check_gpu_vram_available(
                gpu_index, self.min_vram_mb
            )

            if is_available:
                if wait_count > 0:
                    logger.info(
                        f"VRAM now available on GPU {gpu_index} for task {task_id} after {wait_count} waits. "
                        f"Free: {current_free_mb:.0f} MB"
                    )
                return True

            wait_count += 1
            if wait_count == 1:
                logger.info(
                    f"Task {task_id} waiting for VRAM on GPU {gpu_index}. {message}. "
                    f"Waiting for task completion notification..."
                )

            vram_condition = self._vram_condition
            if vram_condition is None:
                raise RuntimeError("VRAM wait condition is not initialized")
            async with vram_condition:
                try:
                    await asyncio.wait_for(
                        vram_condition.wait(), timeout=self.vram_check_interval
                    )
                except asyncio.TimeoutError:
                    pass

            if wait_count % 12 == 0:
                logger.info(
                    f"Task {task_id} still waiting for VRAM on GPU {gpu_index} "
                    f"({wait_count * self.vram_check_interval:.0f}s elapsed). {message}"
                )

        return False

    async def _wait_for_any_gpu(self, task_id: str) -> int:
        """
        Wait until any GPU has sufficient VRAM available.

        Tries to find a GPU with enough VRAM. If none available, waits for
        VRAM to be released.

        Args:
            task_id: Task ID for logging and cancellation check

        Returns:
            GPU index with available VRAM, or -1 if task was cancelled/shutdown
        """
        wait_count = 0
        while not self._shutdown:
            if task_id not in self._pending_tasks:
                logger.info(f"Task {task_id} was cancelled while waiting for GPU")
                return -1

            required_vram_mb = self._estimate_task_vram_mb(task_id)
            gpu_idx, effective_free = self._select_optimal_gpu(required_vram_mb)
            if gpu_idx >= 0:
                self._reserve_soft_vram(task_id, gpu_idx, required_vram_mb)
                if wait_count > 0:
                    logger.info(
                        f"GPU {gpu_idx} now available for task {task_id} after {wait_count} waits"
                    )
                return gpu_idx

            wait_count += 1
            if wait_count == 1:
                logger.info(
                    f"Task {task_id} waiting for any GPU with sufficient VRAM. "
                    f"Required: {required_vram_mb:.0f} MB"
                )

            vram_condition = self._vram_condition
            if vram_condition is None:
                raise RuntimeError("VRAM wait condition is not initialized")
            async with vram_condition:
                try:
                    await asyncio.wait_for(
                        vram_condition.wait(), timeout=self.vram_check_interval
                    )
                except asyncio.TimeoutError:
                    pass

            if wait_count % 12 == 0:
                logger.info(
                    f"Task {task_id} still waiting for GPU "
                    f"({wait_count * self.vram_check_interval:.0f}s elapsed)"
                )

        return -1

    async def acquire_gpu_stage(
        self,
        task_id: str,
        stage: str,
        required_vram_mb: float | None = None,
    ) -> str:
        """Select any GPU for a pipeline stage and reserve its startup VRAM budget."""
        wait_count = 0
        stage_key = f"{task_id}:{stage}"
        required_mb = (
            float(required_vram_mb)
            if required_vram_mb is not None and math.isfinite(required_vram_mb)
            else float(self.min_vram_mb)
        )

        # Stage-level scheduling supersedes the task startup reservation once the
        # pipeline starts waiting on concrete GPU work.
        self._release_soft_vram(task_id)

        try:
            while not self._shutdown:
                self._gpu_stage_details[stage_key] = {
                    "task_id": task_id,
                    "stage": stage,
                    "state": "waiting",
                    "gpu": None,
                    "device": None,
                    "required_vram_mb": required_mb,
                }
                gpu_idx, effective_free = self._select_optimal_gpu(required_mb)
                if gpu_idx >= 0:
                    self._reserve_soft_vram(stage_key, gpu_idx, required_mb)
                    self._gpu_stage_details[stage_key] = {
                        "task_id": task_id,
                        "stage": stage,
                        "state": "running",
                        "gpu": gpu_idx,
                        "device": f"cuda:{gpu_idx}",
                        "required_vram_mb": required_mb,
                        "effective_free_mb": effective_free,
                    }
                    if wait_count > 0:
                        logger.info(
                            f"GPU {gpu_idx} now available for task {task_id} stage {stage} "
                            f"after {wait_count} waits"
                        )
                    return f"cuda:{gpu_idx}"

                wait_count += 1
                if wait_count == 1:
                    logger.info(
                        f"Task {task_id} stage {stage} waiting for any GPU with sufficient VRAM. "
                        f"Required: {required_mb:.0f} MB"
                    )

                vram_condition = self._vram_condition
                if vram_condition is None:
                    raise RuntimeError("VRAM wait condition is not initialized")
                async with vram_condition:
                    try:
                        await asyncio.wait_for(
                            vram_condition.wait(), timeout=self.vram_check_interval
                        )
                    except asyncio.TimeoutError:
                        pass

                if wait_count % 12 == 0:
                    logger.info(
                        f"Task {task_id} stage {stage} still waiting for GPU "
                        f"({wait_count * self.vram_check_interval:.0f}s elapsed)"
                    )
        except asyncio.CancelledError:
            self._release_soft_vram(stage_key)
            self._gpu_stage_details.pop(stage_key, None)
            raise

        self._release_soft_vram(stage_key)
        self._gpu_stage_details.pop(stage_key, None)
        raise asyncio.CancelledError(
            f"Task queue stopped while waiting for task {task_id} stage {stage}"
        )

    def release_gpu_stage(self, task_id: str, stage: str) -> None:
        """Release the soft VRAM reservation for a completed pipeline stage."""
        stage_key = f"{task_id}:{stage}"
        self._release_soft_vram(stage_key)
        self._gpu_stage_details.pop(stage_key, None)

    async def _notify_vram_released(self):
        """
        Notify waiting tasks that GPU memory may have been released.

        Called after a task completes to wake up tasks waiting for VRAM.
        """
        if self._vram_condition:
            async with self._vram_condition:
                self._vram_condition.notify_all()

    async def _notify_concurrency_changed(self):
        """Notify tasks waiting on concurrency limits or queue-head cancellation."""
        if self._condition:
            async with self._condition:
                self._condition.notify_all()

    async def _notify_queue_state_changed(self):
        """Wake queue waiters after task completion, cancellation, or config changes."""
        await self._notify_concurrency_changed()
        await self._notify_vram_released()

    async def _worker_loop(self):
        """Main worker loop that processes tasks from the queue"""
        logger.info("Worker loop started")

        while not self._shutdown:
            try:
                # Get task from queue (blocks until available)
                queued_task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # Check if task was cancelled while in queue
            # (cancel_task removes from _pending_tasks but can't remove from asyncio.Queue)
            if queued_task.task_id not in self._pending_tasks:
                logger.info(f"Task {queued_task.task_id} was cancelled, skipping")
                self._queue.task_done()
                continue

            # Wait for concurrency slot (dynamic control via Condition)
            condition = self._condition
            if condition is None:
                raise RuntimeError("Concurrency condition is not initialized")
            async with condition:
                while len(self._running_tasks) >= self.max_concurrent:
                    await condition.wait()

            # GPU assignment: Wait for a GPU with sufficient VRAM
            # This selects the GPU with most free VRAM that meets minimum requirement
            assigned_gpu = await self._wait_for_any_gpu(queued_task.task_id)
            if assigned_gpu < 0:
                # Task was cancelled or shutdown requested
                self._queue.task_done()
                continue

            # Double-check task wasn't cancelled during GPU wait
            if queued_task.task_id not in self._pending_tasks:
                logger.info(
                    f"Task {queued_task.task_id} was cancelled during GPU wait, skipping"
                )
                self._release_soft_vram(queued_task.task_id)
                self._queue.task_done()
                continue

            # Assign GPU to task
            queued_task.assigned_gpu = assigned_gpu
            queued_task.kwargs["assigned_device"] = f"cuda:{assigned_gpu}"

            # Remove from pending, add to running
            self._pending_tasks.pop(queued_task.task_id, None)
            self._gpu_assignments[queued_task.task_id] = assigned_gpu

            # Create task and track it
            task = asyncio.create_task(self._run_task(queued_task))
            self._running_tasks[queued_task.task_id] = task

            logger.info(
                f"Task {queued_task.task_id} started on GPU {assigned_gpu}. "
                f"Running: {len(self._running_tasks)}/{self.max_concurrent}"
            )

    async def _run_task(self, queued_task: QueuedTask):
        try:
            await queued_task.coro_func(*queued_task.args, **queued_task.kwargs)
            logger.info(
                f"Task {queued_task.task_id} completed successfully on GPU {queued_task.assigned_gpu}"
            )
            asyncio.create_task(
                self._notify_task_status_change(queued_task, "completed")
            )
        except asyncio.CancelledError:
            logger.info(f"Task {queued_task.task_id} was cancelled")
            asyncio.create_task(
                self._notify_task_status_change(queued_task, "cancelled")
            )
            raise
        except Exception as e:
            logger.error(
                f"Task {queued_task.task_id} failed on GPU {queued_task.assigned_gpu}: {e}"
            )
            if queued_task.assigned_gpu is not None and "CUDA error" in str(e):
                self.mark_gpu_bad(queued_task.assigned_gpu)
            await self._ensure_task_failed(
                queued_task.task_id, queued_task.task_type, str(e)
            )
            asyncio.create_task(self._notify_task_status_change(queued_task, "failed"))
        finally:
            self._release_soft_vram(queued_task.task_id)
            await self._invalidate_context_for_task(queued_task)
            self._running_tasks.pop(queued_task.task_id, None)
            self._gpu_assignments.pop(queued_task.task_id, None)
            await self._notify_queue_state_changed()
            self._queue.task_done()

    _STATUS_SUBJECT = {
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }
    _STATUS_DESC = {
        "completed": "completed successfully",
        "failed": "failed",
        "cancelled": "been cancelled",
    }
    _STATUS_PREF = {
        "completed": "notify_on_success",
        "failed": "notify_on_failed",
        "cancelled": "notify_on_cancelled",
    }

    async def _notify_task_status_change(
        self, queued_task: QueuedTask, status: str
    ) -> None:
        if queued_task.task_type not in (
            TaskType.TRAINING,
            TaskType.INFERENCE,
            TaskType.EXTERNAL_VALIDATION,
        ):
            return

        user_id: str | None = queued_task.kwargs.get("user_id")
        task_name: str = queued_task.task_id
        try:
            async with async_session() as db:
                if queued_task.task_type in (
                    TaskType.TRAINING,
                    TaskType.EXTERNAL_VALIDATION,
                ):
                    task = await TrainingTaskRepository.get_by_id(
                        db, queued_task.task_id
                    )
                else:
                    task = await AITaskRepository.get_by_id(db, queued_task.task_id)

                if not task:
                    return

                task_status = str(task.status)
                if status == "completed" and task_status != "completed":
                    logger.info(
                        f"[TaskEmail] task {queued_task.task_id} DB status={task_status!r}, skipping"
                    )
                    return

                if not user_id:
                    user_id = task.user_id
                task_name = getattr(task, "task_name", None) or queued_task.task_id
        except Exception as exc:
            logger.warning(
                f"[TaskEmail] could not resolve task info for {queued_task.task_id}: {exc}"
            )
            return

        if not user_id:
            return

        try:
            async with async_session() as db:
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if not user:
                    return

                pref_attr = self._STATUS_PREF.get(status)
                if not pref_attr or not getattr(user, pref_attr, False):
                    return

                to_email = user.registration_email or ""
                display_name = user.nickname or user.username

            await send_templated_email(
                template_key="task_completed_notice",
                to_email=to_email,
                context={
                    "display_name": display_name,
                    "username": user.username,
                    "task_name": task_name,
                    "task_status": self._STATUS_SUBJECT.get(status, status),
                    "task_status_desc": self._STATUS_DESC.get(status, status),
                },
                for_admin=False,
            )
        except Exception as exc:
            logger.warning(
                f"[TaskEmail] failed to send notice for task {queued_task.task_id}: {exc}"
            )

    async def _invalidate_context_for_task(self, queued_task: QueuedTask) -> None:
        if queued_task.task_type not in (TaskType.TRAINING, TaskType.INFERENCE):
            return
        user_id: str | None = queued_task.kwargs.get("user_id")
        if not user_id:
            try:
                async with async_session() as db:
                    if queued_task.task_type == TaskType.TRAINING:
                        task = await TrainingTaskRepository.get_by_id(
                            db, queued_task.task_id
                        )
                    else:
                        task = await AITaskRepository.get_by_id(db, queued_task.task_id)
                    user_id = str(task.user_id) if task else None
            except Exception as exc:
                logger.warning(
                    f"[ChatCtxCache] could not resolve user_id for task {queued_task.task_id}: {exc}"
                )
        if user_id:
            try:
                context_cache = _get_context_cache_module()
                await context_cache.invalidate_chat_context(user_id)
                await context_cache.clear_training_snapshot(queued_task.task_id)
            except Exception as exc:
                logger.warning(
                    f"[ChatCtxCache] invalidation failed for task {queued_task.task_id}: {exc}"
                )

    async def _ensure_task_failed(
        self, task_id: str, task_type: TaskType, error_msg: str
    ):
        """
        Safety net: check if the task is still in a non-terminal state after an exception,
        and force-update it to 'failed' if so.

        This handles the case where the pipeline's own error handler also failed
        (e.g., DB connection issue), leaving the task stuck in 'resuming'/'pending'/'patching'.
        """
        NON_TERMINAL = {
            "pending",
            "queued",
            "patching",
            "resuming",
            "extracting",
            "training",
        }
        try:
            async with async_session() as db:
                if task_type == TaskType.TRAINING:
                    task = await TrainingTaskRepository.get_by_id(db, task_id)
                    if task and task.status in NON_TERMINAL:
                        logger.warning(
                            f"Safety net: task {task_id} still in '{task.status}' after exception, "
                            f"forcing to 'failed'"
                        )
                        await TrainingTaskRepository.update_status(
                            db,
                            task_id,
                            TaskStatus.FAILED,
                            error_message=f"Task failed (safety net): {error_msg}",
                        )
                elif task_type == TaskType.INFERENCE:
                    task = await AITaskRepository.get_by_id(db, task_id)
                    if task and task.status in NON_TERMINAL:
                        logger.warning(
                            f"Safety net: task {task_id} still in '{task.status}' after exception, "
                            f"forcing to 'failed'"
                        )
                        await AITaskRepository.update_status(
                            db,
                            task_id,
                            TaskStatus.FAILED,
                            error_message=f"Task failed (safety net): {error_msg}",
                        )
                elif task_type == TaskType.EXTERNAL_VALIDATION:
                    # External validation reuses TrainingTask table
                    task = await TrainingTaskRepository.get_by_id(db, task_id)
                    if task and task.status in NON_TERMINAL:
                        logger.warning(
                            f"Safety net: task {task_id} still in '{task.status}' after exception, "
                            f"forcing to 'failed'"
                        )
                        await TrainingTaskRepository.update_status(
                            db,
                            task_id,
                            TaskStatus.FAILED,
                            error_message=f"Task failed (safety net): {error_msg}",
                        )
                await db.commit()
        except Exception as fallback_err:
            # Last resort: if even the safety net fails, just log it.
            # The task will be picked up on next restart via resume_interrupted_tasks().
            logger.error(
                f"Safety net also failed for task {task_id}: {fallback_err}. "
                f"Task may remain in non-terminal state until next restart."
            )

    def get_status(self) -> Dict[str, Any]:
        """
        Get current queue status including VRAM and GPU information.

        Returns:
            Dictionary with queue statistics, GPU info, and memory status
        """
        # Build running tasks info with GPU assignments
        running_tasks_info = []
        for task_id in self._running_tasks.keys():
            gpu_idx = self._gpu_assignments.get(task_id)
            running_tasks_info.append(
                {
                    "task_id": task_id,
                    "gpu": gpu_idx,
                }
            )

        status: Dict[str, Any] = {
            "max_concurrent": self.max_concurrent,
            "min_vram_mb": self.min_vram_mb,
            "gpu_count": self.gpu_count,
            "bad_gpus": sorted(self._bad_gpus),
            "running_count": len(self._running_tasks),
            "pending_count": len(self._pending_tasks),
            "queue_size": self._queue.qsize() if self._queue else 0,
            "patching_count": len(self._patching_tasks),
            "patching_task_ids": list(self._patching_tasks.keys()),
            "running_task_ids": list(self._running_tasks.keys()),
            "running_tasks": running_tasks_info,
            "pending_task_ids": list(self._pending_tasks.keys()),
            "gpu_stage_details": dict(self._gpu_stage_details),
            "is_running": self._worker_task is not None and not self._shutdown,
        }

        # Add GPU info if available
        try:
            gpu_utils = _get_gpu_utils_module()
            get_all_gpu_info = gpu_utils.get_all_gpu_info
            check_vram_available = gpu_utils.check_vram_available

            status["gpus"] = get_all_gpu_info()
            is_available, current_free_mb, message = check_vram_available(
                self.min_vram_mb
            )
            status["vram_available"] = is_available
            status["vram_free_mb"] = current_free_mb
            status["vram_status"] = message
        except ImportError:
            status["gpus"] = []
            status["vram_available"] = None
            status["vram_status"] = "GPU utils not available"

        return status

    async def set_max_concurrent(self, max_concurrent: int) -> None:
        """
        Update maximum concurrent tasks dynamically.

        If increasing the limit, immediately wakes up waiting tasks.
        If decreasing, excess running tasks continue but no new ones start.
        """
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")

        if not self._condition:
            # Queue not started yet, just update the value
            old_value = self.max_concurrent
            self.max_concurrent = max_concurrent
            logger.info(f"max_concurrent changed from {old_value} to {max_concurrent}")
            return

        # Modify value inside the lock to avoid race condition with _worker_loop
        async with self._condition:
            old_value = self.max_concurrent
            self.max_concurrent = max_concurrent
            # If we increased the limit, notify waiting tasks so they can start
            if max_concurrent > old_value:
                self._condition.notify_all()

        logger.info(f"max_concurrent changed from {old_value} to {max_concurrent}")

    def is_task_in_queue(self, task_id: str) -> bool:
        """Check if a task is tracked (patching pre-queue, pending in queue, or running)."""
        return (
            task_id in self._running_tasks
            or task_id in self._pending_tasks
            or task_id in self._patching_tasks
        )

    async def cancel_pending_task(self, task_id: str) -> bool:
        """Remove a task only if it is still pending and has not started running."""
        if task_id not in self._pending_tasks:
            return False

        queued_task = self._pending_tasks.pop(task_id)
        self._release_soft_vram(task_id)
        logger.info(f"Task {task_id} removed from pending queue")
        asyncio.create_task(self._notify_task_status_change(queued_task, "cancelled"))
        await self._notify_queue_state_changed()
        return True

    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a task if it's running or queued.

        Also wakes any worker currently blocked on the cancelled queue head so the
        next pending task can be considered immediately instead of waiting for the
        next timeout/notification cycle.

        Returns:
            True if task was cancelled, False if not found or not running
        """
        if task_id in self._patching_tasks:
            patching_task = self._patching_tasks.pop(task_id)
            patching_task.cancel()
            logger.info(f"Pre-queue patching task {task_id} cancelled")
            await self._notify_queue_state_changed()
            return True

        if task_id in self._running_tasks:
            task = self._running_tasks[task_id]
            task.cancel()
            logger.info(f"Task {task_id} cancelled")
            await self._notify_queue_state_changed()
            return True

        if await self.cancel_pending_task(task_id):
            return True

        return False


# Global instance getter
def get_task_queue() -> TaskQueueManager:
    """Get the global TaskQueueManager instance"""
    if TaskQueueManager._instance is None:
        TaskQueueManager()
    return cast(TaskQueueManager, TaskQueueManager._instance)


async def init_task_queue(
    max_concurrent: int = 1,
    min_vram_mb: float | None = None,
    vram_check_interval: float = 5.0,
    gpu_count: int = 1,
) -> TaskQueueManager:
    """
    Initialize and start the task queue.

    Should be called during application startup.

    Args:
        max_concurrent: Maximum number of concurrent GPU tasks (default: 1)
        min_vram_mb: Minimum free VRAM required to start a task (default from Config)
        vram_check_interval: Interval in seconds between VRAM checks (default: 5.0)
        gpu_count: Number of available GPUs (default: 1)
    """
    queue = TaskQueueManager(
        max_concurrent=max_concurrent,
        min_vram_mb=min_vram_mb,
        vram_check_interval=vram_check_interval,
        gpu_count=gpu_count,
    )
    await queue.start()
    return queue


async def shutdown_task_queue() -> None:
    """
    Shutdown the task queue gracefully.

    Should be called during application shutdown.
    """
    queue = get_task_queue()
    await queue.stop()
