"""
Auto Research Agent — API Server

FastAPI routes for starting, monitoring, and controlling auto-research sessions.
Can be mounted into the gateway or run standalone.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.database.repositories import AutoResearchRepository
from backend.auth import current_active_user, User

from .builder import build_auto_research_graph
from .monitor import ExperimentMonitor, MonitoredSession, get_monitor
from .tools import configure_tools
from .types import AutoResearchConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auto-research", tags=["Auto Research"])

# In-memory graph instances per session (for interrupt/resume)
_active_graphs: dict[str, Any] = {}
_active_tasks: dict[str, asyncio.Task] = {}


# =============================================================================
# Request/Response Models
# =============================================================================

class StartRequest(BaseModel):
    research_question: str = Field(..., min_length=5)
    max_iterations: int = Field(default=3, ge=1, le=10)
    primary_metric: str = Field(default="auc")
    auto_approve_plan: bool = Field(default=False)
    locale: str = Field(default="en-US")


class ApproveRequest(BaseModel):
    feedback: str = Field(..., description="'accepted' or 'edit_plan'")
    message: Optional[str] = Field(default=None, description="Edit instructions if feedback is edit_plan")


class StopRequest(BaseModel):
    reason: Optional[str] = None


# =============================================================================
# Helper: Run Graph in Background
# =============================================================================

async def _run_graph_session(
    session_id: str,
    research_question: str,
    config: AutoResearchConfig,
    user_id: str,
):
    """Run the auto-research graph as a background task, persisting events."""
    thread_id = session_id  # Use session_id as thread_id for simplicity

    # Configure tools with gateway URL and auth token
    configure_tools(config.gateway_url, config.auth_token)

    # Build graph
    graph = build_auto_research_graph()
    _active_graphs[session_id] = graph

    # Initial state
    initial_state = {
        "research_question": research_question,
        "locale": config.locale if hasattr(config, 'locale') else "en-US",
        "max_iterations": config.max_iterations,
        "best_metric_name": config.primary_metric,
    }

    graph_config = {"configurable": {"thread_id": thread_id}}
    event_seq = 0

    try:
        # Emit start event
        async with async_session() as db:
            event_seq = await AutoResearchRepository.append_events_batch(
                db, session_id,
                [{"event_type": "phase_change", "event_data": {
                    "phase": "literature", "message": "Starting auto research..."
                }}],
                event_seq,
            )
            await db.commit()

        # Stream graph execution
        async for event in graph.astream(initial_state, graph_config, stream_mode="updates"):
            if not event:
                continue

            # Extract node name and state update
            for node_name, state_update in event.items():
                if node_name == "__interrupt__":
                    # Graph interrupted (human_review or experiment_monitor)
                    async with async_session() as db:
                        interrupt_data = state_update
                        event_seq = await AutoResearchRepository.append_events_batch(
                            db, session_id,
                            [{"event_type": "interrupt", "event_data": {
                                "node": "unknown",
                                "data": str(interrupt_data),
                            }}],
                            event_seq,
                        )
                        await db.commit()
                    continue

                # Extract phase and messages from state update
                phase = state_update.get("phase", "")
                messages = state_update.get("messages", [])

                events_to_write = []

                if phase:
                    events_to_write.append({
                        "event_type": "phase_change",
                        "event_data": {"phase": phase, "node": node_name},
                    })

                # Persist plan if created
                if "experiment_plan" in state_update and state_update["experiment_plan"]:
                    events_to_write.append({
                        "event_type": "plan_created",
                        "event_data": {
                            "experiments": state_update["experiment_plan"],
                            "requires_approval": not state_update.get("plan_approved", False),
                        },
                    })

                # Persist literature findings
                if "literature_findings" in state_update and state_update["literature_findings"]:
                    for finding in state_update["literature_findings"]:
                        events_to_write.append({
                            "event_type": "literature_finding",
                            "event_data": finding,
                        })

                # Persist comparison table
                if "comparison_table" in state_update and state_update["comparison_table"]:
                    events_to_write.append({
                        "event_type": "analysis_complete",
                        "event_data": {"comparison_table": state_update["comparison_table"]},
                    })

                # Persist ratchet update
                if "best_metric" in state_update:
                    events_to_write.append({
                        "event_type": "ratchet_update",
                        "event_data": {
                            "best_metric": state_update.get("best_metric"),
                            "best_experiment": state_update.get("best_experiment"),
                        },
                    })

                # Persist final report
                if "final_report" in state_update and state_update["final_report"]:
                    events_to_write.append({
                        "event_type": "report_generated",
                        "event_data": {"report": state_update["final_report"]},
                    })

                # Agent thinking from messages
                for msg in messages:
                    content = msg.content if hasattr(msg, 'content') else str(msg)
                    if content:
                        events_to_write.append({
                            "event_type": "agent_thinking",
                            "event_data": {"agent": node_name, "message": content[:2000]},
                        })

                if events_to_write:
                    async with async_session() as db:
                        event_seq = await AutoResearchRepository.append_events_batch(
                            db, session_id, events_to_write, event_seq,
                        )
                        # Update session phase
                        if phase:
                            await AutoResearchRepository.update_session(
                                db, session_id, phase=phase,
                            )
                        await db.commit()

        # Graph completed
        async with async_session() as db:
            await AutoResearchRepository.update_session(
                db, session_id, status="completed",
            )
            await AutoResearchRepository.append_events_batch(
                db, session_id,
                [{"event_type": "end", "event_data": {"status": "completed"}}],
                event_seq,
            )
            await db.commit()

    except asyncio.CancelledError:
        async with async_session() as db:
            await AutoResearchRepository.update_session(db, session_id, status="cancelled")
            await db.commit()

    except Exception as e:
        logger.error(f"[auto-research] Session {session_id} failed: {e}", exc_info=True)
        async with async_session() as db:
            await AutoResearchRepository.update_session(
                db, session_id, status="failed",
            )
            await AutoResearchRepository.append_events_batch(
                db, session_id,
                [{"event_type": "end", "event_data": {"status": "failed", "error": str(e)}}],
                event_seq,
            )
            await db.commit()

    finally:
        _active_graphs.pop(session_id, None)
        _active_tasks.pop(session_id, None)


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/start")
async def start_auto_research(
    req: StartRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new auto-research session and start the graph."""
    session_id = f"ar_{uuid.uuid4().hex[:16]}"
    thread_id = session_id

    # Create session in DB
    session = await AutoResearchRepository.create_session(db, {
        "session_id": session_id,
        "user_id": str(user.id),
        "research_question": req.research_question,
        "thread_id": thread_id,
        "max_iterations": req.max_iterations,
        "best_metric_name": req.primary_metric,
    })
    await db.commit()

    # Build config
    config = AutoResearchConfig(
        max_iterations=req.max_iterations,
        primary_metric=req.primary_metric,
        auto_approve_plan=req.auto_approve_plan,
    )

    # Start graph in background
    task = asyncio.create_task(
        _run_graph_session(session_id, req.research_question, config, str(user.id))
    )
    _active_tasks[session_id] = task

    return {
        "session_id": session_id,
        "message": f"Auto research started for: {req.research_question}",
    }


