# SmartResearch Backend Services

Backend microservices for the SmartResearch digital pathology platform, providing WSI processing, AI inference, and API gateway functionality with PostgreSQL database backend.

## Architecture Overview

### Microservices Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    SmartResearch Backend                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐      │
│  │   Gateway    │  │  Preprocessing   │  │  AI Service  │      │
│  │  (Port 6100) │  │   (Port 6101)    │  │ (Port 6102)  │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                  │              │
│         └─────────────────┴──────────────────┘              │
│                           │                                 │
│  ┌────────────────────────▼─────────────────────────┐      │
│  │         PostgreSQL Database (Port 5432)          │      │
│  │  ┌────────────────────────────────────────────┐  │      │
│  │  │  Tables:                                   │  │      │
│  │  │  - wsi_slides       (WSI metadata)         │  │      │
│  │  │  - ai_tasks         (Task tracking)        │  │      │
│  │  │  - ai_results       (AI predictions)       │  │      │
│  │  │  - chat_conversations (Chat sessions)      │  │      │
│  │  │  - chat_messages    (Chat history)         │  │      │
│  │  └────────────────────────────────────────────┘  │      │
│  └──────────────────────────────────────────────────┘      │
│                           │                                 │
│  ┌────────────────────────▼─────────────────────────┐      │
│  │      File System Storage (Large Files)           │      │
│  │  - uploads/wsi_files/     (WSI images)           │      │
│  │  - uploads/thumbnails/    (Generated thumbs)     │      │
│  │  - uploads/coordinates/   (Tile coordinates)     │      │
│  │  - uploads/patches/       (Extracted patches)    │      │
│  └──────────────────────────────────────────────────┘      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Technology Stack

- **Framework**: FastAPI (Python 3.8+)
- **ASGI Server**: Uvicorn
- **Database**: PostgreSQL 15 (Docker)
- **ORM**: SQLAlchemy 2.0+ (async)
- **Database Driver**: asyncpg
- **WSI Processing**: ASlide (OpenSlide wrapper)
- **AI Framework**: PyTorch
- **Image Processing**: PIL, NumPy
- **Data Format**: PostgreSQL (structured data), File System (large files)
- **Concurrency**: asyncio, connection pooling

## Database Architecture

### Storage Strategy

SmartResearch uses a hybrid storage approach:

1. **PostgreSQL Database**: Stores structured metadata, task records, AI results, and chat history
2. **File System**: Stores large binary files (WSI images, thumbnails, patches)

This approach provides:
- Fast querying and indexing for metadata
- Efficient storage for large files
- ACID transactions for data integrity
- Scalability for both structured and unstructured data

### Database Schema

#### Table: `wsi_slides`

Stores WSI metadata and properties.

```sql
CREATE TABLE wsi_slides (
    id SERIAL PRIMARY KEY,
    wsi_id VARCHAR(255) UNIQUE NOT NULL,
    case_id VARCHAR(255),
    label VARCHAR(100),
    wsi_path TEXT NOT NULL,

    -- WSI properties
    mpp FLOAT,                    -- Microns per pixel
    vendor VARCHAR(100),          -- Scanner vendor
    width INTEGER,                -- Image width in pixels
    height INTEGER,               -- Image height in pixels
    magnification INTEGER,        -- Objective power (e.g., 40x)

    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Indexes
    INDEX idx_wsi_id (wsi_id),
    INDEX idx_case_id (case_id),
    INDEX idx_label (label)
);
```

#### Table: `ai_tasks`

Tracks AI analysis tasks and their status.

```sql
CREATE TABLE ai_tasks (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(255) UNIQUE NOT NULL,
    wsi_id VARCHAR(255) NOT NULL REFERENCES wsi_slides(wsi_id),
    task_type VARCHAR(50) NOT NULL,     -- e.g., "wsi-classification"
    status VARCHAR(20) NOT NULL,        -- pending, running, completed, failed
    progress INTEGER DEFAULT 0,         -- 0-100

    -- Task parameters (JSON)
    params JSONB,

    -- Error information
    error_message TEXT,

    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at TIMESTAMP,
    finished_at TIMESTAMP,

    -- Indexes
    INDEX idx_task_id (task_id),
    INDEX idx_wsi_id (wsi_id),
    INDEX idx_status (status)
);
```

