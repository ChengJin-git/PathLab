import json
from importlib import import_module
from typing import Any

import redis.asyncio as aioredis

_redis_client = import_module("backend.common.redis_client")
get_redis = _redis_client.get_redis
make_key = _redis_client.make_key
REDIS_URL = _redis_client.REDIS_URL

PRESENCE_CHANNEL_PREFIX = "presence_ch"


async def publish_presence(dataset_id: str, payload: dict[str, Any]) -> None:
    await get_redis().publish(
        make_key(PRESENCE_CHANNEL_PREFIX, dataset_id), json.dumps(payload)
    )


async def subscribe_presence_iter(dataset_id: str):
    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(make_key(PRESENCE_CHANNEL_PREFIX, dataset_id))
    try:
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                yield msg["data"]
    finally:
        await pubsub.unsubscribe()
        await client.aclose()
