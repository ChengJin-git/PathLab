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
    yield SQLAlchemyUserDatabase(session, User)


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
        """Called after a user successfully registers."""
        print(f"[Auth] User {user.email} (id={user.id}) has registered with role={user.role}")

        # Auto-verify user (no email verification required)
        # This is done in the database directly since we don't have session here
        user.is_verified = True
        await self.user_db.update(user, {"is_verified": True})
    
    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None
    ):
        """Called after password reset is requested."""
        # In production, send email with reset link
        print(f"[Auth] User {user.email} requested password reset. Token: {token[:8]}...")
    
    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None
    ):
        """Called after email verification is requested."""
        # In production, send verification email
        print(f"[Auth] User {user.email} requested verification. Token: {token[:8]}...")
    
    async def on_after_login(
        self, user: User, request: Optional[Request] = None, response = None
    ):
        """Called after successful login."""
        print(f"[Auth] User {user.email} (role={user.role}) logged in")


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)):
    """Dependency to get user manager."""
    yield UserManager(user_db)


# JWT Transport - Bearer token in Authorization header
bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")


class SingleSessionJWTStrategy(JWTStrategy):
    """
    Custom JWT strategy that enforces single-device login.

    On each login (write_token), a new random session_nonce is generated, saved to DB,
    and embedded in the JWT. On each request (read_token), the JWT's nonce is compared
    against the DB value. If they don't match, the token is rejected, effectively
    logging out the old device.
    """

    async def write_token(self, user: models.UP) -> str:
        """Generate JWT with a fresh session_nonce for single-session enforcement."""
        new_nonce = str(uuid.uuid4())
        async with db_session_factory() as session:
            await session.execute(
                update(User).where(User.id == user.id).values(session_nonce=new_nonce)
            )
            await session.commit()

        logger.info(f"[Auth] New session nonce for user {user.id} (single-device enforcement)")

        data = {
            "sub": str(user.id),
            "aud": self.token_audience,
            "sn": new_nonce,  # session nonce for single-device check
        }
        return generate_jwt(
            data, self.encode_key, self.lifetime_seconds, algorithm=self.algorithm
        )

    async def read_token(
        self, token: str | None, user_manager: BaseUserManagerType[models.UP, models.ID]
    ) -> models.UP | None:
        """Decode JWT and verify session_nonce matches DB (single-session check)."""
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

        # Single-session enforcement: nonce must match DB
        db_nonce = getattr(user, 'session_nonce', None)
        if jwt_nonce != db_nonce:
            logger.info(f"[Auth] Rejected stale token for user {user.id}: session nonce mismatch")
            return None

        return user


def get_jwt_strategy() -> SingleSessionJWTStrategy:
    """Get JWT strategy with single-device login enforcement."""
    return SingleSessionJWTStrategy(secret=JWT_SECRET, lifetime_seconds=Config.JWT_LIFETIME_SECONDS)


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

