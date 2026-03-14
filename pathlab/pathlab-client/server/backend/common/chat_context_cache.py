"""
Redis-backed chat user-context cache using version-counter invalidation.

Redis keys:
  pathlab:chat_ctx_ver:{user_id}     → integer version counter (INCR on any mutation)
  pathlab:chat_ctx:{user_id}:{ver}   → JSON dict (format_user_data_context kwargs
                                       minus current_datetime)
  pathlab:chat_snapshot:{task_id}    → latest training-log snapshot string

Call invalidate_chat_context(user_id) on: WSI/dataset/model/task mutations,
permission grant/revoke. Chat handler rebuilds on the next cache miss.
"""

import json
import logging
from typing import Optional

from backend.common.redis_client import get_redis, make_key

logger = logging.getLogger(__name__)

CHAT_CTX_TTL = 3600
VER_TTL = 7200
SNAPSHOT_TTL = 86400


async def get_cached_context_kwargs(user_id: str) -> Optional[dict]:
    """Return cached kwargs dict (everything except current_datetime), or None."""
    try:
        r = get_redis()
        ver = await r.get(make_key("chat_ctx_ver", user_id))
        if not ver:
            return None
        raw = await r.get(make_key("chat_ctx", user_id, ver))
        if not raw:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.warning("[ChatCtxCache] read error uid=%s: %s", user_id, exc)
        return None


async def set_cached_context_kwargs(user_id: str, kwargs: dict) -> None:
    try:
        r = get_redis()
        ver_key = make_key("chat_ctx_ver", user_id)
        ver = await r.get(ver_key)
        if not ver:
            ver = "1"
            await r.set(ver_key, ver, ex=VER_TTL)
        await r.set(
            make_key("chat_ctx", user_id, ver),
            json.dumps(kwargs, ensure_ascii=False),
            ex=CHAT_CTX_TTL,
        )
    except Exception as exc:
        logger.warning("[ChatCtxCache] write error uid=%s: %s", user_id, exc)


async def invalidate_chat_context(user_id: str) -> None:
    if not user_id:
        return
    try:
        r = get_redis()
        ver_key = make_key("chat_ctx_ver", user_id)
        await r.incr(ver_key)
        await r.expire(ver_key, VER_TTL)
    except Exception as exc:
        logger.warning("[ChatCtxCache] invalidate error uid=%s: %s", user_id, exc)


async def get_training_snapshot(task_id: str) -> Optional[str]:
    try:
        r = get_redis()
        return await r.get(make_key("chat_snapshot", task_id))
    except Exception:
        return None


async def set_training_snapshot(task_id: str, snapshot: str) -> None:
    if not snapshot:
        return
    try:
        r = get_redis()
        await r.set(make_key("chat_snapshot", task_id), snapshot, ex=SNAPSHOT_TTL)
    except Exception:
        pass


async def clear_training_snapshot(task_id: str) -> None:
    try:
        r = get_redis()
        await r.delete(make_key("chat_snapshot", task_id))
    except Exception:
        pass
