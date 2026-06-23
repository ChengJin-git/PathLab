import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def fresh_queue():
    """Create a fresh TaskQueueManager (reset singleton state)."""
    from gateway.task_queue import TaskQueueManager

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
