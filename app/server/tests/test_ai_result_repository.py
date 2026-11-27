"""Paginated/export result rows must not trigger async ORM lazy loads."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database.models import AIResult, WSISlide
from backend.database.repositories.ai_result import AIResultRepository


async def test_results_include_slide_metadata_after_session_closes():
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(WSISlide.__table__.create)
            await connection.run_sync(AIResult.__table__.create)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            db.add(WSISlide(wsi_id="slide", wsi_path="/test.png", original_filename="test.png", case_id="case"))
            db.add(AIResult(wsi_id="slide", task_id="batch", pred="tumor", probs={"tumor":0.9}))
            await db.commit()
        async with sessions() as db:
            rows = await AIResultRepository.get_by_task_paginated(db, "batch", limit=None)
        assert len(rows) == 1
        assert rows[0].wsi_slide.original_filename == "test.png"
        assert rows[0].wsi_slide.case_id == "case"
        assert rows[0].probs == {"tumor":0.9}
    finally:
        await engine.dispose()
