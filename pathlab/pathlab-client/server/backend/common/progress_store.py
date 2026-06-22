"""
Redis-backed Training Progress Store

Trainers (AI Service) write progress to Redis keys.
Gateway SSE reads these keys directly — no HTTP call, no DB lock.

Keys: pathlab:progress:{task_id} = integer string (e.g. "75")
TTL: 24h auto-expiry (stale keys self-clean after crash/restart).
Cleanup: key deleted when task completes/fails.

Both AI Service and Gateway import this module (lives in backend.common).
"""

import logging
from importlib import import_module

_redis_client = import_module("backend.common.redis_client")
get_redis = _redis_client.get_redis
make_key = _redis_client.make_key

logger = logging.getLogger("progress_store")

PROGRESS_TTL = 86400  # 24 hours


async def set_progress(task_id: str, progress: int) -> None:
    try:
        r = get_redis()
        await r.set(make_key("progress", task_id), str(progress), ex=PROGRESS_TTL)
    except Exception as e:
        logger.warning(f"Failed to write progress to Redis (task={task_id}): {e}")


async def get_progress(task_id: str) -> int | None:
    try:
        r = get_redis()
        val = await r.get(make_key("progress", task_id))
        return int(val) if val is not None else None
    except Exception:
        return None


async def get_all_progress() -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        r = get_redis()
        prefix = make_key("progress", "")
        async for key in r.scan_iter(match=prefix + "*", count=100):
            task_id = key[len(prefix) :]
            val = await r.get(key)
            if val is not None:
                try:
                    result[task_id] = int(val)
                except ValueError:
                    pass
    except Exception:
        pass
    return result


async def clear_progress(task_id: str) -> None:
    try:
        r = get_redis()
        await r.delete(make_key("progress", task_id))
    except Exception:
        pass


async def set_task_owner(task_id: str, user_id: str) -> None:
    try:
        r = get_redis()
        await r.set(make_key("task_owner", task_id), user_id, ex=PROGRESS_TTL)
    except Exception as e:
        logger.warning(f"Failed to write task owner to Redis (task={task_id}): {e}")


async def get_task_owner(task_id: str) -> str | None:
    try:
        r = get_redis()
        val = await r.get(make_key("task_owner", task_id))
        return val.decode() if isinstance(val, bytes) else val
    except Exception:
        return None


async def cleanup_all_progress() -> int:
    count = 0
    try:
        r = get_redis()
        prefix = make_key("progress", "")
        keys = []
        async for key in r.scan_iter(match=prefix + "*", count=100):
            keys.append(key)
        if keys:
            count = await r.delete(*keys)
    except Exception:
        pass
    if count > 0:
        logger.info(f"Cleaned up {count} stale progress key(s) from Redis")
    return count
