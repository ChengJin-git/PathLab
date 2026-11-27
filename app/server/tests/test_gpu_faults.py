import asyncio
import subprocess
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.autoresearch.engine import jobs
from backend.common import gpu_utils
from task_worker.gpu_scheduler import GpuScheduler, Request

FAULT = "torch.AcceleratorError: CUDA error: an illegal memory access was encountered"


def completed(returncode, stderr=""):
    return SimpleNamespace(returncode=returncode, stderr=stderr)


@pytest.mark.parametrize(
    ("outcome", "healthy"),
    [
        (completed(0), True),
        (completed(2), False),
        (completed(1, FAULT), False),
        (completed(1, "RuntimeError: No CUDA GPUs are available"), True),
        (subprocess.TimeoutExpired("python", 1), False),
    ],
)
def test_stress_probe_counts_only_device_faults(monkeypatch, outcome, healthy):
    def run(command, **kwargs):
        assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "GPU-5"
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(gpu_utils.subprocess, "run", run)
    assert gpu_utils.stress_probe("GPU-5", seconds=0.1) is healthy


def test_probe_all_gpu_health_uses_stress_probe(monkeypatch):
    monkeypatch.setattr(gpu_utils, "mps_available", lambda: False)
    monkeypatch.setattr(gpu_utils.torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(gpu_utils.torch.cuda, "device_count", lambda: 3)
    monkeypatch.setattr(gpu_utils.torch.cuda, "get_device_name", lambda i: f"GPU{i}")
    monkeypatch.setattr(gpu_utils, "is_gpu_healthy", lambda i: i != 1)
    assert gpu_utils.probe_all_gpu_health() == {0: True, 1: False, 2: True}


@pytest.fixture
def fault_env(monkeypatch):
    queue = MagicMock()
    monkeypatch.setattr("task_worker.task_queue.get_task_queue", lambda: queue)
    monkeypatch.setattr(gpu_utils, "sandbox_visible_device", lambda index: f"GPU-{index}")
    row = SimpleNamespace(status="running", payload={"command": ["python", "train.py"]})

    class Db:
        async def get(self, *args, **kwargs):
            return row

        async def commit(self):
            pass

    @asynccontextmanager
    async def session():
        yield Db()

    monkeypatch.setattr(jobs, "safe_session", session)
    monkeypatch.setattr(jobs.store, "job_update", AsyncMock())
    monkeypatch.setattr(jobs.store, "experiment_update", AsyncMock())
    return SimpleNamespace(queue=queue, row=row)


def job(**payload):
    return SimpleNamespace(job_id="research_1", session_id="s1", payload=payload)


def assert_requeued(env, faults):
    env.queue.avoid_gpu.assert_called_once_with("research_1", int(faults[-1].split(":")[-1]))
    assert env.row.payload["device_faults"] == faults
    assert jobs.store.job_update.await_args.args[:2] == ("research_1", "queued")
    jobs.store.experiment_update.assert_awaited_once_with("s1", "research_1", status="queued")


@pytest.mark.asyncio
async def test_gpu_failing_its_probe_is_excluded_and_run_requeued(monkeypatch, fault_env):
    monkeypatch.setattr(gpu_utils, "stress_probe", lambda device: False)

    assert await jobs.handle_device_fault(job(), "cuda:5", FAULT) is None

    fault_env.queue.mark_gpu_bad.assert_called_once_with(5)
    assert_requeued(fault_env, ["cuda:5"])


@pytest.mark.asyncio
async def test_unreproduced_fault_moves_the_run_to_another_gpu(monkeypatch, fault_env):
    monkeypatch.setattr(gpu_utils, "stress_probe", lambda device: True)

    assert await jobs.handle_device_fault(job(), "cuda:5", FAULT) is None

    fault_env.queue.mark_gpu_bad.assert_not_called()
    assert_requeued(fault_env, ["cuda:5"])


@pytest.mark.asyncio
async def test_faults_on_two_healthy_gpus_are_attributed_to_the_run(monkeypatch, fault_env):
    monkeypatch.setattr(gpu_utils, "stress_probe", lambda device: True)

    error = await jobs.handle_device_fault(job(device_faults=["cuda:5"]), "cuda:2", FAULT)

    assert error.startswith(FAULT)
    assert "cuda:5, cuda:2" in error and "CUDA_LAUNCH_BLOCKING=1" in error
    jobs.store.job_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_device_retries_are_bounded(monkeypatch, fault_env):
    monkeypatch.setattr(gpu_utils, "stress_probe", lambda device: False)
    faults = ["cuda:5"] * jobs.MAX_DEVICE_RETRIES

    error = await jobs.handle_device_fault(job(device_faults=faults), "cuda:5", FAULT)

    assert "retries are exhausted" in error
    fault_env.queue.mark_gpu_bad.assert_called_once_with(5)
    jobs.store.job_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_ordinary_errors_skip_the_probe(monkeypatch, fault_env):
    monkeypatch.setattr(gpu_utils, "stress_probe", MagicMock())

    assert await jobs.handle_device_fault(job(), "cuda:2", "ValueError: bad shape") == "ValueError: bad shape"
    gpu_utils.stress_probe.assert_not_called()


def test_completion_elsewhere_convicts_the_gpus_that_faulted(fault_env):
    jobs.confirm_device_faults(job(device_faults=["cuda:5", "cuda:5"]), "cuda:2")
    fault_env.queue.mark_gpu_bad.assert_called_once_with(5)

    fault_env.queue.reset_mock()
    jobs.confirm_device_faults(job(), "cuda:2")
    fault_env.queue.mark_gpu_bad.assert_not_called()


def gpus(*indices):
    return [{"index": i, "total_mb": 24576, "free_mb": 20000} for i in indices]


@pytest.mark.asyncio
@pytest.mark.parametrize(("healthy", "placed"), [((5, 2), 2), ((5,), 5)])
async def test_scheduler_avoids_a_tasks_faulted_gpu_while_another_fits(healthy, placed):
    scheduler = GpuScheduler(list, dict, limit=2)
    scheduler.avoid["research_1"] = {5}
    request = Request("research_1", "job", 1000, asyncio.get_running_loop().create_future())
    scheduler.pending[("research_1", "job")] = request

    scheduler.dispatch(gpus(*healthy), {})

    assert request.future.result() == placed


INIT_FAILURE = (
    "UserWarning: CUDA initialization: CUDA unknown error - this may be due to an "
    "incorrectly set up environment\nRuntimeError: CUDA unavailable"
)


@pytest.mark.asyncio
async def test_machine_wide_cuda_outage_pauses_dispatch_without_counting_a_fault(monkeypatch, fault_env):
    monkeypatch.setattr(gpu_utils, "cuda_initializes", lambda: False)
    monkeypatch.setattr(gpu_utils, "stress_probe", MagicMock())

    assert await jobs.handle_device_fault(job(), "cuda:6", INIT_FAILURE) is None

    fault_env.queue.pause_for_cuda_outage.assert_called_once_with()
    fault_env.queue.avoid_gpu.assert_not_called()
    gpu_utils.stress_probe.assert_not_called()
    assert fault_env.row.payload["device_faults"] == []
    assert jobs.store.job_update.await_args.args[2] == {"device_fault": jobs.CUDA_OUTAGE_NOTICE}


@pytest.mark.asyncio
async def test_cuda_init_failure_on_one_gpu_moves_the_run(monkeypatch, fault_env):
    monkeypatch.setattr(gpu_utils, "cuda_initializes", lambda: True)
    monkeypatch.setattr(gpu_utils, "stress_probe", lambda device: True)

    assert await jobs.handle_device_fault(job(), "cuda:6", INIT_FAILURE) is None

    fault_env.queue.pause_for_cuda_outage.assert_not_called()
    assert_requeued(fault_env, ["cuda:6"])


@pytest.mark.asyncio
async def test_scheduler_holds_dispatch_until_cuda_initializes(monkeypatch):
    from task_worker import gpu_scheduler

    monkeypatch.setattr(gpu_scheduler, "CUDA_OUTAGE_RECHECK_SECONDS", 0.01)
    checks = iter([False, False, True])
    scheduler = GpuScheduler(lambda: gpus(0), dict, interval=0.01, cuda_check=lambda: next(checks))
    scheduler.pause_for_cuda_outage()
    assert next(iter(scheduler.details().values()), None) is None

    acquired = asyncio.create_task(scheduler.acquire("research_1", "job", 1000))
    await asyncio.sleep(0)
    assert scheduler.details()["research_1:job"]["reason"] == "cuda_outage"
    assert await asyncio.wait_for(acquired, 2) == "cuda:0"
    assert scheduler.cuda_outage_since is None
    await scheduler.stop()
