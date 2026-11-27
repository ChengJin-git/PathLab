"""Transaction-scoped queue backpressure shared by creation and continuation."""

import os
from fastapi import HTTPException
from sqlalchemy import func, select, text
from backend.database.models import AutoResearchSession


async def lock_admission(db):
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    await db.execute(text("SELECT pg_advisory_xact_lock(71849123)"))


async def check_capacity(db, user_id: str):
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    await lock_admission(db)
    active = {"preparing", "queued", "running", "waiting", "pausing", "stopping"}
    total = await db.scalar(
        select(func.count())
        .select_from(AutoResearchSession)
        .where(
            AutoResearchSession.status.in_(active),
        )
    )
    owned = await db.scalar(
        select(func.count())
        .select_from(AutoResearchSession)
        .where(
            AutoResearchSession.status.in_(active),
            AutoResearchSession.user_id == user_id,
        )
    )
    if total >= max(
        1, int(os.getenv("PATHLAB_RESEARCH_MAX_PENDING", "100"))
    ) or owned >= max(1, int(os.getenv("PATHLAB_RESEARCH_MAX_PENDING_PER_USER", "8"))):
        raise HTTPException(
            429,
            "Research queue is full. Finish or pause an existing task before starting another.",
        )
