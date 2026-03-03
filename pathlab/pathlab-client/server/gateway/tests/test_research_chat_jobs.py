import asyncio
import time
from types import SimpleNamespace

import pytest

from gateway.routes import research_chat


class _FakeStreamResponse:
    def __init__(self, status_code: int, chunks: list[str]):
        self.status_code = status_code
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_text(self):
        for chunk in self._chunks:
            yield chunk


class _FakeClient:
    def __init__(self, response: _FakeStreamResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, *args, **kwargs):
        return self._response


class _FakeRequest:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload


@pytest.fixture(autouse=True)
async def _reset_jobs():
    async with research_chat._background_jobs_lock:
        research_chat._background_jobs.clear()
    yield
    async with research_chat._background_jobs_lock:
        research_chat._background_jobs.clear()


@pytest.mark.asyncio
async def test_background_job_marks_failed_when_error_event_received(monkeypatch):
    job_id = "job-error-event"
    async with research_chat._background_jobs_lock:
        research_chat._background_jobs[job_id] = {
            "job_id": job_id,
            "user_email": "admin",
            "thread_id": "thread-1",
            "status": "pending",
            "error": None,
            "cancel_requested": False,
            "created_at": time.time(),
            "updated_at": time.time(),
            "next_seq": 0,
            "events": [],
        }

    error_chunk = (
        'event: error\n'
        'data: {"thread_id":"thread-1","error":"Error during graph execution"}\n\n'
    )
    fake_response = _FakeStreamResponse(200, [error_chunk])
    monkeypatch.setattr(
        research_chat,
        "_new_deep_research_client",
        lambda timeout: _FakeClient(fake_response),
    )

    await research_chat._run_background_research_job(job_id, {"thread_id": "thread-1"})

    async with research_chat._background_jobs_lock:
        job = research_chat._background_jobs[job_id]

    assert job["status"] == "failed"
    assert job["error"] == "Error during graph execution"
    assert len(job["events"]) == 1
    assert job["events"][0]["event"] == "error"


@pytest.mark.asyncio
async def test_background_job_marks_completed_without_error_event(monkeypatch):
    job_id = "job-completed"
    async with research_chat._background_jobs_lock:
        research_chat._background_jobs[job_id] = {
            "job_id": job_id,
            "user_email": "admin",
            "thread_id": "thread-2",
            "status": "pending",
            "error": None,
            "cancel_requested": False,
            "created_at": time.time(),
            "updated_at": time.time(),
            "next_seq": 0,
            "events": [],
        }

    message_chunk = (
        'event: message_chunk\n'
        'data: {"thread_id":"thread-2","content":"ok"}\n\n'
    )
    fake_response = _FakeStreamResponse(200, [message_chunk])
    monkeypatch.setattr(
        research_chat,
        "_new_deep_research_client",
        lambda timeout: _FakeClient(fake_response),
    )

    await research_chat._run_background_research_job(job_id, {"thread_id": "thread-2"})

    async with research_chat._background_jobs_lock:
        job = research_chat._background_jobs[job_id]

    assert job["status"] == "completed"
    assert job["error"] is None
    assert len(job["events"]) == 1
    assert job["events"][0]["event"] == "message_chunk"


@pytest.mark.asyncio
async def test_job_events_response_contains_error_field():
    job_id = "job-events"
    async with research_chat._background_jobs_lock:
        research_chat._background_jobs[job_id] = {
            "job_id": job_id,
            "user_email": "admin@example.com",
            "thread_id": "thread-3",
            "status": "failed",
            "error": "Error during graph execution",
            "cancel_requested": False,
            "created_at": time.time(),
            "updated_at": time.time(),
            "next_seq": 0,
            "events": [],
        }

    payload = await research_chat.get_research_job_events(
        job_id=job_id,
        cursor=0,
        wait_ms=0,
        user=SimpleNamespace(email="admin@example.com"),
    )

    assert payload["done"] is True
    assert payload["status"] == "failed"
    assert payload["error"] == "Error during graph execution"


