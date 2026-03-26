import json
import os
import re
import uuid
import httpx
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common import get_logger

logger = get_logger("ChatConversation")

# Regex patterns for special UI-only blocks that should be stripped before
# sending user message content to the title-generation AI prompt.
_SPECIAL_BLOCK_RE = re.compile(
    r"\["
    r"(?:CSV_PREVIEW|OPTIONS|TASK_CONFIG|CONTEXT_LIMIT|RESPONSE_TRUNCATED"
    r"|NAVIGATE|IMAGE_RECOMMENDATION|CSV_ACTION|METRIC_CONFIG|CHART_CONFIG"
    r"|QUICK_ANALYSIS_CONFIG|VOICE_CONTROL|MODEL_LIST|PATCH_INFERENCE"
    r"|PDF_CONTEXT|TRAINING_RECOMMENDATION_CONTEXT|ANALYSIS_CONFIG)"
    r"\][\s\S]*?\[/"
    r"(?:CSV_PREVIEW|OPTIONS|TASK_CONFIG|CONTEXT_LIMIT|RESPONSE_TRUNCATED"
    r"|NAVIGATE|IMAGE_RECOMMENDATION|CSV_ACTION|METRIC_CONFIG|CHART_CONFIG"
    r"|QUICK_ANALYSIS_CONFIG|VOICE_CONTROL|MODEL_LIST|PATCH_INFERENCE"
    r"|PDF_CONTEXT|TRAINING_RECOMMENDATION_CONTEXT|ANALYSIS_CONFIG)"
    r"\]",
    re.IGNORECASE,
)


def _clean_message_for_title(content: str) -> str:
    """Strip special UI-only blocks from a user message before using it for title generation."""
    cleaned = _SPECIAL_BLOCK_RE.sub("", content or "")
    # Collapse excessive whitespace left by removed blocks
    cleaned = re.sub(r"\s{3,}", "\n\n", cleaned)
    return cleaned.strip()

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
from .chat_llm_client import _check_local_vllm_available

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

    # ── Model selection: local vLLM → OpenRouter (mirrors stream_ai_response logic) ──
    global_settings = Config.get_global_settings()

    # OpenRouter settings from headers (user's client-side config) or global settings
    header_api_key = request.headers.get("X-OpenRouter-API-Key") or ""
    header_base_url = request.headers.get("X-OpenRouter-Base-URL") or ""
    header_model = request.headers.get("X-OpenRouter-Model") or ""

    openrouter_api_key = (
        header_api_key
        or global_settings.get("openrouter_api_key")
        or os.environ.get("OPENROUTER_API_KEY", "")
    )
    openrouter_base_url = (
        header_base_url
        or global_settings.get("openrouter_base_url")
        or os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    )
    openrouter_model = (
        header_model
        or global_settings.get("openrouter_model")
        or os.environ.get("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")
    )

    # Local vLLM settings
    local_vllm_enabled = global_settings.get("local_vllm_enabled", False)
    local_vllm_base_url = global_settings.get(
        "local_vllm_base_url", "http://127.0.0.1:8000/v1"
    )
    local_vllm_model = global_settings.get("local_vllm_model", "")
    local_vllm_api_key = global_settings.get("local_vllm_api_key", "")

    # Determine effective endpoint: prefer local vLLM when enabled and available
    use_local = False
    effective_base_url: str = str(openrouter_base_url or "")
    effective_api_key: str = str(openrouter_api_key or "")
    effective_model: str = str(openrouter_model or "")

    if local_vllm_enabled and local_vllm_base_url:
        is_available, detected_model = await _check_local_vllm_available(
            local_vllm_base_url, local_vllm_api_key
        )
        if is_available:
            local_model_resolved = local_vllm_model or detected_model
            if local_model_resolved:
                use_local = True
                effective_base_url = local_vllm_base_url
                effective_api_key = local_vllm_api_key
                effective_model = local_model_resolved
                logger.info(
                    f"Title generation using local vLLM at {local_vllm_base_url}, "
                    f"model={effective_model!r}"
                )
            else:
                logger.warning(
                    "Local vLLM available but no model resolved; falling back to OpenRouter"
                )
        else:
            logger.warning(
                "Local vLLM server offline for title generation; falling back to OpenRouter"
            )

    if not use_local and not effective_api_key:
        raise HTTPException(status_code=400, detail="No API key configured")

    # Strip special UI-only blocks (e.g. [CSV_PREVIEW], [OPTIONS]) so the AI
    # receives only the natural-language portion of the user's first message.
    cleaned_message = _clean_message_for_title(first_message)
    if not cleaned_message:
        # If cleaning removed everything (e.g. pure CSV upload), fall back to
        # the raw truncated content so we still have something to work with.
        cleaned_message = first_message

    truncated = cleaned_message[:300]
    title_prompt = (
        "Summarize the following message in 10 words or fewer as a concise "
        "conversation title. Output ONLY the title text, nothing else.\n\n"
        f'Message:\n"{truncated}"'
    )

    logger.info(
        f"Generating title for {conversation_id} using "
        f"{'local vLLM' if use_local else 'OpenRouter'}, "
        f"model={effective_model!r}, "
        f"truncated_len={len(truncated)}, first_60={truncated[:60]!r}"
    )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if effective_api_key:
                headers["Authorization"] = f"Bearer {effective_api_key}"
            resp = await client.post(
                f"{effective_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json={
                    "model": effective_model,
                    "messages": [{"role": "user", "content": title_prompt}],
                    # Use enough tokens for thinking models to complete their <think> block
                    # before emitting the actual title (30 was too small and caused truncation).
                    "max_tokens": 512,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            message = data.get("choices", [{}])[0].get("message", {})
            raw_content = message.get("content") or ""
            logger.info(
                f"Title generation raw_content for {conversation_id}: {raw_content!r}"
            )

            # For thinking/reasoning models the API puts the chain-of-thought in a
            # separate `reasoning_content` field and the final answer in `content`.
            # When that field is present and non-empty we can use `content` directly.
            reasoning_content = message.get("reasoning_content") or ""
            if reasoning_content.strip():
                # `content` is already the post-reasoning answer
                cleaned_content = raw_content.strip()
            else:
                # Strip <think>...</think> blocks (XML-tagged thinking models, e.g. QwQ)
                cleaned_content = re.sub(
                    r"<think>[\s\S]*?</think>", "", raw_content, flags=re.IGNORECASE
                ).strip()
                # Strip unclosed <think> block if reasoning was cut off mid-stream
                cleaned_content = re.sub(
                    r"<think>[\s\S]*$", "", cleaned_content, flags=re.IGNORECASE
                ).strip()

            # Safety truncation: DB column is VARCHAR(500); titles should be short anyway
            title = cleaned_content.strip('"').strip("'")[:100]
    except Exception as e:
        logger.error(f"Title generation failed for {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate title")

    if not title:
        logger.warning(
            f"Title generation returned empty for {conversation_id}; "
            f"falling back to message truncation"
        )
        title = cleaned_message[:50]

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
