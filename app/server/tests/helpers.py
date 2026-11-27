"""
Shared test helper functions.

These are plain functions (not pytest fixtures) used directly by test modules.
Kept in helpers.py (not conftest.py) to avoid being shadowed by any
site-packages 'tests' package when using absolute imports.
"""

import uuid
from unittest.mock import MagicMock
from fastapi import FastAPI


def _make_user(role: str = "admin") -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.role = role
    user.is_active = True
    user.is_admin = MagicMock(return_value=(role == "admin"))
    user.can_use_gpu = MagicMock(return_value=(role in ("admin", "pathologist")))
    return user


def make_settings_app(user_stub) -> FastAPI:
    from gateway.routes.settings import router as settings_router
    from backend.auth import current_active_user
    from backend.auth.dependencies import require_admin

    app = FastAPI()
    app.dependency_overrides[current_active_user] = lambda: user_stub
    app.dependency_overrides[require_admin] = lambda: user_stub
    app.include_router(settings_router)
    return app


def make_queue_app(user_stub) -> FastAPI:
    from gateway.routes.queue import router as queue_router
    from backend.auth import current_active_user
    from backend.auth.dependencies import require_admin

    app = FastAPI()
    app.dependency_overrides[current_active_user] = lambda: user_stub
    app.dependency_overrides[require_admin] = lambda: user_stub
    app.include_router(queue_router)
    return app
