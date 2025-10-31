# SmartResearch Gateway Service

API Gateway and orchestration layer for the SmartResearch digital pathology platform.

## Purpose

The Gateway Service acts as the **single entry point** for all frontend requests, providing:

- **Request Routing**: Forwards requests to appropriate backend services (WSI, AI)
- **Data Aggregation**: Combines data from multiple services into unified responses
- **Business Logic**: Implements cross-service workflows and orchestration
- **Metadata Management**: CRUD operations for WSI metadata (JSON-based)
- **AI Chat Integration**: Handles LLM-based conversational interface
- **System Statistics**: Aggregates metrics across all services

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Gateway Service (Port 6100)               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │  FastAPI Application                               │     │
│  │  - CORS middleware (allow all origins in dev)      │     │
│  │  - Request validation (Pydantic models)            │     │
│  │  - Error handling and logging                      │     │
│  └────────────────────────────────────────────────────┘     │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Service Orchestration Layer                       │     │
│  │  - Preprocessing Service client (HTTP)             │     │
│  │  - AI Service client (HTTP)                        │     │
│  │  - Response aggregation                            │     │
│  └────────────────────────────────────────────────────┘     │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Metadata Management                               │     │
│  │  - PostgreSQL database storage                     │     │
│  │  - Repository pattern for data access              │     │
│  │  - Validation and sanitization                     │     │
│  └────────────────────────────────────────────────────┘     │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │  AI Chat Handler                                   │     │
│  │  - LLM integration (streaming responses)           │     │
│  │  - Task parameter extraction                       │     │
│  │  - Conversation context management                 │     │
│  └────────────────────────────────────────────────────┘     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
  Preprocessing         AI Service          File System
     Service           (Port 6102)      (uploads/ directory)
   (Port 6101)
```

## API Endpoints

### Health Check

```http
GET /health
```

**Response**:
```json
{
  "status": "ok",
  "service": "gateway"
}
```

### WSI Management

#### List All WSI Slides

```http
GET /wsi
```

**Response**:
```json
{
  "items": [
    {
      "wsi_id": "slide_001",
      "case_id": "CASE_001",
      "label": "HSIL",
      "wsi_path": "/data/slides/sample.svs",
      "width": 50000,
      "height": 40000,
      "mpp": 0.25,
      "vendor": "Aperio"
    }
  ]
}
```

#### Get WSI Metadata

```http
GET /wsi/{wsi_id}
```

**Response**:
```json
{
  "wsi_id": "slide_001",
  "meta": {
    "case_id": "CASE_001",
    "label": "HSIL",
    "wsi_path": "/data/slides/sample.svs",
    "width": 50000,
    "height": 40000,
    "mpp": 0.25,
    "vendor": "Aperio"
  },
  "last_run": {
    "task_id": "task_abc123",
    "timestamp": "2025-10-29T12:34:56",
    "status": "completed"
  }
}
```

#### Register WSI by File Path

```http
POST /wsi/upload/path
Content-Type: application/json

{
  "wsi_path": "/data/slides/sample.svs",
  "case_id": "CASE_001",
  "label": "HSIL",
  "wsi_id": "slide_001"  // Optional, auto-generated if not provided
}
```

**Response**:
```json
{
  "wsi_id": "slide_001",
  "message": "WSI registered successfully",
  "metadata": {
    "wsi_id": "slide_001",
    "case_id": "CASE_001",
    "label": "HSIL",
    "wsi_path": "/data/slides/sample.svs",
    "width": 50000,
    "height": 40000,
    "mpp": 0.25,
    "vendor": "Aperio"
  }
}
```

### Task Management

#### Create WSI Classification Task

```http
POST /tasks/wsi-classification
Content-Type: application/json