@pytest.mark.asyncio
async def test_create_job_uses_conversation_thread_on_accepted(monkeypatch):
    async def _noop_run(job_id: str, body: dict):
        return None

    async def _noop_resolve():
        return None

    monkeypatch.setattr(research_chat, "_run_background_research_job", _noop_run)
    monkeypatch.setattr(research_chat, "_resolve_llm_override_from_settings", _noop_resolve)

    payload = {
        "messages": [{"role": "user", "content": "start"}],
        "conversation_id": "conv_accepted_thread",
        "thread_id": "stale_thread_from_cache",
        "interrupt_feedback": "accepted",
    }
    resp = await research_chat.create_research_job(
        request=_FakeRequest(payload),
        user=SimpleNamespace(email="admin@example.com"),
    )

    job_id = resp["job_id"]
    async with research_chat._background_jobs_lock:
        job = research_chat._background_jobs[job_id]

    assert resp["thread_id"] == "conv_accepted_thread"
    assert job["thread_id"] == "conv_accepted_thread"
    task = job.get("task")
    if task is not None and not task.done():
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_create_job_keeps_explicit_thread_when_not_accepted(monkeypatch):
    async def _noop_run(job_id: str, body: dict):
        return None

    async def _noop_resolve():
        return None

    monkeypatch.setattr(research_chat, "_run_background_research_job", _noop_run)
    monkeypatch.setattr(research_chat, "_resolve_llm_override_from_settings", _noop_resolve)

    payload = {
        "messages": [{"role": "user", "content": "plan"}],
        "conversation_id": "conv_plan_only",
        "thread_id": "explicit_thread",
        "interrupt_feedback": "edit_plan",
    }
    resp = await research_chat.create_research_job(
        request=_FakeRequest(payload),
        user=SimpleNamespace(email="admin@example.com"),
    )

    job_id = resp["job_id"]
    async with research_chat._background_jobs_lock:
        job = research_chat._background_jobs[job_id]

    assert resp["thread_id"] == "explicit_thread"
    assert job["thread_id"] == "explicit_thread"
    task = job.get("task")
    if task is not None and not task.done():
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_create_job_auto_detects_vllm_model_when_local_model_empty(monkeypatch):
    captured_bodies: list[dict] = []

    async def _capture_run(job_id: str, body: dict):
        captured_bodies.append(body)
        return None

    async def _fake_auto_detect(base_url: str, api_key: str = ""):
        assert base_url == "http://127.0.0.1:8000/v1"
        assert api_key == "token-local"
        return "detected/model-from-vllm"

    monkeypatch.setattr(research_chat, "_run_background_research_job", _capture_run)
    monkeypatch.setattr(
        research_chat.Config,
        "get_global_settings",
        lambda: {
            "local_vllm_enabled": True,
            "local_vllm_base_url": "http://127.0.0.1:8000/v1",
            "local_vllm_api_key": "token-local",
            "local_vllm_model": "",
            "openrouter_api_key": "",
            "openrouter_base_url": "https://openrouter.ai/api/v1",
            "openrouter_model": "unused/model",
        },
    )
    monkeypatch.setattr(research_chat, "_auto_detect_vllm_model", _fake_auto_detect)

    resp = await research_chat.create_research_job(
        request=_FakeRequest(
            {
                "messages": [{"role": "user", "content": "start research"}],
                "conversation_id": "conv_detect_model",
                "interrupt_feedback": "accepted",
            }
        ),
        user=SimpleNamespace(email="admin@example.com"),
    )

    job_id = resp["job_id"]
    async with research_chat._background_jobs_lock:
        task = research_chat._background_jobs[job_id].get("task")
    if task is not None and not task.done():
        await task

    assert len(captured_bodies) == 1
    llm_override = captured_bodies[0].get("llm_override")
    assert llm_override is not None
    assert llm_override.get("base_url") == "http://127.0.0.1:8000/v1"
    assert llm_override.get("api_key") == "token-local"
    assert llm_override.get("model") == "detected/model-from-vllm"
