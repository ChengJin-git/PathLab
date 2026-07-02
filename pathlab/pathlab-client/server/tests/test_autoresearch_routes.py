# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportImplicitRelativeImport=false, reportMissingTypeArgument=false
import importlib.util
import asyncio
import io
import json
import os
import sys
import tempfile
import threading
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


ROUTE_PATH = Path(__file__).resolve().parents[1] / "gateway" / "routes" / "autoresearch.py"
SERVER_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_SCRIPT_PATH = SERVER_ROOT / "scripts" / "migrate_autoresearch_file_sessions_to_db.py"


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
    spec = importlib.util.spec_from_file_location("autoresearch_route_under_test", ROUTE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.autoresearch_persistence.persist_session_created = lambda **kwargs: None
    module.autoresearch_persistence.persist_event = lambda **kwargs: None
    module.autoresearch_persistence.persist_session_state = lambda **kwargs: None
    module.autoresearch_persistence.delete_session = lambda session_id: None
    module._DB_HISTORY_ENABLED = False
    return module


def test_autoresearch_route_has_no_file_backed_session_runtime():
    source = ROUTE_PATH.read_text(encoding="utf-8")

    forbidden = [
        "GATEWAY_SESSION_REGISTRY",
        "GATEWAY_EVENT_DIR",
        "GATEWAY_DELETED_SESSIONS",
        "GATEWAY_DELETE_AUDIT_LOG",
        "AUTORESEARCH_DB_HISTORY",
        "_save_gateway_session_record",
        "_load_gateway_session_records",
        "_scan_persisted_conversations",
        "_hydrate_persisted_record_detail",
        "_refresh_persisted_record_detail",
        "_mark_gateway_session_deleted",
        "_delete_gateway_session_events",
    ]
    assert [token for token in forbidden if token in source] == []


def test_autoresearch_file_session_migration_is_self_contained():
    source = MIGRATION_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "from gateway.routes" not in source
    assert "autoresearch_routes" not in source
    assert "gateway_sessions.json" in source
    assert "gateway_events" in source


def install_fake_user(
    app: FastAPI,
    route_module,
    user_id: str = "user-test",
    *,
    override_autoresearch_access_token: bool = True,
):
    fake_user = lambda: SimpleNamespace(id=user_id)
    app.dependency_overrides[route_module.current_active_user] = fake_user
    app.dependency_overrides[route_module.get_user_from_header_or_param] = fake_user
    app.dependency_overrides[route_module.get_user_from_token_param] = fake_user
    if override_autoresearch_access_token and hasattr(
        route_module,
        "get_autoresearch_access_token_claims",
    ):
        app.dependency_overrides[route_module.get_autoresearch_access_token_claims] = (
            lambda: {
                "user": SimpleNamespace(id=user_id),
                "purpose": "header",
                "sid": "",
                "rid": "",
            }
        )
    if override_autoresearch_access_token and hasattr(
        route_module,
        "get_autoresearch_header_or_access_token_claims",
    ):
        app.dependency_overrides[
            route_module.get_autoresearch_header_or_access_token_claims
        ] = (
            lambda: {
                "user": SimpleNamespace(id=user_id),
                "purpose": "header",
                "sid": "",
                "rid": "",
            }
        )


def disable_persistence(route_module):
    route_module.autoresearch_persistence.persist_session_created = lambda **kwargs: None
    route_module.autoresearch_persistence.persist_event = lambda **kwargs: None
    route_module.autoresearch_persistence.persist_session_state = lambda **kwargs: None
    route_module.autoresearch_persistence.delete_session = lambda session_id: None


def canonical_workspace(route_module, uploads_dir: Path, session_id: str) -> Path:
    route_module._resolve_autoresearch_base_dir = lambda: (uploads_dir / "autoresearch").resolve()
    workspace = uploads_dir / "autoresearch" / "autoresearch_sessions" / f"session_{session_id}"
    workspace.parent.mkdir(parents=True, exist_ok=True)
    return workspace


def make_app():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="autoresearch-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._queue_session_title_generation = lambda record, config: None
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []
    manager = route_module.AutoResearchSessionManager()

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


@pytest.mark.parametrize(
    ("method", "path", "json_payload"),
    [
        ("get", "/autoresearch/sessions/session-owned-by-x", None),
        ("post", "/autoresearch/sessions/session-owned-by-x/stop", None),
        ("post", "/autoresearch/sessions/session-owned-by-x/resume", {"question": "resume"}),
        ("delete", "/autoresearch/sessions/session-owned-by-x", None),
        ("post", "/autoresearch/sessions/session-owned-by-x/access-token", {"purpose": "events"}),
        ("get", "/autoresearch/sessions/session-owned-by-x/download", None),
        ("get", "/autoresearch/sessions/session-owned-by-x/runs/run-a/download", None),
        ("get", "/autoresearch/sessions/session-owned-by-x/events", None),
    ],
)
def test_session_endpoints_deny_other_users_in_memory_record(method, path, json_payload):
    route_module = load_route_module()
    manager = route_module.AutoResearchSessionManager()
    manager._sessions["session-owned-by-x"] = route_module.SessionRecord(
        session_id="session-owned-by-x",
        conversation_id="",
        question="private",
        model="gpt-5.5",
        user_id="user-x",
        status="completed",
        stage="completed",
        state={"workspace_path": "/tmp/autoresearch-private-workspace"},
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
    manager = route_module.AutoResearchSessionManager()
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
        raise HTTPException(status_code=403, detail="AutoResearch session access denied")

    monkeypatch.setattr(route_module, "_load_db_record", fake_load_db_record)

    with pytest.raises(HTTPException) as exc:
        await route_module.get_session(
            "session-shadow",
            user=SimpleNamespace(id="user-other", is_admin=lambda: False),
        )

    assert exc.value.status_code == 403


def test_autoresearch_access_token_replaces_full_jwt_query_token(tmp_path):
    route_module = load_route_module()
    route_module._resolve_autoresearch_base_dir = lambda: tmp_path
    workspace = tmp_path / "session-token"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("hello\n", encoding="utf-8")
    run_dir = workspace / ".evidence" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "record.json").write_text(
        json.dumps({"run_id": "run-1", "artifacts": []}),
        encoding="utf-8",
    )
    manager = route_module.AutoResearchSessionManager()
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
        override_autoresearch_access_token=False,
    )
    client = TestClient(app)

    minted = client.post(
        "/autoresearch/sessions/session-token/access-token",
        json={"purpose": "run_download", "run_id": "run-1"},
    )
    assert minted.status_code == 200
    access_token = minted.json()["token"]
    assert minted.json()["expires_in"] <= 300

    full_jwt = jwt.encode(
        {"sub": "user-test", "aud": "fastapi-users:auth", "sn": "nonce"},
        route_module.AUTORESEARCH_ACCESS_TOKEN_SECRET,
        algorithm="HS256",
    )
    full_jwt_response = client.get(
        "/autoresearch/sessions/session-token/runs/run-1/download",
        params={"token": full_jwt},
    )
    assert full_jwt_response.status_code == 401

    response = client.get(
        "/autoresearch/sessions/session-token/runs/run-1/download",
        params={"token": access_token},
    )
    assert response.status_code == 200
    assert response.headers["Referrer-Policy"] == "no-referrer"

    wrong_run = client.get(
        "/autoresearch/sessions/session-token/runs/run-2/download",
        params={"token": access_token},
    )
    assert wrong_run.status_code == 403


def test_autoresearch_events_require_single_purpose_access_token():
    route_module = load_route_module()
    manager = route_module.AutoResearchSessionManager()
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
        override_autoresearch_access_token=False,
    )
    client = TestClient(app)

    minted = client.post(
        "/autoresearch/sessions/session-events-token/access-token",
        json={"purpose": "events"},
    )
    assert minted.status_code == 200
    events_token = minted.json()["token"]

    response = client.get(
        "/autoresearch/sessions/session-events-token/events",
        params={"token": events_token},
    )
    assert response.status_code == 200
    assert response.headers["Referrer-Policy"] == "no-referrer"

    wrong_purpose = client.post(
        "/autoresearch/sessions/session-events-token/access-token",
        json={"purpose": "session_download"},
    ).json()["token"]
    rejected = client.get(
        "/autoresearch/sessions/session-events-token/events",
        params={"token": wrong_purpose},
    )
    assert rejected.status_code == 403


def test_does_not_publicly_list_internal_skills():
    client = TestClient(make_app())

    response = client.get("/autoresearch/skills")

    assert response.status_code == 404


def test_start_session_request_has_no_public_skill_field():
    route_module = load_route_module()

    fields = getattr(
        route_module.StartAutoResearchSessionRequest,
        "model_fields",
        getattr(route_module.StartAutoResearchSessionRequest, "__fields__", {}),
    )

    assert "skill" not in fields


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
    registry_dir = Path(tempfile.mkdtemp(prefix="autoresearch-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._queue_session_title_generation = lambda record, config: None
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []
    manager = route_module.AutoResearchSessionManager()

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
        "/autoresearch/sessions",
        json={"question": "quick smoke", "max_iter": 1},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"]
    assert data["model"] == "gpt-5.5"


def test_create_session_rejects_legacy_skill_payload(monkeypatch):
    route_module = load_route_module()
    monkeypatch.setattr(
        route_module.Config,
        "get_global_settings",
        staticmethod(lambda: {}),
    )

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.post(
        "/autoresearch/sessions",
        json={"question": "quick smoke", "skill": "mil_classification"},
    )

    assert response.status_code == 422


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
        "_sync_autoresearch_manifest_to_pathlab_best_effort",
        lambda record, state: {"status": "skipped"},
    )

    manager = route_module.AutoResearchSessionManager()

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
        route_module.StartAutoResearchSessionRequest(question=record.question),
        SimpleNamespace(primary_metric="auc"),
    )

    assert record.status == "failed"
    assert record.stage == "failed"
    assert "Run run_bad did not provide" in record.error
    assert record.state["stage"] == "failed"
    assert record.state["error"] == record.error


def test_session_manager_passes_pathlab_user_context_to_runner_config(monkeypatch):
    route_module = load_route_module()

    class _StubConfig:
        data_mounts: dict[str, str] = {}
        llm_model = "gpt-5.5"
        primary_metric = "auc"

    monkeypatch.setattr(route_module, "_build_config", lambda req: _StubConfig())
    route_module._queue_session_title_generation = lambda record, config: None

    manager = route_module.AutoResearchSessionManager()
    captured: list[tuple[str, str]] = []

    def fake_run(record, req, config):
        captured.append((
            getattr(config, "pathlab_user_id", ""),
            getattr(config, "pathlab_user_role", ""),
        ))

    monkeypatch.setattr(manager, "_run", fake_run)

    manager.start(
        route_module.StartAutoResearchSessionRequest(question="download PANDA"),
        user_id="user-test",
        user_role="admin",
    )

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not captured:
        time.sleep(0.01)

    assert captured == [("user-test", "admin")]


