import json

import pytest

from backend.common.task_dispatch import (
    TaskDescriptor,
    ack_task_descriptor,
    acquire_job_lock,
    build_task_descriptor,
    claim_task_descriptor,
    enqueue_task_descriptor,
    dequeue_task_descriptor,
    fail_task_descriptor,
    is_task_cancelled,
    publish_task_cancellation,
    rescue_processing_descriptors,
    release_job_lock,
    set_worker_heartbeat,
    is_worker_healthy,
    TASK_QUEUE_KEY,
    TASK_PROCESSING_KEY,
    TASK_DLQ_KEY,
    TASK_ATTEMPTS_KEY,
    TASK_PROCESSING_TIMESTAMPS_KEY,
    CANCEL_CHANNEL,
    HEARTBEAT_KEY,
    HEARTBEAT_TTL_SECONDS,
    TASK_RETRY_MAX,
    TASK_CANCELLATION_TTL_SECONDS,
    JOB_LOCK_TTL_SECONDS,
)


async def test_recovered_descriptor_can_reacquire_crashed_worker_lock():
    redis = FakeRedis()
    descriptor = build_task_descriptor("crashed", "training", "training.run", {})
    await enqueue_task_descriptor(descriptor, redis=redis)
    assert await claim_task_descriptor(redis=redis) is not None
    assert await acquire_job_lock("crashed", redis=redis)

    assert await rescue_processing_descriptors(redis=redis) == 1
    recovered, _ = await claim_task_descriptor(redis=redis)
    assert recovered.job_id == "crashed"
    assert await acquire_job_lock("crashed", redis=redis)


class FakeRedis:
    def __init__(self):
        self._lists = {}
        self._strings = {}
        self._pubs = []
        self._hashes = {}
        self._sets = {}

    async def lpush(self, key, value):
        self._lists.setdefault(key, []).append(value)

    async def brpop(self, key, timeout=0):
        lst = self._lists.get(key, [])
        if not lst:
            return None
        return (key, lst.pop(0))

    async def publish(self, channel, message):
        self._pubs.append((channel, message))

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self._strings:
            return False
        self._strings[key] = {"value": value, "ex": ex}
        return True

    async def exists(self, key):
        return 1 if key in self._strings else 0

    async def delete(self, *keys):
        count = 0
        for key in keys:
            if key in self._strings:
                del self._strings[key]
                count += 1
            if key in self._hashes:
                del self._hashes[key]
                count += 1
            if key in self._sets:
                del self._sets[key]
                count += 1
        return count

    async def lrem(self, key, count, value):
        lst = self._lists.get(key, [])
        if count == 0:
            before = len(lst)
            self._lists[key] = [v for v in lst if v != value]
            return before - len(self._lists[key])
        removed = 0
        new_lst = []
        if count > 0:
            for v in lst:
                if v == value and removed < count:
                    removed += 1
                else:
                    new_lst.append(v)
        else:
            for v in reversed(lst):
                if v == value and removed < -count:
                    removed += 1
                else:
                    new_lst.insert(0, v)
        self._lists[key] = new_lst
        return removed

    async def rpush(self, key, value):
        self._lists.setdefault(key, []).append(value)

    async def lpop(self, key):
        lst = self._lists.get(key, [])
        if not lst:
            return None
        return lst.pop(0)

    async def llen(self, key):
        return len(self._lists.get(key, []))

    async def hset(self, key, field, value):
        self._hashes.setdefault(key, {})[field] = value

    async def hdel(self, key, *fields):
        h = self._hashes.get(key, {})
        count = 0
        for f in fields:
            if f in h:
                del h[f]
                count += 1
        return count

    async def hincrby(self, key, field, increment=1):
        h = self._hashes.setdefault(key, {})
        h[field] = int(h.get(field, 0)) + increment
        return h[field]

    async def sadd(self, key, member):
        s = self._sets.setdefault(key, set())
        if member in s:
            return 0
        s.add(member)
        return 1

    async def srem(self, key, member):
        s = self._sets.get(key, set())
        if member in s:
            s.remove(member)
            return 1
        return 0


def test_task_descriptor_requires_json_payload():
    with pytest.raises(TypeError):
        build_task_descriptor(
            job_id="task_1",
            job_kind="training",
            handler="training.preflight",
            payload={"bad": object()},
        )


