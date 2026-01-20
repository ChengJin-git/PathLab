# PathLab Backend Services

Backend microservices for the PathLab digital pathology platform, providing WSI processing, AI inference, and API gateway functionality with SQLite database backend (零配置).

## Architecture Overview

### Microservices Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   PathLab Backend                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐   │
│  │   Gateway    │  │  Preprocessing   │  │  AI Service  │   │
│  │  (动态端口)  │  │   (内部端口)     │  │  (内部端口)  │   │
│  └──────┬───────┘  └──────┬───────────┘  └──────┬───────┘   │
│         │                 │                      │           │
│         └─────────────────┴──────────────────────┘           │
│                           │                                  │
│  ┌────────────────────────▼─────────────────────────┐       │
│  │         SQLite Database (零配置，内嵌)            │       │
│  │  ┌────────────────────────────────────────────┐  │       │
│  │  │  Tables:                                   │  │       │
│  │  │  - wsi_slides       (WSI metadata)         │  │       │
│  │  │  - ai_tasks         (Task tracking)        │  │       │
│  │  │  - ai_results       (AI predictions)       │  │       │
│  │  │  - chat_conversations (Chat sessions)      │  │      │
│  │  │  - chat_messages    (Chat history)         │  │      │
│  │  └────────────────────────────────────────────┘  │      │
│  └──────────────────────────────────────────────────┘      │
│                           │                                 │
│  ┌────────────────────────▼─────────────────────────┐      │
│  │      File System Storage (Large Files)           │      │
│  │  - uploads/wsi_files/     (WSI images)           │      │
│  │  - uploads/masks/         (Tissue masks)         │      │
│  │  - uploads/coordinates/   (Tile coordinates)     │      │
│  └──────────────────────────────────────────────────┘      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Technology Stack

- **Framework**: FastAPI (Python 3.8+)
- **ASGI Server**: Uvicorn
- **Database**: SQLite (零配置，内嵌)
- **ORM**: SQLAlchemy 2.0+ (async)
- **Database Driver**: aiosqlite
- **WSI Processing**: ASlide (OpenSlide wrapper)
- **AI Framework**: PyTorch
- **Image Processing**: PIL, NumPy
- **Data Format**: SQLite (structured data), File System (large files)
- **Concurrency**: asyncio
- **Port Discovery**: 动态端口分配，避免冲突

## Database Architecture

### Storage Strategy

PathLab uses a hybrid storage approach:

1. **SQLite Database**: Stores structured metadata, task records, AI results, and chat history (零配置)
2. **File System**: Stores large binary files (WSI images, masks, patches)

This approach provides:
- Fast querying and indexing for metadata
- Efficient storage for large files
- 无需安装数据库服务器
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
    task_type VARCHAR(50) NOT NULL,     -- e.g., "wsi_classification"
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
from pathlab.services.backend.database import engine
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
# pathlab/services/backend/database/models.py
class WSISlide(Base):
    __tablename__ = "wsi_slides"

    # Add new field
    tissue_type = Column(String(50))
```

### Database Connection Management

#### Connection Configuration

Database connection is automatically configured (零配置):

```bash
# 默认 SQLite 路径（按平台自动选择）
# Linux:   ~/.local/share/PathLab/pathlab.db
# macOS:   ~/Library/Application Support/PathLab/pathlab.db
# Windows: %APPDATA%/PathLab/pathlab.db

# 无需手动配置，系统自动创建数据库文件
```

#### Connection Pool Settings

```python
# pathlab/database/database.py
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
from pathlab.database import get_db
from pathlab.database.repositories import WSIRepository

@app.get("/wsi")
async def list_wsi(db: AsyncSession = Depends(get_db)):
    """List all WSI slides"""
    wsi_list = await WSIRepository.get_all(db, skip=0, limit=100)
    return {"items": [wsi.to_dict() for wsi in wsi_list]}
```

### Repository Pattern

PathLab uses the Repository pattern for data access, providing a clean abstraction over database operations.

#### Repository Structure

```
pathlab/services/backend/database/
├── models.py           # SQLAlchemy ORM models
├── repositories.py     # Data access layer
├── database.py         # Connection management
└── init_db.py          # Database initialization
```

#### Example Repository Usage

```python
from pathlab.database.repositories import WSIRepository

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
python pathlab/services/backend/database/init_db.py
```

This script creates all database tables required for the application.

#### Migration Output Example

```
==========================================================
PathLab Database Initialization & Migration
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

**Purpose**: API orchestration, request routing, and business logic coordination with SQLite backend

**Port**: 动态分配（通过 `PORT=xxxxx` 输出通知 Electron）

**Key Responsibilities**:
- Route frontend requests to appropriate backend services
- Aggregate data from multiple services
- Manage WSI metadata via SQLite (CRUD operations)
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
POST /tasks/wsi_classification        # Create AI analysis task
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
from pathlab.database import get_db
from pathlab.database.repositories import WSIRepository

