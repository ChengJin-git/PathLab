"""
Research Chat Route - Proxy to Deep Research Agent (backend/deep-research)

Forwards SSE streams from the deep-research service and converts the event format
to be compatible with the existing PathLab frontend chat UI.

Research jobs and events are persisted to PostgreSQL for resumability.
"""
import json
import os
import time
import asyncio
import sys
from pathlib import Path
from uuid import uuid4
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import StreamingResponse
from backend.auth import current_active_user, User
from backend.common.config import Config
from backend.database import async_session
from backend.database.repositories import ResearchJobRepository
from ..dependencies import logger
from ..models import ChatRequest

router = APIRouter(tags=["Research Chat"])

# Deep Research target:
# - If DEEP_RESEARCH_URL is explicitly set: use external HTTP service (legacy mode)
# - Otherwise: default to in-process integration mode (single backend process)
_DEEP_RESEARCH_URL_ENV = os.environ.get("DEEP_RESEARCH_URL")
DEEP_RESEARCH_URL = _DEEP_RESEARCH_URL_ENV or "http://127.0.0.1:8080"
USE_INPROC_DEEP_RESEARCH = os.environ.get(
    "PATHLAB_INPROC_DEEP_RESEARCH",
    "1" if _DEEP_RESEARCH_URL_ENV is None else "0",
).lower() in ("1", "true", "yes", "on")
INPROC_DEEP_RESEARCH_BASE_URL = "http://deep-research.local"
_DEEP_RESEARCH_APP = None

# In-memory dict only for asyncio.Task references (needed for cancel)
_running_tasks: dict[str, asyncio.Task] = {}
_running_tasks_lock = asyncio.Lock()

# Agent name → user-readable stage mapping
_AGENT_TO_STAGE = {
    "coordinator": "coordinating",
    "planner": "planning",
    "researcher": "researching",
    "coder": "coding",
    "reporter": "writing_report",
}


class _EventBuffer:
    """Batch buffer for writing research job events to DB efficiently.

    Events are buffered in memory and flushed to DB either when the buffer
    reaches `max_size` or when `max_wait` seconds have elapsed since last flush.
    """

    def __init__(self, job_id: str, max_size: int = 50, max_wait: float = 0.5):
        self.job_id = job_id
        self.max_size = max_size
        self.max_wait = max_wait
        self._buffer: list[dict] = []
        self._seq: int = 0
        self._last_flush: float = time.time()
        self._current_stage: Optional[str] = None

    async def init_seq(self):
        """Load next_seq from DB so we continue from the right offset."""
        async with async_session() as db:
            job = await ResearchJobRepository.get_job(db, self.job_id)
            if job:
                self._seq = job.next_seq

    async def append(self, event_type: str, data):
        """Add an event to the buffer, auto-flushing when thresholds are met."""
        seq = self._seq
        self._seq += 1
        self._buffer.append({
            "seq": seq,
            "event_type": event_type,
            "data": data,
        })

        # Track stage from event data
        if isinstance(data, dict):
            agent = data.get("agent")
            if agent and agent in _AGENT_TO_STAGE:
                new_stage = _AGENT_TO_STAGE[agent]
                if new_stage != self._current_stage:
                    self._current_stage = new_stage

        now = time.time()
        if len(self._buffer) >= self.max_size or (now - self._last_flush) >= self.max_wait:
            await self.flush()

    async def flush(self):
        """Write buffered events to DB and update job metadata."""
        if not self._buffer:
            return
        batch = self._buffer[:]
        self._buffer.clear()
        self._last_flush = time.time()

        try:
            async with async_session() as db:
                await ResearchJobRepository.append_events_batch(db, self.job_id, batch)
                # Update next_seq to our current counter
                from sqlalchemy import update as sa_update
                from backend.database.models import ResearchJob, utc_now
                values = {"next_seq": self._seq, "updated_at": utc_now()}
                if self._current_stage:
                    values["current_stage"] = self._current_stage
                await db.execute(
                    sa_update(ResearchJob)
                    .where(ResearchJob.job_id == self.job_id)
                    .values(**values)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"[ResearchChat] Failed to flush events for job {self.job_id}: {e}")