#### Table: `ai_results`

Stores AI analysis results (predictions, probabilities, attention weights).

```sql
CREATE TABLE ai_results (
    id SERIAL PRIMARY KEY,
    wsi_id VARCHAR(255) NOT NULL REFERENCES wsi_slides(wsi_id),
    task_id VARCHAR(255) REFERENCES ai_tasks(task_id),

    -- Prediction results
    pred VARCHAR(100),              -- Predicted label
    probs JSONB,                    -- Probability distribution
    attention_weights JSONB,        -- Attention heatmap data
    extra_metadata JSONB,           -- Additional metadata

    -- Timestamp
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Indexes
    INDEX idx_wsi_id (wsi_id),
    INDEX idx_task_id (task_id)
);
```

#### Table: `chat_conversations`

Stores chat conversation sessions.

```sql
CREATE TABLE chat_conversations (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(255) UNIQUE NOT NULL,
    user_id VARCHAR(255),           -- For future multi-user support
    title VARCHAR(500),             -- Auto-generated from first message

    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Indexes
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_user_id (user_id)
);
```

#### Table: `chat_messages`

Stores individual messages in conversations.

```sql
CREATE TABLE chat_messages (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(255) NOT NULL REFERENCES chat_conversations(conversation_id),
    role VARCHAR(20) NOT NULL,      -- "user" or "assistant"
    content TEXT NOT NULL,
    extra_metadata JSONB,           -- Optional metadata (model, tokens, etc.)

    -- Timestamp
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Indexes
    INDEX idx_conversation_created (conversation_id, created_at)
);
```

### Database Schema Changes

For this research project, we use direct SQL for schema changes instead of migration tools.

#### Adding New Columns

```python
from smartresearch.services.backend.database import engine
from sqlalchemy import text

async def add_new_column():
    async with engine.begin() as conn:
        await conn.execute(text(
            'ALTER TABLE wsi_slides ADD COLUMN tissue_type VARCHAR(50)'
        ))
        print('✓ Column added')

# Run it
import asyncio
asyncio.run(add_new_column())
```

#### Common Schema Operations

```sql
-- Add column
ALTER TABLE wsi_slides ADD COLUMN tissue_type VARCHAR(50);

-- Modify column
ALTER TABLE wsi_slides ALTER COLUMN label TYPE VARCHAR(200);

-- Add index
CREATE INDEX idx_tissue_type ON wsi_slides(tissue_type);

-- Drop column
ALTER TABLE wsi_slides DROP COLUMN old_field;
```

**Important**: After changing the database schema, update the corresponding model in `models.py`:

```python
# smartresearch/services/backend/database/models.py
class WSISlide(Base):
    __tablename__ = "wsi_slides"

    # Add new field
    tissue_type = Column(String(50))
```

### Database Connection Management

#### Connection Configuration

Database connection is configured via environment variable:

```bash
# Default (Docker PostgreSQL)
DATABASE_URL=postgresql+asyncpg://smartresearch:smartresearch@localhost:5432/smartresearch

# Custom PostgreSQL instance
DATABASE_URL=postgresql+asyncpg://user:password@host:port/database
```

#### Connection Pool Settings

```python
# smartresearch/database/database.py
engine = create_async_engine(
    DATABASE_URL,
    echo=False,              # Set to True for SQL query logging
    pool_pre_ping=True,      # Verify connections before using
    pool_size=10,            # Connection pool size
    max_overflow=20,         # Max overflow connections
)
```

#### Using Database Sessions in FastAPI

```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from smartresearch.database import get_db
from smartresearch.database.repositories import WSIRepository

@app.get("/wsi")
async def list_wsi(db: AsyncSession = Depends(get_db)):
    """List all WSI slides"""
    wsi_list = await WSIRepository.get_all(db, skip=0, limit=100)
    return {"items": [wsi.to_dict() for wsi in wsi_list]}
```