@app.get("/wsi")
async def list_wsi(skip: int = 0, limit: int = 100,
                   db: AsyncSession = Depends(get_db)):
    """Query WSI slides from SQLite"""
    wsi_list = await WSIRepository.get_all(db, skip=skip, limit=limit)
    return {"items": [wsi.to_dict() for wsi in wsi_list]}
```

**Storage Strategy**:
- Structured data (metadata, tasks, results, chat): SQLite database
- Large files (WSI images): File system at `uploads/wsi_files/`
- Generated files (masks, patches): File system at `uploads/`

### 2. Preprocessing Service (`backend/preprocessing/main.py`)

**Purpose**: WSI file processing, tissue segmentation, patch extraction, tile generation, and image serving

**Port**: 内部端口（动态分配）

**Key Responsibilities**:
- Open and cache WSI files (OpenSlide/ASlide)
- Generate Deep Zoom Image (DZI) descriptors
- Serve image tiles on-demand
- Generate tissue masks (also serve as thumbnails)
- Extract tissue coordinates for AI processing
- LRU caching for performance

**API Endpoints**:
```python
GET /health                                    # Health check
GET /api/wsi                                   # List WSI slides
GET /api/wsi/{wsi_id}/dzi                      # DZI descriptor (XML/JSON)
GET /api/wsi/{wsi_id}/tiles/{z}/{x}_{y}.jpeg  # Image tile
GET /api/wsi/{wsi_id}/mask                     # Tissue mask image
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

**Port**: 内部端口（动态分配）

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
    task: str  # "wsi_classification"
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

### SQLite Database (Current Implementation)

✅ **WSI Metadata**: Stored in `wsi_slides` table（含患者信息：年龄、性别、来源）
✅ **AI Tasks**: Stored in `ai_tasks` table
✅ **AI Results**: Stored in `ai_results` table
✅ **Chat Conversations**: Stored in `chat_conversations` and `chat_messages` tables
✅ **Training Tasks**: Stored in `training_tasks`, `training_task_wsi`, `trained_models`, `training_logs` tables
✅ **User Profiles**: Stored in `user_profiles` table（OAuth 登录缓存）
✅ **Training Tasks**: Stored in `training_tasks` table
✅ **Trained Models**: Stored in `trained_models` table

### File-Based Storage (Legacy/Cache)

```
pathlab/uploads/
├── ai_results/         # Attention weights (.npy files)
│   └── {wsi_id}/
│       └── {task_id}_attention.npy
├── models/             # User-trained models
│   └── {model_id}/
│       ├── checkpoint.pth
│       ├── config.json
│       └── training_history.json
├── features/           # Global feature cache (reusable across tasks)
│   └── {extractor_name}/
│       └── {params_hash}/              # Preprocessing config hash
│           └── {wsi_id}.pt             # Cached features
├── training/           # Training task data
│   └── {task_id}/
│       └── features/
│           └── {wsi_id}.pt  # Symlink → global cache
├── coordinates/        # Tile coordinates cache (H5)
│   └── {wsi_id}_coords.h5
├── masks/              # Tissue segmentation masks (PNG, also serve as thumbnails)
│   └── {wsi_id}_mask.png
└── wsi_files/          # WSI image files (optional)
    └── {wsi_id}.svs
```

**Note**: All metadata (WSI info, tasks, results) is stored in SQLite database. Only large binary data is stored in files.

### Benefits of Current SQLite Approach

✅ **Zero Configuration**: 无需安装数据库服务器
✅ **Transaction Support**: ACID guarantees for data consistency
✅ **Rich Query Capabilities**: Efficient search, filter, and aggregation
✅ **Conversation Storage**: Full chat history persistence
✅ **Portable**: 单文件数据库，易于备份和迁移
✅ **Cross-Platform**: 自动适配 Linux/macOS/Windows 路径

## Future Storage Architecture (Production)

Based on industry best practices from **Digital Slide Archive (DSA)** and **Cytomine**, we recommend a **hybrid storage architecture**:

### Phase 1: SQLite (Quick Start)

**Current SQLite Advantages**:
- ✅ Zero configuration (serverless)
- ✅ ACID transactions
- ✅ SQL query capabilities
- ✅ Easy migration path to PostgreSQL (if needed)
- ✅ Perfect for single-server deployments
- ✅ 已实现并投入使用

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

### Phase 2: PostgreSQL + MinIO (Future Production)

**Recommended Architecture for Large-Scale Deployment** (inspired by Cytomine):

