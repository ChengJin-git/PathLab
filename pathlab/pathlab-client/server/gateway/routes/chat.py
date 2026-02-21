"""
Chat and conversation management routes
Handles AI chat, conversation persistence, and task parsing
"""
import json
import os
import uuid
import httpx
from typing import List, Dict, AsyncIterator, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.database.repositories import ChatRepository, WSIRepository, TrainedModelRepository, DatasetPermissionRepository, DatasetRepository, TrainingTaskRepository, AITaskRepository
from backend.database.models import TrainingTask, DataGroup
from backend.auth import current_active_user, User
from backend.auth.dependencies import check_data_ownership, get_user_id_filter
from backend.common.config import Config
from backend.common.gpu_utils import get_gpu_summary_for_prompt
from ..dependencies import logger
from ..prompts import get_chat_system_prompt, format_user_data_context
from ..models import ChatRequest, CreateConversationRequest, UpdateMessageRequest, AddMessageRequest

router = APIRouter(tags=["Chat & Conversations"])

# Include feedback sub-router
from .chat_feedback import router as chat_feedback_router
router.include_router(chat_feedback_router)


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
    openrouter_model = model or global_settings.get("openrouter_model") or os.environ.get("OPENROUTER_MODEL", "qwen/qwen3.5-plus-02-15")

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

    local_failed = False
    if use_local:
        # Use local vLLM
        # Auto-detect model if not specified
        effective_model = local_vllm_model or detected_model
        if not effective_model:
            logger.error("No model specified and auto-detect failed, falling back to OpenRouter")
            local_failed = True
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
                logger.warning(f"Local vLLM error: {e}, falling back to OpenRouter")
                local_failed = True
                # Fall through to OpenRouter

    # Fallback to OpenRouter
    if local_failed:
        logger.info("Attempting fallback to OpenRouter...")

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

    # Sort messages by id to ensure chronological order (defense-in-depth)
    sorted_messages = sorted(conversation.messages, key=lambda m: m.id)
    return {
        **conversation.to_dict(),
        "messages": [msg.to_dict() for msg in sorted_messages]
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

    # Fetch user's temporary dataset permissions (for non-admin users)
    # Need this first to pass elevated_dataset_ids to get_chat_context_stats
    temp_permissions = []
    elevated_dataset_ids = None
    if not user.is_admin():
        temp_permissions = await DatasetPermissionRepository.get_valid_by_user(db, str(user.id))
        if temp_permissions:
            elevated_dataset_ids = [perm.dataset_id for perm in temp_permissions]

    # Fetch user's data overview for context (single optimized query)
    # Pass elevated_dataset_ids so that temporarily authorized datasets are included
    stats = await WSIRepository.get_chat_context_stats(
        db, user_id=user_id_filter, elevated_dataset_ids=elevated_dataset_ids
    )

    # Fetch user's trained models
    trained_models = await TrainedModelRepository.get_all(db, limit=100, offset=0, user_id=user_id_filter)

    # Fetch user's training tasks (recent 10 for context, with counts)
    training_tasks = await TrainingTaskRepository.get_all(db, limit=10, offset=0, user_id=user_id_filter)
    training_tasks_stats = await TrainingTaskRepository.get_status_counts(db, user_id=user_id_filter)

    # Fetch user's inference tasks (recent 10 for context, with counts)
    inference_tasks = await AITaskRepository.get_recent(db, limit=10, user_id=user_id_filter)
    inference_tasks_stats = await AITaskRepository.get_status_counts(db, user_id=user_id_filter)

    # Format user data context for System Prompt
    wsi_count = stats["total_count"]
    datasets = stats["datasets"]
    data_type_dist = stats["data_types"]

    # Format datasets with detailed info (data_type and labels per dataset)
    # Each dataset has its own labels and survival data - do NOT show global labels to avoid confusion
    # Datasets are now marked with access_type: "own" (user's own) or "elevated" (temporary permission)
    if datasets:
        datasets_details = []
        for d in datasets:
            ds_name = d['dataset_name']
            ds_id = d.get('dataset_id', 'unknown')
            ds_count = d['file_count']
            ds_type = d.get('data_type', 'unknown')
            ds_labels = d.get('labels', {})
            ds_survival = d.get('survival_count', 0)
            ds_event_status = d.get('event_status', {})
            ds_has_splits = d.get('has_predefined_splits', False)
            ds_access_type = d.get('access_type', 'own')

            # Build info parts
            labels_str = ", ".join([f"{lbl}({cnt})" for lbl, cnt in ds_labels.items()]) if ds_labels else "none"

            # Format survival data with event_status distribution
            if ds_survival > 0 and ds_event_status:
                event_count = ds_event_status.get('event', 0)
                censored_count = ds_event_status.get('censored', 0)
                survival_str = f", survival_data={ds_survival} (event={event_count}, censored={censored_count})"
            elif ds_survival > 0:
                survival_str = f", survival_data={ds_survival}"
            else:
                survival_str = ""

            splits_str = ", has_predefined_splits=true" if ds_has_splits else ""

            # Determine supported task types based on data
            task_types = []
            if ds_labels:
                task_types.append("classification")
            if ds_survival > 0:
                task_types.append("survival")
            task_types_str = f", supported_tasks=[{', '.join(task_types)}]" if task_types else ""

            # For WSI datasets, scan feature cache to find available extractors (for external validation compatibility)
            available_extractors_str = ""
            if ds_type == "wsi":
                # Get WSI IDs for this dataset
                wsi_ids = await DatasetRepository.get_wsi_ids(db, ds_id)
                if wsi_ids:
                    first_wsi_id = wsi_ids[0]
                    features_root = Config.get_uploads_dir() / "features"
                    available_extractors = []
                    if features_root.exists():
                        for extractor_dir in features_root.iterdir():
                            if extractor_dir.is_dir():
                                for params_hash_dir in extractor_dir.iterdir():
                                    if params_hash_dir.is_dir():
                                        feat_file = params_hash_dir / f"{first_wsi_id}.pt"
                                        if feat_file.exists():
                                            available_extractors.append(extractor_dir.name)
                                            break  # Found for this extractor, move to next
                    if available_extractors:
                        available_extractors_str = f", available_extractors=[{', '.join(available_extractors)}]"

            # Add access type marker for elevated (temporary permission) datasets
            access_marker = " [ELEVATED ACCESS - temporary permission]" if ds_access_type == "elevated" else ""

            datasets_details.append(f"  - {ds_name} (dataset_id={ds_id}){access_marker}: {ds_count} files, type={ds_type}, labels=[{labels_str}]{survival_str}{splits_str}{task_types_str}{available_extractors_str}")
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

    # Format trained models info (with detailed info for external validation)
    # Embedding dimension mapping for feature extractors
    EXTRACTOR_EMBED_DIM = {
        "resnet50": 2048, "vit_l_16": 1024, "conch": 512, "uni": 1024, "uni2": 1536,
        "virchow": 1280, "virchow2": 1280, "plip": 512, "phikon": 1024, "phikon2": 1024,
        "patho_clip": 512, "openmidnight": 1536, "conch15": 512, "H-Optimus-1": 1536,
        "H-Optimus-0": 1536, "mSTAR": 1024, "GPFM": 1024,
    }

    if trained_models:
        models_details = []
        # Batch query all training tasks to get detailed info with eager loading
        task_ids = list(set(m.task_id for m in trained_models if m.task_id))
        training_tasks_map = {}
        if task_ids:
            from sqlalchemy import select
            # Eager load data_group and datasets to avoid lazy loading issues
            stmt = select(TrainingTask).options(
                selectinload(TrainingTask.data_group).selectinload(DataGroup.datasets)
            ).where(TrainingTask.task_id.in_(task_ids))
            result = await db.execute(stmt)
            tasks = result.scalars().all()
            for task in tasks:
                training_tasks_map[task.task_id] = task

        for m in trained_models:
            model_name = m.model_name
            model_id = m.model_id
            model_classes = m.classes or []
            model_task_id = m.task_id
            model_feature_extractor = m.feature_extractor or "unknown"
            classes_str = ", ".join(model_classes) if model_classes else "none"

            # Get data_type and task_type from training task's DataGroup
            training_task = training_tasks_map.get(model_task_id)
            training_dataset_name = None
            if training_task and training_task.data_group:
                data_type = training_task.data_group.data_type
                task_type = training_task.data_group.task_type
                # Get the dataset name from the data group
                if training_task.data_group.datasets:
                    # Assuming one dataset per group for training tasks
                    training_dataset_name = training_task.data_group.datasets[0].name
            else:
                data_type = "unknown"
                task_type = "unknown"

            # Get embedding dimension for WSI models
            embed_dim = EXTRACTOR_EMBED_DIM.get(model_feature_extractor, 0)

            # Build model info string
            info_parts = [
                f"id={model_id}",
                f"task_type={task_type}",
                f"data_type={data_type}",
            ]

            # Add classes for classification models
            if model_classes:
                info_parts.append(f"classes=[{classes_str}]")

            # Add feature extractor info for WSI models
            if data_type == "wsi" and model_feature_extractor != "unknown":
                info_parts.append(f"feature_extractor={model_feature_extractor}")
                if embed_dim > 0:
                    info_parts.append(f"embedding_dim={embed_dim}")

            # Add training dataset name for external validation overlap detection
            if training_dataset_name:
                info_parts.append(f"trained_on_dataset={training_dataset_name}")

            info_parts.append(f"trained_on_task={model_task_id}")

            models_details.append(f"  - {model_name} ({', '.join(info_parts)})")

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
            # Get task_type and data_type from DataGroup relationship
            if t.data_group:
                task_type = t.data_group.task_type
                data_type = t.data_group.data_type
            else:
                task_type = "unknown"
                data_type = "unknown"
            training_tasks_details.append(
                f"  - [{t.status.upper()}] {t.task_name} (id={t.task_id}): {task_type}, {data_type}, created={created_str}"
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
            inference_tasks_details.append(
                f"  - [{t.status.upper()}] {t.task_type} on {t.wsi_id} (id={t.task_id}): created={created_str}"
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
    # logger.info(f"[Chat] User data context for agent:\n{user_data_context}")

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
