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
from dataclasses import dataclass, field
from typing import Dict, Callable, Awaitable, Any, Optional, List
from enum import Enum
from datetime import datetime
from sqlalchemy import select

from backend.common.config import Config
from backend.database import async_session
from backend.auth.models import User
from .email_notifications import send_templated_email

logger = logging.getLogger("task_queue")


class TaskType(str, Enum):
    """Task types managed by the queue"""

    TRAINING = "training"
    INFERENCE = "inference"
    EXTERNAL_VALIDATION = "external_validation"
    ANALYSIS = "analysis"


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
        min_vram_mb: float = None,
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
        self._bad_gpus: set = set()  # GPU indices confirmed to have hardware failures
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
            task_type: Type of task (training or inference) - for queue management
            coro_func: Async function to execute
            *args, **kwargs: Arguments to pass to the function
                Note: kwargs may contain 'task_type' which is for coro_func (e.g., classification/survival),
                not for queue management. This is handled correctly.
        """
        # Ensure task_id is passed to coro_func via kwargs
        # (coro_func typically expects task_id as its first argument)
        # Note: kwargs may contain 'task_type' which is for coro_func (e.g., classification/survival),
        # not for queue management. This is fine - we keep it in kwargs for coro_func.
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

    def get_bad_gpus(self) -> frozenset:
        """Return a snapshot of GPU indices currently marked as unhealthy."""
        return frozenset(self._bad_gpus)

    def _select_optimal_gpu(self) -> int:
        """
        Select the optimal GPU for a new task.

        Selection strategy:
        1. First, try to find a GPU that has NO running tasks and meets VRAM requirement
        2. If all GPUs have tasks, fall back to selecting the one with most free VRAM

        This ensures tasks are distributed across GPUs when max_concurrent > 1.

        Returns:
            GPU index with most free VRAM that meets minimum requirement,
            or -1 if no suitable GPU found.
        """
        try:
            from backend.common.gpu_utils import get_all_gpu_info
        except ImportError:
            logger.warning("Could not import gpu_utils, defaulting to GPU 0")
            return 0

        gpu_info_list = get_all_gpu_info()
        if not gpu_info_list:
            return -1

        gpus_with_tasks = set(self._gpu_assignments.values())

        # Strategy 1: idle GPU (no running tasks) that is healthy and meets VRAM requirement
        best_idle_gpu = -1
        best_idle_free_mb = 0.0
        for info in gpu_info_list:
            gpu_idx = info["index"]
            free_mb = info["free_mb"]
            if gpu_idx in self._bad_gpus:
                continue
            if gpu_idx not in gpus_with_tasks and free_mb >= self.min_vram_mb:
                if free_mb > best_idle_free_mb:
                    best_idle_free_mb = free_mb
                    best_idle_gpu = gpu_idx

        if best_idle_gpu >= 0:
            logger.debug(
                f"Selected idle GPU {best_idle_gpu} with {best_idle_free_mb:.0f} MB free VRAM "
                f"(GPUs with tasks: {gpus_with_tasks}, bad GPUs: {self._bad_gpus})"
            )
            return best_idle_gpu

        # Strategy 2: all healthy GPUs have tasks — pick the one with most free VRAM
        best_gpu = -1
        best_free_mb = 0.0
        for info in gpu_info_list:
            gpu_idx = info["index"]
            free_mb = info["free_mb"]
            if gpu_idx in self._bad_gpus:
                continue
            if free_mb >= self.min_vram_mb and free_mb > best_free_mb:
                best_free_mb = free_mb
                best_gpu = gpu_idx

        if best_gpu >= 0:
            logger.debug(
                f"All healthy GPUs have tasks, selected GPU {best_gpu} with {best_free_mb:.0f} MB free VRAM"
            )
        return best_gpu

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
            from backend.common.gpu_utils import (
                check_gpu_vram_available,
                get_total_vram_mb,
            )
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

            async with self._vram_condition:
                try:
                    await asyncio.wait_for(
                        self._vram_condition.wait(), timeout=self.vram_check_interval
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

            # Try to find a GPU with enough VRAM
            gpu_idx = self._select_optimal_gpu()
            if gpu_idx >= 0:
                if wait_count > 0:
                    logger.info(
                        f"GPU {gpu_idx} now available for task {task_id} after {wait_count} waits"
                    )
                return gpu_idx

            wait_count += 1
            if wait_count == 1:
                logger.info(
                    f"Task {task_id} waiting for any GPU with sufficient VRAM. "
                    f"Required: {self.min_vram_mb:.0f} MB"
                )

            async with self._vram_condition:
                try:
                    await asyncio.wait_for(
                        self._vram_condition.wait(), timeout=self.vram_check_interval
                    )
                except asyncio.TimeoutError:
                    pass

            if wait_count % 12 == 0:
                logger.info(
                    f"Task {task_id} still waiting for GPU "
                    f"({wait_count * self.vram_check_interval:.0f}s elapsed)"
                )

        return -1

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
            async with self._condition:
                while len(self._running_tasks) >= self.max_concurrent:
                    await self._condition.wait()

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
                    from backend.database.repositories import TrainingTaskRepository

                    task = await TrainingTaskRepository.get_by_id(
                        db, queued_task.task_id
                    )
                else:
                    from backend.database.repositories import AITaskRepository

                    task = await AITaskRepository.get_by_id(db, queued_task.task_id)

                if not task:
                    return

                if status == "completed" and task.status != "completed":
                    logger.info(
                        f"[TaskEmail] task {queued_task.task_id} DB status={task.status!r}, skipping"
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
                display_name = user.nickname or user.email

            await send_templated_email(
                template_key="task_completed_notice",
                to_email=to_email,
                context={
                    "display_name": display_name,
                    "username": user.email,
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
                from backend.database import async_session

                async with async_session() as db:
                    if queued_task.task_type == TaskType.TRAINING:
                        from backend.database.repositories import TrainingTaskRepository

                        task = await TrainingTaskRepository.get_by_id(
                            db, queued_task.task_id
                        )
                    else:
                        from backend.database.repositories import AITaskRepository

                        task = await AITaskRepository.get_by_id(db, queued_task.task_id)
                    user_id = task.user_id if task else None
            except Exception as exc:
                logger.warning(
                    f"[ChatCtxCache] could not resolve user_id for task {queued_task.task_id}: {exc}"
                )
        if user_id:
            try:
                from backend.common.chat_context_cache import (
                    invalidate_chat_context,
                    clear_training_snapshot,
                )

                await invalidate_chat_context(user_id)
                await clear_training_snapshot(queued_task.task_id)
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
            from backend.database import async_session
            from backend.ai.schemas.base import TaskStatus

            async with async_session() as db:
                if task_type == TaskType.TRAINING:
                    from backend.database.repositories import TrainingTaskRepository

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
                    from backend.database.repositories import AITaskRepository

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
                    from backend.database.repositories import TrainingTaskRepository

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

        status = {
            "max_concurrent": self.max_concurrent,
            "min_vram_mb": self.min_vram_mb,
            "gpu_count": self.gpu_count,
            "bad_gpus": sorted(self._bad_gpus),
            "running_count": len(self._running_tasks),
            "pending_count": len(self._pending_tasks),
            "queue_size": self._queue.qsize() if self._queue else 0,
            "running_task_ids": list(self._running_tasks.keys()),
            "running_tasks": running_tasks_info,  # Tasks with GPU assignments
            "pending_task_ids": list(self._pending_tasks.keys()),
            "is_running": self._worker_task is not None and not self._shutdown,
        }

        # Add GPU info if available
        try:
            from backend.common.gpu_utils import get_all_gpu_info, check_vram_available

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
        """Check if a task is in the queue (pending or running)"""
        return task_id in self._running_tasks or task_id in self._pending_tasks

    async def cancel_pending_task(self, task_id: str) -> bool:
        """Remove a task only if it is still pending and has not started running."""
        if task_id not in self._pending_tasks:
            return False

        queued_task = self._pending_tasks.pop(task_id)
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
    return TaskQueueManager._instance


async def init_task_queue(
    max_concurrent: int = 1,
    min_vram_mb: float = None,
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


async def shutdown_task_queue():
    """
    Shutdown the task queue gracefully.

    Should be called during application shutdown.
    """
    queue = get_task_queue()
    if queue:
        await queue.stop()
