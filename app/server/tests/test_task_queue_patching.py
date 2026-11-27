"""Mixed jobs and pipeline stages must share one memory/concurrency contract."""

import asyncio
import os
from unittest.mock import AsyncMock

import pytest

from backend.common.gpu_resources import GpuWorkload, estimate_gpu, task_workload
from backend.common.task_types import TaskType
from task_worker.gpu_scheduler import GpuScheduler, Request
from task_worker.task_queue import TaskQueueManager


@pytest.fixture
def queue(monkeypatch):
    TaskQueueManager._instance = None
    TaskQueueManager._initialized = False
    q = TaskQueueManager(max_concurrent=2, vram_check_interval=0.01)
    q._gpu.snapshot = lambda: [{"index": 0, "free_mb": 12000, "total_mb": 24000}]
    q._gpu.process_memory = dict
    monkeypatch.setattr(q, "_invalidate_context_for_task", AsyncMock())
    monkeypatch.setattr(q, "_ensure_task_failed", AsyncMock())
    yield q
    TaskQueueManager._instance = None
    TaskQueueManager._initialized = False


def test_shared_estimates_distinguish_frozen_encoder_training_and_embeddings():
    extraction = GpuWorkload(
        operation="feature_extraction", model="conch", batch_size=64
    )
    patch = task_workload(
        "training",
        {
            "training_task_type": "patch_classification",
            "preprocessing_config": {"feature_extractor": "conch"},
            "model_config": {"batch_size": 64},
        },
    )
    assert (
        estimate_gpu(patch).required_mb == estimate_gpu(extraction).required_mb < 24000
    )
    fine_tune = extraction.model_copy(update={"trainable": True})
    assert estimate_gpu(fine_tune).required_mb > estimate_gpu(extraction).required_mb
    large = GpuWorkload(
        operation="mil_training", model="transmil", bag_size=100000, feature_dim=2560
    )
    assert estimate_gpu(large).required_mb > 8000
    assert (
        estimate_gpu(GpuWorkload(operation="custom", peak_vram_mb=8192)).required_mb
        == 8192
    )
    with pytest.raises(ValueError):
        GpuWorkload(operation="custom")


def test_gpu_queue_wait_is_excluded_from_research_wall_budget():
    from types import SimpleNamespace

    from backend.autoresearch.engine.budget import expired

    session = SimpleNamespace(
        recovery_metadata={
            "started_at": 100,
            "time_budget_seconds": 600,
            "gpu_wait_started_at": 200,
        }
    )
    assert not expired(session, now=5000)
    session.recovery_metadata = {"started_at": 4900, "time_budget_seconds": 600}
    assert not expired(session, now=5000)
    assert expired(session, now=5500)


async def test_stage_waiter_does_not_consume_slot_and_research_backfills(queue):
    ready = asyncio.Event()

    async def staged(**kwargs):
        await queue.acquire_gpu_stage(kwargs["task_id"], "features", 18000)
        raise AssertionError("not enough memory")

    async def research(**kwargs):
        assert kwargs["assigned_device"] == "cuda:0"
        ready.set()

    await queue.start()
    await queue.submit("chat", TaskType.TRAINING, staged, staged=True)
    await queue.submit(
        "research",
        TaskType.RESEARCH,
        research,
        resources={"operation": "custom", "peak_vram_mb": 4000},
    )
    await asyncio.wait_for(ready.wait(), 2)
    assert "chat" in queue._pending_tasks and "chat" not in queue._running_tasks
    await queue.cancel_task("chat")
    await queue.join()
    assert not queue._gpu.leases and not queue._gpu.pending
    await queue.stop()


async def test_stage_and_job_share_concurrency_and_cancel_releases(queue):
    queue._gpu.limit = 1
    started, second = asyncio.Event(), asyncio.Event()

    async def job(**kwargs):
        started.set()
        await asyncio.Event().wait()

    async def stage():
        await queue.acquire_gpu_stage("chat", "training", 2000)
        second.set()
        queue.release_gpu_stage("chat", "training")

    await queue.submit(
        "research",
        TaskType.RESEARCH,
        job,
        resources={"operation": "custom", "peak_vram_mb": 4000},
    )
    await asyncio.wait_for(started.wait(), 2)
    waiter = asyncio.create_task(stage())
    await asyncio.sleep(0.03)
    assert not second.is_set()
    await queue.cancel_task("research")
    await asyncio.wait_for(waiter, 2)
    assert second.is_set()
    await queue.stop()