def test_session_manager_passes_pathlab_user_context_to_resume_config(monkeypatch):
    route_module = load_route_module()

    class _StubConfig:
        data_mounts: dict[str, str] = {}
        llm_model = "gpt-5.5"
        primary_metric = "auc"

    monkeypatch.setattr(route_module, "_build_config", lambda req: _StubConfig())

    manager = route_module.AutoResearchSessionManager()
    captured: list[tuple[str, str]] = []

    def fake_resume_run(record, req, config):
        captured.append((
            getattr(config, "pathlab_user_id", ""),
            getattr(config, "pathlab_user_role", ""),
        ))

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
        route_module.StartAutoResearchSessionRequest(question="resume"),
        user_role="admin",
    )

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not captured:
        time.sleep(0.01)

    assert captured == [("user-test", "admin")]


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
    manager = route_module.AutoResearchSessionManager()

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
        "/autoresearch/sessions",
        json={
            "question": "Train a patch-level classifier on internal_patch_dataset, then validate on external_patch_dataset.",
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
    manager = route_module.AutoResearchSessionManager()

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
        "/autoresearch/sessions",
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
        return {str(prepared_dir): "/data/autoresearch_tcga_luad"}

    monkeypatch.setattr(
        route_module,
        "_resolve_pathlab_dataset_mounts",
        fake_resolve_dataset_mounts,
        raising=False,
    )
    manager = route_module.AutoResearchSessionManager()

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
        "/autoresearch/sessions",
        json={"question": "Train a LUAD model using AutoResearch TCGA-LUAD"},
    )

    assert response.status_code == 200
    assert resolved_calls == [([], "user-dataset", "Train a LUAD model using AutoResearch TCGA-LUAD")]
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not captured_mounts:
        time.sleep(0.01)
    assert captured_mounts == [{str(prepared_dir): "/data/autoresearch_tcga_luad"}]


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
        lambda *, dataset, slides, view_dir, question="": view_dir,
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


def test_resolve_pathlab_dataset_mounts_ignores_grant_only_dataset_for_non_admin(
    monkeypatch,
    tmp_path,
):
    route_module = load_route_module()
    route_module._resolve_autoresearch_base_dir = lambda: tmp_path / "autoresearch-base"

    def make_slides(dataset_id: str) -> list[SimpleNamespace]:
        source_dir = tmp_path / dataset_id
        source_dir.mkdir()
        slides = []
        for idx, split in enumerate(["train", "train", "val", "test"], start=1):
            source = source_dir / f"{dataset_id}-{idx}.svs"
            source.write_text("slide", encoding="utf-8")
            slides.append(
                SimpleNamespace(
                    wsi_id=f"{dataset_id}-{idx}",
                    wsi_path=str(source),
                    original_filename=source.name,
                    label="positive" if idx % 2 else "negative",
                    split=split,
                )
            )
        return slides

    datasets = {
        "own-private": SimpleNamespace(
            dataset_id="own-private",
            name="Own-GC-IM",
            user_id="user-dataset",
            is_public=False,
            parent_dataset_id=None,
            source_organ="gastric",
            data_type="wsi",
        ),
        "public-dataset": SimpleNamespace(
            dataset_id="public-dataset",
            name="Public-GC-IM",
            user_id="other-user",
            is_public=True,
            parent_dataset_id=None,
            source_organ="gastric",
            data_type="wsi",
        ),
        "grant-private": SimpleNamespace(
            dataset_id="grant-private",
            name="Grant-Only-GC-IM",
            user_id="other-user",
            is_public=False,
            parent_dataset_id=None,
            source_organ="gastric",
            data_type="wsi",
        ),
    }
    slides_by_dataset = {dataset_id: make_slides(dataset_id) for dataset_id in datasets}
    dataset_list_elevated_ids: list[list[str] | None] = []
    loaded_dataset_ids: list[str] = []

    class FakeSafeSession:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_get_permitted_dataset_ids(user, db):
        return ["grant-private"]

    async def fake_get_dataset_with_access(dataset_id, user, db, **kwargs):
        return datasets[dataset_id]

    class FakeWSIRepository:
        @staticmethod
        async def get_datasets(db, **kwargs):
            if kwargs.get("data_type") != "wsi":
                return []
            dataset_list_elevated_ids.append(kwargs.get("elevated_dataset_ids"))
            rows = [
                {"dataset_id": "own-private", "dataset_name": "Own-GC-IM", "data_type": "wsi"},
                {"dataset_id": "public-dataset", "dataset_name": "Public-GC-IM", "data_type": "wsi"},
            ]
            if "grant-private" in (kwargs.get("elevated_dataset_ids") or []):
                rows.append(
                    {
                        "dataset_id": "grant-private",
                        "dataset_name": "Grant-Only-GC-IM",
                        "data_type": "wsi",
                    }
                )
            return rows

        @staticmethod
        async def get_by_dataset(db, dataset_id, **kwargs):
            loaded_dataset_ids.append(dataset_id)
            return slides_by_dataset[dataset_id]

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
    monkeypatch.setattr(route_module, "_autoresearch_dataset_match_llm_caller", lambda: None)
    monkeypatch.setattr(
        route_module,
        "_prepare_pathlab_registered_wsi_dataset_root",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        route_module,
        "_prepare_pathlab_dataset_view",
        lambda **kwargs: kwargs["view_dir"],
    )
    monkeypatch.setattr("builtins.__import__", fake_import)

    mounts = asyncio.run(
        route_module._resolve_pathlab_dataset_mounts(
            [],
            SimpleNamespace(id="user-dataset", is_admin=lambda: False),
            question="Use Grant-Only-GC-IM for intestinal metaplasia classification",
        )
    )

    assert dataset_list_elevated_ids == [[]]
    assert "grant-private" not in loaded_dataset_ids
    assert all("grant_only_gc_im" not in host for host in mounts)


def test_resolve_pathlab_dataset_mounts_rejects_explicit_grant_only_dataset_for_non_admin(
    monkeypatch,
    tmp_path,
):
    route_module = load_route_module()
    route_module._resolve_autoresearch_base_dir = lambda: tmp_path / "autoresearch-base"
    dataset = SimpleNamespace(
        dataset_id="grant-private",
        name="Grant-Only-GC-IM",
        user_id="other-user",
        is_public=False,
        parent_dataset_id=None,
        source_organ="gastric",
        data_type="wsi",
    )

    class FakeSafeSession:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_get_permitted_dataset_ids(user, db):
        return ["grant-private"]

    async def fake_get_dataset_with_access(dataset_id, user, db, **kwargs):
        return dataset

    class FakeWSIRepository:
        @staticmethod
        async def get_by_dataset(db, dataset_id, **kwargs):
            raise AssertionError("grant-only datasets should be rejected before loading slides")

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

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            route_module._resolve_pathlab_dataset_mounts(
                ["grant-private"],
                SimpleNamespace(id="user-dataset", is_admin=lambda: False),
                question="Use Grant-Only-GC-IM",
            )
        )

    assert exc_info.value.status_code == 403


def test_match_pathlab_datasets_from_question_prefers_visible_name_matches():
    route_module = load_route_module()

    matches = route_module._match_pathlab_datasets_from_question(
        "Please run AutoResearch on AutoResearch TCGA-LUAD and compare ABMIL.",
        [
            {"dataset_id": "dataset-lusc", "dataset_name": "AutoResearch TCGA-LUSC"},
            {"dataset_id": "dataset-luad", "dataset_name": "AutoResearch TCGA-LUAD"},
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

    assert "internal" in matches
    assert "synthetic" in matches


def test_final_status_from_state_marks_missing_data_as_failed():
    route_module = load_route_module()

    status, stage, error = route_module._final_status_from_state(
        {
            "stage": "pre_execution_ready",
            "stop_reason": "data_missing",
            "data_readiness": {
                "status": "missing_data",
                "missing": ["features_dir", "images_dir"],
            },
            "execution_plan": {
                "status": "blocked",
                "missing": ["features_dir", "images_dir"],
                "notes": ["Required data is missing."],
            },
            "run_history": [],
        }
    )

    assert status == "failed"
    assert stage == "failed"
    assert "features_dir" in error
    assert "images_dir" in error


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


def test_classify_pathlab_mount_roles_does_not_promote_unmentioned_external_named_dataset(tmp_path):
    route_module = load_route_module()
    internal_dir = tmp_path / "tcga_nsclc_fcd42d36_contract"
    requested_external_dir = tmp_path / "nanfang_nsclc_cc7d5b75_contract"
    unrelated_external_named_dir = tmp_path / "cervical_cytology_external_validation_f97df65c_contract"
    for view_dir, dataset_name in (
        (internal_dir, "TCGA-NSCLC"),
        (requested_external_dir, "Nanfang-NSCLC"),
        (unrelated_external_named_dir, "Cervical Cytology External Validation"),
    ):
        view_dir.mkdir()
        (view_dir / "dataset_manifest.json").write_text(
            json.dumps({"dataset_name": dataset_name}),
            encoding="utf-8",
        )

    roles = route_module._classify_pathlab_mount_roles(
        "Use TCGA-NSCLC as the internal training dataset. Use Nanfang-NSCLC as the external validation dataset.",
        {
            str(internal_dir): "/data/tcga_nsclc_fcd42d36_contract",
            str(unrelated_external_named_dir): "/data/cervical_cytology_external_validation_f97df65c_contract",
            str(requested_external_dir): "/data/nanfang_nsclc_cc7d5b75_contract",
        },
    )

    assert roles.get("internal", {}).get("dataset_name") == "TCGA-NSCLC"
    assert roles.get("external", {}).get("dataset_name") == "Nanfang-NSCLC"
    assert roles.get("external", {}).get("container") == "/data/nanfang_nsclc_cc7d5b75_contract"


def test_create_session_uses_llm_roles_before_role_fallback(monkeypatch, tmp_path):
    route_module = load_route_module()
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._queue_session_title_generation = lambda record, config: None
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []
    route_module._resolve_autoresearch_base_dir = lambda: tmp_path / "autoresearch-base"

    dataset_specs = {
        "tcga": ("TCGA-NSCLC", "fcd42d36", "LUAD"),
        "nanfang": ("Nanfang-NSCLC", "cc7d5b75", "LUAD"),
        "cervical": ("Cervical Cytology External Validation", "f97df65c", "negative"),
    }
    roots: dict[str, Path] = {}
    slides_by_dataset: dict[str, list[SimpleNamespace]] = {}
    for dataset_id, (name, _suffix, label) in dataset_specs.items():
        root = tmp_path / name
        wsi_dir = root / "WSIs"
        features_dir = root / "features" / "virchow2"
        wsi_dir.mkdir(parents=True)
        features_dir.mkdir(parents=True)
        roots[dataset_id] = root
        slides = []
        for idx, split in enumerate(["train", "train", "val", "test"], start=1):
            source = wsi_dir / f"{dataset_id}-{idx}.svs"
            source.write_text("slide", encoding="utf-8")
            (features_dir / f"{dataset_id}-{idx}.pt").write_bytes(b"pt")
            slides.append(
                SimpleNamespace(
                    wsi_id=f"{dataset_id}-{idx}",
                    wsi_path=str(source),
                    original_filename=source.name,
                    label=label if idx % 2 else "LUSC",
                    split=split,
                )
            )
        slides_by_dataset[dataset_id] = slides

    dataset_rows = [
        {"dataset_id": "tcga", "dataset_name": "TCGA-NSCLC", "data_type": "wsi", "labels": {"LUAD": 2, "LUSC": 2}},
        {"dataset_id": "nanfang", "dataset_name": "Nanfang-NSCLC", "data_type": "wsi", "labels": {"LUAD": 2, "LUSC": 2}},
        {
            "dataset_id": "cervical",
            "dataset_name": "Cervical Cytology External Validation",
            "data_type": "wsi",
            "labels": {"negative": 2, "LUSC": 2},
        },
    ]

    class FakeSafeSession:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_get_permitted_dataset_ids(user, db):
        return []

    loaded_dataset_ids = []

    async def fake_get_dataset_with_access(dataset_id, user, db, **kwargs):
        loaded_dataset_ids.append(dataset_id)
        name, _suffix, _label = dataset_specs[dataset_id]
        return SimpleNamespace(
            dataset_id=dataset_id,
            name=name,
            user_id="user-dataset",
            is_public=True,
            parent_dataset_id=None,
            source_organ="lung",
            data_type="wsi",
        )

    class FakeWSIRepository:
        @staticmethod
        async def get_datasets(db, **kwargs):
            return dataset_rows if kwargs.get("data_type") == "wsi" else []

        @staticmethod
        async def get_by_dataset(db, dataset_id, **kwargs):
            return slides_by_dataset[dataset_id]

    def fake_llm(prompt):
        assert "Cervical Cytology External Validation" in prompt
        return json.dumps(
            {
                "matches": [
                    {"dataset_id": "tcga", "role": "internal", "confidence": "high", "reason": "training cohort"},
                    {"dataset_id": "nanfang", "role": "external", "confidence": "high", "reason": "external validation cohort"},
                ]
            }
        )

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

    captured_configs = []
    manager = route_module.AutoResearchSessionManager()
    manager.create_runner = lambda config, question, emit: captured_configs.append(config) or {"stage": "completed"}
    route_module._SESSION_MANAGER = manager
    disable_persistence(route_module)
    monkeypatch.setattr(route_module, "safe_session", lambda: FakeSafeSession())
    monkeypatch.setattr(route_module, "_autoresearch_dataset_match_llm_caller", lambda: fake_llm)
    monkeypatch.setattr(
        route_module,
        "_match_pathlab_datasets_from_question",
        lambda question, datasets: ["tcga", "nanfang", "cervical"],
    )
    monkeypatch.setattr("builtins.__import__", fake_import)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module, user_id="user-dataset")
    response = TestClient(app).post(
        "/autoresearch/sessions",
        json={
            "question": "Use TCGA-NSCLC as the internal training dataset. Use Nanfang-NSCLC as the external validation dataset.",
        },
    )

    assert response.status_code == 200
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not captured_configs:
        time.sleep(0.01)
    assert loaded_dataset_ids == ["tcga", "nanfang"]
    contract = captured_configs[0].external_test_contract
    assert contract["external_pathlab_uploads_dir"].startswith("/data/nanfang_nsclc")
    assert contract["external_features_dir"].startswith("/data/nanfang_nsclc")
    assert contract["external_labels_file"].startswith("/data/nanfang_nsclc")
    assert "cervical" not in json.dumps(contract).lower()
    internal = next(item for item in contract["datasets"] if item["role"] == "internal")
    external = next(item for item in contract["datasets"] if item["role"] == "external")
    assert internal["dataset_name"] == "TCGA-NSCLC"
    assert external["dataset_name"] == "Nanfang-NSCLC"


def test_resolve_pathlab_dataset_mounts_matches_question_dataset_name(monkeypatch, tmp_path):
    route_module = load_route_module()
    route_module._resolve_autoresearch_base_dir = lambda: tmp_path / "autoresearch-base"
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
        name="AutoResearch TCGA-LUAD",
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
            return [{"dataset_id": "dataset-luad", "dataset_name": "AutoResearch TCGA-LUAD"}]

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
            question="Use AutoResearch TCGA-LUAD for feature extraction",
        )
    )

    assert len(mounts) == 1
    [(host, container)] = mounts.items()
    assert Path(host).name.startswith("autoresearch_tcga_luad")
    assert container.startswith("/data/autoresearch_tcga_luad")


