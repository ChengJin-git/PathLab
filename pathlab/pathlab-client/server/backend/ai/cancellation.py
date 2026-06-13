"""Training Cancellation Mechanism — backed by TaskInterruptionSet."""

from backend.ai.common.task_control import TaskInterruptionSet

_cancellation = TaskInterruptionSet("cancellation")


class TrainingCancelledException(Exception):
    """Raised inside a training loop when the task is cancelled."""


def request_cancellation(task_id: str) -> bool:
    return _cancellation.request(task_id)


def is_task_cancelled(task_id: str) -> bool:
    return _cancellation.is_set(task_id)


def clear_cancellation(task_id: str) -> None:
    _cancellation.clear(task_id)
