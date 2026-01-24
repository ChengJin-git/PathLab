"""
Chat and conversation management routes
Handles AI chat, conversation persistence, and task parsing
"""
import os
import json
import uuid
import httpx
from typing import List, Dict, AsyncIterator
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.database.repositories import ChatRepository, WSIRepository
from backend.auth import current_active_user, User
from backend.auth.dependencies import check_data_ownership
from ..dependencies import logger
from ..models import ChatRequest, CreateConversationRequest

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
        api_key: OpenRouter API key (from request header or env)
        base_url: OpenRouter base URL (from request header or env)
        model: Model name (from request header or env)
    """
    # Use provided config or fall back to environment variables
    openrouter_api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
    openrouter_base_url = base_url or os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_model = model or os.environ.get("OPENROUTER_MODEL", "qwen/qwen3-vl-235b-a22b-instruct")

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


@router.post("/chat")
async def chat_with_ai(
    req: ChatRequest,
    request: Request,
    user: User = Depends(current_active_user),
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
    # Admin users can see all data, regular users only see their own
    user_id_filter = None if user.is_admin() else str(user.id)
    stats = await WSIRepository.get_chat_context_stats(db, user_id=user_id_filter)

    # Format user data context for System Prompt
    wsi_count = stats["total_count"]
    labels_count = stats["labels"]
    datasets = stats["datasets"]
    data_type_dist = stats["data_types"]

    if labels_count:
        labels_list = ", ".join([f"{label} ({count} images)" for label, count in labels_count.items()])
    else:
        labels_list = "None"

    if datasets:
        datasets_list = ", ".join([f"{d['dataset_name']} ({d['file_count']} files)" for d in datasets])
    else:
        datasets_list = "None"

    # Format data type distribution
    wsi_count_val = data_type_dist.get("wsi", 0)
    patch_count_val = data_type_dist.get("patch", 0)
    if wsi_count_val > 0 and patch_count_val > 0:
        data_types_info = f"WSI: {wsi_count_val}, Patches: {patch_count_val}"
    elif wsi_count_val > 0:
        data_types_info = f"WSI only: {wsi_count_val} (no patches)"
    elif patch_count_val > 0:
        data_types_info = f"Patches only: {patch_count_val} (no WSI)"
    else:
        data_types_info = "None"

    user_data_context = f"""
## USER'S CURRENT DATA

The user has the following data available:
- **Total images**: {wsi_count}
- **Data types**: {data_types_info}
- **Available labels**: {labels_list}
- **Datasets**: {datasets_list}

IMPORTANT: When recommending images, offering label choices, or asking about data:
- ONLY suggest labels and datasets that actually exist in the user's data above
- ONLY offer data type options (WSI/Patches) that the user actually has
- If user only has patches, do NOT ask about WSI - skip directly to patches
- If user only has WSI, do NOT ask about patches - skip directly to WSI
- If user has no data, guide them to upload data first
- Tailor your [OPTIONS] to match the user's actual labels and datasets
"""

    # Add system prompt if not present
    messages = req.messages.copy()
    if not messages or messages[0].get("role") != "system":
        base_system_prompt = """You are PathLab Agent, a friendly AI assistant for pathology research.

## CRITICAL RULES

1. **BE CONVERSATIONAL**: Short responses (2-4 sentences). One question at a time.
2. **USE INTERACTIVE ELEMENTS**: Use [OPTIONS] for choices, [TASK_CONFIG] for final configuration.
3. **PROGRESSIVE FLOW**: Gather info step by step, then generate config.
4. **USER-FRIENDLY LANGUAGE**: Always use natural, readable text. NO underscores, NO technical codes.
5. **USE USER'S ACTUAL DATA**: Only suggest labels and datasets that exist in the user's data (see USER'S CURRENT DATA section).

## INTERACTIVE ELEMENTS

### Options (for user choices)
When offering choices, use this EXACT format with human-readable text:
```
What would you like to predict?

[OPTIONS]
- Classify disease types (e.g., tumor vs normal)
- Predict patient survival outcomes
- Other (please describe)
[/OPTIONS]
```

IMPORTANT for [OPTIONS]:
- Each option is ONE LINE starting with "- "
- Use natural language, NOT technical codes like "classification" or "breast_cancer"
- Good: "Breast cancer", "Lung tissue", "Show all images"
- Bad: "breast_cancer", "lung_tissue", "show_all"
- When asking about labels/categories, use the actual labels from USER'S CURRENT DATA

### Task Configuration (when ready to submit)
After gathering all info, output the final config:
```
Here's your training configuration:

[TASK_CONFIG]
{
  "task_name": "Lung Cancer Classification",
  "task_type": "classification",
  "data_level": "wsi",
  "tile_size": 512,
  "encoder": "resnet50",
  "aggregator": "abmil",
  "learning_rate": 0.0001,
  "epochs": 50,
  "batch_size": 1,
  "optimizer": "adam"
}
[/TASK_CONFIG]

You can edit any field above, then click "Start Training" when ready.
```

## CONVERSATION FLOWS

### Training Flow
1. Ask what they want to predict → use [OPTIONS] with friendly descriptions
2. Confirm which dataset/labels to use (based on USER'S CURRENT DATA)
3. Ask speed vs quality preference → use [OPTIONS]
4. Generate [TASK_CONFIG] with recommended settings

### Browse Images Flow
When user wants to browse/analyze images (WSI or patches):
1. Ask what they're looking for → use [OPTIONS] based on their actual labels
2. **SKIP data type question if user only has one type** (check USER'S CURRENT DATA → Data types)
   - If "Patches only" → directly work with patches, do NOT offer WSI option
   - If "WSI only" → directly work with WSI, do NOT offer patches option
   - If both → ask about data type preference using [OPTIONS]
3. Recommend images using [IMAGE_RECOMMENDATION] format:

```
Based on your needs, here are some recommended images:

[IMAGE_RECOMMENDATION]
{
  "query": "lung cancer images with high confidence predictions",
  "filters": {
    "label": "lung",
    "has_predictions": true,
    "data_type": "wsi"
  },
  "reason": "These images have AI predictions with high confidence scores"
}
[/IMAGE_RECOMMENDATION]
```

## CONFIGURATION REFERENCE

**task_type**: classification, survival_prediction
**data_level**: wsi, patch
**tile_size**: 256, 512, 1024 (default: 512)
**encoder**: resnet50 (fast), uni (best), ctranspath, vit_l_16
**aggregator** (for wsi): abmil (recommended), meanmil, maxmil
**learning_rate**: 0.0001 (default)
**epochs**: 50 (default)
**batch_size**: 1 for wsi, 32 for patch
**optimizer**: adam, sgd

## ERROR HANDLING

If user reports an error after submitting, help them fix it:
- Invalid parameter values → suggest correct values
- Missing required fields → explain what's needed
- API errors → explain in simple terms

## NEVER DO
- Output long explanations before user asks
- Skip the [OPTIONS] format when offering choices
- Use underscores or technical codes in [OPTIONS] (use natural language!)
- Generate [TASK_CONFIG] before gathering enough info
- Suggest labels or datasets that don't exist in the user's data
- Offer WSI options when user only has patches (check "Data types" in USER'S CURRENT DATA)
- Offer patch options when user only has WSI
- Ask about data type when user only has one type"""

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

        # Save assistant response to database
        if req.conversation_id and full_response:
            async for db_session in get_db():
                try:
                    message_data = {
                        "conversation_id": req.conversation_id,
                        "role": "assistant",
                        "content": full_response,
                    }
                    await ChatRepository.add_message(db_session, message_data)
                    await db_session.commit()
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
