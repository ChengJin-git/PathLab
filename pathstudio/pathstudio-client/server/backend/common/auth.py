"""
Authentication module for PathStudio Client.

Uses Casdoor Python SDK for OAuth authentication with PathStudio Server.
Implements the "Identity Unified, Data Separated" architecture.

Casdoor SDK documentation: https://github.com/casdoor/casdoor-python-sdk
"""

import os
from typing import Optional
from functools import lru_cache

from casdoor import AsyncCasdoorSDK


class AuthConfig:
    """Authentication configuration for PathStudio Server (Casdoor)."""

    # PathStudio Server URL (Casdoor endpoint)
    CASDOOR_ENDPOINT = os.getenv("PATHSTUDIO_SERVER_URL", "http://localhost:8000")
    
    # Casdoor application credentials
    CLIENT_ID = os.getenv("PATHSTUDIO_CLIENT_ID", "")
    CLIENT_SECRET = os.getenv("PATHSTUDIO_CLIENT_SECRET", "")

    # Casdoor organization and application
    ORG_NAME = os.getenv("PATHSTUDIO_ORG_NAME", "pathstudio")
    APP_NAME = os.getenv("PATHSTUDIO_APP_NAME", "pathstudio-client")

    # Certificate for JWT verification (PEM format)
    # This should match the certificate configured in Casdoor
    CERTIFICATE = os.getenv("PATHSTUDIO_CERTIFICATE", b"")
    
    # Deep Link protocol for OAuth callback
    DEEPLINK_PROTOCOL = "pathstudio"
    DEEPLINK_CALLBACK_PATH = "auth"
    
    # Token refresh threshold (minutes before expiry)
    TOKEN_REFRESH_THRESHOLD_MINUTES = 30
    
    @classmethod
    def get_redirect_uri(cls) -> str:
        """Get the Deep Link URL for OAuth callback."""
        return f"{cls.DEEPLINK_PROTOCOL}://{cls.DEEPLINK_CALLBACK_PATH}"
    
    @classmethod
    def is_configured(cls) -> bool:
        """Check if authentication is properly configured."""
        return bool(cls.CLIENT_ID and cls.CLIENT_SECRET)


@lru_cache()
def get_casdoor_sdk() -> AsyncCasdoorSDK:
    """
    Get singleton instance of AsyncCasdoorSDK.
    
    Uses lru_cache to ensure only one instance is created.
    """
    config = AuthConfig()
    
    # Convert certificate string to bytes if needed
    certificate = config.CERTIFICATE
    if isinstance(certificate, str):
        certificate = certificate.encode('utf-8')
    
    return AsyncCasdoorSDK(
        endpoint=config.CASDOOR_ENDPOINT,
        client_id=config.CLIENT_ID,
        client_secret=config.CLIENT_SECRET,
        certificate=certificate,
        org_name=config.ORG_NAME,
        application_name=config.APP_NAME,
    )


def get_login_url(redirect_uri: Optional[str] = None, state: Optional[str] = None) -> str:
    """
    Generate the OAuth login URL for PathStudio Server.

    Args:
        redirect_uri: Override default redirect URI (default: pathstudio://auth)
        state: Optional state parameter for CSRF protection

    Returns:
        Full login URL to open in browser
    """
    config = AuthConfig()

    redirect = redirect_uri or config.get_redirect_uri()

    # Build OAuth authorize URL
    url = (
        f"{config.CASDOOR_ENDPOINT}/login/oauth/authorize"
        f"?client_id={config.CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={redirect}"
        f"&scope=read"
    )

    if state:
        url += f"&state={state}"

    return url


def get_signup_url(redirect_uri: Optional[str] = None, state: Optional[str] = None) -> str:
    """
    Generate the signup URL for PathStudio Server.

    Args:
        redirect_uri: Override default redirect URI (default: pathstudio://auth)
        state: Optional state parameter for CSRF protection

    Returns:
        Full signup URL to open in browser
    """
    config = AuthConfig()

    redirect = redirect_uri or config.get_redirect_uri()

    # Build OAuth signup URL (Casdoor signup with redirect back to app)
    url = (
        f"{config.CASDOOR_ENDPOINT}/signup/{config.APP_NAME}"
        f"?client_id={config.CLIENT_ID}"
        f"&redirect_uri={redirect}"
    )

    if state:
        url += f"&state={state}"

    return url


async def exchange_code_for_token(code: str) -> dict:
    """
    Exchange OAuth authorization code for access token.
    
    Args:
        code: Authorization code from OAuth callback
    
    Returns:
        Token response containing access_token, refresh_token, etc.
    """
    sdk = get_casdoor_sdk()
    return await sdk.get_oauth_token(code=code)


async def parse_token(access_token: str) -> dict:
    """
    Parse and verify JWT access token.
    
    Args:
        access_token: JWT token to parse
    
    Returns:
        Decoded token payload with user info
    """
    sdk = get_casdoor_sdk()
    return sdk.parse_jwt_token(access_token)


async def refresh_access_token(refresh_token: str) -> dict:
    """
    Refresh access token using refresh token.
    
    Args:
        refresh_token: Refresh token from previous token response
    
    Returns:
        New token response
    """
    sdk = get_casdoor_sdk()
    return await sdk.refresh_token_request(refresh_token, scope="read")


async def get_user_info(user_id: str) -> Optional[dict]:
    """
    Get user information from PathStudio Server.

    Args:
        user_id: User ID (username) to fetch

    Returns:
        User information dict or None if not found
    """
    sdk = get_casdoor_sdk()
    return await sdk.get_user(user_id)

