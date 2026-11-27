"""
ASR (Automatic Speech Recognition) routes
Handles voice input transcription using local vLLM ASR server or DashScope Qwen3-ASR Realtime API.

Priority: Local ASR (if enabled and online) > Remote DashScope (fallback)

Provides realtime streaming ASR via WebSocket with server-side VAD (Voice Activity Detection).
"""

import asyncio
import base64
import json
import os
import time
import uuid
from typing import Any, Optional, Tuple

import httpx
import websockets
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from backend.auth.dependencies import _get_user_from_jwt, assert_research_access
from backend.common.config import Config
from backend.database.database import async_session

from ..dependencies import logger

router = APIRouter(tags=["ASR"])


def _ws_is_open(ws: Any) -> bool:
    if hasattr(ws, "closed"):
        return not ws.closed
    if hasattr(ws, "state"):
        return ws.state.name == "OPEN"
    return False


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
        self._monitor_task: Optional[asyncio.Task[None]] = None

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
                    if self._monitor_task and not self._monitor_task.done():
                        self._monitor_task.cancel()
                    self._ws = ws
                    self._session_created_msg = msg
                    self._url = url
                    self._monitor_task = asyncio.create_task(
                        self._monitor(ws, url, headers)
                    )
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

    async def _monitor(self, ws: Any, url: str, headers: dict[str, str]) -> None:
        try:
            await ws.wait_closed()
        except Exception:
            pass
        async with self._lock:
            if self._ws is ws:
                self._ws = None
                self._session_created_msg = None
                should_rewarm = not self._warming
                if should_rewarm:
                    self._warming = True
            else:
                should_rewarm = False
        if should_rewarm:
            logger.debug("Local ASR warmup connection closed by server; re-warming")
            asyncio.create_task(self._do_warm(url, headers))

    def ensure_warm(self, url: str, headers: dict[str, str]) -> None:
        if self._warming or (self._ws is not None and self._url == url):
            return
        self._warming = True
        asyncio.create_task(self._do_warm(url, headers))

    async def claim(
        self, url: str, headers: dict[str, str]
    ) -> Tuple[Optional[Any], Optional[str]]:
        async with self._lock:
            if self._ws is not None and self._url == url:
                if _ws_is_open(self._ws):
                    ws, msg = self._ws, self._session_created_msg
                    self._ws = None
                    self._session_created_msg = None
                    if self._monitor_task and not self._monitor_task.done():
                        self._monitor_task.cancel()
                    self._warming = True
                    asyncio.create_task(self._do_warm(url, headers))
                    return ws, msg
                else:
                    # Stale connection — clear so ensure_warm can restart properly
                    self._ws = None
                    self._session_created_msg = None
        return None, None


_asr_warmup = _LocalASRWarmup()


