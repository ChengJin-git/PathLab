import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROUTE_PATH = Path(__file__).resolve().parents[1] / "gateway" / "routes" / "pathscientist.py"


def load_route_module():
    spec = importlib.util.spec_from_file_location("pathscientist_route_under_test", ROUTE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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

    app = FastAPI()
    app.include_router(route_module.router)
    return app


def test_lists_registered_skills():
    client = TestClient(make_app())

    response = client.get("/pathscientist/skills")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert any(item["id"] == "mil_classification" for item in data["items"])


def test_create_session_returns_default_model():
    client = TestClient(make_app())

    response = client.post(
        "/pathscientist/sessions",
        json={"question": "quick smoke", "max_iter": 1},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"]
    assert data["model"] == "gpt-5.5"
    assert data["status"] in {"queued", "running", "completed"}


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

    app = FastAPI()
    app.include_router(route_module.router)
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
        status="running",
        stage="execution",
    )
    manager._sessions[record.session_id] = record
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
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
        status="completed",
        stage="completed",
    )
    manager._sessions[record.session_id] = record
    route_module._save_gateway_session_record(record)
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
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
        status="completed",
        stage="completed",
        state={"workspace_dir": str(workspace)},
    )
    manager._sessions[record.session_id] = record
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
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
        status="completed",
        stage="completed",
        state={"workspace_dir": str(outside_workspace)},
    )
    manager._sessions[record.session_id] = record
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
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
        status="running",
        stage="execution",
    )
    manager._sessions[record.session_id] = record
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
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
        status="completed",
        stage="completed",
    )
    route_module._scan_persisted_conversations = lambda *, curated_only=False: [legacy]
    manager = route_module.PathScientistSessionManager()
    route_module._SESSION_MANAGER = manager

    app = FastAPI()
    app.include_router(route_module.router)
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
        status="finished",
        stage="finished",
    )
    route_module._scan_persisted_conversations = lambda *, curated_only=False: [legacy]

    app = FastAPI()
    app.include_router(route_module.router)
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
        status="completed",
        stage="completed",
    )
    legacy = route_module.SessionRecord(
        session_id="legacy123",
        conversation_id="conv-dup",
        question="same run",
        model="",
        status="finished",
        stage="completed",
    )
    with manager._lock:
        manager._sessions[gateway.session_id] = gateway
    route_module._scan_persisted_conversations = lambda *, curated_only=False: [legacy]

    app = FastAPI()
    app.include_router(route_module.router)
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
        status="running",
        stage="execution",
        state={"conversation_id": "conv-live-dup", "session_id": "workspace123"},
    )
    legacy = route_module.SessionRecord(
        session_id="legacy123",
        conversation_id="conv-live-dup",
        question="same live run",
        model="",
        status="running",
        stage="execution",
    )
    with manager._lock:
        manager._sessions[gateway.session_id] = gateway
    route_module._scan_persisted_conversations = lambda *, curated_only=False: [legacy]

    app = FastAPI()
    app.include_router(route_module.router)
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
        status="running",
        stage="execution",
    )
    route_module._scan_persisted_conversations = lambda *, curated_only=False: [legacy]
    route_module._SESSION_MANAGER = route_module.PathScientistSessionManager()

    app = FastAPI()
    app.include_router(route_module.router)
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
        status="finished",
        stage="finished",
    )
    route_module._scan_persisted_conversations = lambda *, curated_only=False: [legacy]

    app = FastAPI()
    app.include_router(route_module.router)
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
    for name in (
        "PATHSCIENTIST_ENV_FILE",
        "PATHSCIENTIST_LLM_MODEL",
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
    monkeypatch.setenv("PATHSCIENTIST_ENV_FILE", str(tmp_path / "missing.env"))

    config = route_module._build_config(
        route_module.StartPathScientistSessionRequest(question="align defaults")
    )

    assert config.llm_model == "gpt-5.5"
    assert config.llm_profile == "codex-relay"
    assert config.llm_wire_api == "responses"
    assert config.sandbox_mode == "auto"
    assert config.max_iterations == 5
    assert config.literature_online_enabled is True
    assert config.literature_online_max_results == 10
    assert config.auto_acquire_data is True
    assert config.download_policy == "all"
    assert config.max_download_size_gb == 500
    assert config.allow_large_downloads is True
    assert config.dataset_cache_dir == "/project/llmponco/wangyihui/original_data/pathlab_test_data"
    assert os.environ["PATHSCIENTIST_GENERATE_PAPER_DRAFT"] == "0"
    assert os.environ["PATHSCIENTIST_FEATURE_EXTRACTOR_MODE"] == "auto"
    assert os.environ.get("PATHSCIENTIST_FEATURE_EXTRACTOR", "") == ""
    assert os.environ.get("PATHSCIENTIST_MIL_MODEL", "") == ""


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
        status="error",
        stage="error",
    )

    def fake_scan(*, curated_only=False):
        return [] if curated_only else [noisy]

    route_module._scan_persisted_conversations = fake_scan

    app = FastAPI()
    app.include_router(route_module.router)
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