```
┌─────────────────────────────────────────────────────────────┐
│                  Production Architecture                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  PostgreSQL Database (可选升级)                       │   │
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
│  │  - Masks and cached tiles                            │   │
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

**Why PostgreSQL for Future Scale?** (Following Cytomine's approach)
- ✅ Proven in production digital pathology platforms
- ✅ Strong ACID guarantees
- ✅ pgvector extension for semantic search (chat history)
- ✅ Full-text search capabilities
- ✅ JSON/JSONB support for flexible schemas
- ✅ Better concurrency for multi-user scenarios
- ✅ Excellent Python ecosystem (asyncpg, SQLAlchemy)

**Why MinIO?** (Following DSA's approach)
- ✅ S3-compatible API (easy migration to AWS/Azure)
- ✅ Self-hosted (no cloud vendor lock-in)
- ✅ Optimized for large files (WSI images)
- ✅ Built-in versioning and lifecycle policies
- ✅ Docker deployment ready

**Implementation Roadmap** (if upgrading to PostgreSQL):

1. ✅ **已完成**: SQLAlchemy models 和 Repository pattern
2. ✅ **已完成**: Conversation storage API
3. ✅ **已完成**: SQLite 数据库实现
4. **Future**: Add MinIO integration for WSI files (if needed)
5. **Future**: Add pgvector for semantic chat search
6. **Future**: Performance testing and optimization

## Development Setup

### Prerequisites

- Python 3.8+
- pip or conda
- WSI files (`.svs`, `.tif`, or other OpenSlide-compatible formats)

### Installation

```bash
# Navigate to project root
cd pathlab

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
# 推荐：通过统一入口启动（自动端口发现）
cd server && python main.py

# 输出示例:
# PORT=48427              ← Electron 通过此解析端口
# [Gateway] Starting on port 48427
# [Services] Gateway: 48427, Preprocessing: 47001, AI: 53633
# [Database] Using SQLite: sqlite+aiosqlite:///~/.local/share/PathLab/pathlab.db
```

This starts all services with dynamic port allocation.

#### Option 2: Electron Development Mode

```bash
# 在 pathlab-client 目录执行
npm run dev
```

Electron 自动启动 Python 后端并解析端口。

### Stopping Services

```bash
# From project root
./pathlab/stop_all.sh
```

### Health Checks

```bash
# 端口动态分配，需要先获取实际端口
# 启动时查看 PORT=xxxxx 输出

# Check Gateway (使用实际端口)
curl http://127.0.0.1:$PORT/health
```

## Data Flow Examples

### Example 1: WSI Upload and Registration

```bash
# 注意：端口动态分配，以下示例使用 $PORT 变量
# 实际使用时替换为启动时输出的端口号

# Register a WSI by file path (no file copy)
curl -X POST http://127.0.0.1:$PORT/wsi/upload/path \
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
# Submit analysis task (使用动态端口)
curl -X POST http://127.0.0.1:$PORT/tasks/wsi_classification \
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
curl http://127.0.0.1:$PORT/tasks/task_abc123

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
# Chat with AI assistant (使用动态端口)
curl -X POST http://127.0.0.1:$PORT/chat \
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

Located in `pathlab/services/gateway/main.py`:

```python
# Uploads directory
UPLOADS_DIR = Path(__file__).resolve().parents[3] / "uploads"

# Metadata auto-generation from CSV
CSV_PATH = UPLOADS_DIR.parent / "services" / "frontend" / "public" / "source.csv"

# Backend service URLs (动态分配，运行时确定)
# 内部服务端口在启动时自动发现
```

### Preprocessing Service Configuration

Located in `pathlab/services/backend/preprocessing/main.py`:

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

Located in `pathlab/services/backend/ai/main.py`:

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
# 注意：端口动态分配，以下示例使用 $PORT 变量
# 实际使用时替换为启动时输出的端口号

# Test WSI list endpoint
curl http://127.0.0.1:$PORT/wsi

# Test WSI metadata
curl http://127.0.0.1:$PORT/wsi/slide_001

# Test system statistics
curl http://127.0.0.1:$PORT/stats
```

### Automated Testing (Planned)

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest tests/

# Run with coverage
pytest --cov=pathlab tests/
```

## API Documentation

### Interactive API Docs

FastAPI provides automatic interactive documentation:

```bash
# 启动服务后访问（端口动态分配）
python main.py
# PORT=48427
# 访问: http://127.0.0.1:48427/docs
```

### OpenAPI Specification

```bash
# 访问: http://127.0.0.1:$PORT/openapi.json
```

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

# Or manually create metadata (使用动态端口)
curl -X POST http://127.0.0.1:$PORT/wsi/upload/path \
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
- [SQLite Documentation](https://www.sqlite.org/docs.html)
- [aiosqlite Documentation](https://aiosqlite.omnilib.dev/)
- [MinIO Documentation](https://min.io/docs/) (Future)

## Contributing

1. Follow PEP 8 style guide
2. Use type hints for all functions
3. Add docstrings for public APIs
4. Write tests for new features
5. Update API documentation

## License

See root repository LICENSE file.


