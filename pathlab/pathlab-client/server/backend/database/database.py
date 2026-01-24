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

        from sqlalchemy import text

        # Migration 1: Check if 'split' column exists in 'wsi_slides'
        try:
            result = await conn.execute(text("PRAGMA table_info(wsi_slides)"))
            columns = [row[1] for row in result.fetchall()]

            if "split" not in columns:
                print("[Database] Migrating: Adding 'split' column to wsi_slides")
                await conn.execute(text("ALTER TABLE wsi_slides ADD COLUMN split VARCHAR(20)"))
        except Exception as e:
            print(f"[Database] Migration warning (split column): {e}")

        # Migration 2: Dataset privacy migration (dataset_name -> dataset_id)
        # This runs automatically on startup to migrate existing data
        try:
            result = await conn.execute(text("PRAGMA table_info(wsi_slides)"))
            columns = [row[1] for row in result.fetchall()]

            has_dataset_name = "dataset_name" in columns
            has_dataset_id = "dataset_id" in columns

            # If we have dataset_name but no dataset_id, need full migration
            if has_dataset_name and not has_dataset_id:
                print("[Database] Migrating: Adding 'dataset_id' column to wsi_slides")
                await conn.execute(text("ALTER TABLE wsi_slides ADD COLUMN dataset_id VARCHAR(255)"))
                print("[Database] ⚠ NOTE: Run 'python -m backend.database.migrate_datasets' to migrate existing data")

            # If we have dataset_name, migrate data to datasets table and update references
            if has_dataset_name:
                # Check if any wsi_slides have dataset_name but not dataset_id
                result = await conn.execute(text(
                    "SELECT COUNT(*) FROM wsi_slides WHERE dataset_name IS NOT NULL AND (dataset_id IS NULL OR dataset_id = '')"
                ))
                unmigrated_count = result.fetchone()[0]

                if unmigrated_count > 0:
                    print(f"[Database] Found {unmigrated_count} slides needing dataset migration")
                    print("[Database] ⚠ Run 'python -m backend.database.migrate_datasets' to complete migration")
        except Exception as e:
            print(f"[Database] Migration warning (dataset_id column): {e}")

        # Migration 3: Add user_id columns to business tables
        await _migrate_user_id_columns(conn)

        # Migration 4: Add agreement_accepted_at column to users table
        await _migrate_agreement_column(conn)

        print("[Database] All tables created/verified successfully")

    # Create default admin user if no users exist
    await _create_default_admin()


async def _migrate_user_id_columns(conn):
    """Add user_id column to all business tables that need it."""
    from sqlalchemy import text

    tables_needing_user_id = [
        "datasets",
        "wsi_slides",
        "ai_tasks",
        "ai_results",
        "training_tasks",
        "trained_models",
    ]

    for table_name in tables_needing_user_id:
        try:
            result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
            columns = [row[1] for row in result.fetchall()]

            if "user_id" not in columns:
                print(f"[Database] Migrating: Adding 'user_id' column to {table_name}")
                await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN user_id VARCHAR(255)"))
                # Create index for user_id
                await conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_user_id ON {table_name}(user_id)"))
        except Exception as e:
            print(f"[Database] Migration warning (user_id in {table_name}): {e}")


async def _migrate_agreement_column(conn):
    """Add agreement_accepted_at column to users table if not exists."""
    from sqlalchemy import text

    try:
        result = await conn.execute(text("PRAGMA table_info(users)"))
        columns = [row[1] for row in result.fetchall()]

        if "agreement_accepted_at" not in columns:
            print("[Database] Migrating: Adding 'agreement_accepted_at' column to users table")
            await conn.execute(text("ALTER TABLE users ADD COLUMN agreement_accepted_at DATETIME"))
    except Exception as e:
        print(f"[Database] Migration warning (agreement_accepted_at in users): {e}")


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
                hashed_password = password_helper.hash("password")

                # Create admin user
                import uuid
                admin_user = User(
                    id=uuid.uuid4(),
                    email="admin@pathlab.local",
                    hashed_password=hashed_password,
                    is_active=True,
                    is_superuser=True,
                    is_verified=True,
                    role="admin",
                    nickname="Admin",
                )

                session.add(admin_user)
                await session.commit()
                print(f"[Auth] ✓ Default admin user created (email: admin@pathlab.local, password: password)")
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

