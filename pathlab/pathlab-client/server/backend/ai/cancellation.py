"""
Training Cancellation Mechanism

This module provides the cancellation mechanism for training tasks.
It is kept separate from training routes to avoid circular imports.

Usage:
- Gateway calls request_cancellation(task_id) when timeout occurs or user cancels
- Trainers call is_task_cancelled(task_id) in their training loops
- Training endpoints call clear_cancellation(task_id) in their finally blocks
"""
import logging
from typing import Set

logger = logging.getLogger("training_cancellation")

# Global set of task IDs that have been requested to cancel
# Trainers check this set in their training loops
_cancellation_requests: Set[str] = set()


class TrainingCancelledException(Exception):
    """Exception raised when training is cancelled by user or timeout."""
    pass


def request_cancellation(task_id: str) -> bool:
    """
    Request cancellation of a training task.

    Returns:
        True if cancellation was requested (task will stop at next check point)
    """
    _cancellation_requests.add(task_id)
    logger.info(f"Cancellation requested for task {task_id}")
    return True


def is_task_cancelled(task_id: str) -> bool:
    """
    Check if a task has been requested to cancel.

    Trainers should call this in their training loops (e.g., at each epoch start).
    """
    return task_id in _cancellation_requests


def clear_cancellation(task_id: str) -> None:
    """Clear the cancellation flag for a task (called after task cleanup)."""
    _cancellation_requests.discard(task_id)