def test_task_descriptor_round_trip():
    descriptor = build_task_descriptor(
        job_id="task_1",
        job_kind="training",
        handler="training.preflight",
        payload={"task_id": "task_1", "wsi_ids": ["w1"]},
    )

    encoded = descriptor.to_json()
    decoded = TaskDescriptor.from_json(encoded)

    assert decoded.job_id == "task_1"
    assert decoded.handler == "training.preflight"
    assert decoded.payload["wsi_ids"] == ["w1"]


def test_build_task_descriptor_rejects_unsafe_job_id():
    with pytest.raises(ValueError, match="job_id"):
        build_task_descriptor(
            job_id="bad:key",
            job_kind="training",
            handler="training.preflight",
            payload={"task_id": "task_1"},
        )


def test_task_descriptor_from_json_rejects_oversized_job_id():
    raw = json.dumps(
        {
            "schema_version": 1,
            "job_id": "x" * 129,
            "job_kind": "training",
            "handler": "training.preflight",
            "payload": {"task_id": "task_1"},
            "created_at": "2026-01-01T00:00:00Z",
        }
    )

    with pytest.raises(ValueError, match="job_id"):
        TaskDescriptor.from_json(raw)


@pytest.mark.asyncio
async def test_enqueue_and_dequeue_task_descriptor():
    fake = FakeRedis()
    descriptor = build_task_descriptor(
        job_id="task_1",
        job_kind="training",
        handler="training.preflight",
        payload={"task_id": "task_1"},
    )
    await enqueue_task_descriptor(descriptor, redis=fake)
    assert len(fake._lists[TASK_QUEUE_KEY]) == 1

    decoded = await dequeue_task_descriptor(redis=fake)
    assert decoded is not None
    assert decoded.job_id == "task_1"
    assert decoded.handler == "training.preflight"


@pytest.mark.asyncio
async def test_dequeue_empty_queue():
    fake = FakeRedis()
    result = await dequeue_task_descriptor(redis=fake)
    assert result is None


@pytest.mark.asyncio
async def test_publish_task_cancellation():
    fake = FakeRedis()
    await publish_task_cancellation("cancel_me", redis=fake)
    assert len(fake._pubs) == 1
    channel, message = fake._pubs[0]
    assert channel == CANCEL_CHANNEL
    assert "cancel_me" in message


@pytest.mark.asyncio
async def test_publish_task_cancellation_rejects_unsafe_task_id():
    fake = FakeRedis()

    with pytest.raises(ValueError, match="task_id"):
        await publish_task_cancellation("../cancel_me", redis=fake)

    assert fake._strings == {}
    assert fake._pubs == []


@pytest.mark.asyncio
async def test_set_worker_heartbeat():
    fake = FakeRedis()
    await set_worker_heartbeat(redis=fake)
    assert HEARTBEAT_KEY in fake._strings
    assert fake._strings[HEARTBEAT_KEY]["value"] == "1"
    assert fake._strings[HEARTBEAT_KEY]["ex"] == HEARTBEAT_TTL_SECONDS


@pytest.mark.asyncio
async def test_is_worker_healthy():
    fake = FakeRedis()
    assert await is_worker_healthy(redis=fake) is False
    await set_worker_heartbeat(redis=fake)
    assert await is_worker_healthy(redis=fake) is True





@pytest.mark.asyncio
async def test_claim_task_descriptor_moves_to_processing():
    fake = FakeRedis()
    descriptor = build_task_descriptor(
        job_id="task_1",
        job_kind="training",
        handler="training.preflight",
        payload={"task_id": "task_1"},
    )
    await enqueue_task_descriptor(descriptor, redis=fake)
    result = await claim_task_descriptor(timeout=1, redis=fake)
    assert result is not None
    parsed, raw = result
    assert isinstance(parsed, TaskDescriptor)
    assert parsed.job_id == "task_1"
    assert raw == descriptor.to_json()
    assert fake._lists.get(TASK_QUEUE_KEY) == []
    assert fake._lists.get(TASK_PROCESSING_KEY) == [raw]


