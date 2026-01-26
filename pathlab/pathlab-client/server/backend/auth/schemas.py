"""
Pydantic Schemas for User API.

Custom schemas that use username (string) instead of email validation.
This allows simple usernames like 'admin' instead of requiring email format.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class UserRead(BaseModel):
    """Schema for reading user data (API responses).

    Note: We use 'email' field name for compatibility with FastAPI-Users,
    but it actually stores username (no email validation).
    """
    id: uuid.UUID
    email: str = Field(description="Username (stored in email field for FastAPI-Users compatibility)")
    is_active: bool = True
    is_superuser: bool = False
    is_verified: bool = False
    role: str = Field(default="guest", description="User role: admin, pathologist, guest")
    nickname: Optional[str] = Field(default=None, description="Display name")
    agreement_accepted_at: Optional[datetime] = Field(default=None, description="When user accepted the terms of service")
    created_at: Optional[datetime] = Field(default=None, description="Account creation time")
    updated_at: Optional[datetime] = Field(default=None, description="Last update time")

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    """Schema for creating a new user.

    Note: 'email' field is actually username (no email validation).
    """
    email: str = Field(description="Username (stored in email field)")
    password: str = Field(description="User password")
    is_active: Optional[bool] = True
    is_superuser: Optional[bool] = False
    is_verified: Optional[bool] = False
    role: str = Field(default="guest", description="User role: admin, pathologist, guest")
    nickname: Optional[str] = Field(default=None, description="Display name")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Validate role is one of the allowed values."""
        valid_roles = {"admin", "pathologist", "guest"}
        if v not in valid_roles:
            raise ValueError(f"Role must be one of: {', '.join(valid_roles)}")
        return v

    @field_validator("email")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Validate username is not empty and has reasonable length."""
        if not v or len(v.strip()) == 0:
            raise ValueError("Username cannot be empty")
        if len(v) > 255:
            raise ValueError("Username too long (max 255 characters)")
        return v.strip()


class UserUpdate(BaseModel):
    """Schema for updating user data."""
    password: Optional[str] = Field(default=None, description="New password")
    email: Optional[str] = Field(default=None, description="Username (stored in email field)")
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None
    is_verified: Optional[bool] = None
    role: Optional[str] = Field(default=None, description="User role: admin, pathologist, guest")
    nickname: Optional[str] = Field(default=None, description="Display name")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        """Validate role is one of the allowed values."""
        if v is None:
            return v
        valid_roles = {"admin", "pathologist", "guest"}
        if v not in valid_roles:
            raise ValueError(f"Role must be one of: {', '.join(valid_roles)}")
        return v


class UserReadAdmin(UserRead):
    """Extended schema for admin to see more user details.

    Same as UserRead since we already include all fields.
    """
    pass

