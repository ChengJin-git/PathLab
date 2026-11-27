"""
Gateway-layer ownership and role assertion helpers.

Eliminates the repeated two-line pattern:
    if not check_data_ownership(owner_id, user):
        raise HTTPException(status_code=403, detail="...")

Route handlers express intent (assert_owner / assert_admin);
enforcement mechanics stay here.
"""

from fastapi import HTTPException
from backend.auth import User
from backend.auth.dependencies import check_data_ownership


def assert_owner(
    resource_owner_id: str,
    user: User,
    detail: str = "You don't have permission to access this resource",
) -> None:
    """Raise HTTP 403 if user is not the resource owner (admins bypass this check)."""
    if not check_data_ownership(resource_owner_id, user):
        raise HTTPException(status_code=403, detail=detail)


def assert_admin(user: User, detail: str = "Admin access required") -> None:
    """Raise HTTP 403 if user is not an admin."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail=detail)
