# PathLab Database Layer

PostgreSQL-based data persistence layer for PathLab platform.

## Overview

This directory contains the database layer implementation using:
- **PostgreSQL**: Production-grade relational database with MVCC concurrency
- **SQLAlchemy 2.0+**: Async ORM for Python
- **asyncpg**: High-performance asynchronous PostgreSQL driver

## Core Features

- ✅ **MVCC concurrency**: Full concurrent reads and writes without lock contention
- ✅ **Automatic creation**: Tables are automatically created on first startup
- ✅ **Connection pooling**: AsyncAdaptedQueuePool with pool_size=20, max_overflow=10
- ✅ **Multi-user support**: Supports ~10+ concurrent users comfortably

## Directory Structure

```
backend/database/
├── README.md                   # This file
├── __init__.py                 # Package exports
├── database.py                 # PostgreSQL connection management (async engine)
├── models.py                   # SQLAlchemy ORM models
└── repositories.py             # Data access layer (Repository pattern)
```

## Database Connection

Configure via `DATABASE_URL` environment variable:

```bash
# Default (local development)
DATABASE_URL=postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab
```

## Database Schema

### Tables (17 total)

1. **users**: User accounts (FastAPI-Users with RBAC roles)
2. **accesstoken**: Access tokens for JWT authentication (FastAPI-Users)
3. **data_groups**: Data group definitions (data type, aggregation level, task type combinations)
4. **datasets**: Dataset metadata (UUID privacy protection, name, description)
5. **dataset_permissions**: Temporary elevated dataset permissions (GPU operations)
6. **wsi_slides**: WSI metadata and patient information
   - **Core Fields**: wsi_id, case_id, label, wsi_path, dataset_id
   - **Patient Metadata**: age (Integer), gender (String), source (String)
   - **Survival Fields**: event_time, event_status
   - **WSI Properties**: mpp, vendor, width, height, magnification
   - **Timestamps**: created_at, updated_at
7. **ai_tasks**: AI task tracking (task_id, status, progress, params)
8. **ai_results**: AI predictions (pred, probs, extra_metadata with file paths)
9. **chat_conversations**: Chat sessions (conversation_id, user_id, title)
10. **chat_messages**: Chat history (role, content, metadata)
11. **message_feedbacks**: Message feedback (thumbs up/down/task helpfulness)
12. **export_tasks**: Data export task tracking
13. **training_tasks**: Training task configuration and status (classification/survival)
14. **training_task_wsi**: Training task to WSI many-to-many relationship
15. **trained_models**: User-trained model metadata
16. **training_logs**: Training log entries (real-time SSE streaming)
17. **storage_tasks**: Storage operation task tracking (batch import/delete)

See `models.py` for detailed schema definitions.

### WSI Slides Schema Details

The `wsi_slides` table supports comprehensive metadata for pathology slides:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `wsi_id` | String | Unique slide identifier | `slide_001` |
| `case_id` | String | Patient/case identifier | `case_123` |
| `label` | String | Disease classification | `Benign`, `Malignant`, `HSIL` |
| `age` | Integer | Patient age in years | `45`, `62` |
| `gender` | String(20) | Patient gender | `Male`, `Female`, `Other` |
| `source` | String(100) | Organ/tissue source | `Cervix`, `Lung`, `Breast` |
| `wsi_path` | Text | Full path to WSI file | `/path/to/slide.svs` |
| `mpp` | Float | Microns per pixel | `0.25` |
| `vendor` | String | Scanner vendor | `Aperio`, `Hamamatsu` |
| `width` | Integer | Image width in pixels | `50000` |
| `height` | Integer | Image height in pixels | `40000` |
| `magnification` | Integer | Scan magnification | `20`, `40` |
| `created_at` | DateTime | Record creation time | `2024-10-29T10:30:00` |
| `updated_at` | DateTime | Last update time | `2024-10-29T14:15:00` |

## Quick Start

### 1. No manual initialization!

The database is automatically created on service startup. Run:

```bash
cd server && python main.py
```

