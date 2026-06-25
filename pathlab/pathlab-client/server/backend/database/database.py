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
from collections.abc import AsyncGenerator, Iterable, Mapping
from datetime import datetime
from sqlalchemy.exc import DBAPIError, InterfaceError, SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy import text
from backend.common.config import Config
from .models import Base

logger = logging.getLogger(__name__)


def _plan_user_identity_cleanup(rows: Iterable[Mapping[str, object]]) -> dict[str, str]:
    """Plan deterministic username repairs for blank/duplicate identities.

    Input rows must provide id, username, created_at. The first row in
    created_at NULLS FIRST + id order keeps its username in duplicate groups;
    later rows are renamed with deterministic suffixes derived from their UUID.
    """

    def _id_hex(user_id: object) -> str:
        return str(user_id).replace("-", "")

    def _username(row: Mapping[str, object]) -> str:
        raw_username = row.get("username")
        if raw_username is None:
            return ""
        return str(raw_username).strip()

    def _sort_key(row: Mapping[str, object]) -> tuple[bool, datetime, str]:
        created_at = row.get("created_at")
        sortable_created_at = created_at if isinstance(created_at, datetime) else datetime.min
        return (created_at is not None, sortable_created_at, str(row["id"]))

    sorted_rows = sorted(
        rows,
        key=_sort_key,
    )

    reserved_usernames = {
        username
        for row in sorted_rows
        if (username := _username(row)) != ""
    }
    seen_usernames: set[str] = set()
    updates: dict[str, str] = {}

    for row in sorted_rows:
        username = _username(row)
        user_id = row["id"]
        user_id_str = str(user_id)
        user_id_hex = _id_hex(user_id)

        if username:
            if username not in seen_usernames:
                seen_usernames.add(username)
                continue
            base = username
            suffix_len = 8
            while True:
                candidate = f"{base}_{user_id_hex[:suffix_len]}"
                if candidate not in reserved_usernames:
                    reserved_usernames.add(candidate)
                    updates[user_id_str] = candidate
                    break
                suffix_len += 4
            continue

        base = "user"
        suffix_len = 12
        while True:
            candidate = f"{base}_{user_id_hex[:suffix_len]}"
            if candidate not in reserved_usernames:
                reserved_usernames.add(candidate)
                updates[user_id_str] = candidate
                break
            suffix_len += 4

    return updates


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
        await conn.execute(text("SELECT pg_advisory_lock(2026040801)"))
        try:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("All tables created/verified successfully")
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_wsi_dataset_case "
                    "ON wsi_slides(dataset_id, case_id)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_wsi_dataset_type_case "
                    "ON wsi_slides(dataset_id, data_type, case_id)"
                )
            )
            logger.info("WSI case pagination indexes ensured")
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
                    "CREATE TABLE IF NOT EXISTS wsi_slide_user_splits ("
                    "    id SERIAL PRIMARY KEY,"
                    "    wsi_id VARCHAR(255) NOT NULL REFERENCES wsi_slides(wsi_id) ON DELETE CASCADE,"
                    "    user_id VARCHAR(255) NOT NULL,"
                    "    split VARCHAR(20) NOT NULL,"
                    "    created_at TIMESTAMP NOT NULL DEFAULT NOW(),"
                    "    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),"
                    "    CONSTRAINT uq_wsi_slide_user_splits_wsi_user UNIQUE (wsi_id, user_id)"
                    ")"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_wsi_slide_user_splits_user "
                    "ON wsi_slide_user_splits(user_id)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_wsi_slide_user_splits_wsi "
                    "ON wsi_slide_user_splits(wsi_id)"
                )
            )
            logger.info(
                "Skipping wsi_slides.data_type startup DDL; migration handled separately"
            )
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
                    "username VARCHAR(255)"
                )
            )
            await conn.execute(
                text(
                    "UPDATE users SET username = email "
                    "WHERE username IS NULL OR LENGTH(TRIM(username)) = 0"
                )
            )
            await conn.execute(
                text(
                    "UPDATE users SET email = registration_email "
                    "WHERE registration_email IS NOT NULL AND "
                    "(email IS NULL OR email = username)"
                )
            )
            identity_rows = [
                dict(row)
                for row in (
                    await conn.execute(
                        text(
                            "SELECT id, username, created_at FROM users "
                            "ORDER BY created_at NULLS FIRST, id"
                        )
                    )
                )
                .mappings()
                .all()
            ]
            identity_updates = _plan_user_identity_cleanup(identity_rows)
            for user_id, username in identity_updates.items():
                await conn.execute(
                    text(
                        "UPDATE users SET username = :username "
                        "WHERE id = :user_id"
                    ),
                    {"username": username, "user_id": user_id},
                )
            await conn.execute(text("ALTER TABLE users ALTER COLUMN email DROP NOT NULL"))
            await conn.execute(
                text(
                    """
                    DO $$
                    DECLARE c RECORD;
                    BEGIN
                        FOR c IN
                            SELECT con.conname
                            FROM pg_constraint con
                            JOIN pg_class rel ON rel.oid = con.conrelid
                            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                            JOIN unnest(con.conkey) AS colnum(attnum) ON TRUE
                            JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = colnum.attnum
                            WHERE rel.relname = 'users'
                              AND nsp.nspname = current_schema()
                              AND con.contype = 'u'
                              AND att.attname = 'email'
                        LOOP
                            EXECUTE format('ALTER TABLE %I.users DROP CONSTRAINT IF EXISTS %I', current_schema(), c.conname);
                        END LOOP;
                    END $$;
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    DO $$
                    DECLARE idx RECORD;
                    BEGIN
                        FOR idx IN
                            SELECT i.indexname
                            FROM pg_indexes i
                            JOIN pg_class rel ON rel.relname = i.tablename
                            JOIN pg_namespace nsp ON nsp.nspname = i.schemaname
                            JOIN pg_class ic ON ic.relname = i.indexname AND ic.relnamespace = nsp.oid
                            JOIN pg_index pi ON pi.indexrelid = ic.oid
                            JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = ANY(pi.indkey)
                            WHERE i.schemaname = current_schema()
                              AND i.tablename = 'users'
                              AND pi.indisunique = TRUE
                              AND att.attname = 'email'
                        LOOP
                            EXECUTE format('DROP INDEX IF EXISTS %I.%I', current_schema(), idx.indexname);
                        END LOOP;
                    END $$;
                    """
                )
            )
            await conn.execute(
                text("ALTER TABLE users ALTER COLUMN username SET NOT NULL")
            )
            await conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username "
                    "ON users (username)"
                )
            )
            logger.info("users.username column ensured and account identity cleanup completed")

            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                    "first_activated_at TIMESTAMP DEFAULT NULL"
                )
            )
            await conn.execute(
                text(
                    "UPDATE users SET first_activated_at = NOW() "
                    "WHERE first_activated_at IS NULL AND is_active = TRUE"
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
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(2026040801)"))

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
        logger.info(
            "chat conversation branch column and chat_messages variant columns ensured"
        )

        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "session_nonces TEXT DEFAULT NULL"
            )
        )
        # Migrate existing single nonce to JSON array format (runs once per row, idempotent)
        await conn.execute(
            text(
                "UPDATE users SET session_nonces = json_build_array(session_nonce)::text "
                "WHERE session_nonce IS NOT NULL AND session_nonces IS NULL"
            )
        )
        logger.info(
            "users.session_nonces column ensured and backfilled from session_nonce"
        )

        await conn.execute(
            text(
                "ALTER TABLE auto_research_sessions "
                "ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(255)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE auto_research_sessions "
                "ADD COLUMN IF NOT EXISTS persistence_dir TEXT"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE auto_research_sessions "
                "ADD COLUMN IF NOT EXISTS workspace_path TEXT"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE auto_research_sessions "
                "ADD COLUMN IF NOT EXISTS resume_available BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE auto_research_sessions "
                "ADD COLUMN IF NOT EXISTS event_source_version VARCHAR(50) NOT NULL DEFAULT 'gateway-v1'"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE auto_research_sessions "
                "ADD COLUMN IF NOT EXISTS recovery_metadata JSONB"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_auto_research_sessions_conversation_id "
                "ON auto_research_sessions (conversation_id)"
            )
        )
        await conn.execute(
            text(
                "DELETE FROM auto_research_events newer "
                "USING auto_research_events older "
                "WHERE newer.session_id = older.session_id "
                "AND newer.sequence = older.sequence "
                "AND newer.id > older.id"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_auto_research_events_session_seq "
                "ON auto_research_events (session_id, sequence)"
            )
        )
        logger.info("auto_research AutoResearch recovery columns and event index ensured")

    await _enforce_data_group_task_taxonomy_constraint()
    await _create_default_admin()


async def _enforce_data_group_task_taxonomy_constraint() -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'chk_data_groups_task_type_canonical'
                          AND conrelid = 'data_groups'::regclass
                    ) THEN
                        ALTER TABLE data_groups
                        ADD CONSTRAINT chk_data_groups_task_type_canonical
                        CHECK (task_type IN (
                            'wsi_classification',
                            'patch_classification',
                            'wsi_survival',
                            'patch_segmentation'
                        ));
                    END IF;
                END $$;
                """
            )
        )
    logger.info("data_groups.task_type canonical constraint ensured")


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
                    username="admin",
                    email=None,
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
