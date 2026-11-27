"""PostgreSQL sessions and current-schema initialization.

Existing deployments must already match the recorded current schema. Startup never
rewrites historical data or runs one-time upgrade scripts.
"""

import os
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
import anyio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InterfaceError, SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool
from backend.common.config import Config
from .models import Base

logger = logging.getLogger(__name__)


def get_database_url():
    return os.environ.get("DATABASE_URL") or Config.DATABASE_URL_DEFAULT


DATABASE_URL = get_database_url()
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=20,
    max_overflow=10,
    pool_timeout=10,
    pool_pre_ping=True,
    pool_recycle=3600,
)
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def _invalidate_session_connection(session):
    try:
        with anyio.CancelScope(shield=True):
            await session.invalidate()
    except Exception:
        logger.debug("Unable to invalidate database connection", exc_info=True)


async def _rollback_safely(session, *, context):
    try:
        with anyio.CancelScope(shield=True):
            await session.rollback()
    except (InterfaceError, DBAPIError) as exc:
        logger.warning("Database rollback unavailable (%s): %s", context, exc)
        await _invalidate_session_connection(session)
    except SQLAlchemyError:
        logger.exception("Database rollback failed (%s)", context)


async def _close_safely(session, *, context):
    try:
        with anyio.CancelScope(shield=True):
            await session.close()
    except SQLAlchemyError:
        logger.exception("Database session close failed (%s)", context)


@asynccontextmanager
async def safe_session() -> AsyncGenerator[AsyncSession, None]:
    session = async_session()
    try:
        yield session
    except BaseException:
        await _rollback_safely(session, context="safe_session exception")
        raise
    finally:
        await _close_safely(session, context="safe_session")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with safe_session() as session:
        try:
            yield session
            with anyio.CancelScope(shield=True):
                await session.commit()
        except (InterfaceError, DBAPIError):
            await _invalidate_session_connection(session)
            raise


@asynccontextmanager
async def read_session() -> AsyncGenerator[AsyncSession, None]:
    """Complete one bounded SSE read before propagating a client disconnect.

    Starlette's AnyIO cancellation is level-triggered: cancelling an in-flight
    asyncpg query also cancels SQLAlchemy's connection invalidation. Shield the
    short read and its cleanup, bounded by PostgreSQL's statement timeout. Callers
    must release this context before yielding a stream event or waiting for I/O.
    """
    with anyio.CancelScope(shield=True):
        async with safe_session() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await session.execute(text("SET LOCAL statement_timeout = '5s'"))
            yield session
    await anyio.lowlevel.checkpoint_if_cancelled()


async def init_db():
    from .current_schema import initialize

    async with engine.begin() as connection:
        await connection.execute(text("SELECT pg_advisory_xact_lock(2026040801)"))
        await initialize(connection)
    await _create_default_admin()


async def _create_default_admin():
    from backend.auth.models import User
    from fastapi_users.password import PasswordHelper
    from sqlalchemy import select, func
    import hashlib
    import secrets
    import uuid

    async with async_session() as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(2026110110)"))
        if await session.scalar(select(func.count(User.id))):
            return
        password = os.getenv("DEFAULT_ADMIN_PASSWORD") or secrets.token_urlsafe(24)
        user = User(
            id=uuid.uuid4(),
            username="admin",
            email=None,
            hashed_password=PasswordHelper().hash(password),
            password_sha256=hashlib.sha256(password.encode()).hexdigest(),
            is_active=True,
            is_superuser=True,
            is_verified=True,
            role="admin",
            nickname="Admin",
        )
        session.add(user)
        await session.commit()
        logger.warning(
            "Created initial administrator. Use the configured DEFAULT_ADMIN_PASSWORD or the account recovery procedure."
        )
        if not os.getenv("DEFAULT_ADMIN_PASSWORD"):
            logger.warning("Initial administrator password (shown once): %s", password)


async def drop_all_tables():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


async def close_db():
    await engine.dispose()
    logger.info("Database connections closed")