@pytest.mark.asyncio
async def test_claim_task_descriptor_quarantines_invalid_json():
    fake = FakeRedis()
    raw = "not-json"
    await fake.lpush(TASK_QUEUE_KEY, raw)

    with pytest.raises(Exception):
        await claim_task_descriptor(timeout=1, redis=fake)

    assert fake._lists.get(TASK_QUEUE_KEY) == []
    assert fake._lists.get(TASK_PROCESSING_KEY) == []
    assert fake._lists.get(TASK_DLQ_KEY) == [raw]


@pytest.mark.asyncio
async def test_claim_task_descriptor_quarantines_invalid_descriptor_shape():
    fake = FakeRedis()
    raw = '{"schema_version":1,"job_id":"j1","job_kind":"analysis","handler":"analysis.task","payload":[],"created_at":"2026-01-01T00:00:00Z"}'
    await fake.lpush(TASK_QUEUE_KEY, raw)

    with pytest.raises(Exception):
        await claim_task_descriptor(timeout=1, redis=fake)

    assert fake._lists.get(TASK_QUEUE_KEY) == []
    assert fake._lists.get(TASK_PROCESSING_KEY) == []
    assert fake._lists.get(TASK_DLQ_KEY) == [raw]


@pytest.mark.asyncio
async def test_claim_task_descriptor_empty_queue():
    fake = FakeRedis()
    result = await claim_task_descriptor(timeout=1, redis=fake)
    assert result is None


@pytest.mark.asyncio
async def test_dequeue_task_descriptor_compatibility():
    fake = FakeRedis()
    descriptor = build_task_descriptor(
        job_id="task_1",
        job_kind="training",
        handler="training.preflight",
        payload={"task_id": "task_1"},
    )
    await enqueue_task_descriptor(descriptor, redis=fake)
    decoded = await dequeue_task_descriptor(redis=fake)
    assert decoded is not None
    assert decoded.job_id == "task_1"


@pytest.mark.asyncio
async def test_ack_task_descriptor_removes_processing():
    fake = FakeRedis()
    descriptor = build_task_descriptor(
        job_id="task_1",
        job_kind="training",
        handler="training.preflight",
        payload={"task_id": "task_1"},
    )
    raw = descriptor.to_json()
    await enqueue_task_descriptor(descriptor, redis=fake)
    result = await claim_task_descriptor(timeout=1, redis=fake)
    assert result is not None
    await ack_task_descriptor(raw, descriptor=descriptor, redis=fake)
    assert fake._lists.get(TASK_PROCESSING_KEY) == []
    assert fake._hashes.get(TASK_ATTEMPTS_KEY, {}).get("task_1") is None


@pytest.mark.asyncio
async def test_fail_task_descriptor_requeues_up_to_max():
    fake = FakeRedis()
    descriptor = build_task_descriptor(
        job_id="task_1",
        job_kind="training",
        handler="training.preflight",
        payload={"task_id": "task_1"},
    )
    raw = descriptor.to_json()
    await enqueue_task_descriptor(descriptor, redis=fake)
    result = await claim_task_descriptor(timeout=1, redis=fake)
    assert result is not None
    for i in range(TASK_RETRY_MAX):
        await fail_task_descriptor(raw, descriptor, error="err", redis=fake)
        if i < TASK_RETRY_MAX - 1:
            assert fake._lists.get(TASK_QUEUE_KEY) == [raw]
            assert fake._lists.get(TASK_PROCESSING_KEY) == []
            result = await claim_task_descriptor(timeout=1, redis=fake)
            assert result is not None
        else:
            assert fake._lists.get(TASK_QUEUE_KEY) == []
            assert fake._lists.get(TASK_PROCESSING_KEY) == []
            assert fake._lists.get(TASK_DLQ_KEY) == [raw]


@pytest.mark.asyncio
async def test_fail_task_descriptor_clears_processing_timestamp_on_retry():
    fake = FakeRedis()
    descriptor = build_task_descriptor(
        job_id="task_1",
        job_kind="training",
        handler="training.preflight",
        payload={"task_id": "task_1"},
    )
    raw = descriptor.to_json()
    await enqueue_task_descriptor(descriptor, redis=fake)
    assert await claim_task_descriptor(timeout=1, redis=fake) is not None
    assert "task_1" in fake._hashes.get(TASK_PROCESSING_TIMESTAMPS_KEY, {})

    await fail_task_descriptor(raw, descriptor, error="err", redis=fake)

    assert fake._hashes.get(TASK_PROCESSING_TIMESTAMPS_KEY, {}).get("task_1") is None


