"""
Shared resource revision counters and task log snapshots.

Redis keys:
  pathlab:chat_ctx_ver:{user_id}     → integer version counter (INCR on any mutation)
  pathlab:chat_snapshot:{task_id}    → latest training-log snapshot string

Call invalidate_chat_context(user_id) on WSI/dataset/model/task mutations and
permission changes. Request-time context is queried within the effective scope.
"""

import logging
import asyncio
import hashlib
import json
from typing import Any, Dict, List, Optional

from backend.common.redis_client import get_redis, make_key

logger = logging.getLogger(__name__)

VER_TTL = 7200
SNAPSHOT_TTL = 86400
ADMIN_SCOPE = "__admin_all__"


async def scoped_context_key(identity: dict) -> str | None:
    """Include mutation revision; caller includes freshly resolved access IDs."""
    try:
        revision = await asyncio.wait_for(
            get_redis().get(make_key("chat_ctx_ver", ADMIN_SCOPE)), 0.15
        )
        identity = {**identity, "revision": str(revision or "0")}
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        return make_key("workspace_context", digest)
    except Exception:
        return None


async def read_scoped_context(key: str | None) -> str | None:
    if key is None:
        return None
    try:
        value = await asyncio.wait_for(get_redis().get(key), 0.15)
        return value.decode() if isinstance(value, bytes) else value
    except Exception:
        return None


async def write_scoped_context(key: str | None, context: str) -> None:
    if key is None:
        return
    try:
        await asyncio.wait_for(get_redis().set(key, context, ex=20), 0.15)
    except Exception:
        pass


async def invalidate_chat_context(user_id: str) -> None:
    if not user_id:
        return
    await invalidate_all_user_chat_contexts([user_id])


async def invalidate_all_user_chat_contexts(user_ids: List[str]) -> None:
    if not user_ids:
        return
    try:
        # One round trip and a bounded post-commit wait, including visibility
        # changes affecting many users. Atomic revisions remain awaited on success.
        async with get_redis().pipeline(transaction=True) as pipe:
            for uid in dict.fromkeys([*user_ids, ADMIN_SCOPE]):
                ver_key = make_key("chat_ctx_ver", uid)
                pipe.incr(ver_key)
                pipe.expire(ver_key, VER_TTL)
            await asyncio.wait_for(pipe.execute(), timeout=0.5)
    except Exception as exc:
        logger.warning("[ChatCtxCache] batch invalidate error: %s", exc)


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
