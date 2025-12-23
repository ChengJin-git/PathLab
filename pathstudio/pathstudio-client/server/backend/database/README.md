# PathStudio Database Layer

SQLite-based data persistence layer for PathStudio platform. **零配置，开箱即用。**

## Overview

This directory contains the database layer implementation using:
- **SQLite**: 零配置嵌入式数据库（无需安装服务）
- **SQLAlchemy 2.0+**: Async ORM for Python
- **aiosqlite**: 异步 SQLite 驱动

## 核心特性

- ✅ **零配置**: 无需安装 PostgreSQL 或任何数据库服务
- ✅ **自动创建**: 首次启动自动创建数据库和表
- ✅ **平台感知**: 自动选择平台特定的数据目录
- ✅ **开发友好**: 单文件数据库，易于备份和调试

## Directory Structure

```
backend/database/
├── README.md                   # This file
├── __init__.py                 # Package exports
├── database.py                 # SQLite 连接管理 (异步引擎)
├── models.py                   # SQLAlchemy ORM models
└── repositories.py             # Data access layer (Repository pattern)
```

## 数据库存储位置

数据库文件自动存储在平台特定目录：

| 平台 | 路径 |
|------|------|
| **Linux** | `~/.local/share/PathStudio/pathstudio.db` |
| **macOS** | `~/Library/Application Support/PathStudio/pathstudio.db` |
| **Windows** | `%APPDATA%/PathStudio/pathstudio.db` |

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
5. **trained_models**: User-trained model metadata
6. **training_logs**: Training log entries (real-time streaming)
7. **chat_conversations**: Chat sessions (conversation_id, user_id, title)
8. **chat_messages**: Chat history (role, content, metadata)
9. **user_profiles**: 本地用户信息缓存（OAuth 登录后）

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

### 1. 无需手动初始化！

数据库在服务启动时自动创建。直接运行：

```bash
cd server && python main.py
# 输出:
# [Database] Using SQLite: sqlite+aiosqlite:///~/.local/share/PathStudio/pathstudio.db
# [Database] ✓ All tables created/verified successfully
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

SQLite 表结构在首次启动时自动创建。如需修改 schema：

### 方式一：修改 models.py（推荐）

1. 修改 `models.py` 中的模型定义
2. 删除数据库文件（开发环境）
3. 重新启动服务

```bash
# Linux
rm ~/.local/share/PathStudio/pathstudio.db

# 重启服务
cd server && python main.py
```

### 方式二：手动迁移（保留数据）

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

**注意**: SQLite 的 `ALTER TABLE` 功能有限，不支持修改/删除列。

## Repository Pattern

The repository pattern provides a clean abstraction over database operations.

### Available Repositories

- **WSIRepository**: WSI slide operations
- **AITaskRepository**: AI task operations
- **AIResultRepository**: AI result operations
- **ChatRepository**: Chat conversation and message operations
- **TrainingTaskRepository**: Training task operations
- **TrainedModelRepository**: Trained model operations
- **TrainingLogRepository**: Training log operations
- **UserProfileRepository**: User profile operations (OAuth 登录)

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

**Solution**: 确保没有其他进程在使用数据库
```bash
# 查找占用进程
fuser ~/.local/share/PathStudio/pathstudio.db
```

### 重置数据库

删除数据库文件即可重置：

```bash
# Linux
rm ~/.local/share/PathStudio/pathstudio.db

# macOS
rm ~/Library/Application\ Support/PathStudio/pathstudio.db

# Windows
del %APPDATA%\PathStudio\pathstudio.db
```

## Best Practices

1. **Update models.py** after schema changes
2. **Use transactions** for data integrity
3. **Backup database** before major changes: `cp pathstudio.db pathstudio.db.bak`
4. **Monitor query performance** with `echo=True` during development

## References

- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/en/20/)
- [aiosqlite Documentation](https://aiosqlite.omnilib.dev/)
- [SQLite Documentation](https://www.sqlite.org/docs.html)
