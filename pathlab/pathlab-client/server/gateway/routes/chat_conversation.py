import json
import logging
import uuid
import httpx
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from backend.common.config import Config
from backend.database import get_db
from backend.database.repositories import ChatRepository
from backend.auth import current_active_user, User
from gateway.chat.permissions import require_conversation_access
from ..models import (
    CreateConversationRequest,
    UpdateConversationRequest,
    UpdateMessageRequest,
    AddMessageRequest,
)
from .chat_patch_inference import (
    cleanup_conversation_chat_patch_tasks,
    cleanup_chat_patch_tasks_from_message,
)

router = APIRouter(tags=["Chat & Conversations"])


@router.post("/conversations")
async def create_conversation(
    req: CreateConversationRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    conversation_id = f"conv_{uuid.uuid4().hex[:16]}"
    conversation_data = {
        "conversation_id": conversation_id,
        "user_id": str(user.id),
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
    db: AsyncSession = Depends(get_db),
):
    user_id = str(user.id)
    conversations = await ChatRepository.get_user_conversations(
        db, user_id, skip, limit
    )
    total = await ChatRepository.count_user_conversations(db, user_id)
    return {"items": [conv.to_dict() for conv in conversations], "total": total}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    conversation = await require_conversation_access(db, conversation_id, user)
    sorted_messages = sorted(conversation.messages, key=lambda m: m.id)

    variant_groups: dict[str, list] = {}
    for msg in sorted_messages:
        if msg.variant_group_id:
            variant_groups.setdefault(msg.variant_group_id, []).append(msg)

    result_messages = []
    for msg in sorted_messages:
        if msg.variant_group_id and not msg.is_active_variant:
            continue
        msg_dict = msg.to_dict()
        if msg.variant_group_id and msg.variant_group_id in variant_groups:
            siblings = sorted(variant_groups[msg.variant_group_id], key=lambda m: m.id)
            if len(siblings) > 1:
                msg_dict["variants"] = [v.to_dict() for v in siblings]
        result_messages.append(msg_dict)

    return {
        **conversation.to_dict(),
        "messages": result_messages,
    }


@router.patch("/conversations/{conversation_id}/messages/{message_id}/activate-variant")
async def activate_variant(
    conversation_id: str,
    message_id: int,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await require_conversation_access(db, conversation_id, user)
    success = await ChatRepository.activate_variant(db, message_id)
    if not success:
        raise HTTPException(
            status_code=404, detail="Message not found or not part of a variant group"
        )
    await db.commit()
    return {"message": "Variant activated"}


@router.patch("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    req: UpdateConversationRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await require_conversation_access(db, conversation_id, user)
    success = await ChatRepository.update_conversation_title(
        db, conversation_id, req.title
    )
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.commit()
    return {"conversation_id": conversation_id, "title": req.title}


@router.post("/conversations/{conversation_id}/generate-title")
async def generate_conversation_title(
    conversation_id: str,
    request: Request,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await require_conversation_access(db, conversation_id, user)

    first_message = await ChatRepository.get_conversation_first_user_message(
        db, conversation_id
    )
    if not first_message or not first_message.strip():
        raise HTTPException(status_code=400, detail="No user message found")

    api_key = request.headers.get("X-OpenRouter-API-Key")
    base_url = request.headers.get(
        "X-OpenRouter-Base-URL",
        "https://openrouter.ai/api/v1",
    )
    model = request.headers.get("X-OpenRouter-Model", "google/gemini-2.0-flash-001")

    if not api_key:
        global_settings = Config.get_global_settings()
        api_key = global_settings.get("openrouter_api_key") or ""
        base_url = global_settings.get("openrouter_base_url") or base_url
        model = global_settings.get("openrouter_model") or model

    if not api_key:
        raise HTTPException(status_code=400, detail="No API key configured")

    truncated = first_message[:300]
    title_prompt = (
        "Summarize the following message in 10 words or fewer as a concise "
        "conversation title. Output ONLY the title text, nothing else.\n\n"
        f'Message:\n"{truncated}"'
    )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": title_prompt}],
                    "max_tokens": 30,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            raw_content = data.get("choices", [{}])[0].get("message", {}).get("content")
            title = (raw_content or "").strip().strip('"').strip("'")
    except Exception as e:
        logger.error(f"Title generation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate title")

    if not title:
        title = first_message[:50]

    await ChatRepository.update_conversation_title(db, conversation_id, title)
    await db.commit()
    return {"conversation_id": conversation_id, "title": title}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await require_conversation_access(db, conversation_id, user)
    await cleanup_conversation_chat_patch_tasks(conversation_id)
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
    db: AsyncSession = Depends(get_db),
):
    await require_conversation_access(db, conversation_id, user)
    message = await ChatRepository.update_message(
        db, message_id, req.content, req.metadata
    )
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    await db.commit()
    return message.to_dict()


@router.delete("/conversations/{conversation_id}/messages/{message_id}")
async def delete_messages_from(
    conversation_id: str,
    message_id: int,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await require_conversation_access(db, conversation_id, user)
    await cleanup_chat_patch_tasks_from_message(conversation_id, message_id)
    deleted_count = await ChatRepository.delete_messages_from_id(
        db, conversation_id, message_id
    )
    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="Message not found")
    await db.commit()
    return {
        "message": f"Deleted {deleted_count} message(s)",
        "deleted_count": deleted_count,
    }


@router.post("/conversations/{conversation_id}/messages")
async def add_message(
    conversation_id: str,
    req: AddMessageRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await require_conversation_access(db, conversation_id, user)
    message_data = {
        "conversation_id": conversation_id,
        "role": req.role,
        "content": req.content,
    }
    message = await ChatRepository.add_message(db, message_data)
    await db.commit()
    return message.to_dict()
