"""
Research Chat Route - Proxy to Deep Research Agent (agentv2/deep-research)

Forwards SSE streams from the deep-research service and converts the event format
to be compatible with the existing PathLab frontend chat UI.
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

BACKGROUND_JOB_TTL_SECONDS = 60 * 60 * 6
BACKGROUND_JOB_MAX_EVENTS = 4000

_background_jobs_lock = asyncio.Lock()
_background_jobs: dict[str, dict] = {}


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
        Path(__file__).resolve().parents[2] / "backend" / "agentv2" / "deep-research"
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
    return status in {"completed", "failed", "cancelled"}


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


async def _cleanup_expired_jobs() -> None:
    now = time.time()
    async with _background_jobs_lock:
        expired_ids = []
        for job_id, job in _background_jobs.items():
            if now - job.get("updated_at", now) > BACKGROUND_JOB_TTL_SECONDS:
                task = job.get("task")
                if task is not None and not task.done():
                    task.cancel()
                expired_ids.append(job_id)
        for job_id in expired_ids:
            _background_jobs.pop(job_id, None)


async def _append_job_event(job_id: str, event_type: str, data):
    async with _background_jobs_lock:
        job = _background_jobs.get(job_id)
        if not job:
            return
        seq = job["next_seq"]
        job["next_seq"] = seq + 1
        job["events"].append(
            {
                "seq": seq,
                "event": event_type,
                "data": data,
                "ts": time.time(),
            }
        )
        if len(job["events"]) > BACKGROUND_JOB_MAX_EVENTS:
            overflow = len(job["events"]) - BACKGROUND_JOB_MAX_EVENTS
            job["events"] = job["events"][overflow:]
        job["updated_at"] = time.time()


async def _set_job_status(job_id: str, status: str, error: str | None = None):
    async with _background_jobs_lock:
        job = _background_jobs.get(job_id)
        if not job:
            return
        job["status"] = status
        job["updated_at"] = time.time()
        if error:
            job["error"] = error


def _parse_sse_block(event_block: str) -> tuple[str, Optional[str]]:
    event_type = "message"
    event_data = None
    for line in event_block.split("\n"):
        if line.startswith("event: "):
            event_type = line[7:]
        elif line.startswith("data: "):
            event_data = line[6:]
    return event_type, event_data


def _normalize_tavily_api_url(url: str | None) -> str | None:
    if not isinstance(url, str):
        return None
    cleaned = url.strip().rstrip("/")
    if not cleaned:
        return None
    if not cleaned.startswith(("http://", "https://")):
        return None
    return cleaned


def _apply_tavily_api_url_override_from_settings() -> None:
    """
    Keep process-level Tavily base URL aligned with global settings so
    in-process deep-research requests use the configured endpoint.
    """
    try:
        settings = Config.get_global_settings()
        configured = _normalize_tavily_api_url(settings.get("tavily_api_url"))
    except Exception as e:
        logger.warning(f"[ResearchChat] Failed to read tavily_api_url from settings: {e}")
        return

    env_key = "TAVILY_API_URL"
    current = os.environ.get(env_key)
    if configured:
        if current != configured:
            os.environ[env_key] = configured
            logger.info(f"[ResearchChat] Using Tavily API URL override: {configured}")
    elif current:
        os.environ.pop(env_key, None)
        logger.info("[ResearchChat] Cleared Tavily API URL override")


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
    await _set_job_status(job_id, "running")
    saw_error_event = False
    last_error: str | None = None
    try:
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
                    await _append_job_event(job_id, "error", {"error": err})
                    await _set_job_status(job_id, "failed", err)
                    return

                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
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
                        await _append_job_event(job_id, event_type, parsed_data)
        async with _background_jobs_lock:
            job = _background_jobs.get(job_id)
            cancel_requested = bool(job and job.get("cancel_requested"))
        if cancel_requested:
            await _set_job_status(job_id, "cancelled")
        elif saw_error_event:
            await _set_job_status(
                job_id,
                "failed",
                last_error or "Deep research stream returned an error event",
            )
        else:
            await _set_job_status(job_id, "completed")
    except asyncio.CancelledError:
        await _set_job_status(job_id, "cancelled")
        raise
    except Exception as e:
        logger.exception(f"[ResearchChat] Background job failed: {job_id}")
        await _append_job_event(job_id, "error", {"error": str(e)})
        await _set_job_status(job_id, "failed", str(e))


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

    _apply_tavily_api_url_override_from_settings()
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

    logger.info(f"[ResearchChat/Raw] User {user.email} → {_deep_research_target_label()}/api/chat/stream")

    async def raw_proxy():
        try:
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
                        yield f'event: error\ndata: {json.dumps({"error": f"HTTP {response.status_code}: {error_text[:200]}"})}\n\n'
                        return
                    async for chunk in response.aiter_bytes():
                        yield chunk
        except httpx.ConnectError:
            yield f'event: error\ndata: {json.dumps({"error": "Cannot connect to deep research service"})}\n\n'
        except Exception as e:
            yield f'event: error\ndata: {json.dumps({"error": str(e)})}\n\n'

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
    await _cleanup_expired_jobs()
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

    _apply_tavily_api_url_override_from_settings()
    llm_override = await _resolve_llm_override_from_settings()
    if llm_override:
        body["llm_override"] = llm_override

    job_id = str(uuid4())
    now = time.time()
    async with _background_jobs_lock:
        _background_jobs[job_id] = {
            "job_id": job_id,
            "user_email": user.email,
            "thread_id": body.get("thread_id"),
            "status": "pending",
            "error": None,
            "cancel_requested": False,
            "created_at": now,
            "updated_at": now,
            "next_seq": 0,
            "events": [],
        }

    task = asyncio.create_task(_run_background_research_job(job_id, body))
    async with _background_jobs_lock:
        job = _background_jobs.get(job_id)
        if job is not None:
            job["task"] = task
    return {"job_id": job_id, "thread_id": body.get("thread_id"), "status": "running"}


@router.get("/agent/research/jobs/{job_id}")
async def get_research_job(
    job_id: str,
    user: User = Depends(current_active_user),
):
    await _cleanup_expired_jobs()
    async with _background_jobs_lock:
        job = _background_jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.get("user_email") != user.email:
            raise HTTPException(status_code=403, detail="Forbidden")
        return {
            "job_id": job["job_id"],
            "thread_id": job.get("thread_id"),
            "status": job.get("status"),
            "error": job.get("error"),
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
            "event_count": len(job.get("events", [])),
        }


@router.post("/agent/research/jobs/{job_id}/cancel")
async def cancel_research_job(
    job_id: str,
    user: User = Depends(current_active_user),
):
    await _cleanup_expired_jobs()
    job = None
    task = None
    thread_id = None
    async with _background_jobs_lock:
        job = _background_jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.get("user_email") != user.email:
            raise HTTPException(status_code=403, detail="Forbidden")

        status = job.get("status", "running")
        if _job_is_done(status):
            return {
                "job_id": job_id,
                "status": status,
                "cancelled": status == "cancelled",
            }

        thread_id = job.get("thread_id")
        task = job.get("task")
        job["cancel_requested"] = True
        job["status"] = "cancelling"
        job["updated_at"] = time.time()
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
        # Hard-cancel fallback to guarantee user-visible stop behavior.
        if task is not None and not task.done():
            task.cancel()
        await _set_job_status(job_id, "cancelled")
        await _append_job_event(job_id, "cancelled", {"job_id": job_id, "mode": "hard"})
        return {"job_id": job_id, "status": "cancelled", "cancelled": True, "mode": "hard"}

    await _append_job_event(job_id, "cancelling", {"job_id": job_id, "mode": "graceful"})
    return {"job_id": job_id, "status": "cancelling", "cancelled": False, "mode": "graceful"}


@router.get("/agent/research/jobs/{job_id}/events")
async def get_research_job_events(
    job_id: str,
    cursor: int = Query(0, ge=0),
    wait_ms: int = Query(15000, ge=0, le=30000),
    user: User = Depends(current_active_user),
):
    await _cleanup_expired_jobs()
    deadline = time.time() + (wait_ms / 1000.0)
    while True:
        async with _background_jobs_lock:
            job = _background_jobs.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")
            if job.get("user_email") != user.email:
                raise HTTPException(status_code=403, detail="Forbidden")

            events = job.get("events", [])
            status = job.get("status", "running")
            next_cursor = min(cursor, len(events))
            if cursor < len(events):
                payload = {
                    "job_id": job_id,
                    "events": events[cursor:],
                    "next_cursor": len(events),
                    "status": status,
                    "error": job.get("error"),
                    "done": _job_is_done(status),
                }
                return payload
            if _job_is_done(status):
                return {
                    "job_id": job_id,
                    "events": [],
                    "next_cursor": next_cursor,
                    "status": status,
                    "error": job.get("error"),
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

    llm_override = await _resolve_llm_override_from_settings()

    # Build deep-research request body
    deep_research_body = {
        "messages": req.messages,
        "thread_id": req.conversation_id or "__default__",
        "locale": req.locale or "zh-CN",
        # Default settings for normal chat (no deep research)
        "auto_accepted_plan": True,
        "enable_background_investigation": False,
        "enable_deep_thinking": False,
        "enable_clarification": False,
        "enable_web_search": True,
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

        try:
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

                    # Parse SSE events from deep-research
                    buffer = ""
                    async for chunk in response.aiter_text():
                        buffer += chunk

                        # Process complete SSE events (separated by \n\n)
                        while "\n\n" in buffer:
                            event_block, buffer = buffer.split("\n\n", 1)
                            event_block = event_block.strip()
                            if not event_block:
                                continue

                            # Parse event type and data
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
                                    # Filter out JSON structural artifacts from tool call responses
                                    # These appear as: '"}', '}', '&#125;', or just '"' at the end
                                    stripped = content.strip().replace("&#125;", "}").replace("&#123;", "{")
                                    if stripped in ('"}', '{', '}', '"'):
                                        continue
                                    # Strip trailing escaped quote + brace from content like: '?"}'
                                    if content.endswith('"}') or content.endswith('"\\}'):
                                        content = content[:-2]
                                    elif content.endswith('&#125;'):
                                        content = content[:-6]
                                    if content:
                                        yield f'data: {json.dumps({"content": content})}\n\n'

                            elif event_type == "tool_calls":
                                # Detect start of direct_response tool call
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
                                    elif args_text and not in_tool_args:
                                        # Non-direct_response tool — skip args
                                        pass

                            elif event_type == "error":
                                error_msg = parsed.get("error", "Unknown error")
                                error_content = f"\n\n[Error: {error_msg}]"
                                yield f'data: {json.dumps({"content": error_content})}\n\n'

                            # Skip other event types for now (interrupt, tool_call_result, citations, token_usage)

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

        except httpx.ConnectError:
            logger.error(f"[ResearchChat] Cannot connect to deep-research at {_deep_research_target_label()}")
            yield f'data: {json.dumps({"content": "[Error: Cannot connect to deep research service. Is it running?]"})}\n\n'
        except httpx.ReadTimeout:
            logger.error("[ResearchChat] Timeout reading from deep-research")
            yield f'data: {json.dumps({"content": "[Error: Deep research service timed out]"})}\n\n'
        except Exception as e:
            logger.error(f"[ResearchChat] Unexpected error: {e}")
            yield f'data: {json.dumps({"content": f"[Error: {str(e)}]"})}\n\n'
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
