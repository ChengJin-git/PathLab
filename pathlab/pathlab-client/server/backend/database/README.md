# PathLab Database Layer

SQLite-based data persistence layer for PathLab platform. **零配置，开箱即用。**

> 📌 无论是网页端（调试模式）还是本地端（打包模式），都使用相同的 SQLite 数据库。

## Overview

This directory contains the database layer implementation using:
- **SQLite**: Zero configuration embedded database (no service installation)
- **SQLAlchemy 2.0+**: Async ORM for Python
- **aiosqlite**: Asynchronous SQLite driver

## Core Features

- ✅ **Zero configuration**: No need to install PostgreSQL or any database service
- ✅ **Automatic creation**: Database and tables are automatically created on first startup
- ✅ **Platform aware**: Automatically selects platform-specific data directory
- ✅ **Development friendly**: Single-file database, easy backup and debugging

## Directory Structure

```
backend/database/
├── README.md                   # This file
├── __init__.py                 # Package exports
├── database.py                 # SQLite connection management (async engine)
├── models.py                   # SQLAlchemy ORM models
└── repositories.py             # Data access layer (Repository pattern)
```

## Database Storage Location

The database file is automatically stored in the platform-specific directory:

| Platform | Path |
|------|------|
| **Linux** | `~/.local/share/PathLab/pathlab.db` |
| **macOS** | `~/Library/Application Support/PathLab/pathlab.db` |
| **Windows** | `%APPDATA%/PathLab/pathlab.db` |

## Database Schema

### Tables (11 total)

1. **datasets**: Dataset metadata (UUID privacy protection, name, description)
2. **wsi_slides**: WSI metadata and patient information
   - **Core Fields**: wsi_id, case_id, label, wsi_path, dataset_id
   - **Patient Metadata**: age (Integer), gender (String), source (String)
   - **WSI Properties**: mpp, vendor, width, height, magnification
   - **Segmentation Fields**: segmentation_path, segmentation_label, segmentation_model
   - **Timestamps**: created_at, updated_at
3. **ai_tasks**: AI task tracking (task_id, status, progress, params)
4. **ai_results**: AI predictions (pred, probs, extra_metadata with file paths)
5. **training_tasks**: Training task configuration and status (classification/survival)
6. **training_task_wsi**: Training task to WSI many-to-many relationship
7. **trained_models**: User-trained model metadata
8. **training_logs**: Training log entries (real-time SSE streaming)
9. **chat_conversations**: Chat sessions (conversation_id, user_id, title)
10. **chat_messages**: Chat history (role, content, metadata)
11. **user_profiles**: Local user profile cache (OAuth login via Casdoor)

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

The SQLite schema is automatically created on first startup. To modify:

### Method 1: Update models.py (recommended)

1. Update the model definitions in `models.py`
2. Delete the database file (development only)
3. Restart the service

```bash
# Linux
rm ~/.local/share/PathLab/pathlab.db

# Restart the service
cd server && python main.py
```

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

**Note**: SQLite's `ALTER TABLE` functionality is limited, and does not support column changes/deletions.

## Repository Pattern

The repository pattern provides a clean abstraction over database operations.

### Available Repositories

- **DatasetRepository**: Dataset operations
- **WSIRepository**: WSI slide operations
- **AITaskRepository**: AI task operations
- **AIResultRepository**: AI result operations
- **ChatConversationRepository**: Chat conversation operations
- **ChatMessageRepository**: Chat message operations
- **TrainingTaskRepository**: Training task operations
- **TrainingTaskWSIRepository**: Training task to WSI relationship operations
- **TrainedModelRepository**: Trained model operations
- **TrainingLogRepository**: Training log operations
- **UserProfileRepository**: User profile operations (OAuth login via Casdoor)

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

### Database locked

```
sqlite3.OperationalError: database is locked
```

**Solution**: Ensure no other processes are using the database
```bash
# Find processes using the database
fuser ~/.local/share/PathLab/pathlab.db
```

### Reset the database

Delete the database file to reset:

```bash
# Linux
rm ~/.local/share/PathLab/pathlab.db

# macOS
rm ~/Library/Application\ Support/PathLab/pathlab.db

# Windows
del %APPDATA%\PathLab\pathlab.db
```

## Best Practices

1. **Update models.py** after schema changes
2. **Use transactions** for data integrity
3. **Backup database** before major changes: `cp pathlab.db pathlab.db.bak`
4. **Monitor query performance** with `echo=True` during development

## References

- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/en/20/)
- [aiosqlite Documentation](https://aiosqlite.omnilib.dev/)
- [SQLite Documentation](https://www.sqlite.org/docs.html)
