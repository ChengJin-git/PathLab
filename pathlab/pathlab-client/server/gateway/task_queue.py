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

logger = logging.getLogger("task_queue")

# Default minimum VRAM required to start a GPU task (in MB)
# This ensures previous task has released GPU memory before starting a new one
DEFAULT_MIN_VRAM_MB = 2000  # 2GB - reasonable for most models


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
    args: tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __hash__(self):
        return hash(self.task_id)


class TaskQueueManager:
    """
    Singleton manager for GPU task queue.

    Controls the number of concurrent GPU tasks to prevent GPU memory exhaustion.
    Tasks are executed in FIFO order.

    Features:
    - Concurrency control (default: 1 GPU task at a time)
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
        min_vram_mb: float = DEFAULT_MIN_VRAM_MB,
        vram_check_interval: float = 5.0,
    ):
        """
        Initialize the TaskQueueManager.

        Args:
            max_concurrent: Maximum number of concurrent GPU tasks (default: 1)
            min_vram_mb: Minimum free VRAM required to start a task (default: 2000 MB)
            vram_check_interval: Interval in seconds between VRAM checks (default: 5.0)
        """
        # Prevent re-initialization
        if TaskQueueManager._initialized:
            return

        self.max_concurrent = max_concurrent
        self.min_vram_mb = min_vram_mb
        self.vram_check_interval = vram_check_interval
        self._queue: asyncio.Queue[QueuedTask] = asyncio.Queue()
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._pending_tasks: Dict[str, QueuedTask] = {}  # task_id -> QueuedTask
        self._condition: Optional[asyncio.Condition] = None  # For dynamic concurrency control
        self._vram_condition: Optional[asyncio.Condition] = None  # For VRAM availability notification
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown: bool = False

        TaskQueueManager._initialized = True
        logger.info(
            f"TaskQueueManager initialized with max_concurrent={max_concurrent}, "
            f"min_vram_mb={min_vram_mb}, vram_check_interval={vram_check_interval}s"
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
        **kwargs
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
    
    async def _wait_for_vram(self, task_id: str) -> bool:
        """
        Wait until sufficient VRAM is available.

        Uses event-driven waiting with timeout fallback:
        1. First checks if VRAM is already available (fast path)
        2. If not, waits for notification from completed tasks
        3. Uses timeout to handle edge cases (external GPU memory release)

        Args:
            task_id: Task ID for logging and cancellation check

        Returns:
            True if VRAM is available, False if task was cancelled during wait
        """
        # Import here to avoid circular imports (gateway -> backend)
        try:
            from backend.common.gpu_utils import check_vram_available, get_total_vram_mb
        except ImportError:
            # If import fails, skip VRAM check (e.g., in tests without GPU)
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
            # Check if task was cancelled while waiting
            if task_id not in self._pending_tasks:
                logger.info(f"Task {task_id} was cancelled while waiting for VRAM")
                return False

            is_available, current_free_mb, message = check_vram_available(self.min_vram_mb)

            if is_available:
                if wait_count > 0:
                    logger.info(
                        f"VRAM now available for task {task_id} after {wait_count} waits. "
                        f"Free: {current_free_mb:.0f} MB"
                    )
                return True

            wait_count += 1
            if wait_count == 1:
                logger.info(
                    f"Task {task_id} waiting for VRAM. {message}. "
                    f"Waiting for task completion notification..."
                )

            # Event-driven wait with timeout fallback
            # - Primary: Wait for notification when a task completes (_notify_vram_released)
            # - Fallback: Timeout ensures we don't miss external GPU memory releases
            async with self._vram_condition:
                try:
                    await asyncio.wait_for(
                        self._vram_condition.wait(),
                        timeout=self.vram_check_interval
                    )
                    # Notified by a completed task, check VRAM again
                except asyncio.TimeoutError:
                    # Timeout - check anyway in case of external GPU memory release
                    pass

            # Log progress every minute
            if wait_count % 12 == 0:
                logger.info(
                    f"Task {task_id} still waiting for VRAM ({wait_count * self.vram_check_interval:.0f}s elapsed). "
                    f"{message}"
                )

        return False

    async def _notify_vram_released(self):
        """
        Notify waiting tasks that GPU memory may have been released.

        Called after a task completes to wake up tasks waiting for VRAM.
        """
        if self._vram_condition:
            async with self._vram_condition:
                self._vram_condition.notify_all()

    async def _worker_loop(self):
        """Main worker loop that processes tasks from the queue"""
        logger.info("Worker loop started")

        while not self._shutdown:
            try:
                # Get task from queue (blocks until available)
                queued_task = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0
                )
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

            # VRAM pre-check: Wait until GPU has enough free memory
            # This prevents OOM when previous task hasn't fully released GPU memory
            vram_ready = await self._wait_for_vram(queued_task.task_id)
            if not vram_ready:
                # Task was cancelled or shutdown requested
                self._queue.task_done()
                continue

            # Double-check task wasn't cancelled during VRAM wait
            if queued_task.task_id not in self._pending_tasks:
                logger.info(f"Task {queued_task.task_id} was cancelled during VRAM wait, skipping")
                self._queue.task_done()
                continue

            # Remove from pending, add to running
            self._pending_tasks.pop(queued_task.task_id, None)

            # Create task and track it
            task = asyncio.create_task(
                self._run_task(queued_task)
            )
            self._running_tasks[queued_task.task_id] = task

            logger.info(
                f"Task {queued_task.task_id} started. "
                f"Running: {len(self._running_tasks)}/{self.max_concurrent}"
            )
    
    async def _run_task(self, queued_task: QueuedTask):
        """Execute a single task and handle cleanup"""
        try:
            await queued_task.coro_func(*queued_task.args, **queued_task.kwargs)
            logger.info(f"Task {queued_task.task_id} completed successfully")
        except Exception as e:
            logger.error(f"Task {queued_task.task_id} failed: {e}")
        finally:
            # Cleanup and notify waiting tasks
            self._running_tasks.pop(queued_task.task_id, None)

            # Notify concurrency waiters
            async with self._condition:
                self._condition.notify()  # Wake up one waiting task

            # Notify VRAM waiters - GPU memory should be released soon
            await self._notify_vram_released()

            self._queue.task_done()

    def get_status(self) -> Dict[str, Any]:
        """
        Get current queue status including VRAM information.

        Returns:
            Dictionary with queue statistics and GPU memory status
        """
        status = {
            "max_concurrent": self.max_concurrent,
            "min_vram_mb": self.min_vram_mb,
            "running_count": len(self._running_tasks),
            "pending_count": len(self._pending_tasks),
            "queue_size": self._queue.qsize() if self._queue else 0,
            "running_task_ids": list(self._running_tasks.keys()),
            "pending_task_ids": list(self._pending_tasks.keys()),
            "is_running": self._worker_task is not None and not self._shutdown,
        }

        # Add VRAM info if available
        try:
            from backend.common.gpu_utils import check_vram_available
            is_available, current_free_mb, message = check_vram_available(self.min_vram_mb)
            status["vram_available"] = is_available
            status["vram_free_mb"] = current_free_mb
            status["vram_status"] = message
        except ImportError:
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

    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a task if it's running.

        Returns:
            True if task was cancelled, False if not found or not running
        """
        if task_id in self._running_tasks:
            task = self._running_tasks[task_id]
            task.cancel()
            logger.info(f"Task {task_id} cancelled")
            return True

        if task_id in self._pending_tasks:
            # Remove from pending (it's still in the asyncio.Queue,
            # but will be skipped when dequeued)
            self._pending_tasks.pop(task_id, None)
            logger.info(f"Task {task_id} removed from pending queue")
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
    min_vram_mb: float = DEFAULT_MIN_VRAM_MB,
    vram_check_interval: float = 5.0,
) -> TaskQueueManager:
    """
    Initialize and start the task queue.

    Should be called during application startup.

    Args:
        max_concurrent: Maximum number of concurrent GPU tasks (default: 1)
        min_vram_mb: Minimum free VRAM required to start a task (default: 2000 MB)
        vram_check_interval: Interval in seconds between VRAM checks (default: 5.0)
    """
    queue = TaskQueueManager(
        max_concurrent=max_concurrent,
        min_vram_mb=min_vram_mb,
        vram_check_interval=vram_check_interval,
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

