"""
Pydantic Schemas for User API.

Extends FastAPI-Users base schemas with custom fields.
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi_users import schemas
from pydantic import Field, field_validator


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Schema for reading user data (API responses)."""

    role: str = Field(default="guest", description="User role: admin, pathologist, guest")
    nickname: Optional[str] = Field(default=None, description="Display name")
    agreement_accepted_at: Optional[datetime] = Field(default=None, description="When user accepted the terms of service")
    created_at: Optional[datetime] = Field(default=None, description="Account creation time")
    updated_at: Optional[datetime] = Field(default=None, description="Last update time")


class UserCreate(schemas.BaseUserCreate):
    """Schema for creating a new user."""
    
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


class UserUpdate(schemas.BaseUserUpdate):
    """Schema for updating user data."""
    
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
    """Extended schema for admin to see more user details."""
    
    is_active: bool
    is_superuser: bool
    is_verified: bool

