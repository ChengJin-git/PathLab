"""Startup validates the current schema without replaying historical data upgrades."""

import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.database import current_schema


@pytest.mark.parametrize("ledger,version", [(False, None), (True, None)])
async def test_existing_database_requires_current_version(ledger, version):
    connection = SimpleNamespace(
        scalar=AsyncMock(side_effect=["public", version]),
        run_sync=AsyncMock(side_effect=[True, ledger]),
        execute=AsyncMock(),
    )
    with pytest.raises(RuntimeError, match="Database schema does not match"):
        await current_schema.initialize(connection)
    connection.execute.assert_not_awaited()


async def test_current_database_startup_does_not_rewrite_data():
    connection = SimpleNamespace(
        scalar=AsyncMock(side_effect=["public", 1]),
        run_sync=AsyncMock(side_effect=[True, True]),
        execute=AsyncMock(),
    )
    await current_schema.initialize(connection)
    assert connection.scalar.call_args.args[1] == {"v": current_schema.SCHEMA_VERSION}
    connection.execute.assert_not_awaited()


async def test_schema_failure_preserves_original_error_and_releases_transaction(
    monkeypatch,
):
    database = importlib.import_module("backend.database.database")
    connection = SimpleNamespace(execute=AsyncMock())
    exited = []

    @asynccontextmanager
    async def begin():
        try:
            yield connection
        finally:
            exited.append(True)

    original = RuntimeError("schema initialization failed")
    monkeypatch.setattr(database, "engine", SimpleNamespace(begin=begin))
    monkeypatch.setattr(current_schema, "initialize", AsyncMock(side_effect=original))
    admin = AsyncMock()
    monkeypatch.setattr(database, "_create_default_admin", admin)
    with pytest.raises(RuntimeError) as raised:
        await database.init_db()
    assert raised.value is original
    assert exited == [True]
    assert (
        str(connection.execute.call_args.args[0])
        == "SELECT pg_advisory_xact_lock(2026040801)"
    )
    admin.assert_not_awaited()
