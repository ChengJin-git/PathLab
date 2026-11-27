from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from backend.database.repositories.auto_research import AutoResearchRepository


@pytest.mark.asyncio
async def test_session_reads_are_owner_scoped():
    result = SimpleNamespace(scalar_one_or_none=lambda: None)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    assert (
        await AutoResearchRepository.get_session(db, "session", user_id="owner") is None
    )
    sql = str(
        db.execute.call_args.args[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert "user_id = 'owner'" in sql and "session_id = 'session'" in sql


@pytest.mark.asyncio
async def test_delete_is_owner_scoped():
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=0)), flush=AsyncMock()
    )
    assert not await AutoResearchRepository.delete_session(
        db, "session", user_id="other"
    )
    sql = str(
        db.execute.call_args.args[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert "user_id = 'other'" in sql


@pytest.mark.asyncio
async def test_upsert_preserves_owner():
    row = SimpleNamespace(user_id="owner", session_id="s", status="running")
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: row)),
        flush=AsyncMock(),
        refresh=AsyncMock(),
    )
    await AutoResearchRepository.upsert_session(
        db, {"session_id": "s", "user_id": "other", "status": "completed"}
    )
    assert row.user_id == "owner" and row.status == "completed"


@pytest.mark.asyncio
async def test_event_replay_is_idempotent():
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: 1))
    )
    assert not await AutoResearchRepository.append_event_once(
        db, "s", {"event_type": "state", "event_data": {}}, 7
    )
