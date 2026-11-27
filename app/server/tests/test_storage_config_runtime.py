import importlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def test_get_uploads_dir_uses_updated_setting_without_module_reimport(
    tmp_path, monkeypatch
):
    from backend.common.config import Config

    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    monkeypatch.setattr(Config, "STORAGE_CONFIG_FILE", str(tmp_path / "storage.json"))
    monkeypatch.delenv("PATHLAB_UPLOADS_DIR", raising=False)

    Config.set_uploads_dir(str(first_dir))
    assert Config.get_uploads_dir() == first_dir.resolve()

    Config.set_uploads_dir(str(second_dir))
    assert Config.get_uploads_dir() == second_dir.resolve()

def test_storage_manager_refresh_is_explicit_and_preserves_other_instances(
    tmp_path, monkeypatch
):
    from backend.common.config import Config

    first_dir = tmp_path / "first-storage"
    second_dir = tmp_path / "second-storage"

    monkeypatch.setattr(Config, "STORAGE_CONFIG_FILE", str(tmp_path / "storage.json"))
    monkeypatch.delenv("PATHLAB_UPLOADS_DIR", raising=False)

    from backend.storage.manager import StorageManager

    Config.set_uploads_dir(str(first_dir))
    manager = StorageManager(str(Config.get_uploads_dir()))
    assert manager.uploads_dir == first_dir.resolve()

    Config.set_uploads_dir(str(second_dir))
    assert manager.uploads_dir == first_dir.resolve()
    manager.set_uploads_dir(str(Config.get_uploads_dir()))
    assert manager.uploads_dir == second_dir.resolve()


@pytest.mark.asyncio
async def test_ai_training_route_uses_current_uploads_root_after_runtime_change(
    tmp_path, monkeypatch
):
    from backend.common.config import Config
    from backend.ai.schemas.requests import FeatureExtractionRequest

    first_dir = tmp_path / "first-ai-root"
    second_dir = tmp_path / "second-ai-root"

    monkeypatch.setattr(Config, "STORAGE_CONFIG_FILE", str(tmp_path / "storage.json"))
    monkeypatch.delenv("PATHLAB_UPLOADS_DIR", raising=False)

    Config.set_uploads_dir(str(first_dir))
    training_routes = importlib.import_module("backend.ai.routes.training")
    Config.set_uploads_dir(str(second_dir))

    observed_uploads_root = {}

    class _DummyTrainingLogger:
        async def info(self, *args, **kwargs):
            return None

        async def error(self, *args, **kwargs):
            return None

    class _DummySession:
        async def __aenter__(self):
            return (_DummyTrainingLogger(), object())

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _DummyScopedSession:
        def __init__(self, task_id):
            self.task_id = task_id

        def session(self):
            return _DummySession()

        def get_session_maker(self):
            return lambda: None

    class _DummyScopedLogger:
        def __init__(self, task_id):
            self.task_id = task_id

        async def info(self, *args, **kwargs):
            return None

        async def close(self):
            return None

    class _DummyResult:
        def model_dump(self):
            return {"status": "ok", "results": []}

    class _DummyTrainer:
        def __init__(self, task_id, uploads_root, device):
            observed_uploads_root["value"] = uploads_root

        async def extract_features(self, **kwargs):
            return _DummyResult()

    async def _mock_get_by_id(db, task_id):
        return SimpleNamespace(preprocessing_config={})

    async def _mock_update_status(db, task_id, status, progress=None):
        return None

    monkeypatch.setattr(training_routes, "ScopedSession", _DummyScopedSession)
    monkeypatch.setattr(training_routes, "ScopedTrainingLogger", _DummyScopedLogger)
    monkeypatch.setattr(
        training_routes.TrainingTaskRepository, "get_by_id", _mock_get_by_id
    )
    monkeypatch.setattr(
        training_routes.TrainingTaskRepository, "update_status", _mock_update_status
    )
    monkeypatch.setattr(training_routes, "WSIClassificationTrainer", _DummyTrainer)
    monkeypatch.setattr(training_routes, "cleanup_gpu_memory", lambda: None)

    req = FeatureExtractionRequest(task_id="task_rt_root", wsi_ids=["wsi_1"])
    await training_routes.extract_features(req)

    assert observed_uploads_root["value"] == second_dir.resolve()


@pytest.mark.asyncio
async def test_storage_config_route_updates_runtime_manager_and_reports_restart_semantics(
    tmp_path, monkeypatch, admin_user
):
    storage_routes = importlib.import_module("gateway.routes.storage")

    updated_dirs = []
    ensured = {"called": False}

    def _fake_set_uploads_dir(path: str):
        updated_dirs.append(path)
        return (tmp_path / "runtime-updated").resolve()

    def _fake_ensure_directories():
        ensured["called"] = True

    class _FakeStorageManager:
        def __init__(self):
            self.paths = []

        def set_uploads_dir(self, path: str):
            self.paths.append(path)

    fake_storage_manager = _FakeStorageManager()

    monkeypatch.setattr(storage_routes.Config, "set_uploads_dir", _fake_set_uploads_dir)
    monkeypatch.setattr(
        storage_routes.Config, "ensure_directories", _fake_ensure_directories
    )
    monkeypatch.setattr(storage_routes, "storage_manager", fake_storage_manager)

    app = FastAPI()
    app.include_router(storage_routes.router)
    app.dependency_overrides[storage_routes.require_admin] = lambda: admin_user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/storage/config", json={"uploads_dir": str(tmp_path / "target")}
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["restart_required"] is True
    assert payload["runtime_refreshed"] is True
    assert updated_dirs == [str(tmp_path / "target")]
    assert ensured["called"] is True
    assert fake_storage_manager.paths == [str((tmp_path / "runtime-updated").resolve())]
