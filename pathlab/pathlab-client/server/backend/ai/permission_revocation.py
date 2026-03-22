"""
Permission Revocation Mechanism

This module provides the permission revocation mechanism for training tasks.
When an admin revokes a user's temporary elevated permission for a dataset,
all running tasks that depend on that permission should be terminated.

This is kept separate from training routes to avoid circular imports.

Usage:
- Gateway calls revoke_task_permission(task_id) when admin revokes dataset grant
- Trainers call is_permission_revoked(task_id) in their training loops (same checkpoints as cancellation)
- Training endpoints call clear_revocation(task_id) in their finally blocks
"""
import logging
from typing import Set

logger = logging.getLogger("permission_revocation")

# Global set of task IDs whose permissions have been revoked
# Trainers check this set in their training loops alongside cancellation checks
_revoked_tasks: Set[str] = set()


class PermissionRevokedException(Exception):
    """Exception raised when a task's permission is revoked by admin during execution."""
    pass


def revoke_task_permission(task_id: str) -> bool:
    """
    Mark a task as having its permission revoked.

    Called by Gateway when admin revokes a user's dataset grant
    and there are running tasks that depend on that permission.

    Args:
        task_id: The training task ID to mark as revoked

    Returns:
        True if revocation was marked (task will stop at next checkpoint)
    """
    _revoked_tasks.add(task_id)
    logger.info(f"Permission revoked for task {task_id}")
    return True


def is_permission_revoked(task_id: str) -> bool:
    """
    Check if a task's permission has been revoked.

    Trainers should call this in their training loops alongside is_task_cancelled().
    This check is O(1) and has negligible performance impact.

    Args:
        task_id: The training task ID to check

    Returns:
        True if the task's permission has been revoked
    """
    return task_id in _revoked_tasks


def clear_revocation(task_id: str) -> None:
    """
    Clear the revocation flag for a task.

    Called after task cleanup (in finally blocks) to free memory.

    Args:
        task_id: The training task ID to clear
    """
    _revoked_tasks.discard(task_id)
    logger.debug(f"Cleared revocation flag for task {task_id}")

