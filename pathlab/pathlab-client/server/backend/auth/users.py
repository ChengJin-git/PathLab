"""
FastAPI-Users Configuration

Sets up:
- User Manager with custom logic
- JWT Authentication Backend
- FastAPI-Users instance with all routers
"""

import os
import uuid
from typing import Optional

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.database import get_db
from backend.common.config import Config
from .models import User


# Secret key for JWT tokens - use environment variable or generate a secure default
JWT_SECRET = os.getenv("JWT_SECRET", "pathlab-jwt-secret-change-in-production-12345")


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


def get_jwt_strategy() -> JWTStrategy:
    """Get JWT strategy with secret and lifetime."""
    return JWTStrategy(secret=JWT_SECRET, lifetime_seconds=Config.JWT_LIFETIME_SECONDS)


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

