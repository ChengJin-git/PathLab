"""
Local Authentication Routes for PathLab Client.

Uses FastAPI-Users for local email/password authentication with JWT tokens.
Replaces the previous Casdoor OAuth-based authentication.

Endpoints:
- POST /auth/jwt/login - Login with email/password, returns JWT token
- POST /auth/jwt/logout - Logout (client-side token removal)
- POST /auth/register - Register new user
- GET /auth/me - Get current user info
- PATCH /auth/me - Update current user info
- GET /auth/users - List all users (admin only)
- GET /auth/users/{id} - Get user by ID (admin only)
- PATCH /auth/users/{id} - Update user (admin only)
- DELETE /auth/users/{id} - Delete user (admin only)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from backend.database import get_db
from backend.auth import (
    fastapi_users,
    auth_backend,
    current_active_user,
    User,
    UserRead,
    UserCreate,
    UserUpdate,
    require_admin,
)
from backend.auth.schemas import UserReadAdmin
from ..dependencies import logger

# Create main auth router
router = APIRouter(tags=["Authentication"])

# Include FastAPI-Users auth routes
# POST /auth/jwt/login - Login
# POST /auth/jwt/logout - Logout
router.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
)

# Custom register endpoint (replaces FastAPI-Users default to allow non-email usernames)
@router.post("/auth/register", response_model=UserRead, tags=["Authentication"])
async def register_user(
    user_create: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new user.

    Unlike the default FastAPI-Users register, this allows non-email usernames.
    """
    from fastapi_users.password import PasswordHelper
    import uuid as uuid_module

    # Check if username already exists
    result = await db.execute(select(User).where(User.email == user_create.email))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="REGISTER_USER_ALREADY_EXISTS"
        )

    # Hash password
    password_helper = PasswordHelper()
    hashed_password = password_helper.hash(user_create.password)

    # Create user
    user = User(
        id=uuid_module.uuid4(),
        email=user_create.email,
        hashed_password=hashed_password,
        is_active=user_create.is_active if user_create.is_active is not None else True,
        is_superuser=user_create.is_superuser if user_create.is_superuser is not None else False,
        is_verified=True,  # Auto-verify since we don't use email verification
        role=user_create.role or "guest",
        nickname=user_create.nickname,
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info(f"New user registered: {user.email} (role={user.role})")
    return user


# Custom endpoints for admin user management
@router.get("/auth/users", response_model=List[UserReadAdmin], tags=["User Management"])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    List all users (admin only).
    
    Returns all users with their roles and status.
    """
    result = await db.execute(
        select(User).offset(skip).limit(limit).order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    logger.info(f"Admin {admin.email} listed {len(users)} users")
    return users


@router.get("/auth/users/{user_id}", response_model=UserReadAdmin, tags=["User Management"])
async def get_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a specific user by ID (admin only).
    """
    import uuid
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    
    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return user


@router.patch("/auth/users/{user_id}", response_model=UserReadAdmin, tags=["User Management"])
async def update_user(
    user_id: str,
    user_update: UserUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a user (admin only).

    Admins can update any user's role, nickname, password, and status.
    """
    import uuid
    from fastapi_users.password import PasswordHelper

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update fields
    update_data = user_update.model_dump(exclude_unset=True)

    # Handle password separately - needs to be hashed
    if 'password' in update_data:
        password = update_data.pop('password')
        if password:  # Only update if not empty
            password_helper = PasswordHelper()
            user.hashed_password = password_helper.hash(password)
            logger.info(f"Admin {admin.email} changed password for user {user.email}")

    # Update other fields
    for field, value in update_data.items():
        if hasattr(user, field) and value is not None:
            setattr(user, field, value)

    await db.commit()
    await db.refresh(user)

    logger.info(f"Admin {admin.email} updated user {user.email}")
    return user


@router.delete("/auth/users/{user_id}", tags=["User Management"])
async def delete_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a user (admin only).

    Cannot delete yourself or the last admin.
    """
    import uuid
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    # Cannot delete yourself
    if user_uuid == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if this is the last admin
    if user.role == "admin":
        admin_count_result = await db.execute(
            select(User).where(User.role == "admin")
        )
        admin_count = len(admin_count_result.scalars().all())
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin")

    await db.delete(user)
    await db.commit()

    logger.info(f"Admin {admin.email} deleted user {user.email}")
    return {"success": True, "message": f"User {user.email} deleted"}


# Agreement acceptance endpoints
@router.post("/auth/accept-agreement", response_model=UserRead, tags=["Authentication"])
async def accept_agreement(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept the terms of service agreement.

    Records the current timestamp when user accepts the agreement.
    Must be called after first login before accessing the system.
    """
    from datetime import datetime, timezone

    user.agreement_accepted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    logger.info(f"User {user.email} accepted the agreement")
    return user


@router.post("/auth/users/{user_id}/revoke-agreement", response_model=UserReadAdmin, tags=["User Management"])
async def revoke_user_agreement(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Revoke a user's agreement acceptance (admin only).

    This will require the user to accept the agreement again on next login.
    """
    import uuid
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.agreement_accepted_at = None
    await db.commit()
    await db.refresh(user)

    logger.info(f"Admin {admin.email} revoked agreement for user {user.email}")
    return user


# Include user management routes for current user
# GET /auth/me - Get current user
# PATCH /auth/me - Update current user
# DELETE /auth/me - Delete current user (disabled by default)
# NOTE: This must be included AFTER custom /auth/users endpoints to avoid route collision
# (/auth/{id} would match /auth/users if included first)
router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/auth",
)