def test_resolve_pathlab_dataset_mounts_matches_patch_dataset_name(monkeypatch, tmp_path):
    route_module = load_route_module()
    route_module._resolve_autoresearch_base_dir = lambda: tmp_path / "autoresearch-base"
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


def test_resolve_pathlab_dataset_mounts_uses_llm_when_dataset_name_is_unknown(
    monkeypatch,
    tmp_path,
):
    route_module = load_route_module()
    route_module._resolve_autoresearch_base_dir = lambda: tmp_path / "autoresearch-base"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    slides = []
    for wsi_id, label, split in [
        ("patch-1", "MSIH", "train"),
        ("patch-2", "nonMSIH", "train"),
        ("patch-3", "MSIH", "test"),
    ]:
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
    prompts: list[str] = []

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
            if kwargs.get("data_type") == "patch":
                return [
                    {
                        "dataset_id": "patch-dataset",
                        "dataset_name": "CRC-MSI-100patches",
                        "data_type": "patch",
                        "task_type": "classification",
                        "source_organ": "colorectal",
                        "file_count": 100,
                        "labels": {"MSIH": 50, "nonMSIH": 50},
                    }
                ]
            return [
                {
                    "dataset_id": "wsi-dataset",
                    "dataset_name": "TCGA-LUAD Diagnostic Slides",
                    "data_type": "wsi",
                    "task_type": "classification",
                    "source_organ": "lung",
                    "file_count": 10,
                    "labels": {"LUAD": 10},
                }
            ]

        @staticmethod
        async def get_by_dataset(db, dataset_id, **kwargs):
            assert dataset_id == "patch-dataset"
            assert kwargs.get("data_type") == "patch"
            return slides

    def fake_llm(prompt):
        prompts.append(prompt)
        return (
            '{"matches": ['
            '{"dataset_id": "patch-dataset", "confidence": "high", '
            '"reason": "colorectal MSI patch classification dataset"}'
            "]}"
        )

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
    monkeypatch.setattr(route_module, "_autoresearch_dataset_match_llm_caller", lambda: fake_llm)
    monkeypatch.setattr("builtins.__import__", fake_import)

    mounts = route_module.asyncio.run(
        route_module._resolve_pathlab_dataset_mounts(
            [],
            SimpleNamespace(id="user-dataset", is_admin=lambda: False),
            question="Use the colorectal MSI patch test cohort for a quick smoke test",
        )
    )

    assert prompts
    assert "CRC-MSI-100patches" in prompts[0]
    assert "TCGA-LUAD Diagnostic Slides" in prompts[0]
    assert len(mounts) == 1
    [(host, container)] = mounts.items()
    assert Path(host).name.startswith("crc_msi_100patches")
    assert container.startswith("/data/crc_msi_100patches")
    assert (Path(host) / "images" / "MSIH").is_dir()


def test_resolve_pathlab_wsi_dataset_mounts_durable_root_without_session_view(
    monkeypatch,
    tmp_path,
):
    route_module = load_route_module()
    route_module._resolve_autoresearch_base_dir = lambda: tmp_path / "autoresearch-base"
    durable_root = tmp_path / "durable" / "Chronic-gastritis"
    wsi_dir = durable_root / "WSIs"
    wsi_dir.mkdir(parents=True)
    slides = []
    for idx, label in enumerate(["0", "1", "0", "1"], start=1):
        source = wsi_dir / f"slide-{idx}.svs"
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
        id=1,
        dataset_id="dataset-im",
        name="Chronic-gastritis",
        user_id="user-dataset",
        is_public=False,
        parent_dataset_id=None,
        source_organ="stomach",
        data_type="wsi",
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
        assert dataset_id == "dataset-im"
        return dataset

    class FakeWSIRepository:
        @staticmethod
        async def get_datasets(db, **kwargs):
            if kwargs.get("data_type") != "wsi":
                return []
            return [
                {
                    "dataset_id": "dataset-im",
                    "dataset_name": "Chronic-gastritis",
                    "data_type": "wsi",
                    "task_type": "classification",
                    "source_organ": "stomach",
                    "file_count": 4,
                    "labels": {"0": 2, "1": 2},
                }
            ]

        @staticmethod
        async def get_by_dataset(db, dataset_id, **kwargs):
            assert dataset_id == "dataset-im"
            assert kwargs.get("data_type") == "wsi"
            return slides

    def fail_prepare_view(**kwargs):
        raise AssertionError("registered WSI datasets should not create session view symlinks")

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
    monkeypatch.setattr(route_module, "_prepare_pathlab_dataset_view", fail_prepare_view)
    monkeypatch.setattr("builtins.__import__", fake_import)

    mounts = route_module.asyncio.run(
        route_module._resolve_pathlab_dataset_mounts(
            [],
            SimpleNamespace(id="user-dataset", is_admin=lambda: False),
            question="Use Chronic-gastritis as the internal training dataset.",
        )
    )

    assert len(mounts) == 2
    data_container = mounts[str(durable_root)]
    assert data_container.startswith("/data/chronic_gastritis")
    contract_hosts = [
        Path(host)
        for host, container in mounts.items()
        if container == f"{data_container}_contract"
    ]
    assert len(contract_hosts) == 1
    contract_dir = contract_hosts[0]
    assert contract_dir.name.startswith("chronic_gastritis")
    assert contract_dir.name.endswith("_contract")
    assert not (
        tmp_path / "autoresearch-base" / "pathlab_datasets" / "session_inputs" / "chronic_gastritis" / "WSIs"
    ).exists()
    assert not (durable_root / "dataset_manifest.json").exists()
    assert not (durable_root / "autoresearch_labels.csv").exists()
    assert not (durable_root / "autoresearch_splits.json").exists()
    manifest = json.loads((contract_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["layout"] == "pathlab_registered_dataset_root"
    assert manifest["pathlab_uploads_dir"] == data_container
    assert manifest["wsi_dir"] == f"{data_container}/WSIs"
    assert manifest["labels_file"] == f"{data_container}_contract/autoresearch_labels.csv"
    assert manifest["splits_file"] == f"{data_container}_contract/autoresearch_splits.json"
    assert (contract_dir / "autoresearch_labels.csv").is_file()
    assert (contract_dir / "autoresearch_splits.json").is_file()


def test_pathlab_dataset_contract_updates_uses_direct_root_manifest(tmp_path):
    route_module = load_route_module()
    contract_dir = tmp_path / "PWH-GC-IM_contract"
    contract_dir.mkdir(parents=True)
    (contract_dir / "autoresearch_labels.csv").write_text("slide_id,label\nslide-1,1\n", encoding="utf-8")
    (contract_dir / "autoresearch_splits.json").write_text("{}", encoding="utf-8")
    (contract_dir / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "layout": "pathlab_registered_dataset_root",
                "pathlab_uploads_dir": "/data/pwh_gc_im",
                "wsi_dir": "/data/pwh_gc_im/WSIs",
                "features_dir": "/data/pwh_gc_im/features/virchow2",
                "labels_file": "/data/pwh_gc_im_contract/autoresearch_labels.csv",
                "splits_file": "/data/pwh_gc_im_contract/autoresearch_splits.json",
            }
        ),
        encoding="utf-8",
    )

    updates = route_module._pathlab_dataset_contract_updates(str(contract_dir), "/data/pwh_gc_im_contract")

    assert updates["pathlab_uploads_dir"] == "/data/pwh_gc_im"
    assert updates["data_layout"] == "pathlab_uploads"
    assert updates["dataset_manifest_file"] == "/data/pwh_gc_im_contract/dataset_manifest.json"
    assert updates["wsi_dir"] == "/data/pwh_gc_im/WSIs"
    assert updates["pathlab_wsi_files_dir"] == "/data/pwh_gc_im/WSIs"
    assert updates["labels_file"] == "/data/pwh_gc_im_contract/autoresearch_labels.csv"
    assert updates["splits_file"] == "/data/pwh_gc_im_contract/autoresearch_splits.json"
    assert updates["features_dir"] == "/data/pwh_gc_im/features/virchow2"