### 2. Use in Application

```python
from backend.database import get_db
from backend.database.repositories import WSIRepository
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

@app.get("/wsi")
async def list_wsi(db: AsyncSession = Depends(get_db)):
    wsi_list = await WSIRepository.get_all(db, skip=0, limit=100)
    return {"items": [wsi.to_dict() for wsi in wsi_list]}
```

## Schema Changes

The PostgreSQL schema is automatically created on first startup via `Base.metadata.create_all`. To modify:

### Method 1: Update models.py (recommended)

1. Update the model definitions in `models.py`
2. Drop and recreate tables (development only), or use manual migration
3. Restart the service

### Method 2: Manual migration (preserve data)

```python
from backend.database import engine
from sqlalchemy import text

async def add_new_column():
    async with engine.begin() as conn:
        await conn.execute(text(
            'ALTER TABLE wsi_slides ADD COLUMN tissue_type TEXT'
        ))
        print('✓ Column added')

import asyncio
asyncio.run(add_new_column())
```

**Note**: PostgreSQL supports full `ALTER TABLE` operations including column type changes and deletions.

## Repository Pattern

The repository pattern provides a clean abstraction over database operations.

### Available Repositories

- **DatasetRepository**: Dataset operations
- **DatasetPermissionRepository**: Dataset permission operations
- **WSIRepository**: WSI slide operations
- **AITaskRepository**: AI task operations
- **AIResultRepository**: AI result operations
- **ChatRepository**: Chat conversation and message operations
- **FeedbackRepository**: Message feedback operations
- **ExportTaskRepository**: Export task operations
- **TrainingTaskRepository**: Training task operations
- **TrainedModelRepository**: Trained model operations
- **TrainingLogRepository**: Training log operations
- **StorageTaskRepository**: Storage task operations (batch import/delete)
- **OrphanedRecordsRepository**: Orphaned database records detection

### Example Usage

```python
from backend.database import async_session
from backend.database.repositories import WSIRepository

# Create WSI record with patient metadata
async with async_session() as db:
    wsi_data = {
        "wsi_id": "slide_001",
        "case_id": "case_123",
        "label": "Benign",
        "age": 45,
        "gender": "Female",
        "source": "Cervix",
        "wsi_path": "/path/to/slide.svs",
        "mpp": 0.25,
        "vendor": "Aperio",
        "width": 50000,
        "height": 40000,
        "magnification": 40
    }
    wsi = await WSIRepository.create(db, wsi_data)
    await db.commit()

# Query by ID
async with async_session() as db:
    wsi = await WSIRepository.get_by_id(db, "slide_001")
    print(wsi.to_dict())
```

## Session Management

```python
# Automatic session management with FastAPI
from fastapi import Depends
from backend.database import get_db

@app.get("/endpoint")
async def endpoint(db: AsyncSession = Depends(get_db)):
    # Session is automatically managed
    result = await db.execute(select(Model))
    return result.scalars().all()

# Manual session management
from backend.database import async_session

async with async_session() as db:
    try:
        # Your database operations
        await db.commit()
    except Exception:
        await db.rollback()
        raise
```

## Troubleshooting

### Connection pool exhaustion

```
QueuePool limit of size 20 overflow 10 reached, connection timed out
```

**Solution**: Check for long-held connections (e.g., SSE streams not releasing sessions properly).
Use `safe_session()` for SSE endpoints to ensure proper cleanup on client disconnect.

### Reset the database

```sql
-- Connect to PostgreSQL and drop/recreate
DROP DATABASE pathlab;
CREATE DATABASE pathlab OWNER pathlab;
```

## Best Practices

1. **Update models.py** after schema changes
2. **Use transactions** for data integrity
3. **Use `safe_session()`** for SSE endpoints (protects against uvicorn cancellation)
4. **Use `scoped_db()`** for AI service operations (short-lived sessions)
5. **Monitor query performance** with `echo=True` during development

## References

- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/en/20/)
- [asyncpg Documentation](https://magicstack.github.io/asyncpg/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
