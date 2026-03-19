"""
Authentication Routes for PathLab Client.

Uses FastAPI-Users for email/password authentication with JWT tokens.

Security Features:
- Password is hashed on client-side with SHA-256 + timestamp before transmission
- Timestamp validation prevents replay attacks (5 minute window)
- Server stores bcrypt hash of the password

Endpoints:
- POST /auth/jwt/login - DISABLED (blocked to prevent Turnstile bypass)
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
import os
import shutil
import httpx
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from pydantic import BaseModel, Field

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
from backend.auth.schemas import UserReadAdmin, AdminUserUpdate
from backend.auth.users import get_jwt_strategy
from backend.common.config import Config
from ..dependencies import logger


APP_SALT: str = os.getenv("APP_SALT", "PathLab2024SecureSalt")

# ============================================================================
# Educational Email Validation
# ============================================================================

import re as _re
import json as _json
from pathlib import Path as _Path
from functools import lru_cache as _lru_cache


@_lru_cache(maxsize=1)
def _load_university_domains() -> frozenset:
    data_file = (
        _Path(__file__).parent.parent.parent
        / "backend"
        / "auth"
        / "university_domains.json"
    )
    if data_file.exists():
        return frozenset(_json.loads(data_file.read_text()))
    return frozenset()


def is_educational_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.strip().lower().rsplit("@", 1)[-1]
    if not domain or "." not in domain:
        return False

    known = _load_university_domains()

    if known:
        if domain in known:
            return True
        parts = domain.split(".")
        for i in range(1, len(parts) - 1):
            if ".".join(parts[i:]) in known:
                return True

    _FALLBACK = [
        r"\.edu$",
        r"\.edu\.[a-z]{2,6}$",
        r"\.ac\.[a-z]{2,6}$",
    ]
    return any(_re.search(pat, domain) for pat in _FALLBACK)


class AccessRequest(BaseModel):
    """Request body for public self-registration (access request)."""

    username: str = Field(description="Desired username (stored in email field)")
    password: str = Field(description="Account password")
    registration_email: str = Field(
        description="Educational email for identity verification"
    )
    nickname: Optional[str] = Field(default=None, description="Display name")


_LEGAL_FOOTER_HTML = (
    "<hr style='border:none;border-top:1px solid #e0e0e0;margin:32px 0 16px'>"
    "<p style='font-size:11px;color:#999;line-height:1.6;font-family:Arial,sans-serif;'>"
    "This message contains confidential information intended for a specific individual "
    "and purpose. If you are not the intended recipient, you should delete this message "
    "and notify the sender, "
    "<a href='https://smartlab.cse.ust.hk/' style='color:#999;'>SmartLab</a>, "
    "and The Hong Kong University of Science and Technology (the University) immediately. "
    "Any disclosure, copying, or distribution of this message, or the taking of any action "
    "based on it, is strictly prohibited and may be unlawful.<br><br>"
    "SmartLab and the University specifically deny any responsibility for the accuracy or "
    "quality of information obtained through University E-mail Facilities. Any views and "
    "opinions expressed are only those of the author(s) and do not necessarily represent "
    "those of SmartLab or the University, and neither SmartLab nor the University accepts "
    "liability whatsoever for any losses or damages incurred or caused to any party as a "
    "result of the use of such information."
    "</p>"
)


async def _send_activation_email(user: "User") -> None:
    settings = Config.get_global_settings()
    if not settings.get("resend_enabled") or not settings.get("resend_api_key"):
        return
    if not user.registration_email:
        return

    try:
        import resend as _resend

        _resend.api_key = settings["resend_api_key"]
        from_addr = settings.get("resend_from_email") or "PathLab <noreply@resend.dev>"
        display_name = user.nickname or user.email
        html_body = (
            "<div style='font-family:Arial,sans-serif;max-width:600px;margin:0 auto;'>"
            f"<p>Dear {display_name},</p>"
            f"<p>Your PathLab account <strong>{user.email}</strong> has been activated "
            "by an administrator. You can now log in to the platform.</p>"
            "<p>If you have any questions, please contact your system administrator.</p>"
            "<p style='color:#555;'>\u2014 PathLab \u00b7 "
            "<a href='https://smartlab.cse.ust.hk/' style='color:#555;'>SmartLab</a>, HKUST</p>"
            + _LEGAL_FOOTER_HTML
            + "</div>"
        )
        _resend.Emails.send(
            {
                "from": from_addr,
                "to": [user.registration_email],
                "subject": "Your PathLab account has been activated",
                "html": html_body,
            }
        )
        logger.info(
            f"Activation email sent to {user.registration_email} for user {user.email}"
        )
    except Exception as exc:
        logger.warning(
            f"Failed to send activation email to {user.registration_email}: {exc}"
        )

async def verify_turnstile(token: str, secret_key: str) -> bool:
    """
    Verify Cloudflare Turnstile token with Cloudflare API.

    Args:
        token: Turnstile token from client
        secret_key: Turnstile secret key

    Returns:
        True if verification successful, False otherwise
    """
    if not token or not secret_key:
        return False

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={
                    "secret": secret_key,
                    "response": token,
                },
                timeout=10.0,
            )

            if response.status_code != 200:
                logger.warning(
                    f"Turnstile verification failed with status {response.status_code}"
                )
                return False

            result = response.json()
            success = result.get("success", False)

            if not success:
                error_codes = result.get("error-codes", [])
                logger.warning(f"Turnstile verification failed: {error_codes}")

            return success

    except Exception as e:
        logger.error(f"Turnstile verification error: {e}")
        return False


class SecureLoginRequest(BaseModel):
    """Request body for secure login with client-side hashed password."""

    username: str
    hashed_password: str  # SHA256(SHA256(password) + timestamp + APP_SALT)
    timestamp: int  # Unix timestamp in milliseconds
    turnstile_token: Optional[str] = None  # Cloudflare Turnstile token (optional)


class PaginatedUserListResponse(BaseModel):
    """Paginated admin user list response."""

    items: List[UserReadAdmin]
    total: int
    page: int
    page_size: int


# Create main auth router
router = APIRouter(tags=["Authentication"])


# Include FastAPI-Users auth routes (/auth/jwt/login disabled via config, /auth/jwt/logout active)
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
    Register a new non-admin user.

    Unlike the default FastAPI-Users register, this allows non-email usernames.
    Public registration cannot create admin or superuser accounts.
    """
    from fastapi_users.password import PasswordHelper
    import uuid as uuid_module

    # Check if username already exists
    result = await db.execute(select(User).where(User.email == user_create.email))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="REGISTER_USER_ALREADY_EXISTS",
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
        is_active=True,
        is_superuser=False,
        is_verified=True,  # Auto-verify since we don't use email verification
        role=user_create.role or "guest",
        nickname=user_create.nickname,
    )

    # Race-condition safe: catch IntegrityError if concurrent registration
    # with same email passes the existence check above (PostgreSQL READ COMMITTED)
    try:
        db.add(user)
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="REGISTER_USER_ALREADY_EXISTS",
        )

    logger.info(f"New user registered: {user.email} (role={user.role})")
    return user