{
  "wsi_id": "slide_001",
  "params": {
    "tile_size": 256,
    "stride": 256,
    "feature_model": "resnet50",
    "aggregator": "attention",
    "device": "cuda"
  }
}
```

**Response**:
```json
{
  "task_id": "task_abc123",
  "status": "pending",
  "wsi_id": "slide_001",
  "message": "Task created successfully"
}
```

#### Get Task Status

```http
GET /tasks/{task_id}
```

**Response**:
```json
{
  "task_id": "task_abc123",
  "status": "completed",
  "progress": 100,
  "wsi_id": "slide_001",
  "result": {
    "pred": "HSIL",
    "probs": {
      "HSIL": 0.85,
      "LSIL": 0.12,
      "Normal": 0.03
    }
  },
  "created_at": "2025-10-29T12:34:56",
  "completed_at": "2025-10-29T12:45:30"
}
```

### Results

#### Get Analysis Results

```http
GET /results/{wsi_id}
```

**Response**:
```json
{
  "wsi_id": "slide_001",
  "pred": "HSIL",
  "probs": {
    "HSIL": 0.85,
    "LSIL": 0.12,
    "Normal": 0.03
  },
  "attention_weights": [...],
  "timestamp": "2025-10-29T12:45:30"
}
```

### AI Chat

#### Chat with AI Assistant (Streaming)

```http
POST /chat
Content-Type: application/json

{
  "messages": [
    {"role": "user", "content": "I want to classify cervical cancer slides"},
    {"role": "assistant", "content": "I can help you with that. What labels are you working with?"},
    {"role": "user", "content": "HSIL, LSIL, and Normal"}
  ]
}
```

**Response** (Server-Sent Events / Chunked Transfer):
```
data: I understand you want to classify cervical cancer slides into HSIL, LSIL, and Normal categories.

data: To set up this analysis, I'll need a few more details:

data: 1. Which slides do you want to analyze?
data: 2. What tile size would you like to use? (default: 256)
data: 3. Do you have a GPU available for faster processing?

data: Once you provide these details, I can help you create the analysis task.
```

### System Statistics

#### Get System Statistics

```http
GET /stats
```

**Response**:
```json
{
  "wsi_count": 150,
  "task_count": 45,
  "completed_count": 42,
  "results_count": 42,
  "labels": {
    "HSIL": 60,
    "LSIL": 50,
    "Normal": 40
  }
}
```

## Data Models

### WSIMetadata

```python
class WSIMetadata(BaseModel):
    wsi_id: str
    case_id: Optional[str] = None
    label: Optional[str] = None
    wsi_path: str
    mpp: Optional[float] = None
    vendor: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    magnification: Optional[int] = None
```

### WSIClassifyRequest

```python
class WSIClassifyRequest(BaseModel):
    wsi_id: str
    params: Optional[Dict] = None
```

### ChatRequest

```python
class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]  # [{"role": "user", "content": "..."}]
```

### UploadByPathRequest

```python
class UploadByPathRequest(BaseModel):
    wsi_path: str
    label: Optional[str] = None
    case_id: Optional[str] = None
    wsi_id: Optional[str] = None
```

## Request Flow Examples

### Example 1: WSI Upload and Viewing

```
1. User uploads WSI via frontend
   ↓
2. Frontend calls POST /wsi/upload/path
   ↓
3. Gateway validates request
   ↓
4. Gateway extracts WSI properties (mpp, vendor, dimensions, etc.)
   ↓
5. Gateway saves metadata to PostgreSQL database
   ↓
6. Gateway returns wsi_id to frontend
   ↓
7. Frontend navigates to /wsi/{wsi_id}
   ↓
8. Frontend requests DZI from Preprocessing Service directly
```

### Example 2: AI Analysis Workflow

```
1. User clicks "Analyze" on WSI detail page
   ↓
2. Frontend calls POST /tasks/wsi-classification
   ↓
3. Gateway validates wsi_id exists
   ↓
4. Gateway forwards request to AI Service
   ↓
5. AI Service creates task and returns task_id
   ↓
6. Gateway saves task record to uploads/tasks/{task_id}.json
   ↓
7. Gateway returns task_id to frontend
   ↓
8. Frontend polls GET /tasks/{task_id} for status
   ↓
9. When complete, frontend fetches GET /results/{wsi_id}
   ↓
10. Gateway reads from uploads/ai_results/{wsi_id}.json
```

### Example 3: AI Chat Interaction

```
1. User types message in chat interface
   ↓
2. Frontend calls POST /chat with message history
   ↓
3. Gateway validates request
   ↓
4. Gateway calls LLM API (streaming)
   ↓
5. Gateway streams response chunks to frontend
   ↓
6. Frontend updates UI incrementally
   ↓
