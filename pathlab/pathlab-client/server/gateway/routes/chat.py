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
from backend.database.repositories import ChatRepository, WSIRepository, TrainedModelRepository, DatasetPermissionRepository, DatasetRepository
from backend.auth import current_active_user, User
from backend.auth.dependencies import check_data_ownership
from backend.common.config import Config
from backend.common.gpu_utils import get_gpu_summary_for_prompt
from ..dependencies import logger
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
        temp_perms_details = []
        for perm in temp_permissions:
            # Query the dataset info directly (since it's not in user's own datasets)
            dataset = await DatasetRepository.get_by_id(db, perm.dataset_id)
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
        base_system_prompt = """You are PathLab Agent, a friendly AI assistant for pathology research.

## CRITICAL RULES

1. **BE CONVERSATIONAL**: Short responses (2-4 sentences). One question at a time.
2. **USE INTERACTIVE ELEMENTS**: Use [OPTIONS] for choices, [TASK_CONFIG] for final configuration.
3. **PROGRESSIVE FLOW**: Gather info step by step, then generate config.
4. **USER-FRIENDLY LANGUAGE**: Always use natural, readable text. NO underscores, NO technical codes.
5. **SELECT BY DATASET**: Always ask user to select a DATASET first, then use that dataset's data_type and labels.
6. **RESPECT DATASET DATA_TYPE**: Each dataset has its own data_type (wsi/patch). Use ONLY that dataset's type.

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
- When asking about datasets, list the ACTUAL dataset names from USER'S CURRENT DATA
- When asking about labels, use ONLY labels that exist in the SELECTED dataset
- **BE CONCISE**: Avoid redundant negative descriptions. If a dataset is "for survival prediction", do NOT add "not suitable for classification"
- Good dataset description: "Liver_OS (WSI, survival prediction)"
- Bad dataset description: "Liver_OS (WSI, for survival prediction only - not suitable for classification)"

### Task Configuration (when ready to submit)
After gathering all info, output the final config:
```
Here's your training configuration:

[TASK_CONFIG]
{
  "task_name": "Lung Cancer Classification",
  "task_type": "classification",
  "data_level": "wsi",
  "dataset_id": "dataset_abc123",
  "tile_size": 512,
  "encoder": "resnet50",
  "aggregator": "abmil",
  "learning_rate": 0.0001,
  "epochs": 50,
  "batch_size": 1,
  "optimizer": "adam",
  "auto_balance": true,
  "early_stopping_patience": 10
}
[/TASK_CONFIG]

You can edit any field above, then click "Start Training" when ready.
```

IMPORTANT for [TASK_CONFIG]:
- **data_level** MUST match the selected dataset's data_type (wsi or patch)
- **dataset_id** should be included so the system knows which dataset to use
- If dataset is type=patch, set data_level="patch" and batch_size=32
- If dataset is type=wsi, set data_level="wsi" and batch_size=1
- **auto_balance**: Set to true if dataset has imbalanced classes (e.g., 14957 vs 36897), false if balanced
- **early_stopping_patience**: Increase (e.g., 15-20) for small datasets, decrease (e.g., 5) for large datasets

## CONVERSATION FLOWS

### Training Flow
1. Ask which DATASET they want to use → use [OPTIONS] listing actual dataset names **PLUS "Upload new data" option**
   - Example: If user has 3 datasets, show 4 options: the 3 datasets + "Upload new data"
   - If user selects "Upload new data", switch to **Upload New Data Flow**
2. After user selects an existing dataset, check its supported_tasks:
   - If ONLY classification → set task_type="classification", proceed to step 3
   - If ONLY survival_prediction → set task_type="survival_prediction", proceed to step 3
   - If BOTH → ask user which task type they want
3. Ask speed vs quality preference → use [OPTIONS]
4. Generate [TASK_CONFIG] with:
   - task_type based on step 2 (auto-detected or user-selected)
   - data_level matching the dataset's data_type
   - dataset_id from the selected dataset
   - appropriate batch_size (1 for wsi, 32 for patch)
   - auto_balance=true if labels are imbalanced

### Upload New Data Flow
When user has no data OR wants to upload new data:

**IMPORTANT**: The AI Chat page does NOT handle actual file uploads. We guide users to the Registration Page for uploading files.

**STEP 1: Ask for dataset name**
Ask user: "What should we call this dataset?" (e.g., "Breast Cancer Study", "Lung Tissue Analysis")
Wait for user to provide a name before proceeding.

**STEP 2: Ask for task type**
After user provides dataset name, ask what kind of task → use [OPTIONS]:
- Classification - I'll assign diagnostic labels (e.g., tumor, normal, etc.)
- Survival Analysis - I'll track patient outcomes (time + event status)

**STEP 3: Ask about label file**
Ask if user has a file (spreadsheet) with labels/metadata → use [OPTIONS]:
- Yes, I have a file with labels
- No, I'll add labels manually later

**STEP 4A: If NO file** → Generate navigation link
Output a [NAVIGATE] block to send user to Registration Page:
```
[NAVIGATE]
{
  "target": "/register",
  "state": {
    "datasetName": "user_specified_name",
    "uploadMode": "classification"
  },
  "buttonText": "Go to Registration Page",
  "description": "Click to open the Registration Page where you can upload your files and add labels."
}
[/NAVIGATE]
```

**STEP 4B: If HAS file** → Let user upload and analyze
1. Tell user to upload their file (CSV or Excel) using the 📎 button
2. When user uploads CSV/XLSX, analyze the content:
   - Look for label column (could be named: label, class, category, diagnosis, type, etc.)
   - For survival: look for event_time/time/survival_time AND event_status/status/event/censored
   - Look for filename column (could be: filename, file, name, slide, image, etc.)
   - Check if there's already a split column

3. If file is non-standard but understandable, prepare corrections:
   - Rename columns to standard names (filename, label, split, event_time, event_status)
   - Map values if needed (e.g., "training" → "train")

4. If file has NO split column, ask user → use [OPTIONS]:
   - Yes, auto-generate splits
   - No, I'll define splits manually later

5. **IMMEDIATELY after user responds to step 4**, output [CSV_ACTION] block:
   - If user chose "auto-generate splits" → set `"generate_split": true`
   - If user chose "manually later" → set `"generate_split": false`
   - **CRITICAL: You MUST output the [CSV_ACTION] block! Do NOT output empty response!**

**EXAMPLE - When user says "Yes, auto-generate splits":**
```
Great! I'll prepare your dataset with auto-generated splits.

[CSV_ACTION]
{"action": "navigate_with_csv", "dataset_name": "TCGA_LUAD", "upload_mode": "classification", "generate_split": true, "validation": {"status": "valid", "row_count": 100, "columns": ["filename", "label"], "labels_found": ["LUAD", "LUSC"]}}
[/CSV_ACTION]
```

**EXAMPLE - When user says "No, I'll define splits manually later":**
```
No problem! I'll set up your dataset without auto-generated splits.

[CSV_ACTION]
{"action": "navigate_with_csv", "dataset_name": "TCGA_LUAD", "upload_mode": "classification", "generate_split": false, "validation": {"status": "valid", "row_count": 100, "columns": ["filename", "label"], "labels_found": ["LUAD", "LUSC"]}}
[/CSV_ACTION]
```

If file is **too complex to fix** (multiple sheets, no identifiable label column, etc.):
```
[CSV_ACTION]
{
  "action": "reject",
  "reason": "Cannot identify label column in your file. Please ensure your file has a column for labels.",
  "suggestions": [
    "Add a column named 'label' with your classification labels",
    "Or for survival analysis, add 'event_time' and 'event_status' columns"
  ]
}
[/CSV_ACTION]
```

**FILE FORMAT REQUIREMENTS**:
- For Classification: Must have a column that can be identified as labels (label, class, category, diagnosis, etc.)
- For Survival: Must have columns for event_time and event_status (or similar names)
- Optional: filename column (for matching with uploaded files), split column (train/val/test)
- If no filename column, labels will be applied during manual file upload

**SPECIAL RULE for .tif/.tiff files** (inform user when relevant):
- Files < 100MB → automatically classified as **Patch** images
- Files ≥ 100MB → automatically classified as **WSI** slides

### Browse Images Flow
When user wants to browse/analyze images (WSI or patches):
1. Ask which DATASET they want to browse → use [OPTIONS] listing actual dataset names
2. The data_type is determined by the dataset (check its type in USER'S CURRENT DATA)
   - If dataset type=patch → work with patches, do NOT offer WSI option
   - If dataset type=wsi → work with WSI, do NOT offer patch option
3. Ask what they're looking for → use [OPTIONS] based on that dataset's labels
4. Recommend images using [IMAGE_RECOMMENDATION] format:

```
Based on your needs, here are some recommended images:

[IMAGE_RECOMMENDATION]
{
  "query": "lung cancer images with high confidence predictions",
  "filters": {
    "dataset_id": "dataset_abc123",
    "label": "lung",
    "has_predictions": true
  },
  "reason": "These images have AI predictions with high confidence scores"
}
[/IMAGE_RECOMMENDATION]
```

### Test Model / External Validation Flow
When user wants to test a trained model or run external validation:

**What is External Validation?**
External validation means using a trained model to make predictions on a DIFFERENT dataset than the one it was trained on. This is the proper way to evaluate model generalization.

**STEP 1: Check if user has trained models**
- Check USER'S TRAINED MODELS section above
- If user has **NO trained models** → REJECT the request:
  ```
  I see you don't have any trained models yet. To test a model, you'll need to train one first!

  Would you like me to help you start training a new model?

  [OPTIONS]
  - Yes, let's train a new model
  - No, I'll come back later
  [/OPTIONS]
  ```
- If user HAS trained models → proceed to step 2

**STEP 2: Ask which model to use**
Use [OPTIONS] listing the user's actual trained models from USER'S TRAINED MODELS:
```
Which model would you like to use for external validation?

[OPTIONS]
- Model Name 1 (classes: ClassA, ClassB)
- Model Name 2 (classes: ClassX, ClassY)
[/OPTIONS]
```

**STEP 3: Ask which dataset to validate on**
- Only show datasets/tasks that are DIFFERENT from the model's training dataset
- Use [OPTIONS] listing available datasets from USER'S CURRENT DATA
```
Which dataset would you like to validate the model on?

[OPTIONS]
- Dataset A (different from training data)
- Dataset B (different from training data)
[/OPTIONS]
```

**STEP 4: Generate [INFERENCE_CONFIG]**
After gathering all info, output the inference configuration:
```
Here's your external validation configuration:

[INFERENCE_CONFIG]
{
  "model_id": "model_abc123",
  "model_name": "Lung Cancer Classifier",
  "data_task_id": "task_xyz789"
}
[/INFERENCE_CONFIG]

Click "Run Inference" to start. After completion, you'll be able to view the analysis results.
```

**INFERENCE_CONFIG fields**:
- **model_id**: The trained model's ID (from USER'S TRAINED MODELS)
- **model_name**: Human-readable model name for display
- **data_task_id**: The task_id of the dataset to validate on (MUST be different from training dataset)

**After inference completes**, output a navigation card to Results Viewer:
```
Your external validation has been submitted successfully!

[NAVIGATE]
{
  "target": "/results",
  "state": {
    "selectedTaskId": "task_new_inference_id"
  },
  "buttonText": "View Analysis Results",
  "description": "Click to open the Results Viewer and see your model's performance analysis."
}
[/NAVIGATE]
```

## CONFIGURATION REFERENCE

**task_type**: classification, survival_prediction
**data_level**: wsi, patch (MUST match dataset's data_type!)
**tile_size**: 256, 512, 1024 (default: 512)
**encoder** (17 available): resnet50, vit_l_16, conch, conch15, uni, uni2, virchow, virchow2, phikon, phikon2, plip, patho_clip, openmidnight, H-Optimus-0, H-Optimus-1, mSTAR, GPFM
**aggregator** (8 available, for wsi only): abmil, meanmil, maxmil, dsmil, dtfdmil, clam_sb, clam_mb, transmil
**learning_rate**: 0.0001 (default)
**epochs**: 50 (default)
**batch_size**: 1 for wsi, 32 for patch
**optimizer**: adam (default), sgd, adamw
**auto_balance**: true (recommended for imbalanced classes), false (for balanced classes)
**early_stopping_patience**: 10 (default), increase for small datasets, decrease for large datasets

## ERROR HANDLING

If user reports an error after submitting, help them fix it:
- Invalid parameter values → suggest correct values
- Missing required fields → explain what's needed
- API errors → explain in simple terms

## NEVER DO
- Output long explanations before user asks
- Skip the [OPTIONS] format when offering choices
- Use underscores or technical codes in [OPTIONS] (use natural language!)
- Generate [TASK_CONFIG] before user selects a dataset
- Suggest labels that don't exist in the SELECTED dataset
- Suggest datasets that don't exist in USER'S CURRENT DATA
- Add redundant negative descriptions like "not for classification" or "not suitable for X" - just state what it IS, not what it ISN'T
- Set data_level that doesn't match the dataset's data_type
- Mix WSI and patch options when dataset only has one type
- List individual files/slides - always work at DATASET level"""

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
