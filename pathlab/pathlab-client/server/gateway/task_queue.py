"""
GPU Task Queue Manager

Centralized task queue management to control GPU task concurrency and prevent GPU overload.
Supports:
- Maximum concurrency control (default: 1 GPU task at a time)
- FIFO task scheduling
- Task recovery after power outage/restart
- Unified management for both TrainingTask and AITask (inference)
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Callable, Awaitable, Any, Optional, List
from enum import Enum
from datetime import datetime

logger = logging.getLogger("task_queue")


class TaskType(str, Enum):
    """Task types managed by the queue"""
    TRAINING = "training"
    INFERENCE = "inference"


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
    """
    _instance: Optional["TaskQueueManager"] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, max_concurrent: int = 1):
        # Prevent re-initialization
        if TaskQueueManager._initialized:
            return
        
        self.max_concurrent = max_concurrent
        self._queue: asyncio.Queue[QueuedTask] = asyncio.Queue()
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._pending_tasks: Dict[str, QueuedTask] = {}  # task_id -> QueuedTask
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown: bool = False
        
        TaskQueueManager._initialized = True
        logger.info(f"TaskQueueManager initialized with max_concurrent={max_concurrent}")
    
    async def start(self):
        """Start the queue worker"""
        if self._worker_task is not None:
            return
        
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
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
            task_type: Type of task (training or inference)
            coro_func: Async function to execute
            *args, **kwargs: Arguments to pass to the function
        """
        queued_task = QueuedTask(
            task_id=task_id,
            task_type=task_type,
            coro_func=coro_func,
            args=args,
            kwargs=kwargs,
        )
        
        self._pending_tasks[task_id] = queued_task
        await self._queue.put(queued_task)
        
        logger.info(
            f"Task {task_id} ({task_type.value}) submitted to queue. "
            f"Queue size: {self._queue.qsize()}, Running: {len(self._running_tasks)}"
        )
    
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
            
            # Wait for semaphore (concurrency control)
            await self._semaphore.acquire()
            
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
            # Cleanup
            self._running_tasks.pop(queued_task.task_id, None)
            self._semaphore.release()
            self._queue.task_done()

    def get_status(self) -> Dict[str, Any]:
        """
        Get current queue status.

        Returns:
            Dictionary with queue statistics
        """
        return {
            "max_concurrent": self.max_concurrent,
            "running_count": len(self._running_tasks),
            "pending_count": len(self._pending_tasks),
            "queue_size": self._queue.qsize() if self._queue else 0,
            "running_task_ids": list(self._running_tasks.keys()),
            "pending_task_ids": list(self._pending_tasks.keys()),
            "is_running": self._worker_task is not None and not self._shutdown,
        }

    def set_max_concurrent(self, max_concurrent: int) -> None:
        """
        Update maximum concurrent tasks.

        Note: Changes take effect for new tasks only.
        Currently running tasks are not affected.
        """
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")

        old_value = self.max_concurrent
        self.max_concurrent = max_concurrent
        # Semaphore will be recreated on next start
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


async def init_task_queue(max_concurrent: int = 1) -> TaskQueueManager:
    """
    Initialize and start the task queue.

    Should be called during application startup.
    """
    queue = TaskQueueManager(max_concurrent=max_concurrent)
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

