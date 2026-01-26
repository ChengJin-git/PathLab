"""
PathLab Authentication Module

Provides user authentication, authorization, and role-based access control (RBAC).
Built on FastAPI-Users with custom role management.

Roles:
- admin: Full system access, including user management and system settings
- pathologist: Can use all analysis features except admin functions
- guest: View-only access, no GPU operations (analysis, training)
"""

from .users import (
    fastapi_users,
    auth_backend,
    current_active_user,
    current_superuser,
    get_user_manager,
    UserManager,
)
from .models import User
from .schemas import UserRead, UserCreate, UserUpdate
from .dependencies import (
    require_admin,
    require_pathologist_or_admin,
    require_can_use_gpu,
    get_current_user_id,
    get_user_from_token_param,
    get_user_from_header_or_param,
)

__all__ = [
    # FastAPI-Users
    "fastapi_users",
    "auth_backend",
    "current_active_user",
    "current_superuser",
    "get_user_manager",
    "UserManager",
    # Models
    "User",
    # Schemas
    "UserRead",
    "UserCreate",
    "UserUpdate",
    # RBAC Dependencies
    "require_admin",
    "require_pathologist_or_admin",
    "require_can_use_gpu",
    "get_current_user_id",
    "get_user_from_token_param",
    "get_user_from_header_or_param",
]