### Repository Pattern

SmartResearch uses the Repository pattern for data access, providing a clean abstraction over database operations.

#### Repository Structure

```
smartresearch/services/backend/database/
├── models.py           # SQLAlchemy ORM models
├── repositories.py     # Data access layer
├── database.py         # Connection management
└── init_db.py          # Database initialization
```

#### Example Repository Usage

```python
from smartresearch.database.repositories import WSIRepository

# Create a new WSI record
async with async_session() as db:
    wsi_data = {
        "wsi_id": "slide_001",
        "case_id": "case_123",
        "label": "HSIL",
        "wsi_path": "/path/to/slide.svs",
        "mpp": 0.25,
        "vendor": "Aperio",
        "width": 50000,
        "height": 40000,
        "magnification": 40
    }
    wsi = await WSIRepository.create(db, wsi_data)
    await db.commit()

# Query WSI by ID
async with async_session() as db:
    wsi = await WSIRepository.get_by_id(db, "slide_001")
    print(wsi.to_dict())

# Query with filters
async with async_session() as db:
    hsil_slides = await WSIRepository.get_by_label(db, "HSIL")

# Get label distribution
async with async_session() as db:
    distribution = await WSIRepository.get_label_distribution(db)
    # Returns: {"HSIL": 45, "LSIL": 30, "NILM": 25}
```

### Database Initialization

Initialize the database by creating all tables:

```bash
# Run database initialization (automatically called by start_all.sh)
python smartresearch/services/backend/database/init_db.py
```

This script creates all database tables required for the application.

#### Migration Output Example

```
==========================================================
SmartResearch Database Initialization & Migration
==========================================================

[Step 1] Creating database tables...
[Database] All tables created successfully

[Step 2] Migrating existing data from JSON files...

[1/3] Migrating WSI metadata...
  Found 150 metadata files
  Migrated: 150, Skipped: 0

[2/3] Migrating AI tasks...
  Found 75 task files
  Migrated: 75, Skipped: 0

[3/3] Migrating AI results...
  Found 150 result files
  Migrated: 150, Skipped: 0

[Validation] Checking migrated data...
  WSI Slides: 150
  AI Tasks: 75
  AI Results: 150
  Label Distribution: {'HSIL': 45, 'LSIL': 30, 'NILM': 25, ...}

==========================================================
Database initialization and migration completed!
==========================================================
```

## Service Components

### 1. Gateway Service (`gateway/main.py`)

**Purpose**: API orchestration, request routing, and business logic coordination with PostgreSQL backend

**Port**: 6100

**Key Responsibilities**:
- Route frontend requests to appropriate backend services
- Aggregate data from multiple services
- Manage WSI metadata via PostgreSQL (CRUD operations)
- Track AI tasks and results in database
- Handle AI chat requests with conversation history
- Provide system statistics and health checks
- Auto-generate metadata from CSV files

**API Endpoints**:

WSI Management:
```python
GET  /health                          # Health check
GET  /wsi                             # List all WSI slides (from database)
GET  /wsi/{wsi_id}                    # Get WSI metadata (from database)
POST /wsi/upload/path                 # Register WSI by file path
```

AI Task Management:
```python
POST /tasks/wsi-classification        # Create AI analysis task
GET  /tasks/{task_id}                 # Get task status (from database)
GET  /results/{wsi_id}                # Get AI analysis results (from database)
```

Chat Management:
```python
POST /conversations                   # Create new conversation
GET  /conversations                   # List all conversations
GET  /conversations/{id}              # Get conversation details
DELETE /conversations/{id}            # Delete conversation
POST /conversations/{id}/messages     # Add message to conversation
GET  /conversations/{id}/messages     # Get conversation history
POST /chat                            # AI chat (streaming)
```

System:
```python
GET  /stats                           # System statistics (from database)
```

