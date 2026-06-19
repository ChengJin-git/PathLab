import importlib.util
import asyncio
import io
import json
import os
import sys
import tempfile
import time
import types
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jose import jwt


ROUTE_PATH = Path(__file__).resolve().parents[1] / "gateway" / "routes" / "pathscientist.py"
SERVER_ROOT = Path(__file__).resolve().parents[1]


async def _not_implemented_repository_method(*args, **kwargs):
    raise NotImplementedError


class _DataGroupRepositoryStub:
    get_or_create = staticmethod(_not_implemented_repository_method)


class _DatasetRepositoryStub:
    get_by_name = staticmethod(_not_implemented_repository_method)
    get_or_create = staticmethod(_not_implemented_repository_method)


class _DatasetStatsRepositoryStub:
    recompute = staticmethod(_not_implemented_repository_method)


class _WSIRepositoryStub:
    bulk_update_feature_extracted = staticmethod(_not_implemented_repository_method)
    get_by_id = staticmethod(_not_implemented_repository_method)
    create = staticmethod(_not_implemented_repository_method)


def install_lightweight_auto_research_import():
    package = types.ModuleType("backend.database.repositories")
    package.__path__ = [str(SERVER_ROOT / "backend" / "database" / "repositories")]
    package.DataGroupRepository = _DataGroupRepositoryStub
    package.DatasetRepository = _DatasetRepositoryStub
    package.DatasetStatsRepository = _DatasetStatsRepositoryStub
    package.WSIRepository = _WSIRepositoryStub
    sys.modules["backend.database.repositories"] = package

    dataset_stats = types.ModuleType("backend.database.repositories.dataset_stats")
    dataset_stats.DatasetStatsRepository = _DatasetStatsRepositoryStub
    sys.modules["backend.database.repositories.dataset_stats"] = dataset_stats

    module_name = "backend.database.repositories.auto_research"
    spec = importlib.util.spec_from_file_location(
        module_name,
        SERVER_ROOT / "backend" / "database" / "repositories" / "auto_research.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    package.AutoResearchRepository = module.AutoResearchRepository
    return module.AutoResearchRepository


def load_route_module():
    install_lightweight_auto_research_import()
    spec = importlib.util.spec_from_file_location("pathscientist_route_under_test", ROUTE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.pathscientist_persistence.persist_session_created = lambda **kwargs: None
    module.pathscientist_persistence.persist_event = lambda **kwargs: None
    module.pathscientist_persistence.persist_session_state = lambda **kwargs: None
    module.pathscientist_persistence.delete_session = lambda session_id: None
    module._DB_HISTORY_ENABLED = False
    return module


def install_fake_user(
    app: FastAPI,
    route_module,
    user_id: str = "user-test",
    *,
    override_pathscientist_access_token: bool = True,
):
    fake_user = lambda: SimpleNamespace(id=user_id)
    app.dependency_overrides[route_module.current_active_user] = fake_user
    app.dependency_overrides[route_module.get_user_from_header_or_param] = fake_user
    app.dependency_overrides[route_module.get_user_from_token_param] = fake_user
    if override_pathscientist_access_token and hasattr(
        route_module,
        "get_pathscientist_access_token_claims",
    ):
        app.dependency_overrides[route_module.get_pathscientist_access_token_claims] = (
            lambda: {
                "user": SimpleNamespace(id=user_id),
                "purpose": "header",
                "sid": "",
                "rid": "",
            }
        )
    if override_pathscientist_access_token and hasattr(
        route_module,
        "get_pathscientist_header_or_access_token_claims",
    ):
        app.dependency_overrides[
            route_module.get_pathscientist_header_or_access_token_claims
        ] = (
            lambda: {
                "user": SimpleNamespace(id=user_id),
                "purpose": "header",
                "sid": "",
                "rid": "",
            }
        )


def disable_persistence(route_module):
    route_module.pathscientist_persistence.persist_session_created = lambda **kwargs: None
    route_module.pathscientist_persistence.persist_event = lambda **kwargs: None
    route_module.pathscientist_persistence.persist_session_state = lambda **kwargs: None
    route_module.pathscientist_persistence.delete_session = lambda session_id: None


def make_app():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._queue_session_title_generation = lambda record, config: None
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []
    manager = route_module.PathScientistSessionManager()

    def fake_runner(config, question, emit):
        emit({"kind": "stage_enter", "stage": "grounding"})
        return {
            "session_id": "session_fake",
            "conversation_id": "conv_fake",
            "stage": "completed",
            "objective": {"question": question, "success_metric": config.primary_metric},
        }

    manager.create_runner = fake_runner
    route_module._SESSION_MANAGER = manager
    disable_persistence(route_module)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    return app


def test_can_access_record_denies_empty_owner_for_non_admin():
    route_module = load_route_module()
    record = route_module.SessionRecord(
        session_id="session-ownerless",
        conversation_id="",
        question="ownerless",
        model="gpt-5.5",
        user_id="",
    )
    non_admin = SimpleNamespace(id="user-other", is_admin=lambda: False)
    admin = SimpleNamespace(id="admin", is_admin=lambda: True)

    assert route_module._can_access_record(record, non_admin) is False
    assert route_module._can_access_record(record, admin) is True


def test_registry_payload_round_trips_user_id(tmp_path):
    route_module = load_route_module()
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    record = route_module.SessionRecord(
        session_id="session-owned",
        conversation_id="conv-owned",
        question="owned",
        model="gpt-5.5",
        user_id="user-owner",
        status="completed",
        stage="completed",
    )

    route_module._save_gateway_session_record(record)
    [loaded] = route_module._load_gateway_session_records()

    assert loaded.user_id == "user-owner"
    assert loaded.summary()["user_id"] == "user-owner"


def test_persisted_summary_owner_is_loaded_from_research_session():
    route_module = load_route_module()

    assert (
        route_module._owner_from_persisted_summary(
            {"research_session": {"pathlab_user_id": "user-owner"}}
        )
        == "user-owner"
    )
    assert (
        route_module._owner_from_persisted_summary(
            {"research_session": {"recovery_metadata": {"user_id": "user-recovery"}}}
        )
        == "user-recovery"
    )
    assert route_module._owner_from_persisted_summary({}) == ""


def test_ownerless_persisted_record_is_hidden_from_non_admin():
    route_module = load_route_module()
    record = route_module.SessionRecord(
        session_id="legacy-ownerless",
        conversation_id="conv",
        question="legacy",
        model="",
        user_id="",
        status="completed",
        stage="completed",
    )
    non_admin = SimpleNamespace(id="user-other", is_admin=lambda: False)

    assert route_module._can_access_record(record, non_admin) is False


@pytest.mark.parametrize(
    ("method", "path", "json_payload"),
    [
        ("get", "/pathscientist/sessions/session-owned-by-x", None),
        ("post", "/pathscientist/sessions/session-owned-by-x/stop", None),
        ("post", "/pathscientist/sessions/session-owned-by-x/resume", {"question": "resume"}),
        ("delete", "/pathscientist/sessions/session-owned-by-x", None),
        ("post", "/pathscientist/sessions/session-owned-by-x/access-token", {"purpose": "events"}),
        ("get", "/pathscientist/sessions/session-owned-by-x/download", None),
        ("get", "/pathscientist/sessions/session-owned-by-x/runs/run-a/download", None),
        ("get", "/pathscientist/sessions/session-owned-by-x/events", None),
    ],
)
def test_session_endpoints_deny_other_users_in_memory_record(method, path, json_payload):
    route_module = load_route_module()
    manager = route_module.PathScientistSessionManager()
    manager._sessions["session-owned-by-x"] = route_module.SessionRecord(
        session_id="session-owned-by-x",
        conversation_id="",
        question="private",
        model="gpt-5.5",
        user_id="user-x",
        status="completed",
        stage="completed",
        state={"workspace_path": "/tmp/pathscientist-private-workspace"},
    )
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module, user_id="user-y")
    client = TestClient(app)

    request = getattr(client, method)
    kwargs = {"json": json_payload} if json_payload is not None else {}
    response = request(path, **kwargs)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_session_rejects_ownerless_memory_record_when_db_denies(monkeypatch):
    route_module = load_route_module()
    route_module._DB_HISTORY_ENABLED = True
    manager = route_module.PathScientistSessionManager()
    manager._sessions["session-shadow"] = route_module.SessionRecord(
        session_id="session-shadow",
        conversation_id="",
        question="shadow",
        model="gpt-5.5",
        user_id="",
        status="completed",
        stage="completed",
    )
    route_module._SESSION_MANAGER = manager

    async def fake_load_db_record(session_id, **kwargs):
        assert session_id == "session-shadow"
        raise HTTPException(status_code=403, detail="PathScientist session access denied")

    monkeypatch.setattr(route_module, "_load_db_record", fake_load_db_record)

    with pytest.raises(HTTPException) as exc:
        await route_module.get_session(
            "session-shadow",
            user=SimpleNamespace(id="user-other", is_admin=lambda: False),
        )

    assert exc.value.status_code == 403


def test_pathscientist_access_token_replaces_full_jwt_query_token(tmp_path):
    route_module = load_route_module()
    route_module._resolve_pathscientist_base_dir = lambda: tmp_path
    workspace = tmp_path / "session-token"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("hello\n", encoding="utf-8")
    run_dir = workspace / ".evidence" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "record.json").write_text(
        json.dumps({"run_id": "run-1", "artifacts": []}),
        encoding="utf-8",
    )
    manager = route_module.PathScientistSessionManager()
    record = route_module.SessionRecord(
        session_id="session-token",
        conversation_id="conv-token",
        question="token hardening",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
        state={"workspace_dir": str(workspace)},
    )
    manager._sessions[record.session_id] = record
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(
        app,
        route_module,
        override_pathscientist_access_token=False,
    )
    client = TestClient(app)

    minted = client.post(
        "/pathscientist/sessions/session-token/access-token",
        json={"purpose": "run_download", "run_id": "run-1"},
    )
    assert minted.status_code == 200
    access_token = minted.json()["token"]
    assert minted.json()["expires_in"] <= 300

    full_jwt = jwt.encode(
        {"sub": "user-test", "aud": "fastapi-users:auth", "sn": "nonce"},
        route_module.PATHSCIENTIST_ACCESS_TOKEN_SECRET,
        algorithm="HS256",
    )
    full_jwt_response = client.get(
        "/pathscientist/sessions/session-token/runs/run-1/download",
        params={"token": full_jwt},
    )
    assert full_jwt_response.status_code == 401

    response = client.get(
        "/pathscientist/sessions/session-token/runs/run-1/download",
        params={"token": access_token},
    )
    assert response.status_code == 200
    assert response.headers["Referrer-Policy"] == "no-referrer"

    wrong_run = client.get(
        "/pathscientist/sessions/session-token/runs/run-2/download",
        params={"token": access_token},
    )
    assert wrong_run.status_code == 403


def test_pathscientist_events_require_single_purpose_access_token():
    route_module = load_route_module()
    manager = route_module.PathScientistSessionManager()
    record = route_module.SessionRecord(
        session_id="session-events-token",
        conversation_id="conv-events-token",
        question="token hardening",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
        state={"stage": "completed"},
    )
    record.add_event({"kind": "state", "state": {"stage": "completed"}, "status": "completed"})
    manager._sessions[record.session_id] = record
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(
        app,
        route_module,
        override_pathscientist_access_token=False,
    )
    client = TestClient(app)

    minted = client.post(
        "/pathscientist/sessions/session-events-token/access-token",
        json={"purpose": "events"},
    )
    assert minted.status_code == 200
    events_token = minted.json()["token"]

    response = client.get(
        "/pathscientist/sessions/session-events-token/events",
        params={"token": events_token},
    )
    assert response.status_code == 200
    assert response.headers["Referrer-Policy"] == "no-referrer"

    wrong_purpose = client.post(
        "/pathscientist/sessions/session-events-token/access-token",
        json={"purpose": "session_download"},
    ).json()["token"]
    rejected = client.get(
        "/pathscientist/sessions/session-events-token/events",
        params={"token": wrong_purpose},
    )
    assert rejected.status_code == 403


def test_lists_registered_skills():
    client = TestClient(make_app())

    response = client.get("/pathscientist/skills")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert any(item["id"] == "mil_classification" for item in data["items"])


def test_create_session_returns_default_codex_relay_model(monkeypatch):
    route_module = load_route_module()
    monkeypatch.setattr(
        route_module.Config,
        "get_global_settings",
        staticmethod(
            lambda: {
                "local_vllm_enabled": False,
                "local_vllm_base_url": "http://127.0.0.1:8000/v1",
                "local_vllm_model": "",
                "local_vllm_api_key": "",
                "openrouter_api_key": "openrouter-key",
                "openrouter_base_url": "https://openrouter.ai/api/v1",
                "openrouter_model": "qwen/qwen3.5-plus-02-15",
            }
        ),
    )
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._queue_session_title_generation = lambda record, config: None
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []
    manager = route_module.PathScientistSessionManager()

    def fake_runner(config, question, emit):
        return {
            "session_id": "session_fake",
            "conversation_id": "conv_fake",
            "stage": "completed",
            "objective": {"question": question, "success_metric": config.primary_metric},
        }

    manager.create_runner = fake_runner
    route_module._SESSION_MANAGER = manager
    disable_persistence(route_module)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.post(
        "/pathscientist/sessions",
        json={"question": "quick smoke", "max_iter": 1},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"]
    assert data["model"] == "gpt-5.5"
    assert data["status"] in {"queued", "running", "completed"}


def test_manager_marks_completed_workflow_without_committed_run_as_failed(monkeypatch, tmp_path):
    route_module = load_route_module()
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    disable_persistence(route_module)
    monkeypatch.setattr(
        route_module,
        "_sync_pathscientist_manifest_to_pathlab_best_effort",
        lambda record, state: {"status": "skipped"},
    )

    manager = route_module.PathScientistSessionManager()

    def fake_runner(config, question, emit):
        return {
            "session_id": "session_failed_science",
            "conversation_id": "conv_failed_science",
            "stage": "completed",
            "objective": {"question": question, "success_metric": "auc"},
            "run_history": [
                {
                    "run_id": "run_bad",
                    "iteration": 0,
                    "metric_name": "auc",
                    "metric_value": 0.0,
                    "committed": False,
                    "exit_code": 1,
                    "error_type": "FileNotFound",
                    "metrics": {"status": "failed", "error": "Required FEATURES_DIR does not exist"},
                }
            ],
            "latest_review": {
                "status": "failed",
                "decision": "enter_synthesis",
                "summary": "Run run_bad did not provide a valid positive AUC metric.",
            },
            "review_decision": "enter_synthesis",
            "stop_reason": "stall_limit",
        }

    manager.create_runner = fake_runner
    record = route_module.SessionRecord(
        session_id="session-ui",
        conversation_id="",
        question="train with missing external features",
        model="gpt-5.5",
    )

    manager._run(
        record,
        route_module.StartPathScientistSessionRequest(question=record.question),
        SimpleNamespace(primary_metric="auc"),
    )

    assert record.status == "failed"
    assert record.stage == "failed"
    assert "Run run_bad did not provide" in record.error
    assert record.state["stage"] == "failed"
    assert record.state["error"] == record.error


def test_session_manager_passes_pathlab_user_id_to_runner_config(monkeypatch):
    route_module = load_route_module()

    class _StubConfig:
        data_mounts: dict[str, str] = {}
        llm_model = "gpt-5.5"
        primary_metric = "auc"

    monkeypatch.setattr(route_module, "_build_config", lambda req: _StubConfig())
    route_module._queue_session_title_generation = lambda record, config: None

    manager = route_module.PathScientistSessionManager()
    captured: list[str] = []

    def fake_run(record, req, config):
        captured.append(getattr(config, "pathlab_user_id", ""))

    monkeypatch.setattr(manager, "_run", fake_run)

    manager.start(
        route_module.StartPathScientistSessionRequest(question="download PANDA"),
        user_id="user-test",
    )

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not captured:
        time.sleep(0.01)

    assert captured == ["user-test"]


def test_session_manager_passes_pathlab_user_id_to_resume_config(monkeypatch):
    route_module = load_route_module()

    class _StubConfig:
        data_mounts: dict[str, str] = {}
        llm_model = "gpt-5.5"
        primary_metric = "auc"

    monkeypatch.setattr(route_module, "_build_config", lambda req: _StubConfig())

    manager = route_module.PathScientistSessionManager()
    captured: list[str] = []

    def fake_resume_run(record, req, config):
        captured.append(getattr(config, "pathlab_user_id", ""))

    monkeypatch.setattr(manager, "_resume_run", fake_resume_run)

    record = route_module.SessionRecord(
        session_id="session-1",
        conversation_id="11111111111111111111111111111111",
        question="resume",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
    )
    monkeypatch.setattr(
        route_module,
        "_conversation_uuid",
        lambda conversation_id: conversation_id,
    )
    monkeypatch.setattr(
        route_module,
        "_conversation_base_state_exists",
        lambda conversation_id, state: True,
    )

    manager.resume(
        record,
        route_module.StartPathScientistSessionRequest(question="resume"),
    )

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not captured:
        time.sleep(0.01)

    assert captured == ["user-test"]


def test_create_session_preserves_patch_external_task_type(monkeypatch, tmp_path):
    route_module = load_route_module()
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    internal_dir = tmp_path / "internal_patch_dataset"
    external_dir = tmp_path / "external_patch_dataset"
    for root in (internal_dir, external_dir):
        (root / "images").mkdir(parents=True)
        (root / "splits.json").write_text("{}", encoding="utf-8")
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._queue_session_title_generation = lambda record, config: None
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []
    captured_configs = []

    async def fake_resolve_dataset_mounts(dataset_ids, user, question=""):
        return {
            str(internal_dir): "/data/internal_patch_dataset",
            str(external_dir): "/data/external_patch_dataset",
        }

    monkeypatch.setattr(
        route_module,
        "_resolve_pathlab_dataset_mounts",
        fake_resolve_dataset_mounts,
        raising=False,
    )
    manager = route_module.PathScientistSessionManager()

    def fake_runner(config, question, emit):
        captured_configs.append(config)
        return {"stage": "completed", "conversation_id": "conv_patch_external"}

    manager.create_runner = fake_runner
    route_module._SESSION_MANAGER = manager
    disable_persistence(route_module)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module, user_id="user-dataset")
    client = TestClient(app)

    response = client.post(
        "/pathscientist/sessions",
        json={
            "question": "Train a patch-level classifier on internal_patch_dataset, then validate on external_patch_dataset.",
            "skill": "patch_classification",
        },
    )

    assert response.status_code == 200
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not captured_configs:
        time.sleep(0.01)
    config = captured_configs[0]
    assert config.external_test_enabled is True
    assert config.external_test_contract["external_task_type"] == "patch_classification"
    assert config.external_test_contract["external_images_dir"] == "/data/external_patch_dataset/images"


