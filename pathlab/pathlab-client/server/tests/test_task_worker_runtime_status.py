from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from task_worker.runtime_status import (
    RUNTIME_STATUS_KEY,
    RUNTIME_STATUS_TTL_SECONDS,
    build_runtime_status_snapshot,
    empty_runtime_status,
    get_runtime_status,
    publish_runtime_status,
)


class FakeRedis:
    def __init__(self):
        self._strings: dict[str, dict[str, object]] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._strings[key] = {"value": value, "ex": ex}

    async def get(self, key: str) -> str | None:
        entry = self._strings.get(key)
        return entry["value"] if entry else None


def test_build_runtime_status_snapshot_full():
    queue = MagicMock()
    queue.max_concurrent = 4
    queue.gpu_count = 7
    queue.min_vram_mb = 2048.0
    queue.task_timeout = None
    queue._queue = MagicMock()
    queue._queue.qsize.return_value = 3
    queue._running_tasks = {"t1": MagicMock(), "t2": MagicMock()}
    queue._pending_tasks = {"t3": MagicMock(), "t4": MagicMock()}
    queue._patching_tasks = {"t5": MagicMock()}
    queue._bad_gpus = {1, 3}
    queue.descriptor_queue_counts = {
        "pending": 7,
        "processing": 2,
        "dlq": 1,
    }

    snapshot = build_runtime_status_snapshot(queue, is_running=True)

    assert snapshot["is_running"] is True
    assert snapshot["max_concurrent"] == 4
    assert snapshot["gpu_count"] == 7
    assert snapshot["task_timeout"] is None
    assert snapshot["running_count"] == 2
    assert snapshot["pending_count"] == 2
    assert snapshot["patching_count"] == 1
    assert snapshot["queue_size"] == 3
    assert snapshot["descriptor_pending_count"] == 7
    assert snapshot["descriptor_processing_count"] == 2
    assert snapshot["descriptor_dlq_count"] == 1
    assert snapshot["running_task_ids"] == ["t1", "t2"]
    assert snapshot["pending_task_ids"] == ["t3", "t4"]
    assert snapshot["patching_task_ids"] == ["t5"]
    assert snapshot["bad_gpu_ids"] == [1, 3]
    assert "updated_at" in snapshot


def test_build_runtime_status_snapshot_missing_attrs():
    queue = MagicMock(spec=[])

    snapshot = build_runtime_status_snapshot(queue, is_running=False)

    assert snapshot["is_running"] is False
    assert snapshot["max_concurrent"] is None
    assert snapshot["gpu_count"] == 0
    assert snapshot["task_timeout"] is None
    assert snapshot["running_count"] == 0
    assert snapshot["pending_count"] == 0
    assert snapshot["patching_count"] == 0
    assert snapshot["queue_size"] == 0
    assert snapshot["descriptor_pending_count"] == 0
    assert snapshot["descriptor_processing_count"] == 0
    assert snapshot["descriptor_dlq_count"] == 0
    assert snapshot["running_task_ids"] == []
    assert snapshot["pending_task_ids"] == []
    assert snapshot["patching_task_ids"] == []
    assert snapshot["bad_gpu_ids"] == []
    assert "updated_at" in snapshot


def test_build_runtime_status_snapshot_with_task_timeout():
    queue = MagicMock()
    queue.max_concurrent = 2
    queue.task_timeout = 300
    queue._queue = MagicMock()
    queue._queue.qsize.return_value = 0
    queue._running_tasks = {}
    queue._pending_tasks = {}
    queue._patching_tasks = {}
    queue._bad_gpus = set()

    snapshot = build_runtime_status_snapshot(queue, is_running=True)

    assert snapshot["task_timeout"] == 300


def test_build_runtime_status_snapshot_sorts_ids():
    queue = MagicMock()
    queue.max_concurrent = 1
    queue._queue = MagicMock()
    queue._queue.qsize.return_value = 0
    queue._running_tasks = {"z": MagicMock(), "a": MagicMock()}
    queue._pending_tasks = {"m": MagicMock(), "b": MagicMock()}
    queue._patching_tasks = {"x": MagicMock(), "c": MagicMock()}
    queue._bad_gpus = {9, 2}

    snapshot = build_runtime_status_snapshot(queue, is_running=True)

    assert snapshot["running_task_ids"] == ["a", "z"]
    assert snapshot["pending_task_ids"] == ["b", "m"]
    assert snapshot["patching_task_ids"] == ["c", "x"]
    assert snapshot["bad_gpu_ids"] == [2, 9]


