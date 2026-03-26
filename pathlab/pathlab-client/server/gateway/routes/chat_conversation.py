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


def _build_title_generation_payload(
    *, model: str, title_prompt: str, use_local_vllm: bool
) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": title_prompt}],
        # Keep enough output room in case a provider still emits reasoning or extra text.
        "max_tokens": 512,
        "temperature": 0.3,
    }
    if use_local_vllm:
        # Qwen on vLLM enables thinking by default. Title generation is a short,
        # formatting-sensitive request, so explicitly disable thinking here.
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    return payload


def _clean_message_for_title(content: str) -> str:
    """Strip special UI-only blocks from a user message before using it for title generation."""
    cleaned = _SPECIAL_BLOCK_RE.sub("", content or "")
    # Collapse excessive whitespace left by removed blocks
    cleaned = re.sub(r"\s{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _get_title_source_message(conversation) -> str | None:
    """Pick the first user message that should drive title generation.

    For branched conversations, use the first user message after the recorded
    branch boundary instead of the original conversation's first user message.
    """

    active_messages = [
        message
        for message in sorted(conversation.messages, key=lambda msg: msg.id)
        if not message.variant_group_id or message.is_active_variant
    ]

    search_messages = active_messages
    if conversation.parent_conversation_id and conversation.branch_source_message_count:
        search_messages = active_messages[conversation.branch_source_message_count :]

    for message in search_messages:
        if message.role == "user" and (message.content or "").strip():
            return message.content

    return None


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
    source_conversation = None
    source_message_count = None
    if req.source_conversation_id:
        source_conversation = await require_conversation_access(
            db, req.source_conversation_id, user
        )
        source_message_count = sum(
            1
            for message in source_conversation.messages
            if not message.variant_group_id or message.is_active_variant
        )

    conversation_id = f"conv_{uuid.uuid4().hex[:16]}"
    conversation_data = {
        "conversation_id": conversation_id,
        "user_id": str(user.id),
        "title": req.title or "New Conversation",
        "parent_conversation_id": (
            source_conversation.conversation_id if source_conversation else None
        ),
        "branch_source_message_count": source_message_count,
    }
    await ChatRepository.create_conversation(db, conversation_data)

    if source_conversation:
        await ChatRepository.clone_messages_to_conversation(
            db, source_conversation, conversation_id
        )

    await db.commit()
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=500, detail="Conversation creation failed")
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
    conversation = await require_conversation_access(db, conversation_id, user)

    first_message = _get_title_source_message(conversation)
    if not first_message or not first_message.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "No user message found after branch point"
                if conversation.parent_conversation_id
                else "No user message found"
            ),
        )

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

    fallback_title = first_message

    if not use_local and not effective_api_key:
        logger.warning(
            f"No AI provider configured for title generation {conversation_id}; "
            "falling back to first user message"
        )
        title = fallback_title
        await ChatRepository.update_conversation_title(db, conversation_id, title)
        await db.commit()
        return {"conversation_id": conversation_id, "title": title}

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

    title = ""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if effective_api_key:
                headers["Authorization"] = f"Bearer {effective_api_key}"
            payload = _build_title_generation_payload(
                model=effective_model,
                title_prompt=title_prompt,
                use_local_vllm=use_local,
            )
            resp = await client.post(
                f"{effective_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            message = data.get("choices", [{}])[0].get("message", {})
            raw_content = message.get("content") or ""
            title = raw_content.strip().strip('"').strip("'")
    except Exception as e:
        logger.warning(
            f"Title generation failed for {conversation_id}; falling back to first user message: {e}"
        )
        title = fallback_title

    if not title:
        logger.warning(
            f"Title generation returned empty for {conversation_id}; "
            f"falling back to first user message"
        )
        title = fallback_title

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
