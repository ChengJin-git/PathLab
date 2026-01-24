"""
RBAC (Role-Based Access Control) Dependencies

Provides FastAPI dependencies for role-based authorization:
- require_admin: Only admin users
- require_pathologist_or_admin: Pathologist or admin
- require_can_use_gpu: Users who can use GPU operations (admin/pathologist)
- get_current_user_id: Get current user's ID for data filtering

Usage:
    @router.get("/admin-only")
    async def admin_endpoint(user: User = Depends(require_admin)):
        ...
    
    @router.post("/analyze")
    async def analyze(user: User = Depends(require_can_use_gpu)):
        ...
"""

import uuid
from typing import Optional

from fastapi import Depends, HTTPException, status

from .users import current_active_user, optional_current_user
from .models import User


async def require_admin(user: User = Depends(current_active_user)) -> User:
    """
    Dependency that requires the current user to be an admin.
    
    Raises:
        HTTPException 403: If user is not an admin
    """
    if not user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


async def require_pathologist_or_admin(user: User = Depends(current_active_user)) -> User:
    """
    Dependency that requires the current user to be a pathologist or admin.
    
    Raises:
        HTTPException 403: If user is neither pathologist nor admin
    """
    if user.role not in {User.ROLE_ADMIN, User.ROLE_PATHOLOGIST}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pathologist or admin access required"
        )
    return user


async def require_can_use_gpu(user: User = Depends(current_active_user)) -> User:
    """
    Dependency that requires the current user to have GPU access.
    
    GPU operations include:
    - AI analysis tasks
    - Model training
    - Feature extraction
    
    Guests cannot use GPU operations.
    
    Raises:
        HTTPException 403: If user cannot use GPU
    """
    if not user.can_use_gpu():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="GPU operations not available for guest users. Please contact admin for access."
        )
    return user


async def get_current_user_id(user: User = Depends(current_active_user)) -> str:
    """
    Get the current user's ID as a string for database queries.
    
    Use this for data filtering - associating data with users.
    """
    return str(user.id)


async def get_optional_user_id(
    user: Optional[User] = Depends(optional_current_user)
) -> Optional[str]:
    """
    Get the current user's ID if logged in, otherwise None.
    
    Use this for routes that work with or without authentication.
    """
    if user is None:
        return None
    return str(user.id)


def check_data_ownership(resource_user_id: Optional[str], current_user: User) -> bool:
    """
    Check if the current user can access a resource based on ownership.
    
    Admin can access all resources.
    Other users can only access their own resources.
    
    Args:
        resource_user_id: The user_id of the resource owner
        current_user: The currently authenticated user
        
    Returns:
        True if the user can access the resource
    """
    # Admin can access everything
    if current_user.is_admin():
        return True
    
    # If resource has no owner (legacy data), allow access
    if resource_user_id is None:
        return True
    
    # Check if user owns the resource
    return resource_user_id == str(current_user.id)

