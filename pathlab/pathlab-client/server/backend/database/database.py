"""
Database Connection and Session Management

SQLite database using SQLAlchemy 2.0+ and aiosqlite.
Zero-configuration local database for PathLab Client.
"""

import os
import sys
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from .models import Base


def get_database_path() -> Path:
    """
    Get the database file path based on the operating system.

    - Windows: %APPDATA%/PathLab/pathlab.db
    - macOS: ~/Library/Application Support/PathLab/pathlab.db
    - Linux: ~/.local/share/PathLab/pathlab.db
    """
    if sys.platform == "win32":
        base_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base_dir = Path.home() / "Library" / "Application Support"
    else:
        base_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    data_dir = base_dir / "PathLab"
    data_dir.mkdir(parents=True, exist_ok=True)

    return data_dir / "pathlab.db"


def get_database_url() -> str:
    """
    Get SQLite database URL.
    Uses environment variable if set, otherwise uses platform-specific path.
    """
    if db_url := os.environ.get("DATABASE_URL"):
        return db_url

    db_path = get_database_path()
    return f"sqlite+aiosqlite:///{db_path}"


# Database URL
DATABASE_URL = get_database_url()

# Create async engine for SQLite
# StaticPool is used because SQLite has limited concurrency support
engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL query logging
    future=True,
    # SQLite-specific settings
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Create async session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Don't expire objects after commit
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for FastAPI to get database session.
    
    Usage:
        @app.get("/wsi")
        async def list_wsi(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(WSISlide))
            return result.scalars().all()
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """
    Initialize database: create all tables.

    This should be called on application startup.
    SQLite database is created automatically if it doesn't exist.
    """
    print(f"[Database] Using SQLite: {DATABASE_URL}")
    async with engine.begin() as conn:
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
        print("[Database] ✓ All tables created/verified successfully")


async def drop_all_tables():
    """
    Drop all tables. USE WITH CAUTION!
    Only for development/testing.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        print("[Database] ⚠ All tables dropped")


async def close_db():
    """
    Close database connections.
    Should be called on application shutdown.
    """
    await engine.dispose()
    print("[Database] ✓ Database connections closed")

