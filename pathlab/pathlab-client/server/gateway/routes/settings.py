"""
Global Settings Routes

Provides API endpoints for managing global application settings.
These settings are shared across all users.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from backend.common.config import Config
from backend.auth import current_active_user, User
from backend.auth.dependencies import require_admin

router = APIRouter(prefix="/settings", tags=["Global Settings"])


class GlobalSettingsResponse(BaseModel):
    """Response model for global settings"""
    openrouter_api_key: str
    openrouter_base_url: str
    openrouter_model: str
    huggingface_token: str
    dashscope_api_key: str


class GlobalSettingsUpdateRequest(BaseModel):
    """Request model for updating global settings"""
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: Optional[str] = None
    openrouter_model: Optional[str] = None
    huggingface_token: Optional[str] = None
    dashscope_api_key: Optional[str] = None


@router.get("")
async def get_global_settings(
    user: User = Depends(current_active_user)
) -> GlobalSettingsResponse:
    """
    Get global settings. Available to all authenticated users.
    
    Returns:
        Global settings including AI configuration
    """
    settings = Config.get_global_settings()
    return GlobalSettingsResponse(**settings)


@router.post("")
async def update_global_settings(
    request: GlobalSettingsUpdateRequest,
    user: User = Depends(require_admin)
) -> GlobalSettingsResponse:
    """
    Update global settings. Admin only.
    
    Only provided fields will be updated.
    
    Returns:
        Updated global settings
    """
    # Convert to dict, excluding None values
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    
    if not updates:
        raise HTTPException(status_code=400, detail="No settings provided to update")
    
    settings = Config.update_global_settings(updates)
    return GlobalSettingsResponse(**settings)

