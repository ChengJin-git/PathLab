import importlib
from typing import Protocol, cast

import pytest
from pytest import MonkeyPatch


class _FakeMappingResult:
    def mappings(self) -> "_FakeMappingResult":
        return self

    def all(self) -> list[dict[str, object]]:
        return []


class _FakeConnection:
    def __init__(self):
        self.statements: list[str] = []

    async def execute(
        self,
        statement: object,
        _params: object | None = None,
    ) -> _FakeMappingResult | None:
        statement_text = str(statement)
        self.statements.append(statement_text)
        if "SELECT id, username, created_at FROM users" in statement_text:
            return _FakeMappingResult()
        return None

    async def run_sync(self, _fn: object) -> None:
        return None


class _FakeBegin:
    def __init__(self, connection: _FakeConnection):
        self.connection: _FakeConnection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self.connection

    async def __aexit__(self, *_exc_info: object) -> None:
        return None


class _FakeEngine:
    def __init__(self):
        self.connection: _FakeConnection = _FakeConnection()

    def begin(self) -> _FakeBegin:
        return _FakeBegin(self.connection)


class _DatabaseModule(Protocol):
    engine: object

    async def init_db(self) -> None: ...


@pytest.mark.asyncio
async def test_first_activation_backfill_only_marks_active_users(
    monkeypatch: MonkeyPatch,
) -> None:
    database = cast(
        _DatabaseModule,
        cast(object, importlib.import_module("backend.database.database")),
    )

    fake_engine = _FakeEngine()
    monkeypatch.setattr(database, "engine", fake_engine)

    await database.init_db()

    backfill_statements = [
        statement
        for statement in fake_engine.connection.statements
        if "UPDATE users SET first_activated_at" in statement
    ]

    expected_statement = (
        "UPDATE users SET first_activated_at = NOW() "
        "WHERE first_activated_at IS NULL AND is_active = TRUE"
    )
    assert backfill_statements == [expected_statement]