def test_match_pathlab_datasets_from_question_matches_prefixed_hyphenated_names():
    route_module = load_route_module()
    datasets = [
        {
            "dataset_id": "internal-id",
            "dataset_name": "AutoResearch Chronic-gastritis",
            "data_type": "wsi",
        },
        {
            "dataset_id": "external-id",
            "dataset_name": "AutoResearch PWH-GC-IM",
            "data_type": "wsi",
        },
    ]

    matches = route_module._match_pathlab_datasets_from_question(
        "Use Chronic-gastritis as internal and PWH-GC-IM as external validation.",
        datasets,
    )

    assert matches == ["internal-id", "external-id"]


def test_match_pathlab_datasets_with_llm_times_out(monkeypatch):
    route_module = load_route_module()

    def slow_caller(_prompt):
        time.sleep(1)
        return '{"matches":[{"dataset_id":"dataset-id","confidence":"high"}]}'

    monkeypatch.setenv("AUTORESEARCH_DATASET_LLM_MATCH_TIMEOUT_SEC", "0.05")
    monkeypatch.setattr(route_module, "_autoresearch_dataset_match_llm_caller", lambda: slow_caller)

    started = time.time()
    matches = route_module._match_pathlab_datasets_with_llm(
        "unknown request",
        [{"dataset_id": "dataset-id", "dataset_name": "Unknown dataset"}],
    )

    assert matches == []
    assert time.time() - started < 0.5


def test_resolve_pathlab_dataset_mounts_uses_llm_to_add_requested_external_dataset(
    monkeypatch,
    tmp_path,
):
    route_module = load_route_module()
    route_module._resolve_autoresearch_base_dir = lambda: tmp_path / "autoresearch-base"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    internal_id = "521c7518-f72d-5e42-a243-385b91cf7b8c"
    external_id = "b84756e8-62ea-4d74-ba25-4829bd2060d8"

    slides_by_dataset = {}
    for dataset_id, labels in {
        internal_id: ["LUAD", "LUSC", "LUAD", "LUSC"],
        external_id: ["LUAD", "LUSC", "LUAD"],
    }.items():
        slides = []
        for idx, label in enumerate(labels, start=1):
            source = source_dir / f"{dataset_id}-{idx}.svs"
            source.write_text(f"{dataset_id} {idx}", encoding="utf-8")
            slides.append(
                SimpleNamespace(
                    wsi_id=f"{dataset_id}-{idx}",
                    wsi_path=str(source),
                    original_filename=source.name,
                    label=label,
                    split="train" if idx <= 2 else ("val" if idx == 3 else "test"),
                )
            )
        slides_by_dataset[dataset_id] = slides

    datasets = {
        internal_id: SimpleNamespace(
            id=1,
            dataset_id=internal_id,
            name="local - tcga-nsclc-subset4",
            user_id="user-dataset",
            is_public=False,
            parent_dataset_id=None,
            source_organ="lung",
            data_type="wsi",
        ),
        external_id: SimpleNamespace(
            id=2,
            dataset_id=external_id,
            name="synthetic - NSCLC-external-test",
            user_id="user-dataset",
            is_public=False,
            parent_dataset_id=None,
            source_organ="lung",
            data_type="wsi",
        ),
    }
    prompts: list[str] = []

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
        return datasets[dataset_id]

    class FakeWSIRepository:
        @staticmethod
        async def get_datasets(db, **kwargs):
            if kwargs.get("data_type") != "wsi":
                return []
            return [
                {
                    "dataset_id": internal_id,
                    "dataset_name": "local - tcga-nsclc-subset4",
                    "data_type": "wsi",
                    "task_type": "classification",
                    "source_organ": "lung",
                    "file_count": 4,
                    "labels": {"LUAD": 2, "LUSC": 2},
                },
                {
                    "dataset_id": external_id,
                    "dataset_name": "synthetic - NSCLC-external-test",
                    "data_type": "wsi",
                    "task_type": "classification",
                    "source_organ": "lung",
                    "file_count": 2,
                    "labels": {"LUAD": 1, "LUSC": 1},
                },
            ]

        @staticmethod
        async def get_by_dataset(db, dataset_id, **kwargs):
            assert kwargs.get("data_type") == "wsi"
            return slides_by_dataset[dataset_id]

    def fake_llm(prompt):
        prompts.append(prompt)
        return (
            '{"matches": ['
            f'{{"dataset_id": "{external_id}", "confidence": "high", '
            '"reason": "explicit nsclc_external_test external validation request"}'
            "]}"
        )

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
    monkeypatch.setattr(route_module, "_autoresearch_dataset_match_llm_caller", lambda: fake_llm)
    monkeypatch.setattr("builtins.__import__", fake_import)

    mounts = route_module.asyncio.run(
        route_module._resolve_pathlab_dataset_mounts(
            [],
            SimpleNamespace(id="user-dataset", is_admin=lambda: False),
            question=(
                "用内部数据集 local - tcga-nsclc-subset4 训练 NSCLC LUAD vs LUSC，"
                "然后用 nsclc_external_test 作为 external validation"
            ),
        )
    )

    assert len(mounts) == 2
    containers = set(mounts.values())
    assert any("local_tcga_nsclc_subset4" in c for c in containers)
    assert any("synthetic_nsclc_external_test" in c for c in containers)


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
        name="AutoResearch TCGA-LUAD",
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


def test_prepare_pathlab_dataset_view_prefers_task4_for_intestinal_metaplasia_question(tmp_path):
    route_module = load_route_module()
    source_dir = tmp_path / "source" / "WSIs"
    source_dir.mkdir(parents=True)
    labels_path = source_dir.parent / "labels.csv"
    labels_path.write_text(
        "slide_id,Task1,Task4\n"
        "slide-1,0,Intestinal metaplasia\n"
        "slide-2,1,Not Intestinal metaplasia\n"
        "slide-3,2,Intestinal metaplasia\n"
        "slide-4,3,Not Intestinal metaplasia\n",
        encoding="utf-8",
    )
    slides = []
    for idx, db_label in enumerate(["0", "1", "2", "3"], start=1):
        source = source_dir / f"slide-{idx}.svs"
        source.write_text(f"slide {idx}", encoding="utf-8")
        slides.append(
            SimpleNamespace(
                wsi_id=f"slide-{idx}",
                wsi_path=str(source),
                original_filename=source.name,
                label=db_label,
                split="",
            )
        )
    dataset = SimpleNamespace(
        dataset_id="dataset-im",
        name="AutoResearch Chronic-gastritis",
        source_organ="stomach",
    )

    view_dir = route_module._prepare_pathlab_dataset_view(
        dataset=dataset,
        slides=slides,
        view_dir=tmp_path / "view-im",
        question=(
            "Use Chronic-gastritis as the internal training dataset and "
            "PWH-GC-IM as the external validation dataset."
        ),
    )

    manifest = json.loads((view_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    labels_text = (view_dir / "labels.csv").read_text(encoding="utf-8")

    assert manifest["task_label_column"] == "Task4"
    assert manifest["classes"] == ["Intestinal metaplasia", "Not Intestinal metaplasia"]
    assert "s1" not in labels_text
    assert "Intestinal metaplasia" in labels_text
    assert "Not Intestinal metaplasia" in labels_text


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

    from backend.autoresearch.dataset.readiness import assess_data_readiness
    from backend.autoresearch.dataset.types import TaskProfile

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


def test_prepare_pathlab_dataset_view_links_registered_autoresearch_features(tmp_path):
    route_module = load_route_module()
    source_dir = tmp_path / "registered" / "WSIs"
    source_dir.mkdir(parents=True)
    feature_dir = tmp_path / "registered" / "features" / "virchow2"
    feature_dir.mkdir(parents=True)
    slides = []
    for idx, label in enumerate(["0", "1", "0"], start=1):
        source = source_dir / f"slide-{idx}.svs"
        source.write_text(f"slide {idx}", encoding="utf-8")
        feature = feature_dir / f"slide-{idx}.pt"
        feature.write_bytes(b"feature")
        slides.append(
            SimpleNamespace(
                wsi_id=f"uuid-slide-{idx}",
                wsi_path=str(source),
                original_filename=source.name,
                label=label,
                split="train" if idx == 1 else ("val" if idx == 2 else "test"),
                associated_files={
                    "autoresearch_features": {
                        "internal": {
                            "feature_path": str(feature),
                            "features_dir": str(feature_dir),
                            "extractor_name": "virchow2",
                        }
                    }
                },
            )
        )
    dataset = SimpleNamespace(
        dataset_id="dataset-registered-features",
        name="AutoResearch Registered Features",
        source_organ="stomach",
    )

    view_dir = route_module._prepare_pathlab_dataset_view(
        dataset=dataset,
        slides=slides,
        view_dir=tmp_path / "view",
    )

    for idx in range(1, 4):
        linked = view_dir / "features" / "virchow2" / f"uuid-slide-{idx}.pt"
        assert linked.is_symlink()
        assert linked.resolve() == (feature_dir / f"slide-{idx}.pt").resolve()
    manifest = json.loads((view_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["feature_link_count"] == 3
    assert manifest["feature_extractors"] == ["virchow2"]


def test_prepare_pathlab_dataset_view_remaps_no_tissue_feature_metadata(tmp_path):
    route_module = load_route_module()
    source_dir = tmp_path / "registered" / "WSIs"
    source_dir.mkdir(parents=True)
    feature_dir = tmp_path / "registered" / "features" / "virchow2"
    feature_dir.mkdir(parents=True)
    (tmp_path / "registered" / "extraction_meta.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "extractor": "virchow2",
                "results": {
                    "slide-1": {"status": "success"},
                    "slide-2": {"status": "no_tissue", "reason": "No detectable tissue"},
                    "slide-3": {"status": "success"},
                },
            }
        ),
        encoding="utf-8",
    )
    slides = []
    for idx, label in enumerate(["0", "1", "0"], start=1):
        source = source_dir / f"slide-{idx}.svs"
        source.write_text(f"slide {idx}", encoding="utf-8")
        if idx != 2:
            (feature_dir / f"slide-{idx}.pt").write_bytes(b"feature")
        slides.append(
            SimpleNamespace(
                wsi_id=f"uuid-slide-{idx}",
                wsi_path=str(source),
                original_filename=source.name,
                label=label,
                split="train" if idx == 1 else ("val" if idx == 2 else "test"),
            )
        )
    dataset = SimpleNamespace(
        dataset_id="dataset-no-tissue-features",
        name="AutoResearch no tissue metadata",
        source_organ="stomach",
    )

    view_dir = route_module._prepare_pathlab_dataset_view(
        dataset=dataset,
        slides=slides,
        view_dir=tmp_path / "view",
    )

    remapped = json.loads((view_dir / "extraction_meta.json").read_text(encoding="utf-8"))
    assert set(remapped["results"]) == {"uuid-slide-1", "uuid-slide-2", "uuid-slide-3"}
    assert remapped["results"]["uuid-slide-2"]["status"] == "no_tissue"


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


def test_sync_autoresearch_download_manifest_registers_pathlab_dataset(monkeypatch, tmp_path):
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
        route_module._sync_autoresearch_manifest_to_pathlab(
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


def test_sync_autoresearch_manifest_registers_uploads_root(monkeypatch, tmp_path):
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
        route_module._sync_autoresearch_manifest_to_pathlab(
            record,
            {"dataset_manifest_path": str(manifest_path)},
        )
    )

    assert result["status"] == "registered"
    assert result["dataset_name"] == "multi - all"
    assert result["created_wsi_count"] == 1


def test_create_session_returns_pending_title_without_waiting_for_llm_title():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="autoresearch-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    queued: list[str] = []
    route_module._queue_session_title_generation = lambda record, config: queued.append(record.session_id)
    route_module._generate_session_title = lambda question, config=None: (_ for _ in ()).throw(
        AssertionError("title LLM must not run on the create-session request path")
    )
    manager = route_module.AutoResearchSessionManager()

    def fake_runner(config, question, emit):
        return {"stage": "completed", "conversation_id": "conv_title"}

    manager.create_runner = fake_runner
    route_module._SESSION_MANAGER = manager
    route_module.autoresearch_persistence.persist_session_created = lambda **kwargs: None
    route_module.autoresearch_persistence.persist_event = lambda **kwargs: None
    route_module.autoresearch_persistence.persist_session_state = lambda **kwargs: None

    app = FastAPI()
    app.include_router(route_module.router)
    app.dependency_overrides[route_module.current_active_user] = lambda: SimpleNamespace(id="user-test")
    client = TestClient(app)
    question = (
        "我想训练一个 chronic gastritis inflammation grading 的 WSI MIL 分类任务，"
        "使用 SciDB 数据集并比较 ABMIL 和 TransMIL。"
    )

    response = client.post("/autoresearch/sessions", json={"question": question})

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == ""
    assert data["title_pending"] is True
    assert data["question"] == question
    assert queued == [data["session_id"]]



def test_create_session_rejects_ui_description_as_question():
    route_module = load_route_module()
    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.post(
        "/autoresearch/sessions",
        json={"question": "Structured AutoResearch execution console for this run."},
    )

    assert response.status_code == 422
    assert "real research question" in response.json()["detail"].lower()

def test_create_session_rejects_overlong_question():
    route_module = load_route_module()
    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.post("/autoresearch/sessions", json={"question": "x" * 4001})

    assert response.status_code == 422


def test_create_session_persists_current_user_id():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="autoresearch-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._queue_session_title_generation = lambda record, config: None
    route_module._scan_persisted_conversations = lambda *, curated_only=False: []
    calls: list[dict[str, str]] = []
    route_module.autoresearch_persistence.persist_session_created = (
        lambda **kwargs: calls.append(kwargs)
    )
    route_module.autoresearch_persistence.persist_event = lambda **kwargs: None
    route_module.autoresearch_persistence.persist_session_state = lambda **kwargs: None
    manager = route_module.AutoResearchSessionManager()
    manager.create_runner = lambda config, question, emit: {"stage": "completed"}
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    app.dependency_overrides[route_module.current_active_user] = lambda: SimpleNamespace(id="user-42")
    client = TestClient(app)

    response = client.post("/autoresearch/sessions", json={"question": "persist me"})

    assert response.status_code == 200
    assert calls
    assert calls[0]["user_id"] == "user-42"
    assert calls[0]["question"] == "persist me"


def test_background_title_generation_updates_record_title():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="autoresearch-route-test-"))
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


