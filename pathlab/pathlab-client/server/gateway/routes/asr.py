"""
ASR (Automatic Speech Recognition) routes
Handles voice input transcription using local vLLM ASR server or DashScope Qwen3-ASR Realtime API.

Priority: Local ASR (if enabled and online) > Remote DashScope (fallback)

Provides realtime streaming ASR via WebSocket with server-side VAD (Voice Activity Detection).
"""

import os
import json
import base64
import asyncio
import websockets
import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Any, Optional, Tuple

import uuid
from jose import jwt, JWTError
from sqlalchemy import select

from ..dependencies import logger
from backend.auth import User
from backend.auth.users import JWT_SECRET
from backend.common.config import Config
from backend.database.database import async_session

router = APIRouter(tags=["ASR"])


# ============================================================================
# Local ASR Connection Pre-Warming
# ============================================================================


class _LocalASRWarmup:
    """Keeps one pre-warmed WebSocket to local ASR (session.created already received)."""

    def __init__(self) -> None:
        self._ws: Optional[Any] = None
        self._session_created_msg: Optional[str] = None
        self._url: Optional[str] = None
        self._lock: asyncio.Lock = asyncio.Lock()
        self._warming: bool = False

    async def _do_warm(self, url: str, headers: dict[str, str]) -> None:
        ws = None
        try:
            ws = await websockets.connect(
                url, additional_headers=headers, open_timeout=10
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            msg = raw if isinstance(raw, str) else raw.decode("utf-8")
            data = json.loads(msg)
            if data.get("type") == "session.created":
                async with self._lock:
                    if self._ws is not None:
                        try:
                            await self._ws.close()
                        except Exception:
                            pass
                    self._ws = ws
                    self._session_created_msg = msg
                    self._url = url
                logger.info("Local ASR pre-warm ready (session.created buffered)")
                ws = None  # ownership transferred; don't close in finally
        except Exception as e:
            logger.debug(f"Local ASR pre-warm failed: {e}")
        finally:
            self._warming = False
            if ws is not None:
                try:
                    await ws.close()
                except Exception:
                    pass

    def ensure_warm(self, url: str, headers: dict[str, str]) -> None:
        if self._warming or (self._ws is not None and self._url == url):
            return
        self._warming = True
        asyncio.create_task(self._do_warm(url, headers))

    async def claim(
        self, url: str, headers: dict[str, str]
    ) -> Tuple[Optional[Any], Optional[str]]:
        async with self._lock:
            if self._ws is not None and self._url == url and not self._ws.closed:
                ws, msg = self._ws, self._session_created_msg
                self._ws = None
                self._session_created_msg = None
                # Re-warm immediately so the next caller doesn't wait
                self._warming = True
                asyncio.create_task(self._do_warm(url, headers))
                return ws, msg
        return None, None


_asr_warmup = _LocalASRWarmup()


# ============================================================================
# Local ASR Server Detection
# ============================================================================


def _is_websocket_url(url: str) -> bool:
    """Check if the URL is a WebSocket URL (ws:// or wss://)."""
    return url.startswith("ws://") or url.startswith("wss://")


async def _check_local_asr_available(
    base_url: str, api_key: str = None
) -> Tuple[bool, Optional[str]]:
    """
    Check if local ASR server (OpenAI-compatible HTTP) is available and get the first available model.

    Returns:
        Tuple of (is_available, first_model_name)
    """
    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(f"{base_url}/models", headers=headers)
            if response.status_code == 200:
                data = response.json()
                # Extract first model name for auto-detect
                model_name = None
                if "data" in data and len(data["data"]) > 0:
                    model_name = data["data"][0].get("id")
                return True, model_name
            return False, None
    except Exception:
        return False, None


# ============================================================================
# Realtime ASR WebSocket Proxy
# ============================================================================


@router.websocket("/asr/realtime")
async def asr_realtime_websocket(
    websocket: WebSocket, token: Optional[str] = Query(None)
):
    """
    Realtime ASR WebSocket proxy for qwen3-asr-realtime.

    This endpoint proxies audio data from the frontend to DashScope's
    realtime ASR API and forwards transcription events back.

    Protocol:
    1. Client connects and sends 'session.update' to configure
    2. Client streams audio via 'input_audio_buffer.append'
    3. Server forwards VAD events and transcription results
    4. When speech_stopped is detected, server sends final transcript

    Events from server to client:
    - session.created: Connection established
    - session.updated: Config applied
    - input_audio_buffer.speech_started: Voice detected
    - input_audio_buffer.speech_stopped: Silence detected (VAD triggered)
    - conversation.item.input_audio_transcription.text: Realtime partial transcript
    - conversation.item.input_audio_transcription.completed: Final transcript
    - error: Error occurred
    """
    await websocket.accept()
    logger.info("Realtime ASR WebSocket connection accepted")

    # Authenticate user from token (passed as query param for WebSocket)
    if not token:
        await websocket.send_json(
            {
                "type": "error",
                "error": {"message": "Authentication required: no token provided"},
            }
        )
        await websocket.close(code=4001)
        return

    # Validate JWT token and get user
    try:
        payload = jwt.decode(
            token, JWT_SECRET, algorithms=["HS256"], audience="fastapi-users:auth"
        )
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise ValueError("Invalid token: no user ID")

        # Get user from database
        async with async_session() as db:
            result = await db.execute(
                select(User).where(User.id == uuid.UUID(user_id_str))
            )
            user = result.scalar_one_or_none()

            if not user or not user.is_active:
                raise ValueError("User not found or inactive")

    except (JWTError, ValueError) as e:
        logger.warning(f"WebSocket auth failed: {e}")
        await websocket.send_json(
            {"type": "error", "error": {"message": f"Authentication failed: {e}"}}
        )
        await websocket.close(code=4001)
        return

    logger.info(f"WebSocket authenticated for user: {user.email}")

    # Send progress: authenticated
    await websocket.send_json({"type": "session.progress", "step": "authenticated"})

    # Get settings
    global_settings = Config.get_global_settings()

    # Local ASR settings
    local_asr_enabled = global_settings.get("local_asr_enabled", False)
    local_asr_base_url = global_settings.get(
        "local_asr_base_url", "ws://127.0.0.1:8001/api-ws/v1/realtime"
    )
    local_asr_model = global_settings.get("local_asr_model", "")
    local_asr_api_key = global_settings.get("local_asr_api_key", "")

    # Remote DashScope settings (fallback)
    dashscope_api_key = global_settings.get("dashscope_api_key") or os.environ.get(
        "DASHSCOPE_API_KEY"
    )

    # Check if local ASR URL is a WebSocket URL (ws:// or wss://)
    local_is_websocket = (
        _is_websocket_url(local_asr_base_url) if local_asr_base_url else False
    )

    # Determine which service to use
    use_local = False
    detected_model = None

    if local_asr_enabled and local_asr_base_url:
        if local_is_websocket:
            # WebSocket URL - will try to connect directly
            logger.info(
                f"Local ASR configured with WebSocket URL: {local_asr_base_url}"
            )
            use_local = True
            detected_model = local_asr_model
        else:
            # HTTP URL - check availability via HTTP API
            logger.info(f"Checking local ASR server at {local_asr_base_url}...")
            await websocket.send_json(
                {"type": "session.progress", "step": "checking_local_asr"}
            )
            is_available, detected_model = await _check_local_asr_available(
                local_asr_base_url, local_asr_api_key
            )
            if is_available:
                use_local = True
                logger.info("Local ASR server is online, using local server")
            else:
                logger.warning(
                    "Local ASR server is offline, falling back to remote DashScope"
                )

    # If not using local and no remote API key, fail
    if not use_local and not dashscope_api_key:
        await websocket.send_json(
            {
                "type": "error",
                "error": {
                    "message": "ASR not configured: Local ASR is offline and DashScope API key not set"
                },
            }
        )
        await websocket.close(code=4002)
        return

    upstream_ws = None
    source_name = "DashScope"  # Will be updated if local succeeds
    stored_session_created: Optional[str] = None
    _warm_url: Optional[str] = None
    _warm_headers: Optional[dict[str, str]] = None

    # Helper function to connect to DashScope with retry
    async def connect_to_dashscope():
        model = "qwen3-asr-flash-realtime"
        base_url = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime"
        url = f"{base_url}?model={model}"
        headers = {
            "Authorization": f"Bearer {dashscope_api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        max_retries = 2
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    f"Connecting to DashScope ASR (attempt {attempt}/{max_retries}): {url}"
                )
                await websocket.send_json(
                    {
                        "type": "session.progress",
                        "step": "connecting_upstream",
                        "provider": "DashScope",
                        "attempt": attempt,
                        "max_attempts": max_retries,
                    }
                )
                ws = await websockets.connect(
                    url, additional_headers=headers, open_timeout=10
                )
                logger.info("Connected to DashScope realtime ASR")
                return ws
            except Exception as e:
                last_error = e
                logger.warning(
                    f"DashScope connection attempt {attempt}/{max_retries} failed: {e}"
                )
                if attempt < max_retries:
                    wait_time = attempt * 1.0
                    logger.info(f"Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)

        raise Exception(
            f"Failed to connect to DashScope after {max_retries} attempts: {last_error}"
        )

    try:
        if use_local:
            # Try to connect to local ASR first
            try:
                effective_model = (
                    local_asr_model or detected_model or "Qwen/Qwen3-ASR-1.7B"
                )

                if local_is_websocket:
                    # User provided a WebSocket URL directly - use it as-is
                    ws_url = local_asr_base_url.rstrip("/")
                    # Append model as query parameter if not already present
                    if "model=" not in ws_url and effective_model:
                        if "?" in ws_url:
                            url = f"{ws_url}&model={effective_model}"
                        else:
                            url = f"{ws_url}?model={effective_model}"
                    else:
                        url = ws_url
                else:
                    # HTTP URL - convert to WebSocket URL
                    ws_base_url = local_asr_base_url.replace(
                        "http://", "ws://"
                    ).replace("https://", "wss://")
                    # Remove /v1 suffix if present and add /realtime
                    ws_base_url = ws_base_url.rstrip("/")
                    if ws_base_url.endswith("/v1"):
                        ws_base_url = ws_base_url[:-3]
                    url = f"{ws_base_url}/v1/realtime?model={effective_model}"

                headers = {"OpenAI-Beta": "realtime=v1"}
                if local_asr_api_key:
                    headers["Authorization"] = f"Bearer {local_asr_api_key}"

                upstream_ws, stored_session_created = await _asr_warmup.claim(
                    url, headers
                )
                if upstream_ws:
                    source_name = "Local ASR"
                    logger.info(
                        f"Local ASR fast path: pre-warmed connection claimed (model: {effective_model})"
                    )
                else:
                    logger.info(f"Connecting to local ASR: {url}")
                    await websocket.send_json(
                        {
                            "type": "session.progress",
                            "step": "connecting_upstream",
                            "provider": "Local ASR",
                        }
                    )
                    upstream_ws = await websockets.connect(
                        url, additional_headers=headers, open_timeout=10
                    )
                    source_name = "Local ASR"
                    logger.info(f"Connected to local ASR with model: {effective_model}")

                _warm_url = url
                _warm_headers = headers
                _asr_warmup.ensure_warm(url, headers)
            except Exception as local_err:
                # Local ASR WebSocket connection failed, try fallback to DashScope
                logger.warning(f"Local ASR WebSocket connection failed: {local_err}")
                if dashscope_api_key:
                    logger.info("Falling back to remote DashScope ASR...")
                    upstream_ws = await connect_to_dashscope()
                    source_name = "DashScope"
                else:
                    # No fallback available, re-raise the error
                    raise Exception(
                        f"Local ASR failed and no DashScope API key configured: {local_err}"
                    )
        else:
            # Use DashScope directly
            upstream_ws = await connect_to_dashscope()

        # Forward session.created event to client when we receive it
        async def forward_from_upstream():
            try:
                if stored_session_created:
                    data = json.loads(stored_session_created)
                    logger.info(
                        f"{source_name} -> Client: session.created (pre-warmed)"
                    )
                    await websocket.send_json(data)

                async for message in upstream_ws:
                    data = json.loads(message)
                    event_type = data.get("type", "")

                    # Log all events with their full content for debugging
                    # This helps identify format differences between Local ASR and DashScope
                    if event_type in [
                        "session.created",
                        "session.updated",
                        "input_audio_buffer.speech_started",
                        "input_audio_buffer.speech_stopped",
                        "conversation.item.input_audio_transcription.completed",
                        "conversation.item.input_audio_transcription.text",
                        "session.finished",
                        "error",
                    ]:
                        # Log full message for transcript events to debug format issues
                        if "transcription" in event_type:
                            logger.info(
                                f"{source_name} -> Client: {event_type} | Full: {json.dumps(data, ensure_ascii=False)}"
                            )
                        else:
                            logger.info(f"{source_name} -> Client: {event_type}")

                    # Forward all events to frontend
                    await websocket.send_json(data)

                    # If session finished, we're done - exit cleanly
                    if event_type == "session.finished":
                        return  # Use return instead of break to exit cleanly

            except websockets.exceptions.ConnectionClosed:
                # Normal closure after session.finished, not an error
                logger.debug(f"{source_name} connection closed")
            except Exception as e:
                # Only log as error if there's actually an error message
                if str(e):
                    logger.error(f"Error forwarding from {source_name}: {e}")
                    try:
                        await websocket.send_json(
                            {"type": "error", "error": {"message": str(e)}}
                        )
                    except Exception:
                        pass  # Client may have already disconnected

        async def forward_from_client():
            """Forward events from frontend to upstream ASR server"""
            try:
                while True:
                    # Receive from frontend (can be text or bytes)
                    message = await websocket.receive()

                    if "text" in message:
                        data = json.loads(message["text"])
                        event_type = data.get("type", "")

                        # Log non-audio events
                        if event_type != "input_audio_buffer.append":
                            logger.info(f"Client -> {source_name}: {event_type}")

                        # Forward to upstream
                        await upstream_ws.send(json.dumps(data))

                        # If client sends session.finish, stop receiving
                        if event_type == "session.finish":
                            logger.info("Client requested session finish")
                            break

                    elif "bytes" in message:
                        # Binary audio data - wrap in append event
                        audio_data = message["bytes"]
                        encoded = base64.b64encode(audio_data).decode("utf-8")
                        append_event = {
                            "event_id": f"event_audio_{id(audio_data)}",
                            "type": "input_audio_buffer.append",
                            "audio": encoded,
                        }
                        await upstream_ws.send(json.dumps(append_event))

            except WebSocketDisconnect:
                logger.info("Client WebSocket disconnected")
            except Exception as e:
                logger.error(f"Error forwarding from client: {e}")

        # Run both directions concurrently
        await asyncio.gather(
            forward_from_upstream(), forward_from_client(), return_exceptions=True
        )

    except websockets.exceptions.ConnectionClosed as e:
        logger.error(f"{source_name} WebSocket closed: {e}")
        await websocket.send_json(
            {
                "type": "error",
                "error": {"message": f"{source_name} connection closed: {e}"},
            }
        )
    except Exception as e:
        logger.error(f"Realtime ASR error ({source_name}): {e}")
        await websocket.send_json({"type": "error", "error": {"message": str(e)}})
    finally:
        if upstream_ws:
            try:
                await upstream_ws.close()
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info(f"Realtime ASR WebSocket closed (was using {source_name})")
        if _warm_url and _warm_headers:
            _asr_warmup.ensure_warm(_warm_url, _warm_headers)