**Data Models**:
```python
class WSIMetadata(BaseModel):
    wsi_id: str
    case_id: Optional[str]
    label: Optional[str]
    wsi_path: str
    mpp: Optional[float]
    vendor: Optional[str]
    width: Optional[int]
    height: Optional[int]
    magnification: Optional[int]

class CreateConversationRequest(BaseModel):
    user_id: Optional[str] = "default_user"
    title: Optional[str] = None

class AddMessageRequest(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    metadata: Optional[Dict] = None
```

**Database Integration**:
```python
from smartresearch.database import get_db
from smartresearch.database.repositories import WSIRepository

@app.get("/wsi")
async def list_wsi(skip: int = 0, limit: int = 100,
                   db: AsyncSession = Depends(get_db)):
    """Query WSI slides from PostgreSQL"""
    wsi_list = await WSIRepository.get_all(db, skip=skip, limit=limit)
    return {"items": [wsi.to_dict() for wsi in wsi_list]}
```

**Storage Strategy**:
- Structured data (metadata, tasks, results, chat): PostgreSQL database
- Large files (WSI images): File system at `uploads/wsi_files/`
- Generated files (thumbnails, patches): File system at `uploads/`

### 2. Preprocessing Service (`backend/preprocessing/main.py`)

**Purpose**: WSI file processing, tissue segmentation, patch extraction, tile generation, and image serving

**Port**: 6101

**Key Responsibilities**:
- Open and cache WSI files (OpenSlide/ASlide)
- Generate Deep Zoom Image (DZI) descriptors
- Serve image tiles on-demand
- Generate thumbnails
- Extract tissue coordinates for AI processing
- LRU caching for performance

**API Endpoints**:
```python
GET /health                                    # Health check
GET /api/wsi                                   # List WSI slides
GET /api/wsi/{wsi_id}/dzi                      # DZI descriptor (XML/JSON)
GET /api/wsi/{wsi_id}/tiles/{z}/{x}_{y}.jpeg  # Image tile
GET /api/wsi/{wsi_id}/thumbnail                # Thumbnail image
GET /api/wsi/{wsi_id}/coordinates              # Tissue coordinates
```

**Caching Strategy**:
```python
# LRU cache for slide objects (default: 8 slides)
SLIDE_CACHE_SIZE = 8
slide_cache = OrderedDict()

# LRU cache for DeepZoom generators (default: 16)
DZG_CACHE_SIZE = 16
dzg_cache = OrderedDict()
```

**Tile Generation**:
- Uses ASlide's DeepZoom generator
- Tile size: 256x256 pixels (configurable)
- Format: JPEG (quality: 90)
- Overlap: 1 pixel (for seamless rendering)

**Coordinate Extraction** (`tiling.py`):
- Detects tissue regions using Otsu thresholding
- Generates grid coordinates for AI processing
- Caches coordinates to `uploads/coordinates/{wsi_id}_coords.json`

### 3. AI Service (`backend/ai/main.py`)

**Purpose**: AI model inference and analysis task execution

**Port**: 6102

**Key Responsibilities**:
- Load and manage AI models (checkpoints)
- Execute WSI classification tasks
- Generate predictions and attention maps
- Store analysis results
- Task status tracking

**API Endpoints**:
```python
GET  /health                          # Health check
POST /api/ai/analyze                  # Run AI analysis
GET  /api/ai/results/{wsi_id}         # Get analysis results
GET  /api/ai/tasks/{task_id}          # Get task status
```

**Analysis Request**:
```python
class AnalyzeRequest(BaseModel):
    task: str  # "wsi-classification"
    wsi_id: str
    params: Optional[Dict] = {
        "tile_size": 256,
        "stride": 256,
        "feature_model": "resnet50",
        "aggregator": "attention",
        "device": "cuda"
    }
```

**Analysis Pipeline**:
1. Fetch WSI metadata from Gateway (database)
2. Get tissue coordinates from Preprocessing Service
3. Extract tiles from WSI
4. Run feature extraction (CNN)
5. Aggregate features (attention mechanism)
6. Generate slide-level prediction
7. Save results to database (metadata) and files (attention weights)

