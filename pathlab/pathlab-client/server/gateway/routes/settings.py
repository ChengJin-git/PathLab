"""
Global Settings Routes

Provides API endpoints for managing global application settings.
These settings are shared across all users.
"""

import httpx
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from backend.common.config import Config
from backend.auth import current_active_user, User
from backend.auth.dependencies import require_admin

router = APIRouter(prefix="/settings", tags=["Global Settings"])


class PublicSettingsResponse(BaseModel):
    """Response model for public settings (no authentication required)"""

    turnstile_enabled: bool
    turnstile_site_key: str


class GlobalSettingsResponse(BaseModel):
    """Response model for global settings"""

    openrouter_api_key: str
    openrouter_base_url: str
    openrouter_model: str
    huggingface_token: str
    dashscope_api_key: str
    # Exa Search API key for web search functionality
    exa_api_key: str
    # Local vLLM settings (OpenAI-compatible server for LLM)
    local_vllm_enabled: bool
    local_vllm_base_url: str
    local_vllm_model: str
    local_vllm_api_key: str
    # Local ASR settings (OpenAI-compatible server for ASR)
    local_asr_enabled: bool
    local_asr_base_url: str
    local_asr_model: str
    local_asr_api_key: str
    # Cloudflare Turnstile settings
    turnstile_enabled: bool
    turnstile_site_key: str
    turnstile_secret_key: str
    resend_enabled: bool
    resend_api_key: str
    resend_from_email: str


class GlobalSettingsUpdateRequest(BaseModel):
    """Request model for updating global settings"""

    openrouter_api_key: Optional[str] = None
    openrouter_base_url: Optional[str] = None
    openrouter_model: Optional[str] = None
    huggingface_token: Optional[str] = None
    dashscope_api_key: Optional[str] = None
    # Exa Search API key
    exa_api_key: Optional[str] = None
    # Local vLLM settings
    local_vllm_enabled: Optional[bool] = None
    local_vllm_base_url: Optional[str] = None
    local_vllm_model: Optional[str] = None
    local_vllm_api_key: Optional[str] = None
    # Local ASR settings
    local_asr_enabled: Optional[bool] = None
    local_asr_base_url: Optional[str] = None
    local_asr_model: Optional[str] = None
    local_asr_api_key: Optional[str] = None
    # Cloudflare Turnstile settings
    turnstile_enabled: Optional[bool] = None
    turnstile_site_key: Optional[str] = None
    turnstile_secret_key: Optional[str] = None
    resend_enabled: Optional[bool] = None
    resend_api_key: Optional[str] = None
    resend_from_email: Optional[str] = None


@router.get("/public")
async def get_public_settings() -> PublicSettingsResponse:
    """
    Get public settings that don't require authentication.
    This includes Cloudflare Turnstile site key for login page.

    Returns:
        Public settings (Turnstile configuration)
    """
    settings = Config.get_global_settings()
    return PublicSettingsResponse(
        turnstile_enabled=settings.get("turnstile_enabled", False),
        turnstile_site_key=settings.get("turnstile_site_key", ""),
    )


@router.get("")
async def get_global_settings(
    user: User = Depends(require_admin),
) -> GlobalSettingsResponse:
    """
    Get global settings. Admin only - contains sensitive API keys.

    Returns:
        Global settings including AI configuration
    """
    settings = Config.get_global_settings()
    return GlobalSettingsResponse(**settings)


