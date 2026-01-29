"""
ASR (Automatic Speech Recognition) routes
Handles voice input transcription using DashScope Qwen3-ASR Realtime API

Provides realtime streaming ASR via WebSocket with server-side VAD (Voice Activity Detection).
"""
import os
import json
import base64
import asyncio
import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional

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
# Realtime ASR WebSocket Proxy
# ============================================================================

@router.websocket("/asr/realtime")
async def asr_realtime_websocket(
    websocket: WebSocket,
    token: Optional[str] = Query(None)
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
        await websocket.send_json({
            "type": "error",
            "error": {"message": "Authentication required: no token provided"}
        })
        await websocket.close(code=4001)
        return

    # Validate JWT token and get user
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            audience="fastapi-users:auth"
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
        await websocket.send_json({
            "type": "error",
            "error": {"message": f"Authentication failed: {e}"}
        })
        await websocket.close(code=4001)
        return

    logger.info(f"WebSocket authenticated for user: {user.email}")

    # Get API key
    global_settings = Config.get_global_settings()
    api_key = global_settings.get("dashscope_api_key") or os.environ.get("DASHSCOPE_API_KEY")

    if not api_key:
        await websocket.send_json({
            "type": "error",
            "error": {"message": "DashScope API key not configured"}
        })
        await websocket.close(code=4002)
        return

    # Connect to DashScope realtime ASR
    model = "qwen3-asr-flash-realtime"
    base_url = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime"
    url = f"{base_url}?model={model}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "OpenAI-Beta": "realtime=v1"
    }

    dashscope_ws = None

    try:
        dashscope_ws = await websockets.connect(url, additional_headers=headers)
        logger.info("Connected to DashScope realtime ASR")

        # Forward session.created event to client when we receive it
        async def forward_from_dashscope():
            """Forward events from DashScope to frontend"""
            try:
                async for message in dashscope_ws:
                    data = json.loads(message)
                    event_type = data.get("type", "")

                    # Log important events
                    if event_type in [
                        "session.created", "session.updated",
                        "input_audio_buffer.speech_started",
                        "input_audio_buffer.speech_stopped",
                        "conversation.item.input_audio_transcription.completed",
                        "session.finished", "error"
                    ]:
                        logger.info(f"DashScope -> Client: {event_type}")

                    # Forward all events to frontend
                    await websocket.send_json(data)

                    # If session finished, we're done
                    if event_type == "session.finished":
                        break

            except websockets.exceptions.ConnectionClosed:
                logger.info("DashScope connection closed")
            except Exception as e:
                logger.error(f"Error forwarding from DashScope: {e}")
                await websocket.send_json({
                    "type": "error",
                    "error": {"message": str(e)}
                })

        async def forward_from_client():
            """Forward events from frontend to DashScope"""
            try:
                while True:
                    # Receive from frontend (can be text or bytes)
                    message = await websocket.receive()

                    if "text" in message:
                        data = json.loads(message["text"])
                        event_type = data.get("type", "")

                        # Log non-audio events
                        if event_type != "input_audio_buffer.append":
                            logger.info(f"Client -> DashScope: {event_type}")

                        # Forward to DashScope
                        await dashscope_ws.send(json.dumps(data))

                        # If client sends session.finish, stop receiving
                        if event_type == "session.finish":
                            logger.info("Client requested session finish")
                            break

                    elif "bytes" in message:
                        # Binary audio data - wrap in append event
                        audio_data = message["bytes"]
                        encoded = base64.b64encode(audio_data).decode('utf-8')
                        append_event = {
                            "event_id": f"event_audio_{id(audio_data)}",
                            "type": "input_audio_buffer.append",
                            "audio": encoded
                        }
                        await dashscope_ws.send(json.dumps(append_event))

            except WebSocketDisconnect:
                logger.info("Client WebSocket disconnected")
            except Exception as e:
                logger.error(f"Error forwarding from client: {e}")

        # Run both directions concurrently
        await asyncio.gather(
            forward_from_dashscope(),
            forward_from_client(),
            return_exceptions=True
        )

    except websockets.exceptions.ConnectionClosed as e:
        logger.error(f"DashScope WebSocket closed: {e}")
        await websocket.send_json({
            "type": "error",
            "error": {"message": f"DashScope connection closed: {e}"}
        })
    except Exception as e:
        logger.error(f"Realtime ASR error: {e}")
        await websocket.send_json({
            "type": "error",
            "error": {"message": str(e)}
        })
    finally:
        if dashscope_ws:
            try:
                await dashscope_ws.close()
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info("Realtime ASR WebSocket closed")