@router.get("/{session_id}/stream")
async def stream_events(
    session_id: str,
    cursor: int = 0,
    user: User = Depends(current_active_user),
):
    """SSE stream of auto-research events with cursor-based replay."""

    async def event_generator():
        current_cursor = cursor
        consecutive_empty = 0

        try:
            while True:
                async with async_session() as db:
                    # Verify ownership
                    session = await AutoResearchRepository.get_session(db, session_id)
                    if not session or session.user_id != str(user.id):
                        err = json.dumps({"error": "Not found"})
                        yield f"data: {err}\n\n"
                        break

                    # Get new events
                    events = await AutoResearchRepository.get_events_after(
                        db, session_id, current_cursor, limit=50,
                    )

                    if events:
                        consecutive_empty = 0
                        for event in events:
                            payload = json.dumps(
                                {
                                    "event_type": event.event_type,
                                    "data": event.event_data,
                                    "sequence": event.sequence,
                                },
                                ensure_ascii=False,
                                default=str,
                            )
                            yield f"data: {payload}\n\n"
                            current_cursor = event.sequence

                        # Check if session is done
                        if session.status in ("completed", "failed", "cancelled"):
                            break
                    else:
                        consecutive_empty += 1
                        if session.status in ("completed", "failed", "cancelled"):
                            break

                await asyncio.sleep(2)

        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{session_id}/approve")
async def approve_plan(
    session_id: str,
    req: ApproveRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve or edit the experiment plan (resumes interrupted graph)."""
    session = await AutoResearchRepository.get_session(db, session_id)
    if not session or session.user_id != str(user.id):
        raise HTTPException(status_code=404, detail="Session not found")

    graph = _active_graphs.get(session_id)
    if not graph:
        raise HTTPException(status_code=400, detail="No active graph for this session")

    # Resume the graph with user feedback
    feedback = req.feedback.upper()
    if req.message:
        resume_value = f"[{feedback}] {req.message}"
    else:
        resume_value = f"[{feedback}]"

    try:
        from langgraph.types import Command
        graph_config = {"configurable": {"thread_id": session_id}}

        # Resume by sending the interrupt response
        asyncio.create_task(
            _resume_graph(session_id, graph, graph_config, resume_value)
        )

        return {"message": f"Plan {feedback.lower()}", "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _resume_graph(session_id: str, graph, config: dict, resume_value: str):
    """Resume an interrupted graph with feedback."""
    try:
        from langgraph.types import Command
        async for event in graph.astream(Command(resume=resume_value), config, stream_mode="updates"):
            # Events are handled by the running _run_graph_session task
            pass
    except Exception as e:
        logger.error(f"[auto-research] Resume failed for {session_id}: {e}")


@router.post("/{session_id}/stop")
async def stop_session(
    session_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Stop an active auto-research session."""
    session = await AutoResearchRepository.get_session(db, session_id)
    if not session or session.user_id != str(user.id):
        raise HTTPException(status_code=404, detail="Session not found")

    # Cancel the background task
    task = _active_tasks.get(session_id)
    if task and not task.done():
        task.cancel()

    await AutoResearchRepository.update_session(db, session_id, status="cancelled")
    await db.commit()

    # Unregister from monitor
    get_monitor().unregister(session_id)

    return {"message": "Session stopped", "session_id": session_id}


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get auto-research session details."""
    session = await AutoResearchRepository.get_session(db, session_id)
    if not session or session.user_id != str(user.id):
        raise HTTPException(status_code=404, detail="Session not found")

    experiments = await AutoResearchRepository.get_session_experiments(db, session_id)

    return {
        **session.to_dict(),
        "experiment_plan": session.experiment_plan,
        "comparison_results": session.comparison_results,
        "final_report": session.final_report,
        "experiments": [e.to_dict() for e in experiments],
    }


@router.get("/sessions/list")
async def list_sessions(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List all auto-research sessions for the current user."""
    sessions = await AutoResearchRepository.get_user_sessions(db, str(user.id))
    return {
        "items": [s.to_dict() for s in sessions],
    }
