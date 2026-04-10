from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.auth.models import User
from backend.database.models import AIResult, TrainedModel, WSISlide
from backend.storage.migration import MigrationManager


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalarResult(self._rows)


class _FakeSession:
    def __init__(self, rows_by_entity):
        self._rows_by_entity = rows_by_entity
        self.commit_called = False
        self.rollback_called = False

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        return _FakeExecuteResult(self._rows_by_entity.get(entity, []))

    async def commit(self):
        self.commit_called = True

    async def rollback(self):
        self.rollback_called = True


@pytest.mark.asyncio
async def test_update_database_paths_rewrites_all_managed_descendant_fields():
    manager = MigrationManager()
    old_root = "/mnt/storage/uploads"
    new_root = "/mnt/new-storage/uploads"

    wsi = SimpleNamespace(
        wsi_path="/mnt/storage/uploads/wsi_files/case_a.svs",
        associated_files={
            "format_type": "mrxs",
            "data_folder": "/mnt/storage/uploads/wsi_files/case_a",
            "dt_files": [
                "/mnt/storage/uploads/wsi_files/case_a.DT0",
                "/mnt/storage/uploads/wsi_files/case_a.DT1",
            ],
        },
    )
    model = SimpleNamespace(
        model_path="/mnt/storage/uploads/models/model_a.pth",
        config_path="/mnt/storage/uploads/models/model_a.json",
    )
    result = SimpleNamespace(
        extra_metadata={
            "attention_path": "/mnt/storage/uploads/ai_results/task_a_attention.npy",
        }
    )

    user = SimpleNamespace(avatar_path="/mnt/storage/uploads/avatars/user_a.png")

    db = _FakeSession(
        {
            WSISlide: [wsi],
            TrainedModel: [model],
            AIResult: [result],
            User: [user],
        }
    )

    await manager.update_database_paths(db, old_root, new_root)

    assert wsi.wsi_path == "/mnt/new-storage/uploads/wsi_files/case_a.svs"
    assert (
        wsi.associated_files["data_folder"]
        == "/mnt/new-storage/uploads/wsi_files/case_a"
    )
    assert wsi.associated_files["dt_files"] == [
        "/mnt/new-storage/uploads/wsi_files/case_a.DT0",
        "/mnt/new-storage/uploads/wsi_files/case_a.DT1",
    ]
    assert model.model_path == "/mnt/new-storage/uploads/models/model_a.pth"
    assert model.config_path == "/mnt/new-storage/uploads/models/model_a.json"
    assert (
        result.extra_metadata["attention_path"]
        == "/mnt/new-storage/uploads/ai_results/task_a_attention.npy"
    )
    assert user.avatar_path == "/mnt/new-storage/uploads/avatars/user_a.png"
    assert db.commit_called is True
    assert db.rollback_called is False


@pytest.mark.asyncio
async def test_update_database_paths_leaves_external_and_non_descendant_paths_unchanged():
    manager = MigrationManager()
    old_root = "/mnt/storage/uploads"
    new_root = "/mnt/new-storage/uploads"

    wsi = SimpleNamespace(
        wsi_path="/mnt/storage/uploads-archive/wsi_files/case_b.svs",
        associated_files={
            "format_type": "mrxs",
            "data_folder": "/external/wsi/case_b",
            "dt_files": ["/external/wsi/case_b.DT0"],
        },
    )
    model = SimpleNamespace(
        model_path="/external/models/model_b.pth",
        config_path="/mnt/storage/uploads-archive/models/model_b.json",
    )
    result = SimpleNamespace(
        extra_metadata={
            "attention_path": "/external/ai_results/task_b_attention.npy",
        }
    )

    user = SimpleNamespace(avatar_path="avatars/user_b.png")

    db = _FakeSession(
        {
            WSISlide: [wsi],
            TrainedModel: [model],
            AIResult: [result],
            User: [user],
        }
    )

    await manager.update_database_paths(db, old_root, new_root)

    assert wsi.wsi_path == "/mnt/storage/uploads-archive/wsi_files/case_b.svs"
    assert wsi.associated_files == {
        "format_type": "mrxs",
        "data_folder": "/external/wsi/case_b",
        "dt_files": ["/external/wsi/case_b.DT0"],
    }
    assert model.model_path == "/external/models/model_b.pth"
    assert model.config_path == "/mnt/storage/uploads-archive/models/model_b.json"
    assert (
        result.extra_metadata["attention_path"]
        == "/external/ai_results/task_b_attention.npy"
    )
    assert user.avatar_path == "avatars/user_b.png"
    assert db.commit_called is True
    assert db.rollback_called is False


