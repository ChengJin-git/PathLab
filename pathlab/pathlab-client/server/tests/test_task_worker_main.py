"""Tests for task_worker main runtime."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.task_dispatch import (
    TaskDescriptor,
    build_task_descriptor,
    CANCEL_CHANNEL,
)


class _ClaimedDescriptor:
    def __init__(self, descriptor: TaskDescriptor):
        self.descriptor = descriptor
        self.raw_descriptor = descriptor.to_json()

    def __iter__(self):
        yield self.descriptor
        yield self.raw_descriptor


@pytest.fixture
def fake_redis():
    class FakeRedis:
        def __init__(self):
            self._lists: dict[str, list[str]] = {}
            self._strings: dict[str, dict[str, object]] = {}
            self._pubs: list[tuple[str, str]] = []

        async def lpush(self, key: str, value: str) -> None:
            self._lists.setdefault(key, []).append(value)

        async def brpop(self, key: str, timeout: float = 0.0) -> tuple[str, str] | None:
            lst = self._lists.get(key, [])
            if not lst:
                return None
            return (key, lst.pop(0))

        async def publish(self, channel: str, message: str) -> None:
            self._pubs.append((channel, message))

        async def set(self, key: str, value: str, ex: int | None = None) -> None:
            self._strings[key] = {"value": value, "ex": ex}

        async def exists(self, key: str) -> int:
            return 1 if key in self._strings else 0

    return FakeRedis()


@pytest.fixture
def fake_task_queue(monkeypatch):
    queue = MagicMock()
    queue.cancel_task = AsyncMock(return_value=True)
    monkeypatch.setattr("gateway.task_queue.get_task_queue", lambda: queue)
    return queue


@pytest.mark.asyncio
async def test_run_once_dequeues_and_dispatches(monkeypatch, fake_redis):
    from task_worker.main import TaskWorkerRuntime

    dispatched = []

    async def fake_dispatch(descriptor: TaskDescriptor) -> None:
        dispatched.append(descriptor)

    monkeypatch.setattr(
        "task_worker.main.dispatch_descriptor", fake_dispatch
    )
    async def fake_dequeue(timeout, redis=None):
        result = await fake_redis.brpop("task_worker:queue", timeout=timeout)
        if result is None:
            return None
        return TaskDescriptor.from_json(result[1])

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="training",
        handler="training.preflight",
        payload={"task_id": "t1"},
    )
    await fake_redis.lpush("task_worker:queue", descriptor.to_json())

    runtime = TaskWorkerRuntime(dequeue=fake_dequeue)
    await runtime.run_once()

    assert len(dispatched) == 1
    assert dispatched[0].job_id == "j1"
    assert dispatched[0].handler == "training.preflight"


@pytest.mark.asyncio
async def test_run_once_invalid_descriptor_logs_and_continues(monkeypatch, caplog):
    from task_worker.main import TaskWorkerRuntime

    async def fake_dequeue_bad_descriptor(timeout, redis=None):
        class BadDescriptor:
            job_id = "bad_job"
        return BadDescriptor()

    runtime = TaskWorkerRuntime(dequeue=fake_dequeue_bad_descriptor)
    with caplog.at_level(logging.ERROR, logger="task_worker"):
        await runtime.run_once()

    assert "Failed to process task descriptor" in caplog.text


@pytest.mark.asyncio
async def test_run_once_malformed_descriptor_without_job_id_logs_and_continues(monkeypatch, caplog):
    from task_worker.main import TaskWorkerRuntime

    async def fake_dequeue_malformed_descriptor(timeout, redis=None):
        class MalformedDescriptor:
            pass
        return MalformedDescriptor()

    runtime = TaskWorkerRuntime(dequeue=fake_dequeue_malformed_descriptor)
    with caplog.at_level(logging.ERROR, logger="task_worker"):
        await runtime.run_once()

    assert "Failed to process task descriptor" in caplog.text


@pytest.mark.asyncio
async def test_run_once_claimed_descriptor_missing_job_id_quarantines(monkeypatch):
    from task_worker.main import TaskWorkerRuntime

    bad_raw = '{"schema_version":1,"job_id":"","job_kind":"test","handler":"h","payload":{},"created_at":"2026-01-01T00:00:00Z"}'
    events = []

    async def fake_claim(timeout):
        from gateway.task_dispatch import TaskDescriptor
        d = TaskDescriptor(
            schema_version=1,
            job_id="",
            job_kind="test",
            handler="h",
            payload={},
            created_at="2026-01-01T00:00:00Z",
        )
        return (d, bad_raw)

    async def fake_ack(raw, descriptor=None):
        events.append(("ack", raw))

    async def fake_quarantine(raw, descriptor=None, error=None):
        events.append(("quarantine", raw))

    monkeypatch.setattr("task_worker.main.claim_task_descriptor", fake_claim)
    monkeypatch.setattr("task_worker.main.ack_task_descriptor", fake_ack)
    monkeypatch.setattr("task_worker.main.quarantine_task_descriptor", fake_quarantine)

    runtime = TaskWorkerRuntime()
    await runtime.run_once()

    assert any(e[0] == "quarantine" and e[1] == bad_raw for e in events)


@pytest.mark.asyncio
async def test_run_once_rejects_claimed_descriptor_without_job_id(monkeypatch, caplog):
    from task_worker.main import TaskWorkerRuntime

    raw = "raw descriptor"
    descriptor = TaskDescriptor(
        schema_version=1,
        job_id="",
        job_kind="training",
        handler="training.preflight",
        payload={"task_id": "t1"},
        created_at="2026-01-01T00:00:00Z",
    )
    quarantined: list[str] = []

    async def fake_claim(timeout):
        return descriptor, raw

    async def fake_quarantine(raw_descriptor, descriptor=None, error=None, redis=None):
        quarantined.append(raw_descriptor)

    monkeypatch.setattr("task_worker.main.claim_task_descriptor", fake_claim)
    monkeypatch.setattr("task_worker.main.quarantine_task_descriptor", fake_quarantine)

    runtime = TaskWorkerRuntime()
    with caplog.at_level(logging.ERROR, logger="task_worker"):
        await runtime.run_once()

    assert quarantined == [raw]
    assert "missing job_id" in caplog.text


@pytest.mark.asyncio
async def test_run_once_dequeue_error_logs_and_continues(monkeypatch, caplog):
    from task_worker.main import TaskWorkerRuntime

    async def failing_dequeue(timeout, redis=None):
        raise RuntimeError("Redis is down")

    runtime = TaskWorkerRuntime(dequeue=failing_dequeue)
    with caplog.at_level(logging.ERROR, logger="task_worker"):
        await runtime.run_once()

    assert "Failed to dequeue task descriptor" in caplog.text


@pytest.mark.asyncio
async def test_heartbeat_once_sets_heartbeat_and_publishes_snapshot(monkeypatch, fake_redis):
    from task_worker.main import TaskWorkerRuntime

    heartbeat_called = []
    snapshot_called = []

    async def fake_set_heartbeat(redis=None):
        heartbeat_called.append(redis)

    monkeypatch.setattr(
        "task_worker.main.set_worker_heartbeat", fake_set_heartbeat
    )

    fake_queue = MagicMock()
    fake_queue.max_concurrent = 2
    fake_queue.task_timeout = 30
    fake_queue._running_tasks = {"t1": "running"}
    fake_queue._pending_tasks = {"t2": "pending"}
    fake_queue._patching_tasks = {"t3": "patching"}
    fake_queue._bad_gpus = {0}
    fake_queue._queue = MagicMock()
    fake_queue._queue.qsize.return_value = 1

    monkeypatch.setattr(
        "gateway.task_queue.get_task_queue", lambda: fake_queue
    )

    async def fake_publish_runtime_status(queue, redis=None):
        snapshot_called.append(queue)

    monkeypatch.setattr(
        "task_worker.main.publish_runtime_status", fake_publish_runtime_status
    )

    runtime = TaskWorkerRuntime()
    await runtime.heartbeat_once()

    assert len(heartbeat_called) == 1
    assert len(snapshot_called) == 1
    assert snapshot_called[0] is fake_queue


@pytest.mark.asyncio
async def test_heartbeat_once_heartbeat_failure_still_attempts_publish(monkeypatch, caplog):
    from task_worker.main import TaskWorkerRuntime

    heartbeat_called = []
    snapshot_called = []

    async def failing_heartbeat(redis=None):
        heartbeat_called.append("heartbeat")
        raise RuntimeError("redis down")

    monkeypatch.setattr(
        "task_worker.main.set_worker_heartbeat", failing_heartbeat
    )

    fake_queue = MagicMock()
    monkeypatch.setattr(
        "gateway.task_queue.get_task_queue", lambda: fake_queue
    )

    async def fake_publish_runtime_status(queue, redis=None):
        snapshot_called.append(queue)

    monkeypatch.setattr(
        "task_worker.main.publish_runtime_status", fake_publish_runtime_status
    )

    runtime = TaskWorkerRuntime()
    with caplog.at_level(logging.WARNING, logger="task_worker"):
        await runtime.heartbeat_once()

    assert len(heartbeat_called) == 1
    assert len(snapshot_called) == 1
    assert snapshot_called[0] is fake_queue
    assert "Heartbeat failed" in caplog.text


@pytest.mark.asyncio
async def test_heartbeat_once_publish_failure_logs_warning(monkeypatch, caplog):
    from task_worker.main import TaskWorkerRuntime

    heartbeat_called = []

    async def fake_set_heartbeat(redis=None):
        heartbeat_called.append("heartbeat")

    monkeypatch.setattr(
        "task_worker.main.set_worker_heartbeat", fake_set_heartbeat
    )

    async def failing_publish_runtime_status(queue, redis=None):
        raise RuntimeError("publish failed")

    monkeypatch.setattr(
        "task_worker.main.publish_runtime_status", failing_publish_runtime_status
    )

    runtime = TaskWorkerRuntime()
    with caplog.at_level(logging.WARNING, logger="task_worker"):
        await runtime.heartbeat_once()

    assert len(heartbeat_called) == 1
    assert "Runtime snapshot publish failed" in caplog.text


@pytest.mark.asyncio
async def test_handle_cancel_message_calls_cancel_task(fake_task_queue):
    from task_worker.main import TaskWorkerRuntime

    runtime = TaskWorkerRuntime()
    await runtime.handle_cancel_message(json.dumps({"task_id": "cancel_me"}))

    fake_task_queue.cancel_task.assert_awaited_once_with("cancel_me")


@pytest.mark.asyncio
async def test_handle_cancel_message_invalid_payload_logs(caplog):
    from task_worker.main import TaskWorkerRuntime

    runtime = TaskWorkerRuntime()
    with caplog.at_level(logging.WARNING, logger="task_worker"):
        await runtime.handle_cancel_message("not-json")

    assert "Ignoring invalid cancellation payload" in caplog.text


@pytest.mark.asyncio
async def test_handle_cancel_message_missing_task_id_logs(caplog):
    from task_worker.main import TaskWorkerRuntime

    runtime = TaskWorkerRuntime()
    with caplog.at_level(logging.WARNING, logger="task_worker"):
        await runtime.handle_cancel_message(json.dumps({"foo": "bar"}))

    assert "Ignoring cancellation payload without task_id" in caplog.text


@pytest.mark.asyncio
async def test_run_loop_stops_on_event(monkeypatch):
    from task_worker.main import TaskWorkerRuntime

    calls = []

    async def fake_run_once(self):
        calls.append("run_once")
        if len(calls) >= 2:
            self._shutdown_event.set()

    monkeypatch.setattr(TaskWorkerRuntime, "run_once", fake_run_once)

    runtime = TaskWorkerRuntime()
    runtime._shutdown_event = asyncio.Event()
    await runtime.run_loop()

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_heartbeat_loop_stops_on_event(monkeypatch):
    from task_worker.main import TaskWorkerRuntime

    calls = []

    async def fake_heartbeat_once(self):
        calls.append("heartbeat_once")
        if len(calls) >= 2:
            self._shutdown_event.set()

    monkeypatch.setattr(TaskWorkerRuntime, "heartbeat_once", fake_heartbeat_once)

    runtime = TaskWorkerRuntime()
    runtime._shutdown_event = asyncio.Event()
    await runtime.heartbeat_loop()

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_cancel_loop_stops_on_event(monkeypatch):
    from task_worker.main import TaskWorkerRuntime

    calls = []

    async def fake_get_message(timeout):
        calls.append("get_message")
        if len(calls) >= 2:
            runtime._shutdown_event.set()
        return None

    monkeypatch.setattr(
        "task_worker.main._get_cancel_message", fake_get_message
    )

    runtime = TaskWorkerRuntime()
    runtime._shutdown_event = asyncio.Event()
    await runtime.cancel_loop()

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_initialize_task_queue_runtime_with_gpu_probe(monkeypatch):
    from task_worker.main import _initialize_task_queue_runtime

    monkeypatch.setattr(
        "backend.common.gpu_utils.get_gpu_count", lambda: 2
    )
    monkeypatch.setattr(
        "backend.common.gpu_utils.probe_all_gpu_health",
        lambda: {0: True, 1: False},
    )

    init_calls = []

    async def fake_init_task_queue(**kwargs):
        init_calls.append(kwargs)

    monkeypatch.setattr(
        "gateway.task_queue.init_task_queue", fake_init_task_queue
    )

    queue_mock = MagicMock()
    queue_mock.mark_gpu_bad = MagicMock()
    monkeypatch.setattr(
        "gateway.task_queue.get_task_queue", lambda: queue_mock
    )

    await _initialize_task_queue_runtime()

    assert len(init_calls) == 1
    assert init_calls[0]["gpu_count"] == 2
    queue_mock.mark_gpu_bad.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_initialize_task_queue_runtime_import_error_fallback(monkeypatch):
    from task_worker.main import _initialize_task_queue_runtime

    def bad_import():
        raise ImportError("no gpu_utils")

    monkeypatch.setattr(
        "backend.common.gpu_utils.get_gpu_count", bad_import
    )

    init_calls = []

    async def fake_init_task_queue(**kwargs):
        init_calls.append(kwargs)

    monkeypatch.setattr(
        "gateway.task_queue.init_task_queue", fake_init_task_queue
    )

    await _initialize_task_queue_runtime()

    assert len(init_calls) == 1
    assert init_calls[0]["gpu_count"] == 1


@pytest.mark.asyncio
async def test_run_recovery_guarded_when_module_missing(monkeypatch, caplog):
    from task_worker.main import _run_recovery

    monkeypatch.setattr(
        "task_worker.main.import_module",
        lambda name: (_ for _ in ()).throw(ImportError("no module")),
    )

    with caplog.at_level(logging.INFO, logger="task_worker"):
        await _run_recovery()

    assert "Recovery module not available" in caplog.text


@pytest.mark.asyncio
async def test_run_recovery_calls_resume_when_module_present(monkeypatch):
    from task_worker.main import _run_recovery

    called = []

    class FakeModule:
        @staticmethod
        async def resume_interrupted_tasks():
            called.append("resume")

    monkeypatch.setattr(
        "task_worker.main.import_module", lambda name: FakeModule()
    )

    await _run_recovery()
    assert called == ["resume"]


@pytest.mark.asyncio
async def test_run_recovery_rescues_processing_descriptors_before_task_recovery(monkeypatch):
    from task_worker.main import _run_recovery

    called = []

    async def fake_rescue_processing():
        called.append("rescue-processing")
        return 2

    class FakeModule:
        @staticmethod
        async def resume_interrupted_tasks():
            called.append("resume-db-tasks")

    monkeypatch.setattr("task_worker.main.rescue_processing_descriptors", fake_rescue_processing)
    monkeypatch.setattr(
        "task_worker.main.import_module", lambda name: FakeModule()
    )

    await _run_recovery()

    assert called == ["rescue-processing", "resume-db-tasks"]


@pytest.mark.asyncio
async def test_runtime_injected_dequeue_and_dispatch():
    from task_worker.main import TaskWorkerRuntime

    calls = []

    async def fake_dequeue(timeout):
        return build_task_descriptor(
            job_id="j1", job_kind="test", handler="test.handler", payload={}
        )

    async def fake_dispatch(descriptor):
        calls.append(descriptor.job_id)

    runtime = TaskWorkerRuntime(dequeue=fake_dequeue, dispatch=fake_dispatch)
    await runtime.run_once()

    assert calls == ["j1"]


@pytest.mark.asyncio
async def test_run_once_claims_dispatches_acks_and_releases_lock(monkeypatch):
    from task_worker.main import TaskWorkerRuntime

    descriptor = build_task_descriptor(
        job_id="j-ack", job_kind="test", handler="test.handler", payload={}
    )
    claimed = _ClaimedDescriptor(descriptor)
    events = []

    async def fake_claim(timeout):
        events.append(("claim", timeout))
        return claimed

    async def fake_cancelled(job_id):
        events.append(("cancelled", job_id))
        return False

    async def fake_lock(job_id):
        events.append(("lock", job_id))
        return True

    async def fake_dispatch(received):
        events.append(("dispatch", received.job_id))

    async def fake_ack(raw, descriptor=None):
        events.append(("ack", raw, descriptor.job_id if descriptor else None))

    async def fake_release(job_id):
        events.append(("release", job_id))

    monkeypatch.setattr("task_worker.main.claim_task_descriptor", fake_claim)
    monkeypatch.setattr("task_worker.main.is_task_cancelled", fake_cancelled)
    monkeypatch.setattr("task_worker.main.acquire_job_lock", fake_lock)
    monkeypatch.setattr("task_worker.main.dispatch_descriptor", fake_dispatch)
    monkeypatch.setattr("task_worker.main.ack_task_descriptor", fake_ack)
    monkeypatch.setattr("task_worker.main.release_job_lock", fake_release)

    runtime = TaskWorkerRuntime()
    await runtime.run_once()

    assert ("dispatch", "j-ack") in events
    assert ("ack", claimed.raw_descriptor, "j-ack") in events
    assert events[-1] == ("release", "j-ack")


@pytest.mark.asyncio
async def test_run_once_skips_durably_cancelled_descriptor(monkeypatch):
    from task_worker.main import TaskWorkerRuntime

    descriptor = build_task_descriptor(
        job_id="j-cancel", job_kind="test", handler="test.handler", payload={}
    )
    claimed = _ClaimedDescriptor(descriptor)
    events = []

    async def fake_claim(timeout):
        return claimed

    async def fake_cancelled(job_id):
        return True

    async def fake_ack(raw, descriptor=None):
        events.append(("ack", descriptor.job_id if descriptor else None))

    async def forbidden_dispatch(_descriptor):
        raise AssertionError("cancelled descriptor must not dispatch")

    monkeypatch.setattr("task_worker.main.claim_task_descriptor", fake_claim)
    monkeypatch.setattr("task_worker.main.is_task_cancelled", fake_cancelled)
    monkeypatch.setattr("task_worker.main.ack_task_descriptor", fake_ack)
    monkeypatch.setattr("task_worker.main.dispatch_descriptor", forbidden_dispatch)

    runtime = TaskWorkerRuntime()
    await runtime.run_once()

    assert events == [("ack", "j-cancel")]


@pytest.mark.asyncio
async def test_run_once_requeues_claimed_descriptor_on_dispatch_failure(monkeypatch):
    from task_worker.main import TaskWorkerRuntime

    descriptor = build_task_descriptor(
        job_id="j-fail", job_kind="test", handler="test.handler", payload={}
    )
    claimed = _ClaimedDescriptor(descriptor)
    events = []

    async def fake_claim(timeout):
        return claimed

    async def fake_cancelled(job_id):
        return False

    async def fake_lock(job_id):
        return True

    async def failing_dispatch(_descriptor):
        raise RuntimeError("boom")

    async def fake_fail(raw, descriptor, error):
        events.append(("fail", raw, descriptor.job_id, str(error)))

    async def fake_release(job_id):
        events.append(("release", job_id))

    monkeypatch.setattr("task_worker.main.claim_task_descriptor", fake_claim)
    monkeypatch.setattr("task_worker.main.is_task_cancelled", fake_cancelled)
    monkeypatch.setattr("task_worker.main.acquire_job_lock", fake_lock)
    monkeypatch.setattr("task_worker.main.dispatch_descriptor", failing_dispatch)
    monkeypatch.setattr("task_worker.main.fail_task_descriptor", fake_fail)
    monkeypatch.setattr("task_worker.main.release_job_lock", fake_release)

    runtime = TaskWorkerRuntime()
    await runtime.run_once()

    assert events[0][0:3] == ("fail", claimed.raw_descriptor, "j-fail")
    assert events[-1] == ("release", "j-fail")


@pytest.mark.asyncio
async def test_run_once_acks_duplicate_locked_descriptor(monkeypatch):
    from task_worker.main import TaskWorkerRuntime

    descriptor = build_task_descriptor(
        job_id="j-dupe", job_kind="test", handler="test.handler", payload={}
    )
    claimed = _ClaimedDescriptor(descriptor)
    events = []

    async def fake_claim(timeout):
        return claimed

    async def fake_cancelled(job_id):
        return False

    async def fake_lock(job_id):
        return False

    async def fake_ack(raw, descriptor=None):
        events.append(("ack", descriptor.job_id if descriptor else None))

    async def forbidden_dispatch(_descriptor):
        raise AssertionError("duplicate descriptor must not dispatch")

    monkeypatch.setattr("task_worker.main.claim_task_descriptor", fake_claim)
    monkeypatch.setattr("task_worker.main.is_task_cancelled", fake_cancelled)
    monkeypatch.setattr("task_worker.main.acquire_job_lock", fake_lock)
    monkeypatch.setattr("task_worker.main.ack_task_descriptor", fake_ack)
    monkeypatch.setattr("task_worker.main.dispatch_descriptor", forbidden_dispatch)

    runtime = TaskWorkerRuntime()
    await runtime.run_once()

    assert events == [("ack", "j-dupe")]


@pytest.mark.asyncio
async def test_runtime_injected_heartbeat():
    from task_worker.main import TaskWorkerRuntime

    beats = []

    async def fake_heartbeat():
        beats.append("beat")

    runtime = TaskWorkerRuntime(heartbeat=fake_heartbeat)
    await runtime.heartbeat_once()

    assert beats == ["beat"]


@pytest.mark.asyncio
async def test_runtime_injected_cancel_task():
    from task_worker.main import TaskWorkerRuntime

    cancels = []

    async def fake_cancel(task_id):
        cancels.append(task_id)

    runtime = TaskWorkerRuntime(cancel_task=fake_cancel)
    await runtime.handle_cancel_message(json.dumps({"task_id": "t1"}))

    assert cancels == ["t1"]


@pytest.mark.asyncio
async def test_cancel_loop_uses_injected_get_message():
    from task_worker.main import TaskWorkerRuntime

    msgs = [json.dumps({"task_id": "a"}), None]
    idx = 0

    async def fake_get_message(timeout):
        nonlocal idx
        item = msgs[idx]
        idx += 1
        if item is None:
            runtime._shutdown_event.set()
        return item

    cancels = []

    async def fake_cancel(task_id):
        cancels.append(task_id)

    runtime = TaskWorkerRuntime(
        get_cancel_message=fake_get_message, cancel_task=fake_cancel
    )
    await runtime.cancel_loop()

    assert cancels == ["a"]


@pytest.mark.asyncio
async def test_cancel_loop_reads_from_subscribed_pubsub(monkeypatch):
    from task_worker.main import TaskWorkerRuntime

    class FakePubSub:
        def __init__(self):
            self._messages = [
                {"type": "message", "data": json.dumps({"task_id": "pubsub_task"})},
                None,
            ]
            self._idx = 0

        async def get_message(self, timeout):
            msg = self._messages[self._idx]
            self._idx += 1
            return msg

    pubsub = FakePubSub()

    cancels = []

    async def fake_cancel(task_id):
        cancels.append(task_id)

    async def fake_get_message(timeout):
        msg = await pubsub.get_message(timeout=timeout)
        if msg is None:
            runtime._shutdown_event.set()
        return msg.get("data") if isinstance(msg, dict) else msg

    runtime = TaskWorkerRuntime(
        get_cancel_message=fake_get_message, cancel_task=fake_cancel
    )
    await runtime.cancel_loop()

    assert cancels == ["pubsub_task"]


@pytest.mark.asyncio
async def test_default_cancel_fallback_returns_none_silently():
    from task_worker.main import _get_cancel_message

    result = await _get_cancel_message(1.0)
    assert result is None


@pytest.mark.asyncio
async def test_main_calls_startup_before_loops_and_shutdown_after(monkeypatch):
    from task_worker import main as main_module

    startup_calls = []
    shutdown_calls = []
    loop_calls = []

    async def fake_startup():
        startup_calls.append("startup")
        return main_module.TaskWorkerRuntime()

    async def fake_shutdown(runtime):
        shutdown_calls.append("shutdown")

    async def fake_run_loop(self):
        loop_calls.append("run_loop")
        self._shutdown_event.set()

    async def fake_heartbeat_loop(self, interval=5.0):
        loop_calls.append("heartbeat_loop")

    async def fake_cancel_loop(self):
        loop_calls.append("cancel_loop")

    monkeypatch.setattr(main_module, "_startup", fake_startup)
    monkeypatch.setattr(main_module, "_shutdown", fake_shutdown)
    monkeypatch.setattr(main_module.TaskWorkerRuntime, "run_loop", fake_run_loop)
    monkeypatch.setattr(main_module.TaskWorkerRuntime, "heartbeat_loop", fake_heartbeat_loop)
    monkeypatch.setattr(main_module.TaskWorkerRuntime, "cancel_loop", fake_cancel_loop)

    await main_module.main()

    assert startup_calls == ["startup"]
    assert "run_loop" in loop_calls
    assert "heartbeat_loop" in loop_calls
    assert "cancel_loop" in loop_calls
    assert shutdown_calls == ["shutdown"]


@pytest.mark.asyncio
async def test_main_preserves_runtime_dependencies_no_cloning(monkeypatch):
    from task_worker import main as main_module

    beats = []

    async def fake_heartbeat():
        beats.append("beat")

    async def fake_startup():
        return main_module.TaskWorkerRuntime(heartbeat=fake_heartbeat)

    monkeypatch.setattr(main_module, "_startup", fake_startup)
    async def fake_shutdown(runtime):
        runtime._shutdown_event.set()

    monkeypatch.setattr(main_module, "_shutdown", fake_shutdown)
    monkeypatch.setattr(
        main_module, "_subscribe_cancel_channel",
        lambda: (_ for _ in ()).throw(RuntimeError("no redis"))
    )

    async def fake_heartbeat_loop(self, interval=5.0):
        beats.append("loop")
        self._shutdown_event.set()

    monkeypatch.setattr(main_module.TaskWorkerRuntime, "heartbeat_loop", fake_heartbeat_loop)

    async def fake_cancel_loop(self):
        self._shutdown_event.set()

    monkeypatch.setattr(main_module.TaskWorkerRuntime, "cancel_loop", fake_cancel_loop)

    async def fake_run_loop(self):
        self._shutdown_event.set()

    monkeypatch.setattr(main_module.TaskWorkerRuntime, "run_loop", fake_run_loop)

    await main_module.main()

    assert "loop" in beats


@pytest.mark.asyncio
async def test_main_shutdown_on_failure_after_startup(monkeypatch):
    from task_worker import main as main_module

    shutdown_runtimes = []

    async def fake_startup():
        return main_module.TaskWorkerRuntime()

    async def fake_shutdown(runtime):
        shutdown_runtimes.append(runtime)

    monkeypatch.setattr(main_module, "_startup", fake_startup)
    monkeypatch.setattr(main_module, "_shutdown", fake_shutdown)
    monkeypatch.setattr(
        main_module, "_subscribe_cancel_channel",
        lambda: (_ for _ in ()).throw(RuntimeError("subscribe failed"))
    )

    async def fake_run_loop(self):
        raise RuntimeError("loop crashed")

    monkeypatch.setattr(main_module.TaskWorkerRuntime, "run_loop", fake_run_loop)
    async def fake_heartbeat_loop(self, interval=5.0):
        self._shutdown_event.set()

    monkeypatch.setattr(main_module.TaskWorkerRuntime, "heartbeat_loop", fake_heartbeat_loop)

    async def fake_cancel_loop(self):
        self._shutdown_event.set()

    monkeypatch.setattr(main_module.TaskWorkerRuntime, "cancel_loop", fake_cancel_loop)

    with pytest.raises(RuntimeError, match="loop crashed"):
        await main_module.main()

    assert len(shutdown_runtimes) == 1


@pytest.mark.asyncio
async def test_cancel_loop_survives_get_message_error(caplog):
    from task_worker.main import TaskWorkerRuntime

    calls = []

    async def failing_get_message(timeout):
        calls.append("get")
        if len(calls) == 1:
            raise RuntimeError("pubsub broken")
        runtime._shutdown_event.set()
        return None

    runtime = TaskWorkerRuntime(get_cancel_message=failing_get_message)
    with caplog.at_level(logging.ERROR, logger="task_worker"):
        await runtime.cancel_loop()

    assert len(calls) == 2
    assert "pubsub broken" in caplog.text


@pytest.mark.asyncio
async def test_default_cancel_fallback_is_silent():
    from task_worker.main import _get_cancel_message

    result = await _get_cancel_message(1.0)
    assert result is None


def test_importing_main_does_not_load_gpu_utils_or_task_queue():
    import importlib

    preloaded = set(sys.modules.keys())

    import task_worker.main as main_module
    importlib.reload(main_module)

    newly_loaded = set(sys.modules.keys()) - preloaded

    assert "backend.common.gpu_utils" not in newly_loaded, (
        f"backend.common.gpu_utils loaded as side-effect: {newly_loaded}"
    )
    assert "gateway.task_queue" not in newly_loaded, (
        f"gateway.task_queue loaded as side-effect: {newly_loaded}"
    )