def test_session_title_prompt_requires_domain_and_task(monkeypatch):
    route_module = load_route_module()
    captured: dict[str, str] = {}

    class FakeMessage:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    class FakeTextContent:
        def __init__(self, text):
            self.text = text

    fake_openhands_llm = types.ModuleType("openhands.sdk.llm")
    fake_openhands_llm.Message = FakeMessage
    fake_openhands_llm.TextContent = FakeTextContent
    monkeypatch.setitem(sys.modules, "openhands.sdk.llm", fake_openhands_llm)

    fake_llm_client = types.ModuleType("backend.autoresearch.llm_client")
    fake_llm_client.make_llm_config = lambda **kwargs: SimpleNamespace()
    fake_llm_client.build_chat_llm = lambda *args, **kwargs: object()

    def fake_invoke_chat_llm(llm, *, messages, wire_api):
        captured["prompt"] = messages[0].content[0].text
        captured["wire_api"] = wire_api
        return "Lung NSCLC classification"

    fake_llm_client.invoke_chat_llm = fake_invoke_chat_llm
    fake_llm_client.extract_text = lambda response: str(response)
    monkeypatch.setitem(sys.modules, "backend.autoresearch.llm_client", fake_llm_client)

    title = route_module._generate_session_title(
        "Use TCGA-NSCLC as internal and Nanfang-NSCLC as external to train ABMIL."
    )

    assert title == "Lung NSCLC classification"
    assert captured["wire_api"] == "completion"
    prompt = captured["prompt"]
    assert "organ" in prompt.lower()
    assert "disease" in prompt.lower()
    assert "task" in prompt.lower()
    assert "action" in prompt.lower()
    assert "Lung NSCLC classification" in prompt


def test_fallback_session_title_includes_domain_and_task_for_nsclc_classification():
    route_module = load_route_module()

    title = route_module._fallback_session_title(
        "Use TCGA-NSCLC as the internal training dataset and Nanfang-NSCLC as external validation. "
        "Train an ABMIL model for classification."
    )

    assert "Lung" in title
    assert "NSCLC" in title
    assert "classification" in title


def test_fallback_session_title_includes_domain_and_task_for_gastric_im():
    route_module = load_route_module()

    title = route_module._fallback_session_title(
        "用 Chronic-gastritis 做 internal，PWH-GC-IM 做 external，训练一个 IM 分类模型"
    )

    assert any(token in title for token in ("Gastric", "Stomach", "Gastritis"))
    assert "IM" in title
    assert "classification" in title


def test_autoresearch_sessions_wait_in_gateway_queue_when_gpu_capacity_is_full(monkeypatch):
    route_module = load_route_module()
    monkeypatch.setattr(route_module.Config, "get_max_concurrent", lambda default=1: 1)
    monkeypatch.setattr(route_module.Config, "get_task_timeout", lambda: 30)
    route_module._queue_session_title_generation = lambda record, config: None
    manager = route_module.AutoResearchSessionManager()
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    finished = threading.Event()
    started_questions: list[str] = []

    def fake_runner(_config, question, _emit):
        started_questions.append(question)
        if question == "first run":
            first_started.set()
            assert release_first.wait(1.0)
        else:
            second_started.set()
        return {"stage": "completed", "conversation_id": f"conv-{question}"}

    manager.create_runner = fake_runner

    first = manager.start(route_module.StartAutoResearchSessionRequest(question="first run"), user_id="user-test")
    assert first_started.wait(1.0)

    second = manager.start(route_module.StartAutoResearchSessionRequest(question="second run"), user_id="user-test")

    assert second.status == "queued"
    assert second.stage == "queued"
    assert not second_started.wait(0.05)
    assert started_questions == ["first run"]

    release_first.set()
    assert second_started.wait(1.0)
    deadline = time.time() + 1.0
    while time.time() < deadline:
        if first.status == "completed" and second.status == "completed":
            finished.set()
            break
        time.sleep(0.01)

    assert finished.wait(0)
    assert started_questions == ["first run", "second run"]


def test_autoresearch_session_timeout_stops_running_processes(monkeypatch):
    route_module = load_route_module()
    from backend.autoresearch.runtime import session_registry

    monkeypatch.setattr(route_module.Config, "get_max_concurrent", lambda default=1: 1)
    monkeypatch.setattr(route_module.Config, "get_task_timeout", lambda: 0.05)
    route_module._queue_session_title_generation = lambda record, config: None
    cancelled = threading.Event()
    cleanup_calls: list[tuple[str, float, float]] = []

    def fake_cancel(session_id: str, *, term_timeout: float = 0.0, kill_timeout: float = 0.0):
        cleanup_calls.append((session_id, term_timeout, kill_timeout))
        cancelled.set()
        return {
            "active_process_count": 1,
            "terminated_process_groups": [9876],
            "sigterm_sent": [9876],
            "sigkill_sent": [9876],
            "processes": [{"session_id": session_id, "pgid": 9876}],
        }

    monkeypatch.setattr(session_registry, "cancel_session_processes", fake_cancel)
    manager = route_module.AutoResearchSessionManager()

    def slow_runner(_config, _question, _emit):
        assert cancelled.wait(1.0)
        return {"stage": "completed", "conversation_id": "conv-too-late"}

    manager.create_runner = slow_runner

    record = manager.start(route_module.StartAutoResearchSessionRequest(question="timeout run"), user_id="user-test")

    assert cancelled.wait(1.0)
    deadline = time.time() + 1.0
    while time.time() < deadline and record.status not in {"interrupted", "failed"}:
        time.sleep(0.01)

    assert record.status == "interrupted"
    assert record.stage == "interrupted"
    assert record.state["stop_reason"] == "task_timeout"
    assert "timed out" in record.error.lower()
    assert cleanup_calls == [(record.session_id, 3.0, 0.5)]
    assert record.state["process_cleanup"]["sigkill_sent"] == [9876]
    assert record.conversation_id != "conv-too-late"


def test_stop_running_session_marks_record_interrupted():
    route_module = load_route_module()
    manager = route_module.AutoResearchSessionManager()
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
    from backend.autoresearch.runtime import session_registry

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
    manager = route_module.AutoResearchSessionManager()
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


def test_stop_running_gateway_session_also_cancels_internal_autoresearch_session(monkeypatch):
    route_module = load_route_module()
    from backend.autoresearch.runtime import session_registry

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
    manager = route_module.AutoResearchSessionManager()
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
    registry_dir = Path(tempfile.mkdtemp(prefix="autoresearch-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    manager = route_module.AutoResearchSessionManager()

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
        route_module.StartAutoResearchSessionRequest(question="long run"),
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
    manager = route_module.AutoResearchSessionManager()
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

    response = client.post("/autoresearch/sessions/s-stop-api/stop")

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
    manager = route_module.AutoResearchSessionManager()
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
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.delete("/autoresearch/sessions/s-delete")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert client.get("/autoresearch/sessions/s-delete").status_code == 404
    assert all(item["session_id"] != "s-delete" for item in client.get("/autoresearch/sessions").json()["items"])

    restarted = route_module.AutoResearchSessionManager()
    route_module._SESSION_MANAGER = restarted
    assert all(record.session_id != "s-delete" for record in restarted.list())


def test_delete_session_endpoint_removes_safe_workspace(tmp_path):
    route_module = load_route_module()
    base_dir = tmp_path / "autoresearch-base"
    workspace = base_dir / "session_safe_delete"
    workspace.mkdir(parents=True)
    (workspace / "train.py").write_text("print('bye')\n", encoding="utf-8")
    route_module._resolve_autoresearch_base_dir = lambda: base_dir
    manager = route_module.AutoResearchSessionManager()
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

    response = client.delete("/autoresearch/sessions/s-delete-workspace")

    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] is True
    assert data["workspace_deleted"] is True
    assert data["workspace_path"] == str(workspace.resolve())
    assert not workspace.exists()


def test_delete_session_endpoint_does_not_remove_workspace_outside_base(tmp_path):
    route_module = load_route_module()
    base_dir = tmp_path / "autoresearch-base"
    outside_workspace = tmp_path / "outside-workspace"
    outside_workspace.mkdir()
    (outside_workspace / "keep.txt").write_text("important\n", encoding="utf-8")
    route_module._resolve_autoresearch_base_dir = lambda: base_dir
    manager = route_module.AutoResearchSessionManager()
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

    response = client.delete("/autoresearch/sessions/s-delete-outside-workspace")

    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] is True
    assert data["workspace_deleted"] is False
    assert data["workspace_delete_reason"] == "No workspace found for this session."
    assert outside_workspace.exists()


