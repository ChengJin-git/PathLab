from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from typing import Protocol, TypeAlias, cast

class RedisClientModule(Protocol):
    def get_redis(self) -> object: ...

    def make_key(self, *parts: str) -> str: ...


_redis_client = cast(RedisClientModule, cast(object, import_module("backend.common.redis_client")))
get_redis = _redis_client.get_redis
make_key = _redis_client.make_key

TASK_QUEUE_KEY = make_key("task_worker", "queue")
TASK_PROCESSING_KEY = make_key("task_worker", "processing")
TASK_DLQ_KEY = make_key("task_worker", "dlq")
TASK_PROCESSING_TIMESTAMPS_KEY = make_key("task_worker", "processing_ts")
TASK_ATTEMPTS_KEY = make_key("task_worker", "attempts")
TASK_RETRY_MAX = 3
TASK_CANCELLATION_TTL_SECONDS = 300
JOB_LOCK_TTL_SECONDS = 300
CANCEL_CHANNEL = make_key("task_worker", "cancel")
HEARTBEAT_KEY = make_key("task_worker", "heartbeat")
HEARTBEAT_TTL_SECONDS = 15
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


JsonValue: TypeAlias = (
    "str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]"
)
JsonPayload: TypeAlias = dict[str, JsonValue]


class TaskDispatchRedis(Protocol):
    async def lpush(self, key: str, value: str) -> object: ...

    async def brpop(self, key: str, timeout: float = 0.0) -> object: ...

    async def publish(self, channel: str, message: str) -> object: ...

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> object: ...

    async def exists(self, key: str) -> object: ...

    async def delete(self, *keys: str) -> object: ...

    async def lrem(self, key: str, count: int, value: str) -> object: ...

    async def rpush(self, key: str, value: str) -> object: ...

    async def lpop(self, key: str) -> object: ...

    async def llen(self, key: str) -> object: ...

    async def hset(self, key: str, field: str, value: str) -> object: ...

    async def hdel(self, key: str, *fields: str) -> object: ...

    async def hincrby(self, key: str, field: str, increment: int = 1) -> object: ...

    async def sadd(self, key: str, member: str) -> object: ...

    async def srem(self, key: str, member: str) -> object: ...


class BlmoveRedis(TaskDispatchRedis, Protocol):
    async def blmove(
        self,
        source: str,
        destination: str,
        *,
        timeout: float = 0.0,
        src: str = "RIGHT",
        dest: str = "LEFT",
    ) -> str | bytes | None: ...


class BrpoplpushRedis(TaskDispatchRedis, Protocol):
    async def brpoplpush(
        self,
        source: str,
        destination: str,
        *,
        timeout: float = 0.0,
    ) -> str | bytes | None: ...


def _default_redis() -> TaskDispatchRedis:
    return cast(TaskDispatchRedis, get_redis())


def _coerce_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"TaskDescriptor {field_name} must be an integer")
    return int(value)


def _coerce_redis_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str, bytes)):
        raise ValueError("Redis integer response must be int-compatible")
    return int(value)


def _validate_key_suffix(value: str, field_name: str) -> str:
    if not _ID_PATTERN.fullmatch(value):
        raise ValueError(
            f"TaskDescriptor {field_name} must match [A-Za-z0-9_-] and be 1-128 characters"
        )
    return value


@dataclass(frozen=True)
class TaskDescriptor:
    schema_version: int
    job_id: str
    job_kind: str
    handler: str
    payload: JsonPayload
    created_at: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "job_id": self.job_id,
                "job_kind": self.job_kind,
                "handler": self.handler,
                "payload": self.payload,
                "created_at": self.created_at,
            }
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> "TaskDescriptor":
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        parsed = cast(object, json.loads(raw))
        if not isinstance(parsed, Mapping):
            raise ValueError("TaskDescriptor JSON must be an object")
        data = cast(Mapping[str, object], parsed)
        payload = data["payload"]
        if not isinstance(payload, dict):
            raise ValueError("TaskDescriptor payload must be a JSON object")
        return cls(
            schema_version=_coerce_int(data["schema_version"], "schema_version"),
            job_id=_validate_key_suffix(str(data["job_id"]), "job_id"),
            job_kind=str(data["job_kind"]),
            handler=str(data["handler"]),
            payload=cast(JsonPayload, payload),
            created_at=str(data["created_at"]),
        )


