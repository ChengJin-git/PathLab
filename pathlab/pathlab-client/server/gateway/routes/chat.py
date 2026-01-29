"""
Chat and conversation management routes
Handles AI chat, conversation persistence, and task parsing
"""
import csv
import io
import os
import json
import tempfile
import uuid
import httpx
from datetime import datetime
from typing import List, Dict, AsyncIterator, Optional
from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import ChatRepository, WSIRepository, TrainedModelRepository, DatasetPermissionRepository, DatasetRepository, FeedbackRepository, ExportTaskRepository, TrainingTaskRepository, AITaskRepository
from backend.auth import current_active_user, User
from backend.auth.dependencies import check_data_ownership, get_user_id_filter
from backend.common.config import Config
from backend.common.gpu_utils import get_gpu_summary_for_prompt
from ..dependencies import logger
from ..prompts import get_chat_system_prompt, format_user_data_context
from ..models import ChatRequest, CreateConversationRequest, UpdateMessageRequest, AddMessageRequest, MessageFeedbackRequest

router = APIRouter(tags=["Chat & Conversations"])


def extract_text_from_content(content) -> str:
    """Extract text content from message content (handles both string and multimodal format)"""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # Multimodal format: [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
        return " ".join(text_parts)
    return ""


async def _stream_from_openai_compatible(
    messages: List[Dict],
    base_url: str,
    api_key: str,
    model: str,
    source_name: str = "API"
) -> AsyncIterator[str]:
    """
    Stream AI response from an OpenAI-compatible API endpoint.

    Args:
        messages: Chat messages (text or multimodal format)
        base_url: API base URL (e.g., http://127.0.0.1:8000/v1)
        api_key: API key for authentication
        model: Model name to use
        source_name: Name of the source for logging (e.g., "Local vLLM", "OpenRouter")

    Yields:
        SSE formatted response chunks
    """
    logger.info(f"Using {source_name} with model: {model}")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": messages,
                "stream": True,
                "temperature": 0.7,
                "max_tokens": 2048,
            }
        ) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        yield "data: [DONE]\n\n"
                        break
                    try:
                        parsed = json.loads(data)
                        if "choices" in parsed and len(parsed["choices"]) > 0:
                            delta = parsed["choices"][0].get("delta", {})
                            if "content" in delta:
                                yield f"data: {json.dumps({'content': delta['content']})}\n\n"
                    except json.JSONDecodeError:
                        continue


async def _check_local_vllm_available(base_url: str, api_key: str = None) -> tuple[bool, str | None]:
    """
    Check if local vLLM server is available and get the first available model.

    Returns:
        Tuple of (is_available, first_model_name)
    """
    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=3.0) as client:
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