def test_create_session_marks_external_named_dataset_in_contract(monkeypatch, tmp_path):
    route_module = load_route_module()
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    internal_dir = tmp_path / "local_tcga_nsclc_subset4_521c7518"
    external_dir = tmp_path / "synthetic_nsclc_external_test_b84756e8"
    for root in (internal_dir, external_dir):
        (root / "wsi_files").mkdir(parents=True)
        (root / "features" / "virchow2").mkdir(parents=True)
        (root / "splits.json").write_text("{}", encoding="utf-8")
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._queue_session_title_generation = lambda record, config: None
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []
    captured_configs = []

    async def fake_resolve_dataset_mounts(dataset_ids, user, question=""):
        return {
            str(internal_dir): "/data/local_tcga_nsclc_subset4_521c7518",
            str(external_dir): "/data/synthetic_nsclc_external_test_b84756e8",
        }

    monkeypatch.setattr(
        route_module,
        "_resolve_pathlab_dataset_mounts",
        fake_resolve_dataset_mounts,
        raising=False,
    )
    manager = route_module.PathScientistSessionManager()

    def fake_runner(config, question, emit):
        captured_configs.append(config)
        return {"stage": "completed", "conversation_id": "conv_external"}

    manager.create_runner = fake_runner
    route_module._SESSION_MANAGER = manager
    disable_persistence(route_module)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module, user_id="user-dataset")
    client = TestClient(app)

    response = client.post(
        "/pathscientist/sessions",
        json={
            "question": "Train on local - tcga-nsclc-subset4, then validate on nsclc_external_test.",
        },
    )

    assert response.status_code == 200
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not captured_configs:
        time.sleep(0.01)
    config = captured_configs[0]
    assert config.external_test_enabled is True
    assert config.external_test_contract["external_wsi_dir"] == "/data/synthetic_nsclc_external_test_b84756e8/wsi_files"
    assert config.external_test_contract["external_splits_file"] == "/data/synthetic_nsclc_external_test_b84756e8/splits.json"
    external_dataset = next(
        item for item in config.external_test_contract["datasets"] if item["role"] == "external"
    )
    assert external_dataset["paths"] == ["/data/synthetic_nsclc_external_test_b84756e8"]


def test_create_session_resolves_pathlab_dataset_name_from_question_without_client_paths(monkeypatch, tmp_path):
    route_module = load_route_module()
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    prepared_dir = tmp_path / "pathlab-dataset-view"
    prepared_dir.mkdir()
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._queue_session_title_generation = lambda record, config: None
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []
    resolved_calls: list[tuple[list[str], str]] = []
    captured_mounts: list[dict[str, str]] = []

    async def fake_resolve_dataset_mounts(dataset_ids, user, question=""):
        resolved_calls.append((list(dataset_ids), str(user.id), question))
        return {str(prepared_dir): "/data/pathscientist_tcga_luad"}

    monkeypatch.setattr(
        route_module,
        "_resolve_pathlab_dataset_mounts",
        fake_resolve_dataset_mounts,
        raising=False,
    )
    manager = route_module.PathScientistSessionManager()

    def fake_runner(config, question, emit):
        captured_mounts.append(dict(config.data_mounts))
        return {"stage": "completed", "conversation_id": "conv_dataset"}

    manager.create_runner = fake_runner
    route_module._SESSION_MANAGER = manager
    disable_persistence(route_module)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module, user_id="user-dataset")
    client = TestClient(app)

    response = client.post(
        "/pathscientist/sessions",
        json={"question": "Train a LUAD model using PathScientist TCGA-LUAD"},
    )

    assert response.status_code == 200
    assert resolved_calls == [([], "user-dataset", "Train a LUAD model using PathScientist TCGA-LUAD")]
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not captured_mounts:
        time.sleep(0.01)
    assert captured_mounts == [{str(prepared_dir): "/data/pathscientist_tcga_luad"}]


def test_resolve_pathlab_dataset_mounts_uses_explicit_dataset_data_type(monkeypatch, tmp_path):
    route_module = load_route_module()
    selected_dataset_id = "patch-dataset"
    selected_group_id = "patch-group"
    captured_data_types: list[str | None] = []
    captured_group_ids: list[str] = []

    class DatasetWithLazyDataGroup:
        dataset_id = selected_dataset_id
        name = "CRC-MSI-100patches"
        is_public = True
        user_id = None
        parent_dataset_id = None
        source_organ = "colorectal"
        group_id = selected_group_id

        @property
        def data_group(self):
            raise AssertionError("data_group relationship should not be lazy-loaded")

    dataset = DatasetWithLazyDataGroup()
    slides = [
        SimpleNamespace(
            wsi_id="patch-1",
            wsi_path=str(tmp_path / "patch-1.jpg"),
            label="MSIH",
            split="train",
            original_filename="patch-1.jpg",
        ),
        SimpleNamespace(
            wsi_id="patch-2",
            wsi_path=str(tmp_path / "patch-2.jpg"),
            label="nonMSIH",
            split="test",
            original_filename="patch-2.jpg",
        ),
        SimpleNamespace(
            wsi_id="patch-3",
            wsi_path=str(tmp_path / "patch-3.jpg"),
            label="MSIH",
            split="train",
            original_filename="patch-3.jpg",
        ),
    ]

    async def fake_get_dataset_with_access(dataset_id, user, db, **kwargs):
        assert dataset_id == selected_dataset_id
        return dataset

    async def fake_get_permitted_dataset_ids(user, db):
        return []

    class FakeWSIRepository:
        @staticmethod
        async def get_by_dataset(db, dataset_id, **kwargs):
            assert dataset_id == selected_dataset_id
            captured_data_types.append(kwargs.get("data_type"))
            return slides

    class FakeDataGroupRepository:
        @staticmethod
        async def get_by_id(db, group_id):
            captured_group_ids.append(group_id)
            assert group_id == selected_group_id
            return SimpleNamespace(data_type="patch")

    class FakeSafeSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(route_module, "_pathlab_dataset_view_parent", lambda: tmp_path / "views")
    monkeypatch.setattr(
        route_module,
        "_prepare_pathlab_dataset_view",
        lambda *, dataset, slides, view_dir: view_dir,
    )
    monkeypatch.setattr(
        route_module,
        "safe_session",
        lambda: FakeSafeSession(),
    )

    repositories = types.ModuleType("backend.database.repositories")
    repositories.WSIRepository = FakeWSIRepository
    repositories.DataGroupRepository = FakeDataGroupRepository
    sys.modules["backend.database.repositories"] = repositories

    dependencies = types.ModuleType("backend.auth.dependencies")
    dependencies.get_dataset_with_access = fake_get_dataset_with_access
    dependencies.get_permitted_dataset_ids = fake_get_permitted_dataset_ids
    sys.modules["backend.auth.dependencies"] = dependencies

    mounts = asyncio.run(
        route_module._resolve_pathlab_dataset_mounts(
            [selected_dataset_id],
            SimpleNamespace(id="admin", is_admin=lambda: True),
            question="patch level classification",
        )
    )

    assert captured_data_types == ["patch"]
    assert captured_group_ids == [selected_group_id]
    assert len(mounts) == 1
    assert list(mounts.values())[0].startswith("/data/crc_msi_100patches")


def test_match_pathlab_datasets_from_question_prefers_visible_name_matches():
    route_module = load_route_module()

    matches = route_module._match_pathlab_datasets_from_question(
        "Please run PathScientist on PathScientist TCGA-LUAD and compare ABMIL.",
        [
            {"dataset_id": "dataset-lusc", "dataset_name": "PathScientist TCGA-LUSC"},
            {"dataset_id": "dataset-luad", "dataset_name": "PathScientist TCGA-LUAD"},
        ],
    )

    assert matches == ["dataset-luad"]


def test_match_pathlab_datasets_from_question_does_not_treat_synthetic_as_named_external_cache():
    route_module = load_route_module()

    matches = route_module._match_pathlab_datasets_from_question(
        "Train on local - tcga-nsclc-subset4, then validate on nsclc_external_test.",
        [
            {"dataset_id": "internal", "dataset_name": "local - tcga-nsclc-subset4"},
            {"dataset_id": "synthetic", "dataset_name": "synthetic - NSCLC-external-test"},
        ],
    )

    assert matches == ["internal"]


def test_classify_pathlab_mount_roles_keeps_chinese_internal_dataset_internal(tmp_path):
    route_module = load_route_module()
    view_dir = tmp_path / "local_tcga_nsclc_subset4_521c7518"
    view_dir.mkdir()
    (view_dir / "dataset_manifest.json").write_text(
        json.dumps({"dataset_name": "local - tcga-nsclc-subset4"}),
        encoding="utf-8",
    )

    roles = route_module._classify_pathlab_mount_roles(
        (
            "使用内部数据集 local - tcga-nsclc-subset4 训练一个快速的 NSCLC "
            "LUAD vs LUSC MIL 分类模型。优先使用已有的 virchow2 features，"
            "调试用最小配置，只跑 1 个 iteration / 少量 epoch。然后用 "
            "nsclc_external_test 作为 external validation。"
        ),
        {str(view_dir): "/data/local_tcga_nsclc_subset4_521c7518"},
    )

    assert roles.get("internal", {}).get("container") == "/data/local_tcga_nsclc_subset4_521c7518"
    assert "external" not in roles


def test_resolve_pathlab_dataset_mounts_matches_question_dataset_name(monkeypatch, tmp_path):
    route_module = load_route_module()
    route_module._resolve_pathscientist_base_dir = lambda: tmp_path / "pathscientist-base"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    slides = []
    for idx, split in enumerate(["train", "train", "val", "test"], start=1):
        source = source_dir / f"slide-{idx}.svs"
        source.write_text(f"slide {idx}", encoding="utf-8")
        slides.append(
            SimpleNamespace(
                wsi_id=f"slide-{idx}",
                wsi_path=str(source),
                original_filename=source.name,
                label="luad",
                split=split,
            )
        )
    dataset = SimpleNamespace(
        id=1,
        dataset_id="dataset-luad",
        name="PathScientist TCGA-LUAD",
        user_id="user-dataset",
        is_public=False,
        parent_dataset_id=None,
        source_organ="lung",
    )

    class FakeSession:
        pass

    class FakeSafeSession:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_get_permitted_dataset_ids(user, db):
        return []

    async def fake_get_dataset_with_access(dataset_id, user, db, **kwargs):
        assert dataset_id == "dataset-luad"
        return dataset

    class FakeWSIRepository:
        @staticmethod
        async def get_datasets(db, **kwargs):
            return [{"dataset_id": "dataset-luad", "dataset_name": "PathScientist TCGA-LUAD"}]

        @staticmethod
        async def get_by_dataset(db, dataset_id, **kwargs):
            assert dataset_id == "dataset-luad"
            return slides

    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "backend.auth.dependencies":
            return SimpleNamespace(
                get_dataset_with_access=fake_get_dataset_with_access,
                get_permitted_dataset_ids=fake_get_permitted_dataset_ids,
            )
        if name == "backend.database.repositories":
            return SimpleNamespace(WSIRepository=FakeWSIRepository)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(route_module, "safe_session", lambda: FakeSafeSession())
    monkeypatch.setattr("builtins.__import__", fake_import)

    mounts = route_module.asyncio.run(
        route_module._resolve_pathlab_dataset_mounts(
            [],
            SimpleNamespace(id="user-dataset", is_admin=lambda: False),
            question="Use PathScientist TCGA-LUAD for feature extraction",
        )
    )

    assert len(mounts) == 1
    [(host, container)] = mounts.items()
    assert Path(host).name.startswith("pathscientist_tcga_luad")
    assert container.startswith("/data/pathscientist_tcga_luad")
    assert (Path(host) / "wsi_files").is_dir()
    assert (Path(host) / "labels.csv").is_file()


def test_resolve_pathlab_dataset_mounts_matches_patch_dataset_name(monkeypatch, tmp_path):
    route_module = load_route_module()
    route_module._resolve_pathscientist_base_dir = lambda: tmp_path / "pathscientist-base"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    slides = []
    specs = [
        ("patch-1", "MSIH", "train"),
        ("patch-2", "nonMSIH", "train"),
        ("patch-3", "MSIH", "test"),
    ]
    for wsi_id, label, split in specs:
        source = source_dir / f"{wsi_id}.jpg"
        source.write_bytes(b"image")
        slides.append(
            SimpleNamespace(
                wsi_id=wsi_id,
                wsi_path=str(source),
                original_filename=source.name,
                label=label,
                split=split,
            )
        )
    dataset = SimpleNamespace(
        id=1,
        dataset_id="patch-dataset",
        name="CRC-MSI-100patches",
        user_id="user-dataset",
        is_public=False,
        parent_dataset_id=None,
        source_organ="colorectal",
        data_type="patch",
    )
    captured_get_dataset_data_types: list[str | None] = []

    class FakeSession:
        pass

    class FakeSafeSession:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_get_permitted_dataset_ids(user, db):
        return []

    async def fake_get_dataset_with_access(dataset_id, user, db, **kwargs):
        assert dataset_id == "patch-dataset"
        return dataset

    class FakeWSIRepository:
        @staticmethod
        async def get_datasets(db, **kwargs):
            captured_get_dataset_data_types.append(kwargs.get("data_type"))
            if kwargs.get("data_type") == "patch":
                return [{"dataset_id": "patch-dataset", "dataset_name": "CRC-MSI-100patches"}]
            return [{"dataset_id": "wsi-dataset", "dataset_name": "Unrelated WSI Dataset"}]

        @staticmethod
        async def get_by_dataset(db, dataset_id, **kwargs):
            assert dataset_id == "patch-dataset"
            assert kwargs.get("data_type") == "patch"
            return slides

    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "backend.auth.dependencies":
            return SimpleNamespace(
                get_dataset_with_access=fake_get_dataset_with_access,
                get_permitted_dataset_ids=fake_get_permitted_dataset_ids,
            )
        if name == "backend.database.repositories":
            return SimpleNamespace(WSIRepository=FakeWSIRepository)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(route_module, "safe_session", lambda: FakeSafeSession())
    monkeypatch.setattr("builtins.__import__", fake_import)

    mounts = route_module.asyncio.run(
        route_module._resolve_pathlab_dataset_mounts(
            [],
            SimpleNamespace(id="user-dataset", is_admin=lambda: False),
            question="Use the registered PathLab dataset CRC-MSI-100patches for a smoke test",
        )
    )

    assert captured_get_dataset_data_types == ["wsi", "patch"]
    assert len(mounts) == 1
    [(host, container)] = mounts.items()
    assert Path(host).name.startswith("crc_msi_100patches")
    assert container.startswith("/data/crc_msi_100patches")
    assert (Path(host) / "images" / "MSIH").is_dir()
    assert (Path(host) / "pathlab_training_manifest.json").is_file()