**Result Format** (stored in database):
```json
{
  "wsi_id": "slide_001",
  "pred": "HSIL",
  "probs": {
    "HSIL": 0.85,
    "LSIL": 0.12,
    "Normal": 0.03
  },
  "extra_metadata": {
    "attention_path": "ai_results/slide_001/task_123_attention.npy"
  }
}
```

## Current Storage Architecture

### PostgreSQL Database (Current Implementation)

✅ **WSI Metadata**: Stored in `wsi_slides` table
✅ **AI Tasks**: Stored in `ai_tasks` table
✅ **AI Results**: Stored in `ai_results` table
✅ **Chat Conversations**: Stored in `chat_conversations` and `chat_messages` tables
✅ **Training Tasks**: Stored in `training_tasks` table
✅ **Trained Models**: Stored in `trained_models` table

### File-Based Storage (Legacy/Cache)

```
smartresearch/uploads/
├── ai_results/         # Attention weights (.npy files)
│   └── {wsi_id}/
│       └── {task_id}_attention.npy
├── models/             # User-trained models
│   └── {model_id}/
│       ├── checkpoint.pth
│       ├── config.json
│       └── training_history.json
├── training/           # Training features
│   └── {task_id}/
│       └── features/
│           └── {wsi_id}_features.pt
├── coordinates/        # Tile coordinates cache (H5)
├── thumbnails/         # Generated thumbnails (JPEG)
├── patches/            # Temporary tile cache (JPEG)
└── wsi_files/          # WSI image files (optional)
    └── {wsi_id}.svs
```

**Note**: All metadata (WSI info, tasks, results) is stored in PostgreSQL database. Only large binary data is stored in files.

### Benefits of Database Approach

✅ **Transaction Support**: ACID guarantees for data consistency
✅ **Rich Query Capabilities**: Efficient search, filter, and aggregation
✅ **Excellent Concurrency**: PostgreSQL handles concurrent access
✅ **Conversation Storage**: Full chat history persistence
❌ **Scalability Issues**: File system performance degrades with many files  
❌ **No Relationships**: Cannot model complex data relationships  

## Recommended Storage Architecture (Future)

Based on industry best practices from **Digital Slide Archive (DSA)** and **Cytomine**, we recommend a **hybrid storage architecture**:

### Phase 1: SQLite (Quick Start)

**Advantages**:
- ✅ Zero configuration (serverless)
- ✅ ACID transactions
- ✅ SQL query capabilities
- ✅ Easy migration path to PostgreSQL
- ✅ Perfect for single-server deployments

**Implementation**:
```python
# Install dependencies
pip install sqlalchemy aiosqlite

# Database models (SQLAlchemy)
class WSISlide(Base):
    __tablename__ = "wsi_slides"
    id = Column(Integer, primary_key=True)
    wsi_id = Column(String(255), unique=True, nullable=False)
    case_id = Column(String(255))
    label = Column(String(100))
    wsi_path = Column(Text, nullable=False)
    mpp = Column(Float)
    vendor = Column(String(100))
    width = Column(Integer)
    height = Column(Integer)
    magnification = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatConversation(Base):
    __tablename__ = "chat_conversations"
    id = Column(Integer, primary_key=True)
    conversation_id = Column(String(255), unique=True, nullable=False)
    user_id = Column(String(255))
    title = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True)
    conversation_id = Column(String(255), ForeignKey("chat_conversations.conversation_id"))
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    metadata = Column(Text)  # JSON string
    created_at = Column(DateTime, default=datetime.utcnow)
```

### Phase 2: PostgreSQL + MinIO (Production)

**Recommended Architecture** (inspired by Cytomine):