async def stream_ai_response(
    messages: List[Dict],
    api_key: str = None,
    base_url: str = None,
    model: str = None
) -> AsyncIterator[str]:
    """
    Stream AI response using OpenAI-compatible API.
    Priority: Local vLLM (if enabled and online) > OpenRouter (fallback)

    Supports both text-only and multimodal messages.

    Args:
        messages: Chat messages (text or multimodal format)
        api_key: OpenRouter API key (from global settings or env)
        base_url: OpenRouter base URL (from global settings or env)
        model: Model name (from global settings or env)
    """
    global_settings = Config.get_global_settings()

    # Local vLLM settings
    local_vllm_enabled = global_settings.get("local_vllm_enabled", False)
    local_vllm_base_url = global_settings.get("local_vllm_base_url", "http://127.0.0.1:8000/v1")
    local_vllm_model = global_settings.get("local_vllm_model", "")
    local_vllm_api_key = global_settings.get("local_vllm_api_key", "")

    # OpenRouter settings (fallback)
    openrouter_api_key = api_key or global_settings.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY")
    openrouter_base_url = base_url or global_settings.get("openrouter_base_url") or os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_model = model or global_settings.get("openrouter_model") or os.environ.get("OPENROUTER_MODEL", "qwen/qwen3-vl-235b-a22b-instruct")

    # Try local vLLM first if enabled
    use_local = False
    detected_model = None
    if local_vllm_enabled and local_vllm_base_url:
        logger.info(f"Checking local vLLM server at {local_vllm_base_url}...")
        is_available, detected_model = await _check_local_vllm_available(local_vllm_base_url, local_vllm_api_key)
        if is_available:
            use_local = True
            logger.info("Local vLLM server is online, using local server")
        else:
            logger.warning("Local vLLM server is offline, falling back to OpenRouter")

    if use_local:
        # Use local vLLM
        # Auto-detect model if not specified
        effective_model = local_vllm_model or detected_model
        if not effective_model:
            logger.error("No model specified and auto-detect failed, falling back to OpenRouter")
        else:
            try:
                async for chunk in _stream_from_openai_compatible(
                    messages=messages,
                    base_url=local_vllm_base_url,
                    api_key=local_vllm_api_key,
                    model=effective_model,
                    source_name="Local vLLM"
                ):
                    yield chunk
                return
            except Exception as e:
                logger.error(f"Local vLLM error: {e}, falling back to OpenRouter")
                # Fall through to OpenRouter

    # Fallback to OpenRouter
    if not openrouter_api_key:
        # Return error message if no API key is configured
        error_msg = """**AI Configuration Required**

To use the AI assistant, please configure your OpenRouter API key or enable local vLLM server:

1. Click **Settings** in the left sidebar
2. Enter your **OpenRouter API Key** in the configuration form
   - OR enable **Local vLLM Server** and configure the server URL
3. Click **Save Settings**

**Get your API key:** [OpenRouter Console](https://openrouter.ai/keys)

After saving, return here and start chatting!"""

        yield f"data: {json.dumps({'content': error_msg})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Use OpenRouter API
    try:
        async for chunk in _stream_from_openai_compatible(
            messages=messages,
            base_url=openrouter_base_url,
            api_key=openrouter_api_key,
            model=openrouter_model,
            source_name="OpenRouter"
        ):
            yield chunk
    except Exception as e:
        logger.error(f"Error in AI streaming: {e}")
        error_msg = f"❌ Error: {str(e)}\n\nPlease check your API key and network connection."
        yield f"data: {json.dumps({'content': error_msg})}\n\n"
        yield "data: [DONE]\n\n"


