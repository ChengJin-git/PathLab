import asyncio
from importlib import import_module
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _task_queue_module():
    return import_module("gateway.task_queue")


@pytest.fixture
def fresh_queue():
    """Create a fresh TaskQueueManager (reset singleton state)."""
    TaskQueueManager = _task_queue_module().TaskQueueManager

    TaskQueueManager._instance = None
    TaskQueueManager._initialized = False
    queue = TaskQueueManager(max_concurrent=2, gpu_count=2)
    return queue


@pytest.mark.asyncio
async def test_register_and_cancel_patching_task(fresh_queue):
    """cancel_task cancels a registered pre-queue patching task."""
    queue = fresh_queue
    queue._condition = asyncio.Condition()
    queue._vram_condition = asyncio.Condition()

    async def _forever():
        while True:
            await asyncio.sleep(1)

    task = asyncio.create_task(_forever())
    queue.register_patching_task("task_abc", task)

    assert queue.is_task_in_queue("task_abc")

    cancelled = await queue.cancel_task("task_abc")

    assert cancelled is True
    assert "task_abc" not in queue._patching_tasks
    await asyncio.sleep(0)
    assert task.cancelled()


@pytest.mark.asyncio
async def test_is_task_in_queue_includes_patching(fresh_queue):
    """is_task_in_queue returns True for pre-queue patching tasks."""
    queue = fresh_queue
    mock_task = MagicMock()
    queue.register_patching_task("task_xyz", mock_task)

    assert queue.is_task_in_queue("task_xyz") is True
    assert queue.is_task_in_queue("unknown_task") is False


@pytest.mark.asyncio
async def test_get_status_includes_patching_count(fresh_queue):
    """get_status includes patching_count and patching_task_ids."""
    queue = fresh_queue
    mock_task = MagicMock()
    queue.register_patching_task("task_patching", mock_task)

    with (
        patch("backend.common.gpu_utils.get_all_gpu_info", return_value=[]),
        patch(
            "backend.common.gpu_utils.check_vram_available",
            return_value=(True, 8000.0, "ok"),
        ),
    ):
        status = queue.get_status()

    assert status["patching_count"] == 1
    assert "task_patching" in status["patching_task_ids"]


def test_deregister_patching_task(fresh_queue):
    """deregister_patching_task removes task and is idempotent."""
    queue = fresh_queue
    mock_task = MagicMock()
    queue.register_patching_task("task_dereg", mock_task)
    assert "task_dereg" in queue._patching_tasks

    queue.deregister_patching_task("task_dereg")
    assert "task_dereg" not in queue._patching_tasks

    queue.deregister_patching_task("task_dereg")


@pytest.mark.asyncio
async def test_soft_vram_reservation_uses_task_budget_until_release(
    fresh_queue, monkeypatch
):
    """Startup reservations stay active and use task VRAM budget, not all free VRAM."""
    task_queue = _task_queue_module()
    QueuedTask = task_queue.QueuedTask
    TaskType = task_queue.TaskType

    queue = fresh_queue
    queue.min_vram_mb = 2000.0
    queue._vram_condition = asyncio.Condition()
    now = 1000.0
    monkeypatch.setattr("gateway.task_queue.time.monotonic", lambda: now)

    queue._pending_tasks["task_a"] = QueuedTask(
        task_id="task_a",
        task_type=TaskType.TRAINING,
        coro_func=AsyncMock(),
        kwargs={
            "task_id": "task_a",
            "data_type": "patch",
            "preprocessing_config": {"feature_extractor": "virchow2"},
            "model_config": {"batch_size": 64},
        },
    )

    with patch(
        "backend.common.gpu_utils.get_all_gpu_info",
        return_value=[
            {
                "index": 0,
                "name": "gpu0",
                "allocated_mb": 0.0,
                "free_mb": 60000.0,
                "total_mb": 80000.0,
            },
            {
                "index": 1,
                "name": "gpu1",
                "allocated_mb": 0.0,
                "free_mb": 12000.0,
                "total_mb": 24000.0,
            },
        ],
    ):
        assigned_gpu = await queue._wait_for_any_gpu("task_a")

    now = 1000.0 + 601.0

    assert assigned_gpu == 0
    assert queue._get_soft_reserved_mb(0) == pytest.approx(52652.0)


@pytest.mark.asyncio
async def test_wait_for_any_gpu_waits_for_estimated_task_vram(fresh_queue):
    """A GPU above the global minimum but below task budget is not admitted."""
    task_queue = _task_queue_module()
    QueuedTask = task_queue.QueuedTask
    TaskType = task_queue.TaskType

    queue = fresh_queue
    queue.min_vram_mb = 2000.0
    queue.vram_check_interval = 0.001
    queue._vram_condition = asyncio.Condition()
    queue._pending_tasks["task_a"] = QueuedTask(
        task_id="task_a",
        task_type=TaskType.TRAINING,
        coro_func=AsyncMock(),
        kwargs={
            "task_id": "task_a",
            "data_type": "patch",
            "preprocessing_config": {"feature_extractor": "virchow2"},
            "model_config": {"batch_size": 64},
        },
    )
    gpu_snapshots = [
        [
            {
                "index": 0,
                "name": "gpu0",
                "allocated_mb": 18000.0,
                "free_mb": 6000.0,
                "total_mb": 24000.0,
            }
        ],
        [
            {
                "index": 0,
                "name": "gpu0",
                "allocated_mb": 4000.0,
                "free_mb": 60000.0,
                "total_mb": 80000.0,
            }
        ],
    ]

    with patch(
        "backend.common.gpu_utils.get_all_gpu_info",
        side_effect=gpu_snapshots,
    ) as get_gpu_info:
        assigned_gpu = await queue._wait_for_any_gpu("task_a")

    assert assigned_gpu == 0
    assert get_gpu_info.call_count == 2