7. If task parameters detected, offer to create task
```

## Implementation Details

### Database Integration

The Gateway uses PostgreSQL for all data storage via the repository pattern:

```python
from smartresearch.services.backend.database import get_db
from smartresearch.services.backend.database.repositories import WSIRepository

@app.get("/wsi")
async def list_wsi(skip: int = 0, limit: int = 100,
                   db: AsyncSession = Depends(get_db)):
    """Query WSI slides from PostgreSQL"""
    wsi_list = await WSIRepository.get_all(db, skip=skip, limit=limit)
    return {"items": [wsi.to_dict() for wsi in wsi_list]}

@app.post("/wsi/upload/path")
async def upload_wsi_by_path(req: UploadWSIByPathRequest,
                              db: AsyncSession = Depends(get_db)):
    """Register WSI in database"""
    wsi_data = {
        "wsi_id": req.wsi_id or f"wsi_{uuid.uuid4().hex[:16]}",
        "case_id": req.case_id,
        "label": req.label,
        "wsi_path": req.wsi_path,
        # Extract properties from WSI file
        **extract_wsi_properties(req.wsi_path)
    }
    wsi = await WSIRepository.create(db, wsi_data)
    await db.commit()
    return wsi.to_dict()
```

### Service Communication

The Gateway uses `httpx` for async HTTP requests to backend services:

```python
import httpx

async def forward_to_ai_service(wsi_id: str, params: dict):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AI_SERVICE_URL}/api/ai/analyze",
            json={"task": "wsi-classification", "wsi_id": wsi_id, "params": params},
            timeout=300.0
        )
        return response.json()
```

### Streaming Chat Responses

```python
from fastapi.responses import StreamingResponse

@app.post("/chat")
async def chat(request: ChatRequest):
    async def generate():
        # Call LLM API
        async for chunk in llm_stream(request.messages):
            yield f"data: {chunk}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")
```

## Running the Service

### Development Mode

```bash
python -m uvicorn smartresearch.services.gateway.main:app --host 0.0.0.0 --port 6100 --reload
```

### Production Mode

```bash
gunicorn smartresearch.services.gateway.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:6100 \
  --access-logfile - \
  --error-logfile -
```

## Configuration

### Environment Variables

```bash
# Backend service URLs
export PREPROCESSING_SERVICE_URL=http://127.0.0.1:6101
export AI_SERVICE_URL=http://127.0.0.1:6102

# LLM API configuration (if using external LLM)
export LLM_API_KEY=your_api_key
export LLM_MODEL=gpt-4
export LLM_BASE_URL=https://api.openai.com/v1
```

### File Paths

```python
# Uploads directory structure
UPLOADS_DIR = Path(__file__).resolve().parents[3] / "uploads"
AI_RESULTS_DIR = UPLOADS_DIR / "ai_results"  # Legacy compatibility
```

**Note**: WSI metadata is now stored in PostgreSQL database, not in JSON files.

## Future Enhancements

### Database Integration (Planned)

Replace JSON file storage with PostgreSQL:

```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Database setup
engine = create_async_engine("postgresql+asyncpg://user:pass@localhost/smartresearch")
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Example: Get WSI metadata from database
async def get_wsi_metadata(wsi_id: str, db: AsyncSession):
    result = await db.execute(
        select(WSISlide).where(WSISlide.wsi_id == wsi_id)
    )
    return result.scalar_one_or_none()
```

### Conversation Persistence

Store chat history in database:

```python
async def save_conversation(conversation_id: str, messages: List[Dict], db: AsyncSession):
    conversation = ChatConversation(
        conversation_id=conversation_id,
        user_id="current_user",
        title=messages[0]["content"][:100]
    )
    db.add(conversation)
    
    for msg in messages:
        chat_message = ChatMessage(
            conversation_id=conversation_id,
            role=msg["role"],
            content=msg["content"]
        )
        db.add(chat_message)
    
    await db.commit()
```

### Authentication & Authorization

Add JWT-based authentication:

```python
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.get("/wsi")
async def list_wsi(user_id: str = Depends(get_current_user)):
    # Only return WSI slides accessible to this user
    pass
```

## References

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [HTTPX Documentation](https://www.python-httpx.org/)
- [Server-Sent Events (SSE)](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)

## License

See root repository LICENSE file.

