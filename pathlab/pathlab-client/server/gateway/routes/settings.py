"""
Global Settings Routes

Provides API endpoints for managing global application settings.
These settings are shared across all users.
"""

import httpx
import importlib
from fastapi import APIRouter, HTTPException, Depends, Request

from .access_control import User
from ..models import (
    PublicSettingsResponse,
    GlobalSettingsResponse,
    GlobalSettingsUpdateRequest,
    VllmCheckRequest,
    VllmCheckResponse,
    AsrCheckRequest,
    AsrCheckResponse,
)

_backend_common_config = importlib.import_module("backend.common.config")
_backend_auth_dependencies = importlib.import_module("backend.auth.dependencies")
_geo_ip = importlib.import_module("backend.common.geo_ip")

Config = _backend_common_config.Config
require_admin = _backend_auth_dependencies.require_admin
get_client_ip = _geo_ip.get_client_ip
is_mainland_china_ip = _geo_ip.is_mainland_china_ip

router = APIRouter(prefix="/settings", tags=["Global Settings"])


@router.get("/public")
async def get_public_settings(request: Request) -> PublicSettingsResponse:
    settings = Config.get_global_settings()
    
    client_ip = get_client_ip(request)
    is_china = await is_mainland_china_ip(client_ip)
    
    tencent_enabled = settings.get("tencent_captcha_enabled", False)
    tencent_app_id = settings.get("tencent_captcha_app_id", "")
    turnstile_enabled = settings.get("turnstile_enabled", False)
    turnstile_site_key = settings.get("turnstile_site_key", "")
    
    if is_china and tencent_enabled and tencent_app_id:
        return PublicSettingsResponse(
            captcha_provider="tencent",
            captcha_site_key=tencent_app_id,
        )
    elif turnstile_enabled and turnstile_site_key:
        return PublicSettingsResponse(
            captcha_provider="turnstile",
            captcha_site_key=turnstile_site_key,
        )
    else:
        return PublicSettingsResponse(
            captcha_provider=None,
            captcha_site_key="",
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
