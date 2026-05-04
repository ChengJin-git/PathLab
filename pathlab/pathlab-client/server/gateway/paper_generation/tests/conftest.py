"""
Shared pytest fixtures for paper_generation tests.

Design notes
------------
- `db_session` builds an in-memory async SQLite engine with the SQLAlchemy
  metadata for our `PaperGenerationRun` model. SQLite is enough for unit-level
  CRUD tests; real PostgreSQL behavior is tested in the integration suite
  (out of scope for paper-gen unit tests).
- `paper_run_paths` redirects `Config.get_uploads_dir()` to a temp dir via
  monkeypatch so we never leak `paper_smoketest_*` directories into the real
  uploads area.
- `test_app` builds a minimal FastAPI app with the paper_generation router
  mounted and `current_active_user` / `get_db` dependency-overrides wired so
  TestClient calls don't need a real Postgres / real auth.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Per-test isolated uploads dir (so PaperRunPaths writes into a temp area).
# Autouse: every test that touches storage gets clean dirs.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_uploads(tmp_path: Path, monkeypatch) -> Path:
    """Redirect Config.get_uploads_dir() to a per-test temp directory."""
    from backend.common.config import Config

    monkeypatch.setattr(Config, "get_uploads_dir", classmethod(lambda cls: tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# In-memory async SQLite engine + session
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_engine() -> AsyncGenerator:
    """Per-test in-memory async SQLite engine with metadata created."""
    from backend.database.models import Base, PaperGenerationRun  # noqa: F401

    # `aiosqlite:///:memory:` is *per-connection* — for tests we want a
    # single-connection pool so all sessions see the same in-memory DB.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test async session bound to the in-memory SQLite."""
    SessionLocal = async_sessionmaker(db_engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# User mock (FastAPI-Users style) — minimal surface used by routes.py
# ---------------------------------------------------------------------------

def _make_user(role: str = "admin") -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.role = role
    user.is_active = True
    user.is_superuser = role == "admin"
    return user


@pytest.fixture
def admin_user() -> MagicMock:
    return _make_user("admin")


@pytest.fixture
def regular_user() -> MagicMock:
    return _make_user("pathologist")


@pytest.fixture
def other_user() -> MagicMock:
    return _make_user("pathologist")


# ---------------------------------------------------------------------------
# FastAPI test app + TestClient
# ---------------------------------------------------------------------------

@pytest.fixture
def test_app(db_session, admin_user) -> Iterator[FastAPI]:
    """FastAPI app with paper_generation routes + dependency-overrides.

    `current_active_user` returns `admin_user`. Tests that need a different
    role can override on the returned app.
    """
    from backend.auth import current_active_user
    from backend.database import get_db
    from gateway.paper_generation.routes import router as paper_router

    app = FastAPI()
    app.include_router(paper_router)

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_active_user] = lambda: admin_user
    yield app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    return TestClient(test_app)