def test_delete_session_endpoint_does_not_follow_workspace_symlink(tmp_path):
    route_module = load_route_module()
    base_dir = tmp_path / "autoresearch-base"
    victim_workspace = base_dir / "victim-workspace"
    victim_workspace.mkdir(parents=True)
    keep_file = victim_workspace / "keep.txt"
    keep_file.write_text("important\n", encoding="utf-8")
    symlink_workspace = base_dir / "session_symlink"
    try:
        symlink_workspace.symlink_to(victim_workspace, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    route_module._resolve_autoresearch_base_dir = lambda: base_dir
    manager = route_module.AutoResearchSessionManager()
    record = route_module.SessionRecord(
        session_id="s-delete-symlink-workspace",
        conversation_id="conv-delete-symlink-workspace",
        question="old run",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
        state={"workspace_dir": str(symlink_workspace)},
    )
    manager._sessions[record.session_id] = record
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.delete("/autoresearch/sessions/s-delete-symlink-workspace")

    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] is True
    assert data["workspace_deleted"] is False
    assert data["workspace_delete_reason"] == "Workspace is a symlink; skipped for safety."
    assert symlink_workspace.is_symlink()
    assert keep_file.read_text(encoding="utf-8") == "important\n"


def test_delete_session_endpoint_rejects_running_session():
    route_module = load_route_module()
    manager = route_module.AutoResearchSessionManager()
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

    response = client.delete("/autoresearch/sessions/s-delete-running")

    assert response.status_code == 409
    assert manager.get("s-delete-running") is record


def test_delete_session_does_not_call_manager_delete_without_accessible_record(monkeypatch):
    route_module = load_route_module()
    manager = route_module.AutoResearchSessionManager()
    route_module._SESSION_MANAGER = manager

    async def fake_load_db_record(session_id, **kwargs):
        assert session_id == "unseen-session-id"
        return None

    def fail_delete(session_id: str):
        pytest.fail(f"manager.delete should not be called for unresolved session {session_id}")

    monkeypatch.setattr(route_module, "_load_db_record", fake_load_db_record)
    monkeypatch.setattr(manager, "delete", fail_delete)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.delete("/autoresearch/sessions/unseen-session-id")

    assert response.status_code == 404


def test_delete_session_resolves_db_record_to_runtime_session_id(monkeypatch):
    """Deleting by the DB-facing id must resolve to the internal runtime session_id.

    Regression: delete_session loaded a DB record but still called
    _SESSION_MANAGER.delete with the original route parameter. When the DB
    record maps to a different runtime session_id, the manager could not
    find the session and returned 404.
    """
    route_module = load_route_module()
    manager = route_module.AutoResearchSessionManager()
    route_module._SESSION_MANAGER = manager

    runtime_record = route_module.SessionRecord(
        session_id="runtime-session-id",
        conversation_id="conv-delete",
        question="old run",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
    )
    manager._sessions[runtime_record.session_id] = runtime_record

    db_facing_id = "db-facing-session-id"

    async def fake_load_db_record(session_id, **kwargs):
        assert session_id == db_facing_id
        return route_module.SessionRecord(
            session_id=runtime_record.session_id,
            conversation_id=runtime_record.conversation_id,
            question=runtime_record.question,
            model=runtime_record.model,
            user_id=runtime_record.user_id,
            status=runtime_record.status,
            stage=runtime_record.stage,
        )

    monkeypatch.setattr(route_module, "_load_db_record", fake_load_db_record)

    deleted_ids: list[str] = []
    original_delete = manager.delete

    def capturing_delete(session_id: str):
        deleted_ids.append(session_id)
        return original_delete(session_id)

    monkeypatch.setattr(manager, "delete", capturing_delete)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.delete(f"/autoresearch/sessions/{db_facing_id}")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert response.json()["session_id"] == runtime_record.session_id
    assert deleted_ids == [runtime_record.session_id]
    assert manager.get(runtime_record.session_id) is None


def test_delete_session_rejects_running_session_after_db_resolution(monkeypatch):
    """Queued/running rejection must still apply when the session is resolved from DB."""
    route_module = load_route_module()
    manager = route_module.AutoResearchSessionManager()
    route_module._SESSION_MANAGER = manager

    runtime_record = route_module.SessionRecord(
        session_id="runtime-running-id",
        conversation_id="conv-running",
        question="live run",
        model="gpt-5.5",
        user_id="user-test",
        status="running",
        stage="execution",
    )
    manager._sessions[runtime_record.session_id] = runtime_record

    db_facing_id = "db-facing-running-id"

    async def fake_load_db_record(session_id, **kwargs):
        assert session_id == db_facing_id
        return route_module.SessionRecord(
            session_id=runtime_record.session_id,
            conversation_id=runtime_record.conversation_id,
            question=runtime_record.question,
            model=runtime_record.model,
            user_id=runtime_record.user_id,
            status=runtime_record.status,
            stage=runtime_record.stage,
        )

    monkeypatch.setattr(route_module, "_load_db_record", fake_load_db_record)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.delete(f"/autoresearch/sessions/{db_facing_id}")

    assert response.status_code == 409
    assert manager.get(runtime_record.session_id) is runtime_record


def test_session_summary_includes_workspace_disk_usage(tmp_path):
    route_module = load_route_module()
    workspace = canonical_workspace(route_module, tmp_path / "settings-uploads", "workspace-size")
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
    workspace = canonical_workspace(route_module, tmp_path / "settings-uploads", "training-progress")
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


def test_session_summary_parses_patch_template_training_progress(tmp_path):
    route_module = load_route_module()
    workspace = canonical_workspace(route_module, tmp_path / "settings-uploads", "patch-training-progress")
    run_dir = workspace / "output" / "runs" / "run_patch"
    run_dir.mkdir(parents=True)
    log_path = run_dir / "training.log"
    log_path.write_text(
        "\n".join(
            [
                "2026-06-25 09:20:00 | INFO | epoch 1/50  loss=0.5300  val_auc=0.7200  val_acc=0.6700",
                "2026-06-25 09:21:00 | INFO | epoch 2/50  loss=0.4100  val_auc=0.8100  val_acc=0.7400",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(log_path, (2000, 2000))
    record = route_module.SessionRecord(
        session_id="s-patch-training-progress",
        conversation_id="",
        question="patch classification progress",
        model="gpt-5.5",
        status="running",
        stage="execution",
        state={"workspace_dir": str(workspace)},
    )

    progress = record.summary()["training_progress"]

    assert progress["run_id"] == "run_patch"
    assert progress["current_epoch"] == 2
    assert progress["total_epochs"] == 50
    assert progress["current_val_auc"] == 0.81
    assert progress["current_val_acc"] == 0.74
    assert progress["best_val_auc"] == 0.81
    assert progress["log_path"] == str(log_path.resolve())


def test_session_summary_marks_quick_check_training_progress(tmp_path):
    route_module = load_route_module()
    workspace = canonical_workspace(route_module, tmp_path / "settings-uploads", "training-progress-quick")
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
    workspace = canonical_workspace(route_module, tmp_path / "settings-uploads", "training-progress-quick-live")
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
    workspace = canonical_workspace(route_module, tmp_path / "settings-uploads", "slow-workspace-size")
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
    manager = route_module.AutoResearchSessionManager()
    route_module._SESSION_MANAGER = manager

    def broken_config(_req):
        raise RuntimeError("missing config")

    route_module._build_config = broken_config

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.post(
        "/autoresearch/sessions",
        json={"question": "quick smoke", "max_iter": 1},
    )

    assert response.status_code == 503
    assert "missing config" in response.json()["detail"]


def test_create_session_returns_fast_and_marks_failed_when_runtime_unavailable():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="autoresearch-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    route_module._queue_session_title_generation = lambda record, config: None
    manager = route_module.AutoResearchSessionManager()
    route_module._SESSION_MANAGER = manager

    def broken_runner():
        raise RuntimeError("missing runtime")

    route_module._load_runner = broken_runner

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.post(
        "/autoresearch/sessions",
        json={"question": "quick smoke", "max_iter": 1},
    )

    assert response.status_code == 200
    created = response.json()

    import time as _time
    for _ in range(20):
        detail = client.get(f"/autoresearch/sessions/{created['session_id']}").json()
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
        "/autoresearch/sessions",
        json={"question": "list me"},
    ).json()

    listed = client.get("/autoresearch/sessions").json()
    detail = client.get(f"/autoresearch/sessions/{created['session_id']}").json()

    assert any(item["session_id"] == created["session_id"] for item in listed["items"])
    assert detail["question"] == "list me"
    assert "events" in detail


def test_default_autoresearch_base_dir_uses_settings_autoresearch_root(monkeypatch, tmp_path):
    monkeypatch.delenv("AUTORESEARCH_BASE_DIR", raising=False)
    monkeypatch.delenv("AUTORESEARCH_PERSISTENCE_DIR", raising=False)
    monkeypatch.delenv("AUTORESEARCH_WORKSPACE", raising=False)
    uploads_dir = tmp_path / "settings-uploads"
    monkeypatch.setenv("PATHLAB_UPLOADS_DIR", str(uploads_dir))
    route_module = load_route_module()
    from backend.autoresearch.runtime.session import _resolve_base_dir

    base_dir = _resolve_base_dir()

    assert base_dir == uploads_dir / "autoresearch"
    assert not str(base_dir).startswith("/project/")
    assert route_module._resolve_autoresearch_base_dir() == base_dir.resolve()


def test_autoresearch_gateway_defaults_overwrite_stale_checkpoint_root(monkeypatch, tmp_path):
    uploads_dir = tmp_path / "settings-uploads"
    stale_code_checkpoints = (
        tmp_path / "repo" / "server" / "backend" / "ai" / "extractors" / "checkpoints"
    )
    monkeypatch.setenv("PATHLAB_UPLOADS_DIR", str(uploads_dir))
    monkeypatch.setenv("PATHLAB_CKPT_DIR", str(stale_code_checkpoints))
    route_module = load_route_module()

    config = SimpleNamespace()
    route_module._apply_autoresearch_gateway_defaults(config)

    expected = uploads_dir / "extractor_checkpoints"
    assert route_module._pathlab_feature_checkpoint_dir() == expected
    assert os.environ["PATHLAB_CKPT_DIR"] == str(expected)


def test_autoresearch_session_create_uses_autoresearch_sessions_subdir(monkeypatch, tmp_path):
    monkeypatch.delenv("AUTORESEARCH_BASE_DIR", raising=False)
    monkeypatch.delenv("AUTORESEARCH_PERSISTENCE_DIR", raising=False)
    uploads_dir = tmp_path / "settings-uploads"
    monkeypatch.setenv("PATHLAB_UPLOADS_DIR", str(uploads_dir))
    from backend.autoresearch.runtime.session import AutoResearchSession

    session = AutoResearchSession.create(research_question="canonical workspace")

    assert session.workspace_dir.parent == uploads_dir / "autoresearch" / "autoresearch_sessions"
    assert session.workspace_dir.name.startswith("session_")
    assert session.output_dir == session.workspace_dir / "output"
    assert session.persistence_root == uploads_dir / "autoresearch" / "conversations"


def test_list_sessions_uses_settings_autoresearch_root_without_env(monkeypatch, tmp_path):
    monkeypatch.delenv("AUTORESEARCH_BASE_DIR", raising=False)
    monkeypatch.delenv("AUTORESEARCH_PERSISTENCE_DIR", raising=False)
    uploads_dir = tmp_path / "settings-uploads"
    monkeypatch.setenv("PATHLAB_UPLOADS_DIR", str(uploads_dir))
    route_module = load_route_module()
    manager = route_module.AutoResearchSessionManager()
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.get("/autoresearch/sessions")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert route_module._resolve_autoresearch_base_dir() == (uploads_dir / "autoresearch").resolve()


def test_autoresearch_dataset_roots_stay_under_settings_autoresearch(monkeypatch, tmp_path):
    monkeypatch.delenv("AUTORESEARCH_BASE_DIR", raising=False)
    monkeypatch.delenv("AUTORESEARCH_DATASET_CACHE_DIR", raising=False)
    uploads_dir = tmp_path / "settings-uploads"
    monkeypatch.setenv("PATHLAB_UPLOADS_DIR", str(uploads_dir))
    route_module = load_route_module()

    assert route_module._default_autoresearch_dataset_cache_dir() == str(
        uploads_dir / "autoresearch" / "dataset_cache"
    )
    assert route_module._pathlab_dataset_view_parent() == (
        uploads_dir / "autoresearch" / "pathlab_datasets" / "session_inputs"
    )


def test_events_stream_replays_session_events():
    client = TestClient(make_app())
    created = client.post(
        "/autoresearch/sessions",
        json={"question": "stream me"},
    ).json()

    with client.stream("GET", f"/autoresearch/sessions/{created['session_id']}/events") as response:
        assert response.status_code == 200
        body = next(response.iter_text())

    assert "event:" in body
    assert "data:" in body


def test_events_carry_monotonic_seq():
    """Every emitted event must carry a strictly increasing ``seq`` so the
    frontend can dedup without relying on second-resolution timestamps."""
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="autoresearch-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    manager = route_module.AutoResearchSessionManager()

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

    created = client.post("/autoresearch/sessions", json={"question": "seq"}).json()
    # Wait for the worker thread to finish so all events are in.
    import time as _time
    for _ in range(20):
        detail = client.get(f"/autoresearch/sessions/{created['session_id']}").json()
        if detail["status"] in {"completed", "failed"}:
            break
        _time.sleep(0.05)
    else:
        raise AssertionError("session did not complete in time")

    seqs = [event["seq"] for event in detail["events"]]
    assert seqs == sorted(seqs), f"seq must be monotonic, got {seqs}"
    assert len(seqs) == len(set(seqs)), "seq must be unique"
    assert seqs[0] == 1


def test_gateway_runner_progress_callback_streams_director_state():
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="autoresearch-route-test-"))
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
    manager = route_module.AutoResearchSessionManager()
    emitted: list[dict] = []

    final_state = manager._invoke_runner(
        object(),
        route_module.StartAutoResearchSessionRequest(question="stream director progress"),
        emitted.append,
    )

    state_events = [event for event in emitted if event["kind"] == "state"]
    stages = [event["state"].get("stage") for event in state_events]

    assert "grounding" in stages
    assert "acquisition" in stages
    assert final_state["conversation_id"] == "conv-live-progress"


