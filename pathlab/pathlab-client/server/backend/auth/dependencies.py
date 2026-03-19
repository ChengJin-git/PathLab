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
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Query, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt, JWTError

logger = logging.getLogger(__name__)

from .users import current_active_user, JWT_SECRET
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
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return user


async def require_pathologist_or_admin(
    user: User = Depends(current_active_user),
) -> User:
    """
    Dependency that requires the current user to be a pathologist or admin.

    Raises:
        HTTPException 403: If user is neither pathologist nor admin
    """
    if user.role not in {User.ROLE_ADMIN, User.ROLE_PATHOLOGIST}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pathologist or admin access required",
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
            detail="GPU operations not available for guest users. Please contact admin for access.",
        )
    return user


async def get_current_user_id(user: User = Depends(current_active_user)) -> str:
    """
    Get the current user's ID as a string for database queries.

    Use this for data filtering - associating data with users.
    """
    return str(user.id)


async def get_user_id_filter(
    user: User = Depends(current_active_user),
) -> Optional[str]:
    """
    Get user_id filter for data queries based on user role.

    - Admin users: Returns None (can see all data)
    - Other users: Returns user's ID string (can only see their own data)

    Usage:
        @router.get("/items")
        async def list_items(
            user_id_filter: Optional[str] = Depends(get_user_id_filter),
            db: AsyncSession = Depends(get_db)
        ):
            items = await ItemRepository.get_all(db, user_id=user_id_filter)
            ...
    """
    return None if user.is_admin() else str(user.id)


async def get_permitted_dataset_ids(
    user: User, db: AsyncSession
) -> Optional[list[str]]:
    """
    Get dataset IDs the user can access beyond their own data.

    Returns:
        - None for admin users (no restriction needed)
        - List of dataset IDs for non-admin users, combining:
          (a) public datasets (is_public=True)
          (b) datasets with valid temporary elevated permission
    """
    if user.is_admin():
        return None

    from backend.database.repositories import (
        DatasetPermissionRepository,
        DatasetRepository,
        AnnotationCollaboratorRepository,
    )

    permissions = await DatasetPermissionRepository.get_valid_by_user(db, str(user.id))
    permitted_ids = [p.dataset_id for p in permissions if p.is_valid()]
    public_ids = await DatasetRepository.get_public_dataset_ids(db)
    collab_ids = await AnnotationCollaboratorRepository.list_dataset_ids_for_user(
        db, str(user.id)
    )
    return list(set(permitted_ids + public_ids + collab_ids))


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

    # Legacy resources without an owner are not public.
    # They must be explicitly handled via admin access or a narrower permission check.
    if resource_user_id is None:
        return False

    # Check if user owns the resource
    return resource_user_id == str(current_user.id)


async def check_wsi_access_permission(
    user: User,
    wsi_dataset_id: Optional[str],
    wsi_user_id: Optional[str],
    db: AsyncSession,
    *,
    dataset_is_public: bool = False,
) -> bool:
    """
    Check if a user can access a specific WSI.

    Returns True if:
    - User is admin (can access all)
    - Dataset is public (is_public=True)
    - User owns the WSI (wsi_user_id matches)
    - User has valid temporary elevated permission for the WSI's dataset
    - User is an annotation collaborator for the WSI's dataset

    Args:
        user: Current user
        wsi_dataset_id: Dataset UUID the WSI belongs to (can be None)
        wsi_user_id: User ID of the WSI owner (can be None for legacy data)
        db: Database session
        dataset_is_public: Whether the dataset is marked as public

    Returns:
        True if user can access the WSI
    """
    if user.is_admin():
        return True

    if dataset_is_public:
        return True

    if wsi_user_id == str(user.id):
        return True

    if wsi_dataset_id:
        from backend.database.repositories import (
            DatasetPermissionRepository,
            AnnotationCollaboratorRepository,
        )

        if await DatasetPermissionRepository.has_valid_permission(
            db, wsi_dataset_id, str(user.id), "pathologist"
        ):
            return True
        if await AnnotationCollaboratorRepository.exists(
            db, wsi_dataset_id, str(user.id)
        ):
            return True

    return False