```
┌─────────────────────────────────────────────────────────────┐
│                  Production Architecture                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  PostgreSQL Database                                 │   │
│  │  - WSI metadata (wsi_slides table)                   │   │
│  │  - AI tasks and results (ai_tasks, ai_results)       │   │
│  │  - Chat conversations (chat_conversations, messages) │   │
│  │  - User management (users, permissions)              │   │
│  │  - pgvector extension (semantic search)              │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  MinIO Object Storage (S3-compatible)                │   │
│  │  - WSI files (multi-gigapixel images)                │   │
│  │  - Model checkpoints (PyTorch .pth files)            │   │
│  │  - Thumbnails and cached tiles                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Redis Cache (Optional)                              │   │
│  │  - Tile cache (hot data)                             │   │
│  │  - Session management                                │   │
│  │  - Task queue (Celery backend)                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Why PostgreSQL?** (Following Cytomine's approach)
- ✅ Proven in production digital pathology platforms
- ✅ Strong ACID guarantees
- ✅ pgvector extension for semantic search (chat history)
- ✅ Full-text search capabilities
- ✅ JSON/JSONB support for flexible schemas
- ✅ Excellent Python ecosystem (asyncpg, SQLAlchemy)

**Why MinIO?** (Following DSA's approach)
- ✅ S3-compatible API (easy migration to AWS/Azure)
- ✅ Self-hosted (no cloud vendor lock-in)
- ✅ Optimized for large files (WSI images)
- ✅ Built-in versioning and lifecycle policies
- ✅ Docker deployment ready

**Implementation Roadmap**:

1. **Week 1**: Add SQLAlchemy models and Alembic migrations
2. **Week 2**: Implement conversation storage API
3. **Week 3**: Migrate metadata from JSON to PostgreSQL
4. **Week 4**: Add MinIO integration for WSI files
5. **Week 5**: Add pgvector for semantic chat search
6. **Week 6**: Performance testing and optimization

## Development Setup

### Prerequisites

- Python 3.8+
- pip or conda
- WSI files (`.svs`, `.tif`, or other OpenSlide-compatible formats)

### Installation

```bash
# Navigate to project root
cd smartresearch

# Install dependencies
pip install -r requirements.txt

# Additional dependencies for WSI processing
pip install aslide openslide-python pillow numpy

# For AI inference
pip install torch torchvision
```

### Environment Variables

```bash
# Preprocessing Service
export SLIDE_CACHE_SIZE=8        # Number of slides to cache
export DZG_CACHE_SIZE=16         # Number of DeepZoom generators to cache

# AI Service
export CUDA_VISIBLE_DEVICES=0    # GPU device ID (or empty for CPU)
export MODEL_CHECKPOINT_PATH=/path/to/model.pth
```

### Running Services

#### Option 1: Start All Services (Recommended)

```bash
# From project root
./smartresearch/start_all.sh
```

This script starts:
- Gateway (port 6100)
- Preprocessing Service (port 6101)
- AI Service (port 6102)

Logs are written to `/tmp/smartresearch_*.log`

#### Option 2: Start Services Individually

```bash
# Terminal 1: Gateway
python -m uvicorn smartresearch.services.gateway.main:app --host 0.0.0.0 --port 6100 --reload

# Terminal 2: Preprocessing Service
python -m uvicorn smartresearch.services.backend.preprocessing.main:app --host 0.0.0.0 --port 6101 --reload

# Terminal 3: AI Service
python -m uvicorn smartresearch.services.backend.ai.main:app --host 0.0.0.0 --port 6102 --reload
```

### Stopping Services

```bash
# From project root
./smartresearch/stop_all.sh
```

### Health Checks

```bash
# Check all services
curl http://127.0.0.1:6100/health  # Gateway
curl http://127.0.0.1:6101/health  # Preprocessing Service
curl http://127.0.0.1:6102/health  # AI Service
```

## Data Flow Examples

### Example 1: WSI Upload and Registration

```bash
# Register a WSI by file path (no file copy)
curl -X POST http://127.0.0.1:6100/wsi/upload/path \
  -H "Content-Type: application/json" \
  -d '{
    "wsi_path": "/data/slides/sample.svs",
    "case_id": "CASE_001",
    "label": "HSIL",
    "wsi_id": "slide_001"
  }'