@pytest.mark.asyncio
async def test_fail_task_descriptor_clears_processing_timestamp_on_dlq():
    fake = FakeRedis()
    descriptor = build_task_descriptor(
        job_id="task_1",
        job_kind="training",
        handler="training.preflight",
        payload={"task_id": "task_1"},
    )
    raw = descriptor.to_json()
    await enqueue_task_descriptor(descriptor, redis=fake)
    assert await claim_task_descriptor(timeout=1, redis=fake) is not None

    for _ in range(TASK_RETRY_MAX):
        await fail_task_descriptor(raw, descriptor, error="err", redis=fake)
        if fake._lists.get(TASK_QUEUE_KEY):
            assert await claim_task_descriptor(timeout=1, redis=fake) is not None

    assert fake._hashes.get(TASK_PROCESSING_TIMESTAMPS_KEY, {}).get("task_1") is None


@pytest.mark.asyncio
async def test_publish_task_cancellation_writes_durable_key():
    fake = FakeRedis()
    await publish_task_cancellation("cancel_me", redis=fake)
    assert len(fake._pubs) == 1
    assert await is_task_cancelled("cancel_me", redis=fake) is True


@pytest.mark.asyncio
async def test_is_task_cancelled_not_set():
    fake = FakeRedis()
    assert await is_task_cancelled("never_cancelled", redis=fake) is False


@pytest.mark.asyncio
async def test_acquire_job_lock_success_and_duplicate():
    fake = FakeRedis()
    assert await acquire_job_lock("job_1", redis=fake) is True
    assert await acquire_job_lock("job_1", redis=fake) is False
    assert await acquire_job_lock("job_2", redis=fake) is True


@pytest.mark.asyncio
async def test_acquire_job_lock_rejects_unsafe_job_id():
    fake = FakeRedis()

    with pytest.raises(ValueError, match="job_id"):
        await acquire_job_lock("job:1", redis=fake)

    assert fake._strings == {}


@pytest.mark.asyncio
async def test_release_job_lock():
    fake = FakeRedis()
    await acquire_job_lock("job_1", redis=fake)
    await release_job_lock("job_1", redis=fake)
    assert await acquire_job_lock("job_1", redis=fake) is True


@pytest.mark.asyncio
async def test_rescue_processing_descriptors_requeues_claimed_items():
    fake = FakeRedis()
    descriptor = build_task_descriptor(
        job_id="task_1",
        job_kind="training",
        handler="training.preflight",
        payload={"task_id": "task_1"},
    )
    await enqueue_task_descriptor(descriptor, redis=fake)
    claimed = await claim_task_descriptor(timeout=1, redis=fake)
    assert claimed is not None
    _parsed, raw = claimed

    rescued = await rescue_processing_descriptors(redis=fake)

    assert rescued == 1
    assert fake._lists.get(TASK_PROCESSING_KEY) == []
    assert fake._lists.get(TASK_QUEUE_KEY) == [raw]


@pytest.mark.asyncio
async def test_claim_task_descriptor_quarantines_invalid_json():
    fake = FakeRedis()
    bad_raw = "not-json"
    await fake.lpush(TASK_QUEUE_KEY, bad_raw)
    with pytest.raises(ValueError):
        await claim_task_descriptor(timeout=1, redis=fake)
    assert fake._lists.get(TASK_PROCESSING_KEY) == []
    assert fake._lists.get(TASK_DLQ_KEY) == [bad_raw]


@pytest.mark.asyncio
async def test_claim_task_descriptor_quarantines_bad_shape():
    fake = FakeRedis()
    bad_raw = json.dumps({"schema_version": 1, "job_id": "j1", "job_kind": "test", "handler": "h", "payload": [], "created_at": "2026-01-01T00:00:00Z"})
    await fake.lpush(TASK_QUEUE_KEY, bad_raw)
    with pytest.raises(ValueError):
        await claim_task_descriptor(timeout=1, redis=fake)
    assert fake._lists.get(TASK_PROCESSING_KEY) == []
    assert fake._lists.get(TASK_DLQ_KEY) == [bad_raw]
