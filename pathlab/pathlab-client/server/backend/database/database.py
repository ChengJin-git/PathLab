"""
Database Connection and Session Management

PostgreSQL database using SQLAlchemy 2.0+ and asyncpg.
Supports multi-user concurrent access for PathLab platform.

Key features:
1. PostgreSQL MVCC - full concurrent reads and writes without lock contention
2. asyncpg - high-performance async PostgreSQL driver
3. AsyncAdaptedQueuePool - proper async connection pooling
"""

import os
import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool
from backend.common.config import Config
from .models import Base

logger = logging.getLogger(__name__)


def get_database_url() -> str:
    """
    Get PostgreSQL database URL.
    Uses DATABASE_URL environment variable, with a sensible default for local development.
    """
    if db_url := os.environ.get("DATABASE_URL"):
        return db_url

    # Default: local PostgreSQL for development
    return Config.DATABASE_URL_DEFAULT


# Database URL
DATABASE_URL = get_database_url()

# Create async engine for PostgreSQL with proper pooling
engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL query logging
    future=True,
    # Use async-adapted queue pool for better connection management
    # Pool must be large enough for multi-user concurrent access:
    # - Each user may open 2-3 SSE streams (training tasks, storage tasks, training logs)
    # - Each SSE stream holds a DB connection briefly every poll cycle
    # - API requests also need connections concurrently
    # With pool_size=20 + max_overflow=10 = 30 total connections,
    # this supports ~10 concurrent users comfortably.
    poolclass=AsyncAdaptedQueuePool,
    pool_size=20,  # Base connections to keep in pool
    max_overflow=10,  # Additional connections when all base connections are busy
    pool_timeout=10,  # Fail fast (10s) instead of blocking 30s when pool is exhausted
    pool_pre_ping=True,  # Verify connections before use
    pool_recycle=3600,  # Recycle connections after 1 hour
)


# Create async session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Don't expire objects after commit
    autocommit=False,
    autoflush=False,
)


from contextlib import asynccontextmanager
import anyio


@asynccontextmanager
async def safe_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Safe session context manager for use in SSE streams and other cancellable contexts.

    This ensures that the database connection is properly returned to the pool even if
    the coroutine is cancelled (e.g., when SSE client disconnects).

    IMPORTANT: We use anyio.CancelScope(shield=True) instead of asyncio.shield() because
    uvicorn/starlette uses anyio's cancel scope for cancellation. asyncio.shield() does NOT
    protect against anyio cancel scope cancellation. See SQLAlchemy issue #8145.

    Usage:
        async with safe_session() as db:
            result = await db.execute(select(WSISlide))
            # ...
    """
    # Create session directly without using async_session() as context manager
    # This gives us full control over the close() operation
    session = async_session()
    try:
        yield session
    except Exception:
        # Rollback on any exception (including CancelledError)
        # Use anyio cancel scope shield to protect against uvicorn/starlette cancellation
        with anyio.CancelScope(shield=True):
            await session.rollback()
        raise
    finally:
        # Shield the close operation to ensure connection is returned to pool
        # even if the coroutine is cancelled by anyio cancel scope
        with anyio.CancelScope(shield=True):
            await session.close()


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
            # even if the request/task is cancelled.
            # Use anyio.CancelScope(shield=True) because uvicorn/starlette uses anyio's
            # cancel scope for cancellation. asyncio.shield() does NOT protect against
            # anyio cancel scope cancellation. See SQLAlchemy issue #8145.
            with anyio.CancelScope(shield=True):
                await session.close()


async def init_db():
    """
    Initialize database: create all tables.

    This should be called on application startup.
    PostgreSQL tables are created automatically if they don't exist.
    """
    # Mask password in URL for logging
    import re
    safe_url = re.sub(r'://([^:]+):([^@]+)@', r'://\1:***@', DATABASE_URL)
    logger.info(f"Using PostgreSQL: {safe_url}")
    # Import all models to register them in Base.metadata BEFORE create_all.
    # User model lives in backend.auth.models but shares the same Base.
    # Without this import, the "users" table won't be created.
    import backend.auth.models  # noqa: F401

    async with engine.begin() as conn:
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
        logger.info("All tables created/verified successfully")

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
                logger.info("No users found, creating default admin user...")

                # Create password hash - use environment variable or fallback
                password_helper = PasswordHelper()
                default_password = os.getenv("DEFAULT_ADMIN_PASSWORD", "pathlab_default_password123")
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
                logger.warning("Default admin user created (username: admin). Please change the default password after first login!")
            else:
                logger.info(f"Found {user_count} existing user(s), skipping default admin creation")
    except Exception as e:
        logger.error(f"Could not create default admin user: {e}")


async def drop_all_tables():
    """
    Drop all tables. USE WITH CAUTION!
    Only for development/testing.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        logger.warning("All tables dropped")


async def close_db():
    """
    Close database connections.
    Should be called on application shutdown.
    """
    await engine.dispose()
    print("[Database] Database connections closed")

