"""Admission control for research sessions, independent from GPU concurrency."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from sqlalchemy import Float, cast, func, select

from backend.common.config import Config
from backend.database.database import safe_session
from backend.database.models import AutoResearchSession
from backend.common.queue_lifecycle import fifo_key, timestamp, recover_fifo, interrupt_for_restart

from . import store

OCCUPIED = {"preparing", "running", "waiting", "pausing", "stopping"}


def queue_order():
    return (
        func.coalesce(
            cast(AutoResearchSession.recovery_metadata['queue_submitted_at'].as_string(), Float),
            func.extract('epoch', AutoResearchSession.created_at),
        ),
        AutoResearchSession.id,
    )


def submission_key(row):
    return fifo_key((row.recovery_metadata or {}).get('queue_submitted_at') or row.created_at, row.id)


def suspended_budget(meta, stopped_at):
    """Checkpoint active budget before downtime; GPU wait is credited only once."""
    result = {'queue_entered_at': meta.get('queue_entered_at') or stopped_at,
              'gpu_wait_started_at': None}
    if meta.get('started_at') and meta.get('gpu_wait_started_at'):
        result['started_at'] = meta['started_at'] + max(0, stopped_at - meta['gpu_wait_started_at'])
    return result


async def queue_snapshot() -> dict:
    async with safe_session() as db:
        rows = (
            await db.execute(
                select(AutoResearchSession.session_id, AutoResearchSession.user_id, AutoResearchSession.status)
                .where(
                    AutoResearchSession.status.in_(store.ACTIVE),
                )
                .order_by(*queue_order())
            )
        ).all()
    waiting = [row.session_id for row in rows if row.status == "queued"]
    limit = Config.get_max_autoresearch_concurrent()
    running = sum(row.status in OCCUPIED for row in rows)
    return {
        "limit": limit,
        "running": running,
        "queued": len(waiting),
        "positions": {sid: index + 1 for index, sid in enumerate(waiting)},
    }


def session_queue(snapshot: dict, session_id: str, status: str) -> dict:
    position = snapshot["positions"].get(session_id, 0)
    return {
        "limit": snapshot["limit"],
        "running": snapshot["running"],
        "position": position,
        "busy": status == "queued"
        and (
            snapshot["running"] >= snapshot["limit"]
            or position > max(0, snapshot["limit"] - snapshot["running"])
        ),
    }


class ResearchScheduler:
    """The deployment's advisory-locked supervisor is the sole session owner."""

    def __init__(
        self,
        run: Callable[[str], Awaitable[None]],
        stop_jobs: Callable[[str], Awaitable[None]],
        cleanup: Callable[[str], Awaitable[None]],
    ):
        self.run = run
        self.stop_jobs = stop_jobs
        self.cleanup = cleanup
        self.tasks: dict[str, asyncio.Task] = {}

    async def recover(self, rows: list):
        # A crashed supervisor may leave agents alive, including ones outside the
        # new cap. Reap every orphan before admitting the first recovered session.
        async def restore(row):
            if row.status not in store.ACTIVE or (row.recovery_metadata or {}).get('delete_requested'):
                return
            await self.cleanup(row.session_id)
            if row.status in {"preparing", "running", "waiting"}:
                meta = row.recovery_metadata or {}
                stopped_at = meta.get('last_active_at') or timestamp(row.updated_at)
                await store.update(
                    row.session_id,
                    status="queued",
                    meta={**suspended_budget(meta, stopped_at), 'queue_reason': 'restart'},
                    expected_statuses={"preparing", "running", "waiting"},
                    event={"kind": "state", "status": "queued", 'queue_reason': 'restart'},
                )
        await recover_fifo(rows, key=submission_key, restore=restore)

    async def requeue(self, sid, reason):
        current = await store.get(sid)
        if current.status in {'running', 'waiting', 'preparing'}:
            await store.update(
                sid, status='queued',
                meta={**suspended_budget(current.recovery_metadata or {}, time.time()), 'queue_reason': reason},
                expected_statuses={'running', 'waiting', 'preparing'},
                event={'kind': 'state', 'status': 'queued', 'queue_reason': reason},
            )

    async def tick(self, rows: list, limit: int):
        for sid, task in list(self.tasks.items()):
            if not task.done():
                continue
            if not task.cancelled() and (error := task.exception()) is not None:
                logging.getLogger(__name__).error('Research runner %s interrupted: %s', sid, type(error).__name__)
                current = await store.get(sid)
                if current.status in {'running', 'waiting', 'preparing'}:
                    saved = current.recovery_metadata or {}
                    stopped_at = saved.get('last_active_at') or timestamp(current.updated_at)
                    await store.update(sid, status='queued',
                        meta={**suspended_budget(saved, stopped_at), 'queue_reason': 'restart'},
                        expected_statuses={'running', 'waiting', 'preparing'},
                        event={'kind': 'state', 'status': 'queued', 'queue_reason': 'restart'})
            self.tasks.pop(sid)
        # Lowering the limit checkpoints excess agents before admitting any work.
        excess = list(self.tasks)[limit:]
        for sid in excess:
            task = self.tasks.pop(sid)
            await interrupt_for_restart([task])
            await self.requeue(sid, 'capacity')
        for row in sorted(rows, key=submission_key):
            sid = row.session_id
            if sid in self.tasks or sid in excess:
                continue
            try:
                row = await store.get(sid)
            except KeyError:
                # A durable conversation deletion may settle between ticks.
                continue
            if (row.recovery_metadata or {}).get('delete_requested'):
                continue
            if row.status not in store.ACTIVE:
                continue
            # Cancelling a queued session must work even while every slot is full.
            if row.status in {"pausing", "stopping"}:
                if row.status == "stopping":
                    await self.stop_jobs(sid)
                for command in await store.take_commands(sid):
                    if command["kind"] in {"pause", "stop"}:
                        await store.acknowledge_command(sid, command["id"])
                status = "paused" if row.status == "pausing" else "interrupted"
                await store.update(
                    sid,
                    status=status,
                    expected_statuses={row.status},
                    event={"kind": "state", "status": status},
                )
                continue
            if len(self.tasks) >= limit:
                if row.status != "queued":
                    await store.update(
                        sid,
                        status="queued",
                        event={"kind": "state", "status": "queued"},
                    )
                continue
            meta = {"queue_reason": "", "queue_entered_at": None}
            saved = getattr(row, "recovery_metadata", None) or {}
            if saved.get("queue_entered_at") and saved.get("started_at"):
                downtime = max(0, time.time() - saved['queue_entered_at'])
                meta['started_at'] = saved['started_at'] + downtime
                if saved.get('budget_shutdown'):
                    shutdown = saved['budget_shutdown']
                    meta['budget_shutdown'] = {**shutdown, 'started_at': shutdown['started_at'] + downtime, 'deadline': shutdown['deadline'] + downtime}
            meta['last_active_at'] = time.time()
            admitted = await store.update(
                sid,
                status="preparing",
                meta=meta,
                expected_statuses={"queued", "running", "waiting", "preparing"},
                event={"kind": "state", "status": "preparing"},
            )
            if admitted:
                self.tasks[sid] = asyncio.create_task(self.run(sid))

    async def shutdown(self):
        await interrupt_for_restart(self.tasks.values())
        for sid in self.tasks:
            await self.requeue(sid, 'restart')
        self.tasks.clear()