@router.post("/conversations")
async def create_conversation(
    req: CreateConversationRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new conversation for the current user"""
    conversation_id = f"conv_{uuid.uuid4().hex[:16]}"
    conversation_data = {
        "conversation_id": conversation_id,
        "user_id": str(user.id),  # Use authenticated user's ID
        "title": req.title or "New Conversation",
    }
    conversation = await ChatRepository.create_conversation(db, conversation_data)
    await db.commit()
    return conversation.to_dict()


@router.get("/conversations")
async def list_conversations(
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """List all conversations for the current user"""
    user_id = str(user.id)
    conversations = await ChatRepository.get_user_conversations(db, user_id, skip, limit)
    total = await ChatRepository.count_user_conversations(db, user_id)
    return {"items": [conv.to_dict() for conv in conversations], "total": total}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a conversation with all messages. Users can only view their own conversations."""
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check ownership
    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to view this conversation")

    return {
        **conversation.to_dict(),
        "messages": [msg.to_dict() for msg in conversation.messages]
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a conversation. Users can only delete their own conversations."""
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check ownership
    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to delete this conversation")

    success = await ChatRepository.delete_conversation(db, conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.commit()
    return {"message": "Conversation deleted successfully"}


@router.patch("/conversations/{conversation_id}/messages/{message_id}")
async def update_message(
    conversation_id: str,
    message_id: int,
    req: UpdateMessageRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a message's content. Used to persist task submission status."""
    # First check conversation exists and user owns it
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to update this message")

    # Update the message
    message = await ChatRepository.update_message(db, message_id, req.content)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    await db.commit()
    return message.to_dict()


@router.delete("/conversations/{conversation_id}/messages/{message_id}")
async def delete_messages_from(
    conversation_id: str,
    message_id: int,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a message and all subsequent messages in a conversation.
    Used for conversation branching - allows users to delete from a point and restart.
    Users can only delete messages in their own conversations.
    """
    # First check conversation exists and user owns it
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to delete messages in this conversation")

    # Delete the message and all subsequent messages
    deleted_count = await ChatRepository.delete_messages_from_id(db, conversation_id, message_id)
    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="Message not found")

    await db.commit()
    return {"message": f"Deleted {deleted_count} message(s)", "deleted_count": deleted_count}


@router.post("/conversations/{conversation_id}/messages")
async def add_message(
    conversation_id: str,
    req: AddMessageRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Add a message to a conversation. Used to persist task submission success messages."""
    # First check conversation exists and user owns it
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to add messages to this conversation")

    # Add the message
    message_data = {
        "conversation_id": conversation_id,
        "role": req.role,
        "content": req.content,
    }
    message = await ChatRepository.add_message(db, message_data)
    await db.commit()
    return message.to_dict()


# ============================================================================
# Message Feedback APIs
# ============================================================================


@router.post("/messages/{message_id}/feedback")
async def submit_feedback(
    message_id: int,
    req: MessageFeedbackRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Submit or update feedback for a message.
    Supports thumbs up/down ratings and task helpfulness feedback.
    """
    # Validate feedback values
    if req.feedback_type and req.feedback_type not in ["thumbs_up", "thumbs_down"]:
        raise HTTPException(status_code=400, detail="feedback_type must be 'thumbs_up' or 'thumbs_down'")
    if req.task_helpfulness and req.task_helpfulness not in ["helpful", "not_helpful"]:
        raise HTTPException(status_code=400, detail="task_helpfulness must be 'helpful' or 'not_helpful'")

    # Upsert feedback (convert UUID to string for SQLite compatibility)
    feedback = await FeedbackRepository.upsert_feedback(
        db=db,
        message_id=message_id,
        user_id=str(user.id),
        feedback_type=req.feedback_type,
        task_helpfulness=req.task_helpfulness,
        related_task_id=req.related_task_id,
        time_to_action_seconds=req.time_to_action_seconds,
        message_content=req.message_content,
        context_messages=req.context_messages,
        task_type=req.task_type,
        task_title=req.task_title
    )
    await db.commit()
    return feedback.to_dict()


@router.get("/messages/{message_id}/feedback")
async def get_feedback(
    message_id: int,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get feedback for a specific message."""
    feedback = await FeedbackRepository.get_feedback(db, message_id, str(user.id))
    if not feedback:
        return {"message_id": message_id, "feedback": None}
    return feedback.to_dict()


@router.delete("/messages/{message_id}/feedback")
async def delete_feedback(
    message_id: int,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete feedback for a message."""
    success = await FeedbackRepository.delete_feedback(db, message_id, str(user.id))
    if not success:
        raise HTTPException(status_code=404, detail="Feedback not found")
    await db.commit()
    return {"message": "Feedback deleted successfully"}


@router.get("/conversations/{conversation_id}/feedbacks")
async def get_conversation_feedbacks(
    conversation_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all feedbacks for messages in a conversation."""
    # Verify user has access to this conversation
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to access this conversation")

    feedbacks = await FeedbackRepository.get_feedbacks_for_conversation(db, conversation_id, str(user.id))
    return {"feedbacks": [f.to_dict() for f in feedbacks]}


# ============================================================================
# Admin Feedback Management Endpoints
# ============================================================================

@router.get("/admin/feedbacks")
async def get_admin_feedbacks(
    skip: int = 0,
    limit: int = 50,
    feedback_type: Optional[str] = None,
    helpfulness: Optional[str] = None,
    user_id: Optional[str] = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all feedbacks with pagination and filtering (admin only).
    """
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    feedbacks, total = await FeedbackRepository.get_all_feedbacks(
        db=db,
        skip=skip,
        limit=limit,
        feedback_type_filter=feedback_type,
        helpfulness_filter=helpfulness,
        user_id_filter=user_id
    )

    # feedbacks is already a list of dicts with username included
    return {
        "feedbacks": feedbacks,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/admin/feedbacks/stats")
async def get_admin_feedback_stats(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get feedback statistics (admin only).
    """
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    stats = await FeedbackRepository.get_feedback_stats(db)
    return stats


@router.get("/admin/feedbacks/export")
async def export_admin_feedbacks(
    format: str = "json",
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Export all feedbacks (admin only).
    Supports JSON and CSV formats.
    """
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    # Get all feedbacks (no pagination for export)
    feedbacks, _ = await FeedbackRepository.get_all_feedbacks(db=db, skip=0, limit=10000)

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        # Header
        writer.writerow([
            "id", "message_id", "user_id", "feedback_type",
            "task_helpfulness", "related_task_id", "created_at", "updated_at"
        ])
        # Data rows
        for f in feedbacks:
            f_dict = f.to_dict()
            writer.writerow([
                f_dict.get("id"),
                f_dict.get("message_id"),
                f_dict.get("user_id"),
                f_dict.get("feedback_type"),
                f_dict.get("task_helpfulness"),
                f_dict.get("related_task_id"),
                f_dict.get("created_at"),
                f_dict.get("updated_at")
            ])

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=feedbacks.csv"}
        )
    else:
        # JSON format (default)
        return {"feedbacks": [f.to_dict() for f in feedbacks]}


@router.delete("/admin/feedbacks/reset")
async def reset_all_feedbacks(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete all feedbacks (admin only).
    This is a destructive operation that cannot be undone.
    """
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    deleted_count = await FeedbackRepository.delete_all_feedbacks(db)
    await db.commit()
    return {"message": f"Successfully deleted {deleted_count} feedbacks", "deleted_count": deleted_count}


# Async Export Endpoints


async def process_export_task(
    task_id: str,
    export_type: str,
    file_format: str,
    filter_params: dict,
    db_session_maker
):
    """
    Background task to process export in batches.
    Writes directly to file to avoid memory issues.
    """
    async with db_session_maker() as db:
        try:
            # Mark as processing
            await ExportTaskRepository.update_status(db, task_id, 'processing', progress=0)
            await db.commit()

            # Parse filter params
            date_from = None
            date_to = None
            if filter_params:
                if filter_params.get('date_from'):
                    date_from = datetime.fromisoformat(filter_params['date_from'].replace('Z', '+00:00'))
                if filter_params.get('date_to'):
                    date_to = datetime.fromisoformat(filter_params['date_to'].replace('Z', '+00:00'))

            # Get total count
            total_count = await FeedbackRepository.get_feedbacks_count(
                db=db,
                feedback_type_filter=filter_params.get('feedback_type') if filter_params else None,
                helpfulness_filter=filter_params.get('helpfulness') if filter_params else None,
                user_id_filter=filter_params.get('user_id') if filter_params else None,
                date_from=date_from,
                date_to=date_to
            )

            if total_count == 0:
                await ExportTaskRepository.update_status(
                    db, task_id, 'completed',
                    progress=100,
                    total_records=0,
                    file_path=None
                )
                await db.commit()
                return

            # Create temp file
            import tempfile
            import os
            export_dir = os.path.join(tempfile.gettempdir(), 'pathlab_exports')
            os.makedirs(export_dir, exist_ok=True)

            file_ext = 'csv' if file_format == 'csv' else 'json'
            file_path = os.path.join(export_dir, f'feedbacks_{task_id}.{file_ext}')

            # Batch export
            batch_size = 1000
            processed = 0

            if file_format == 'csv':
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    # Header
                    writer.writerow([
                        "id", "message_id", "user_id", "feedback_type",
                        "task_helpfulness", "related_task_id", "time_to_action_seconds",
                        "created_at", "updated_at"
                    ])

                    offset = 0
                    while offset < total_count:
                        feedbacks = await FeedbackRepository.get_feedbacks_batch(
                            db=db,
                            offset=offset,
                            limit=batch_size,
                            feedback_type_filter=filter_params.get('feedback_type') if filter_params else None,
                            helpfulness_filter=filter_params.get('helpfulness') if filter_params else None,
                            user_id_filter=filter_params.get('user_id') if filter_params else None,
                            date_from=date_from,
                            date_to=date_to
                        )

                        for f_obj in feedbacks:
                            f_dict = f_obj.to_dict()
                            writer.writerow([
                                f_dict.get("id"),
                                f_dict.get("message_id"),
                                f_dict.get("user_id"),
                                f_dict.get("feedback_type"),
                                f_dict.get("task_helpfulness"),
                                f_dict.get("related_task_id"),
                                f_dict.get("time_to_action_seconds"),
                                f_dict.get("created_at"),
                                f_dict.get("updated_at")
                            ])

                        processed += len(feedbacks)
                        progress = min(99, int(processed / total_count * 100))
                        await ExportTaskRepository.update_status(db, task_id, 'processing', progress=progress)
                        await db.commit()

                        offset += batch_size
                        if len(feedbacks) < batch_size:
                            break
            else:
                # JSON format
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write('{"feedbacks": [')
                    first = True

                    offset = 0
                    while offset < total_count:
                        feedbacks = await FeedbackRepository.get_feedbacks_batch(
                            db=db,
                            offset=offset,
                            limit=batch_size,
                            feedback_type_filter=filter_params.get('feedback_type') if filter_params else None,
                            helpfulness_filter=filter_params.get('helpfulness') if filter_params else None,
                            user_id_filter=filter_params.get('user_id') if filter_params else None,
                            date_from=date_from,
                            date_to=date_to
                        )

                        for f_obj in feedbacks:
                            if not first:
                                f.write(',')
                            first = False
                            f.write(json.dumps(f_obj.to_dict()))

                        processed += len(feedbacks)
                        progress = min(99, int(processed / total_count * 100))
                        await ExportTaskRepository.update_status(db, task_id, 'processing', progress=progress)
                        await db.commit()

                        offset += batch_size
                        if len(feedbacks) < batch_size:
                            break

                    f.write(']}')

            # Mark as completed
            await ExportTaskRepository.update_status(
                db, task_id, 'completed',
                progress=100,
                file_path=file_path,
                total_records=processed
            )
            await db.commit()

        except Exception as e:
            logger.error(f"Export task {task_id} failed: {e}")
            await ExportTaskRepository.update_status(
                db, task_id, 'failed',
                error_message=str(e)
            )
            await db.commit()


@router.post("/admin/feedbacks/export-async")
async def start_async_export(
    background_tasks: BackgroundTasks,
    format: str = "json",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    feedback_type: Optional[str] = None,
    helpfulness: Optional[str] = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Start an async export task (admin only).
    Returns task_id for polling status.
    """
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    task_id = str(uuid.uuid4())
    filter_params = {
        "date_from": date_from,
        "date_to": date_to,
        "feedback_type": feedback_type,
        "helpfulness": helpfulness
    }

    # Create task record
    await ExportTaskRepository.create(
        db=db,
        task_id=task_id,
        user_id=str(user.id),
        export_type='feedbacks',
        file_format=format,
        filter_params=filter_params
    )
    await db.commit()

    # Get db session maker for background task
    from backend.database import async_session_maker

    # Schedule background task
    background_tasks.add_task(
        process_export_task,
        task_id,
        'feedbacks',
        format,
        filter_params,
        async_session_maker
    )

    return {"task_id": task_id, "status": "pending"}


@router.get("/admin/feedbacks/export-async/{task_id}")
async def get_export_status(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get export task status (admin only).
    """
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    task = await ExportTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Export task not found")

    return task.to_dict()


@router.get("/admin/feedbacks/export-async/{task_id}/download")
async def download_export_file(
    task_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Download exported file (admin only).
    """
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    task = await ExportTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Export task not found")

    if task.status != 'completed':
        raise HTTPException(status_code=400, detail=f"Export not ready. Status: {task.status}")

    if not task.file_path:
        raise HTTPException(status_code=404, detail="No file generated (possibly empty export)")

    import os
    if not os.path.exists(task.file_path):
        raise HTTPException(status_code=404, detail="Export file not found")

    filename = f"feedbacks_export.{task.file_format}"
    media_type = "text/csv" if task.file_format == "csv" else "application/json"

    return FileResponse(
        path=task.file_path,
        filename=filename,
        media_type=media_type
    )


@router.post("/chat")
async def chat_with_ai(
    req: ChatRequest,
    request: Request,
    user: User = Depends(current_active_user),
    user_id_filter: Optional[str] = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db)
):
    """
    Chat with AI assistant (streaming).
    Returns Server-Sent Events (SSE) stream.

    If conversation_id is provided, messages will be persisted to database.

    AI configuration is read from HTTP headers:
    - X-OpenRouter-API-Key: OpenRouter API key
    - X-OpenRouter-Base-URL: OpenRouter base URL
    - X-OpenRouter-Model: Model name
    """
    # Get AI configuration from request headers
    api_key = request.headers.get("X-OpenRouter-API-Key")
    base_url = request.headers.get("X-OpenRouter-Base-URL")
    model = request.headers.get("X-OpenRouter-Model")

    # Fetch user's data overview for context (single optimized query)
    stats = await WSIRepository.get_chat_context_stats(db, user_id=user_id_filter)

    # Fetch user's trained models
    trained_models = await TrainedModelRepository.get_all(db, limit=100, offset=0, user_id=user_id_filter)

    # Fetch user's training tasks (recent 10 for context, with counts)
    training_tasks = await TrainingTaskRepository.get_all(db, limit=10, offset=0, user_id=user_id_filter)
    training_tasks_stats = await TrainingTaskRepository.get_status_counts(db, user_id=user_id_filter)

    # Fetch user's inference tasks (recent 10 for context, with counts)
    inference_tasks = await AITaskRepository.get_recent(db, limit=10, user_id=user_id_filter)
    inference_tasks_stats = await AITaskRepository.get_status_counts(db, user_id=user_id_filter)

    # Fetch user's temporary dataset permissions (for non-admin users)
    temp_permissions = []
    if not user.is_admin():
        temp_permissions = await DatasetPermissionRepository.get_valid_by_user(db, str(user.id))

    # Format user data context for System Prompt
    wsi_count = stats["total_count"]
    datasets = stats["datasets"]
    data_type_dist = stats["data_types"]

    # Format datasets with detailed info (data_type and labels per dataset)
    # Each dataset has its own labels and survival data - do NOT show global labels to avoid confusion
    if datasets:
        datasets_details = []
        for d in datasets:
            ds_name = d['dataset_name']
            ds_id = d.get('dataset_id', 'unknown')
            ds_count = d['file_count']
            ds_type = d.get('data_type', 'unknown')
            ds_labels = d.get('labels', {})
            ds_survival = d.get('survival_count', 0)

            # Build info parts
            labels_str = ", ".join([f"{lbl}({cnt})" for lbl, cnt in ds_labels.items()]) if ds_labels else "none"
            survival_str = f", survival_data={ds_survival}" if ds_survival > 0 else ""

            # Determine supported task types based on data
            task_types = []
            if ds_labels:
                task_types.append("classification")
            if ds_survival > 0:
                task_types.append("survival_prediction")
            task_types_str = f", supported_tasks=[{', '.join(task_types)}]" if task_types else ""

            datasets_details.append(f"  - {ds_name} (id={ds_id}): {ds_count} files, type={ds_type}, labels=[{labels_str}]{survival_str}{task_types_str}")
        datasets_list = "\n".join(datasets_details)
    else:
        datasets_list = "  None"

    # Format data type distribution (overall summary only)
    wsi_count_val = data_type_dist.get("wsi", 0)
    patch_count_val = data_type_dist.get("patch", 0)
    if wsi_count_val > 0 and patch_count_val > 0:
        data_types_info = f"WSI: {wsi_count_val}, Patches: {patch_count_val}"
    elif wsi_count_val > 0:
        data_types_info = f"WSI only: {wsi_count_val}"
    elif patch_count_val > 0:
        data_types_info = f"Patches only: {patch_count_val}"
    else:
        data_types_info = "None"

    # Format trained models info (with data_level from training task)
    if trained_models:
        models_details = []
        # Batch query all training tasks to get data_level
        task_ids = list(set(m.task_id for m in trained_models if m.task_id))
        training_tasks = {}
        if task_ids:
            from backend.database.repositories import TrainingTaskRepository
            for task_id in task_ids:
                task = await TrainingTaskRepository.get_by_id(db, task_id)
                if task:
                    training_tasks[task_id] = task

        for m in trained_models:
            model_name = m.model_name
            model_id = m.model_id
            model_classes = m.classes or []
            model_task_id = m.task_id
            classes_str = ", ".join(model_classes) if model_classes else "unknown"

            # Get data_level from training task
            training_task = training_tasks.get(model_task_id)
            data_level = training_task.data_level if training_task else "unknown"

            models_details.append(f"  - {model_name} (id={model_id}): classes=[{classes_str}], data_level={data_level}, trained_on_task={model_task_id}")
        models_list = "\n".join(models_details)
        models_count = len(trained_models)
    else:
        models_list = "  None - user needs to train a model first"
        models_count = 0

    # Format user permissions info
    user_role = user.role  # "admin", "pathologist", or "guest"
    can_use_gpu_base = user.can_use_gpu()  # True for admin/pathologist, False for guest

    # Format temporary permissions if any (for non-admin users)
    # These are datasets owned by OTHER users that this user has been granted access to
    if temp_permissions:
        # Batch query all datasets at once to avoid N+1 query problem
        dataset_ids = [perm.dataset_id for perm in temp_permissions]
        datasets = await DatasetRepository.get_by_ids(db, dataset_ids)
        dataset_map = {d.dataset_id: d for d in datasets}

        temp_perms_details = []
        for perm in temp_permissions:
            dataset = dataset_map.get(perm.dataset_id)
            dataset_name = dataset.name if dataset else "Unknown Dataset"

            # Format expiration info
            expires_info = ""
            if perm.expires_at:
                expires_info = f", expires: {perm.expires_at.strftime('%Y-%m-%d %H:%M UTC')}"
            else:
                expires_info = ", no expiration"

            temp_perms_details.append(f"  - **{dataset_name}** (dataset_id={perm.dataset_id}): {perm.permission_level} access{expires_info}")
        temp_perms_list = "\n".join(temp_perms_details)
    else:
        temp_perms_list = "  None"

    # Get GPU status for system prompt
    gpu_summary = get_gpu_summary_for_prompt()

    # Format training tasks info (recent 10 tasks with summary)
    training_tasks_total = training_tasks_stats.get("total", 0)
    training_tasks_completed = training_tasks_stats.get("completed", 0)
    training_tasks_running = training_tasks_stats.get("running", 0)
    training_tasks_failed = training_tasks_stats.get("failed", 0)

    if training_tasks:
        training_tasks_details = []
        for t in training_tasks:
            created_str = t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "unknown"
            status_emoji = {"completed": "✅", "running": "🔄", "failed": "❌", "pending": "⏳"}.get(t.status, "❓")
            training_tasks_details.append(
                f"  - {status_emoji} {t.task_name} (id={t.task_id}): {t.task_type}, {t.data_level}, status={t.status}, created={created_str}"
            )
        if training_tasks_total > 10:
            training_tasks_details.append(f"  ... and {training_tasks_total - 10} more tasks")
        training_tasks_list = "\n".join(training_tasks_details)
    else:
        training_tasks_list = "  None - user has not created any training tasks yet"

    # Format inference tasks info (recent 10 tasks with summary)
    inference_tasks_total = inference_tasks_stats.get("total", 0)
    inference_tasks_completed = inference_tasks_stats.get("completed", 0)
    inference_tasks_running = inference_tasks_stats.get("running", 0)

    if inference_tasks:
        inference_tasks_details = []
        for t in inference_tasks:
            created_str = t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "unknown"
            status_emoji = {"completed": "✅", "running": "🔄", "failed": "❌", "pending": "⏳"}.get(t.status, "❓")
            inference_tasks_details.append(
                f"  - {status_emoji} {t.task_type} on {t.wsi_id} (id={t.task_id}): status={t.status}, created={created_str}"
            )
        if inference_tasks_total > 10:
            inference_tasks_details.append(f"  ... and {inference_tasks_total - 10} more tasks")
        inference_tasks_list = "\n".join(inference_tasks_details)
    else:
        inference_tasks_list = "  None - user has not run any inference tasks yet"

    # Format user data context using template
    user_data_context = format_user_data_context(
        wsi_count=wsi_count,
        data_types_info=data_types_info,
        datasets_list=datasets_list,
        models_count=models_count,
        models_list=models_list,
        training_tasks_total=training_tasks_total,
        training_tasks_completed=training_tasks_completed,
        training_tasks_running=training_tasks_running,
        training_tasks_failed=training_tasks_failed,
        training_tasks_list=training_tasks_list,
        inference_tasks_total=inference_tasks_total,
        inference_tasks_completed=inference_tasks_completed,
        inference_tasks_running=inference_tasks_running,
        inference_tasks_list=inference_tasks_list,
        gpu_summary=gpu_summary,
        user_role=user_role,
        is_admin=user.is_admin(),
        can_use_gpu_base=can_use_gpu_base,
        temp_perms_list=temp_perms_list,
    )

    # Log the user_data_context for debugging
    logger.info(f"[Chat] User data context for agent:\n{user_data_context}")

    # Add system prompt if not present
    messages = req.messages.copy()
    if not messages or messages[0].get("role") != "system":
        # Load system prompt from template file
        base_system_prompt = get_chat_system_prompt()

        system_prompt = {
            "role": "system",
            "content": base_system_prompt + user_data_context
        }
        messages.insert(0, system_prompt)

    # If conversation_id is provided, save user message to database
    # For multimodal messages, only save the text content
    if req.conversation_id and len(req.messages) > 0:
        last_user_message = req.messages[-1]
        if last_user_message.get("role") == "user":
            # Extract text content (handles both string and multimodal format)
            content = last_user_message.get("content", "")
            text_content = extract_text_from_content(content)
            message_data = {
                "conversation_id": req.conversation_id,
                "role": "user",
                "content": text_content,
            }
            await ChatRepository.add_message(db, message_data)
            await db.commit()

    # Stream AI response
    async def stream_with_persistence():
        """Stream AI response and save to database if conversation_id is provided"""
        full_response = ""
        async for chunk in stream_ai_response(messages, api_key, base_url, model):
            # Don't yield [DONE] yet - we need to send message_id first
            if chunk == "data: [DONE]\n\n":
                # Save assistant response to database and return message_id BEFORE [DONE]
                if req.conversation_id and full_response:
                    async for db_session in get_db():
                        try:
                            message_data = {
                                "conversation_id": req.conversation_id,
                                "role": "assistant",
                                "content": full_response,
                            }
                            saved_message = await ChatRepository.add_message(db_session, message_data)
                            await db_session.commit()
                            # Send message_id back to frontend so it can update the message ID
                            # This enables proper persistence of task submission status
                            if saved_message:
                                yield f"data: {json.dumps({'message_id': saved_message.id})}\n\n"
                        finally:
                            await db_session.close()
                # Now yield [DONE] after message_id has been sent
                yield chunk
            else:
                yield chunk
                # Extract content from SSE chunk
                if chunk.startswith("data: "):
                    try:
                        data = json.loads(chunk[6:])
                        if "content" in data:
                            full_response += data["content"]
                    except:
                        pass

    return StreamingResponse(
        stream_with_persistence(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
