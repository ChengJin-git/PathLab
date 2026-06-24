from __future__ import annotations

import contextlib
import os
import sys
import types
from pathlib import Path

import pytest

from pathlab_paper_agent.integrations import task_worker


class _FakeDB:
    def __init__(self, events: list[tuple]) -> None:
        self._events = events

    async def commit(self) -> None:
        self._events.append(("commit",))


class _FakeSession:
    def __init__(self, events: list[tuple]) -> None:
        self._db = _FakeDB(events)

    async def __aenter__(self) -> _FakeDB:
        return self._db

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeRepo:
    events: list[tuple] = []

    @classmethod
    async def mark_started(cls, db, paper_id: str) -> None:
        cls.events.append(("mark_started", paper_id))

    @classmethod
    async def update_stage(cls, db, paper_id: str, stage: str, *, status: str) -> None:
        cls.events.append(("update_stage", paper_id, stage, status))

    @classmethod
    async def mark_completed(cls, db, paper_id: str) -> None:
        cls.events.append(("mark_completed", paper_id))

    @classmethod
    async def mark_failed(cls, db, paper_id: str, message: str) -> None:
        cls.events.append(("mark_failed", paper_id, message))

    @classmethod
    async def update(
        cls,
        db,
        paper_id: str,
        *,
        status: str,
        current_stage: str,
        error_message,
        finished_at,
    ) -> None:
        cls.events.append(("update", paper_id, status, current_stage, error_message, finished_at))


@contextlib.contextmanager
def _fake_backend(events: list[tuple], uploads_dir: Path):
    previous = {name: sys.modules.get(name) for name in _BACKEND_MODULES}

    backend = types.ModuleType("backend")
    backend_common = types.ModuleType("backend.common")
    backend_common_config = types.ModuleType("backend.common.config")
    backend_database = types.ModuleType("backend.database")
    backend_database_repositories = types.ModuleType("backend.database.repositories")
    backend_database_paper_generation = types.ModuleType(
        "backend.database.repositories.paper_generation"
    )

    class FakeConfig:
        @classmethod
        def get_uploads_dir(cls) -> Path:
            return uploads_dir

    backend_common_config.Config = FakeConfig
    backend_database.safe_session = lambda: _FakeSession(events)
    backend_database_paper_generation.PaperGenerationRunRepository = _FakeRepo

    sys.modules.update(
        {
            "backend": backend,
            "backend.common": backend_common,
            "backend.common.config": backend_common_config,
            "backend.database": backend_database,
            "backend.database.repositories": backend_database_repositories,
            "backend.database.repositories.paper_generation": backend_database_paper_generation,
        }
    )
    try:
        yield
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


_BACKEND_MODULES = (
    "backend",
    "backend.common",
    "backend.common.config",
    "backend.database",
    "backend.database.repositories",
    "backend.database.repositories.paper_generation",
)


