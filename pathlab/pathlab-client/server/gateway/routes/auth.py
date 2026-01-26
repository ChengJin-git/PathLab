"""
Authentication Routes for PathLab Client.

Uses FastAPI-Users for email/password authentication with JWT tokens.

Security Features:
- Password is hashed on client-side with SHA-256 + timestamp before transmission
- Timestamp validation prevents replay attacks (5 minute window)
- Server stores bcrypt hash of the password

Endpoints:
- POST /auth/jwt/login - Login with email/password, returns JWT token
- POST /auth/jwt/logout - Logout (client-side token removal)
- POST /auth/secure-login - Secure login with client-side hashed password
- POST /auth/register - Register new user
- GET /auth/me - Get current user info
- PATCH /auth/me - Update current user info
- GET /auth/users - List all users (admin only)
- GET /auth/users/{id} - Get user by ID (admin only)
- PATCH /auth/users/{id} - Update user (admin only)
- DELETE /auth/users/{id} - Delete user (admin only)
"""

import hashlib
import time
from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from pydantic import BaseModel

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
from backend.auth.users import get_jwt_strategy, JWT_SECRET
from ..dependencies import logger


# Application-level salt for client-side hashing (should match frontend)
APP_SALT = "PathLab2024SecureSalt"
# Maximum allowed time difference for timestamp validation (5 minutes)
MAX_TIMESTAMP_DIFF_SECONDS = 300