async def _stream_inproc_sse(app, path: str, body: dict):
    """
    Stream SSE from an in-process ASGI app without buffering.

    Unlike httpx.ASGITransport (which waits for the entire response to complete
    before yielding any bytes), this helper uses an asyncio.Queue to forward
    each ``http.response.body`` chunk as soon as the ASGI app produces it.
    """
    body_bytes = json.dumps(body).encode("utf-8")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body_bytes)).encode()),
        ],
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "server": ("deep-research.local", 80),
        "client": ("127.0.0.1", 123),
        "root_path": "",
    }

    request_complete = False
    disconnect_event = asyncio.Event()
    body_queue: asyncio.Queue = asyncio.Queue()

    async def receive():
        nonlocal request_complete
        if not request_complete:
            request_complete = True
            return {"type": "http.request", "body": body_bytes, "more_body": False}
        # Block until the consumer signals disconnect (e.g. client gone)
        await disconnect_event.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            chunk = message.get("body", b"")
            if chunk:
                await body_queue.put(chunk)
            if not message.get("more_body", False):
                await body_queue.put(None)  # sentinel: response complete

    async def run_app():
        try:
            await app(scope, receive, send)
        except Exception as exc:
            logger.warning(f"[ResearchChat] In-proc ASGI app error: {exc}")
        finally:
            # Ensure the consumer always terminates
            await body_queue.put(None)

    task = asyncio.create_task(run_app())
    try:
        while True:
            chunk = await body_queue.get()
            if chunk is None:
                break
            yield chunk
    finally:
        disconnect_event.set()
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def _ensure_inproc_deep_research_env() -> None:
    """
    Provide sane defaults for deep-research checkpoint persistence when running
    in-process. Explicit env vars always take precedence.
    """
    if os.environ.get("LANGGRAPH_CHECKPOINT_DB_URL"):
        return
    db_url = os.environ.get("DATABASE_URL") or Config.DATABASE_URL_DEFAULT
    os.environ["LANGGRAPH_CHECKPOINT_DB_URL"] = db_url.replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    os.environ.setdefault("LANGGRAPH_CHECKPOINT_SAVER", "true")


def _get_inproc_deep_research_app():
    global _DEEP_RESEARCH_APP
    if _DEEP_RESEARCH_APP is not None:
        return _DEEP_RESEARCH_APP
    _ensure_inproc_deep_research_env()
    deep_research_root = (
        Path(__file__).resolve().parents[2] / "backend" / "deep-research"
    )
    if str(deep_research_root) not in sys.path:
        sys.path.insert(0, str(deep_research_root))
    from src.server import app as deep_research_app  # type: ignore

    _DEEP_RESEARCH_APP = deep_research_app
    logger.info("[ResearchChat] In-process deep-research app initialized")
    return _DEEP_RESEARCH_APP


def _deep_research_api_url(path: str) -> str:
    path = path.lstrip("/")
    if USE_INPROC_DEEP_RESEARCH:
        return f"/api/{path}"
    return f"{DEEP_RESEARCH_URL}/api/{path}"


def _deep_research_target_label() -> str:
    if USE_INPROC_DEEP_RESEARCH:
        return "inproc:/api"
    return DEEP_RESEARCH_URL


def _new_deep_research_client(timeout: httpx.Timeout | float):
    if USE_INPROC_DEEP_RESEARCH:
        transport = httpx.ASGITransport(app=_get_inproc_deep_research_app())
        return httpx.AsyncClient(
            transport=transport,
            base_url=INPROC_DEEP_RESEARCH_BASE_URL,
            timeout=timeout,
        )
    return httpx.AsyncClient(timeout=timeout)


def _job_is_done(status: str) -> bool:
    return status in {"completed", "failed", "cancelled", "interrupted"}


def _normalize_thread_id(body: dict) -> str:
    """
    Resolve the effective deep-research thread ID.

    - Default behavior: keep explicit ``thread_id``; otherwise fallback to
      ``conversation_id`` then ``__default__``.
    - Resume behavior (interrupt accepted): force ``conversation_id`` when
      available so old/stale client-side thread cache does not break resume.
    """
    conversation_id = body.get("conversation_id")
    thread_id = body.get("thread_id")
    if isinstance(thread_id, str):
        thread_id = thread_id.strip()

    if not thread_id or thread_id == "__default__":
        thread_id = conversation_id or "__default__"

    if body.get("interrupt_feedback") == "accepted" and conversation_id:
        thread_id = conversation_id

    body["thread_id"] = thread_id
    return thread_id


def _parse_sse_block(event_block: str) -> tuple[str, Optional[str]]:
    event_type = "message"
    event_data = None
    for line in event_block.split("\n"):
        if line.startswith("event: "):
            event_type = line[7:]
        elif line.startswith("data: "):
            event_data = line[6:]
    return event_type, event_data


def _make_research_error_event(error_msg: str) -> str:
    """Build an SSE error event with a user-friendly message."""
    return f'event: error\ndata: {json.dumps({"error": error_msg}, ensure_ascii=False)}\n\n'


_LLM_NOT_CONFIGURED_MSG = """**AI Configuration Required**

To use Deep Research, please configure your AI model service:

1. Click **Settings** in the left sidebar
2. Choose one of the following:
   - Enter your **OpenRouter API Key** and select a model
   - OR enable **Local vLLM Server** and configure the server URL
3. Click **Save Settings**

**Get your API key:** [OpenRouter Console](https://openrouter.ai/keys)

After saving, return here and start researching!"""


