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
from backend.database.repositories import ChatRepository
from backend.auth import current_active_user, User
from backend.auth.dependencies import check_data_ownership
from ..dependencies import logger
from ..models import ChatRequest, CreateConversationRequest

router = APIRouter(tags=["Chat & Conversations"])


async def stream_ai_response(
    messages: List[Dict[str, str]],
    api_key: str = None,
    base_url: str = None,
    model: str = None
) -> AsyncIterator[str]:
    """
    Stream AI response using OpenRouter API (OpenAI-compatible).

    Args:
        messages: Chat messages
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

    # Add system prompt if not present
    messages = req.messages.copy()
    if not messages or messages[0].get("role") != "system":
        system_prompt = {
            "role": "system",
            "content": """You are PathLab Agent, an AI assistant that helps researchers set up pathology AI training tasks.
Your role is to guide users through the training wizard step by step, explaining each option clearly.

## Training Wizard Steps

### Step 1: Task Configuration
- **Task Name**: A descriptive name (e.g., "Lung Cancer Classification")
- **Task Type**:
  - `classification`: Predict categorical labels (e.g., HSIL vs LSIL)
  - `survival_prediction`: Predict time-to-event outcomes
- **Data Level**:
  - `wsi`: WSI-level training - one label per whole slide, uses MIL aggregation
  - `patch`: Patch-level training - train on individual patches

### Step 2: Data Selection
- Select WSI slides from the library for training
- Each slide needs a label (the class to predict)
- Recommend: at least 10-20 slides per class for reasonable results

### Step 3: Preprocessing (WSI-level only)
**Patch Extraction:**
- **Tile Size**: 256, 512, or 1024 pixels (default: 512)
- **Stride**: Overlap between tiles, 0 = no overlap (default: 0)
- **Pyramid Level**: 0 = highest resolution (default: 0)

**Feature Extraction:**
| Encoder | ID | Description |
|---------|-----|-------------|
| ResNet50 | resnet50 | ImageNet pretrained, general-purpose (recommended for most tasks) |
| ViT-Large | vit_l_16 | Vision Transformer, captures global context |
| CTransPath | ctranspath | Pathology-specific pretrained |
| UNI | uni | Universal pathology foundation model (state-of-the-art) |

### Step 4: Model Configuration
**For WSI-level (Aggregators):**
| Aggregator | ID | Description |
|------------|-----|-------------|
| ABMIL | abmil | Attention-based MIL - learns patch importance (recommended) |
| MeanMIL | meanmil | Simple average pooling baseline |
| MaxMIL | maxmil | Max pooling - selects strongest signal |

**For Patch-level (Backbone Models):**
| Model | ID | Description |
|-------|-----|-------------|
| ResNet50 | resnet50 | Good balance of accuracy and speed |
| ResNet101 | resnet101 | Higher capacity, slower |
| ViT-Base | vit_base | Attention-based, base size |
| ViT-Large | vit_large | Higher capacity, needs more data |
| EfficientNet-B0 | efficientnet_b0 | Optimized for efficiency |
| EfficientNet-B4 | efficientnet_b4 | Better accuracy, more compute |

**Training Parameters:**
- **Learning Rate**: 0.0001 (default, range: 0.00001 - 0.01)
- **Epochs**: 50 (default, warning if >200)
- **Batch Size**: 1 for WSI-level (default)
- **Optimizer**: adam (default), sgd available
- **Early Stopping**: 10 epochs patience (default)

### Step 5: Training & Execution
- Review configuration summary
- Submit task to start training
- Monitor in Task Manager

## Your Role
1. Ask clarifying questions about the research goal
2. Recommend appropriate settings based on their data and goals
3. Explain trade-offs (e.g., larger tile size = more detail but fewer patches)
4. Guide them to New Task page when ready

Be concise and helpful. When recommending, always explain WHY."""
        }
        messages.insert(0, system_prompt)

    # If conversation_id is provided, save user message to database
    if req.conversation_id and len(req.messages) > 0:
        last_user_message = req.messages[-1]
        if last_user_message.get("role") == "user":
            message_data = {
                "conversation_id": req.conversation_id,
                "role": "user",
                "content": last_user_message.get("content", ""),
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
