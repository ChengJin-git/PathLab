"""
RBAC (Role-Based Access Control) Dependencies

Provides FastAPI dependencies for role-based authorization:
- require_admin: Only admin users
- require_pathologist_or_admin: Pathologist or admin
- require_can_use_gpu: Users who can use GPU operations (admin/pathologist)
- get_current_user_id: Get current user's ID for data filtering
- check_dataset_gpu_permission: Check if user has GPU permission for a specific dataset
- get_user_from_token_param: Validate JWT from URL query parameter (for SSE streams)

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

from fastapi import Depends, HTTPException, Query, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt, JWTError

from .users import current_active_user, optional_current_user, JWT_SECRET
from .models import User
from backend.database.database import get_db


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


async def check_dataset_gpu_permission(
    user: User,
    dataset_id: str,
    db: AsyncSession
) -> bool:
    """
    Check if a user can perform GPU operations on a specific dataset.

    Returns True if:
    - User is admin or pathologist (has can_use_gpu())
    - OR user has valid temporary elevated permission for this dataset

    This is used for AI analysis and training tasks where we allow
    temporary elevated access for demo purposes.

    Args:
        user: Current user
        dataset_id: Dataset UUID to check permission for
        db: Database session

    Returns:
        True if user can use GPU operations on this dataset
    """
    # Admin or pathologist can always use GPU
    if user.can_use_gpu():
        return True

    # Check for temporary elevated permission
    from backend.database.repositories import DatasetPermissionRepository
    return await DatasetPermissionRepository.has_valid_permission(
        db, dataset_id, str(user.id), "pathologist"
    )


async def require_dataset_gpu_permission(
    user: User,
    dataset_id: str,
    db: AsyncSession
) -> None:
    """
    Require that a user has GPU permission for a specific dataset.

    Raises HTTPException 403 if user does not have permission.

    This should be called in route handlers when:
    - User wants to run AI analysis on a WSI
    - User wants to train a model on a dataset

    Args:
        user: Current user
        dataset_id: Dataset UUID to check permission for
        db: Database session

    Raises:
        HTTPException 403: If user doesn't have GPU permission for this dataset
    """
    has_permission = await check_dataset_gpu_permission(user, dataset_id, db)
    if not has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="GPU operations not available. You need pathologist access or temporary elevated permission for this dataset."
        )



async def _get_user_from_jwt(token: str, db: AsyncSession) -> User:
    """
    Internal helper to decode JWT and get user from database.

    Args:
        token: JWT token string
        db: Database session

    Returns:
        User object if token is valid

    Raises:
        HTTPException 401: If token is invalid or user not found
    """
    try:
        # Decode JWT token
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            audience="fastapi-users:auth"
        )
        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: no user ID"
            )

        # Get user from database
        result = await db.execute(
            select(User).where(User.id == uuid.UUID(user_id))
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User is inactive"
            )

        return user

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid user ID format: {str(e)}"
        )


async def get_user_from_token_param(
    token: Optional[str] = Query(None, description="JWT token for SSE authentication"),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Validate JWT token from query parameter (for SSE streams).

    EventSource API doesn't support custom headers, so token must be passed via URL.
    This function decodes the JWT and retrieves the user from database.

    Args:
        token: JWT token from query parameter
        db: Database session

    Returns:
        User object if token is valid

    Raises:
        HTTPException 401: If token is missing, invalid, or user not found
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    return await _get_user_from_jwt(token, db)


async def get_user_from_header_or_param(
    token: Optional[str] = Query(None, alias="token", description="JWT token for image authentication"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Validate JWT token from Authorization header OR query parameter.

    This is used for endpoints that may be accessed via:
    - fetch() with Authorization header
    - <img src="...?token=..."> tag with query parameter

    Priority: Authorization header > Query parameter

    Args:
        token: JWT token from query parameter
        authorization: Authorization header value
        db: Database session

    Returns:
        User object if token is valid

    Raises:
        HTTPException 401: If no valid token found
    """
    # Try Authorization header first
    jwt_token = None
    if authorization and authorization.startswith("Bearer "):
        jwt_token = authorization[7:]  # Remove "Bearer " prefix
    elif token:
        jwt_token = token

    if not jwt_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    return await _get_user_from_jwt(jwt_token, db)