def test_prepare_pathlab_dataset_view_uses_symlinks_and_generates_contract(tmp_path):
    route_module = load_route_module()
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    slides = []
    for idx, label in enumerate(["luad", "luad", "lusc", "lusc"], start=1):
        source = source_dir / f"slide-{idx}.svs"
        source.write_text(f"slide {idx}", encoding="utf-8")
        slides.append(
            SimpleNamespace(
                wsi_id=f"slide-{idx}",
                wsi_path=str(source),
                original_filename=source.name,
                label=label,
                split="train" if idx <= 2 else ("val" if idx == 3 else "test"),
            )
        )
    dataset = SimpleNamespace(
        dataset_id="dataset-123",
        name="PathScientist TCGA-LUAD",
        source_organ="lung",
    )

    view_dir = route_module._prepare_pathlab_dataset_view(
        dataset=dataset,
        slides=slides,
        view_dir=tmp_path / "view",
    )

    assert (view_dir / "wsi_files").is_dir()
    assert (view_dir / "labels.csv").is_file()
    assert (view_dir / "splits.json").is_file()
    assert (view_dir / "dataset_manifest.json").is_file()
    links = sorted((view_dir / "wsi_files").iterdir())
    assert len(links) == 4
    assert all(link.is_symlink() for link in links)
    manifest = json.loads((view_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset_id"] == "dataset-123"
    assert manifest["layout"] == "pathlab_dataset_view"
    assert manifest["num_wsi"] == 4
    splits = json.loads((view_dir / "splits.json").read_text(encoding="utf-8"))
    assert set(splits) >= {"train", "val", "test", "labels"}
    assert all(splits[key] for key in ("train", "val", "test"))


def test_prepare_pathlab_patch_dataset_view_is_patch_readiness_ready(tmp_path):
    route_module = load_route_module()
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    slides = []
    specs = [
        ("patch-1", "MSIH", "train"),
        ("patch-2", "nonMSIH", "train"),
        ("patch-3", "MSIH", "test"),
        ("patch-4", "nonMSIH", "test"),
    ]
    for wsi_id, label, split in specs:
        source = source_dir / f"{wsi_id}.jpg"
        source.write_bytes(b"image")
        slides.append(
            SimpleNamespace(
                wsi_id=wsi_id,
                wsi_path=str(source),
                original_filename=source.name,
                label=label,
                split=split,
            )
        )
    dataset = SimpleNamespace(
        dataset_id="patch-dataset",
        name="CRC-MSI-100patches",
        source_organ="colorectal",
        data_group=SimpleNamespace(data_type="patch"),
    )

    view_dir = route_module._prepare_pathlab_dataset_view(
        dataset=dataset,
        slides=slides,
        view_dir=tmp_path / "patch-view",
    )

    assert sorted(p.name for p in (view_dir / "images").iterdir()) == ["MSIH", "nonMSIH"]
    assert len(list((view_dir / "images" / "MSIH").iterdir())) == 2
    assert len(list((view_dir / "images" / "nonMSIH").iterdir())) == 2
    pathlab_manifest = json.loads(
        (view_dir / "pathlab_training_manifest.json").read_text(encoding="utf-8")
    )
    assert [item["split"] for item in pathlab_manifest["items"]] == [
        "train",
        "train",
        "test",
        "test",
    ]
    assert all(str(view_dir / "images") in item["wsi_path"] for item in pathlab_manifest["items"])

    from backend.pathscientist.dataset.readiness import assess_data_readiness
    from backend.pathscientist.dataset.types import TaskProfile

    readiness = assess_data_readiness(
        TaskProfile.from_dict(
            {
                "task_type": "patch_classification",
                "asset_level": "patch",
                "input_modality": "patch_images",
                "label_granularity": "patch",
                "preferred_skill": "patch_classification",
            }
        ),
        data_mounts={str(view_dir): "/data/crc_msi_100patches"},
    )

    assert readiness.status == "patch_images_ready"
    assert readiness.data_dir == "/data/crc_msi_100patches"
    assert readiness.images_dir == "/data/crc_msi_100patches/images"


def test_prepare_pathlab_dataset_view_links_tcga_patches_features_by_view_slide_id(tmp_path):
    route_module = load_route_module()
    pathology_root = tmp_path / "Pathology"
    slide_specs = [
        ("LUAD", "uuid-luad-1", "TCGA-05-4244-01Z-00-DX1.d4ff32cd-38cf-40ea-8213-45c2b100ac01", "luad", "train"),
        ("LUAD", "uuid-luad-2", "TCGA-05-4245-01Z-00-DX1.36ff5403-d4bb-4415-b2c5-7c750d655cde", "luad", "val"),
        ("LUSC", "uuid-lusc-1", "TCGA-18-3406-01Z-00-DX1.8D07F006-425C-4724-BBB3-5BA099401234", "lusc", "train"),
        ("LUSC", "uuid-lusc-2", "TCGA-18-3407-01Z-00-DX1.E7DDA7E3-45A2-4E06-A081-E6A81A672155", "lusc", "test"),
    ]
    slides = []
    expected_features = {}
    for cohort, wsi_id, tcga_stem, label, split in slide_specs:
        source_dir = pathology_root / "original_data" / "TCGA" / cohort / "slides" / f"case-{wsi_id}"
        source_dir.mkdir(parents=True)
        source = source_dir / f"{tcga_stem}.svs"
        source.write_text("wsi", encoding="utf-8")
        feature_dir = pathology_root / "Patches" / "TCGA" / f"TCGA-{cohort}" / "pt_files" / "virchow2"
        feature_dir.mkdir(parents=True, exist_ok=True)
        feature = feature_dir / f"{tcga_stem}.pt"
        feature.write_bytes(b"feature")
        expected_features[wsi_id] = feature
        slides.append(
            SimpleNamespace(
                wsi_id=wsi_id,
                wsi_path=str(source),
                original_filename=f"{cohort}__{tcga_stem}.svs",
                label=label,
                split=split,
            )
        )
    dataset = SimpleNamespace(
        dataset_id="dataset-tcga-nsclc",
        name="local - tcga-nsclc-subset4",
        source_organ="lung",
    )

    view_dir = route_module._prepare_pathlab_dataset_view(
        dataset=dataset,
        slides=slides,
        view_dir=tmp_path / "view",
    )

    for wsi_id, feature in expected_features.items():
        linked = view_dir / "features" / "virchow2" / f"{wsi_id}.pt"
        assert linked.is_symlink()
        assert linked.resolve() == feature.resolve()


def test_sync_pathscientist_download_manifest_registers_pathlab_dataset(monkeypatch, tmp_path):
    route_module = load_route_module()
    uploads = tmp_path / "uploads"
    wsi_dir = uploads / "DemoWSI" / "wsi_files"
    wsi_dir.mkdir(parents=True)
    first = wsi_dir / "slide_001.svs"
    second = wsi_dir / "slide_002.svs"
    first.write_bytes(b"wsi-1")
    second.write_bytes(b"wsi-2")
    labels = tmp_path / "labels.csv"
    labels.write_text("slide_id,label\nslide_001,tumor\nslide_002,normal\n", encoding="utf-8")
    splits = tmp_path / "splits.json"
    splits.write_text(
        json.dumps({"train": ["slide_001"], "test": ["slide_002"], "labels": {}}),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dataset_id": "hf:demo/wsi",
                "provider": "huggingface",
                "selected_for_task": "mil_classification",
                "raw_root": str(wsi_dir),
                "prepared_root": str(tmp_path / "prepared"),
                "data_mounts": {},
                "prepared_contract": {
                    "labels_file": str(labels),
                    "splits_file": str(splits),
                },
                "status": "prepared",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(route_module.Config, "get_uploads_dir", staticmethod(lambda: uploads))

    class FakeDb:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    fake_db = FakeDb()

    class FakeSafeSession:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(route_module, "safe_session", lambda: FakeSafeSession())

    from backend.database.repositories import (
        DataGroupRepository,
        DatasetRepository,
        DatasetStatsRepository,
        WSIRepository,
    )

    calls = {"groups": [], "datasets": [], "wsis": [], "stats": []}

    async def fake_group_get_or_create(db, **kwargs):
        calls["groups"].append(kwargs)
        return SimpleNamespace(group_id="group-1", **kwargs)

    async def fake_dataset_get_or_create(db, name, **kwargs):
        calls["datasets"].append({"name": name, **kwargs})
        return SimpleNamespace(dataset_id="dataset-1", name=name, **kwargs)

    async def fake_dataset_get_by_name(db, name, user_id=None):
        return None

    async def fake_get_by_id(db, wsi_id):
        return None

    async def fake_wsi_create(db, **kwargs):
        calls["wsis"].append(kwargs)
        return SimpleNamespace(**kwargs)

    async def fake_recompute(db, dataset_id):
        calls["stats"].append(dataset_id)

    monkeypatch.setattr(DataGroupRepository, "get_or_create", staticmethod(fake_group_get_or_create))
    monkeypatch.setattr(DatasetRepository, "get_by_name", staticmethod(fake_dataset_get_by_name))
    monkeypatch.setattr(DatasetRepository, "get_or_create", staticmethod(fake_dataset_get_or_create))
    monkeypatch.setattr(WSIRepository, "get_by_id", staticmethod(fake_get_by_id))
    monkeypatch.setattr(WSIRepository, "create", staticmethod(fake_wsi_create))
    monkeypatch.setattr(DatasetStatsRepository, "recompute", staticmethod(fake_recompute))

    record = route_module.SessionRecord(
        session_id="session-download",
        conversation_id="",
        question="download demo wsi",
        model="gpt-5.5",
        user_id="user-test",
    )
    result = route_module.asyncio.run(
        route_module._sync_pathscientist_manifest_to_pathlab(
            record,
            {
                "dataset_manifest_path": str(manifest_path),
                "selected_dataset": {"name": "Demo WSI"},
                "task_profile": {"organ": "lung"},
            },
        )
    )

    assert result["status"] == "registered"
    assert result["dataset_id"] == "dataset-1"
    assert result["created_wsi_count"] == 2
    assert calls["groups"] == [
        {
            "data_type": "wsi",
            "aggregation_level": "file",
            "task_type": "classification",
            "name": "WSI File-level Classification",
        }
    ]
    assert calls["datasets"][0]["name"] == "hf - demo - wsi"
    assert calls["datasets"][0]["user_id"] == "user-test"
    assert {item["original_filename"] for item in calls["wsis"]} == {"slide_001.svs", "slide_002.svs"}
    assert {item["label"] for item in calls["wsis"]} == {"tumor", "normal"}
    assert {item["split"] for item in calls["wsis"]} == {"train", "test"}
    assert calls["stats"] == ["dataset-1"]
    assert fake_db.commits == 1


def test_sync_pathscientist_manifest_registers_uploads_root(monkeypatch, tmp_path):
    route_module = load_route_module()
    uploads = tmp_path / "uploads"
    wsi_dir = uploads / "existing_dataset" / "wsi_files"
    wsi_dir.mkdir(parents=True)
    (wsi_dir / "slide_001.svs").write_bytes(b"wsi")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dataset_id": "multi:all",
                "provider": "multi",
                "selected_for_task": "mil_classification",
                "raw_root": str(uploads),
                "prepared_root": "",
                "data_mounts": {},
                "prepared_contract": {},
                "status": "prepared",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(route_module.Config, "get_uploads_dir", staticmethod(lambda: uploads))

    class FakeDb:
        async def commit(self):
            return None

        async def rollback(self):
            return None

    class FakeSafeSession:
        async def __aenter__(self):
            return FakeDb()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(route_module, "safe_session", lambda: FakeSafeSession())

    from backend.database.repositories import (
        DataGroupRepository,
        DatasetRepository,
        DatasetStatsRepository,
        WSIRepository,
    )

    async def fake_group_get_or_create(db, **kwargs):
        return SimpleNamespace(group_id="group-1", **kwargs)

    async def fake_dataset_get_or_create(db, name, **kwargs):
        return SimpleNamespace(dataset_id="dataset-1", name=name, **kwargs)

    async def fake_dataset_get_by_name(db, name, user_id=None):
        return None

    async def fake_get_by_id(db, wsi_id):
        return None

    async def fake_wsi_create(db, **kwargs):
        return SimpleNamespace(**kwargs)

    async def fake_recompute(db, dataset_id):
        return None

    monkeypatch.setattr(DataGroupRepository, "get_or_create", staticmethod(fake_group_get_or_create))
    monkeypatch.setattr(DatasetRepository, "get_by_name", staticmethod(fake_dataset_get_by_name))
    monkeypatch.setattr(DatasetRepository, "get_or_create", staticmethod(fake_dataset_get_or_create))
    monkeypatch.setattr(WSIRepository, "get_by_id", staticmethod(fake_get_by_id))
    monkeypatch.setattr(WSIRepository, "create", staticmethod(fake_wsi_create))
    monkeypatch.setattr(DatasetStatsRepository, "recompute", staticmethod(fake_recompute))

    record = route_module.SessionRecord(
        session_id="session-download",
        conversation_id="",
        question="download demo wsi",
        model="gpt-5.5",
        user_id="user-test",
    )

    result = route_module.asyncio.run(
        route_module._sync_pathscientist_manifest_to_pathlab(
            record,
            {"dataset_manifest_path": str(manifest_path)},
        )
    )

    assert result["status"] == "registered"
    assert result["dataset_name"] == "multi - all"
    assert result["created_wsi_count"] == 1


def test_create_session_returns_pending_title_without_waiting_for_llm_title():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    queued: list[str] = []
    route_module._queue_session_title_generation = lambda record, config: queued.append(record.session_id)
    route_module._generate_session_title = lambda question, config=None: (_ for _ in ()).throw(
        AssertionError("title LLM must not run on the create-session request path")
    )
    manager = route_module.PathScientistSessionManager()

    def fake_runner(config, question, emit):
        return {"stage": "completed", "conversation_id": "conv_title"}

    manager.create_runner = fake_runner
    route_module._SESSION_MANAGER = manager
    route_module.pathscientist_persistence.persist_session_created = lambda **kwargs: None
    route_module.pathscientist_persistence.persist_event = lambda **kwargs: None
    route_module.pathscientist_persistence.persist_session_state = lambda **kwargs: None

    app = FastAPI()
    app.include_router(route_module.router)
    app.dependency_overrides[route_module.current_active_user] = lambda: SimpleNamespace(id="user-test")
    client = TestClient(app)
    question = (
        "我想训练一个 chronic gastritis inflammation grading 的 WSI MIL 分类任务，"
        "使用 SciDB 数据集并比较 ABMIL 和 TransMIL。"
    )

    response = client.post("/pathscientist/sessions", json={"question": question})

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == ""
    assert data["title_pending"] is True
    assert data["question"] == question
    assert queued == [data["session_id"]]


def test_create_session_rejects_overlong_question():
    route_module = load_route_module()
    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.post("/pathscientist/sessions", json={"question": "x" * 4001})

    assert response.status_code == 422


def test_create_session_persists_current_user_id():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._queue_session_title_generation = lambda record, config: None
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []
    calls: list[dict[str, str]] = []
    route_module.pathscientist_persistence.persist_session_created = (
        lambda **kwargs: calls.append(kwargs)
    )
    route_module.pathscientist_persistence.persist_event = lambda **kwargs: None
    route_module.pathscientist_persistence.persist_session_state = lambda **kwargs: None
    manager = route_module.PathScientistSessionManager()
    manager.create_runner = lambda config, question, emit: {"stage": "completed"}
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    app.dependency_overrides[route_module.current_active_user] = lambda: SimpleNamespace(id="user-42")
    client = TestClient(app)

    response = client.post("/pathscientist/sessions", json={"question": "persist me"})

    assert response.status_code == 200
    assert calls
    assert calls[0]["user_id"] == "user-42"
    assert calls[0]["question"] == "persist me"


def test_background_title_generation_updates_record_title():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    record = route_module.SessionRecord(
        session_id="s-title",
        conversation_id="",
        question="long question",
        model="gpt-5.5",
        title="",
        title_pending=True,
    )
    route_module._generate_session_title = lambda question, config=None: "LLM concise title"

    route_module._refresh_session_title(record, object())

    assert record.title == "LLM concise title"
    assert record.title_pending is False
    assert record.events[-1]["kind"] == "session_title"
    assert record.events[-1]["title"] == "LLM concise title"


def test_stop_running_session_marks_record_interrupted():
    route_module = load_route_module()
    manager = route_module.PathScientistSessionManager()
    record = route_module.SessionRecord(
        session_id="s-stop",
        conversation_id="",
        question="long run",
        model="gpt-5.5",
        user_id="user-test",
        status="running",
        stage="execution",
    )
    manager._sessions[record.session_id] = record

    stopped = manager.stop("s-stop")

    assert stopped is record
    assert record.cancel_requested is True
    assert record.status == "interrupted"
    assert record.stage == "interrupted"
    assert record.error == "Stopped by user from PathLab."
    assert record.state["stage"] == "interrupted"
    assert record.state["stop_reason"] == "user_cancelled"
    assert record.state["user_stop_requested"] is True
    assert record.state["stop_source"] == "pathlab_ui"
    assert isinstance(record.state["stop_requested_at"], float)
    assert record.events[-1]["kind"] == "state"
    assert record.events[-1]["status"] == "interrupted"
    assert record.events[-1]["user_stop_requested"] is True
    assert record.events[-1]["stop_source"] == "pathlab_ui"
    assert record.events[-1]["stop_requested_at"] == record.state["stop_requested_at"]


def test_stop_running_session_hard_cancels_active_processes(monkeypatch):
    route_module = load_route_module()
    from backend.pathscientist.runtime import session_registry

    cancelled: list[tuple[str, float, float]] = []

    def fake_cancel(session_id: str, *, term_timeout: float = 0.0, kill_timeout: float = 0.0):
        cancelled.append((session_id, term_timeout, kill_timeout))
        return {
            "active_process_count": 1,
            "terminated_process_groups": [12345],
            "sigterm_sent": [12345],
            "sigkill_sent": [12345],
        }

    monkeypatch.setattr(session_registry, "cancel_session_processes", fake_cancel)
    manager = route_module.PathScientistSessionManager()
    record = route_module.SessionRecord(
        session_id="s-hard-stop",
        conversation_id="",
        question="long feature extraction",
        model="gpt-5.5",
        status="running",
        stage="execution",
    )
    manager._sessions[record.session_id] = record

    manager.stop("s-hard-stop")

    assert cancelled == [("s-hard-stop", 3.0, 0.5)]
    assert record.state["process_cleanup"]["active_process_count"] == 1
    assert record.state["process_cleanup"]["terminated_process_groups"] == [12345]
    assert record.events[-1]["process_cleanup"]["sigkill_sent"] == [12345]


def test_stop_running_gateway_session_also_cancels_internal_pathscientist_session(monkeypatch):
    route_module = load_route_module()
    from backend.pathscientist.runtime import session_registry

    cancelled: list[str] = []

    def fake_cancel(session_id: str, *, term_timeout: float = 0.0, kill_timeout: float = 0.0):
        cancelled.append(session_id)
        if session_id == "internal-session":
            return {
                "active_process_count": 2,
                "terminated_process_groups": [111, 222],
                "sigterm_sent": [111, 222],
                "sigkill_sent": [222],
                "processes": [{"session_id": "internal-session", "pgid": 111}],
            }
        return {
            "active_process_count": 0,
            "terminated_process_groups": [],
            "sigterm_sent": [],
            "sigkill_sent": [],
            "processes": [],
        }

    monkeypatch.setattr(session_registry, "cancel_session_processes", fake_cancel)
    manager = route_module.PathScientistSessionManager()
    record = route_module.SessionRecord(
        session_id="gateway-session",
        conversation_id="",
        question="long feature extraction",
        model="gpt-5.5",
        status="running",
        stage="execution",
        state={"session_id": "internal-session"},
    )
    manager._sessions[record.session_id] = record

    manager.stop("gateway-session")

    assert cancelled == ["gateway-session", "internal-session"]
    cleanup = record.state["process_cleanup"]
    assert cleanup["active_process_count"] == 2
    assert cleanup["terminated_process_groups"] == [111, 222]
    assert cleanup["sigterm_sent"] == [111, 222]
    assert cleanup["sigkill_sent"] == [222]
    assert cleanup["session_ids"] == ["gateway-session", "internal-session"]


def test_cancelled_run_preserves_user_stop_marker_when_runner_returns():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    manager = route_module.PathScientistSessionManager()

    def fake_runner(_config, _question, _emit):
        return {"stage": "completed", "conversation_id": "conv-after-stop"}

    manager.create_runner = fake_runner
    record = route_module.SessionRecord(
        session_id="s-after-stop",
        conversation_id="",
        question="long run",
        model="gpt-5.5",
        status="running",
        stage="execution",
        error="Stopped by user from PathLab.",
        cancel_requested=True,
        state={
            "user_stop_requested": True,
            "stop_source": "pathlab_ui",
            "stop_requested_at": 123.0,
            "process_cleanup": {"active_process_count": 0},
        },
    )

    manager._run(
        record,
        route_module.StartPathScientistSessionRequest(question="long run"),
        object(),
    )

    assert record.status == "interrupted"
    assert record.state["stop_reason"] == "user_cancelled"
    assert record.state["user_stop_requested"] is True
    assert record.state["stop_source"] == "pathlab_ui"
    assert record.state["stop_requested_at"] == 123.0
    assert record.state["process_cleanup"]["active_process_count"] == 0


def test_stop_session_endpoint_returns_interrupted_summary():
    route_module = load_route_module()
    manager = route_module.PathScientistSessionManager()
    record = route_module.SessionRecord(
        session_id="s-stop-api",
        conversation_id="",
        question="long run",
        model="gpt-5.5",
        user_id="user-test",
        status="running",
        stage="execution",
    )
    manager._sessions[record.session_id] = record
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.post("/pathscientist/sessions/s-stop-api/stop")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "interrupted"
    assert data["stage"] == "interrupted"
    assert data["title_pending"] is False
    assert data["stop_reason"] == "user_cancelled"
    assert data["user_stop_requested"] is True
    assert data["stop_source"] == "pathlab_ui"
    assert isinstance(data["stop_requested_at"], float)


def test_delete_session_endpoint_removes_terminal_gateway_session():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []
    manager = route_module.PathScientistSessionManager()
    record = route_module.SessionRecord(
        session_id="s-delete",
        conversation_id="conv-delete",
        question="old run",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
    )
    manager._sessions[record.session_id] = record
    route_module._save_gateway_session_record(record)
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.delete("/pathscientist/sessions/s-delete")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert client.get("/pathscientist/sessions/s-delete").status_code == 404
    assert all(item["session_id"] != "s-delete" for item in client.get("/pathscientist/sessions").json()["items"])

    restarted = route_module.PathScientistSessionManager()
    route_module._SESSION_MANAGER = restarted
    assert all(record.session_id != "s-delete" for record in restarted.list())


def test_delete_session_endpoint_removes_safe_workspace(tmp_path):
    route_module = load_route_module()
    base_dir = tmp_path / "pathscientist-base"
    workspace = base_dir / "session_safe_delete"
    workspace.mkdir(parents=True)
    (workspace / "train.py").write_text("print('bye')\n", encoding="utf-8")
    route_module._resolve_pathscientist_base_dir = lambda: base_dir
    route_module._gateway_session_registry_path = (
        lambda: base_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []
    manager = route_module.PathScientistSessionManager()
    record = route_module.SessionRecord(
        session_id="s-delete-workspace",
        conversation_id="conv-delete-workspace",
        question="old run",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
        state={"workspace_dir": str(workspace)},
    )
    manager._sessions[record.session_id] = record
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.delete("/pathscientist/sessions/s-delete-workspace")

    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] is True
    assert data["workspace_deleted"] is True
    assert data["workspace_path"] == str(workspace.resolve())
    assert not workspace.exists()
    audit_path = base_dir / route_module.GATEWAY_DELETE_AUDIT_LOG
    audit = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[-1])
    assert audit["action"] == "delete_session"
    assert audit["source"] == "pathlab_ui"
    assert audit["session_id"] == "s-delete-workspace"
    assert audit["conversation_id"] == "conv-delete-workspace"
    assert audit["status_before_delete"] == "completed"
    assert audit["workspace_path"] == str(workspace.resolve())
    assert audit["workspace_deleted"] is True


def test_delete_session_endpoint_does_not_remove_workspace_outside_base(tmp_path):
    route_module = load_route_module()
    base_dir = tmp_path / "pathscientist-base"
    outside_workspace = tmp_path / "outside-workspace"
    outside_workspace.mkdir()
    (outside_workspace / "keep.txt").write_text("important\n", encoding="utf-8")
    route_module._resolve_pathscientist_base_dir = lambda: base_dir
    route_module._gateway_session_registry_path = (
        lambda: base_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    manager = route_module.PathScientistSessionManager()
    record = route_module.SessionRecord(
        session_id="s-delete-outside-workspace",
        conversation_id="conv-delete-outside-workspace",
        question="old run",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
        state={"workspace_dir": str(outside_workspace)},
    )
    manager._sessions[record.session_id] = record
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.delete("/pathscientist/sessions/s-delete-outside-workspace")

    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] is True
    assert data["workspace_deleted"] is False
    assert "outside PathScientist base dir" in data["workspace_delete_reason"]
    assert outside_workspace.exists()
    audit_path = base_dir / route_module.GATEWAY_DELETE_AUDIT_LOG
    audit = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[-1])
    assert audit["session_id"] == "s-delete-outside-workspace"
    assert audit["workspace_path"] == str(outside_workspace.resolve())
    assert audit["workspace_deleted"] is False
    assert "outside PathScientist base dir" in audit["workspace_delete_reason"]


def test_delete_session_endpoint_rejects_running_session():
    route_module = load_route_module()
    manager = route_module.PathScientistSessionManager()
    record = route_module.SessionRecord(
        session_id="s-delete-running",
        conversation_id="",
        question="live run",
        model="gpt-5.5",
        user_id="user-test",
        status="running",
        stage="execution",
    )
    manager._sessions[record.session_id] = record
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.delete("/pathscientist/sessions/s-delete-running")

    assert response.status_code == 409
    assert manager.get("s-delete-running") is record


def test_delete_session_hides_legacy_conversation():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    legacy = route_module.SessionRecord(
        session_id="legacydelete",
        conversation_id="conv-legacy-delete",
        question="legacy run",
        model="",
        user_id="user-test",
        status="completed",
        stage="completed",
    )
    route_module._scan_persisted_conversations = lambda *, curated_only=False: [legacy]
    manager = route_module.PathScientistSessionManager()
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    assert any(item["session_id"] == "legacydelete" for item in client.get("/pathscientist/sessions").json()["items"])

    response = client.delete("/pathscientist/sessions/legacydelete")

    assert response.status_code == 200
    assert all(item["session_id"] != "legacydelete" for item in client.get("/pathscientist/sessions").json()["items"])
    assert client.get("/pathscientist/sessions/legacydelete").status_code == 404


def test_session_summary_includes_workspace_disk_usage(tmp_path):
    route_module = load_route_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "metrics.json").write_bytes(b"12345")
    nested = workspace / "output"
    nested.mkdir()
    (nested / "model.bin").write_bytes(b"abcdef")
    record = route_module.SessionRecord(
        session_id="s-workspace-size",
        conversation_id="",
        question="disk usage",
        model="gpt-5.5",
        state={"workspace_dir": str(workspace)},
    )

    summary = record.summary()

    assert summary["workspace_path"] == str(workspace.resolve())
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        summary = record.summary()
        if "workspace_size_bytes" in summary:
            break
        time.sleep(0.02)
    assert summary["workspace_size_bytes"] >= 11


