"""
FastAPI-Users Configuration

Sets up:
- User Manager with custom logic
- JWT Authentication Backend (with single-device login enforcement)
- FastAPI-Users instance with all routers
"""

import os
import uuid
import logging
from typing import Optional

import jwt as pyjwt
from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, exceptions, models
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users.jwt import generate_jwt, decode_jwt
from fastapi_users.manager import BaseUserManager as BaseUserManagerType
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.database import get_db, async_session as db_session_factory
from backend.common.config import Config
from .models import User

logger = logging.getLogger(__name__)


def _contact_email_log_part(user: User) -> str:
    contact = getattr(user, "email", None)
    return f", contact_email={contact}" if contact else ""


# Secret key for JWT tokens - use environment variable or generate a random secret
_jwt_secret_env = os.getenv("JWT_SECRET")
if _jwt_secret_env:
    JWT_SECRET = _jwt_secret_env
else:
    import secrets

    JWT_SECRET = secrets.token_urlsafe(64)
    logger.warning(
        "JWT_SECRET not set in environment — generated a random secret. "
        "Sessions will be invalidated on server restart. "
        "Set JWT_SECRET environment variable for persistent sessions."
    )


async def get_user_db(session: AsyncSession = Depends(get_db)):
    """Dependency to get user database adapter."""
    yield SQLAlchemyUserDatabase[User, uuid.UUID](session, User)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """
    Custom User Manager with PathLab-specific logic.

    Handles:
    - User registration hooks
    - Password reset tokens
    - Email verification tokens
    """

    reset_password_token_secret = JWT_SECRET
    verification_token_secret = JWT_SECRET

    async def on_after_register(self, user: User, request: Optional[Request] = None):
        logger.info(
            f"User {user.username} (id={user.id}) has registered with "
            f"role={user.role}{_contact_email_log_part(user)}"
        )

        # Auto-verify user (no email verification required)
        # This is done in the database directly since we don't have session here
        user.is_verified = True
        await self.user_db.update(user, {"is_verified": True})

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None
    ):
        logger.info(
            f"User {user.username} requested password reset. "
            f"Token: {token[:8]}...{_contact_email_log_part(user)}"
        )

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None
    ):
        logger.info(
            f"User {user.username} requested verification. "
            f"Token: {token[:8]}...{_contact_email_log_part(user)}"
        )

    async def on_after_login(
        self, user: User, request: Optional[Request] = None, response=None
    ):
        logger.info(
            f"User {user.username} (role={user.role}) logged in"
            f"{_contact_email_log_part(user)}"
        )


async def get_user_manager(user_db: SQLAlchemyUserDatabase[User, uuid.UUID] = Depends(get_user_db)):
    """Dependency to get user manager."""
    yield UserManager(user_db)


# JWT Transport - Bearer token in Authorization header
# tokenUrl points to the secure login endpoint (the legacy /auth/jwt/login is disabled)
bearer_transport = BearerTransport(tokenUrl="auth/secure-login")


# Maximum number of concurrent sessions (devices) allowed per user.
# To change the limit, update this single constant — no other code changes needed.
MAX_CONCURRENT_SESSIONS = 2


class SingleSessionJWTStrategy(JWTStrategy[User, uuid.UUID]):
    """
    Custom JWT strategy that enforces multi-device login with a configurable session limit.

    On each login (write_token), a new random nonce is generated and appended to the
    user's active nonces list (JSON array). If the list exceeds MAX_CONCURRENT_SESSIONS,
    the oldest nonce is evicted, ending that session.
    On each request (read_token), the JWT's nonce must be present in the active nonces list.
    """

    async def write_token(self, user: User) -> str:
        """Generate JWT with a fresh nonce; evict oldest session if limit is exceeded."""
        import json as _json

        new_nonce = str(uuid.uuid4())

        # Parse current active nonces (gracefully handle NULL or malformed values)
        try:
            existing: list[str] = _json.loads(getattr(user, "session_nonces", None) or "[]")
            if not isinstance(existing, list):
                existing = []
        except (ValueError, TypeError):
            existing = []

        # Append new nonce and evict oldest entries beyond the configured limit
        existing.append(new_nonce)
        if len(existing) > MAX_CONCURRENT_SESSIONS:
            existing = existing[-MAX_CONCURRENT_SESSIONS:]

        async with db_session_factory() as session:
            await session.execute(
                update(User).where(User.id == user.id).values(session_nonces=_json.dumps(existing))
            )
            await session.commit()

        logger.info(
            f"[Auth] Session nonce added for user {user.id} "
            f"({len(existing)}/{MAX_CONCURRENT_SESSIONS} active sessions)"
        )

        data = {
            "sub": str(user.id),
            "aud": self.token_audience,
            "sn": new_nonce,
        }
        return generate_jwt(
            data, self.encode_key, self.lifetime_seconds, algorithm=self.algorithm
        )

    async def read_token(
        self, token: str | None, user_manager: BaseUserManagerType[User, uuid.UUID]
    ) -> User | None:
        """Decode JWT and verify the nonce is in the user's active sessions list."""
        if token is None:
            return None

        try:
            data = decode_jwt(
                token, self.decode_key, self.token_audience, algorithms=[self.algorithm]
            )
            user_id = data.get("sub")
            if user_id is None:
                return None
        except pyjwt.PyJWTError:
            return None

        # Reject tokens without session nonce (no backward compat)
        jwt_nonce = data.get("sn")
        if not jwt_nonce:
            return None

        try:
            parsed_id = user_manager.parse_id(user_id)
            user = await user_manager.get(parsed_id)
            if user is None:
                return None
        except (exceptions.UserNotExists, exceptions.InvalidID):
            return None

        # Multi-session enforcement: nonce must be in the active nonces list
        import json as _json
        try:
            db_nonces: list[str] = _json.loads(getattr(user, "session_nonces", None) or "[]")
            if not isinstance(db_nonces, list):
                db_nonces = []
        except (ValueError, TypeError):
            db_nonces = []

        if jwt_nonce not in db_nonces:
            logger.info(
                f"[Auth] Rejected stale token for user {user.id}: nonce not in active sessions"
            )
            return None

        return user


def get_jwt_strategy() -> SingleSessionJWTStrategy:
    """Get JWT strategy with single-device login enforcement."""
    return SingleSessionJWTStrategy(
        secret=JWT_SECRET, lifetime_seconds=Config.JWT_LIFETIME_SECONDS
    )


# Authentication backend combining transport and strategy
auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)


# Main FastAPI-Users instance
fastapi_users = FastAPIUsers[User, uuid.UUID](
    get_user_manager=get_user_manager,
    auth_backends=[auth_backend],
)


# Common dependencies for routes
current_active_user = fastapi_users.current_user(active=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
# Optional user for routes that work with or without auth
optional_current_user = fastapi_users.current_user(active=True, optional=True)
