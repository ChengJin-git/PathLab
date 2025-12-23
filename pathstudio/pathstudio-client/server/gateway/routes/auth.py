"""
Authentication routes for PathStudio Client.

Uses Casdoor Python SDK for OAuth with PathStudio Server.
Implements endpoints for login, signup, callback, logout, and user info.
"""

import secrets
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import UserProfileRepository
from backend.common.auth import (
    AuthConfig, get_login_url, get_signup_url, exchange_code_for_token,
    parse_token, refresh_access_token, get_user_info
)
from ..dependencies import logger

router = APIRouter(prefix="/auth", tags=["Authentication"])


# Request/Response models
class LoginUrlResponse(BaseModel):
    login_url: str
    state: str
    message: str = "Open this URL in browser to login"


class CallbackRequest(BaseModel):
    code: str  # Authorization code from OAuth callback
    state: Optional[str] = None


class CallbackResponse(BaseModel):
    success: bool
    user_id: str
    username: str
    message: str


class UserInfoResponse(BaseModel):
    is_logged_in: bool
    user: Optional[dict] = None


@router.get("/login-url", response_model=LoginUrlResponse)
async def get_login_url_endpoint():
    """
    Get the PathStudio Server login URL.

    The frontend should open this URL in the system browser.
    After login, PathStudio Server redirects to pathstudio://auth?code=xxx&state=yyy
    """
    if not AuthConfig.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Authentication not configured. Set PATHSTUDIO_CLIENT_ID and PATHSTUDIO_CLIENT_SECRET."
        )

    state = secrets.token_urlsafe(32)
    login_url = get_login_url(state=state)
    logger.info(f"Generated login URL with state: {state[:8]}...")

    return LoginUrlResponse(login_url=login_url, state=state)


@router.get("/signup-url", response_model=LoginUrlResponse)
async def get_signup_url_endpoint():
    """
    Get the PathStudio Server signup (registration) URL.

    The frontend should open this URL in the system browser.
    After signup, user can login through the normal login flow.
    """
    if not AuthConfig.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Authentication not configured. Set PATHSTUDIO_CLIENT_ID and PATHSTUDIO_CLIENT_SECRET."
        )

    state = secrets.token_urlsafe(32)
    signup_url = get_signup_url(state=state)
    logger.info(f"Generated signup URL with state: {state[:8]}...")

    return LoginUrlResponse(
        login_url=signup_url,  # Reuse LoginUrlResponse, field is named login_url
        state=state,
        message="Open this URL in browser to signup"
    )


@router.post("/callback", response_model=CallbackResponse)
async def process_callback(
    req: CallbackRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Process OAuth callback from PathStudio Server.

    Called after user logs in and Electron receives the pathstudio://auth?code=xxx deep link.
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
            "last_synced_at": datetime.utcnow(),
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


@router.post("/logout")
async def logout(db: AsyncSession = Depends(get_db)):
    """Logout current user by clearing local session."""
    try:
        current_user = await UserProfileRepository.get_current_user(db)

        if current_user:
            await UserProfileRepository.update(db, current_user.user_id, {
                "is_current": False,
                "access_token_encrypted": None,
                "refresh_token_encrypted": None,
                "token_expires_at": None,
            })
            await db.commit()
            logger.info(f"User logged out: {current_user.username}")

        return {"success": True, "message": "Logged out successfully"}
    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/me", response_model=UserInfoResponse)
async def get_current_user(db: AsyncSession = Depends(get_db)):
    """Get current logged-in user information."""
    try:
        current_user = await UserProfileRepository.get_current_user(db)

        if not current_user:
            return UserInfoResponse(is_logged_in=False)

        if not current_user.is_token_valid():
            return UserInfoResponse(
                is_logged_in=False,
                user={"message": "Token expired, please login again"}
            )

        return UserInfoResponse(
            is_logged_in=True,
            user=current_user.to_dict(include_sensitive=True)
        )
    except Exception as e:
        logger.error(f"Get current user error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh")
async def refresh_token_endpoint(db: AsyncSession = Depends(get_db)):
    """Refresh access token using Casdoor SDK."""
    try:
        current_user = await UserProfileRepository.get_current_user(db)

        if not current_user:
            raise HTTPException(status_code=401, detail="Not logged in")

        if not current_user.refresh_token_encrypted:
            raise HTTPException(status_code=400, detail="No refresh token. Please login again.")

        # Check if refresh is needed
        if not current_user.is_token_expiring_soon():
            return {
                "success": True,
                "refreshed": False,
                "message": "Token is still valid",
                "expires_at": current_user.token_expires_at.isoformat() if current_user.token_expires_at else None
            }

        # Refresh token using Casdoor SDK
        token_response = await refresh_access_token(current_user.refresh_token_encrypted)
        new_access_token = token_response.get("access_token")
        new_refresh_token = token_response.get("refresh_token")

        if not new_access_token:
            raise HTTPException(status_code=500, detail="Failed to refresh token")

        # Parse new token for expiry
        user_info = await parse_token(new_access_token)
        exp = user_info.get("exp")
        new_expires_at = datetime.fromtimestamp(exp) if exp else None

        # Update stored tokens
        await UserProfileRepository.update_tokens(
            db,
            current_user.user_id,
            new_access_token,
            new_refresh_token,
            new_expires_at
        )
        await db.commit()

        logger.info(f"Token refreshed for user: {current_user.username}")

        return {
            "success": True,
            "refreshed": True,
            "message": "Token refreshed successfully",
            "expires_at": new_expires_at.isoformat() if new_expires_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