def test_gateway_runner_progress_callback_includes_download_progress_sidecar(tmp_path):
    route_module = load_route_module()
    registry_dir = Path(tempfile.mkdtemp(prefix="autoresearch-route-test-"))
    route_module._gateway_session_registry_path = (
        lambda: registry_dir / route_module.GATEWAY_SESSION_REGISTRY
    )
    workspace = canonical_workspace(route_module, tmp_path / "settings-uploads", "internal-live")
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
    manager = route_module.AutoResearchSessionManager()
    emitted: list[dict] = []

    final_state = manager._invoke_runner(
        object(),
        route_module.StartAutoResearchSessionRequest(question="stream download progress"),
        emitted.append,
    )

    state_events = [event for event in emitted if event["kind"] == "state"]
    assert state_events[-1]["state"]["download_progress"]["status"] == "downloading"
    assert state_events[-1]["state"]["download_progress"]["downloaded_bytes"] == 5 * 1024 * 1024
    assert final_state["download_progress"]["current_file"] == "panda.zip"


def test_download_progress_poller_emits_state_events(tmp_path):
    route_module = load_route_module()
    route_module.DOWNLOAD_PROGRESS_POLL_SECONDS = 0.01
    workspace = canonical_workspace(route_module, tmp_path / "settings-uploads", "poll-live")
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
    manager = route_module.AutoResearchSessionManager()
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

    data = client.get("/autoresearch/sessions").json()

    ids = {item["session_id"] for item in data["items"]}
    assert {"db1", "live1"} <= ids


def test_admin_session_responses_include_owner_username(monkeypatch):
    route_module = load_route_module()
    route_module._DB_HISTORY_ENABLED = True
    record = route_module.SessionRecord(
        session_id="admin-visible",
        conversation_id="",
        question="admin sees owner",
        model="gpt-5.5",
        user_id="owner-1",
        status="completed",
        stage="completed",
    )
    route_module._SESSION_MANAGER = route_module.AutoResearchSessionManager()
    route_module._SESSION_MANAGER._sessions[record.session_id] = record

    async def fake_db_list(*, user, include_persisted, limit=100):
        assert user.is_admin() is True
        return []

    async def fake_owner_names(user_ids):
        assert user_ids == {"owner-1"}
        return {"owner-1": "Yihui Wang"}

    monkeypatch.setattr(route_module, "_load_db_session_list", fake_db_list)
    monkeypatch.setattr(route_module, "_load_autoresearch_owner_names", fake_owner_names)

    admin = SimpleNamespace(id="admin", is_admin=lambda: True)

    list_response = asyncio.run(route_module.list_sessions(user=admin))
    assert list_response["items"][0]["username"] == "Yihui Wang"

    detail_response = asyncio.run(route_module.get_session("admin-visible", user=admin))
    assert detail_response["username"] == "Yihui Wang"


def test_non_admin_session_responses_do_not_include_owner_username(monkeypatch):
    route_module = load_route_module()
    record = route_module.SessionRecord(
        session_id="own-session",
        conversation_id="",
        question="owner view",
        model="gpt-5.5",
        user_id="owner-1",
        status="completed",
        stage="completed",
    )
    route_module._SESSION_MANAGER = route_module.AutoResearchSessionManager()
    route_module._SESSION_MANAGER._sessions[record.session_id] = record

    async def fail_owner_names(_user_ids):
        raise AssertionError("owner names should only be loaded for admin users")

    monkeypatch.setattr(route_module, "_load_autoresearch_owner_names", fail_owner_names)
    user = SimpleNamespace(id="owner-1", is_admin=lambda: False)

    list_response = asyncio.run(route_module.list_sessions(user=user))
    assert "username" not in list_response["items"][0]

    detail_response = asyncio.run(route_module.get_session("own-session", user=user))
    assert "username" not in detail_response


def test_get_session_falls_back_to_db_record(monkeypatch):
    route_module = load_route_module()
    route_module._DB_HISTORY_ENABLED = True
    route_module._SESSION_MANAGER = route_module.AutoResearchSessionManager()
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

    data = client.get("/autoresearch/sessions/db-detail").json()

    assert data["question"] == "from db"
    assert data["resume_available"] is True
    assert data["events"][0]["text"] == "hello"


def test_delete_session_deletes_db_backed_history_record(monkeypatch):
    route_module = load_route_module()
    route_module._DB_HISTORY_ENABLED = True
    route_module._SESSION_MANAGER = route_module.AutoResearchSessionManager()
    record = route_module.SessionRecord(
        session_id="db-delete",
        conversation_id="conv-delete",
        question="from db",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
    )
    deleted: list[str] = []
    route_module.autoresearch_persistence.delete_session = deleted.append

    async def fake_db_record(session_id, **kwargs):
        assert session_id == "db-delete"
        assert kwargs["include_events"] is False
        assert kwargs["register"] is True
        route_module._SESSION_MANAGER.register_hydrated(record)
        return record

    monkeypatch.setattr(route_module, "_load_db_record", fake_db_record)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.delete("/autoresearch/sessions/db-delete")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert deleted == ["db-delete"]