def _has_deep_research_llm_config() -> bool:
    """Check whether the deep-research backend has its own LLM configuration
    (conf.yaml or environment variables) so it can function without an override."""
    # Check common environment variable patterns for deep-research LLM config
    for prefix in ("BASIC_MODEL__", "REASONING_MODEL__"):
        if any(k.startswith(prefix) for k in os.environ):
            return True
    # Check if conf.yaml exists and has model configuration
    try:
        conf_path = (
            Path(__file__).resolve().parents[2]
            / "backend" / "deep-research" / "conf.yaml"
        )
        if conf_path.exists():
            import yaml
            with open(conf_path) as f:
                conf = yaml.safe_load(f)
            if isinstance(conf, dict) and (
                conf.get("BASIC_MODEL", {}).get("model")
                or conf.get("REASONING_MODEL", {}).get("model")
            ):
                return True
    except Exception:
        pass
    return False


def _has_llm_settings_configured() -> bool:
    """Check whether the user has configured any LLM in the frontend settings,
    even if llm_override resolution failed (e.g. model auto-detect timeout)."""
    try:
        settings = Config.get_global_settings()
        if settings.get("local_vllm_enabled") and settings.get("local_vllm_base_url"):
            return True
        if settings.get("openrouter_api_key"):
            return True
    except Exception:
        pass
    return False


def _apply_search_settings_overrides_from_settings() -> str:
    """
    Keep process-level search provider and API keys aligned with global settings
    so in-process deep-research requests use the configured provider.

    Returns the resolved provider for downstream request-body injection.
    """
    try:
        settings = Config.get_global_settings()
        provider = Config.resolve_search_provider(settings)
        exa_configured = (settings.get("exa_api_key") or "").strip()
        tavily_configured = (settings.get("tavily_api_key") or "").strip()
    except Exception as e:
        logger.warning(f"[ResearchChat] Failed to read search settings: {e}")
        return "exa"

    if os.environ.get("SEARCH_API") != provider:
        os.environ["SEARCH_API"] = provider
        logger.info(f"[ResearchChat] Using search provider override from settings: {provider}")

    key_overrides = {
        "EXA_API_KEY": exa_configured,
        "TAVILY_API_KEY": tavily_configured,
    }
    for env_key, configured in key_overrides.items():
        current = os.environ.get(env_key)
        if configured:
            if current != configured:
                os.environ[env_key] = configured
                logger.info(f"[ResearchChat] Using {env_key} override from settings")
        elif current:
            os.environ.pop(env_key, None)
            logger.info(f"[ResearchChat] Cleared {env_key} override")

    return provider


async def _resolve_llm_override_from_settings() -> Optional[dict]:
    llm_override: Optional[dict] = None
    try:
        settings = Config.get_global_settings()
        local_vllm_enabled = settings.get("local_vllm_enabled", False)

        if local_vllm_enabled and settings.get("local_vllm_base_url"):
            vllm_base_url = settings.get("local_vllm_base_url", "")
            vllm_api_key = settings.get("local_vllm_api_key", "")
            vllm_model = settings.get("local_vllm_model", "")
            if not vllm_model:
                vllm_model = await _auto_detect_vllm_model(vllm_base_url, vllm_api_key)
            if vllm_model:
                llm_override = {"base_url": vllm_base_url, "model": vllm_model, "api_key": vllm_api_key}
                logger.info(f"[ResearchChat] Using local vLLM: {vllm_base_url}, model={vllm_model}")
            else:
                logger.warning("[ResearchChat] Local vLLM enabled but no model specified and auto-detect failed")
        elif settings.get("openrouter_api_key"):
            llm_override = {
                "base_url": settings.get("openrouter_base_url", "https://openrouter.ai/api/v1"),
                "model": settings.get("openrouter_model", ""),
                "api_key": settings.get("openrouter_api_key", ""),
            }
            logger.info(f"[ResearchChat] Using OpenRouter: model={llm_override.get('model')}")
        else:
            logger.info("[ResearchChat] No LLM override from settings, using deep-research defaults (conf.yaml)")
    except Exception as e:
        logger.warning(f"[ResearchChat] Failed to read global settings: {e}")
    return llm_override


