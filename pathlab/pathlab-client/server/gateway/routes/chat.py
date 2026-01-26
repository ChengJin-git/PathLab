"""
Chat and conversation management routes
Handles AI chat, conversation persistence, and task parsing
"""
import os
import json
import uuid
import httpx
from typing import List, Dict, AsyncIterator, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import ChatRepository, WSIRepository, TrainedModelRepository, DatasetPermissionRepository, DatasetRepository
from backend.auth import current_active_user, User
from backend.auth.dependencies import check_data_ownership, get_user_id_filter
from backend.common.config import Config
from backend.common.gpu_utils import get_gpu_summary_for_prompt
from ..dependencies import logger
from ..prompts import get_chat_system_prompt
from ..models import ChatRequest, CreateConversationRequest, UpdateMessageRequest, AddMessageRequest

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


async def stream_ai_response(
    messages: List[Dict],
    api_key: str = None,
    base_url: str = None,
    model: str = None
) -> AsyncIterator[str]:
    """
    Stream AI response using OpenRouter API (OpenAI-compatible).
    Supports both text-only and multimodal messages.

    Args:
        messages: Chat messages (text or multimodal format)
        api_key: OpenRouter API key (from global settings or env)
        base_url: OpenRouter base URL (from global settings or env)
        model: Model name (from global settings or env)
    """
    # Priority: provided config > global settings > environment variables
    global_settings = Config.get_global_settings()
    openrouter_api_key = api_key or global_settings.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY")
    openrouter_base_url = base_url or global_settings.get("openrouter_base_url") or os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_model = model or global_settings.get("openrouter_model") or os.environ.get("OPENROUTER_MODEL", "qwen/qwen3-vl-235b-a22b-instruct")

    if not openrouter_api_key:
        # Return error message if no API key is configured
        error_msg = """**AI Configuration Required**

To use the AI assistant, please configure your OpenRouter API key:

1. Click **Settings** in the left sidebar
2. Enter your **OpenRouter API Key** in the configuration form
3. Click **Save Settings**

**Get your API key:** [OpenRouter Console](https://openrouter.ai/keys)

After saving, return here and start chatting!"""

        # Output error message instantly (no typing effect for errors)
        yield f"data: {json.dumps({'content': error_msg})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Real OpenRouter API call with streaming
    try:
        logger.info(f"Using OpenRouter API with model: {openrouter_model}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{openrouter_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": openrouter_model,
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

    # Format trained models info
    if trained_models:
        models_details = []
        for m in trained_models:
            model_name = m.model_name
            model_id = m.model_id
            model_classes = m.classes or []
            model_task_id = m.task_id
            classes_str = ", ".join(model_classes) if model_classes else "unknown"
            models_details.append(f"  - {model_name} (id={model_id}): classes=[{classes_str}], trained_on_task={model_task_id}")
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

    user_data_context = f"""
## USER'S CURRENT DATA

The user has the following data available:
- **Total images**: {wsi_count}
- **Data types (overall)**: {data_types_info}
- **Datasets** (IMPORTANT - each dataset has its own data_type and labels, use ONLY these):
{datasets_list}

## USER'S TRAINED MODELS

The user has **{models_count}** trained model(s) available for inference:
{models_list}

## SYSTEM STATUS

{gpu_summary}

## USER'S PERMISSIONS

- **Role**: {user_role}
- **Data visibility**: {"Can see ALL users' data" if user.is_admin() else "Can only see OWN data (plus datasets with temporary access below)"}
- **Can use GPU operations by default**: {"Yes" if can_use_gpu_base else "No (Guest role - requires admin-granted permission)"}
- **Temporary elevated permissions** (admin-granted access to OTHER users' datasets):
{temp_perms_list}

**Permission Model Explanation**:
- **Admin**: Can see all data, can use GPU on any dataset
- **Pathologist**: Can only see own data, can use GPU on own datasets (or datasets with temporary access)
- **Guest**: Can only see own data, CANNOT use GPU unless granted temporary access to specific datasets
- **Temporary Permission**: Admin can grant access to specific datasets, which includes BOTH data visibility AND GPU operations

CRITICAL RULES FOR DATA SELECTION:
1. **ALWAYS select by DATASET, not individual files** - when user wants to train or browse, ask which dataset to use
2. **Respect each dataset's data_type** - if a dataset is type=patch, it contains patches; if type=wsi, it contains WSI
3. **ONLY suggest labels that exist in the SELECTED dataset** - each dataset has different labels, check the labels list for that specific dataset
4. **DO NOT mix labels from different datasets** - IM/Not_IM are WSI labels, MSIH/nonMSIH are patch labels
5. **DO NOT invent labels or datasets** - only use what's listed above
6. **If user has no data or wants to upload new data** - follow the "Upload New Data Flow" to guide them through the process
7. **SMART DATASET FILTERING** - When user mentions specific keywords (organ, disease, tissue type), ONLY show relevant datasets:
   - If user says "胃" (gastric/stomach), only show datasets with gastric-related names
   - If user says "肺" (lung), only show lung-related datasets
   - If NO dataset matches the user's description, offer "Upload new data" option
   - Example: User says "胃活检切片" → only show GC_IM_Detection if it exists, NOT CRC-MSI or Liver_OS

CRITICAL RULES FOR TASK TYPE:
8. **INFER task_type from user's message FIRST**:
   - If user says "分类" / "classification" / "检测是否有X" / "区分X和Y" → task_type = classification
   - If user says "生存" / "survival" / "预后" / "预测存活" → task_type = survival_prediction
   - If user's intent is clear, DO NOT ask again - just confirm: "好的，我们来做分类任务"
9. **AUTO-DETECT task_type from dataset's supported_tasks** (only if not already inferred from user):
   - If dataset has labels (labels=[...]) → it supports "classification"
   - If dataset has survival_data > 0 → it supports "survival_prediction"
   - If dataset supports ONLY ONE task type → use that type directly, DO NOT ask user
   - If dataset supports BOTH task types AND user hasn't specified → ask user which one they want
10. **DO NOT ask about task type if already determined** - either from user's message or from dataset constraints

CRITICAL RULES FOR TEST MODEL / INFERENCE:
11. **CHECK trained models FIRST** - if user wants to test/run inference but has NO trained models, reject the request and guide them to train a model first
12. **List available models** - when user wants to test, show them their available trained models using [OPTIONS]

CRITICAL RULES FOR PERMISSION CHECKING:
13. **Data visibility is role-based**:
    - Users can ONLY see datasets listed in USER'S CURRENT DATA above
    - The datasets shown are already filtered based on user's permissions
    - If a dataset is NOT listed, the user CANNOT access it
14. **GPU Operations require permission** - Training, AI analysis, and external validation are GPU operations
15. **Check user role and permissions BEFORE offering GPU tasks**:
    - If user is **Admin** → can use GPU operations on any dataset they can see
    - If user is **Pathologist** → can use GPU operations on their OWN datasets (or datasets with temporary access)
    - If user is **Guest** → CANNOT use GPU unless they have temporary elevated permission for the specific dataset
16. **REJECT unauthorized requests politely**:
    - If Guest wants to train/analyze but has NO temporary permission for that dataset → reject and explain:
      "I see you're a Guest user and don't have GPU access for this dataset. Training and AI analysis require Pathologist or Admin access. Please contact an administrator to request temporary access if needed."
    - If Guest HAS temporary permission for specific datasets → allow those datasets, reject others
    - If Pathologist tries to access another user's dataset without temporary permission → explain they can only access their own data
17. **Mention temporary permissions when relevant**:
    - If user has temporary permission, acknowledge it:
      "I see you have temporary elevated access for [Dataset Name] (expires: [date]). Let's proceed with your task..."
    - This temporary access grants BOTH data visibility AND GPU operation rights
"""

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
            yield chunk
            # Extract content from SSE chunk
            if chunk.startswith("data: ") and chunk != "data: [DONE]\n\n":
                try:
                    data = json.loads(chunk[6:])
                    if "content" in data:
                        full_response += data["content"]
                except:
                    pass

        # Save assistant response to database and return message_id
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

    return StreamingResponse(
        stream_with_persistence(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
