"""Tests for TaskWorker startup from sidecar main process."""
from __future__ import annotations

import multiprocessing
from importlib import import_module

import pytest


@pytest.fixture
def fake_process(monkeypatch):
    """Monkeypatch multiprocessing.Process with a fake class that records args."""
    created = []

    class FakeProcess:
        def __init__(self, target, name=None, args=(), kwargs=None, daemon=None):
            self.target = target
            self.name = name
            self.args = args
            self.kwargs = kwargs or {}
            self.daemon = daemon
            self._alive = True
            created.append(self)

        def start(self):
            pass

        def is_alive(self):
            return self._alive

        def terminate(self):
            self._alive = False

        def join(self, timeout=None):
            pass

        def kill(self):
            self._alive = False

        @property
        def pid(self):
            return 12345

    monkeypatch.setattr(multiprocessing, "Process", FakeProcess)
    return created


@pytest.fixture(autouse=True)
def patch_env_and_helpers(monkeypatch):
    """Patch port discovery and GPU detection so main() can run without side effects."""
    monkeypatch.setenv("PATHLAB_DEBUG", "1")
    monkeypatch.setenv("GATEWAY_PORT", "6100")
    monkeypatch.setenv("PREPROCESSING_PORT", "6101")
    monkeypatch.setenv("AI_PORT", "6102")

    monkeypatch.setattr(
        "main.find_free_port", lambda: 6103
    )
    monkeypatch.setattr(
        "main.announce_port", lambda port, name: None
    )
    monkeypatch.setattr(
        "main._detect_and_exclude_bad_gpus", lambda: []
    )

    # Prevent the main loop from blocking forever by raising after first sleep.
    call_count = 0

    def fake_sleep(seconds):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise SystemExit(0)

    monkeypatch.setattr("time.sleep", fake_sleep)

    # Patch signal/atexit so they don't interfere with test process.
    monkeypatch.setattr("signal.signal", lambda *args: None)
    monkeypatch.setattr("atexit.register", lambda *args, **kwargs: None)


def test_main_starts_four_processes(fake_process, monkeypatch):
    """Assert main() starts Preprocessing, AI, TaskWorker, and Gateway."""
    main_module = import_module("main")

    with pytest.raises(SystemExit):
        main_module.main()

    names = [p.name for p in fake_process]
    assert names == ["Preprocessing", "AI", "TaskWorker", "Gateway"]


def test_task_worker_target_is_run_task_worker(fake_process, monkeypatch):
    """Assert TaskWorker process uses run_task_worker target (not run_service)."""
    main_module = import_module("main")

    with pytest.raises(SystemExit):
        main_module.main()

    task_worker_proc = [p for p in fake_process if p.name == "TaskWorker"][0]
    assert task_worker_proc.target.__name__ == "run_task_worker"
    assert task_worker_proc.args == ()


def test_task_worker_has_no_port_or_uvicorn(fake_process, monkeypatch):
    """Assert TaskWorker process does not receive a port or use uvicorn."""
    main_module = import_module("main")

    with pytest.raises(SystemExit):
        main_module.main()

    task_worker_proc = [p for p in fake_process if p.name == "TaskWorker"][0]
    # run_service signature: (app_module, port, name, workers=1, limit_max_requests=None)
    # run_task_worker signature: ()
    assert task_worker_proc.target.__name__ != "run_service"
    assert task_worker_proc.args == ()


def test_cleanup_includes_task_worker(fake_process, monkeypatch):
    """Assert TaskWorker is appended to processes and receives terminate on cleanup."""
    main_module = import_module("main")

    with pytest.raises(SystemExit):
        main_module.main()

    task_worker_proc = [p for p in fake_process if p.name == "TaskWorker"][0]
    assert task_worker_proc in fake_process
    assert not task_worker_proc.is_alive()
