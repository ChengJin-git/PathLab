"""
Pydantic Schemas for User API.

Custom schemas that use username (string) instead of email validation.
This allows simple usernames like 'admin' instead of requiring email format.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


VALID_ROLES = {"admin", "pathologist", "guest"}
PUBLIC_REGISTRATION_ROLES = {"guest"}


def _normalize_username(value: Optional[str]) -> Optional[str]:
    """Normalize usernames while preserving optional semantics."""
    if value is None:
        return value
    normalized = value.strip()
    if len(normalized) == 0:
        raise ValueError("Username cannot be empty")
    if len(normalized) > 255:
        raise ValueError("Username too long (max 255 characters)")
    return normalized


def _validate_role(value: Optional[str], allowed_roles: set[str]) -> Optional[str]:
    """Validate that a role is in the allowed set."""
    if value is None:
        return value
    if value not in allowed_roles:
        raise ValueError(f"Role must be one of: {', '.join(sorted(allowed_roles))}")
    return value


class UserRead(BaseModel):
    """Schema for reading user data (API responses).

    username is login identity; email is real contact email.
    """

    username: str = Field(description="Login username")
    id: uuid.UUID
    email: Optional[str] = Field(default=None, description="Contact email")
    is_active: bool = True
    is_superuser: bool = False
    is_verified: bool = False
    role: str = Field(
        default="guest", description="User role: admin, pathologist, guest"
    )
    nickname: Optional[str] = Field(default=None, description="Display name")
    avatar_url: Optional[str] = Field(
        default=None, description="URL to user's avatar image"
    )
    agreement_accepted_at: Optional[datetime] = Field(
        default=None, description="When user accepted the terms of service"
    )
    agreement_ip: Optional[str] = Field(
        default=None, description="IP address when user accepted the terms of service"
    )
    notice_acknowledged_at: Optional[datetime] = Field(
        default=None, description="When user last acknowledged a maintenance notice"
    )
    registration_email: Optional[str] = Field(
        default=None, description="Educational email provided during self-registration"
    )
    notify_on_success: bool = Field(default=True)
    notify_on_failed: bool = Field(default=False)
    notify_on_cancelled: bool = Field(default=False)
    created_at: Optional[datetime] = Field(
        default=None, description="Account creation time"
    )
    updated_at: Optional[datetime] = Field(default=None, description="Last update time")

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    """Schema for creating a new user.

    Public registration schema.

    Self-registration may only create non-admin accounts.
    """

    model_config = ConfigDict(extra="forbid")

    username: Optional[str] = Field(default=None, description="Login username")
    email: Optional[str] = Field(
        default=None,
        description="Contact email (legacy clients may still send username here)",
    )
    password: str = Field(description="User password")
    role: str = Field(default="guest", description="User role: pathologist, guest")
    nickname: Optional[str] = Field(default=None, description="Display name")
    registration_email: Optional[str] = Field(
        default=None, description="Contact email for the user"
    )

    @model_validator(mode="after")
    def normalize_identity_fields(self):
        # Transition compatibility: treat legacy email as username when username missing.
        if self.username is None and self.email is not None:
            self.username = self.email
            self.email = None
        if self.username is None:
            raise ValueError("Username is required")
        return self

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Validate role is one of the allowed public registration values."""
        return _validate_role(v, PUBLIC_REGISTRATION_ROLES) or "guest"

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Validate username is not empty and has reasonable length."""
        return _normalize_username(v) or ""


class UserUpdate(BaseModel):
    """Schema for current user self-service updates."""

    model_config = ConfigDict(extra="forbid")

    password: Optional[str] = Field(default=None, description="New password")
    email: Optional[str] = Field(default=None, description="Contact email")
    nickname: Optional[str] = Field(default=None, description="Display name")
    notify_on_success: Optional[bool] = None
    notify_on_failed: Optional[bool] = None
    notify_on_cancelled: Optional[bool] = None

class AdminUserUpdate(UserUpdate):
    """Schema for admin-managed updates to user accounts."""

    model_config = ConfigDict(extra="forbid")

    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None
    is_verified: Optional[bool] = None
    role: Optional[str] = Field(
        default=None, description="User role: admin, pathologist, guest"
    )
    registration_email: Optional[str] = Field(
        default=None, description="Contact email for the user"
    )

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        """Validate role is one of the allowed values."""
        return _validate_role(v, VALID_ROLES)


class UserReadAdmin(UserRead):
    """Extended schema for admin to see more user details.

    Same as UserRead since we already include all fields.
    """

    pass
