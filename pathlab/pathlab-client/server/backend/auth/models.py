"""
User Model for FastAPI-Users with custom role field.

This model extends FastAPI-Users' base model to add:
- role: User role for RBAC (admin, pathologist, guest)
- nickname: Display name
- created_at/updated_at: Timestamps
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column

# Import Base from existing models to share the same metadata
from backend.database.models import Base


def utc_now() -> datetime:
    """Get current UTC time as naive datetime (UTC assumed).

    Returns timezone-naive datetime in UTC, compatible with PostgreSQL
    TIMESTAMP WITHOUT TIME ZONE columns via asyncpg.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(SQLAlchemyBaseUserTableUUID, Base):
    """
    User model for authentication and authorization.
    
    Extends FastAPI-Users base model with:
    - role: User role (admin, pathologist, guest)
    - nickname: Display name for UI
    
    Inherits from SQLAlchemyBaseUserTableUUID:
    - id: UUID primary key
    - email: Unique email address
    - hashed_password: Password hash
    - is_active: Account is active
    - is_superuser: Superuser flag (admin bypass)
    - is_verified: Email verified flag
    """
    __tablename__ = "users"
    
    # Custom fields
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="guest",
        index=True
    )
    nickname: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, doc="Path to user's avatar image relative to uploads/avatars")

    # SHA256 hash of password for secure login (prevents plaintext transmission)
    # This is SHA256(password), stored alongside bcrypt hash for secure login verification
    password_sha256: Mapped[Optional[str]] = mapped_column(
        String(64),  # SHA256 produces 64 hex characters
        nullable=True,
        default=None,
        doc="SHA256 hash of password for secure login. NULL for legacy users."
    )

    # Single-device login enforcement: regenerated on each login to invalidate old sessions.
    # JWT tokens include this nonce; if the token's nonce doesn't match the DB, the session is rejected.
    session_nonce: Mapped[Optional[str]] = mapped_column(
        String(36),  # UUID4 string length
        nullable=True,
        default=None,
        doc="Random UUID regenerated on each login. Old tokens with mismatched nonce are rejected."
    )

    # Agreement acceptance tracking
    agreement_accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        default=None,
        doc="Timestamp when user accepted the terms of service. NULL means not accepted."
    )
    agreement_ip: Mapped[Optional[str]] = mapped_column(
        String(45),  # IPv6 max length is 45 chars
        nullable=True,
        default=None,
        doc="IP address of user when they accepted the terms of service."
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False
    )
    
    # Role constants
    ROLE_ADMIN = "admin"
    ROLE_PATHOLOGIST = "pathologist"
    ROLE_GUEST = "guest"
    
    VALID_ROLES = {ROLE_ADMIN, ROLE_PATHOLOGIST, ROLE_GUEST}
    
    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return self.role == self.ROLE_ADMIN or self.is_superuser
    
    def is_pathologist(self) -> bool:
        """Check if user has pathologist role."""
        return self.role == self.ROLE_PATHOLOGIST
    
    def is_guest(self) -> bool:
        """Check if user has guest role."""
        return self.role == self.ROLE_GUEST
    
    def can_use_gpu(self) -> bool:
        """Check if user can use GPU operations (analysis, training)."""
        # Admin and pathologist can use GPU, guest cannot
        return self.role in {self.ROLE_ADMIN, self.ROLE_PATHOLOGIST}
    
    def can_manage_users(self) -> bool:
        """Check if user can manage other users."""
        return self.is_admin()

    def can_access_settings(self) -> bool:
        """Check if user can access system settings."""
        return self.is_admin()

    def has_accepted_agreement(self) -> bool:
        """Check if user has accepted the terms of service."""
        return self.agreement_accepted_at is not None

