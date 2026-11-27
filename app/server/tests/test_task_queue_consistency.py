import asyncio
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.common.task_dispatch import build_task_descriptor
from backend.common.task_types import TaskType
from task_worker.handlers import dispatch_descriptor
from task_worker.task_queue import TaskQueueManager


@pytest.fixture
def queue(monkeypatch):
    TaskQueueManager._instance = None
    TaskQueueManager._initialized = False
    instance = TaskQueueManager(max_concurrent=1)
    monkeypatch.setattr(instance, "_invalidate_context_for_task", AsyncMock())
    monkeypatch.setattr(instance._gpu, 'snapshot', lambda: [{'index': 0, 'free_mb': 16000, 'total_mb': 24000}])
    monkeypatch.setattr(instance._gpu, 'process_memory', lambda: {})
    yield instance
    TaskQueueManager._instance = None
    TaskQueueManager._initialized = False


async def test_duplicate_descriptors_schedule_one_gpu_job(queue):
    descriptor = build_task_descriptor(
        "inference-1", "inference", "inference.single", {"task_id": "inference-1"}
    )
    await dispatch_descriptor(descriptor)
    first = queue._pending_tasks["inference-1"]
    await dispatch_descriptor(descriptor)

    assert len(queue._tasks) == 1
    assert queue._pending_tasks["inference-1"] is first
    await queue.cancel_task('inference-1')


async def test_duplicate_running_task_does_not_create_pending_job(queue):
    queue._tasks["running"] = asyncio.current_task()
    await queue.submit("running", TaskType.TRAINING, AsyncMock())
    assert len(queue._tasks) == 1
    assert "running" not in queue._pending_tasks


@pytest.mark.parametrize("handler", ["training.preflight", "training.patch_then_run"])
async def test_duplicate_patching_descriptor_does_not_restart_preflight(queue, monkeypatch, handler):
    # Missing preflight parameters deliberately: an already-owned job must be
    # skipped before resolving inputs or spawning another patching coroutine.
    queue._patching_tasks["patching"] = asyncio.current_task()
    runner = AsyncMock()
    monkeypatch.setattr("task_worker.jobs.training.validate_files_and_enqueue", runner)
    await dispatch_descriptor(build_task_descriptor(
        "patching", "training", handler, {"task_id": "patching"}
    ))
    runner.assert_not_awaited()
    assert queue._patching_tasks["patching"] is asyncio.current_task()


async def test_cancel_and_resubmit_same_id_never_executes_old_coroutine(queue, monkeypatch):
    old_runner = AsyncMock()
    new_runner = AsyncMock()

    await queue.submit("retry", TaskType.TRAINING, old_runner)
    await queue.cancel_pending_task("retry")
    await queue.submit("retry", TaskType.TRAINING, new_runner)
    await queue.start()
    try:
        await asyncio.wait_for(queue.join(), timeout=2)
    finally:
        await queue.stop()

    old_runner.assert_not_awaited()
    new_runner.assert_awaited_once()
    assert not queue._running_tasks
    assert not queue._pending_tasks


async def test_batch_inference_failure_updates_training_task_record(queue, monkeypatch):
    from task_worker import task_queue

    db = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = db
    monkeypatch.setattr(task_queue, "async_session", lambda: context)
    monkeypatch.setattr(task_queue.TrainingTaskRepository, "get_by_id", AsyncMock(
        return_value=SimpleNamespace(status="queued")
    ))
    update = AsyncMock()
    monkeypatch.setattr(task_queue.TrainingTaskRepository, "update_status", update)

    await queue._ensure_task_failed("binfer_1", TaskType.BATCH_INFERENCE, "GPU unavailable")

    assert update.await_args.args[1:3] == ("binfer_1", "failed")
    db.commit.assert_awaited_once()


async def test_large_waiting_job_does_not_block_small_research_job(queue, monkeypatch):
    queue._gpu.interval = 0.01
    small_finished = asyncio.Event()

    async def small(**kwargs):
        small_finished.set()

    await queue.submit("large", TaskType.TRAINING, AsyncMock(), resources={'operation':'custom','peak_vram_mb':20000})
    await queue.submit("small", TaskType.RESEARCH, small, resources={'operation':'custom','peak_vram_mb':2000})
    await queue.start()
    try:
        await asyncio.wait_for(small_finished.wait(), 2)
        assert "large" in queue._pending_tasks
        await queue.cancel_pending_task("large")
        await asyncio.wait_for(queue.join(), 2)
    finally:
        await queue.stop()


async def test_shutdown_waits_for_owned_background_job_cleanup(queue):
    cleaned = asyncio.Event()
    started = asyncio.Event()

    async def job():
        started.set()
        try:
            await asyncio.sleep(60)
        finally:
            cleaned.set()

    task = asyncio.create_task(job())
    queue.register_patching_task("download", task)
    await started.wait()
    await queue.stop()
    assert cleaned.is_set()
    assert task.cancelled()
    assert not queue._patching_tasks


def test_shared_task_protocols_do_not_import_gateway_or_worker_runtime():
    subprocess.run([
        sys.executable, "-c",
        "import sys; "
        "from backend.common import task_dispatch, task_runtime, task_types; "
        "assert not any(n == 'gateway' or n.startswith('gateway.') for n in sys.modules); "
        "assert 'task_worker.task_queue' not in sys.modules; "
        "assert 'torch' not in sys.modules",
    ], check=True, timeout=30)


def test_gateway_import_does_not_load_worker_queue():
    subprocess.run([
        sys.executable, "-c",
        "import gateway.main, sys; assert 'task_worker.task_queue' not in sys.modules",
    ], check=True, timeout=60)