def build_task_descriptor(
    job_id: str,
    job_kind: str,
    handler: str,
    payload: JsonPayload,
) -> TaskDescriptor:
    job_id = _validate_key_suffix(job_id, "job_id")
    try:
        _ = json.dumps(payload)
    except TypeError:
        raise TypeError("TaskDescriptor payload must be JSON serializable")

    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return TaskDescriptor(
        schema_version=1,
        job_id=job_id,
        job_kind=job_kind,
        handler=handler,
        payload=payload,
        created_at=created_at,
    )


async def enqueue_task_descriptor(
    descriptor: TaskDescriptor,
    redis: TaskDispatchRedis | None = None,
) -> None:
    r = redis if redis is not None else _default_redis()
    _ = await r.lpush(TASK_QUEUE_KEY, descriptor.to_json())


async def set_worker_heartbeat(
    redis: TaskDispatchRedis | None = None,
) -> None:
    r = redis if redis is not None else _default_redis()
    _ = await r.set(HEARTBEAT_KEY, "1", ex=HEARTBEAT_TTL_SECONDS)


async def is_worker_healthy(
    redis: TaskDispatchRedis | None = None,
) -> bool:
    r = redis if redis is not None else _default_redis()
    return bool(await r.exists(HEARTBEAT_KEY))


def _cancellation_key(task_id: str) -> str:
    task_id = _validate_key_suffix(task_id, "task_id")
    return make_key("task_worker", "cancel", task_id)


def _job_lock_key(job_id: str) -> str:
    job_id = _validate_key_suffix(job_id, "job_id")
    return make_key("task_worker", "lock", job_id)


async def quarantine_task_descriptor(
    raw_descriptor: str,
    descriptor: TaskDescriptor | None = None,
    error: object = None,
    redis: TaskDispatchRedis | None = None,
) -> None:
    _ = error
    r = redis if redis is not None else _default_redis()
    _ = await r.lrem(TASK_PROCESSING_KEY, 0, raw_descriptor)
    if descriptor is not None:
        _ = await r.hdel(TASK_PROCESSING_TIMESTAMPS_KEY, descriptor.job_id)
    _ = await r.rpush(TASK_DLQ_KEY, raw_descriptor)