async def test_best_fit_and_no_double_count_for_own_allocations():
    scheduler = GpuScheduler(list, dict, limit=2)
    r = Request(
        "one",
        "job",
        6000,
        asyncio.get_running_loop().create_future(),
        gpu=0,
        pid=os.getpid(),
    )
    scheduler.leases[("one", "job")] = r
    scheduler.baselines[(0, os.getpid(), False)] = 1000
    # 1GiB process baseline is not charged to this task. 4GiB task usage is
    # already reflected in NVML free; only remaining 2GiB is withheld.
    assert (
        scheduler.effective_free({"index": 0, "free_mb": 10000}, {os.getpid(): 5000})
        == 8000
    )
    r2 = Request(
        "two",
        "job",
        3000,
        asyncio.get_running_loop().create_future(),
        gpu=0,
        pid=os.getpid(),
    )
    scheduler.leases[("two", "job")] = r2
    assert (
        scheduler.effective_free({"index": 0, "free_mb": 10000}, {os.getpid(): 5000})
        == 5000
    )
    scheduler.leases.clear()
    future = asyncio.get_running_loop().create_future()
    scheduler.pending[("new", "job")] = Request("new", "job", 3000, future)
    scheduler.dispatch(
        [
            {"index": 0, "free_mb": 8000, "total_mb": 24000},
            {"index": 1, "free_mb": 4000, "total_mb": 12000},
        ],
        {},
    )
    assert future.result() == 1


async def test_old_large_job_reserves_capable_gpu_after_bounded_backfill():
    scheduler = GpuScheduler(list, dict, limit=4)
    loop = asyncio.get_running_loop()
    old = Request("old", "job", 16000, loop.create_future(), bypasses=3)
    a = Request("small", "job", 3000, loop.create_future())
    scheduler.pending = {("old", "job"): old, ("small", "job"): a}
    scheduler.dispatch([{"index": 0, "free_mb": 9000, "total_mb": 24000}], {})
    assert not a.future.done() and not old.future.done()
    scheduler.dispatch([{"index": 0, "free_mb": 20000, "total_mb": 24000}], {})
    assert old.future.done()


async def test_impossible_job_fails_busy_gpu_waits_and_bad_gpu_is_excluded():
    scheduler = GpuScheduler(list, dict)
    loop = asyncio.get_running_loop()
    impossible = Request("oversize", "job", 30000, loop.create_future())
    busy = Request("waiting", "job", 8000, loop.create_future())
    scheduler.pending = {("oversize", "job"): impossible, ("waiting", "job"): busy}
    scheduler.dispatch([{"index": 0, "free_mb": 1000, "total_mb": 24000}], {})
    assert isinstance(impossible.future.exception(), ValueError)
    assert not busy.future.done()
    scheduler.bad_gpus.add(0)
    scheduler.dispatch([{"index": 0, "free_mb": 24000, "total_mb": 24000}], {})
    assert not busy.future.done()


async def test_equal_capacity_gpu_uses_most_uncommitted_vram_and_waiter_can_move():
    scheduler = GpuScheduler(list, dict, limit=2)
    loop = asyncio.get_running_loop()
    first = Request('first', 'job', 5254, loop.create_future())
    scheduler.pending[('first', 'job')] = first
    gpus = [{'index': index, 'total_mb': 24576, 'free_mb': free}
            for index, free in enumerate([4406, 698, 4951, 3392, 6306, 4744, 6928])]
    scheduler.dispatch(gpus, {})
    assert first.future.result() == 6
    assert scheduler.capacity()[6]['available_mb'] == 1674
    second = Request('second', 'job', 6000, loop.create_future())
    scheduler.pending[('second', 'job')] = second
    scheduler.dispatch(gpus, {})
    assert second.future.result() == 4
    scheduler.release('first', 'job')
    waiting = Request('waiting', 'job', 9000, loop.create_future(), bypasses=3)
    scheduler.pending[('waiting', 'job')] = waiting
    scheduler.dispatch(gpus, {})
    assert not waiting.future.done()
    gpus[2]['free_mb'] = 12000
    scheduler.dispatch(gpus, {})
    assert waiting.future.result() == 2  # no stale preference for previously drained GPU 6