async def _run_background_research_job(job_id: str, deep_research_body: dict):
    """Execute a deep research job, buffering SSE events to DB."""
    # Update status to running
    async with async_session() as db:
        await ResearchJobRepository.update_status(db, job_id, "running")
        await db.commit()

    event_buf = _EventBuffer(job_id)
    await event_buf.init_seq()
    saw_error_event = False
    last_error: str | None = None

    async def _process_sse_bytes(byte_iter):
        """Parse SSE from an async byte iterator and store events."""
        nonlocal saw_error_event, last_error
        buffer = ""
        async for raw_chunk in byte_iter:
            buffer += raw_chunk.decode("utf-8") if isinstance(raw_chunk, bytes) else raw_chunk
            while "\n\n" in buffer:
                event_block, buffer = buffer.split("\n\n", 1)
                event_block = event_block.strip()
                if not event_block:
                    continue
                event_type, event_data = _parse_sse_block(event_block)
                if not event_data:
                    continue
                try:
                    parsed_data = json.loads(event_data)
                except json.JSONDecodeError:
                    parsed_data = {"raw": event_data}
                if event_type == "error":
                    saw_error_event = True
                    if isinstance(parsed_data, dict):
                        err = parsed_data.get("error")
                        if isinstance(err, str) and err.strip():
                            last_error = err.strip()
                    elif isinstance(parsed_data, str) and parsed_data.strip():
                        last_error = parsed_data.strip()
                await event_buf.append(event_type, parsed_data)

    try:
        if USE_INPROC_DEEP_RESEARCH:
            app = _get_inproc_deep_research_app()
            await _process_sse_bytes(
                _stream_inproc_sse(app, _deep_research_api_url("chat/stream"), deep_research_body)
            )
        else:
            async with _new_deep_research_client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
                async with client.stream(
                    "POST",
                    _deep_research_api_url("chat/stream"),
                    json=deep_research_body,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status_code != 200:
                        error_text = ""
                        async for chunk in response.aiter_text():
                            error_text += chunk
                        err = f"HTTP {response.status_code}: {error_text[:300]}"
                        await event_buf.append("error", {"error": err})
                        await event_buf.flush()
                        async with async_session() as db:
                            await ResearchJobRepository.update_status(db, job_id, "failed", error=err)
                            await db.commit()
                        return
                    await _process_sse_bytes(response.aiter_bytes())

        # Final flush
        await event_buf.flush()

        # Determine final status
        async with async_session() as db:
            job = await ResearchJobRepository.get_job(db, job_id)
            cancel_requested = bool(job and job.cancel_requested)
            if cancel_requested:
                await ResearchJobRepository.update_status(db, job_id, "cancelled")
            elif saw_error_event:
                await ResearchJobRepository.update_status(
                    db, job_id, "failed",
                    error=last_error or "Deep research stream returned an error event",
                )
            else:
                await ResearchJobRepository.update_status(db, job_id, "completed")
            await db.commit()
    except asyncio.CancelledError:
        await event_buf.flush()
        async with async_session() as db:
            await ResearchJobRepository.update_status(db, job_id, "cancelled")
            await db.commit()
        raise
    except Exception as e:
        logger.exception(f"[ResearchChat] Background job failed: {job_id}")
        await event_buf.append("error", {"error": str(e)})
        await event_buf.flush()
        async with async_session() as db:
            await ResearchJobRepository.update_status(db, job_id, "failed", error=str(e))
            await db.commit()
    finally:
        # Remove task reference
        async with _running_tasks_lock:
            _running_tasks.pop(job_id, None)


async def _auto_detect_vllm_model(base_url: str, api_key: str = "") -> str | None:
    """Auto-detect the model name from a vLLM/OpenAI-compatible server via GET /models."""
    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{base_url}/models", headers=headers)
            if response.status_code == 200:
                data = response.json()
                if "data" in data and len(data["data"]) > 0:
                    model_name = data["data"][0].get("id")
                    logger.info(f"[ResearchChat] Auto-detected vLLM model: {model_name}")
                    return model_name
    except Exception as e:
        logger.warning(f"[ResearchChat] Failed to auto-detect vLLM model: {e}")
    return None


@router.post("/agent/research/chat/stream")
async def research_chat_stream_raw(
    request: Request,
    user: User = Depends(current_active_user),
):
    """
    Raw SSE proxy to deep-research /api/chat/stream.
    Passes through all SSE events without format conversion.
    Used by the dedicated Deep Research page which handles its own event parsing.
    """

    search_provider = _apply_search_settings_overrides_from_settings()
    llm_override = await _resolve_llm_override_from_settings()

    # Build request body - pass through all fields from the request.
    # Use raw JSON parsing to avoid 422 validation failures when frontend
    # adds new optional fields that gateway model does not yet include.
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    # Backward compatibility: allow both `message` and `messages`.
    if "messages" not in body and "message" in body:
        body["messages"] = [{"role": "user", "content": body.get("message", "")}]

    if "messages" not in body:
        raise HTTPException(status_code=400, detail="Missing required field: messages")

    _normalize_thread_id(body)
    if llm_override:
        body["llm_override"] = llm_override
    body["search_provider"] = search_provider

    # Early check: ensure an LLM is configured (like the normal AI chat page does).
    if not llm_override and not _has_deep_research_llm_config() and not _has_llm_settings_configured():
        async def _no_llm_configured():
            yield _make_research_error_event(_LLM_NOT_CONFIGURED_MSG)
        return StreamingResponse(
            _no_llm_configured(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    logger.info(f"[ResearchChat/Raw] User {user.email} → {_deep_research_target_label()}/api/chat/stream")

    async def raw_proxy():
        try:
            if USE_INPROC_DEEP_RESEARCH:
                # Stream directly from the in-process ASGI app using an
                # asyncio.Queue so that SSE chunks are forwarded immediately
                # instead of being buffered by httpx.ASGITransport.
                app = _get_inproc_deep_research_app()
                async for chunk in _stream_inproc_sse(app, _deep_research_api_url("chat/stream"), body):
                    yield chunk
            else:
                async with _new_deep_research_client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
                    async with client.stream(
                        "POST",
                        _deep_research_api_url("chat/stream"),
                        json=body,
                        headers={"Content-Type": "application/json"},
                    ) as response:
                        if response.status_code != 200:
                            error_text = ""
                            async for chunk in response.aiter_text():
                                error_text += chunk
                            yield _make_research_error_event(
                                f"Deep research service returned HTTP {response.status_code}.\n\n"
                                f"{error_text[:200]}\n\nPlease try again."
                            )
                            return
                        async for chunk in response.aiter_bytes():
                            yield chunk
        except httpx.ConnectError:
            yield _make_research_error_event(
                "Cannot connect to deep research service. "
                "Please check that the service is running and try again."
            )
        except httpx.ReadTimeout:
            yield _make_research_error_event(
                "Deep research service timed out. "
                "The request may be too complex or the service is under heavy load. Please try again."
            )
        except Exception as e:
            yield _make_research_error_event(
                f"An unexpected error occurred: {e}\n\n"
                "Please try again. If the problem persists, check the service logs."
            )

    return StreamingResponse(
        raw_proxy(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/agent/research/jobs")
async def create_research_job(
    request: Request,
    user: User = Depends(current_active_user),
):
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    if "messages" not in body and "message" in body:
        body["messages"] = [{"role": "user", "content": body.get("message", "")}]
    if "messages" not in body:
        raise HTTPException(status_code=400, detail="Missing required field: messages")

    _normalize_thread_id(body)

    search_provider = _apply_search_settings_overrides_from_settings()
    llm_override = await _resolve_llm_override_from_settings()
    if llm_override:
        body["llm_override"] = llm_override
    body["search_provider"] = search_provider

    job_id = str(uuid4())

    # Persist job to DB
    async with async_session() as db:
        await ResearchJobRepository.create_job(db, {
            "job_id": job_id,
            "user_email": user.email,
            "conversation_id": body.get("conversation_id"),
            "thread_id": body.get("thread_id"),
            "status": "pending",
            "request_body": body,
        })
        await db.commit()

    task = asyncio.create_task(_run_background_research_job(job_id, body))
    async with _running_tasks_lock:
        _running_tasks[job_id] = task

    return {"job_id": job_id, "thread_id": body.get("thread_id"), "status": "running"}


@router.get("/agent/research/jobs/{job_id}")
async def get_research_job(
    job_id: str,
    user: User = Depends(current_active_user),
):
    async with async_session() as db:
        job = await ResearchJobRepository.get_job(db, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.user_email != user.email:
            raise HTTPException(status_code=403, detail="Forbidden")
        return {
            "job_id": job.job_id,
            "thread_id": job.thread_id,
            "status": job.status,
            "error": job.error,
            "created_at": job.created_at.isoformat() + 'Z' if job.created_at else None,
            "updated_at": job.updated_at.isoformat() + 'Z' if job.updated_at else None,
            "event_count": job.next_seq,
        }


@router.post("/agent/research/jobs/{job_id}/cancel")
async def cancel_research_job(
    job_id: str,
    user: User = Depends(current_active_user),
):
    async with async_session() as db:
        job = await ResearchJobRepository.get_job(db, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.user_email != user.email:
            raise HTTPException(status_code=403, detail="Forbidden")

        status = job.status
        if _job_is_done(status):
            return {
                "job_id": job_id,
                "status": status,
                "cancelled": status == "cancelled",
            }
        thread_id = job.thread_id
        await ResearchJobRepository.set_cancel_requested(db, job_id)
        await db.commit()

    # Try graceful stop via deep-research
    async with _running_tasks_lock:
        task = _running_tasks.get(job_id)

    stop_ok = False
    if thread_id:
        try:
            async with _new_deep_research_client(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
                resp = await client.post(
                    _deep_research_api_url("chat/stop"),
                    json={"thread_id": thread_id, "reason": "Stopped by user"},
                    headers={"Content-Type": "application/json"},
                )
                stop_ok = resp.status_code == 200
        except Exception as e:
            logger.warning(f"[ResearchChat] Graceful stop request failed for job {job_id}: {e}")

    if not stop_ok:
        # Hard-cancel fallback
        if task is not None and not task.done():
            task.cancel()
        async with async_session() as db:
            await ResearchJobRepository.update_status(db, job_id, "cancelled")
            await db.commit()
        return {"job_id": job_id, "status": "cancelled", "cancelled": True, "mode": "hard"}

    return {"job_id": job_id, "status": "cancelling", "cancelled": False, "mode": "graceful"}


@router.get("/agent/research/jobs/{job_id}/events")
async def get_research_job_events(
    job_id: str,
    cursor: int = Query(0, ge=0),
    wait_ms: int = Query(15000, ge=0, le=30000),
    user: User = Depends(current_active_user),
):
    deadline = time.time() + (wait_ms / 1000.0)
    while True:
        async with async_session() as db:
            job = await ResearchJobRepository.get_job(db, job_id)
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")
            if job.user_email != user.email:
                raise HTTPException(status_code=403, detail="Forbidden")

            status = job.status
            events = await ResearchJobRepository.get_events_after(db, job_id, cursor - 1 if cursor > 0 else -1, limit=500)

            if events:
                event_list = [
                    {
                        "seq": e.seq,
                        "event": e.event_type,
                        "data": e.data,
                        "ts": e.created_at.timestamp() if e.created_at else time.time(),
                    }
                    for e in events
                ]
                # Filter to events with seq >= cursor
                event_list = [e for e in event_list if e["seq"] >= cursor]
                if event_list:
                    next_cursor = max(e["seq"] for e in event_list) + 1
                    return {
                        "job_id": job_id,
                        "events": event_list,
                        "next_cursor": next_cursor,
                        "status": status,
                        "error": job.error,
                        "done": _job_is_done(status),
                    }

            if _job_is_done(status):
                return {
                    "job_id": job_id,
                    "events": [],
                    "next_cursor": cursor,
                    "status": status,
                    "error": job.error,
                    "done": True,
                }

        if time.time() >= deadline:
            return {
                "job_id": job_id,
                "events": [],
                "next_cursor": cursor,
                "status": "running",
                "error": None,
                "done": False,
            }
        await asyncio.sleep(0.25)


@router.get("/agent/research/jobs")
async def list_research_jobs(
    status: str = Query("running,pending", description="Comma-separated statuses to filter"),
    user: User = Depends(current_active_user),
):
    """List research jobs for the current user, filtered by status."""
    statuses = [s.strip() for s in status.split(",") if s.strip()]
    async with async_session() as db:
        if set(statuses) == {"running", "pending"} or set(statuses) == {"pending", "running"}:
            jobs = await ResearchJobRepository.get_active_jobs_for_user(db, user.email)
        else:
            # Fallback: query with specific statuses
            from sqlalchemy import select
            from backend.database.models import ResearchJob
            result = await db.execute(
                select(ResearchJob)
                .where(
                    ResearchJob.user_email == user.email,
                    ResearchJob.status.in_(statuses),
                )
                .order_by(ResearchJob.created_at.desc())
            )
            jobs = result.scalars().all()
        return {
            "jobs": [
                {
                    "job_id": j.job_id,
                    "conversation_id": j.conversation_id,
                    "status": j.status,
                    "current_stage": j.current_stage,
                    "created_at": j.created_at.isoformat() + 'Z' if j.created_at else None,
                }
                for j in jobs
            ]
        }


@router.get("/agent/research/conversations/{conversation_id}/job")
async def get_research_job_by_conversation(
    conversation_id: str,
    user: User = Depends(current_active_user),
):
    """Get the latest research job for a conversation."""
    async with async_session() as db:
        job = await ResearchJobRepository.get_job_by_conversation(db, conversation_id)
        if not job:
            raise HTTPException(status_code=404, detail="No job found for this conversation")
        if job.user_email != user.email:
            raise HTTPException(status_code=403, detail="Forbidden")
        return job.to_dict()


@router.post("/agent/research/chat/stop")
async def research_chat_stop(
    request: Request,
    user: User = Depends(current_active_user),
):
    """
    Proxy stop request to deep-research /api/chat/stop.

    Called by the frontend to cancel an in-progress research run by thread_id.
    The deep-research server sets stop_requested=True on the LangGraph state
    so the current run terminates gracefully after the current step.
    """
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}")

    thread_id = body.get("thread_id", "")
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is required")

    logger.info(f"[ResearchChat] Stop request for thread_id={thread_id} from {user.email}")

    try:
        async with _new_deep_research_client(timeout=10.0) as client:
            resp = await client.post(
                _deep_research_api_url("chat/stop"),
                json=body,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"[ResearchChat] Deep research stop returned {resp.status_code}")
            return {"thread_id": thread_id, "stop_requested": True, "checkpoint_updated": False}
    except httpx.ConnectError:
        logger.error(f"[ResearchChat] Cannot connect to deep-research for stop: {_deep_research_target_label()}")
        return {"thread_id": thread_id, "stop_requested": True, "checkpoint_updated": False}
    except Exception as e:
        logger.error(f"[ResearchChat] Unexpected error stopping research: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agent/research/health")
async def research_health():
    """Health check - verify deep-research service is reachable."""
    try:
        async with _new_deep_research_client(timeout=5.0) as client:
            resp = await client.get(_deep_research_api_url("config"))
            if resp.status_code == 200:
                return {
                    "status": "ok",
                    "deep_research_url": DEEP_RESEARCH_URL,
                    "mode": "inproc" if USE_INPROC_DEEP_RESEARCH else "external",
                }
            return {"status": "error", "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@router.get("/agent/research/config")
async def research_config(
    user: User = Depends(current_active_user),
):
    """Proxy deep-research runtime config for frontend hooks with safe fallback."""
    fallback = {
        "rag": {"provider": ""},
        "models": {"basic": [], "reasoning": []},
    }
    try:
        async with _new_deep_research_client(timeout=10.0) as client:
            resp = await client.get(_deep_research_api_url("config"))
            if resp.status_code == 200:
                return resp.json()
            logger.warning(
                f"[ResearchChat] Config proxy returned HTTP {resp.status_code} for {user.email}, using fallback"
            )
            return fallback
    except Exception as e:
        logger.warning(f"[ResearchChat] Config proxy failed for {user.email}: {e}; using fallback")
        return fallback


@router.post("/agent/research/stream")
async def research_chat_stream(
    req: ChatRequest,
    request: Request,
    user: User = Depends(current_active_user),
):
    """
    Proxy chat to deep-research agent, converting SSE format for PathLab frontend.

    - Receives ChatRequest (messages + conversation_id)
    - Forwards to deep-research /api/chat/stream
    - Converts deep-research SSE events to PathLab frontend format:
      message_chunk events → data: {"content": "..."}\n\n
    """

    search_provider = _apply_search_settings_overrides_from_settings()
    llm_override = await _resolve_llm_override_from_settings()

    # Build deep-research request body
    deep_research_body = {
        "messages": req.messages,
        "thread_id": req.conversation_id or "__default__",
        "locale": req.locale or "zh-CN",
        "voice_session_active": bool(req.voice_session_active),
        # Default settings for normal chat (no deep research)
        "auto_accepted_plan": True,
        "enable_background_investigation": False,
        "enable_deep_thinking": False,
        "enable_clarification": False,
        "enable_web_search": True,
        "search_provider": search_provider,
        "max_plan_iterations": 1,
        "max_step_num": 3,
        "max_search_results": 3,
        "report_style": "academic",
    }

    # Inject LLM override if available from PathLab settings
    if llm_override:
        deep_research_body["llm_override"] = llm_override

    logger.info(
        f"[ResearchChat] User {user.email} - proxying to {_deep_research_target_label()}/api/chat/stream "
        f"(thread_id={deep_research_body['thread_id']})"
    )

    async def event_generator():
        """Stream SSE events from deep-research, converting to PathLab format."""
        # State for stripping JSON wrapper from direct_response tool args
        # The args stream looks like: {"message": "实际内容...", "locale": "zh-CN"}
        # We need to strip the JSON structure and only forward the message content.
        in_tool_args = False  # Whether we're inside a direct_response tool call
        tool_args_started = False  # Whether we've seen and stripped the opening prefix

        def _extract_content_from_args(args_text: str) -> str:
            """Strip JSON wrapper from tool call args, keeping only message content.

            Args stream looks like: {"message": "actual content here"}
            We strip the JSON structure and only forward the message text.
            """
            nonlocal in_tool_args, tool_args_started

            if not args_text:
                return ""

            # First chunk: strip the opening JSON prefix {"message": "
            if not tool_args_started:
                prefix_patterns = ['{"message": "', '{"message":"']
                for prefix in prefix_patterns:
                    if args_text.startswith(prefix):
                        tool_args_started = True
                        return args_text[len(prefix):]
                # No prefix found — pass through
                tool_args_started = True
                return args_text

            # Check if this chunk contains the closing JSON: "} or ", "key":
            # Handle both: end of message only, or message + extra fields
            for closing in ['"}', '", "']:
                idx = args_text.find(closing)
                if idx != -1:
                    in_tool_args = False
                    tool_args_started = False
                    return args_text[:idx]

            # Middle chunk: pass through as-is
            return args_text

        async def _parse_and_convert_sse(byte_iter):
            """Parse SSE bytes and yield converted PathLab-format events."""
            nonlocal in_tool_args, tool_args_started
            buffer = ""
            async for raw_chunk in byte_iter:
                buffer += raw_chunk.decode("utf-8") if isinstance(raw_chunk, bytes) else raw_chunk

                while "\n\n" in buffer:
                    event_block, buffer = buffer.split("\n\n", 1)
                    event_block = event_block.strip()
                    if not event_block:
                        continue

                    event_type = "message"
                    event_data = None
                    for line in event_block.split("\n"):
                        if line.startswith("event: "):
                            event_type = line[7:]
                        elif line.startswith("data: "):
                            event_data = line[6:]

                    if not event_data:
                        continue

                    try:
                        parsed = json.loads(event_data)
                    except json.JSONDecodeError:
                        continue

                    if event_type == "message_chunk":
                        content = parsed.get("content", "")
                        if content:
                            stripped = content.strip().replace("&#125;", "}").replace("&#123;", "{")
                            if stripped in ('"}', '{', '}', '"'):
                                continue
                            if content.endswith('"}') or content.endswith('"\\}'):
                                content = content[:-2]
                            elif content.endswith('&#125;'):
                                content = content[:-6]
                            if content:
                                yield f'data: {json.dumps({"content": content})}\n\n'

                    elif event_type == "tool_calls":
                        tool_calls = parsed.get("tool_calls", [])
                        for tc in tool_calls:
                            if tc.get("name") == "direct_response":
                                in_tool_args = True
                                tool_args_started = False

                    elif event_type == "tool_call_chunks":
                        chunks = parsed.get("tool_call_chunks", [])
                        for chunk in chunks:
                            args_text = chunk.get("args", "")
                            if args_text and in_tool_args:
                                content = _extract_content_from_args(args_text)
                                if content:
                                    yield f'data: {json.dumps({"content": content})}\n\n'

                    elif event_type == "error":
                        error_msg = parsed.get("error", "Unknown error")
                        error_content = f"\n\n[Error: {error_msg}]"
                        yield f'data: {json.dumps({"content": error_content})}\n\n'

            # Process remaining buffer
            if buffer.strip():
                for event_block in buffer.strip().split("\n\n"):
                    event_type = "message"
                    event_data = None
                    for line in event_block.strip().split("\n"):
                        if line.startswith("event: "):
                            event_type = line[7:]
                        elif line.startswith("data: "):
                            event_data = line[6:]
                    if event_data:
                        try:
                            parsed = json.loads(event_data)
                            if event_type == "message_chunk":
                                content = parsed.get("content", "")
                                if content:
                                    yield f'data: {json.dumps({"content": content})}\n\n'
                        except json.JSONDecodeError:
                            pass

        try:
            if USE_INPROC_DEEP_RESEARCH:
                app = _get_inproc_deep_research_app()
                async for evt in _parse_and_convert_sse(
                    _stream_inproc_sse(app, _deep_research_api_url("chat/stream"), deep_research_body)
                ):
                    yield evt
            else:
                async with _new_deep_research_client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
                    async with client.stream(
                        "POST",
                        _deep_research_api_url("chat/stream"),
                        json=deep_research_body,
                        headers={"Content-Type": "application/json"},
                    ) as response:
                        if response.status_code != 200:
                            error_text = ""
                            async for chunk in response.aiter_text():
                                error_text += chunk
                            logger.error(f"[ResearchChat] Deep research returned {response.status_code}: {error_text[:500]}")
                            yield f'data: {{"error": "Deep research service error: {response.status_code}"}}\n\n'
                            yield "data: [DONE]\n\n"
                            return
                        async for evt in _parse_and_convert_sse(response.aiter_bytes()):
                            yield evt

        except httpx.ConnectError:
            logger.error(f"[ResearchChat] Cannot connect to deep-research at {_deep_research_target_label()}")
            yield f'data: {json.dumps({"content": "❌ Cannot connect to deep research service. Please check that the service is running and try again."})}\n\n'
        except httpx.ReadTimeout:
            logger.error("[ResearchChat] Timeout reading from deep-research")
            yield f'data: {json.dumps({"content": "❌ Deep research service timed out. Please try again."})}\n\n'
        except Exception as e:
            logger.error(f"[ResearchChat] Unexpected error: {e}")
            err_content = f"❌ Error: {e}\n\nPlease try again. If the problem persists, check the service logs."
            yield f'data: {json.dumps({"content": err_content})}\n\n'
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
