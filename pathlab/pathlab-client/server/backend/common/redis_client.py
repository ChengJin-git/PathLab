"""
Redis Client for PathLab

Shared async Redis connection pool for all services.
Used by: progress_store, analysis_state, training_logs, storage caches.
Override via REDIS_URL environment variable.
"""
import os
import logging
from typing import Optional

import redis.asyncio as aioredis
from backend.common.config import Config

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", Config.REDIS_URL_DEFAULT)
_pool: Optional[aioredis.ConnectionPool] = None
_client: Optional[aioredis.Redis] = None
KEY_PREFIX = "pathlab:"


def _get_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            REDIS_URL,
            max_connections=20,
            decode_responses=True,
        )
    return _pool


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.Redis(connection_pool=_get_pool())
    return _client


async def init_redis() -> None:
    """Initialize Redis connection and verify connectivity. Call on startup."""
    r = get_redis()
    try:
        pong = await r.ping()
        if pong:
            logger.info(f"[Redis] Connected successfully to {REDIS_URL}")
        else:
            logger.error("[Redis] Connection failed: no PONG response")
    except Exception as e:
        logger.error(f"[Redis] Connection failed: {e}")
        raise


async def close_redis() -> None:
    """Close Redis connections. Call on shutdown."""
    global _client, _pool
    if _client is not None:
        await _client.aclose()
        _client = None
    if _pool is not None:
        await _pool.aclose()
        _pool = None
    logger.info("[Redis] Connections closed")


def make_key(*parts: str) -> str:
    """Build a namespaced Redis key. e.g. make_key('progress', task_id) -> 'pathlab:progress:{task_id}'"""
    return KEY_PREFIX + ":".join(parts)
