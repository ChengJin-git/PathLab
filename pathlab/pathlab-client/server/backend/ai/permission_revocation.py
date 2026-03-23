"""Permission Revocation Mechanism — backed by TaskInterruptionSet."""

from backend.ai.common.task_control import TaskInterruptionSet

_revocation = TaskInterruptionSet("permission_revocation")


class PermissionRevokedException(Exception):
    """Raised inside a training loop when the task's permission is revoked."""


def revoke_task_permission(task_id: str) -> bool:
    return _revocation.request(task_id)


def is_permission_revoked(task_id: str) -> bool:
    return _revocation.is_set(task_id)


def clear_revocation(task_id: str) -> None:
    _revocation.clear(task_id)
