"""
Redis Client for PathLab.

Uses loop-local async Redis pools/clients so long-running services and worker
threads do not accidentally reuse a client that was created on a different
event loop. This is especially important for training code that may bridge
sync code to async helpers.
"""

import asyncio
import os
import logging
import threading
import weakref
from importlib import import_module

import redis.asyncio as aioredis

Config = import_module("backend.common.config").Config

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", Config.REDIS_URL_DEFAULT)
_registry_lock = threading.RLock()
_pools_by_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, aioredis.ConnectionPool]" = weakref.WeakKeyDictionary()
_clients_by_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, aioredis.Redis]" = weakref.WeakKeyDictionary()
KEY_PREFIX = "pathlab:"


def _get_running_loop() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_running_loop()
    except RuntimeError as exc:
        raise RuntimeError(
            "get_redis() must be called from within a running event loop"
        ) from exc


def _get_pool_for_loop(loop: asyncio.AbstractEventLoop) -> aioredis.ConnectionPool:
    with _registry_lock:
        pool = _pools_by_loop.get(loop)
        if pool is None:
            pool = aioredis.ConnectionPool.from_url(
                REDIS_URL,
                max_connections=20,
                decode_responses=True,
            )
            _pools_by_loop[loop] = pool
        return pool


def get_redis() -> aioredis.Redis:
    loop = _get_running_loop()
    with _registry_lock:
        client = _clients_by_loop.get(loop)
        if client is None:
            client = aioredis.Redis(connection_pool=_get_pool_for_loop(loop))
            _clients_by_loop[loop] = client
        return client


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
    """Close Redis resources for the current event loop."""
    loop = _get_running_loop()
    with _registry_lock:
        client = _clients_by_loop.pop(loop, None)
        pool = _pools_by_loop.pop(loop, None)

    if client is not None:
        try:
            await client.aclose()
        except Exception as e:
            logger.debug(f"[Redis] Failed closing client for current loop: {e}")

    if pool is not None:
        try:
            await pool.aclose()
        except Exception as e:
            logger.debug(f"[Redis] Failed closing pool for current loop: {e}")

    logger.info("[Redis] Connections closed for current event loop")


def make_key(*parts: str) -> str:
    """Build a namespaced Redis key. e.g. make_key('progress', task_id) -> 'pathlab:progress:{task_id}'"""
    return KEY_PREFIX + ":".join(parts)
