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
from sqlalchemy.exc import DBAPIError, InterfaceError, SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy import text
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


async def _invalidate_session_connection(session: AsyncSession) -> None:
    """Drop a broken DBAPI connection so the pool opens a fresh one next time."""
    try:
        await session.invalidate()
    except Exception:
        logger.debug("Unable to invalidate broken database connection", exc_info=True)


async def _rollback_safely(session: AsyncSession, *, context: str) -> None:
    try:
        with anyio.CancelScope(shield=True):
            await session.rollback()
    except (InterfaceError, DBAPIError) as exc:
        logger.warning(
            "Ignoring rollback failure after database connection closed (%s): %s",
            context,
            exc,
        )
        await _invalidate_session_connection(session)
    except SQLAlchemyError:
        logger.exception("Database rollback failed (%s)", context)


async def _close_safely(session: AsyncSession, *, context: str) -> None:
    try:
        with anyio.CancelScope(shield=True):
            await session.close()
    except SQLAlchemyError:
        logger.exception("Database session close failed (%s)", context)


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
        await _rollback_safely(session, context="safe_session exception")
        raise
    finally:
        # Shield the close operation to ensure connection is returned to pool
        # even if the coroutine is cancelled by anyio cancel scope
        await _close_safely(session, context="safe_session")


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
            with anyio.CancelScope(shield=True):
                await session.commit()
        except (InterfaceError, DBAPIError) as exc:
            logger.warning(
                "Database dependency transaction ended on a closed/broken connection: %s",
                exc,
            )
            await _invalidate_session_connection(session)
            await _rollback_safely(session, context="get_db broken connection")
            raise
        except Exception:
            await _rollback_safely(session, context="get_db exception")
            raise
        finally:
            # Shield the close operation to ensure connection is returned to pool
            # even if the request/task is cancelled.
            # Use anyio.CancelScope(shield=True) because uvicorn/starlette uses anyio's
            # cancel scope for cancellation. asyncio.shield() does NOT protect against
            # anyio cancel scope cancellation. See SQLAlchemy issue #8145.
            await _close_safely(session, context="get_db")


