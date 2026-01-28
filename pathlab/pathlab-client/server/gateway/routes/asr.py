"""
ASR (Automatic Speech Recognition) routes
Handles voice input transcription using DashScope Qwen3-ASR API

Supports both:
1. Batch transcription (POST /asr/transcribe) - for recorded audio
2. Realtime streaming (WebSocket /asr/realtime) - for continuous voice with VAD
"""
import os
import json
import base64
import asyncio
import websockets
from fastapi import APIRouter, Request, Depends, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel
from typing import Optional

import uuid
from jose import jwt, JWTError
from sqlalchemy import select

from ..dependencies import logger
from backend.auth import current_active_user, User
from backend.auth.users import JWT_SECRET
from backend.common.config import Config
from backend.database.database import async_session_maker

router = APIRouter(tags=["ASR"])


class TranscribeRequest(BaseModel):
    """Request model for audio transcription"""
    audio: str  # Base64 encoded audio data (PCM 16kHz mono)
    language: Optional[str] = "zh"  # Language code (zh, en, etc.)


class TranscribeResponse(BaseModel):
    """Response model for audio transcription"""
    text: str  # Transcribed text
    success: bool = True
    error: Optional[str] = None


@router.post("/asr/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    req: TranscribeRequest,
    request: Request,
    user: User = Depends(current_active_user)
):
    """
    Transcribe audio using DashScope Qwen3-ASR API.

    Accepts base64-encoded PCM audio (16kHz, mono) and returns transcribed text.
    """
    # Get API key: request header > global settings > environment variable
    global_settings = Config.get_global_settings()
    api_key = (
        request.headers.get("X-DashScope-API-Key") or
        global_settings.get("dashscope_api_key") or
        os.environ.get("DASHSCOPE_API_KEY")
    )
    
    if not api_key:
        return TranscribeResponse(
            text="",
            success=False,
            error="DashScope API key not configured. Please set it in Settings."
        )
    
    try:
        # Decode audio data
        audio_data = base64.b64decode(req.audio)
        logger.info(f"Received audio data: {len(audio_data)} bytes")
        
        # Call DashScope Qwen3-ASR API via WebSocket (auto language detection)
        transcribed_text = await call_dashscope_asr(
            audio_data=audio_data,
            api_key=api_key
        )
        
        return TranscribeResponse(text=transcribed_text, success=True)
        
    except Exception as e:
        logger.error(f"ASR transcription failed: {str(e)}")
        return TranscribeResponse(
            text="",
            success=False,
            error=f"Transcription failed: {str(e)}"
        )


async def call_dashscope_asr(
    audio_data: bytes,
    api_key: str
) -> str:
    """
    Call DashScope Qwen3-ASR Realtime API via WebSocket.

    Args:
        audio_data: Raw PCM audio data (16kHz, mono, 16-bit signed integer)
        api_key: DashScope API key

    Returns:
        Transcribed text (auto language detection for zh/en/ja/ko/etc.)
    """
    model = "qwen3-asr-flash-realtime"
    # Use international endpoint (Singapore) for better global performance
    base_url = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime"
    url = f"{base_url}?model={model}"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "OpenAI-Beta": "realtime=v1"
    }
    
    transcribed_text = ""
    
    try:
        async with websockets.connect(url, additional_headers=headers) as ws:
            # Send session update event
            # Frontend now sends raw PCM data (16kHz, mono, 16-bit)
            session_update = {
                "event_id": "event_session_update",
                "type": "session.update",
                "session": {
                    "modalities": ["text"],
                    "input_audio_format": "pcm",
                    "sample_rate": 16000,
                    "input_audio_transcription": {
                        # Do not set language to enable auto-detection
                        # Supports: zh (Mandarin, Cantonese, Sichuan, etc.), en, ja, ko, etc.
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "silence_duration_ms": 200
                    }
                }
            }
            await ws.send(json.dumps(session_update))
            logger.info("Sent session update")
            
            # Wait a moment for session to be ready
            await asyncio.sleep(0.5)
            
            # Send audio data in chunks
            chunk_size = 3200  # ~0.1s of PCM16/16kHz
            offset = 0
            
            while offset < len(audio_data):
                chunk = audio_data[offset:offset + chunk_size]
                offset += chunk_size
                
                encoded = base64.b64encode(chunk).decode('utf-8')
                append_event = {
                    "event_id": f"event_audio_{offset}",
                    "type": "input_audio_buffer.append",
                    "audio": encoded
                }
                await ws.send(json.dumps(append_event))
                await asyncio.sleep(0.05)  # Small delay between chunks
            
            logger.info(f"Sent {len(audio_data)} bytes of audio")
            
            # Send finish event
            finish_event = {
                "event_id": "event_finish",
                "type": "session.finish"
            }
            await ws.send(json.dumps(finish_event))
            logger.info("Sent session finish")
            
            # Receive responses - accumulate transcriptions from completed events
            transcription_parts = []

            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    data = json.loads(message)
                    event_type = data.get("type", "")

                    if event_type == "session.finished":
                        # session.finished may not contain transcript, use accumulated parts
                        logger.info(f"Session finished, accumulated transcripts: {transcription_parts}")
                        break
                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        # This is the final result for a speech segment
                        transcript = data.get("transcript", "")
                        if transcript:
                            transcription_parts.append(transcript)
                        logger.info(f"Transcription completed: {transcript}")
                    elif event_type == "conversation.item.input_audio_transcription.text":
                        # Intermediate result (stash), ignore for final output
                        logger.debug(f"Intermediate: {data.get('text', '')}")
                    elif event_type == "error":
                        error_msg = data.get("error", {}).get("message", "Unknown error")
                        raise Exception(f"ASR API error: {error_msg}")

                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for ASR response")
                    break

            # Combine all transcription parts
            transcribed_text = "".join(transcription_parts)
            logger.info(f"Final combined transcript: {transcribed_text}")

    except websockets.exceptions.ConnectionClosed as e:
        logger.error(f"WebSocket connection closed: {e}")
        raise Exception(f"Connection closed: {e}")
    except Exception as e:
        logger.error(f"ASR API call failed: {e}")
        raise

    return transcribed_text


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
        async with async_session_maker() as db:
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
