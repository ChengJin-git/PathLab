"""
ASR (Automatic Speech Recognition) routes
Handles voice input transcription using DashScope Qwen3-ASR API
"""
import os
import json
import base64
import asyncio
import websockets
from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from typing import Optional

from ..dependencies import logger
from backend.auth import current_active_user, User

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
    # Get API key from request header or environment
    api_key = request.headers.get("X-DashScope-API-Key")
    if not api_key:
        api_key = os.environ.get("DASHSCOPE_API_KEY")
    
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
                        "threshold": 0.0,
                        "silence_duration_ms": 400
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