async def claim_task_descriptor(
    timeout: float = 0.0,
    redis: TaskDispatchRedis | None = None,
) -> tuple[TaskDescriptor, str] | None:
    r = redis if redis is not None else _default_redis()
    raw: str | bytes | None = None
    if hasattr(r, "blmove"):
        raw = await cast(BlmoveRedis, r).blmove(
            TASK_QUEUE_KEY,
            TASK_PROCESSING_KEY,
            timeout=timeout,
            src="RIGHT",
            dest="LEFT",
        )
    elif hasattr(r, "brpoplpush"):
        raw = await cast(BrpoplpushRedis, r).brpoplpush(
            TASK_QUEUE_KEY,
            TASK_PROCESSING_KEY,
            timeout=timeout,
        )
    else:
        result = await r.brpop(TASK_QUEUE_KEY, timeout=timeout)
        if result is None:
            return None
        if not isinstance(result, (list, tuple)):
            raise ValueError("Unexpected Redis BRPOP response for task descriptor")
        response = cast(Sequence[object], result)
        if len(response) != 2:
            raise ValueError("Unexpected Redis BRPOP response for task descriptor")
        raw_candidate = response[1]
        if not isinstance(raw_candidate, (str, bytes)):
            raise ValueError("Unexpected Redis task descriptor payload type")
        raw = raw_candidate
        _ = await r.lpush(TASK_PROCESSING_KEY, raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    if raw is None:
        return None
    raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    try:
        descriptor = TaskDescriptor.from_json(raw_str)
    except Exception:
        await quarantine_task_descriptor(raw_str, redis=r)
        raise
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _ = await r.hset(TASK_PROCESSING_TIMESTAMPS_KEY, descriptor.job_id, now)
    return (descriptor, raw_str)


async def dequeue_task_descriptor(
    timeout: float = 0.0,
    redis: TaskDispatchRedis | None = None,
) -> TaskDescriptor | None:
    claimed = await claim_task_descriptor(timeout=timeout, redis=redis)
    if claimed is None:
        return None
    descriptor, _raw = claimed
    return descriptor


async def ack_task_descriptor(
    raw_descriptor: str,
    descriptor: TaskDescriptor | None = None,
    redis: TaskDispatchRedis | None = None,
) -> None:
    r = redis if redis is not None else _default_redis()
    _ = await r.lrem(TASK_PROCESSING_KEY, 0, raw_descriptor)
    if descriptor is not None:
        _ = await r.hdel(TASK_ATTEMPTS_KEY, descriptor.job_id)
        _ = await r.hdel(TASK_PROCESSING_TIMESTAMPS_KEY, descriptor.job_id)


reject_task_descriptor = quarantine_task_descriptor


async def fail_task_descriptor(
    raw_descriptor: str,
    descriptor: TaskDescriptor,
    error: object,
    redis: TaskDispatchRedis | None = None,
) -> None:
    _ = error
    r = redis if redis is not None else _default_redis()
    _ = await r.lrem(TASK_PROCESSING_KEY, 0, raw_descriptor)
    _ = await r.hdel(TASK_PROCESSING_TIMESTAMPS_KEY, descriptor.job_id)
    attempts = _coerce_redis_int(await r.hincrby(TASK_ATTEMPTS_KEY, descriptor.job_id, 1))
    if attempts < TASK_RETRY_MAX:
        _ = await r.rpush(TASK_QUEUE_KEY, raw_descriptor)
    else:
        _ = await r.rpush(TASK_DLQ_KEY, raw_descriptor)
        _ = await r.hdel(TASK_ATTEMPTS_KEY, descriptor.job_id)


async def rescue_processing_descriptors(
    redis: TaskDispatchRedis | None = None,
) -> int:
    r = redis if redis is not None else _default_redis()
    rescued = 0
    while True:
        raw = await r.lpop(TASK_PROCESSING_KEY)
        if raw is None:
            break
        raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        try:
            descriptor = TaskDescriptor.from_json(raw_str)
            _ = await r.hdel(TASK_PROCESSING_TIMESTAMPS_KEY, descriptor.job_id)
        except Exception:
            pass
        _ = await r.rpush(TASK_QUEUE_KEY, raw_str)
        rescued += 1
    return rescued


async def get_task_descriptor_queue_counts(
    redis: TaskDispatchRedis | None = None,
) -> dict[str, int]:
    r = redis if redis is not None else _default_redis()
    pending = _coerce_redis_int(await r.llen(TASK_QUEUE_KEY))
    processing = _coerce_redis_int(await r.llen(TASK_PROCESSING_KEY))
    dlq = _coerce_redis_int(await r.llen(TASK_DLQ_KEY))
    return {"pending": pending, "processing": processing, "dlq": dlq}


async def publish_task_cancellation(
    task_id: str,
    redis: TaskDispatchRedis | None = None,
) -> None:
    r = redis if redis is not None else _default_redis()
    _ = await r.set(_cancellation_key(task_id), "1", ex=TASK_CANCELLATION_TTL_SECONDS)
    _ = await r.publish(CANCEL_CHANNEL, json.dumps({"task_id": task_id}))


async def is_task_cancelled(
    task_id: str,
    redis: TaskDispatchRedis | None = None,
) -> bool:
    r = redis if redis is not None else _default_redis()
    return bool(await r.exists(_cancellation_key(task_id)))


async def acquire_job_lock(
    job_id: str,
    redis: TaskDispatchRedis | None = None,
) -> bool:
    r = redis if redis is not None else _default_redis()
    result = await r.set(_job_lock_key(job_id), "1", ex=JOB_LOCK_TTL_SECONDS, nx=True)
    return bool(result)


async def release_job_lock(
    job_id: str,
    redis: TaskDispatchRedis | None = None,
) -> None:
    r = redis if redis is not None else _default_redis()
    _ = await r.delete(_job_lock_key(job_id))
