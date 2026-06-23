"""Generic task-lifecycle control (cancellation, permission revocation, etc.)."""

from __future__ import annotations

import logging
from typing import Set

logger = logging.getLogger(__name__)


class TaskInterruptionSet:
    """In-process set of task IDs signalling one type of interruption.

    Two instances = two independent signals (cancellation + permission revocation).
    Callers check each independently.
    """

    def __init__(self, label: str) -> None:
        self._label = label
        self._tasks: Set[str] = set()

    def request(self, task_id: str) -> bool:
        """Signal that *task_id* should stop. Always returns True."""
        self._tasks.add(task_id)
        logger.info("%s requested for task %s", self._label, task_id)
        return True

    def is_set(self, task_id: str) -> bool:
        return task_id in self._tasks

    def clear(self, task_id: str) -> None:
        self._tasks.discard(task_id)