async def init_db():
    import re

    safe_url = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", DATABASE_URL)
    logger.info(f"Using PostgreSQL: {safe_url}")
    import backend.auth.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logger.info("All tables created/verified successfully")
        await conn.execute(
            text(
                "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS "
                "parent_dataset_id VARCHAR(255) REFERENCES datasets(dataset_id) ON DELETE SET NULL"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE segmentation_annotations "
                "ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE segmentation_annotations "
                "ADD COLUMN IF NOT EXISTS last_edited_by VARCHAR(255)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE segmentation_annotations "
                "ADD COLUMN IF NOT EXISTS visibility_mode VARCHAR(20) NOT NULL DEFAULT 'personal'"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE wsi_slides ADD COLUMN IF NOT EXISTS data_type VARCHAR(20)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_wsi_user_type"
                " ON wsi_slides (user_id, data_type)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_wsi_dataset_type"
                " ON wsi_slides (dataset_id, data_type)"
            )
        )
        logger.info("wsi_slides.data_type column and indexes ensured")
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS dataset_stats ("
                "    dataset_id   VARCHAR(255) PRIMARY KEY"
                "        REFERENCES datasets(dataset_id) ON DELETE CASCADE,"
                "    file_count        INTEGER   NOT NULL DEFAULT 0,"
                "    total_size        BIGINT    NOT NULL DEFAULT 0,"
                "    split_train_count INTEGER   NOT NULL DEFAULT 0,"
                "    split_val_count   INTEGER   NOT NULL DEFAULT 0,"
                "    split_test_count  INTEGER   NOT NULL DEFAULT 0,"
                "    updated_at        TIMESTAMP NOT NULL DEFAULT NOW()"
                ")"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO dataset_stats"
                " (dataset_id, file_count, total_size,"
                "  split_train_count, split_val_count, split_test_count, updated_at)"
                " SELECT w.dataset_id, COUNT(*), COALESCE(SUM(w.file_size), 0),"
                "   COUNT(DISTINCT CASE WHEN LOWER(w.split) = 'train' THEN"
                "     CASE WHEN dg.aggregation_level = 'case'"
                "       THEN COALESCE(w.case_id, w.wsi_id) ELSE w.wsi_id END END),"
                "   COUNT(DISTINCT CASE WHEN LOWER(w.split) IN ('val','validation') THEN"
                "     CASE WHEN dg.aggregation_level = 'case'"
                "       THEN COALESCE(w.case_id, w.wsi_id) ELSE w.wsi_id END END),"
                "   COUNT(DISTINCT CASE WHEN LOWER(w.split) = 'test' THEN"
                "     CASE WHEN dg.aggregation_level = 'case'"
                "       THEN COALESCE(w.case_id, w.wsi_id) ELSE w.wsi_id END END),"
                "   NOW()"
                " FROM wsi_slides w"
                " JOIN datasets d ON w.dataset_id = d.dataset_id"
                " JOIN data_groups dg ON d.group_id = dg.group_id"
                " GROUP BY w.dataset_id"
                " ON CONFLICT (dataset_id) DO NOTHING"
            )
        )
        logger.info("dataset_stats table ensured and pre-populated")

        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "registration_email VARCHAR(320) DEFAULT NULL"
            )
        )
        logger.info("users.registration_email column ensured")

        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "first_activated_at TIMESTAMP DEFAULT NULL"
            )
        )
        await conn.execute(
            text(
                "UPDATE users SET first_activated_at = NOW() "
                "WHERE first_activated_at IS NULL"
            )
        )
        logger.info("users.first_activated_at column ensured and backfilled")

        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "notify_on_success BOOLEAN NOT NULL DEFAULT TRUE"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "notify_on_failed BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "notify_on_cancelled BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        logger.info("users.notify_on_* columns ensured")

        await conn.execute(
            text(
                "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS "
                "is_public BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        logger.info("datasets.is_public column ensured")

        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS dataset_grants ("
                "    id           SERIAL PRIMARY KEY,"
                "    dataset_id   VARCHAR(255) NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,"
                "    user_id      VARCHAR(255) NOT NULL,"
                "    granted_by   VARCHAR(255) NOT NULL,"
                "    can_collaborate BOOLEAN NOT NULL DEFAULT FALSE,"
                "    can_use_gpu  BOOLEAN NOT NULL DEFAULT FALSE,"
                "    expires_at   TIMESTAMP,"
                "    created_at   TIMESTAMP NOT NULL DEFAULT NOW()"
                ")"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_dataset_grants_user_dataset"
                " ON dataset_grants (user_id, dataset_id)"
            )
        )
        logger.info("dataset_grants table ensured")

        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS permission_audit_logs ("
                "    id              SERIAL PRIMARY KEY,"
                "    dataset_id      VARCHAR(255) NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,"
                "    actor_id        VARCHAR(255) NOT NULL,"
                "    target_user_id  VARCHAR(255) NOT NULL,"
                "    action          VARCHAR(50) NOT NULL,"
                "    metadata        JSONB NOT NULL DEFAULT '{}',"
                "    created_at      TIMESTAMP NOT NULL DEFAULT NOW()"
                ")"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_perm_audit_dataset_created"
                " ON permission_audit_logs (dataset_id, created_at)"
            )
        )
        logger.info("permission_audit_logs table ensured")

        await conn.execute(text("DROP TABLE IF EXISTS annotation_collaborators"))
        await conn.execute(text("DROP TABLE IF EXISTS dataset_permissions"))

        await conn.execute(
            text(
                "ALTER TABLE chat_messages "
                "ADD COLUMN IF NOT EXISTS variant_group_id VARCHAR(36)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE chat_messages "
                "ADD COLUMN IF NOT EXISTS is_active_variant BOOLEAN NOT NULL DEFAULT TRUE"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE chat_conversations "
                "ADD COLUMN IF NOT EXISTS parent_conversation_id VARCHAR(255) "
                "REFERENCES chat_conversations(conversation_id) ON DELETE SET NULL"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE chat_conversations "
                "ADD COLUMN IF NOT EXISTS branch_source_message_count INTEGER"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_chat_conversations_parent_conversation "
                "ON chat_conversations (parent_conversation_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_chat_messages_variant_group "
                "ON chat_messages (variant_group_id)"
            )
        )
        logger.info("chat conversation branch column and chat_messages variant columns ensured")

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

                import hashlib
                import secrets
                import uuid

                password_helper = PasswordHelper()
                default_password = os.getenv("DEFAULT_ADMIN_PASSWORD")
                if not default_password:
                    default_password = secrets.token_urlsafe(16)
                    logger.critical(
                        f"\n{'=' * 60}\n"
                        f"ADMIN PASSWORD (auto-generated, shown once):\n"
                        f"  Username : admin\n"
                        f"  Password : {default_password}\n"
                        f"Save this now — it will not be shown again.\n"
                        f"Set DEFAULT_ADMIN_PASSWORD env var to use a fixed password.\n"
                        f"{'=' * 60}"
                    )

                hashed_password = password_helper.hash(default_password)
                password_sha256 = hashlib.sha256(default_password.encode()).hexdigest()

                admin_user = User(
                    id=uuid.uuid4(),
                    email="admin",
                    hashed_password=hashed_password,
                    password_sha256=password_sha256,
                    is_active=True,
                    is_superuser=True,
                    is_verified=True,
                    role="admin",
                    nickname="Admin",
                )

                session.add(admin_user)
                await session.commit()
                logger.warning(
                    "Default admin user created (username: admin). Change the password after first login."
                )
            else:
                logger.info(
                    f"Found {user_count} existing user(s), skipping default admin creation"
                )
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
