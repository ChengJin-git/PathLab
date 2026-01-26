"""
Database Connection and Session Management

SQLite database using SQLAlchemy 2.0+ and aiosqlite.
Zero-configuration local database for PathLab Client.

Key optimizations for SQLite concurrency:
1. WAL (Write-Ahead Logging) mode - allows concurrent reads with a single writer
2. Busy timeout - wait for locks instead of failing immediately
3. AsyncAdaptedQueuePool - proper async connection pooling
"""

import os
import sys
import asyncio
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool
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

# Create async engine for SQLite with proper pooling
engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL query logging
    future=True,
    # SQLite-specific settings
    connect_args={
        "check_same_thread": False,
        "timeout": 60,  # Wait up to 60 seconds for locks to clear
    },
    # Use async-adapted queue pool for better connection management
    poolclass=AsyncAdaptedQueuePool,
    pool_size=5,  # Number of connections to keep
    max_overflow=10,  # Additional connections when busy
    pool_pre_ping=True,  # Verify connections before use
    pool_recycle=3600,  # Recycle connections after 1 hour
)


# Set up SQLite pragmas for better concurrency
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Configure SQLite for better concurrency and performance."""
    cursor = dbapi_connection.cursor()
    # WAL mode allows concurrent reads while writing
    cursor.execute("PRAGMA journal_mode=WAL")
    # Busy timeout in milliseconds
    cursor.execute("PRAGMA busy_timeout=60000")
    # Synchronous=NORMAL is safe with WAL and faster than FULL
    cursor.execute("PRAGMA synchronous=NORMAL")
    # Increase cache size (negative = KB, positive = pages)
    cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
    cursor.close()


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
            # Shield the close operation to ensure connection is returned to pool
            # even if the request/task is cancelled
            try:
                await asyncio.shield(session.close())
            except asyncio.CancelledError:
                # If the shield itself is cancelled (unlikely unless loop shutdown),
                # we just ignore it. The crucial part is that the inner session.close()
                # was protected by shield and continues running in background.
                pass


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
        print("[Database] All tables created/verified successfully")

    # Create default admin user if no users exist
    await _create_default_admin()


async def _create_default_admin():
    """Create default admin user if no users exist in the database."""
    try:
        # Import here to avoid circular imports
        from backend.auth.models import User
        from fastapi_users.password import PasswordHelper

        async with async_session() as session:
            from sqlalchemy import select, func

            # Check if any users exist
            result = await session.execute(select(func.count(User.id)))
            user_count = result.scalar()

            if user_count == 0:
                print("[Auth] No users found, creating default admin user...")

                # Create password hash
                password_helper = PasswordHelper()
                default_password = "password"
                hashed_password = password_helper.hash(default_password)

                # Create SHA256 hash for secure login
                import hashlib
                password_sha256 = hashlib.sha256(default_password.encode()).hexdigest()

                # Create admin user with simple username (not email format)
                import uuid
                admin_user = User(
                    id=uuid.uuid4(),
                    email="admin",  # Using simple username, not email format
                    hashed_password=hashed_password,
                    password_sha256=password_sha256,  # For secure login
                    is_active=True,
                    is_superuser=True,
                    is_verified=True,
                    role="admin",
                    nickname="Admin",
                )

                session.add(admin_user)
                await session.commit()
                print(f"[Auth] ✓ Default admin user created (username: admin, password: password)")
                print("[Auth] ⚠ Please change the default password after first login!")
            else:
                print(f"[Auth] Found {user_count} existing user(s), skipping default admin creation")
    except Exception as e:
        print(f"[Auth] Warning: Could not create default admin user: {e}")


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
    print("[Database] Database connections closed")