def test_empty_runtime_status():
    snapshot = empty_runtime_status(is_running=False)

    assert snapshot["is_running"] is False
    assert snapshot["max_concurrent"] is None
    assert snapshot["gpu_count"] == 0
    assert snapshot["task_timeout"] is None
    assert snapshot["running_count"] == 0
    assert snapshot["pending_count"] == 0
    assert snapshot["patching_count"] == 0
    assert snapshot["descriptor_processing_count"] == 0
    assert snapshot["descriptor_dlq_count"] == 0
    assert snapshot["queue_size"] == 0
    assert snapshot["descriptor_pending_count"] == 0
    assert snapshot["descriptor_processing_count"] == 0
    assert snapshot["descriptor_dlq_count"] == 0
    assert snapshot["running_task_ids"] == []
    assert snapshot["pending_task_ids"] == []
    assert snapshot["patching_task_ids"] == []
    assert snapshot["bad_gpu_ids"] == []
    assert "updated_at" in snapshot


@pytest.mark.asyncio
async def test_publish_runtime_status():
    fake = FakeRedis()
    queue = MagicMock()
    queue.max_concurrent = 2
    queue.gpu_count = 5
    queue.task_timeout = None
    queue._queue = MagicMock()
    queue._queue.qsize.return_value = 1
    queue._running_tasks = {"r1": MagicMock()}
    queue._pending_tasks = {}
    queue._patching_tasks = {}
    queue._bad_gpus = set()

    await publish_runtime_status(queue, redis=fake)

    assert RUNTIME_STATUS_KEY in fake._strings
    stored = fake._strings[RUNTIME_STATUS_KEY]
    assert stored["ex"] == RUNTIME_STATUS_TTL_SECONDS
    parsed = json.loads(stored["value"])
    assert parsed["is_running"] is True
    assert parsed["gpu_count"] == 5
    assert parsed["running_count"] == 1


@pytest.mark.asyncio
async def test_publish_runtime_status_resets_descriptor_counts_on_collection_error(monkeypatch):
    fake = FakeRedis()
    queue = MagicMock()
    queue.max_concurrent = 2
    queue.task_timeout = None
    queue._queue = MagicMock()
    queue._queue.qsize.return_value = 0
    queue._running_tasks = {}
    queue._pending_tasks = {}
    queue._patching_tasks = {}
    queue._bad_gpus = set()
    queue.descriptor_queue_counts = {"pending": 5, "processing": 4, "dlq": 3}

    async def _raise_counts(redis):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(
        "task_worker.runtime_status.import_module",
        lambda name: SimpleNamespace(get_task_descriptor_queue_counts=_raise_counts),
    )

    await publish_runtime_status(queue, redis=fake)

    parsed = json.loads(fake._strings[RUNTIME_STATUS_KEY]["value"])
    assert parsed["descriptor_pending_count"] == 0
    assert parsed["descriptor_processing_count"] == 0
    assert parsed["descriptor_dlq_count"] == 0


@pytest.mark.asyncio
async def test_get_runtime_status_existing():
    fake = FakeRedis()
    payload = {"is_running": True, "running_count": 5}
    await fake.set(RUNTIME_STATUS_KEY, json.dumps(payload), ex=20)

    result = await get_runtime_status(redis=fake)

    assert result == payload


@pytest.mark.asyncio
async def test_get_runtime_status_missing():
    fake = FakeRedis()

    result = await get_runtime_status(redis=fake)

    assert result is None


@pytest.mark.asyncio
async def test_get_runtime_status_malformed():
    fake = FakeRedis()
    await fake.set(RUNTIME_STATUS_KEY, "not-json", ex=20)

    result = await get_runtime_status(redis=fake)

    assert result is None


@pytest.mark.asyncio
async def test_get_runtime_status_non_dict_json():
    fake = FakeRedis()
    await fake.set(RUNTIME_STATUS_KEY, json.dumps([1, 2, 3]), ex=20)

    result = await get_runtime_status(redis=fake)

    assert result is None

    await fake.set(RUNTIME_STATUS_KEY, json.dumps(42), ex=20)

    result = await get_runtime_status(redis=fake)

    assert result is None


@pytest.mark.asyncio
async def test_get_runtime_status_redis_error():
    class BadRedis:
        async def get(self, key: str) -> str | None:
            raise RuntimeError("redis down")

    result = await get_runtime_status(redis=BadRedis())
    assert result is None


@pytest.mark.asyncio
async def test_publish_runtime_status_redis_error():
    class BadRedis:
        async def set(self, key: str, value: str, ex: int | None = None) -> None:
            raise RuntimeError("redis down")

    queue = MagicMock()
    queue.max_concurrent = 1
    queue.task_timeout = None
    queue._queue = MagicMock()
    queue._queue.qsize.return_value = 0
    queue._running_tasks = {}
    queue._pending_tasks = {}
    queue._patching_tasks = {}
    queue._bad_gpus = set()

    await publish_runtime_status(queue, redis=BadRedis())