def startup_prewarm_local_asr() -> None:
    global_settings = Config.get_global_settings()
    if not global_settings.get("local_asr_enabled", False):
        return
    base_url: str = global_settings.get(
        "local_asr_base_url", "ws://127.0.0.1:8001/api-ws/v1/realtime"
    )
    if not base_url or not _is_websocket_url(base_url):
        return
    model: str = global_settings.get("local_asr_model", "") or "Qwen/Qwen3-ASR-1.7B"
    api_key: str = global_settings.get("local_asr_api_key", "") or ""
    ws_url = base_url.rstrip("/")
    if "model=" not in ws_url and model:
        url = (
            f"{ws_url}?model={model}"
            if "?" not in ws_url
            else f"{ws_url}&model={model}"
        )
    else:
        url = ws_url
    headers: dict[str, str] = {"OpenAI-Beta": "realtime=v1"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    _asr_warmup.ensure_warm(url, headers)
    logger.info(f"Local ASR startup pre-warm initiated: {url}")


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


async def _relay_asr_events(
    websocket, upstream_ws, source_name, stored_session_created=None
):
    """Relay until either peer leaves; allow final recognition to drain on finish."""
    started = time.monotonic()
    request_id = uuid.uuid4().hex[:8]
    first_audio = True
    first_text = True
    speech_stopped_at = None
    audio_sequence = 0

    def timing(stage, since=None):
        elapsed = (time.monotonic() - (since if since is not None else started)) * 1000
        logger.info(
            f"[ASRTiming] req={request_id} provider={source_name} stage={stage} elapsed_ms={elapsed:.1f}"
        )

    async def from_upstream():
        nonlocal first_text, speech_stopped_at
        if stored_session_created:
            await websocket.send_text(stored_session_created)
        async for message in upstream_ws:
            data = json.loads(message)
            kind = data.get("type")
            # DashScope can reject unavailable models using its API error envelope,
            # without a realtime `type`. Surface it instead of waiting for setup timeout.
            if not kind and data.get("code") and data.get("message"):
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": {"code": data["code"], "message": data["message"]},
                    }
                )
                return
            if kind in {"session.created", "session.updated"}:
                timing(kind)
            elif kind == "input_audio_buffer.speech_stopped":
                speech_stopped_at = time.monotonic()
                timing("speech_stopped")
            elif (
                kind == "conversation.item.input_audio_transcription.text"
                and first_text
            ):
                first_text = False
                timing("first_partial")
            elif kind == "conversation.item.input_audio_transcription.completed":
                timing("final_after_vad", speech_stopped_at)
                speech_stopped_at = None
                first_text = True
            # Don't log audio or transcript content on the latency-sensitive path.
            await websocket.send_text(
                message if isinstance(message, str) else message.decode()
            )
            if kind == "session.finished":
                return

    async def from_client():
        nonlocal first_audio, audio_sequence
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return False
            if message.get("bytes") is not None:
                audio_sequence += 1
                data = {
                    "event_id": f"audio_{audio_sequence}",
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(message["bytes"]).decode("ascii"),
                }
                payload = json.dumps(data)
            elif message.get("text") is not None:
                payload = message["text"]
                data = json.loads(payload)
            else:
                continue
            if first_audio and data.get("type") == "input_audio_buffer.append":
                first_audio = False
                timing("first_audio")
            await upstream_ws.send(payload)
            if data.get("type") == "session.finish":
                return True

    upstream = asyncio.create_task(from_upstream())
    client = asyncio.create_task(from_client())
    try:
        done, _ = await asyncio.wait(
            {upstream, client}, return_when=asyncio.FIRST_COMPLETED
        )
        if upstream in done:
            await upstream
        elif await client:
            # Explicit finish must deliver the final transcript before closing.
            await asyncio.wait_for(upstream, timeout=5)
    finally:
        for task in (upstream, client):
            if not task.done():
                task.cancel()
        await asyncio.gather(upstream, client, return_exceptions=True)


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
    4. Transcription.completed carries the final result; speech_stopped is only VAD

    Events from server to client:
    - session.created: Connection established
    - session.updated: Config applied
    - input_audio_buffer.speech_started: Voice detected
    - input_audio_buffer.speech_stopped: Silence detected (VAD triggered)
    - conversation.item.input_audio_transcription.text: Realtime partial transcript
    - conversation.item.input_audio_transcription.completed: Final transcript
    - error: Error occurred
    """
    connection_started = time.monotonic()
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

    # Validate JWT token and get user (uses centralized _get_user_from_jwt which
    # enforces session_nonce, ensuring revoked/stale sessions are rejected)
    try:
        async with async_session() as db:
            user = await _get_user_from_jwt(token, db)
            assert_research_access(user)
    except HTTPException as e:
        logger.warning(f"WebSocket auth failed: {e.detail}")
        await websocket.send_json(
            {
                "type": "error",
                "error": {"message": f"Authentication failed: {e.detail}"},
            }
        )
        await websocket.close(code=4001)
        return

    logger.info(f"WebSocket authenticated for user: {user.username}")
    logger.info(
        f"[ASRTiming] stage=authenticated elapsed_ms={(time.monotonic() - connection_started) * 1000:.1f}"
    )

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
        }

        max_retries = 2
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    f"Connecting to DashScope ASR (attempt {attempt}/{max_retries}): {url}"
                )
                try:
                    await websocket.send_json(
                        {
                            "type": "session.progress",
                            "step": "connecting_upstream",
                            "provider": "DashScope",
                            "attempt": attempt,
                            "max_attempts": max_retries,
                        }
                    )
                except Exception:
                    pass  # Client may have already disconnected
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

        logger.info(
            f"[ASRTiming] provider={source_name} stage=upstream_connected elapsed_ms={(time.monotonic() - connection_started) * 1000:.1f}"
        )
        await websocket.send_json(
            {
                "type": "session.progress",
                "step": "upstream_connected",
                "provider": source_name,
            }
        )
        await _relay_asr_events(
            websocket, upstream_ws, source_name, stored_session_created
        )

    except WebSocketDisconnect:
        logger.debug("ASR client disconnected")
    except websockets.exceptions.ConnectionClosed as e:
        logger.error(f"{source_name} WebSocket closed: {e}")
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "error": {"message": f"{source_name} connection closed: {e}"},
                }
            )
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Realtime ASR error ({source_name}): {e}")
        try:
            await websocket.send_json({"type": "error", "error": {"message": str(e)}})
        except Exception:
            pass
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