async def check_dataset_access_permission(
    user: User,
    dataset_id: str,
    dataset_user_id: Optional[str],
    db: AsyncSession,
    *,
    is_public: bool = False,
) -> bool:
    """
    Check if a user can access a specific dataset.

    Returns True if:
    - User is admin
    - Dataset is public (is_public=True)
    - User owns the dataset
    - User has valid temporary elevated permission for the dataset
    """
    if user.is_admin():
        return True

    if is_public:
        return True

    if check_data_ownership(dataset_user_id, user):
        return True

    from backend.database.repositories import (
        DatasetPermissionRepository,
        AnnotationCollaboratorRepository,
    )

    if await DatasetPermissionRepository.has_valid_permission(
        db, dataset_id, str(user.id), "pathologist"
    ):
        return True

    return await AnnotationCollaboratorRepository.exists(db, dataset_id, str(user.id))


async def get_dataset_with_access(
    dataset_id: str,
    user: User,
    db: AsyncSession,
    *,
    require_owner: bool = False,
    not_found_detail: str = "Dataset not found",
    forbidden_detail: str = "You don't have permission to access this dataset",
):
    """Load a dataset and enforce either owner-only or read access."""
    from backend.database.repositories import DatasetRepository

    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )

    if require_owner:
        has_access = check_data_ownership(dataset.user_id, user)
    else:
        has_access = await check_dataset_access_permission(
            user, dataset_id, dataset.user_id, db, is_public=dataset.is_public
        )

    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=forbidden_detail,
        )

    return dataset


async def get_wsi_with_access(
    wsi_id: str,
    user: User,
    db: AsyncSession,
    *,
    require_owner: bool = False,
    with_dataset: bool = False,
    not_found_detail: str = "WSI not found",
    forbidden_detail: str = "You don't have permission to access this WSI",
):
    """Load a WSI and enforce either owner-only or read access."""
    from backend.database.repositories import WSIRepository

    if with_dataset:
        wsi = await WSIRepository.get_by_id_with_dataset(db, wsi_id)
    else:
        wsi = await WSIRepository.get_by_id(db, wsi_id)

    if not wsi:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )

    if require_owner:
        has_access = check_data_ownership(wsi.user_id, user)
    else:
        dataset_is_public = bool(
            wsi.dataset and getattr(wsi.dataset, "is_public", False)
        )
        has_access = await check_wsi_access_permission(
            user,
            wsi.dataset_id,
            wsi.user_id,
            db,
            dataset_is_public=dataset_is_public,
        )

    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=forbidden_detail,
        )

    return wsi


async def check_task_access_permission(
    user: User,
    task_user_id: Optional[str],
    task_dataset_id: Optional[str],
    db: AsyncSession,
) -> bool:
    """
    Check if a user can access a specific training task (READ operations).

    Returns True if:
    - User is admin (can access all)
    - User owns the task (task_user_id matches)

    Args:
        user: Current user
        task_user_id: User ID of the task owner (can be None for legacy data)
        task_dataset_id: Unused for read access; kept for signature compatibility
        db: Unused for read access; kept for signature compatibility

    Returns:
        True if user can access the task
    """
    # Admin can access everything
    if user.is_admin():
        return True

    # Check if user owns the task
    if task_user_id == str(user.id):
        return True

    return False


async def check_dataset_gpu_permission(
    user: User, dataset_id: str, db: AsyncSession
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
    user: User, dataset_id: str, db: AsyncSession
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
            detail="GPU operations not available. You need pathologist access or temporary elevated permission for this dataset.",
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
            token, JWT_SECRET, algorithms=["HS256"], audience="fastapi-users:auth"
        )
        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: no user ID",
            )

        # Get user from database
        result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive"
            )

        # Single-device login enforcement: check session_nonce
        jwt_nonce = payload.get("sn")
        if not jwt_nonce:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired. Please login again.",
            )
        db_nonce = getattr(user, "session_nonce", None)
        if jwt_nonce != db_nonce:
            logger.info(
                f"[Auth] Rejected stale token for user {user.id}: session nonce mismatch"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired. Please login again.",
            )

        return user

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {str(e)}"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid user ID format: {str(e)}",
        )


async def get_user_from_token_param(
    token: Optional[str] = Query(None, description="JWT token for SSE authentication"),
    db: AsyncSession = Depends(get_db),
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
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return await _get_user_from_jwt(token, db)


async def get_user_from_header_or_param(
    token: Optional[str] = Query(
        None, alias="token", description="JWT token for image authentication"
    ),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
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
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    return await _get_user_from_jwt(jwt_token, db)