class _NoopTask:
    def cancel(self):
        return False


class _FakeStream:
    def readline(self):
        return ""


class _FakePopen:
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.stdout = _FakeStream()
        self.stderr = _FakeStream()

    def poll(self):
        return 0

    def wait(self):
        return 0

    def communicate(self):
        return "", ""


@pytest.mark.asyncio
async def test_start_migration_preserves_target_file_on_conflict_and_reports_conflict(
    tmp_path, monkeypatch
):
    manager = MigrationManager()
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()

    conflicted_rel = "wsi_files/case_a.svs"
    (source / "wsi_files").mkdir()
    (destination / "wsi_files").mkdir()
    (source / conflicted_rel).write_text("source-version")
    (destination / conflicted_rel).write_text("destination-version")

    captured = {}

    def fake_popen(cmd, **kwargs):
        proc = _FakePopen(cmd, **kwargs)
        captured["cmd"] = cmd
        return proc

    def fake_create_task(coro):
        coro.close()
        return _NoopTask()

    monkeypatch.setattr("backend.storage.migration.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "backend.storage.migration.asyncio.create_task", fake_create_task
    )

    started = await manager.start_migration(
        str(source), str(destination), delete_source=False
    )

    assert started is True
    assert "--ignore-existing" in captured["cmd"]
    assert manager.get_status()["conflicts"] == [conflicted_rel]
    assert (destination / conflicted_rel).read_text() == "destination-version"


def test_cleanup_source_only_runs_when_copy_completed_and_finalization_safe(tmp_path):
    manager = MigrationManager()
    source = tmp_path / "source"
    source.mkdir()
    (source / "payload.txt").write_text("data")

    manager._source = str(source)
    manager._delete_source = True
    manager._status = "completed"
    manager._copy_succeeded = True
    manager._finalization_safe = False

    manager.cleanup_source()

    assert source.exists()

    manager._finalization_safe = True
    manager.cleanup_source()
    assert source.exists() is False


@pytest.mark.parametrize(
    "state",
    [
        {"status": "failed"},
        {"status": "completed", "copy_succeeded": False},
        {"status": "completed", "validation_failed": True},
        {
            "status": "completed",
            "copy_succeeded": True,
            "conflicts": ["wsi_files/a.svs"],
        },
    ],
)
def test_cleanup_source_blocked_when_migration_state_is_unsafe(tmp_path, state):
    manager = MigrationManager()
    source = tmp_path / "source"
    source.mkdir()
    (source / "payload.txt").write_text("data")

    manager._source = str(source)
    manager._delete_source = True
    manager._status = state.get("status", "completed")
    manager._copy_succeeded = state.get("copy_succeeded", True)
    manager._validation_failed = state.get("validation_failed", False)
    manager._finalization_safe = True
    manager._conflicts = state.get("conflicts", [])

    manager.cleanup_source()

    assert source.exists() is True


