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
from sqlalchemy import Column, String, DateTime, Boolean, Text
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

    # Contact email is optional and not identity.
    email: Mapped[Optional[str]] = mapped_column(
        String(320),
        nullable=True,
        default=None,
        doc="Optional contact email for notifications and account communication.",
    )

    # Login identity (separate from contact email)
    username: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )

    # Custom fields
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="guest", index=True
    )
    nickname: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_path: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True,
        doc="Path to user's avatar image relative to uploads/avatars",
    )

    # SHA256 hash of password for secure login (prevents plaintext transmission)
    # This is SHA256(password), stored alongside bcrypt hash for secure login verification
    password_sha256: Mapped[Optional[str]] = mapped_column(
        String(64),  # SHA256 produces 64 hex characters
        nullable=True,
        default=None,
        doc="SHA256 hash of password for secure login. NULL for legacy users.",
    )

    # Legacy single-nonce field. Kept for schema compat; no longer written. Use session_nonces instead.
    session_nonce: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        default=None,
        doc="Legacy single-nonce field. Kept for schema compat; no longer written. Use session_nonces instead.",
    )

    # Multi-device login enforcement: JSON array of active session nonces.
    # Length is capped to MAX_CONCURRENT_SESSIONS; oldest nonce is evicted on overflow.
    session_nonces: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default=None,
        doc="JSON array of active session nonces (up to MAX_CONCURRENT_SESSIONS). Oldest nonce evicted on overflow.",
    )

    # Agreement acceptance tracking
    agreement_accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        default=None,
        doc="Timestamp when user accepted the terms of service. NULL means not accepted.",
    )
    agreement_ip: Mapped[Optional[str]] = mapped_column(
        String(45),  # IPv6 max length is 45 chars
        nullable=True,
        default=None,
        doc="IP address of user when they accepted the terms of service.",
    )

    # Educational email provided during self-registration for identity proof.
    # NULL for admin-created users (no email required).
    # For self-registered users, this must pass educational email validation.
    registration_email: Mapped[Optional[str]] = mapped_column(
        String(320),  # RFC 5321 max email length
        nullable=True,
        default=None,
        doc="Educational email provided during self-registration for identity verification. NULL for admin-created users.",
    )

    # Maintenance mode: set True when maintenance mode deactivated this user.
    # Cleared when admin manually changes the user's is_active (either direction).
    # On disable-maintenance, only users with this flag still True are restored.
    deactivated_by_maintenance: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc=(
            "True while this user was deactivated by enabling maintenance mode "
            "AND has not been manually touched by an admin since. "
            "Cleared on any explicit admin is_active change. "
            "Used to restore only untouched users when maintenance ends."
        ),
    )

    first_activated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        default=None,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    # Role constants
    ROLE_ADMIN = "admin"
    ROLE_PATHOLOGIST = "pathologist"
    ROLE_GUEST = "guest"

    VALID_ROLES = {ROLE_ADMIN, ROLE_PATHOLOGIST, ROLE_GUEST}

    def is_admin(self) -> bool:
        return self.role == self.ROLE_ADMIN

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