def test_session_summary_includes_training_progress_from_latest_run_log(tmp_path):
    route_module = load_route_module()
    workspace = tmp_path / "workspace"
    old_run = workspace / "output" / "runs" / "run_old"
    latest_run = workspace / "output" / "runs" / "run_latest"
    old_run.mkdir(parents=True)
    latest_run.mkdir(parents=True)
    old_log = old_run / "training.log"
    latest_log = latest_run / "training.log"
    old_log.write_text(
        "2026-06-17 20:00:00 | INFO | Epoch 1/10 | loss=0.50 | val_auc=0.700\n",
        encoding="utf-8",
    )
    latest_log.write_text(
        "\n".join(
            [
                "2026-06-17 22:27:20 | INFO | Epoch 4/30 | loss=0.1038 | val_loss=0.2353 | val_acc=0.9241 | val_auc=0.9683 | lr=0.000096",
                "2026-06-17 22:45:11 | INFO | Epoch 5/30 | loss=0.0868 | val_loss=0.2632 | val_acc=0.9310 | val_auc=0.9622 | lr=0.000093",
                "2026-06-17 23:18:23 | INFO | Epoch 7/30 | loss=0.0522 | val_loss=0.2950 | val_acc=0.9379 | val_auc=0.9636 | lr=0.000087",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(old_log, (1000, 1000))
    os.utime(latest_log, (2000, 2000))
    record = route_module.SessionRecord(
        session_id="s-training-progress",
        conversation_id="",
        question="train with epoch progress",
        model="gpt-5.5",
        status="running",
        stage="execution",
        state={"workspace_dir": str(workspace)},
    )

    summary = record.summary()

    progress = summary["training_progress"]
    assert progress["run_id"] == "run_latest"
    assert progress["current_epoch"] == 7
    assert progress["total_epochs"] == 30
    assert progress["current_val_auc"] == 0.9636
    assert progress["best_val_auc"] == 0.9683
    assert progress["best_epoch"] == 4
    assert progress["current_metrics"]["val_acc"] == 0.9379
    assert progress["log_path"] == str(latest_log.resolve())
    assert progress["updated_at"] == 2000


def test_session_summary_marks_quick_check_training_progress(tmp_path):
    route_module = load_route_module()
    workspace = tmp_path / "workspace"
    run_dir = workspace / "output" / "runs" / "run_quick"
    run_dir.mkdir(parents=True)
    log_path = run_dir / "training.log"
    log_path.write_text(
        "2026-06-17 22:27:20 | INFO | Epoch 1/2 | loss=0.1038 | val_auc=0.9683\n",
        encoding="utf-8",
    )
    os.utime(log_path, (2000, 2000))
    record = route_module.SessionRecord(
        session_id="s-training-progress-quick",
        conversation_id="",
        question="quick check training progress",
        model="gpt-5.5",
        status="running",
        stage="execution",
        state={
            "workspace_dir": str(workspace),
            "run_history": [
                {
                    "run_id": "run_quick",
                    "quick_check": True,
                    "run_kind": "quick_check",
                }
            ],
        },
    )

    progress = record.summary()["training_progress"]

    assert progress["run_id"] == "run_quick"
    assert progress["current_epoch"] == 1
    assert progress["total_epochs"] == 2
    assert progress["quick_check"] is True
    assert progress["run_kind"] == "quick_check"


def test_session_summary_marks_quick_check_from_run_metadata_without_history(tmp_path):
    route_module = load_route_module()
    workspace = tmp_path / "workspace"
    run_dir = workspace / "output" / "runs" / "run_quick_live"
    run_dir.mkdir(parents=True)
    log_path = run_dir / "training.log"
    log_path.write_text(
        "2026-06-17 22:27:20 | INFO | Epoch 1/2 | loss=0.1038 | val_auc=0.9683\n",
        encoding="utf-8",
    )
    (run_dir / "run_metadata.json").write_text(
        json.dumps({"quick_check": True, "run_kind": "training"}),
        encoding="utf-8",
    )
    os.utime(log_path, (2000, 2000))
    record = route_module.SessionRecord(
        session_id="s-training-progress-quick-live",
        conversation_id="",
        question="quick check training progress before run history",
        model="gpt-5.5",
        status="running",
        stage="execution",
        state={"workspace_dir": str(workspace), "run_history": []},
    )

    progress = record.summary()["training_progress"]

    assert progress["run_id"] == "run_quick_live"
    assert progress["quick_check"] is True
    assert progress["run_kind"] == "training"


def test_session_summary_includes_live_iteration_progress():
    route_module = load_route_module()
    record = route_module.SessionRecord(
        session_id="s-live-iteration",
        conversation_id="",
        question="train with iteration progress",
        model="gpt-5.5",
        status="running",
        stage="execution",
        state={"iteration_index": 0, "max_iterations": 3},
    )

    summary = record.summary()

    assert summary["current_iteration"] == 0
    assert summary["max_iterations"] == 3


def test_session_summary_does_not_block_on_uncached_workspace_size(tmp_path, monkeypatch):
    route_module = load_route_module()
    workspace = tmp_path / "slow-workspace"
    workspace.mkdir()

    def slow_disk_usage(_workspace):
        time.sleep(0.25)
        return 123

    monkeypatch.setattr(route_module, "_directory_disk_usage_bytes", slow_disk_usage)
    record = route_module.SessionRecord(
        session_id="s-slow-workspace-size",
        conversation_id="",
        question="disk usage",
        model="gpt-5.5",
        state={"workspace_dir": str(workspace)},
    )

    started = time.monotonic()
    summary = record.summary()
    elapsed = time.monotonic() - started

    assert elapsed < 0.1
    assert summary["workspace_path"] == str(workspace.resolve())
    assert "workspace_size_bytes" not in summary

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        summary = record.summary()
        if summary.get("workspace_size_bytes") == 123:
            break
        time.sleep(0.02)
    assert summary["workspace_size_bytes"] == 123


def test_live_event_projection_keeps_observations_distinct_from_tool_calls():
    route_module = load_route_module()
    event = SimpleNamespace(
        tool_name="run_experiment",
        action=None,
        observation=SimpleNamespace(exit_code=0, iteration=2),
    )

    payload = route_module._project_event(event, iteration=0)

    assert payload["kind"] == "tool_observation"
    assert payload["tool"] == "run_experiment"
    assert payload["iteration"] == 2
    assert payload["exit_code"] == 0


def test_normalized_state_event_infers_terminal_status_from_completed_stage():
    route_module = load_route_module()

    event = route_module._normalize_gateway_event(
        {"kind": "state", "stage": "completed", "state": {"stage": "completed"}}
    )

    assert event["status"] == "completed"
    assert event["summary"] == "Session completed"


def test_create_session_returns_503_when_config_unavailable():
    route_module = load_route_module()
    manager = route_module.PathScientistSessionManager()
    route_module._SESSION_MANAGER = manager

    def broken_config(_req):
        raise RuntimeError("missing config")

    route_module._build_config = broken_config

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.post(
        "/pathscientist/sessions",
        json={"question": "quick smoke", "max_iter": 1},
    )

    assert response.status_code == 503
    assert "missing config" in response.json()["detail"]


def test_create_session_returns_fast_and_marks_failed_when_runtime_unavailable():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._queue_session_title_generation = lambda record, config: None
    manager = route_module.PathScientistSessionManager()
    route_module._SESSION_MANAGER = manager

    def broken_runner():
        raise RuntimeError("missing runtime")

    route_module._load_runner = broken_runner

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.post(
        "/pathscientist/sessions",
        json={"question": "quick smoke", "max_iter": 1},
    )

    assert response.status_code == 200
    created = response.json()

    import time as _time
    for _ in range(20):
        detail = client.get(f"/pathscientist/sessions/{created['session_id']}").json()
        if detail["status"] == "failed":
            break
        _time.sleep(0.05)
    else:
        raise AssertionError("session did not fail after runtime load error")

    assert detail["status"] == "failed"
    assert "missing runtime" in detail["error"]


def test_list_and_detail_include_created_session():
    client = TestClient(make_app())
    created = client.post(
        "/pathscientist/sessions",
        json={"question": "list me"},
    ).json()

    listed = client.get("/pathscientist/sessions").json()
    detail = client.get(f"/pathscientist/sessions/{created['session_id']}").json()

    assert any(item["session_id"] == created["session_id"] for item in listed["items"])
    assert detail["question"] == "list me"
    assert "events" in detail


def test_default_pathscientist_base_dir_is_local_writable(monkeypatch):
    monkeypatch.delenv("PATHSCIENTIST_BASE_DIR", raising=False)
    route_module = load_route_module()
    from backend.pathscientist.runtime.session import _resolve_base_dir

    base_dir = _resolve_base_dir()

    assert str(base_dir).endswith("pathlab-client/uploads/pathscientist")
    assert not str(base_dir).startswith("/project/")
    assert route_module._resolve_pathscientist_base_dir() == base_dir.resolve()


def test_list_sessions_uses_default_base_dir_without_env(monkeypatch, tmp_path):
    monkeypatch.delenv("PATHSCIENTIST_BASE_DIR", raising=False)
    route_module = load_route_module()
    from backend.pathscientist.runtime import session as runtime_session

    default_base_dir = tmp_path / "pathscientist-default"
    monkeypatch.setattr(runtime_session, "DEFAULT_BASE_DIR", str(default_base_dir))
    manager = route_module.PathScientistSessionManager()
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.get("/pathscientist/sessions")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert route_module._resolve_pathscientist_base_dir() == default_base_dir.resolve()
    assert (default_base_dir / route_module.GATEWAY_SESSION_REGISTRY).exists() is False


def test_events_stream_replays_session_events():
    client = TestClient(make_app())
    created = client.post(
        "/pathscientist/sessions",
        json={"question": "stream me"},
    ).json()

    with client.stream("GET", f"/pathscientist/sessions/{created['session_id']}/events") as response:
        assert response.status_code == 200
        body = next(response.iter_text())

    assert "event:" in body
    assert "data:" in body


def test_events_carry_monotonic_seq():
    """Every emitted event must carry a strictly increasing ``seq`` so the
    frontend can dedup without relying on second-resolution timestamps."""
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    manager = route_module.PathScientistSessionManager()

    def fake_runner(_config, _question, emit):
        emit({"kind": "stage_enter", "stage": "grounding"})
        emit({"kind": "stage_exit", "stage": "grounding"})
        return {"stage": "completed"}

    manager.create_runner = fake_runner
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    created = client.post("/pathscientist/sessions", json={"question": "seq"}).json()
    # Wait for the worker thread to finish so all events are in.
    import time as _time
    for _ in range(20):
        detail = client.get(f"/pathscientist/sessions/{created['session_id']}").json()
        if detail["status"] in {"completed", "failed"}:
            break
        _time.sleep(0.05)
    else:
        raise AssertionError("session did not complete in time")

    seqs = [event["seq"] for event in detail["events"]]
    assert seqs == sorted(seqs), f"seq must be monotonic, got {seqs}"
    assert len(seqs) == len(set(seqs)), "seq must be unique"
    assert seqs[0] == 1


def test_gateway_events_survive_manager_restart():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._generate_session_title = lambda question, config=None: "Persistent events"
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []
    manager = route_module.PathScientistSessionManager()

    def fake_runner(_config, _question, emit):
        emit({"kind": "stage_enter", "stage": "grounding"})
        emit({"kind": "tool_call", "tool": "python", "iteration": 0})
        return {"stage": "completed", "conversation_id": "conv_persisted_events"}

    manager.create_runner = fake_runner
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    created = client.post(
        "/pathscientist/sessions",
        json={"question": "persist event stream"},
    ).json()
    import time as _time
    for _ in range(20):
        detail = client.get(f"/pathscientist/sessions/{created['session_id']}").json()
        if detail["status"] in {"completed", "failed"}:
            break
        _time.sleep(0.05)
    else:
        raise AssertionError("session did not complete in time")

    route_module._SESSION_MANAGER = route_module.PathScientistSessionManager()
    restarted_app = FastAPI()
    restarted_app.include_router(route_module.router)
    install_fake_user(restarted_app, route_module)
    restarted_client = TestClient(restarted_app)

    restored = restarted_client.get(
        f"/pathscientist/sessions/{created['session_id']}"
    ).json()

    restored_kinds = [event["kind"] for event in restored["events"]]
    assert "stage_enter" in restored_kinds
    assert "tool_call" in restored_kinds
    seqs = [event["seq"] for event in restored["events"]]
    assert seqs == sorted(seqs)


def test_gateway_runner_progress_callback_streams_director_state():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )

    def fake_dump(state):
        return state if isinstance(state, dict) else dict(state)

    def fake_runner(_config, question, *, auto_approve=True, visualizer=None, progress_callback=None):
        if progress_callback is not None:
            progress_callback({
                "session_id": "internal-live",
                "conversation_id": "conv-live-progress",
                "stage": "grounding",
                "objective": {"question": question, "success_metric": "auc"},
            })
            progress_callback({
                "session_id": "internal-live",
                "conversation_id": "conv-live-progress",
                "stage": "acquisition",
                "objective": {"question": question, "success_metric": "auc"},
                "selected_dataset": {"name": "PANDA"},
            })
        return ({
            "session_id": "internal-live",
            "conversation_id": "conv-live-progress",
            "stage": "completed",
        }, object(), object())

    route_module._load_runner = lambda: (fake_runner, fake_dump)
    manager = route_module.PathScientistSessionManager()
    emitted: list[dict] = []

    final_state = manager._invoke_runner(
        object(),
        route_module.StartPathScientistSessionRequest(question="stream director progress"),
        emitted.append,
    )

    state_events = [event for event in emitted if event["kind"] == "state"]
    stages = [event["state"].get("stage") for event in state_events]

    assert "grounding" in stages
    assert "acquisition" in stages
    assert final_state["conversation_id"] == "conv-live-progress"


def test_gateway_runner_progress_callback_includes_download_progress_sidecar(tmp_path):
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._resolve_pathscientist_base_dir = lambda: tmp_path
    workspace = tmp_path / "session_internal-live"
    progress_path = workspace / ".dataset" / "download_progress.json"
    progress_path.parent.mkdir(parents=True)
    progress_path.write_text(
        json.dumps({
            "status": "downloading",
            "dataset_id": "kaggle:panda",
            "provider": "kaggle",
            "downloaded_bytes": 5 * 1024 * 1024,
            "bytes_total": 20 * 1024 * 1024,
            "speed_bps": 1024 * 1024,
            "eta_seconds": 15,
            "current_file": "panda.zip",
        }),
        encoding="utf-8",
    )

    def fake_dump(state):
        return state if isinstance(state, dict) else dict(state)

    def fake_runner(_config, question, *, auto_approve=True, visualizer=None, progress_callback=None):
        if progress_callback is not None:
            progress_callback({
                "session_id": "internal-live",
                "conversation_id": "conv-live-progress",
                "stage": "acquisition",
                "objective": {"question": question, "success_metric": "auc"},
            })
        return ({
            "session_id": "internal-live",
            "conversation_id": "conv-live-progress",
            "stage": "pre_execution_ready",
        }, object(), object())

    route_module._load_runner = lambda: (fake_runner, fake_dump)
    manager = route_module.PathScientistSessionManager()
    emitted: list[dict] = []

    final_state = manager._invoke_runner(
        object(),
        route_module.StartPathScientistSessionRequest(question="stream download progress"),
        emitted.append,
    )

    state_events = [event for event in emitted if event["kind"] == "state"]
    assert state_events[-1]["state"]["download_progress"]["status"] == "downloading"
    assert state_events[-1]["state"]["download_progress"]["downloaded_bytes"] == 5 * 1024 * 1024
    assert final_state["download_progress"]["current_file"] == "panda.zip"


def test_download_progress_poller_emits_state_events(tmp_path):
    route_module = load_route_module()
    route_module.DOWNLOAD_PROGRESS_POLL_SECONDS = 0.01
    route_module._resolve_pathscientist_base_dir = lambda: tmp_path
    workspace = tmp_path / "session_poll-live"
    progress_path = workspace / ".dataset" / "download_progress.json"
    progress_path.parent.mkdir(parents=True)
    progress_path.write_text(
        json.dumps({
            "status": "downloading",
            "dataset_id": "kaggle:panda",
            "provider": "kaggle",
            "downloaded_bytes": 123,
        }),
        encoding="utf-8",
    )
    record = route_module.SessionRecord(
        session_id="web-live",
        conversation_id="",
        question="download data",
        model="gpt-5.5",
        status="running",
        stage="acquisition",
        state={"session_id": "poll-live", "stage": "acquisition"},
    )

    stop = route_module._start_download_progress_poller(record)
    try:
        assert record.wait_for_events(0, timeout=1.0)
    finally:
        stop()

    assert record.events[-1]["state"]["download_progress"]["downloaded_bytes"] == 123
    assert record.state["download_progress"]["provider"] == "kaggle"


def test_list_sessions_includes_curated_legacy_by_default():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    manager = route_module.PathScientistSessionManager()
    route_module._SESSION_MANAGER = manager

    legacy = route_module.SessionRecord(
        session_id="legacy123",
        conversation_id="legacy-conv",
        question="meaningful CLI run",
        model="",
        user_id="user-test",
        status="finished",
        stage="finished",
    )
    route_module._scan_persisted_conversations = lambda *, curated_only=False: [legacy]

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    listed = client.get("/pathscientist/sessions").json()

    assert any(item["session_id"] == "legacy123" for item in listed["items"])


def test_list_sessions_deduplicates_legacy_rows_when_gateway_has_same_conversation():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    manager = route_module.PathScientistSessionManager()
    route_module._SESSION_MANAGER = manager

    gateway = route_module.SessionRecord(
        session_id="gateway123",
        conversation_id="conv-dup",
        question="same run",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
    )
    legacy = route_module.SessionRecord(
        session_id="legacy123",
        conversation_id="conv-dup",
        question="same run",
        model="",
        user_id="user-test",
        status="finished",
        stage="completed",
    )
    with manager._lock:
        manager._sessions[gateway.session_id] = gateway
    route_module._scan_persisted_conversations = lambda *, curated_only=False: [legacy]

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    listed = client.get("/pathscientist/sessions").json()
    session_ids = [item["session_id"] for item in listed["items"]]

    assert session_ids == ["gateway123"]


def test_list_sessions_deduplicates_legacy_rows_when_gateway_has_live_state_conversation():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    manager = route_module.PathScientistSessionManager()
    route_module._SESSION_MANAGER = manager

    gateway = route_module.SessionRecord(
        session_id="gateway123",
        conversation_id="",
        question="same live run",
        model="gpt-5.5",
        user_id="user-test",
        status="running",
        stage="execution",
        state={"conversation_id": "conv-live-dup", "session_id": "workspace123"},
    )
    legacy = route_module.SessionRecord(
        session_id="legacy123",
        conversation_id="conv-live-dup",
        question="same live run",
        model="",
        user_id="user-test",
        status="running",
        stage="execution",
    )
    with manager._lock:
        manager._sessions[gateway.session_id] = gateway
    route_module._scan_persisted_conversations = lambda *, curated_only=False: [legacy]

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    listed = client.get("/pathscientist/sessions").json()
    session_ids = [item["session_id"] for item in listed["items"]]

    assert session_ids == ["gateway123"]


def test_list_sessions_deduplicates_legacy_rows_after_restart_using_persisted_state_event():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    gateway = route_module.SessionRecord(
        session_id="gateway123",
        conversation_id="",
        question="same restarted run",
        model="gpt-5.5",
        user_id="user-test",
        status="running",
        stage="starting",
    )
    route_module._save_gateway_session_record(gateway)
    route_module._append_gateway_session_event(
        gateway.session_id,
        {
            "seq": 1,
            "kind": "state",
            "status": "running",
            "stage": "execution",
            "state": {
                "conversation_id": "conv-restart-dup",
                "session_id": "workspace123",
                "stage": "execution",
            },
        },
    )
    legacy = route_module.SessionRecord(
        session_id="legacy123",
        conversation_id="conv-restart-dup",
        question="same restarted run",
        model="",
        user_id="user-test",
        status="running",
        stage="execution",
    )
    route_module._scan_persisted_conversations = lambda *, curated_only=False: [legacy]
    route_module._SESSION_MANAGER = route_module.PathScientistSessionManager()

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    listed = client.get("/pathscientist/sessions").json()

    assert [item["session_id"] for item in listed["items"]] == ["gateway123"]
    assert listed["items"][0]["conversation_id"] == "conv-restart-dup"


def test_deleted_legacy_tombstone_does_not_hide_gateway_session_with_same_conversation_after_restart():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    gateway = route_module.SessionRecord(
        session_id="gateway123",
        conversation_id="conv-dup",
        question="same run",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
    )
    route_module._save_gateway_session_record(gateway)
    route_module._mark_gateway_session_deleted(
        session_id="legacy123",
        conversation_id="conv-dup",
    )
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []
    route_module._SESSION_MANAGER = route_module.PathScientistSessionManager()

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    listed = client.get("/pathscientist/sessions").json()

    assert [item["session_id"] for item in listed["items"]] == ["gateway123"]


def test_legacy_sessions_include_generated_title():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._generate_session_title = lambda question, config=None: "Legacy Gleason MIL"
    manager = route_module.PathScientistSessionManager()
    route_module._SESSION_MANAGER = manager

    question = "我要训练一个前列腺 WSI 的 Gleason score/ISUP grading MIL分类模型。"
    legacy = route_module.SessionRecord(
        session_id="legacy456",
        conversation_id="legacy-conv-456",
        question=question,
        model="",
        title=route_module._generate_session_title(question),
        user_id="user-test",
        status="finished",
        stage="finished",
    )
    route_module._scan_persisted_conversations = lambda *, curated_only=False: [legacy]

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    listed = client.get("/pathscientist/sessions").json()
    item = next(item for item in listed["items"] if item["session_id"] == "legacy456")

    assert item["title"] == "Legacy Gleason MIL"


def test_session_title_helpers_sanitize_and_fallback():
    route_module = load_route_module()

    assert route_module._clean_session_title('"Gastritis WSI MIL grading."') == (
        "Gastritis WSI MIL grading"
    )
    fallback = route_module._fallback_session_title(
        "我想训练一个 chronic gastritis inflammation grading 的 WSI MIL 分类任务"
    )

    assert fallback == "Chronic gastritis WSI MIL grading"


def test_title_generation_forces_chat_completion_for_codex_relay(monkeypatch):
    route_module = load_route_module()
    from backend.pathscientist.config import PathScientistConfig
    from backend.pathscientist import llm_client

    captured: dict[str, str] = {}
    sdk_module = types.ModuleType("openhands.sdk.llm")
    sdk_module.Message = lambda **kwargs: kwargs
    sdk_module.TextContent = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "openhands.sdk.llm", sdk_module)

    monkeypatch.setattr(llm_client, "build_chat_llm", lambda *args, **kwargs: object())

    def fake_invoke(_llm, *, messages, wire_api="", **_kwargs):
        captured["wire_api"] = wire_api
        return {"text": "TCGA NSCLC GDC WSI Acquisition"}

    monkeypatch.setattr(llm_client, "invoke_chat_llm", fake_invoke)
    monkeypatch.setattr(llm_client, "extract_text", lambda response: response["text"])

    title = route_module._generate_session_title(
        "我想获取 TCGA 的 NSCLC 诊断病理 WSI，从 GDC 下载并整理 metadata",
        PathScientistConfig(llm_model="gpt-5.5", llm_profile="codex-relay"),
    )

    assert captured["wire_api"] == "completion"
    assert title == "TCGA NSCLC GDC WSI Acquisition"


def test_codex_relay_chat_llm_uses_xhigh_reasoning(monkeypatch):
    from backend.pathscientist.config import PathScientistConfig
    from backend.pathscientist.llm_client import build_chat_llm

    captured: dict[str, object] = {}

    class FakeLLM:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.stream = bool(kwargs.get("stream", False))

    openhands_module = types.ModuleType("openhands")
    sdk_module = types.ModuleType("openhands.sdk")
    llm_module = types.ModuleType("openhands.sdk.llm")
    llm_module.LLM = FakeLLM
    monkeypatch.setitem(sys.modules, "openhands", openhands_module)
    monkeypatch.setitem(sys.modules, "openhands.sdk", sdk_module)
    monkeypatch.setitem(sys.modules, "openhands.sdk.llm", llm_module)

    build_chat_llm(
        PathScientistConfig(
            llm_model="gpt-5.5",
            llm_api_key="relay-key",
            llm_base_url="https://relay.1hui.wang/v1",
            llm_profile="codex-relay",
            llm_wire_api="completion",
        ),
        component="PathScientist test",
        usage_id="pathscientist_test",
        temperature=0.0,
    )

    assert captured["model"] == "openai/gpt-5.5"
    assert captured["stream"] is True
    assert captured["reasoning_effort"] == "xhigh"


def test_fallback_title_keeps_tcga_nsclc_data_acquisition_terms():
    route_module = load_route_module()

    title = route_module._fallback_session_title(
        "我想获取TCGA 的 NSCLC 诊断病理 WSI，不训练模型，"
        "请把 NSCLC 拆成 TCGA-LUAD 和 TCGA-LUSC，从 GDC 查询 Slide Image 文件并整理 metadata"
    )

    assert title == "TCGA NSCLC LUAD LUSC GDC WSI data acquisition"


def test_legacy_running_status_becomes_interrupted_when_stale():
    route_module = load_route_module()
    updated_at = "2026-05-18T00:00:00"
    updated_ts = route_module._timestamp_to_epoch(updated_at)

    fresh = route_module._legacy_runtime_status(
        {"execution_status": "running", "updated_at": updated_at},
        now=updated_ts + 60,
    )
    stale = route_module._legacy_runtime_status(
        {"execution_status": "running", "updated_at": updated_at},
        now=updated_ts + route_module.LEGACY_RUNNING_STALE_SECONDS + 1,
    )

    assert fresh.status == "running"
    assert fresh.stage == "running"
    assert fresh.error == ""
    assert stale.status == "interrupted"
    assert stale.stage == "interrupted"
    assert "No persisted updates" in stale.error
    assert "for " not in stale.error
    assert "601s" not in stale.error


def test_live_progress_state_projects_current_stage_from_agent_state():
    route_module = load_route_module()
    conversation_state = SimpleNamespace(
        agent_state={
            "research_session": {
                "stage": "execution",
                "stage_started_at": 100.0,
                "stage_history": [
                    {"stage": "intake", "started_at": 90.0, "ended_at": 95.0, "duration_sec": 5.0},
                    {"stage": "execution", "started_at": 100.0},
                ],
                "iteration_index": 2,
                "max_iterations": 4,
                "best_metric_value": 0.8123,
                "best_run_id": "run_b",
                "objective": {"question": "Train a MIL model", "success_metric": "auc"},
                "acquisition_status": "prepared",
                "acquisition_notes": "Existing feature tensors detected.",
                "selected_dataset": {
                    "name": "TCGA-LUAD + TCGA-LUSC",
                    "provider": "local",
                    "access": "existing",
                },
                "dataset_manifest_path": "/data/pathscientist/manifests/nsclc.json",
                "dataset_candidates": [{"name": "TCGA-LUAD"}, {"name": "TCGA-LUSC"}],
                "data_readiness": {
                    "status": "features_ready",
                    "features_dir": "/data/features/virchow2/nsclc",
                    "splits_file": "/data/splits/nsclc.csv",
                },
                "execution_plan": {
                    "status": "ready",
                    "steps": [{"id": "train_mil", "skill": "mil_classification"}],
                },
                "grounding": {
                    "selected_skill": "mil_classification",
                    "papers": [{"title": "TransMIL", "year": 2021, "source": "pubmed"}],
                    "online_literature_count": 7,
                },
                "latest_review": {"summary": "Iter 2 improved AUC.", "decision": "continue_execution"},
                "review_history": [{"summary": "Iter 2 improved AUC.", "decision": "continue_execution"}],
                "review_decision": "continue_execution",
            },
            "iteration_state": {"last_run_id": "run_b"},
        },
    )

    state = route_module._build_live_progress_state(conversation_state)

    assert state["stage"] == "execution"
    assert state["stage_started_at"] == 100.0
    assert state["stage_history"][0]["stage"] == "intake"
    assert state["iteration_index"] == 2
    assert state["max_iterations"] == 4
    assert state["best_metric_value"] == 0.8123
    assert state["best_run_id"] == "run_b"
    assert state["objective"]["success_metric"] == "auc"
    assert state["acquisition_status"] == "prepared"
    assert state["acquisition_notes"] == "Existing feature tensors detected."
    assert state["selected_dataset"]["name"] == "TCGA-LUAD + TCGA-LUSC"
    assert state["dataset_manifest_path"] == "/data/pathscientist/manifests/nsclc.json"
    assert len(state["dataset_candidates"]) == 2
    assert state["data_readiness"]["status"] == "features_ready"
    assert state["execution_plan"]["steps"][0]["skill"] == "mil_classification"
    assert state["grounding"]["selected_skill"] == "mil_classification"
    assert state["grounding"]["papers"][0]["source"] == "pubmed"
    assert state["grounding"]["online_literature_count"] == 7
    assert state["latest_review"]["summary"] == "Iter 2 improved AUC."
    assert state["review_history"][0]["decision"] == "continue_execution"
    assert state["review_decision"] == "continue_execution"


def test_live_state_event_updates_record_stage_before_completion():
    route_module = load_route_module()
    record = route_module.SessionRecord(
        session_id="s-live",
        conversation_id="",
        question="live progress",
        model="gpt-5.5",
        status="running",
        stage="starting",
    )

    route_module._apply_live_state_event_to_record(
        record,
        {"kind": "state", "status": "running", "state": {"stage": "grounding", "iteration_index": 0}},
    )

    assert record.stage == "grounding"
    assert record.state["stage"] == "grounding"
    assert record.state["iteration_index"] == 0


def test_live_state_event_promotes_conversation_id_before_completion():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    record = route_module.SessionRecord(
        session_id="s-live",
        conversation_id="",
        question="live progress",
        model="gpt-5.5",
        status="running",
        stage="starting",
    )

    route_module._apply_live_state_event_to_record(
        record,
        {
            "kind": "state",
            "status": "running",
            "state": {
                "stage": "execution",
                "conversation_id": "conv-live",
                "session_id": "workspace-live",
            },
        },
    )

    assert record.conversation_id == "conv-live"
    assert record.state["conversation_id"] == "conv-live"


def test_record_state_sse_payload_exposes_running_stage():
    route_module = load_route_module()
    record = route_module.SessionRecord(
        session_id="s-live",
        conversation_id="conv-live",
        question="live progress",
        model="gpt-5.5",
        status="running",
        stage="execution",
        state={"stage": "execution", "stage_started_at": 100.0},
    )

    payload = route_module._record_state_sse_payload(record)

    assert payload["kind"] == "state"
    assert payload["status"] == "running"
    assert payload["stage"] == "execution"
    assert payload["state"]["stage_started_at"] == 100.0


def test_gateway_events_are_normalized_for_execution_ui():
    route_module = load_route_module()

    normalized = route_module._normalize_gateway_event(
        {
            "kind": "tool_call",
            "tool": "run_experiment",
            "iteration": "2",
            "action": {"script": "train.py"},
        }
    )
    failed = route_module._normalize_gateway_event(
        {
            "kind": "tool_observation",
            "tool": "validate_script",
            "exit_code": 1,
            "observation": "ImportError: missing package",
        }
    )

    assert normalized["ui_kind"] == "tool"
    assert normalized["stage"] == "execution"
    assert normalized["iteration"] == 2
    assert normalized["summary"] == "run_experiment"
    assert normalized["severity"] == "info"
    assert failed["ui_kind"] == "tool"
    assert failed["stage"] == "execution"
    assert failed["severity"] == "error"
    assert "validate_script" in failed["summary"]


def test_build_config_uses_frontend_backend_defaults_without_forcing_extractor(monkeypatch, tmp_path):
    route_module = load_route_module()
    from backend.common.config import Config

    for name in (
        "PATHSCIENTIST_ENV_FILE",
        "PATHSCIENTIST_LLM_MODEL",
        "PATHSCIENTIST_LLM_API_KEY",
        "PATHSCIENTIST_LLM_BASE_URL",
        "PATHSCIENTIST_LLM_PROFILE",
        "PATHSCIENTIST_LLM_WIRE_API",
        "PATHSCIENTIST_SANDBOX",
        "PATHSCIENTIST_LITERATURE_ONLINE",
        "PATHSCIENTIST_LITERATURE_ONLINE_MAX_RESULTS",
        "PATHSCIENTIST_AUTO_ACQUIRE_DATA",
        "PATHSCIENTIST_DOWNLOAD_POLICY",
        "PATHSCIENTIST_MAX_DOWNLOAD_SIZE_GB",
        "PATHSCIENTIST_ALLOW_LARGE_DOWNLOADS",
        "PATHSCIENTIST_DATASET_CACHE_DIR",
        "PATHSCIENTIST_GENERATE_PAPER_DRAFT",
        "PATHSCIENTIST_FEATURE_EXTRACTOR_MODE",
        "PATHSCIENTIST_FEATURE_EXTRACTOR",
        "PATHSCIENTIST_MIL_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Config, "get_uploads_dir", staticmethod(lambda: tmp_path / "uploads"))
    monkeypatch.setenv("PATHSCIENTIST_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setattr(
        Config,
        "get_global_settings",
        staticmethod(
            lambda: {
                "local_vllm_enabled": False,
                "local_vllm_base_url": "http://127.0.0.1:8000/v1",
                "local_vllm_model": "",
                "local_vllm_api_key": "",
                "openrouter_api_key": "",
                "openrouter_base_url": "https://openrouter.ai/api/v1",
                "openrouter_model": "qwen/qwen3.5-plus-02-15",
            }
        ),
    )

    config = route_module._build_config(
        route_module.StartPathScientistSessionRequest(question="align defaults")
    )

    assert config.llm_model == "gpt-5.5"
    assert config.llm_profile == "codex-relay"
    assert config.llm_wire_api == "completion"
    assert config.llm_base_url == "https://openrouter.ai/api/v1"
    assert os.environ["PATHSCIENTIST_LLM_MODEL"] == "gpt-5.5"
    assert os.environ["PATHSCIENTIST_LLM_PROFILE"] == "codex-relay"
    assert os.environ["PATHSCIENTIST_LLM_WIRE_API"] == "completion"
    assert config.sandbox_mode == "auto"
    assert config.max_iterations == 5
    assert config.literature_online_enabled is True
    assert config.literature_online_max_results == 10
    assert config.auto_acquire_data is True
    assert config.download_policy == "all"
    assert config.max_download_size_gb == 500
    assert config.allow_large_downloads is True
    assert config.dataset_cache_dir == str(tmp_path / "uploads")
    assert os.environ["PATHSCIENTIST_GENERATE_PAPER_DRAFT"] == "0"
    assert os.environ["PATHSCIENTIST_FEATURE_EXTRACTOR_MODE"] == "auto"
    assert os.environ.get("PATHSCIENTIST_FEATURE_EXTRACTOR", "") == ""
    assert os.environ.get("PATHSCIENTIST_MIL_MODEL", "") == ""


def test_build_config_ignores_pathlab_local_vllm_model(monkeypatch, tmp_path):
    route_module = load_route_module()
    from backend.common.config import Config

    for name in (
        "PATHSCIENTIST_ENV_FILE",
        "PATHSCIENTIST_LLM_MODEL",
        "PATHSCIENTIST_LLM_API_KEY",
        "PATHSCIENTIST_LLM_BASE_URL",
        "PATHSCIENTIST_LLM_PROFILE",
        "PATHSCIENTIST_LLM_WIRE_API",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATHSCIENTIST_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setattr(
        Config,
        "get_global_settings",
        staticmethod(
            lambda: {
                "local_vllm_enabled": True,
                "local_vllm_base_url": "http://local-vllm:8000/v1",
                "local_vllm_model": "local-model",
                "local_vllm_api_key": "local-key",
                "openrouter_api_key": "openrouter-key",
                "openrouter_base_url": "https://openrouter.ai/api/v1",
                "openrouter_model": "qwen/qwen3.5-plus-02-15",
            }
        ),
    )

    config = route_module._build_config(
        route_module.StartPathScientistSessionRequest(
            question="use default pathscientist llm",
            model="gpt-5.5",
        )
    )

    assert config.llm_profile == "codex-relay"
    assert config.llm_wire_api == "completion"
    assert config.llm_model == "gpt-5.5"
    assert config.llm_base_url == "https://openrouter.ai/api/v1"
    assert config.llm_api_key == "openrouter-key"


def test_build_config_reuses_pathlab_openrouter_credentials_not_model(monkeypatch, tmp_path):
    route_module = load_route_module()
    from backend.common.config import Config

    for name in (
        "PATHSCIENTIST_ENV_FILE",
        "PATHSCIENTIST_LLM_MODEL",
        "PATHSCIENTIST_LLM_API_KEY",
        "PATHSCIENTIST_LLM_BASE_URL",
        "PATHSCIENTIST_LLM_PROFILE",
        "PATHSCIENTIST_LLM_WIRE_API",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATHSCIENTIST_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setattr(
        Config,
        "get_global_settings",
        staticmethod(
            lambda: {
                "local_vllm_enabled": False,
                "local_vllm_base_url": "http://local-vllm:8000/v1",
                "local_vllm_model": "local-model",
                "local_vllm_api_key": "local-key",
                "openrouter_api_key": "openrouter-key",
                "openrouter_base_url": "https://openrouter.ai/api/v1",
                "openrouter_model": "qwen/qwen3.5-plus-02-15",
            }
        ),
    )

    config = route_module._build_config(
        route_module.StartPathScientistSessionRequest(
            question="reuse pathlab relay credentials",
            model="gpt-5.5",
        )
    )

    assert config.llm_profile == "codex-relay"
    assert config.llm_wire_api == "completion"
    assert config.llm_model == "gpt-5.5"
    assert config.llm_base_url == "https://openrouter.ai/api/v1"
    assert config.llm_api_key == "openrouter-key"


def test_build_config_codex_relay_default_overrides_stale_model_env(monkeypatch, tmp_path):
    route_module = load_route_module()
    from backend.common.config import Config
    from backend.pathscientist.llm_client import resolve_llm_runtime_config

    monkeypatch.setenv("PATHSCIENTIST_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("PATHSCIENTIST_LLM_MODEL", "gpt-5.5")
    monkeypatch.setenv("PATHSCIENTIST_LLM_API_KEY", "stale-key")
    monkeypatch.setenv("PATHSCIENTIST_LLM_BASE_URL", "https://relay.example/openai/v1")
    monkeypatch.setenv("PATHSCIENTIST_LLM_PROFILE", "codex-relay")
    monkeypatch.setenv("PATHSCIENTIST_LLM_WIRE_API", "responses")
    monkeypatch.setattr(
        Config,
        "get_global_settings",
        staticmethod(
            lambda: {
                "local_vllm_enabled": False,
                "local_vllm_base_url": "http://local-vllm:8000/v1",
                "local_vllm_model": "local-model",
                "local_vllm_api_key": "local-key",
                "openrouter_api_key": "openrouter-key",
                "openrouter_base_url": "https://openrouter.ai/api/v1",
                "openrouter_model": "qwen/qwen3.5-plus-02-15",
            }
        ),
    )

    config = route_module._build_config(
        route_module.StartPathScientistSessionRequest(
            question="keep relay default model",
            model="gpt-5.5",
        )
    )
    runtime = resolve_llm_runtime_config(config, component="PathScientist test")

    assert runtime.profile == "codex-relay"
    assert runtime.wire_api == "completion"
    assert runtime.model == "openai/gpt-5.5"
    assert runtime.base_url == "https://openrouter.ai/api/v1"
    assert runtime.api_key == "openrouter-key"


def test_build_config_inherits_pathlab_huggingface_token(monkeypatch, tmp_path):
    route_module = load_route_module()
    from backend.common.config import Config

    monkeypatch.setenv("PATHSCIENTIST_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("PATHSCIENTIST_HUGGINGFACE_TOKEN", "stale-pathscientist-token")
    monkeypatch.setenv("HF_TOKEN", "stale-hf-token")
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "stale-hub-token")
    monkeypatch.setattr(
        Config,
        "get_global_settings",
        staticmethod(
            lambda: {
                "local_vllm_enabled": False,
                "openrouter_base_url": "https://openrouter.ai/api/v1",
                "openrouter_model": "qwen/qwen3.5-plus-02-15",
                "openrouter_api_key": "openrouter-key",
                "huggingface_token": "pathlab-hf-token",
            }
        ),
    )

    config = route_module._build_config(
        route_module.StartPathScientistSessionRequest(question="inherit pathlab hf token")
    )

    assert config.huggingface_token == "pathlab-hf-token"
    assert os.environ["PATHSCIENTIST_HUGGINGFACE_TOKEN"] == "pathlab-hf-token"
    assert os.environ["HF_TOKEN"] == "pathlab-hf-token"
    assert os.environ["HUGGING_FACE_HUB_TOKEN"] == "pathlab-hf-token"


def test_build_config_fallback_keeps_codex_relay_profile(monkeypatch, tmp_path):
    route_module = load_route_module()
    from backend.common.config import Config
    from backend.pathscientist.llm_client import resolve_llm_runtime_config

    monkeypatch.setenv("PATHSCIENTIST_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("PATHSCIENTIST_LLM_MODEL", "stale-model")
    monkeypatch.setenv("PATHSCIENTIST_LLM_API_KEY", "stale-key")
    monkeypatch.setenv("PATHSCIENTIST_LLM_BASE_URL", "https://relay.example/openai/v1")
    monkeypatch.setenv("PATHSCIENTIST_LLM_PROFILE", "codex-relay")
    monkeypatch.setenv("PATHSCIENTIST_LLM_WIRE_API", "responses")
    monkeypatch.setattr(Config, "get_global_settings", staticmethod(lambda: {}))

    config = route_module._build_config(
        route_module.StartPathScientistSessionRequest(question="fallback no relay")
    )
    runtime = resolve_llm_runtime_config(config, component="PathScientist test")

    assert runtime.profile == "codex-relay"
    assert runtime.wire_api == "completion"
    assert runtime.model == "openai/gpt-5.5"
    assert runtime.api_key == "stale-key"
    assert runtime.base_url == "https://relay.example/openai/v1"


def test_build_config_fixed_extractor_mode_keeps_virchow2_compatibility(monkeypatch, tmp_path):
    route_module = load_route_module()
    monkeypatch.setenv("PATHSCIENTIST_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("PATHSCIENTIST_FEATURE_EXTRACTOR_MODE", "fixed")
    monkeypatch.delenv("PATHSCIENTIST_FEATURE_EXTRACTOR", raising=False)

    route_module._build_config(
        route_module.StartPathScientistSessionRequest(question="fixed extractor")
    )

    assert os.environ["PATHSCIENTIST_FEATURE_EXTRACTOR_MODE"] == "fixed"
    assert os.environ["PATHSCIENTIST_FEATURE_EXTRACTOR"] == "virchow2"


def test_build_config_defaults_pathlab_ckpt_dir_to_main_extractor_root(monkeypatch, tmp_path):
    route_module = load_route_module()
    from backend.common.config import Config

    monkeypatch.delenv("PATHLAB_CKPT_DIR", raising=False)
    monkeypatch.setenv("PATHSCIENTIST_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setattr(Config, "get_uploads_dir", staticmethod(lambda: tmp_path / "uploads"))
    monkeypatch.setattr(Config, "get_global_settings", staticmethod(lambda: {}))

    route_module._build_config(
        route_module.StartPathScientistSessionRequest(question="align checkpoint root")
    )

    assert os.environ["PATHLAB_CKPT_DIR"] == str(
        route_module.SERVER_ROOT / "backend" / "ai" / "extractors" / "checkpoints"
    )


def test_include_persisted_exposes_uncurated_legacy():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="pathscientist-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    manager = route_module.PathScientistSessionManager()
    route_module._SESSION_MANAGER = manager

    noisy = route_module.SessionRecord(
        session_id="noise123",
        conversation_id="noise-conv",
        question="tiny failed boot stub",
        model="",
        user_id="user-test",
        status="error",
        stage="error",
    )

    def fake_scan(*, curated_only=False):
        return [] if curated_only else [noisy]

    route_module._scan_persisted_conversations = fake_scan

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    listed = client.get("/pathscientist/sessions").json()
    listed_with_noise = client.get(
        "/pathscientist/sessions?include_persisted=true"
    ).json()

    assert listed["items"] == []
    assert any(item["session_id"] == "noise123" for item in listed_with_noise["items"])


def test_data_paths_map_to_container_basenames():
    """``data_paths`` must be projected onto ``/data/<basename>`` so train.py
    can resolve files inside the sandbox regardless of the host layout.

    Pre-fix the route mapped host→host which would not exist in the sandbox.
    """
    route_module = load_route_module()

    # Stub PathScientistConfig.from_env so we don't depend on real env.
    class _StubConfig:
        data_mounts: dict[str, str] = {}
        llm_model = ""
        skill_name = ""
        max_iterations = 1
        primary_metric = "auc"
        manual_approval = False
        download_policy = ""

    def fake_from_env() -> _StubConfig:
        return _StubConfig()

    import sys
    stub_module = type(sys)("backend.pathscientist.config")
    stub_module.PathScientistConfig = type("PSConfig", (), {"from_env": staticmethod(fake_from_env)})
    sys.modules["backend.pathscientist.config"] = stub_module

    req = route_module.StartPathScientistSessionRequest(
        question="x", data_paths=["/some/HOST/CRC-MSI", "/other/HOST/CRC-MSI"],
    )
    config = route_module._build_config(req)
    assert "/some/HOST/CRC-MSI" in config.data_mounts
    assert config.data_mounts["/some/HOST/CRC-MSI"] == "/data/crc-msi"
    # Disambiguated when basenames collide.
    assert config.data_mounts["/other/HOST/CRC-MSI"] == "/data/crc-msi_2"


def test_projects_persisted_openhands_events_for_legacy_detail(tmp_path):
    route_module = load_route_module()
    conversation_dir = tmp_path / "legacy-conv"
    events_dir = conversation_dir / "events"
    events_dir.mkdir(parents=True)
    (events_dir / "event-00001-action.json").write_text(
        '''{
          "id": "action-1",
          "timestamp": "2026-05-15T10:00:00",
          "kind": "ActionEvent",
          "source": "agent",
          "tool_name": "run_experiment",
          "tool_call_id": "call-1",
          "summary": "Run full training",
          "action": {"script_path": "train.py", "quick_check": false, "kind": "RunExperimentAction"}
        }''',
        encoding="utf-8",
    )
    (events_dir / "event-00002-observation.json").write_text(
        '''{
          "id": "obs-1",
          "timestamp": "2026-05-15T10:01:00",
          "kind": "ObservationEvent",
          "source": "environment",
          "tool_name": "run_experiment",
          "tool_call_id": "call-1",
          "observation": {
            "is_error": false,
            "exit_code": 0,
            "metrics": {"auc": 0.91},
            "duration": 12.5,
            "kind": "RunExperimentObservation",
            "content": [{"type": "text", "text": "Exit code: 0\\nMetrics: auc=0.91"}]
          }
        }''',
        encoding="utf-8",
    )

    events = route_module._load_persisted_conversation_events(conversation_dir)

    assert [event["kind"] for event in events] == ["tool_call", "tool_observation"]
    assert [event["seq"] for event in events] == [1, 2]
    assert all(event["ui_kind"] == "tool" for event in events)
    assert events[0]["tool"] == "run_experiment"
    assert events[0]["summary"] == "Run full training"
    assert events[1]["exit_code"] == 0
    assert events[1]["severity"] == "info"
    assert events[1]["observation"]["metrics"] == {"auc": 0.91}


def test_builds_legacy_state_for_execution_console_metrics():
    route_module = load_route_module()
    summary = {
        "execution_status": "finished",
        "research_question": "Train a WSI MIL model",
        "research_session": {
            "acquisition_status": "prepared",
            "acquisition_notes": "Existing feature tensors detected.",
            "selected_dataset": {
                "name": "TCGA-LUAD + TCGA-LUSC",
                "provider": "local",
                "access": "existing",
            },
            "dataset_manifest_path": "/data/pathscientist/manifests/nsclc.json",
            "dataset_candidates": [{"name": "TCGA-LUAD"}, {"name": "TCGA-LUSC"}],
            "data_readiness": {
                "status": "features_ready",
                "features_dir": "/data/features/virchow2/nsclc",
                "splits_file": "/data/splits/nsclc.csv",
            },
            "execution_plan": {
                "status": "ready",
                "steps": [{"id": "train_mil", "skill": "mil_classification"}],
            },
            "grounding": {
                "selected_skill": "mil_classification",
                "papers": [{"title": "CLAM", "year": 2021, "source": "local"}],
                "online_literature_count": 3,
            },
        },
        "tracker_state": {
            "primary_metric": "auc",
            "best_value": 0.9701,
            "history": [
                {"iteration": 1, "metrics": {"auc": 0.9695}, "committed": True, "run_id": "run_a"},
                {"iteration": 2, "metrics": {"auc": 0.9701}, "committed": True, "run_id": "run_b"},
            ],
        },
        "iteration_state": {"iteration_index": 3, "max_iterations": 5},
    }

    state = route_module._build_persisted_session_state(summary)

    assert state["stage"] == "finished"
    assert state["best_metric_value"] == 0.9701
    assert state["objective"]["success_metric"] == "auc"
    assert state["iteration_index"] == 3
    assert state["max_iterations"] == 5
    assert state["run_history"][1]["metric_value"] == 0.9701
    assert state["run_history"][1]["run_id"] == "run_b"
    assert state["grounding"]["selected_skill"] == "mil_classification"
    assert state["grounding"]["papers"][0]["title"] == "CLAM"
    assert state["grounding"]["online_literature_count"] == 3
    assert state["acquisition_status"] == "prepared"
    assert state["selected_dataset"]["provider"] == "local"
    assert state["dataset_manifest_path"] == "/data/pathscientist/manifests/nsclc.json"
    assert len(state["dataset_candidates"]) == 2
    assert state["data_readiness"]["features_dir"] == "/data/features/virchow2/nsclc"
    assert state["execution_plan"]["status"] == "ready"
    assert state["persisted_summary"] == summary


def test_builds_legacy_state_with_real_stage_history():
    route_module = load_route_module()
    summary = {
        "execution_status": "finished",
        "research_question": "Train a WSI MIL model",
        "research_session": {
            "stage_started_at": 157.0,
            "stage_history": [
                {"stage": "intake", "started_at": 100.0, "ended_at": 105.0, "duration_sec": 5.0},
                {"stage": "grounding", "started_at": 105.0, "ended_at": 117.0, "duration_sec": 12.0},
                {"stage": "execution", "started_at": 117.0, "ended_at": 157.0, "duration_sec": 40.0},
                {"stage": "completed", "started_at": 157.0},
            ],
        },
    }

    state = route_module._build_persisted_session_state(summary)

    assert state["stage_started_at"] == 157.0
    assert state["stage_history"][1]["stage"] == "grounding"
    assert state["stage_history"][1]["duration_sec"] == 12.0


def test_running_legacy_state_uses_research_stage_instead_of_generic_running():
    route_module = load_route_module()
    summary = {
        "execution_status": "running",
        "research_question": "Train a WSI MIL model",
        "research_session": {
            "stage": "acquisition",
            "stage_started_at": 200.0,
        },
    }

    state = route_module._build_persisted_session_state(summary)

    assert state["stage"] == "acquisition"
    assert state["stage_started_at"] == 200.0


def test_scan_persisted_conversations_enriches_running_stage_for_list(monkeypatch, tmp_path):
    route_module = load_route_module()
    from backend.pathscientist.persistence import history, layout
    from backend.pathscientist.runtime import session as runtime_session

    persistence_root = tmp_path / "conversations"
    conv_id = "abcdef1234567890"
    conv_dir = persistence_root / conv_id
    conv_dir.mkdir(parents=True)
    (conv_dir / "base_state.json").write_text(
        json.dumps(
            {
                "agent_state": {
                    "research_session": {
                        "stage": "execution",
                        "stage_started_at": 200.0,
                        "objective": {
                            "question": "Train a slide-level MIL model",
                            "success_metric": "auc",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    summary = {
        "conversation_id": conv_id,
        "execution_status": "running",
        "event_count": 10,
        "started_at": "2026-05-18T00:00:00",
        "updated_at": "2026-05-18T00:01:00",
    }

    monkeypatch.setattr(history, "list_conversations", lambda _root: [summary])
    monkeypatch.setattr(layout, "get_persistence_root", lambda _base_dir: persistence_root)
    monkeypatch.setattr(runtime_session, "_resolve_base_dir", lambda: tmp_path)
    monkeypatch.setattr(route_module, "_legacy_runtime_status", lambda _summary: route_module.LegacyRuntimeStatus("running", "running"))

    records = route_module._scan_persisted_conversations(curated_only=True)

    assert records[0].stage == "execution"
    assert records[0].state["stage"] == "execution"
    assert records[0].question == "Train a slide-level MIL model"


def test_builds_legacy_state_with_ui_run_summary():
    route_module = load_route_module()
    ui_run_summary = {
        "user_request": "Train a slide-level classifier.",
        "agent_actions": "Ran MIL experiments.",
        "result": "Best AUC was 0.9806.",
        "brief": "Completed benchmark.",
        "model": "gpt-5.5",
    }
    summary = {
        "execution_status": "finished",
        "research_question": "Train a WSI MIL model",
        "research_session": {
            "ui_run_summary": ui_run_summary,
        },
    }

    state = route_module._build_persisted_session_state(summary)

    assert state["ui_run_summary"] == ui_run_summary


def test_builds_legacy_state_with_review_summary():
    route_module = load_route_module()
    latest_review = {
        "status": "not_improved",
        "decision": "enter_synthesis",
        "summary": "Stopping after 5/5 iterations; best run remains run_a.",
    }
    summary = {
        "execution_status": "finished",
        "research_question": "Train a WSI MIL model",
        "research_session": {
            "latest_review": latest_review,
            "review_history": [latest_review],
            "review_decision": "enter_synthesis",
        },
    }

    state = route_module._build_persisted_session_state(summary)

    assert state["latest_review"] == latest_review
    assert state["review_history"] == [latest_review]
    assert state["review_decision"] == "enter_synthesis"


def test_downloads_run_artifacts_as_zip(tmp_path):
    route_module = load_route_module()
    route_module._resolve_pathscientist_base_dir = lambda: tmp_path
    workspace = tmp_path / "workspace"
    evidence_run = workspace / ".evidence" / "runs" / "run_a"
    artifacts_dir = evidence_run / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (evidence_run / "stdout.txt").write_text("training stdout", encoding="utf-8")
    (evidence_run / "code_snapshot.py").write_text("print('train')", encoding="utf-8")
    (artifacts_dir / "best_model.pth").write_bytes(b"model-bytes")
    record_json = {
        "run_id": "run_a",
        "session_id": "research_sid",
        "iteration": 1,
        "run_dir": "output/runs/run_a",
        "git_commit": "abc",
        "exit_code": 0,
        "duration": 12.0,
        "metrics": {"auc": 0.91},
        "primary_metric_name": "auc",
        "primary_metric_value": 0.91,
        "committed": True,
        "artifacts": [
            {
                "name": "best_model.pth",
                "path": "output/runs/run_a/best_model.pth",
                "size": 11,
                "hash": "",
                "storage_mode": "copy",
            }
        ],
    }
    (evidence_run / "record.json").write_text(json.dumps(record_json), encoding="utf-8")

    manager = route_module.PathScientistSessionManager()
    manager._sessions["s1"] = route_module.SessionRecord(
        session_id="s1",
        conversation_id="conv",
        question="q",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
        state={
            "workspace_dir": str(workspace),
            "run_history": [
                {
                    "iteration": 1,
                    "run_id": "run_a",
                    "metric_name": "auc",
                    "metric_value": 0.91,
                    "committed": True,
                }
            ],
        },
    )
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.get("/pathscientist/sessions/s1/runs/run_a/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "record.json" in names
        assert "metrics.json" in names
        assert "stdout.txt" in names
        assert "code_snapshot.py" in names
        assert "artifacts/best_model.pth" in names
        assert json.loads(archive.read("metrics.json")) == {"auc": 0.91}
        assert archive.read("artifacts/best_model.pth") == b"model-bytes"


def test_run_artifact_zip_rejects_workspace_outside_base_dir(tmp_path, monkeypatch):
    route_module = load_route_module()
    base_dir = tmp_path / "pathscientist-base"
    outside = tmp_path / "outside-workspace"
    evidence_run = outside / ".evidence" / "runs" / "run_a"
    evidence_run.mkdir(parents=True)
    (evidence_run / "record.json").write_text(
        json.dumps({"run_id": "run_a", "metrics": {"auc": 0.9}}),
        encoding="utf-8",
    )
    record = route_module.SessionRecord(
        session_id="s1",
        conversation_id="",
        question="q",
        model="",
        status="completed",
        stage="completed",
        state={"run_history": [{"run_id": "run_a", "metrics": {"auc": 0.9}}]},
    )
    monkeypatch.setattr(route_module, "_resolve_pathscientist_base_dir", lambda: base_dir)

    with pytest.raises(FileNotFoundError, match="outside PathScientist base dir"):
        route_module._build_run_artifact_zip(record, outside, "run_a")


def test_hydrates_legacy_events_from_hyphenated_conversation_id(tmp_path, monkeypatch):
    route_module = load_route_module()
    persistence_root = tmp_path / "conversations"
    conversation_id = "abc12345-6789-4abc-9def-0123456789ab"
    conversation_dir = persistence_root / conversation_id.replace("-", "")
    events_dir = conversation_dir / "events"
    events_dir.mkdir(parents=True)
    (events_dir / "event-00001-action.json").write_text(
        '{"id":"a","timestamp":"2026-05-15T10:00:00","kind":"ActionEvent","tool_name":"think","summary":"Plan","action":{"kind":"ThinkAction"}}',
        encoding="utf-8",
    )

    import sys as _sys
    layout_module = type(_sys)("backend.pathscientist.persistence.layout")
    layout_module.get_persistence_root = lambda _base: persistence_root
    session_module = type(_sys)("backend.pathscientist.runtime.session")
    session_module._resolve_base_dir = lambda: tmp_path
    monkeypatch.setitem(_sys.modules, "backend.pathscientist.persistence.layout", layout_module)
    monkeypatch.setitem(_sys.modules, "backend.pathscientist.runtime.session", session_module)

    record = route_module.SessionRecord(
        session_id="abc123456789",
        conversation_id=conversation_id,
        question="legacy",
        model="",
        status="finished",
        stage="finished",
        state={"persisted_summary": {"execution_status": "finished"}},
    )

    hydrated = route_module._hydrate_persisted_record_detail(record)

    assert len(hydrated.events) == 1
    assert hydrated.events[0]["kind"] == "tool_call"
    assert hydrated.events[0]["tool"] == "think"


def test_hydrated_legacy_detail_adds_stage_summary_events(tmp_path, monkeypatch):
    route_module = load_route_module()
    persistence_root = tmp_path / "conversations"
    conversation_id = "stage1234-5678-4abc-9def-0123456789ab"
    conversation_dir = persistence_root / conversation_id.replace("-", "")
    events_dir = conversation_dir / "events"
    events_dir.mkdir(parents=True)
    (events_dir / "event-00001-action.json").write_text(
        '{"id":"a","timestamp":"2026-05-15T10:00:00","kind":"ActionEvent","tool_name":"run_experiment","summary":"Run ABMIL","action":{"kind":"RunExperimentAction"}}',
        encoding="utf-8",
    )
    (conversation_dir / "base_state.json").write_text(
        '''{
          "id": "stage1234-5678-4abc-9def-0123456789ab",
          "agent_state": {
            "research_session": {
              "objective": {
                "question": "Train a slide-level MIL classifier with Virchow2.",
                "success_metric": "auc",
                "dataset_hint": "CG-MIL"
              },
              "grounding": {
                "selected_skill": "mil_classification",
                "route": "skill",
                "dataset_hint_inferred": "CG-MIL",
                "sota_lookup_status": "cache_negative",
                "task_profile": {
                  "task_type": "mil_classification",
                  "asset_level": "slide",
                  "prediction_target": "chronic_gastritis_grading"
                }
              }
            }
          }
        }''',
        encoding="utf-8",
    )

    import sys as _sys
    layout_module = type(_sys)("backend.pathscientist.persistence.layout")
    layout_module.get_persistence_root = lambda _base: persistence_root
    session_module = type(_sys)("backend.pathscientist.runtime.session")
    session_module._resolve_base_dir = lambda: tmp_path
    monkeypatch.setitem(_sys.modules, "backend.pathscientist.persistence.layout", layout_module)
    monkeypatch.setitem(_sys.modules, "backend.pathscientist.runtime.session", session_module)

    record = route_module.SessionRecord(
        session_id="stage12345678",
        conversation_id=conversation_id,
        question="legacy",
        model="",
        status="finished",
        stage="finished",
        state={
            "persisted_summary": {
                "execution_status": "finished",
                "event_count": 208,
                "research_question": "Train a slide-level MIL classifier with Virchow2.",
                "research_summary": "Best run achieved auc=0.9701.",
                "tracker_state": {"primary_metric": "auc", "best_value": 0.9701},
                "iteration_state": {"iteration_index": 5, "max_iterations": 5},
                "started_at": "2026-05-15T09:55:00",
                "updated_at": "2026-05-15T10:05:00",
            }
        },
    )

    hydrated = route_module._hydrate_persisted_record_detail(record)

    stage_counts = {}
    for event in hydrated.events:
        stage = event.get("stage")
        if stage:
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
    for stage in [
        "intake",
        "grounding",
        "acquisition",
        "pre_execution_ready",
        "review",
        "synthesis",
        "completed",
    ]:
        assert stage_counts[stage] == 1
    assert stage_counts["execution"] == 1
    assert hydrated.events[0]["kind"] == "stage_summary"
    assert hydrated.events[0]["stage"] == "intake"
    grounding = next(event for event in hydrated.events if event.get("stage") == "grounding")
    assert "mil_classification" in grounding["summary"]
    assert "CG-MIL" in grounding["summary"]
    assert "no SOTA target found" in grounding["summary"]
    assert "cache_negative" not in grounding["summary"]
    assert "best auc" not in grounding["summary"]
    assert hydrated.events[-1]["kind"] == "tool_call"
    assert [event["seq"] for event in hydrated.events] == list(range(1, len(hydrated.events) + 1))


def test_list_sessions_merges_db_history_with_live_records(monkeypatch):
    route_module = load_route_module()
    route_module._DB_HISTORY_ENABLED = True
    db_record = route_module.SessionRecord(
        session_id="db1",
        conversation_id="conv-db",
        question="db history",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
    )
    live_record = route_module.SessionRecord(
        session_id="live1",
        conversation_id="",
        question="live",
        model="gpt-5.5",
        user_id="user-test",
        status="running",
        stage="execution",
    )
    manager = route_module.PathScientistSessionManager()
    manager._sessions[live_record.session_id] = live_record
    route_module._SESSION_MANAGER = manager
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []

    async def fake_db_list(*, user, include_persisted, limit=100):
        return [db_record]

    monkeypatch.setattr(route_module, "_load_db_session_list", fake_db_list)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    data = client.get("/pathscientist/sessions").json()

    ids = {item["session_id"] for item in data["items"]}
    assert {"db1", "live1"} <= ids


def test_get_session_falls_back_to_db_record(monkeypatch):
    route_module = load_route_module()
    route_module._DB_HISTORY_ENABLED = True
    route_module._SESSION_MANAGER = route_module.PathScientistSessionManager()
    record = route_module.SessionRecord(
        session_id="db-detail",
        conversation_id="conv-detail",
        question="from db",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
        state={"resume_available": True},
    )
    record.hydrate_events([{"seq": 1, "kind": "message", "text": "hello"}])

    async def fake_db_record(session_id, **_kwargs):
        assert session_id == "db-detail"
        return record

    monkeypatch.setattr(route_module, "_load_db_record", fake_db_record)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    data = client.get("/pathscientist/sessions/db-detail").json()

    assert data["question"] == "from db"
    assert data["resume_available"] is True
    assert data["events"][0]["text"] == "hello"


def test_get_session_enriches_external_test_from_workspace_artifacts(tmp_path):
    route_module = load_route_module()
    workspace = tmp_path / "workspace"
    run_dir = workspace / "output" / "runs" / "run_best"
    run_dir.mkdir(parents=True)
    (run_dir / "metrics.json").write_text(
        json.dumps({
            "test": {"auc": 0.88},
            "external_test": {"auc": 0.9421, "accuracy": 0.875, "n_external_evaluated": 4},
        }),
        encoding="utf-8",
    )
    (run_dir / "external_test_report.json").write_text(
        json.dumps({
            "external_test": {"auc": 0.9421, "accuracy": 0.875, "n_external_evaluated": 4},
            "features_dir": "/data/nsclc_external_test/features/virchow2/paramsabc",
            "splits_file": "/data/nsclc_external_test/splits.json",
        }),
        encoding="utf-8",
    )
    manager = route_module.PathScientistSessionManager()
    manager._sessions["s-external-artifact"] = route_module.SessionRecord(
        session_id="s-external-artifact",
        conversation_id="",
        question="external validation",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
        state={
            "workspace_dir": str(workspace),
            "objective": {"success_metric": "auc"},
            "best_run_id": "run_best",
            "run_history": [{"run_id": "run_best", "committed": True}],
            "external_test": {},
            "external_test_history": [],
        },
    )
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    data = client.get("/pathscientist/sessions/s-external-artifact").json()

    assert data["state"]["external_test"] == {
        "run_id": "run_best",
        "status": "completed",
        "committed": True,
        "run_dir": str(run_dir),
        "metrics": {"auc": 0.9421, "accuracy": 0.875, "n_external_evaluated": 4},
        "features_dir": "/data/nsclc_external_test/features/virchow2/paramsabc",
        "splits_file": "/data/nsclc_external_test/splits.json",
    }


def test_db_running_session_without_recent_updates_is_marked_interrupted(monkeypatch):
    route_module = load_route_module()
    monkeypatch.setattr(route_module, "LEGACY_RUNNING_STALE_SECONDS", 600)
    monkeypatch.setattr(route_module.time, "time", lambda: 2_000.0)
    session = SimpleNamespace(
        session_id="stale-db-running",
        conversation_id="conv-stale",
        research_question="old running session",
        status="running",
        phase="execution",
        current_iteration=0,
        max_iterations=1,
        user_id="user-test",
        experiment_plan={},
        comparison_results={},
        recovery_metadata={},
        best_metric=None,
        best_metric_name="auc",
        best_experiment=None,
        final_report=None,
        resume_available=False,
        event_source_version="gateway-v1",
        created_at=100.0,
        updated_at=1_000.0,
    )

    record = route_module._db_session_to_record(session, events=[])

    assert record.status == "interrupted"
    assert record.stage == "interrupted"
    assert record.error
    assert record.state["interrupted_reason"] == record.error


def test_db_running_session_with_recent_training_log_stays_running(tmp_path, monkeypatch):
    route_module = load_route_module()
    monkeypatch.setattr(route_module, "LEGACY_RUNNING_STALE_SECONDS", 600)
    monkeypatch.setattr(route_module.time, "time", lambda: 2_000.0)
    workspace = tmp_path / "workspace"
    run_dir = workspace / "output" / "runs" / "run_live"
    run_dir.mkdir(parents=True)
    log_path = run_dir / "training.log"
    log_path.write_text(
        "2026-06-17 23:33:50 | INFO | Epoch 8/30 | loss=0.0462 | val_auc=0.9619\n",
        encoding="utf-8",
    )
    os.utime(log_path, (1_950.0, 1_950.0))
    session = SimpleNamespace(
        session_id="live-db-running",
        conversation_id="conv-live",
        research_question="live running session",
        status="running",
        phase="execution",
        current_iteration=0,
        max_iterations=1,
        user_id="user-test",
        experiment_plan={},
        comparison_results={},
        recovery_metadata={"workspace_path": str(workspace)},
        best_metric=None,
        best_metric_name="auc",
        best_experiment=None,
        final_report=None,
        resume_available=False,
        event_source_version="gateway-v1",
        created_at=100.0,
        updated_at=1_000.0,
        persistence_dir=None,
        workspace_path=str(workspace),
    )

    record = route_module._db_session_to_record(session, events=[])
    summary = record.summary()

    assert record.status == "running"
    assert record.stage == "execution"
    assert not record.error
    assert summary["training_progress"]["current_epoch"] == 8
    assert summary["training_progress"]["total_epochs"] == 30


def test_gateway_running_session_with_recent_training_log_stays_running(tmp_path, monkeypatch):
    route_module = load_route_module()
    monkeypatch.setattr(route_module, "LEGACY_RUNNING_STALE_SECONDS", 600)
    monkeypatch.setattr(route_module.time, "time", lambda: 2_000.0)
    registry_dir = tmp_path / "registry"
    workspace = tmp_path / "workspace"
    run_dir = workspace / "output" / "runs" / "run_live"
    run_dir.mkdir(parents=True)
    registry_dir.mkdir()
    log_path = run_dir / "training.log"
    log_path.write_text(
        "2026-06-17 23:44:55 | INFO | Epoch 9/30 | loss=0.0355 | val_auc=0.9603\n",
        encoding="utf-8",
    )
    os.utime(log_path, (1_950.0, 1_950.0))
    registry_path = registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    registry_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "session_id": "gateway-live-training",
                        "conversation_id": "conv-live-training",
                        "question": "train",
                        "model": "gpt-5.5",
                        "status": "running",
                        "stage": "grounding",
                        "created_at": 100.0,
                        "updated_at": 1_000.0,
                        "workspace_path": str(workspace),
                        "state": {"workspace_path": str(workspace), "stage": "execution"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(route_module, "_gateway_session_registry_path", lambda: registry_path)

    records = route_module._load_gateway_session_records()

    assert len(records) == 1
    record = records[0]
    summary = record.summary()
    assert record.status == "running"
    assert record.stage == "execution"
    assert record.error == ""
    assert summary["training_progress"]["current_epoch"] == 9
    assert summary["training_progress"]["total_epochs"] == 30


def test_gateway_running_session_allows_long_epoch_training_log_gap(tmp_path, monkeypatch):
    route_module = load_route_module()
    monkeypatch.setattr(route_module, "LEGACY_RUNNING_STALE_SECONDS", 600)
    monkeypatch.setattr(route_module, "TRAINING_LOG_ACTIVE_SECONDS", 7200)
    monkeypatch.setattr(route_module.time, "time", lambda: 3_000.0)
    registry_dir = tmp_path / "registry"
    workspace = tmp_path / "workspace"
    run_dir = workspace / "output" / "runs" / "run_live"
    run_dir.mkdir(parents=True)
    registry_dir.mkdir()
    log_path = run_dir / "training.log"
    log_path.write_text(
        "2026-06-17 23:44:55 | INFO | Epoch 9/30 | loss=0.0355 | val_auc=0.9603\n",
        encoding="utf-8",
    )
    os.utime(log_path, (2_000.0, 2_000.0))
    registry_path = registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    registry_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "session_id": "gateway-long-epoch",
                        "conversation_id": "conv-long-epoch",
                        "question": "train",
                        "model": "gpt-5.5",
                        "status": "running",
                        "stage": "execution",
                        "created_at": 100.0,
                        "updated_at": 1_000.0,
                        "workspace_path": str(workspace),
                        "state": {"workspace_path": str(workspace), "stage": "execution"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(route_module, "_gateway_session_registry_path", lambda: registry_path)

    record = route_module._load_gateway_session_records()[0]

    assert record.status == "running"
    assert record.stage == "execution"
    assert record.summary()["training_progress"]["current_epoch"] == 9


def test_events_stream_replays_db_events_when_jsonl_missing(monkeypatch):
    route_module = load_route_module()
    route_module._DB_HISTORY_ENABLED = True
    route_module._SESSION_MANAGER = route_module.PathScientistSessionManager()
    record = route_module.SessionRecord(
        session_id="db-events",
        conversation_id="",
        question="events",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
    )
    db_events = [{"seq": 1, "kind": "message", "text": "replayed from db"}]

    async def fake_db_record(session_id, **_kwargs):
        assert session_id == "db-events"
        return record

    async def fake_db_events(session_id, **_kwargs):
        assert session_id == "db-events"
        return db_events

    monkeypatch.setattr(route_module, "_load_db_record", fake_db_record)
    monkeypatch.setattr(route_module, "_load_db_events", fake_db_events)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    with client.stream("GET", "/pathscientist/sessions/db-events/events") as response:
        assert response.status_code == 200
        body = next(response.iter_text())

    assert "replayed from db" in body


def test_get_session_denies_other_users_db_record(monkeypatch):
    route_module = load_route_module()
    route_module._DB_HISTORY_ENABLED = True
    route_module._SESSION_MANAGER = route_module.PathScientistSessionManager()

    async def forbidden_db_record(session_id, **_kwargs):
        raise route_module.HTTPException(status_code=403, detail="PathScientist session access denied")

    monkeypatch.setattr(route_module, "_load_db_record", forbidden_db_record)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module, user_id="user-a")
    client = TestClient(app)

    response = client.get("/pathscientist/sessions/private-session")

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/pathscientist/sessions/private-session/stop"),
        ("delete", "/pathscientist/sessions/private-session"),
    ],
)
def test_mutating_session_endpoints_deny_other_users_db_record(monkeypatch, method, path):
    route_module = load_route_module()
    route_module._DB_HISTORY_ENABLED = True
    route_module._SESSION_MANAGER = route_module.PathScientistSessionManager()

    async def forbidden_db_record(session_id, **_kwargs):
        assert session_id == "private-session"
        raise route_module.HTTPException(status_code=403, detail="PathScientist session access denied")

    monkeypatch.setattr(route_module, "_load_db_record", forbidden_db_record)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module, user_id="user-a")
    client = TestClient(app)

    response = getattr(client, method)(path)

    assert response.status_code == 403


def test_resume_session_rejects_missing_checkpoint():
    route_module = load_route_module()
    manager = route_module.PathScientistSessionManager()
    record = route_module.SessionRecord(
        session_id="resume-missing",
        conversation_id="87654321-1234-4abc-9def-123456789abc",
        question="resume",
        model="gpt-5.5",
        user_id="user-test",
        status="interrupted",
        stage="interrupted",
    )
    manager._sessions[record.session_id] = record
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.post("/pathscientist/sessions/resume-missing/resume")

    assert response.status_code == 409
    assert "checkpoint is missing" in response.json()["detail"]


def test_resume_session_starts_thread_when_checkpoint_exists(tmp_path, monkeypatch):
    route_module = load_route_module()
    conversation_dir = tmp_path / "conv"
    conversation_dir.mkdir()
    (conversation_dir / "base_state.json").write_text("{}", encoding="utf-8")
    record = route_module.SessionRecord(
        session_id="resume-ok",
        conversation_id="12345678-1234-4abc-9def-123456789abc",
        question="resume",
        model="gpt-5.5",
        user_id="user-test",
        status="interrupted",
        stage="interrupted",
        state={"persistence_dir": str(conversation_dir), "resume_available": True},
    )
    manager = route_module.PathScientistSessionManager()
    manager._sessions[record.session_id] = record
    route_module._SESSION_MANAGER = manager
    route_module._build_config = lambda req: SimpleNamespace(llm_model="gpt-5.5", primary_metric=req.metric)
    route_module._persist_record_state = lambda record, req=None: None
    started: list[str] = []

    def fake_resume_run(record, req, config):
        started.append(record.session_id)

    monkeypatch.setattr(manager, "_resume_run", fake_resume_run)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.post("/pathscientist/sessions/resume-ok/resume")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert data["stage"] == "resuming"
    assert data["resume_available"] is True
    for _ in range(20):
        if started == ["resume-ok"]:
            break
        time.sleep(0.02)
    assert started == ["resume-ok"]