class SecureLoginRequest(BaseModel):
    """Request body for secure login with client-side hashed password."""
    username: str
    hashed_password: str  # SHA256(SHA256(password) + timestamp + APP_SALT)
    timestamp: int  # Unix timestamp in milliseconds

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

    # Hash password (bcrypt for storage, SHA256 for secure login)
    password_helper = PasswordHelper()
    hashed_password = password_helper.hash(user_create.password)

    # Also store SHA256 hash for secure login verification
    password_sha256 = hashlib.sha256(user_create.password.encode()).hexdigest()

    # Create user
    user = User(
        id=uuid_module.uuid4(),
        email=user_create.email,
        hashed_password=hashed_password,
        password_sha256=password_sha256,  # For secure login
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


# Secure login endpoint with client-side password hashing
@router.post("/auth/secure-login", tags=["Authentication"])
async def secure_login(
    request: SecureLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Secure login with client-side hashed password.

    Security features:
    - Password is never transmitted in plaintext
    - Client sends: SHA256(SHA256(password) + timestamp + APP_SALT)
    - Timestamp validation prevents replay attacks (5 minute window)
    - Rainbow table attacks are mitigated by timestamp + salt

    Request body:
    - username: User's username
    - hashed_password: SHA256(SHA256(password) + timestamp + APP_SALT)
    - timestamp: Unix timestamp in milliseconds when hash was created

    Returns:
    - access_token: JWT token for authentication
    - token_type: "bearer"
    """
    from fastapi_users.password import PasswordHelper

    # Validate timestamp (prevent replay attacks)
    current_time_ms = int(time.time() * 1000)
    time_diff_seconds = abs(current_time_ms - request.timestamp) / 1000

    if time_diff_seconds > MAX_TIMESTAMP_DIFF_SECONDS:
        logger.warning(f"Login attempt with expired timestamp for user {request.username}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOGIN_TIMESTAMP_EXPIRED"
        )

    # Find user by username
    result = await db.execute(select(User).where(User.email == request.username))
    user = result.scalar_one_or_none()

    if not user:
        logger.warning(f"Login attempt for non-existent user: {request.username}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOGIN_BAD_CREDENTIALS"
        )

    # Check if user is active
    if not user.is_active:
        logger.warning(f"Login attempt for inactive user: {request.username}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOGIN_USER_NOT_ACTIVE"
        )

    # Verify password
    # The client sends: SHA256(SHA256(password) + timestamp + APP_SALT)
    # We need to verify by computing the same hash from stored password
    # But we only have bcrypt hash of the password, not the original
    #
    # Solution: We store a "password_hash_sha256" field for secure login verification
    # For now, we'll use a hybrid approach:
    # 1. Client also sends the password hash without timestamp for bcrypt verification
    # 2. The timestamped hash is for transport security
    #
    # Actually, let's use a simpler but still secure approach:
    # The client sends SHA256(password + timestamp + APP_SALT)
    # We verify by checking if bcrypt.verify(password, stored_hash) would work
    # But we can't do that without the original password...
    #
    # Best solution: Store SHA256(password) alongside bcrypt hash
    # Then verify: SHA256(stored_sha256 + timestamp + APP_SALT) == received_hash

    # For backward compatibility, check if user has password_sha256 field
    # If not, fall back to requiring password update

    password_helper = PasswordHelper()

    # Check if we have the SHA256 hash stored (new secure method)
    if hasattr(user, 'password_sha256') and user.password_sha256:
        # Compute expected hash: SHA256(stored_sha256 + timestamp + APP_SALT)
        expected_hash_input = f"{user.password_sha256}{request.timestamp}{APP_SALT}"
        expected_hash = hashlib.sha256(expected_hash_input.encode()).hexdigest()

        if request.hashed_password != expected_hash:
            logger.warning(f"Invalid password for user: {request.username}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="LOGIN_BAD_CREDENTIALS"
            )
    else:
        # Fallback: User doesn't have SHA256 hash stored yet
        # This means they registered before secure login was implemented
        # They need to update their password or use legacy login
        logger.warning(f"User {request.username} needs password migration for secure login")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOGIN_PASSWORD_MIGRATION_REQUIRED"
        )

    # Generate JWT token
    jwt_strategy = get_jwt_strategy()
    token = await jwt_strategy.write_token(user)

    logger.info(f"User {user.email} logged in securely (role={user.role})")

    return {
        "access_token": token,
        "token_type": "bearer"
    }


# Password migration endpoint for legacy users
@router.post("/auth/migrate-password", tags=["Authentication"])
async def migrate_password(
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Migrate a legacy user's password to support secure login.

    This endpoint is for users who registered before secure login was implemented.
    It verifies the password using bcrypt (legacy method) and then stores the
    SHA256 hash for future secure logins.

    After successful migration, the user can use the secure login endpoint.

    Request body (form data):
    - username: User's username
    - password: User's current password (verified with bcrypt)

    Returns:
    - access_token: JWT token for authentication
    - token_type: "bearer"
    """
    from fastapi_users.password import PasswordHelper

    # Find user by username
    result = await db.execute(select(User).where(User.email == username))
    user = result.scalar_one_or_none()

    if not user:
        logger.warning(f"Migration attempt for non-existent user: {username}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOGIN_BAD_CREDENTIALS"
        )

    # Check if user is active
    if not user.is_active:
        logger.warning(f"Migration attempt for inactive user: {username}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOGIN_USER_NOT_ACTIVE"
        )

    # Verify password using bcrypt (legacy method)
    password_helper = PasswordHelper()
    valid, _ = password_helper.verify_and_update(password, user.hashed_password)

    if not valid:
        logger.warning(f"Invalid password during migration for user: {username}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LOGIN_BAD_CREDENTIALS"
        )

    # Store SHA256 hash for secure login
    user.password_sha256 = hashlib.sha256(password.encode()).hexdigest()
    await db.commit()

    logger.info(f"User {user.email} migrated to secure login")

    # Generate JWT token
    jwt_strategy = get_jwt_strategy()
    token = await jwt_strategy.write_token(user)

    return {
        "access_token": token,
        "token_type": "bearer",
        "migrated": True
    }


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
            # Also update SHA256 hash for secure login
            user.password_sha256 = hashlib.sha256(password.encode()).hexdigest()
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