@router.post("")
async def update_global_settings(
    request: GlobalSettingsUpdateRequest, user: User = Depends(require_admin)
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


class VllmCheckRequest(BaseModel):
    """Request model for checking vLLM server status"""

    base_url: str
    api_key: Optional[str] = None


class VllmCheckResponse(BaseModel):
    """Response model for vLLM server status check"""

    online: bool
    model: Optional[str] = None
    error: Optional[str] = None


@router.post("/check-vllm")
async def check_vllm_status(
    request: VllmCheckRequest, user: User = Depends(require_admin)
) -> VllmCheckResponse:
    """
    Check if a vLLM server is online and get available model.
    This endpoint proxies the request to avoid CORS issues.

    Returns:
        VllmCheckResponse with online status and model info
    """
    try:
        headers = {}
        if request.api_key:
            headers["Authorization"] = f"Bearer {request.api_key}"

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{request.base_url}/models", headers=headers)

            if response.status_code == 200:
                data = response.json()
                # Extract first model name if available
                model_name = None
                if "data" in data and len(data["data"]) > 0:
                    model_name = data["data"][0].get("id")
                return VllmCheckResponse(online=True, model=model_name)
            else:
                return VllmCheckResponse(
                    online=False, error=f"HTTP {response.status_code}"
                )
    except httpx.TimeoutException:
        return VllmCheckResponse(online=False, error="Connection timeout")
    except httpx.ConnectError:
        return VllmCheckResponse(online=False, error="Connection refused")
    except Exception as e:
        return VllmCheckResponse(online=False, error=str(e))


class AsrCheckRequest(BaseModel):
    """Request model for checking ASR server status"""

    base_url: str  # Can be ws:// or http://
    model: Optional[str] = None
    api_key: Optional[str] = None


class AsrCheckResponse(BaseModel):
    """Response model for ASR server status check"""

    online: bool
    model: Optional[str] = None
    error: Optional[str] = None


@router.post("/check-asr")
async def check_asr_status(
    request: AsrCheckRequest, user: User = Depends(require_admin)
) -> AsrCheckResponse:
    """
    Check if an ASR server is online.
    Supports both WebSocket (ws://, wss://) and HTTP (http://, https://) URLs.

    For WebSocket URLs, attempts to connect and waits for session.created event.
    For HTTP URLs, checks the /models endpoint.

    Returns:
        AsrCheckResponse with online status and model info
    """
    import asyncio
    import json
    import websockets

    base_url = request.base_url.strip()
    is_websocket = base_url.startswith("ws://") or base_url.startswith("wss://")

    if is_websocket:
        # WebSocket URL - try to connect
        try:
            # Build URL with model if provided
            ws_url = base_url.rstrip("/")
            if request.model:
                if "?" in ws_url:
                    ws_url = f"{ws_url}&model={request.model}"
                else:
                    ws_url = f"{ws_url}?model={request.model}"

            headers = {"OpenAI-Beta": "realtime=v1"}
            if request.api_key:
                headers["Authorization"] = f"Bearer {request.api_key}"

            async with asyncio.timeout(5.0):
                async with websockets.connect(ws_url, additional_headers=headers) as ws:
                    # Wait for session.created event
                    message = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    data = json.loads(message)
                    if data.get("type") == "session.created":
                        detected_model = data.get("session", {}).get(
                            "model", request.model
                        )
                        return AsrCheckResponse(online=True, model=detected_model)
                    return AsrCheckResponse(online=False, error="Unexpected response")
        except asyncio.TimeoutError:
            return AsrCheckResponse(online=False, error="Connection timeout")
        except Exception as e:
            return AsrCheckResponse(online=False, error=str(e))
    else:
        # HTTP URL - check /models endpoint
        try:
            headers = {}
            if request.api_key:
                headers["Authorization"] = f"Bearer {request.api_key}"

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{base_url}/models", headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    model_name = None
                    if "data" in data and len(data["data"]) > 0:
                        model_name = data["data"][0].get("id")
                    return AsrCheckResponse(online=True, model=model_name)
                else:
                    return AsrCheckResponse(
                        online=False, error=f"HTTP {response.status_code}"
                    )
        except httpx.TimeoutException:
            return AsrCheckResponse(online=False, error="Connection timeout")
        except httpx.ConnectError:
            return AsrCheckResponse(online=False, error="Connection refused")
        except Exception as e:
            return AsrCheckResponse(online=False, error=str(e))