@pytest.mark.asyncio
async def test_migration_status_completed_finalizes_db_config_and_runtime_manager(
    tmp_path, monkeypatch, admin_user
):
    storage_routes = __import__("gateway.routes.storage", fromlist=["router"])

    calls = {
        "db": [],
        "set_uploads_dir": [],
        "ensure": 0,
        "runtime": [],
        "cleanup": 0,
        "reset": 0,
    }

    class _FakeMigrationManager:
        def get_status(self):
            return {
                "status": "completed",
                "source": str(tmp_path / "old"),
                "destination": str(tmp_path / "new"),
                "delete_source": True,
                "copy_succeeded": True,
                "validation_failed": False,
                "finalization_safe": True,
                "conflicts": [],
                "progress": 100,
                "error": None,
            }

        async def update_database_paths(self, db, source, destination):
            calls["db"].append((db, source, destination))

        def cleanup_source(self):
            calls["cleanup"] += 1

        def reset(self):
            calls["reset"] += 1

    def _fake_set_uploads_dir(path: str):
        calls["set_uploads_dir"].append(path)

    def _fake_ensure_directories():
        calls["ensure"] += 1

    class _FakeStorageManager:
        def set_uploads_dir(self, path: str):
            calls["runtime"].append(path)

    monkeypatch.setattr(storage_routes, "migration_manager", _FakeMigrationManager())
    monkeypatch.setattr(storage_routes.Config, "set_uploads_dir", _fake_set_uploads_dir)
    monkeypatch.setattr(
        storage_routes.Config, "ensure_directories", _fake_ensure_directories
    )
    monkeypatch.setattr(storage_routes, "storage_manager", _FakeStorageManager())

    fake_db = object()
    app = FastAPI()
    app.include_router(storage_routes.router)
    app.dependency_overrides[storage_routes.require_admin] = lambda: admin_user
    app.dependency_overrides[storage_routes.get_db] = lambda: fake_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/storage/migration/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["finalization_applied"] is True
    assert payload["runtime_refreshed"] is True
    assert payload["cleanup_performed"] is True
    assert payload["new_path"] == str(tmp_path / "new")
    assert calls["db"] == [(fake_db, str(tmp_path / "old"), str(tmp_path / "new"))]
    assert calls["set_uploads_dir"] == [str(tmp_path / "new")]
    assert calls["ensure"] == 1
    assert calls["runtime"] == [str(tmp_path / "new")]
    assert calls["cleanup"] == 1
    assert calls["reset"] == 1


@pytest.mark.asyncio
async def test_migration_status_reports_finalization_failure_without_source_cleanup(
    tmp_path, monkeypatch, admin_user
):
    storage_routes = __import__("gateway.routes.storage", fromlist=["router"])

    calls = {
        "cleanup": 0,
        "set_uploads_dir": 0,
        "ensure": 0,
        "runtime": 0,
        "reset": 0,
    }

    class _FakeMigrationManager:
        def get_status(self):
            return {
                "status": "completed",
                "source": str(tmp_path / "old"),
                "destination": str(tmp_path / "new"),
                "delete_source": True,
                "copy_succeeded": True,
                "validation_failed": False,
                "finalization_safe": True,
                "conflicts": [],
                "progress": 100,
                "error": None,
            }

        async def update_database_paths(self, db, source, destination):
            raise RuntimeError("db update blew up")

        def cleanup_source(self):
            calls["cleanup"] += 1

        def reset(self):
            calls["reset"] += 1

    monkeypatch.setattr(storage_routes, "migration_manager", _FakeMigrationManager())
    monkeypatch.setattr(
        storage_routes.Config,
        "set_uploads_dir",
        lambda path: calls.__setitem__("set_uploads_dir", calls["set_uploads_dir"] + 1),
    )
    monkeypatch.setattr(
        storage_routes.Config,
        "ensure_directories",
        lambda: calls.__setitem__("ensure", calls["ensure"] + 1),
    )

    class _FakeStorageManager:
        def set_uploads_dir(self, path: str):
            calls["runtime"] += 1

    monkeypatch.setattr(storage_routes, "storage_manager", _FakeStorageManager())

    app = FastAPI()
    app.include_router(storage_routes.router)
    app.dependency_overrides[storage_routes.require_admin] = lambda: admin_user
    app.dependency_overrides[storage_routes.get_db] = lambda: object()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/storage/migration/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["source_cleanup_performed"] is False
    assert payload["finalization_applied"] is False
    assert payload["runtime_refreshed"] is False
    assert "db update blew up" in payload["error"]
    assert calls["cleanup"] == 0
    assert calls["set_uploads_dir"] == 0
    assert calls["ensure"] == 0
    assert calls["runtime"] == 0
    assert calls["reset"] == 0