@router.post("/auth/request-access", response_model=UserRead, tags=["Authentication"])
async def request_access(
    request: AccessRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Public self-registration — submit an account access request.

    - Requires an educational email address for identity proof.
    - The created account is **inactive** until an admin reviews and activates it.
    - Username must be unique.
    """
    from fastapi_users.password import PasswordHelper
    import uuid as uuid_module

    # Validate educational email
    if not is_educational_email(request.registration_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="REGISTRATION_EMAIL_NOT_EDUCATIONAL",
        )

    # Normalise inputs
    username = request.username.strip()
    reg_email = request.registration_email.strip().lower()

    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="REGISTER_USERNAME_EMPTY",
        )
    if len(request.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="REGISTER_PASSWORD_TOO_SHORT",
        )

    # Check username uniqueness
    result = await db.execute(select(User).where(User.email == username))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="REGISTER_USER_ALREADY_EXISTS",
        )

    # Hash password
    password_helper = PasswordHelper()
    hashed_password = password_helper.hash(request.password)
    password_sha256 = hashlib.sha256(request.password.encode()).hexdigest()

    user = User(
        id=uuid_module.uuid4(),
        email=username,  # username stored in email field
        hashed_password=hashed_password,
        password_sha256=password_sha256,
        is_active=False,  # inactive until admin approves
        is_superuser=False,
        is_verified=True,
        role="guest",
        nickname=request.nickname,
        registration_email=reg_email,
    )

    try:
        db.add(user)
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="REGISTER_USER_ALREADY_EXISTS",
        )

    logger.info(
        f"Access request submitted: username={user.email}, "
        f"registration_email={user.registration_email}"
    )
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
    # Verify Cloudflare Turnstile if enabled
    settings = Config.get_global_settings()
    turnstile_enabled = settings.get("turnstile_enabled", False)
    turnstile_secret_key = settings.get("turnstile_secret_key", "")

    if turnstile_enabled and turnstile_secret_key:
        if not request.turnstile_token:
            logger.warning(
                f"Login attempt without Turnstile token for user {request.username}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TURNSTILE_TOKEN_REQUIRED",
            )

        # Verify Turnstile token
        turnstile_valid = await verify_turnstile(
            request.turnstile_token, turnstile_secret_key
        )
        if not turnstile_valid:
            logger.warning(
                f"Login attempt with invalid Turnstile token for user {request.username}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TURNSTILE_VERIFICATION_FAILED",
            )

    # Validate timestamp (prevent replay attacks)
    current_time_ms = int(time.time() * 1000)
    time_diff_seconds = abs(current_time_ms - request.timestamp) / 1000

    if time_diff_seconds > Config.MAX_TIMESTAMP_DIFF_SECONDS:
        logger.warning(
            f"Login attempt with expired timestamp for user {request.username}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="LOGIN_TIMESTAMP_EXPIRED"
        )

    # Find user by username
    result = await db.execute(select(User).where(User.email == request.username))
    user = result.scalar_one_or_none()

    if not user:
        logger.warning(f"Login attempt for non-existent user: {request.username}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="LOGIN_BAD_CREDENTIALS"
        )

    # Check maintenance mode - only admin can log in during maintenance
    if Config.get_maintenance_mode() and user.role != "admin":
        logger.warning(
            f"Login attempt during maintenance mode for non-admin user: {request.username}"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="MAINTENANCE_MODE"
        )

    # Check if user is active
    if not user.is_active:
        logger.warning(f"Login attempt for inactive user: {request.username}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="LOGIN_USER_NOT_ACTIVE"
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

    # Verify password hash
    if not user.password_sha256:
        logger.warning(f"User {request.username} has no password hash")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="LOGIN_BAD_CREDENTIALS"
        )

    # Compute expected hash: SHA256(stored_sha256 + timestamp + APP_SALT)
    expected_hash_input = f"{user.password_sha256}{request.timestamp}{APP_SALT}"
    expected_hash = hashlib.sha256(expected_hash_input.encode()).hexdigest()

    if request.hashed_password != expected_hash:
        logger.warning(f"Invalid password for user: {request.username}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="LOGIN_BAD_CREDENTIALS"
        )

    # Generate JWT token
    jwt_strategy = get_jwt_strategy()
    token = await jwt_strategy.write_token(user)

    logger.info(f"User {user.email} logged in securely (role={user.role})")

    return {"access_token": token, "token_type": "bearer"}


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


@router.get(
    "/auth/users/paged",
    response_model=PaginatedUserListResponse,
    tags=["User Management"],
)
async def list_users_paged(
    search: Optional[str] = Query(None, description="Search username or nickname"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(10, ge=1, le=100, description="Users per page"),
    exclude_admin: bool = Query(
        False, description="Exclude admin users from the result"
    ),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List users with pagination and optional search."""
    filters = []
    normalized_search = (search or "").strip()

    if exclude_admin:
        filters.append(User.role != "admin")

    if normalized_search:
        pattern = f"%{normalized_search}%"
        filters.append(
            or_(
                User.email.ilike(pattern),
                User.nickname.ilike(pattern),
            )
        )

    count_stmt = select(func.count()).select_from(User)
    query_stmt = select(User)
    if filters:
        count_stmt = count_stmt.where(*filters)
        query_stmt = query_stmt.where(*filters)

    total = (await db.execute(count_stmt)).scalar_one()
    offset = (page - 1) * page_size
    users = (
        (
            await db.execute(
                query_stmt.order_by(User.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    logger.info(
        f"Admin {admin.email} listed {len(users)} users "
        f"(paged, page={page}, page_size={page_size}, "
        f"search={normalized_search or None}, exclude_admin={exclude_admin})"
    )
    return {
        "items": users,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get(
    "/auth/users/{user_id}", response_model=UserReadAdmin, tags=["User Management"]
)
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


@router.patch(
    "/auth/users/{user_id}", response_model=UserReadAdmin, tags=["User Management"]
)
async def update_user(
    user_id: str,
    user_update: AdminUserUpdate,
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

    was_active = user.is_active

    # Update fields
    update_data = user_update.model_dump(exclude_unset=True)

    # Handle password separately - needs to be hashed
    if "password" in update_data:
        password = update_data.pop("password")
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
    if not was_active and user.is_active:
        await _send_activation_email(user)
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
        admin_count_result = await db.execute(select(User).where(User.role == "admin"))
        admin_count = len(admin_count_result.scalars().all())
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin")

    await db.delete(user)
    await db.commit()

    logger.info(f"Admin {admin.email} deleted user {user.email}")
    return {"success": True, "message": f"User {user.email} deleted"}


# Agreement acceptance endpoints
class AcceptAgreementRequest(BaseModel):
    """Request body for accepting the agreement."""

    ip: Optional[str] = Field(
        default=None, description="Client IP address when accepting the agreement"
    )


@router.post("/auth/accept-agreement", response_model=UserRead, tags=["Authentication"])
async def accept_agreement(
    request: AcceptAgreementRequest = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept the terms of service agreement.

    Records the current timestamp and client IP when user accepts the agreement.
    Must be called after first login before accessing the system.
    """
    from datetime import datetime, timezone

    # Use naive UTC datetime for PostgreSQL TIMESTAMP WITHOUT TIME ZONE compatibility
    user.agreement_accepted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if request and request.ip:
        user.agreement_ip = request.ip
    await db.commit()
    await db.refresh(user)

    logger.info(
        f"User {user.email} accepted the agreement from IP: {request.ip if request else 'unknown'}"
    )
    return user


@router.post(
    "/auth/users/{user_id}/revoke-agreement",
    response_model=UserReadAdmin,
    tags=["User Management"],
)
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
    user.agreement_ip = None
    await db.commit()
    await db.refresh(user)

    logger.info(f"Admin {admin.email} revoked agreement for user {user.email}")
    return user


# ============================================================================
# Batch User Operations (Admin only)
# ============================================================================


class BatchUserIdsRequest(BaseModel):
    """Request model for batch user operations."""

    user_ids: List[str]


@router.post("/auth/users/batch/activate", tags=["User Management"])
async def batch_activate_users(
    request: BatchUserIdsRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Batch activate multiple users (admin only).
    Admin users and the current admin cannot be modified.
    """
    import uuid

    updated = 0
    activated_users = []
    for user_id in request.user_ids:
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            continue  # Skip invalid UUIDs

        result = await db.execute(select(User).where(User.id == user_uuid))
        user = result.scalar_one_or_none()

        if user and user.role != "admin" and user.id != admin.id:
            if not user.is_active:
                activated_users.append(user)
            user.is_active = True
            updated += 1

    await db.commit()
    logger.info(f"Admin {admin.email} batch activated {updated} users")
    for _u in activated_users:
        await _send_activation_email(_u)
    return {"updated": updated}


@router.post("/auth/users/batch/deactivate", tags=["User Management"])
async def batch_deactivate_users(
    request: BatchUserIdsRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Batch deactivate multiple users (admin only).
    Admin users and the current admin cannot be modified.
    """
    import uuid

    updated = 0
    for user_id in request.user_ids:
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            continue

        result = await db.execute(select(User).where(User.id == user_uuid))
        user = result.scalar_one_or_none()

        if user and user.role != "admin" and user.id != admin.id:
            user.is_active = False
            updated += 1

    await db.commit()
    logger.info(f"Admin {admin.email} batch deactivated {updated} users")
    return {"updated": updated}


@router.post("/auth/users/batch/delete", tags=["User Management"])
async def batch_delete_users(
    request: BatchUserIdsRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Batch delete multiple users (admin only).
    Admin users and the current admin cannot be deleted.
    """
    import uuid

    deleted = 0
    for user_id in request.user_ids:
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            continue

        result = await db.execute(select(User).where(User.id == user_uuid))
        user = result.scalar_one_or_none()

        if user and user.role != "admin" and user.id != admin.id:
            await db.delete(user)
            deleted += 1

    await db.commit()
    logger.info(f"Admin {admin.email} batch deleted {deleted} users")
    return {"deleted": deleted}


# ============================================================================
# Maintenance Mode (Admin only)
# ============================================================================


class MaintenanceModeRequest(BaseModel):
    """Request model for setting maintenance mode."""

    enabled: bool


@router.get("/auth/maintenance-mode", tags=["User Management"])
async def get_maintenance_mode():
    """
    Get current maintenance mode status.
    Available to authenticated users.
    """
    enabled = Config.get_maintenance_mode()
    return {"enabled": enabled}


@router.post("/auth/maintenance-mode", tags=["User Management"])
async def set_maintenance_mode(
    request: MaintenanceModeRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Set maintenance mode (admin only).
    When enabled, all non-admin users are deactivated and cannot log in.
    When disabled, users that were active before maintenance are restored.
    """
    previous_enabled = Config.get_maintenance_mode()

    affected_users = 0

    if request.enabled:
        if previous_enabled:
            logger.info(
                f"Admin {admin.email} requested maintenance mode enable, but it is already enabled"
            )
            return {"enabled": True, "affected_users": 0}

        # Deactivate all non-admin users
        result = await db.execute(select(User).where(User.role != "admin"))
        users = result.scalars().all()
        restore_user_ids: list[str] = []

        for user in users:
            if user.is_active:
                restore_user_ids.append(str(user.id))
                user.is_active = False
                affected_users += 1

        Config.set_maintenance_mode_state(True, restore_user_ids)
        await db.commit()
        logger.info(
            f"Admin {admin.email} enabled maintenance mode, deactivated {affected_users} users"
        )
    else:
        if not previous_enabled:
            Config.set_maintenance_mode_state(False, [])
            logger.info(
                f"Admin {admin.email} requested maintenance mode disable, but it is already disabled"
            )
            return {"enabled": False, "affected_users": 0}

        import uuid

        restore_user_ids = Config.get_maintenance_mode_restore_user_ids()
        restore_user_uuids = []

        for user_id in restore_user_ids:
            try:
                restore_user_uuids.append(uuid.UUID(user_id))
            except (TypeError, ValueError):
                logger.warning(
                    f"Skipping invalid maintenance restore user id: {user_id}"
                )

        if restore_user_uuids:
            result = await db.execute(
                select(User).where(
                    User.role != "admin",
                    User.id.in_(restore_user_uuids),
                )
            )
            users = result.scalars().all()
            for user in users:
                if not user.is_active:
                    user.is_active = True
                    affected_users += 1

        await db.commit()
        Config.set_maintenance_mode_state(False, [])
        logger.info(
            f"Admin {admin.email} disabled maintenance mode, restored {affected_users} users"
        )

    return {"enabled": request.enabled, "affected_users": affected_users}


# ============================================================================
# Maintenance Notice (Announcement for non-admin users)
# ============================================================================


class MaintenanceNoticeRequest(BaseModel):
    """Request model for setting maintenance notice."""

    message: Optional[str] = Field(
        default=None, description="Notice message. Empty or null to clear."
    )


@router.get("/auth/maintenance-notice/public", tags=["User Management"])
async def get_maintenance_notice_public():
    """
    Get current maintenance notice without authentication.
    Used to display announcements on the login page before users log in.
    Also supports clients caching the notice for offline/unreachable scenarios.
    """
    notice = Config.get_maintenance_notice()
    if not notice:
        return {"active": False, "message": None}
    return {
        "active": True,
        "message": notice.get("message"),
        "updated_at": notice.get("updated_at"),
    }


@router.get("/auth/maintenance-notice", tags=["User Management"])
async def get_maintenance_notice(
    user: User = Depends(current_active_user),
):
    """
    Get current maintenance notice and whether current user needs to acknowledge it.
    Admin users never need to acknowledge.
    """
    notice = Config.get_maintenance_notice()
    if not notice:
        return {"active": False, "message": None, "needs_acknowledgment": False}

    # Admin users never need to acknowledge
    needs_ack = False
    if user.role != "admin":
        notice_time = notice.get("updated_at")
        if notice_time:
            from datetime import datetime, timezone

            notice_dt = datetime.fromisoformat(notice_time)
            if notice_dt.tzinfo is None:
                notice_dt = notice_dt.replace(tzinfo=timezone.utc)
            # Compare with user's last acknowledgment
            if user.notice_acknowledged_at is None:
                needs_ack = True
            else:
                user_ack = user.notice_acknowledged_at
                if user_ack.tzinfo is None:
                    user_ack = user_ack.replace(tzinfo=timezone.utc)
                needs_ack = notice_dt > user_ack

    return {
        "active": True,
        "message": notice.get("message"),
        "updated_at": notice.get("updated_at"),
        "needs_acknowledgment": needs_ack,
    }


@router.post("/auth/maintenance-notice", tags=["User Management"])
async def set_maintenance_notice(
    request: MaintenanceNoticeRequest,
    admin: User = Depends(require_admin),
):
    """
    Set or clear maintenance notice (admin only).
    When set, non-admin users will see a modal they must acknowledge.
    Send null/empty message to clear the notice.
    """
    result = Config.set_maintenance_notice(request.message)
    if result:
        logger.info(
            f"Admin {admin.email} set maintenance notice: {request.message[:50]}..."
        )
        return {
            "active": True,
            "message": result["message"],
            "updated_at": result["updated_at"],
        }
    else:
        logger.info(f"Admin {admin.email} cleared maintenance notice")
        return {"active": False, "message": None}


@router.post(
    "/auth/acknowledge-notice", response_model=UserRead, tags=["Authentication"]
)
async def acknowledge_notice(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Acknowledge the current maintenance notice.
    Records the current timestamp so the user won't see the same notice again.
    """
    from datetime import datetime, timezone

    user.notice_acknowledged_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(user)
    logger.info(f"User {user.email} acknowledged maintenance notice")
    if user.avatar_path:
        user.avatar_url = (
            f"/avatars/{user.avatar_path}?t={int(user.updated_at.timestamp())}"
        )
    return user


# ============================================================================
# Self-service Password Change
# ============================================================================


class ChangePasswordRequest(BaseModel):
    current_password_sha256: str
    new_password_sha256: str


@router.post(
    "/auth/me/change-password",
    response_model=UserRead,
    tags=["Authentication"],
)
async def change_my_password(
    request: ChangePasswordRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    from fastapi_users.password import PasswordHelper

    if not user.password_sha256:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CHANGE_PASSWORD_NOT_SUPPORTED",
        )

    if request.current_password_sha256 != user.password_sha256:
        logger.warning(f"User {user.email} provided incorrect current password")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CURRENT_PASSWORD_INCORRECT",
        )

    password_helper = PasswordHelper()
    user.hashed_password = password_helper.hash(request.new_password_sha256)
    user.password_sha256 = request.new_password_sha256

    await db.commit()
    await db.refresh(user)

    if user.avatar_path:
        user.avatar_url = (
            f"/avatars/{user.avatar_path}?t={int(user.updated_at.timestamp())}"
        )

    logger.info(f"User {user.email} changed their own password")
    return user


# Avatar management routes
@router.get("/auth/me", response_model=UserRead, tags=["Authentication"])
async def get_me(user: User = Depends(current_active_user)):
    """
    Get current user info with populated avatar_url.
    """
    if user.avatar_path:
        user.avatar_url = (
            f"/avatars/{user.avatar_path}?t={int(user.updated_at.timestamp())}"
        )
    return user


@router.post("/auth/avatar", response_model=UserRead, tags=["Authentication"])
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a new avatar for the current user.
    """
    # Validate file type
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    # Get file extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
        raise HTTPException(status_code=400, detail="Unsupported image format")

    # Limit file size to 2MB
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image file too large (max 2MB)")
    await file.seek(0)

    # Create filename: user_id + extension
    filename = f"{user.id}{ext}"
    avatar_dir = Config.get_uploads_dir() / "avatars"
    avatar_path = avatar_dir / filename

    # Delete existing avatar if different extension
    if user.avatar_path and user.avatar_path != filename:
        old_path = avatar_dir / user.avatar_path
        if old_path.exists():
            old_path.unlink()

    # Save file
    Config.ensure_directories()  # Ensure avatars dir exists
    with open(avatar_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Update user record
    user.avatar_path = filename
    await db.commit()
    await db.refresh(user)

    # Populate avatar_url for response
    user.avatar_url = f"/avatars/{filename}?t={int(user.updated_at.timestamp())}"

    logger.info(f"User {user.email} uploaded a new avatar")
    return user


@router.delete("/auth/avatar", response_model=UserRead, tags=["Authentication"])
async def delete_avatar(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete the current user's avatar.
    """
    if user.avatar_path:
        avatar_dir = Config.get_uploads_dir() / "avatars"
        avatar_path = avatar_dir / user.avatar_path
        if avatar_path.exists():
            try:
                avatar_path.unlink()
            except Exception as e:
                logger.error(f"Failed to delete avatar file {avatar_path}: {e}")

        user.avatar_path = None
        await db.commit()
        await db.refresh(user)

    logger.info(f"User {user.email} deleted their avatar")
    return user


# Include user management routes for current user
# GET /auth/me - Get current user (OVERRIDDEN ABOVE)
# PATCH /auth/me - Update current user
# DELETE /auth/me - Delete current user (disabled by default)
# NOTE: This must be included AFTER custom /auth/users endpoints to avoid route collision
# (/auth/{id} would match /auth/users if included first)
router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/auth",
)