async def test_cancelled_stage_waiter_and_stop_have_no_reservation_leaks(queue):
    waiter = asyncio.create_task(queue.acquire_gpu_stage("waiting", "features", 18000))
    await asyncio.sleep(0.02)
    waiter.cancel()
    await asyncio.gather(waiter, return_exceptions=True)
    assert not queue._gpu.pending and not queue._gpu.leases
    await queue.stop()


async def test_cpu_preparation_is_owned_and_cancellable(queue):
    task = asyncio.create_task(asyncio.Event().wait())
    queue.register_patching_task("patch", task)
    assert queue.is_task_in_queue("patch")
    assert await queue.cancel_task("patch")
    assert task.cancelled() and not queue._gpu.leases


async def test_shutdown_marks_interruption_and_does_not_send_user_cancel_notification(queue):
    from backend.common.queue_lifecycle import is_restart_interruption
    entered = asyncio.Event()
    restarted = []
    async def run(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as error:
            restarted.append(is_restart_interruption(error))
            raise
    await queue.submit('training-restart', TaskType.TRAINING, run, staged=True)
    await entered.wait()
    await queue.stop()
    assert restarted == [True]
    assert not queue.is_task_in_queue('training-restart')


async def test_changing_limit_admits_waiting_job_without_restarting_queue(queue):
    await queue.set_max_concurrent(1)
    first = asyncio.create_task(queue.acquire_gpu_stage("one", "job", 3000))
    assert await asyncio.wait_for(first, 2) == "cuda:0"
    second = asyncio.create_task(queue.acquire_gpu_stage("two", "job", 3000))
    await asyncio.sleep(0.03)
    assert not second.done()
    await queue.set_max_concurrent(2)
    assert await asyncio.wait_for(second, 2) == "cuda:0"
    queue.release_gpu_stage("one", "job")
    queue.release_gpu_stage("two", "job")
    await queue.stop()


@pytest.mark.parametrize('restart', [False, True])
async def test_remote_cancellation_retains_request_until_service_finishes(monkeypatch, restart):
    import httpx

    from gateway import pipeline

    entered, cancel_received, remote_finished = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    async def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json={"pid": os.getpid()})
        entered.set()
        await remote_finished.wait()
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(pipeline.httpx, "AsyncClient", lambda **kwargs: client)

    async def cancel(_, **options):
        assert options == ({'for_restart': True} if restart else {})
        cancel_received.set()

    monkeypatch.setattr(pipeline, "cancel_ai_service_training", cancel)
    task = asyncio.create_task(
        pipeline._call_ai_service(None, "job", "http://localhost/train", {}, "training")
    )
    await entered.wait()
    from backend.common.queue_lifecycle import RESTART_INTERRUPTION
    task.cancel(RESTART_INTERRUPTION) if restart else task.cancel()
    await cancel_received.wait()
    assert not task.done()
    remote_finished.set()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize(
    "status,exception", [("cancelled", asyncio.CancelledError), ("failed", RuntimeError)]
)
async def test_http_success_with_terminal_failure_cannot_continue_pipeline(monkeypatch, status, exception):
    import httpx
    from gateway import pipeline

    async def handle(request):
        return httpx.Response(200, json={} if request.method == "GET" else {
            "status": status, "error_message": "stopped by service"
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(pipeline.httpx, "AsyncClient", lambda **kwargs: client)
    with pytest.raises(exception, match="stopped by service"):
        await pipeline._call_ai_service(None, "job", "http://localhost/train", {}, "training")