def test_access_token_mint_does_not_replay_db_events(monkeypatch):
    route_module = load_route_module()
    route_module._DB_HISTORY_ENABLED = True
    route_module._SESSION_MANAGER = route_module.AutoResearchSessionManager()
    record = route_module.SessionRecord(
        session_id="db-token",
        conversation_id="conv-token",
        question="from db",
        model="gpt-5.5",
        user_id="user-test",
        status="completed",
        stage="completed",
    )

    async def fake_db_record(session_id, **kwargs):
        assert session_id == "db-token"
        assert kwargs["include_events"] is False
        return record

    monkeypatch.setattr(route_module, "_load_db_record", fake_db_record)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module)
    client = TestClient(app)

    response = client.post(
        "/autoresearch/sessions/db-token/access-token",
        json={"purpose": "session_download"},
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == "db-token"


def test_get_session_enriches_external_test_from_workspace_artifacts(tmp_path):
    route_module = load_route_module()
    workspace = canonical_workspace(route_module, tmp_path / "settings-uploads", "external-artifact")
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
    manager = route_module.AutoResearchSessionManager()
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

    data = client.get("/autoresearch/sessions/s-external-artifact").json()

    assert data["state"]["external_test"] == {
        "run_id": "run_best",
        "status": "completed",
        "committed": True,
        "run_dir": str(run_dir),
        "metrics": {"auc": 0.9421, "accuracy": 0.875, "n_external_evaluated": 4},
        "features_dir": "/data/nsclc_external_test/features/virchow2/paramsabc",
        "splits_file": "/data/nsclc_external_test/splits.json",
    }


def test_run_zip_for_model_run_includes_linked_external_test_artifacts(tmp_path):
    route_module = load_route_module()
    workspace = canonical_workspace(route_module, tmp_path / "settings-uploads", "zip-external")
    model_path = workspace / "model_artifacts" / "s1" / "run_best" / "best_model.pth"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"model-bytes")

    best_evidence = workspace / ".evidence" / "runs" / "run_best"
    (best_evidence / "artifacts").mkdir(parents=True)
    (best_evidence / "artifacts" / "best_model.pth").write_bytes(b"model-bytes")
    (best_evidence / "record.json").write_text(
        json.dumps({
            "run_id": "run_best",
            "run_dir": "output/runs/run_best",
            "metrics": {"auc": 0.976},
            "committed": True,
            "model_path": str(model_path),
            "artifacts": [
                {
                    "name": "best_model.pth",
                    "path": "output/runs/run_best/best_model.pth",
                    "storage_mode": "copy",
                }
            ],
        }),
        encoding="utf-8",
    )

    external_run_dir = workspace / "output" / "runs" / "run_external"
    external_run_dir.mkdir(parents=True)
    (external_run_dir / "external_test_report.json").write_text(
        json.dumps({"external_test": {"auc": 0.726, "accuracy": 0.784}}),
        encoding="utf-8",
    )
    (external_run_dir / "metrics.json").write_text(
        json.dumps({"auc": 0.726, "external": {"auc": 0.726}}),
        encoding="utf-8",
    )
    external_evidence = workspace / ".evidence" / "runs" / "run_external"
    external_evidence.mkdir(parents=True)
    external_artifacts = external_evidence / "artifacts"
    external_artifacts.mkdir()
    (external_artifacts / "predictions.csv").write_text(
        "sample_id,prediction\nslide-1,1\n",
        encoding="utf-8",
    )
    (external_evidence / "record.json").write_text(
        json.dumps({
            "run_id": "run_external",
            "run_dir": "output/runs/run_external",
            "metrics": {"auc": 0.726, "external": {"auc": 0.726}},
            "committed": False,
            "model_path": str(model_path),
            "artifacts": [
                {
                    "name": "external_test_report.json",
                    "path": "output/runs/run_external/external_test_report.json",
                    "storage_mode": "manifest",
                },
                {
                    "name": "predictions.csv",
                    "path": "output/runs/run_external/predictions.csv",
                    "storage_mode": "copy",
                },
                {
                    "name": "metrics.json",
                    "path": "output/runs/run_external/metrics.json",
                    "storage_mode": "manifest",
                },
            ],
        }),
        encoding="utf-8",
    )

    record = route_module.SessionRecord(
        session_id="s1",
        conversation_id="",
        question="q",
        model="gpt-5.5",
        status="completed",
        stage="completed",
        state={
            "best_run_id": "run_best",
            "run_history": [
                {
                    "run_id": "run_best",
                    "committed": True,
                    "model_path": str(model_path),
                    "metrics": {"auc": 0.976},
                }
            ],
            "external_test": {
                "run_id": "run_external",
                "run_dir": "output/runs/run_external",
                "status": "completed",
                "metrics": {"auc": 0.726, "model_path": str(model_path)},
            },
        },
    )

    zip_path = route_module._build_run_artifact_zip(record, workspace, "run_best")

    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
            assert "artifacts/external_test/run_external/external_test_report.json" in names
            assert "artifacts/external_test/run_external/predictions.csv" in names
            assert "artifacts/external_test/run_external/metrics.json" in names
            assert not any(name.startswith("external_test/") for name in names)
            assert json.loads(archive.read("artifacts/external_test/run_external/external_test_report.json")) == {
                "external_test": {"auc": 0.726, "accuracy": 0.784}
            }
    finally:
        Path(zip_path).unlink(missing_ok=True)


def test_run_zip_for_model_run_excludes_feature_cache_artifacts(tmp_path):
    route_module = load_route_module()
    workspace = canonical_workspace(route_module, tmp_path / "settings-uploads", "zip-feature-cache")
    run_id = "run_patch"
    output_run_dir = workspace / "output" / "runs" / run_id
    output_run_dir.mkdir(parents=True)
    (output_run_dir / "best_model.pth").write_bytes(b"model-bytes")
    (output_run_dir / "metrics.json").write_text(json.dumps({"auc": 0.91}), encoding="utf-8")
    (output_run_dir / "run_metadata.json").write_text(
        json.dumps({"run_id": run_id, "quick_check": False}),
        encoding="utf-8",
    )
    (output_run_dir / "train.log").write_text("epoch 1 auc=0.91\n", encoding="utf-8")
    cache_file = output_run_dir / "patch_feature_cache" / "uni" / "train_cache.pt"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"feature-cache-bytes")

    evidence_run_dir = workspace / ".evidence" / "runs" / run_id
    (evidence_run_dir / "artifacts").mkdir(parents=True)
    (evidence_run_dir / "record.json").write_text(
        json.dumps({
            "run_id": run_id,
            "run_dir": f"output/runs/{run_id}",
            "metrics": {"auc": 0.91},
            "committed": True,
            "model_path": str(output_run_dir / "best_model.pth"),
            "artifacts": [
                {
                    "name": "best_model.pth",
                    "path": f"output/runs/{run_id}/best_model.pth",
                    "storage_mode": "copy",
                },
                {
                    "name": "metrics.json",
                    "path": f"output/runs/{run_id}/metrics.json",
                    "storage_mode": "copy",
                },
                {
                    "name": "run_metadata.json",
                    "path": f"output/runs/{run_id}/run_metadata.json",
                    "storage_mode": "manifest",
                },
                {
                    "name": "train.log",
                    "path": f"output/runs/{run_id}/train.log",
                    "storage_mode": "manifest",
                },
                {
                    "name": "train_cache.pt",
                    "path": f"output/runs/{run_id}/patch_feature_cache/uni/train_cache.pt",
                    "storage_mode": "manifest",
                },
            ],
        }),
        encoding="utf-8",
    )
    record = route_module.SessionRecord(
        session_id="s1",
        conversation_id="",
        question="q",
        model="gpt-5.5",
        status="completed",
        stage="completed",
        state={
            "best_run_id": run_id,
            "run_history": [
                {
                    "run_id": run_id,
                    "committed": True,
                    "model_path": str(output_run_dir / "best_model.pth"),
                    "metrics": {"auc": 0.91},
                }
            ],
        },
    )

    zip_path = route_module._build_run_artifact_zip(record, workspace, run_id)

    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
            assert "artifacts/best_model.pth" in names
            assert "artifacts/metrics.json" in names
            assert "artifacts/run_metadata.json" in names
            assert "artifacts/train.log" in names
            assert not any("patch_feature_cache" in name for name in names)
            assert "artifacts/train_cache.pt" not in names
            assert not any(name.startswith("artifacts/best_model-") for name in names)
            assert not any(name.startswith("artifacts/metrics-") for name in names)
            assert not any(name.startswith("artifacts/run_metadata-") for name in names)
            assert not any(name.startswith("artifacts/train-") for name in names)
    finally:
        Path(zip_path).unlink(missing_ok=True)


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


def test_workspace_resolution_prefers_canonical_autoresearch_session(monkeypatch, tmp_path):
    route_module = load_route_module()
    uploads_dir = tmp_path / "settings-uploads"
    canonical_workspace = uploads_dir / "autoresearch" / "autoresearch_sessions" / "session_internal-live"
    stale_workspace = tmp_path / "old-upload-root" / "autoresearch" / "session_internal-live"
    canonical_workspace.mkdir(parents=True)
    stale_workspace.mkdir(parents=True)
    monkeypatch.setattr(route_module.Config, "get_uploads_dir", staticmethod(lambda: uploads_dir))

    workspace = route_module._resolve_workspace_from_state({
        "session_id": "internal-live",
        "workspace_path": str(stale_workspace),
    })

    assert workspace == canonical_workspace.resolve()


def test_db_running_session_with_recent_training_log_stays_running(tmp_path, monkeypatch):
    route_module = load_route_module()
    monkeypatch.setattr(route_module, "LEGACY_RUNNING_STALE_SECONDS", 600)
    monkeypatch.setattr(route_module.time, "time", lambda: 2_000.0)
    workspace = canonical_workspace(route_module, tmp_path / "settings-uploads", "live-db-running")
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
        recovery_metadata={"session_id": "live-db-running", "workspace_path": str(workspace)},
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
    workspace = canonical_workspace(route_module, tmp_path / "settings-uploads", "gateway-live-training")
    run_dir = workspace / "output" / "runs" / "run_live"
    run_dir.mkdir(parents=True)
    log_path = run_dir / "training.log"
    log_path.write_text(
        "2026-06-17 23:44:55 | INFO | Epoch 9/30 | loss=0.0355 | val_auc=0.9603\n",
        encoding="utf-8",
    )
    os.utime(log_path, (1_950.0, 1_950.0))
    record = route_module.SessionRecord(
        session_id="gateway-live-training",
        conversation_id="conv-live-training",
        question="train",
        model="gpt-5.5",
        user_id="user-test",
        status="running",
        stage="execution",
        state={"workspace_path": str(workspace), "stage": "execution"},
        created_at=100.0,
        updated_at=1_000.0,
    )

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
    workspace = canonical_workspace(route_module, tmp_path / "settings-uploads", "gateway-long-epoch")
    run_dir = workspace / "output" / "runs" / "run_live"
    run_dir.mkdir(parents=True)
    log_path = run_dir / "training.log"
    log_path.write_text(
        "2026-06-17 23:44:55 | INFO | Epoch 9/30 | loss=0.0355 | val_auc=0.9603\n",
        encoding="utf-8",
    )
    os.utime(log_path, (2_000.0, 2_000.0))
    record = route_module.SessionRecord(
        session_id="gateway-long-epoch",
        conversation_id="conv-long-epoch",
        question="train",
        model="gpt-5.5",
        user_id="user-test",
        status="running",
        stage="execution",
        state={"workspace_path": str(workspace), "stage": "execution"},
        created_at=100.0,
        updated_at=1_000.0,
    )

    assert record.status == "running"
    assert record.stage == "execution"
    assert record.summary()["training_progress"]["current_epoch"] == 9


def test_events_stream_replays_db_events_when_jsonl_missing(monkeypatch):
    route_module = load_route_module()
    route_module._DB_HISTORY_ENABLED = True
    route_module._SESSION_MANAGER = route_module.AutoResearchSessionManager()
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

    with client.stream("GET", "/autoresearch/sessions/db-events/events") as response:
        assert response.status_code == 200
        body = next(response.iter_text())

    assert "replayed from db" in body


def test_get_session_denies_other_users_db_record(monkeypatch):
    route_module = load_route_module()
    route_module._DB_HISTORY_ENABLED = True
    route_module._SESSION_MANAGER = route_module.AutoResearchSessionManager()

    async def forbidden_db_record(session_id, **_kwargs):
        raise route_module.HTTPException(status_code=403, detail="AutoResearch session access denied")

    monkeypatch.setattr(route_module, "_load_db_record", forbidden_db_record)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module, user_id="user-a")
    client = TestClient(app)

    response = client.get("/autoresearch/sessions/private-session")

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/autoresearch/sessions/private-session/stop"),
        ("delete", "/autoresearch/sessions/private-session"),
    ],
)
def test_mutating_session_endpoints_deny_other_users_db_record(monkeypatch, method, path):
    route_module = load_route_module()
    route_module._DB_HISTORY_ENABLED = True
    route_module._SESSION_MANAGER = route_module.AutoResearchSessionManager()

    async def forbidden_db_record(session_id, **_kwargs):
        assert session_id == "private-session"
        raise route_module.HTTPException(status_code=403, detail="AutoResearch session access denied")

    monkeypatch.setattr(route_module, "_load_db_record", forbidden_db_record)

    app = FastAPI()
    app.include_router(route_module.router)
    install_fake_user(app, route_module, user_id="user-a")
    client = TestClient(app)

    response = getattr(client, method)(path)

    assert response.status_code == 403


def test_resume_session_rejects_missing_checkpoint():
    route_module = load_route_module()
    manager = route_module.AutoResearchSessionManager()
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

    response = client.post("/autoresearch/sessions/resume-missing/resume")

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
    manager = route_module.AutoResearchSessionManager()
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

    response = client.post("/autoresearch/sessions/resume-ok/resume")

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
