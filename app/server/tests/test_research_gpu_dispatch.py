from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.autoresearch.engine import jobs
from backend.common.task_dispatch import build_task_descriptor
from task_worker import handlers


@pytest.mark.parametrize("device", ["gpu", "cpu"])
async def test_research_gpu_keeps_resource_contract_and_cpu_does_not_acquire_gpu(
    monkeypatch, device
):
    from backend.database import database

    resource = {"operation": "feature_extraction", "model": "conch", "batch_size": 16}
    job = SimpleNamespace(
        kind="computation",
        status="queued",
        payload={"device": device, "resources": resource},
    )

    @asynccontextmanager
    async def db():
        yield SimpleNamespace(get=AsyncMock(return_value=job))

    monkeypatch.setattr(database, "safe_session", db)
    queue = SimpleNamespace(
        is_task_in_queue=lambda _: False,
        submit=AsyncMock(),
        register_patching_task=lambda task_id, task: None,
        deregister_patching_task=lambda _: None,
    )
    monkeypatch.setattr(
        handlers,
        "_task_queue_parts",
        lambda: (
            lambda: queue,
            handlers.import_module("backend.common.task_types").TaskType,
        ),
    )
    run = AsyncMock()
    monkeypatch.setattr(jobs, "run", run)
    await handlers.handle_research(
        build_task_descriptor("r", "research", "research.run", {"task_id": "r"})
    )
    if device == "gpu":
        assert queue.submit.await_args.kwargs["resources"] == resource
        run.assert_not_awaited()
    else:
        import asyncio

        await asyncio.sleep(0)
        run.assert_awaited_once_with(task_id="r")
        queue.submit.assert_not_awaited()


async def test_gpu_resource_contract_rejects_missing_plan_before_snapshot(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        jobs.store,
        "get",
        AsyncMock(
            return_value=SimpleNamespace(
                status="running",
                recovery_metadata={},
                current_iteration=0,
                max_iterations=3,
            )
        ),
    )
    monkeypatch.setattr(jobs.store, "update", AsyncMock())
    with pytest.raises(ValueError, match="GPU jobs require resources"):
        await jobs.submit(
            "s",
            "experiment",
            {"name": "GPU job", "command": ["python", "train.py"], "device": "gpu"},
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("timeout, rejected", [(jobs.DEBUG_RUN_SECONDS, False), (7200, True)])
async def test_debug_only_cuda_serialization_is_limited_to_short_runs(monkeypatch, timeout, rejected):
    session = SimpleNamespace(status="running", recovery_metadata={}, current_iteration=0, max_iterations=3)
    monkeypatch.setattr(jobs.store, "get", AsyncMock(return_value=session))
    monkeypatch.setattr(jobs.store, "update", AsyncMock())
    monkeypatch.setattr("backend.autoresearch.engine.study.experiment_config", lambda _s, config: config)
    staged = AsyncMock(return_value={"job_id": "r"})
    monkeypatch.setattr(jobs, "commit_submission", staged)

    class Source:
        async def __aenter__(self):
            return "snapshot"

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(jobs, "staged_source", lambda *_: Source())
    payload = {"name": "debug", "device": "cpu", "timeout": timeout,
               "command": ["env", "CUDA_LAUNCH_BLOCKING=1", "python", "train.py"]}
    if rejected:
        with pytest.raises(ValueError, match="CUDA_LAUNCH_BLOCKING"):
            await jobs.submit("s", "experiment", payload)
        staged.assert_not_awaited()
    else:
        assert await jobs.submit("s", "experiment", payload) == {"job_id": "r"}
