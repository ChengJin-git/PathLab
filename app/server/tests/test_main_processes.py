"""Process startup and supervision in server/main.py."""
from __future__ import annotations

import multiprocessing
import os
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

        @property
        def exitcode(self):
            return None if self._alive else 1

    monkeypatch.setattr(multiprocessing, "Process", FakeProcess)
    return created


@pytest.fixture(autouse=True)
def patch_env_and_helpers(monkeypatch):
    """Fix ports and GPU detection so main() can run without side effects."""
    monkeypatch.setenv("GATEWAY_PORT", "6100")
    monkeypatch.setenv("PREPROCESSING_PORT", "6101")
    monkeypatch.setenv("AI_PORT", "6102")
    from backend.common.config import Config
    for service in ("GATEWAY", "PREPROCESSING", "AI"):
        name = f"{service}_SERVICE_URL"
        monkeypatch.setattr(Config, name, getattr(Config, name))
        monkeypatch.setenv(name, getattr(Config, name))

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


def test_main_starts_five_processes(fake_process, monkeypatch):
    """HTTP services and both independent background workers are launched."""
    main_module = import_module("main")

    with pytest.raises(SystemExit):
        main_module.main()

    names = [p.name for p in fake_process]
    assert names == ["Preprocessing", "AI", "TaskWorker", "ResearchWorker", "Gateway"]


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


def test_configured_ports_replace_cached_urls_before_child_start(fake_process, monkeypatch):
    main_module = import_module("main")
    monkeypatch.setenv("GATEWAY_PORT", "17100")
    monkeypatch.setenv("PREPROCESSING_PORT", "17101")
    monkeypatch.setenv("AI_PORT", "17102")
    snapshots = []
    process_type = multiprocessing.Process

    def start(self):
        snapshots.append((main_module.Config.AI_SERVICE_URL, main_module.Config.PREPROCESSING_SERVICE_URL,
                          main_module.Config.GATEWAY_SERVICE_URL, os.environ["AI_SERVICE_URL"]))

    monkeypatch.setattr(process_type, "start", start)
    with pytest.raises(SystemExit):
        main_module.main()
    assert snapshots == [("http://127.0.0.1:17102", "http://127.0.0.1:17101",
                           "http://127.0.0.1:17100", "http://127.0.0.1:17102")] * 5


def test_exited_research_worker_restarts_without_disrupting_other_services(fake_process):
    main_module = import_module('main')
    worker = multiprocessing.Process(target=main_module.run_research_worker, name='ResearchWorker')
    gateway = multiprocessing.Process(target=lambda: None, name='Gateway')
    worker.terminate()
    processes = [worker, gateway]
    main_module.restart_failed_workers(processes)
    assert processes[0] is not worker and processes[0].is_alive()
    assert processes[0].target is main_module.run_research_worker
    assert processes[1] is gateway and gateway.is_alive()
