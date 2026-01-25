"""
Authentication routes for PathLab Client (Casdoor OAuth).

Uses Casdoor Python SDK for OAuth with PathLab Server.
Implements endpoints for login URL generation, signup URL generation, and OAuth callback.

Note: JWT-based authentication endpoints are in auth_local.py.
"""

import secrets
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import UserProfileRepository
from backend.common.auth import (
    AuthConfig, get_login_url, get_signup_url, exchange_code_for_token,
    parse_token
)
from ..dependencies import logger

router = APIRouter(prefix="/auth", tags=["Authentication"])


# Request/Response models
class AuthUrlResponse(BaseModel):
    """Response containing an authentication URL (login or signup)"""
    url: str
    state: str
    message: str = "Open this URL in browser"


class CallbackRequest(BaseModel):
    code: str  # Authorization code from OAuth callback
    state: Optional[str] = None


class CallbackResponse(BaseModel):
    success: bool
    user_id: str
    username: str
    message: str


@router.get("/login-url", response_model=AuthUrlResponse)
async def get_login_url_endpoint():
    """
    Get the PathLab Server login URL.

    The frontend should open this URL in the system browser.
    After login, PathLab Server redirects to pathlab://auth?code=xxx&state=yyy
    """
    if not AuthConfig.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Authentication not configured. Set PATHLAB_CLIENT_ID and PATHLAB_CLIENT_SECRET."
        )

    state = secrets.token_urlsafe(32)
    login_url = get_login_url(state=state)
    logger.info(f"Generated login URL with state: {state[:8]}...")

    return AuthUrlResponse(url=login_url, state=state, message="Open this URL in browser to login")


@router.get("/signup-url", response_model=AuthUrlResponse)
async def get_signup_url_endpoint():
    """
    Get the PathLab Server signup (registration) URL.

    The frontend should open this URL in the system browser.
    After signup, user can login through the normal login flow.
    """
    if not AuthConfig.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Authentication not configured. Set PATHLAB_CLIENT_ID and PATHLAB_CLIENT_SECRET."
        )

    state = secrets.token_urlsafe(32)
    signup_url = get_signup_url(state=state)
    logger.info(f"Generated signup URL with state: {state[:8]}...")

    return AuthUrlResponse(url=signup_url, state=state, message="Open this URL in browser to signup")


@router.post("/callback", response_model=CallbackResponse)
async def process_callback(
    req: CallbackRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Process OAuth callback from PathLab Server.

    Called after user logs in and Electron receives the pathlab://auth?code=xxx deep link.
    Exchanges code for token, parses user info, and stores locally.
    """
    try:
        # Exchange code for token using Casdoor SDK
        token_response = await exchange_code_for_token(req.code)
        access_token = token_response.get("access_token")
        refresh_token = token_response.get("refresh_token")
        
        if not access_token:
            raise HTTPException(status_code=400, detail="Failed to get access token")
        
        # Parse JWT to get user info
        user_info = await parse_token(access_token)
        user_id = user_info.get("sub") or user_info.get("name")
        username = user_info.get("name", f"user_{user_id[:8] if user_id else 'unknown'}")
        
        if not user_id:
            raise HTTPException(status_code=400, detail="Token missing user identifier")
        
        # Calculate token expiry from JWT
        exp = user_info.get("exp")
        token_expires_at = datetime.fromtimestamp(exp) if exp else None
        
        # Create or update user profile locally
        profile_data = {
            "user_id": user_id,
            "username": username,
            "nickname": user_info.get("displayName"),
            "email": user_info.get("email"),
            "phone": user_info.get("phone"),
            "avatar_url": user_info.get("avatar"),
            "roles": user_info.get("roles", []),
            "access_token_encrypted": access_token,  # TODO: encrypt before storage
            "refresh_token_encrypted": refresh_token,
            "token_expires_at": token_expires_at,
            "server_url": AuthConfig.CASDOOR_ENDPOINT,
            "last_synced_at": datetime.now(timezone.utc),
            "is_current": True,
        }
        
        await UserProfileRepository.upsert(db, profile_data)
        await UserProfileRepository.set_current_user(db, user_id)
        await db.commit()
        
        logger.info(f"User logged in: {username} ({user_id})")
        
        return CallbackResponse(
            success=True,
            user_id=user_id,
            username=username,
            message="Login successful"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login callback error: {e}")
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")