# Response:
# {
#   "wsi_id": "slide_001",
#   "message": "WSI registered successfully",
#   "metadata": {
#     "wsi_id": "slide_001",
#     "case_id": "CASE_001",
#     "label": "HSIL",
#     "wsi_path": "/data/slides/sample.svs",
#     "width": 50000,
#     "height": 40000,
#     "mpp": 0.25,
#     "vendor": "Aperio"
#   }
# }
```

### Example 2: AI Analysis Task

```bash
# Submit analysis task
curl -X POST http://127.0.0.1:6100/tasks/wsi-classification \
  -H "Content-Type: application/json" \
  -d '{
    "wsi_id": "slide_001",
    "params": {
      "tile_size": 256,
      "stride": 256,
      "feature_model": "resnet50",
      "aggregator": "attention",
      "device": "cuda"
    }
  }'

# Response:
# {
#   "task_id": "task_abc123",
#   "status": "pending",
#   "wsi_id": "slide_001"
# }

# Check task status
curl http://127.0.0.1:6100/tasks/task_abc123

# Response:
# {
#   "task_id": "task_abc123",
#   "status": "completed",
#   "progress": 100,
#   "result": {
#     "pred": "HSIL",
#     "probs": {"HSIL": 0.85, "LSIL": 0.12, "Normal": 0.03}
#   }
# }
```

### Example 3: AI Chat (Streaming)

```bash
# Chat with AI assistant
curl -X POST http://127.0.0.1:6100/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "I want to classify cervical cancer slides"}
    ]
  }'

# Response (streaming):
# data: I can help you set up a cervical cancer classification task.
# data: What labels are you working with? (e.g., HSIL, LSIL, Normal)
# ...
```

## Configuration

### Gateway Configuration

Located in `smartresearch/services/gateway/main.py`:

```python
# Uploads directory
UPLOADS_DIR = Path(__file__).resolve().parents[3] / "uploads"

# Metadata auto-generation from CSV
CSV_PATH = UPLOADS_DIR.parent / "services" / "frontend" / "public" / "source.csv"

# Backend service URLs
PREPROCESSING_SERVICE_URL = "http://127.0.0.1:6101"
AI_SERVICE_URL = "http://127.0.0.1:6102"
```

### Preprocessing Service Configuration

Located in `smartresearch/services/backend/preprocessing/main.py`:

```python
# Cache sizes
SLIDE_CACHE_SIZE = int(os.environ.get("SLIDE_CACHE_SIZE", "8"))
DZG_CACHE_SIZE = int(os.environ.get("DZG_CACHE_SIZE", "16"))

# Tile generation
TILE_SIZE = 256
TILE_OVERLAP = 1
TILE_FORMAT = "jpeg"
TILE_QUALITY = 90
```

### AI Service Configuration

Located in `smartresearch/services/backend/ai/main.py`:

```python
# Model paths
MODEL_DIR = Path(__file__).resolve().parents[3] / "models"
CHECKPOINT_DIR = MODEL_DIR / "checkpoints"

# Default inference parameters
DEFAULT_TILE_SIZE = 256
DEFAULT_STRIDE = 256
DEFAULT_FEATURE_MODEL = "resnet50"
DEFAULT_AGGREGATOR = "attention"
DEFAULT_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
```

## Testing

### Manual Testing

```bash
# Test WSI list endpoint
curl http://127.0.0.1:6100/wsi

# Test WSI metadata
curl http://127.0.0.1:6100/wsi/slide_001

# Test DZI descriptor
curl http://127.0.0.1:6101/api/wsi/slide_001/dzi

# Test tile serving
curl http://127.0.0.1:6101/api/wsi/slide_001/tiles/12/0_0.jpeg -o tile.jpeg

# Test system statistics
curl http://127.0.0.1:6100/stats
```

### Automated Testing (Planned)

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest tests/

# Run with coverage
pytest --cov=smartresearch tests/
```

## API Documentation

### Interactive API Docs

FastAPI provides automatic interactive documentation:

