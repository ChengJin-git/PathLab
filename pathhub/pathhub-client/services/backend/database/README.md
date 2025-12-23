# PathHub Database Layer

PostgreSQL-based data persistence layer for PathHub platform.

## Overview

This directory contains the database layer implementation using:
- **PostgreSQL 15**: Production-grade relational database
- **SQLAlchemy 2.0+**: Async ORM for Python
- **asyncpg**: High-performance async PostgreSQL driver

## Directory Structure

```
pathhub/services/backend/database/
├── README.md                   # This file
├── __init__.py                 # Package exports
├── database.py                 # Connection management (engine, session factory)
├── models.py                   # SQLAlchemy ORM models (WSISlide, AITask, AIResult, etc.)
├── repositories.py             # Data access layer (Repository pattern)
└── init_db.py                  # Database initialization and data migration script
```

## Database Schema

### Tables

1. **wsi_slides**: WSI metadata and patient information
   - **Core Fields**: wsi_id, case_id, label, wsi_path
   - **Patient Metadata**: age (Integer), gender (String), source (String)
   - **WSI Properties**: mpp, vendor, width, height, magnification
   - **Timestamps**: created_at, updated_at
2. **ai_tasks**: AI task tracking (task_id, status, progress, params)
3. **ai_results**: AI predictions (pred, probs, extra_metadata with file paths)
4. **training_tasks**: Training task configuration and status
5. **trained_models**: User-trained model metadata (model_path, classes, metrics, is_default, is_active)
6. **chat_conversations**: Chat sessions (conversation_id, user_id, title)
7. **chat_messages**: Chat history (role, content, metadata)

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

### 1. Start PostgreSQL

```bash
# Using Docker Compose (recommended)
docker compose up -d postgres

# Verify PostgreSQL is running
docker compose ps postgres
```

### 2. Initialize Database

```bash
# Run initialization script (creates tables and migrates JSON data)
python pathhub/services/backend/database/init_db.py
```

### 3. Use in Application

```python
from pathhub.services.backend.database import get_db
from pathhub.services.backend.database.repositories import WSIRepository
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

@app.get("/wsi")
async def list_wsi(db: AsyncSession = Depends(get_db)):
    wsi_list = await WSIRepository.get_all(db, skip=0, limit=100)
    return {"items": [wsi.to_dict() for wsi in wsi_list]}
```

## Schema Changes

For this research project, we use direct SQL for schema changes instead of migration tools.

### Adding New Columns

```python
from pathhub.services.backend.database import engine
from sqlalchemy import text

async def add_new_column():
    async with engine.begin() as conn:
        await conn.execute(text(
            'ALTER TABLE wsi_slides ADD COLUMN new_field VARCHAR(100)'
        ))
        print('✓ Column added')

# Run it
import asyncio
asyncio.run(add_new_column())
```

### Common Schema Operations

#### Add Column
```sql
ALTER TABLE wsi_slides ADD COLUMN tissue_type VARCHAR(50);
```

#### Modify Column
```sql
ALTER TABLE wsi_slides ALTER COLUMN label TYPE VARCHAR(200);
```

#### Add Index
```sql
CREATE INDEX idx_label ON wsi_slides(label);
```

#### Drop Column
```sql
ALTER TABLE wsi_slides DROP COLUMN old_field;
```

### Updating Models

After changing the database schema, update the corresponding model in `models.py`:

```python
# models.py
class WSISlide(Base):
    __tablename__ = "wsi_slides"

    # Add new field
    tissue_type = Column(String(50))
```

## Repository Pattern

The repository pattern provides a clean abstraction over database operations.

### Available Repositories

- **WSIRepository**: WSI slide operations
- **AITaskRepository**: AI task operations
- **AIResultRepository**: AI result operations
- **ChatRepository**: Chat conversation and message operations

### Example Usage

```python
from pathhub.services.backend.database import async_session
from pathhub.services.backend.database.repositories import WSIRepository

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

# Query with filters
async with async_session() as db:
    hsil_slides = await WSIRepository.get_by_label(db, "HSIL")

# Get statistics
async with async_session() as db:
    total = await WSIRepository.count(db)
    distribution = await WSIRepository.get_label_distribution(db)
    print(f"Total slides: {total}")
    print(f"Distribution: {distribution}")
```

## Connection Management

### Configuration

Set database URL via environment variable:

```bash
# Default (Docker PostgreSQL)
export DATABASE_URL="postgresql+asyncpg://pathhub:pathhub@localhost:5432/pathhub"

# Custom PostgreSQL
export DATABASE_URL="postgresql+asyncpg://user:password@host:port/database"
```

### Connection Pool

```python
# pathhub/database/database.py
engine = create_async_engine(
    DATABASE_URL,
    echo=False,              # SQL query logging
    pool_pre_ping=True,      # Verify connections
    pool_size=10,            # Pool size
    max_overflow=20,         # Max overflow
)
```

### Session Management

```python
# Automatic session management with FastAPI
from fastapi import Depends
from pathhub.services.backend.database import get_db

@app.get("/endpoint")
async def endpoint(db: AsyncSession = Depends(get_db)):
    # Session is automatically managed
    # Commits on success, rolls back on error
    result = await db.execute(select(Model))
    return result.scalars().all()

# Manual session management
from pathhub.services.backend.database import async_session

async with async_session() as db:
    try:
        # Your database operations
        await db.commit()
    except Exception:
        await db.rollback()
        raise
```

## Database Initialization

The `init_db.py` script creates all database tables.

### Initialization Process

```bash
python pathhub/services/backend/database/init_db.py
```

This will create all database tables required for the application.

### Initialization Output

```
============================================================
PathHub Database Initialization
============================================================

Creating database tables...

============================================================
✓ Database initialization completed!
============================================================
```

## Troubleshooting

### Connection Refused

```
OSError: [Errno 111] Connect call failed
```

**Solution**: Ensure PostgreSQL is running
```bash
docker compose up -d postgres
docker compose ps postgres
```

### Permission Denied (Docker)

```
permission denied while trying to connect to the Docker daemon socket
```

**Solution**: Add user to docker group
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### Table Already Exists

```
sqlalchemy.exc.ProgrammingError: relation "wsi_slides" already exists
```

**Solution**: Database is already initialized, skip `init_db.py`

## Best Practices

1. **Update models.py** after schema changes to keep code and database in sync
2. **Use transactions** for data integrity
3. **Index frequently queried columns** for performance
4. **Use connection pooling** for better resource management
5. **Monitor query performance** with `echo=True` during development
6. **Backup data** before major schema changes
7. **Test schema changes** on development database first

## References

- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/en/20/)
- [asyncpg Documentation](https://magicstack.github.io/asyncpg/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [PostgreSQL ALTER TABLE](https://www.postgresql.org/docs/current/sql-altertable.html)