@pytest.mark.asyncio
async def test_acquire_gpu_stage_reselects_global_gpu_between_wsi_stages(fresh_queue):
    """Each WSI GPU stage gets a fresh global GPU selection."""
    queue = fresh_queue
    queue.min_vram_mb = 2000.0
    queue.vram_check_interval = 0.001
    queue._vram_condition = asyncio.Condition()
    gpu_snapshots = [
        [
            {
                "index": 0,
                "name": "gpu0",
                "allocated_mb": 12000.0,
                "free_mb": 12000.0,
                "total_mb": 24000.0,
            },
            {
                "index": 1,
                "name": "gpu1",
                "allocated_mb": 18000.0,
                "free_mb": 6000.0,
                "total_mb": 24000.0,
            },
        ],
        [
            {
                "index": 0,
                "name": "gpu0",
                "allocated_mb": 22000.0,
                "free_mb": 2000.0,
                "total_mb": 24000.0,
            },
            {
                "index": 1,
                "name": "gpu1",
                "allocated_mb": 10000.0,
                "free_mb": 14000.0,
                "total_mb": 24000.0,
            },
        ],
    ]

    with patch(
        "backend.common.gpu_utils.get_all_gpu_info",
        side_effect=gpu_snapshots,
    ):
        feature_device = await queue.acquire_gpu_stage(
            task_id="task_wsi",
            stage="feature_extraction",
            required_vram_mb=6500.0,
        )
        queue.release_gpu_stage("task_wsi", "feature_extraction")
        training_device = await queue.acquire_gpu_stage(
            task_id="task_wsi",
            stage="wsi_training",
            required_vram_mb=6500.0,
        )

    assert feature_device == "cuda:0"
    assert training_device == "cuda:1"


@pytest.mark.asyncio
async def test_acquire_gpu_stage_replaces_startup_reservation(fresh_queue):
    """Stage reservations should supersede the task startup reservation."""
    task_queue = _task_queue_module()
    QueuedTask = task_queue.QueuedTask
    TaskType = task_queue.TaskType

    queue = fresh_queue
    queue.min_vram_mb = 2000.0
    queue._vram_condition = asyncio.Condition()
    queue._pending_tasks["task_a"] = QueuedTask(
        task_id="task_a",
        task_type=TaskType.TRAINING,
        coro_func=AsyncMock(),
        kwargs={
            "task_id": "task_a",
            "data_type": "patch",
            "preprocessing_config": {"feature_extractor": "virchow2"},
            "model_config": {"batch_size": 64},
        },
    )

    with patch(
        "backend.common.gpu_utils.get_all_gpu_info",
        return_value=[
            {
                "index": 0,
                "name": "gpu0",
                "allocated_mb": 0.0,
                "free_mb": 60000.0,
                "total_mb": 80000.0,
            }
        ],
    ):
        assigned_gpu = await queue._wait_for_any_gpu("task_a")
        stage_device = await queue.acquire_gpu_stage(
            task_id="task_a",
            stage="patch_classification",
            required_vram_mb=6500.0,
        )

    assert assigned_gpu == 0
    assert stage_device == "cuda:0"
    assert queue._get_soft_reserved_mb(0) == pytest.approx(6500.0)


@pytest.mark.asyncio
async def test_acquire_gpu_stage_cleans_waiting_detail_on_cancellation(fresh_queue):
    """Cancelled stage waits should not leave stale waiting details behind."""
    queue = fresh_queue
    queue.min_vram_mb = 2000.0
    queue.vram_check_interval = 0.01
    queue._vram_condition = asyncio.Condition()

    with patch(
        "backend.common.gpu_utils.get_all_gpu_info",
        return_value=[
            {
                "index": 0,
                "name": "gpu0",
                "allocated_mb": 22000.0,
                "free_mb": 2000.0,
                "total_mb": 24000.0,
            }
        ],
    ):
        waiter = asyncio.create_task(
            queue.acquire_gpu_stage(
                task_id="task_waiting",
                stage="wsi_training",
                required_vram_mb=6500.0,
            )
        )
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

    assert "task_waiting:wsi_training" not in queue._gpu_stage_details
    assert queue._soft_vram_reservations == {}


@pytest.mark.asyncio
async def test_feature_extraction_stage_waits_for_conservative_batch_vram(fresh_queue):
    """Feature extraction should wait when the configured batch cannot fit yet."""
    queue = fresh_queue
    queue.vram_check_interval = 0.001
    queue._vram_condition = asyncio.Condition()
    required_vram_mb = import_module("gateway.pipeline")._estimate_stage_vram_mb(
        "conch", 64
    )

    gpu_snapshots = [
        [
            {
                "index": 0,
                "name": "gpu0",
                "allocated_mb": 8600.0,
                "free_mb": 15524.0,
                "total_mb": 24124.0,
            }
        ],
        [
            {
                "index": 0,
                "name": "gpu0",
                "allocated_mb": 4000.0,
                "free_mb": 60000.0,
                "total_mb": 80000.0,
            }
        ],
    ]

    with patch(
        "backend.common.gpu_utils.get_all_gpu_info",
        side_effect=gpu_snapshots,
    ) as get_gpu_info:
        device = await queue.acquire_gpu_stage(
            task_id="task_batch_wait",
            stage="feature_extraction",
            required_vram_mb=required_vram_mb,
        )

    assert required_vram_mb > 15524.0
    assert device == "cuda:0"
    assert get_gpu_info.call_count == 2