- **Gateway**: http://127.0.0.1:6100/docs
- **Preprocessing Service**: http://127.0.0.1:6101/docs
- **AI Service**: http://127.0.0.1:6102/docs

### OpenAPI Specification

- **Gateway**: http://127.0.0.1:6100/openapi.json
- **Preprocessing Service**: http://127.0.0.1:6101/openapi.json
- **AI Service**: http://127.0.0.1:6102/openapi.json

## Troubleshooting

### Common Issues

#### 1. "Cannot open WSI file"

**Cause**: OpenSlide cannot read the file format or file path is incorrect

**Solution**:
```bash
# Check if file exists
ls -lh /path/to/slide.svs

# Test with OpenSlide directly
python -c "import openslide; slide = openslide.OpenSlide('/path/to/slide.svs'); print(slide.dimensions)"

# Check supported formats
python -c "import openslide; print(openslide.FORMATS)"
```

#### 2. "CUDA out of memory"

**Cause**: GPU memory exhausted during AI inference

**Solution**:
```python
# Reduce batch size in AI service
BATCH_SIZE = 32  # Try 16 or 8

# Or use CPU
export CUDA_VISIBLE_DEVICES=""
```

#### 3. "Tile generation is slow"

**Cause**: Cache size too small or disk I/O bottleneck

**Solution**:
```bash
# Increase cache sizes
export SLIDE_CACHE_SIZE=16
export DZG_CACHE_SIZE=32

# Use SSD for uploads directory
# Move uploads/ to SSD mount point
```

#### 4. "Metadata file not found"

**Cause**: Metadata JSON not generated or deleted

**Solution**:
```bash
# Regenerate metadata from CSV
# Gateway auto-generates on startup from source.csv

# Or manually create metadata
curl -X POST http://127.0.0.1:6100/wsi/upload/path \
  -H "Content-Type: application/json" \
  -d '{"wsi_path": "/path/to/slide.svs", "wsi_id": "slide_001"}'
```

## Security Considerations

### Current Status (Development)

⚠️ **No Authentication**: All endpoints are publicly accessible
⚠️ **No Authorization**: No user roles or permissions
⚠️ **No Input Validation**: Limited sanitization of user inputs
⚠️ **CORS Wide Open**: `allow_origins=["*"]` for development

### Production Recommendations

1. **Add Authentication**:
   ```python
   from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

   security = HTTPBearer()

   @app.get("/wsi")
   async def list_wsi(credentials: HTTPAuthorizationCredentials = Depends(security)):
       # Verify JWT token
       user = verify_token(credentials.credentials)
       # ...
   ```

2. **Restrict CORS**:
   ```python
   app.add_middleware(
       CORSMiddleware,
       allow_origins=["https://yourdomain.com"],  # Specific domain
       allow_methods=["GET", "POST"],
       allow_headers=["Authorization", "Content-Type"],
   )
   ```

3. **Input Validation**:
   ```python
   from pydantic import validator, Field

   class WSIUploadRequest(BaseModel):
       wsi_path: str = Field(..., regex=r'^/[a-zA-Z0-9/_\-\.]+$')
       wsi_id: str = Field(..., min_length=1, max_length=255)

       @validator('wsi_path')
       def validate_path(cls, v):
           # Prevent path traversal
           if '..' in v:
               raise ValueError('Invalid path')
           return v
   ```

4. **Rate Limiting**:
   ```python
   from slowapi import Limiter, _rate_limit_exceeded_handler
   from slowapi.util import get_remote_address

   limiter = Limiter(key_func=get_remote_address)
   app.state.limiter = limiter

   @app.get("/chat")
   @limiter.limit("10/minute")
   async def chat(request: Request):
       # ...
   ```

### Technical Documentation

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [OpenSlide Documentation](https://openslide.org/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [MinIO Documentation](https://min.io/docs/)
- [pgvector Documentation](https://github.com/pgvector/pgvector)

## Contributing

1. Follow PEP 8 style guide
2. Use type hints for all functions
3. Add docstrings for public APIs
4. Write tests for new features
5. Update API documentation

## License

See root repository LICENSE file.


