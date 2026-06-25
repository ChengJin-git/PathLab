from __future__ import annotations

import asyncio
import concurrent.futures
import importlib.util
import sys
import types
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1]


def load_persistence_module():
    package = types.ModuleType("backend.database.repositories")
    package.__path__ = [str(SERVER_ROOT / "backend" / "database" / "repositories")]
    package.DataGroupRepository = object
    package.WSIRepository = object
    sys.modules["backend.database.repositories"] = package

    auto_research = types.ModuleType("backend.database.repositories.auto_research")

    class _AutoResearchRepository:
        pass

    auto_research.AutoResearchRepository = _AutoResearchRepository
    sys.modules["backend.database.repositories.auto_research"] = auto_research

    module_name = "gateway.autoresearch_persistence_under_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        SERVER_ROOT / "gateway" / "autoresearch_persistence.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_session_payload_truncates_research_question():
    persistence = load_persistence_module()
    payload = persistence._session_payload(
        session_id="sid",
        user_id="user-1",
        question="x" * 5000,
        status="running",
        stage="stage",
        state={},
        max_iterations=1,
        metric="auc",
        model="model",
        workspace_path="/tmp/ws",
    )

    assert len(payload["research_question"]) <= 4000 + len("\n...[truncated]")
    assert payload["research_question"].endswith("...[truncated]")


def test_json_safe_applies_depth_and_byte_budget():
    persistence = load_persistence_module()
    nested = current = {}
    for index in range(80):
        child = {"payload": "x" * 1000}
        current[f"level_{index}"] = child
        current = child

    safe = persistence._json_safe(nested, max_depth=5, byte_budget=2000)

    text = str(safe)
    assert len(text) < 2500
    assert "truncated" in text


def test_best_effort_uses_per_loop_queue_without_global_lock():
    persistence = load_persistence_module()

    async def scenario():
        loop = asyncio.get_running_loop()
        persistence.configure_loop(loop)
        seen: list[str] = []

        async def append(value: str):
            seen.append(value)

        persistence._run_best_effort(append("first"), "append first")
        persistence._run_best_effort(append("second"), "append second")
        await persistence.drain_persistence_queue(timeout=1)

        assert seen == ["first", "second"]

    asyncio.run(scenario())
    assert not hasattr(persistence, "_persist_lock")


def test_best_effort_cancels_cross_thread_enqueue_future_on_timeout(monkeypatch):
    persistence = load_persistence_module()
    cancelled: list[bool] = []

    class FakeLoop:
        def is_closed(self):
            return False

    class FakeFuture:
        def result(self, timeout=None):
            raise concurrent.futures.TimeoutError()

        def cancel(self):
            cancelled.append(True)

    async def never_run():
        return None

    def fake_run_coroutine_threadsafe(coro, loop):
        coro.close()
        return FakeFuture()

    monkeypatch.setattr(persistence, "_gateway_loop", FakeLoop())
    monkeypatch.setattr(
        persistence.asyncio,
        "run_coroutine_threadsafe",
        fake_run_coroutine_threadsafe,
    )

    persistence._run_best_effort(never_run(), "timeout action")

    assert cancelled == [True]


def test_terminal_model_registration_failure_is_persisted(monkeypatch):
    persistence = load_persistence_module()
    captured: dict[str, object] = {}

    class FakeRepository:
        @staticmethod
        async def upsert_session(db, payload):
            captured["session_payload"] = payload

        @staticmethod
        async def upsert_experiment_by_run_id(db, experiment):
            return experiment

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            captured["committed"] = True

    async def failing_registration(*_args, **_kwargs):
        raise RuntimeError("registry write failed")

    monkeypatch.setattr(persistence, "AutoResearchRepository", FakeRepository)
    monkeypatch.setattr(persistence, "safe_session", lambda: FakeSession())
    monkeypatch.setattr(
        persistence,
        "_register_pathlab_trained_model",
        failing_registration,
    )

    state = {
        "stage": "completed",
        "run_history": [
            {
                "run_id": "run-a",
                "committed": True,
                "model_path": "/tmp/model.pt",
                "metric_value": 0.91,
            }
        ],
    }

    asyncio.run(
        persistence._persist_session_state(
            session_id="sid",
            user_id="user-1",
            question="train model",
            status="completed",
            stage="completed",
            state=state,
            max_iterations=1,
            metric="auc",
            model="model",
            workspace_path="/tmp/workspace",
        )
    )

    registration = captured["session_payload"]["recovery_metadata"][
        "pathlab_model_registration"
    ]
    assert registration["registered"] is False
    assert registration["reason"] == "registry write failed"
    assert registration["session_id"] == "sid"
    assert captured["committed"] is True