class _FakeProcess:
    def __init__(self, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_run_paper_generation_uses_subprocess_helper(tmp_path, monkeypatch):
    events: list[tuple] = []
    _FakeRepo.events = events
    calls: list[dict[str, object]] = []

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        calls.append({"cmd": cmd, "kwargs": kwargs})
        return _FakeProcess()

    monkeypatch.setattr(task_worker.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with _fake_backend(events, tmp_path):
        await task_worker.run_paper_generation("paper_full")

    assert events == [
        ("mark_started", "paper_full"),
        ("update_stage", "paper_full", "created", "running"),
        ("commit",),
        ("mark_completed", "paper_full"),
        ("commit",),
    ]
    cmd = calls[0]["cmd"]
    assert cmd[0:3] == (
        sys.executable,
        "-m",
        "pathlab_paper_agent.cli",
    )
    assert "run" in cmd
    assert "--paper-id" in cmd
    assert "paper_full" in cmd
    assert "--uploads-dir" in cmd
    assert str(tmp_path.resolve()) in cmd
    assert "--config" in cmd
    assert str(tmp_path.resolve() / "paper_generation" / "paper_full" / "config.json") in cmd
    env = calls[0]["kwargs"]["env"]
    assert env["PATHLAB_PAPER_AGENT_NO_APPROVAL_GATE"] == "1"
    pythonpath_entries = env["PYTHONPATH"].split(os.pathsep)
    assert str(task_worker.server_root()) in pythonpath_entries
    assert str(task_worker.server_root() / "paper_agent" / "src") in pythonpath_entries


@pytest.mark.asyncio
async def test_run_paper_generation_records_subprocess_failure(tmp_path, monkeypatch):
    events: list[tuple] = []
    _FakeRepo.events = events

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return _FakeProcess(returncode=7, stdout=b"out", stderr=b"err")

    monkeypatch.setattr(task_worker.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with _fake_backend(events, tmp_path):
        with pytest.raises(RuntimeError, match="paper agent subprocess failed with exit 7"):
            await task_worker.run_paper_generation("paper_fail")

    assert events[0:3] == [
        ("mark_started", "paper_fail"),
        ("update_stage", "paper_fail", "created", "running"),
        ("commit",),
    ]
    assert events[3][0:2] == ("mark_failed", "paper_fail")
    assert "STDOUT:\nout" in events[3][2]
    assert "STDERR:\nerr" in events[3][2]
    assert events[4] == ("commit",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fn_name", "command", "start_stage", "success_event"),
    [
        (
            "run_until_outline",
            "run-until-outline",
            "collecting",
            ("update", "paper_split", "awaiting_outline_approval", "outlining", None, None),
        ),
        ("run_after_outline", "run-after-outline", "plotting", ("mark_completed", "paper_split")),
        ("run_render_export", "render-export", "rendering", ("mark_completed", "paper_split")),
    ],
)
async def test_split_jobs_use_subprocess_and_update_success_status(
    fn_name,
    command,
    start_stage,
    success_event,
    tmp_path,
    monkeypatch,
):
    events: list[tuple] = []
    _FakeRepo.events = events
    calls: list[dict[str, object]] = []

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        calls.append({"cmd": cmd, "kwargs": kwargs})
        return _FakeProcess()

    async def fail_to_thread(*args, **kwargs):
        raise AssertionError("split paper jobs must not use asyncio.to_thread")

    monkeypatch.setattr(task_worker.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(task_worker.asyncio, "to_thread", fail_to_thread)

    with _fake_backend(events, tmp_path):
        await getattr(task_worker, fn_name)("paper_split")

    assert events == [
        ("mark_started", "paper_split"),
        ("update_stage", "paper_split", start_stage, "running"),
        ("commit",),
        success_event,
        ("commit",),
    ]
    cmd = calls[0]["cmd"]
    assert command in cmd
    assert "paper_split" in cmd
    assert str(tmp_path.resolve()) in cmd
    assert str(tmp_path.resolve() / "paper_generation" / "paper_split" / "config.json") in cmd
    env = calls[0]["kwargs"]["env"]
    assert "PATHLAB_PAPER_AGENT_NO_APPROVAL_GATE" not in env


@pytest.mark.asyncio
async def test_split_job_records_subprocess_failure(tmp_path, monkeypatch):
    events: list[tuple] = []
    _FakeRepo.events = events

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return _FakeProcess(returncode=9, stdout=b"split out", stderr=b"split err")

    monkeypatch.setattr(task_worker.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with _fake_backend(events, tmp_path):
        with pytest.raises(RuntimeError, match="paper agent subprocess failed with exit 9"):
            await task_worker.run_until_outline("paper_split_fail")

    assert events[0:3] == [
        ("mark_started", "paper_split_fail"),
        ("update_stage", "paper_split_fail", "collecting", "running"),
        ("commit",),
    ]
    assert events[3][0:2] == ("mark_failed", "paper_split_fail")
    assert "STDOUT:\nsplit out" in events[3][2]
    assert "STDERR:\nsplit err" in events[3][2]
    assert events[4] == ("commit",)
