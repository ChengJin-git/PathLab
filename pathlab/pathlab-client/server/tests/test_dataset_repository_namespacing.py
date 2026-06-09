import types

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.database.repositories.dataset import (
    DatasetNameConflictError,
    DatasetRepository,
)
from backend.database.repositories.wsi import WSIRepository
from gateway.routes import wsi as wsi_routes
from helpers import _make_user


class _AsyncNullContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummyDB:
    def begin_nested(self):
        return _AsyncNullContext()


@pytest.mark.asyncio
async def test_get_or_create_scopes_lookup_to_user_namespace(monkeypatch):
    existing_other_user = types.SimpleNamespace(
        dataset_id="ds-a",
        user_id="user-a",
        name="Shared Dataset",
    )
    created_for_target_user = types.SimpleNamespace(
        dataset_id="ds-b",
        user_id="user-b",
        name="Shared Dataset",
    )

    lookup_user_ids = []
    create_calls = []

    async def _fake_get_by_name(_db, _name, user_id=None):
        lookup_user_ids.append(user_id)
        if user_id is None:
            return existing_other_user
        return None

    async def _fake_create(_db, **kwargs):
        create_calls.append(
            {
                "group_id": kwargs.get("group_id"),
                "user_id": kwargs.get("user_id"),
                "source_organ": kwargs.get("source_organ"),
                "parent_dataset_id": kwargs.get("parent_dataset_id"),
                "is_public": kwargs.get("is_public", False),
            }
        )
        return created_for_target_user

    async def _fake_get_by_id(_db, _dataset_id):
        return created_for_target_user

    monkeypatch.setattr(
        DatasetRepository,
        "get_by_name",
        staticmethod(_fake_get_by_name),
    )
    monkeypatch.setattr(
        DatasetRepository,
        "create",
        staticmethod(_fake_create),
    )
    monkeypatch.setattr(
        DatasetRepository,
        "get_by_id",
        staticmethod(_fake_get_by_id),
    )

    result = await DatasetRepository.get_or_create(
        _DummyDB(),
        name="Shared Dataset",
        group_id="group-1",
        user_id="user-b",
    )

    assert lookup_user_ids == ["user-b"]
    assert len(create_calls) == 1
    assert result.user_id == "user-b"


@pytest.mark.asyncio
async def test_get_or_create_reuses_dataset_for_same_user(monkeypatch):
    existing_same_user = types.SimpleNamespace(
        dataset_id="ds-a",
        user_id="user-a",
        name="Dataset A",
    )

    create_calls = []

    async def _fake_get_by_name(_db, _name, user_id=None):
        if user_id == "user-a":
            return existing_same_user
        return None

    async def _fake_create(*_args, **_kwargs):
        create_calls.append(True)
        return types.SimpleNamespace(dataset_id="new", user_id="user-a")

    monkeypatch.setattr(
        DatasetRepository,
        "get_by_name",
        staticmethod(_fake_get_by_name),
    )
    monkeypatch.setattr(
        DatasetRepository,
        "create",
        staticmethod(_fake_create),
    )

    result = await DatasetRepository.get_or_create(
        _DummyDB(),
        name="Dataset A",
        group_id="group-1",
        user_id="user-a",
    )

    assert result is existing_same_user
    assert create_calls == []


@pytest.mark.asyncio
async def test_get_or_create_raises_conflict_when_reuse_disabled(monkeypatch):
    existing_same_user = types.SimpleNamespace(
        dataset_id="ds-a",
        user_id="user-a",
        name="Dataset A",
    )

    async def _fake_get_by_name(_db, _name, user_id=None):
        if user_id == "user-a":
            return existing_same_user
        return None

    monkeypatch.setattr(
        DatasetRepository,
        "get_by_name",
        staticmethod(_fake_get_by_name),
    )

    with pytest.raises(DatasetNameConflictError):
        await DatasetRepository.get_or_create(
            _DummyDB(),
            name="Dataset A",
            group_id="group-1",
            user_id="user-a",
            reuse_existing=False,
        )


@pytest.mark.asyncio
async def test_list_datasets_passes_private_visibility_filter(monkeypatch):
    captured_filters = []

    async def _fake_get_datasets_with_total(_db, **kwargs):
        captured_filters.append(kwargs.get("is_public"))
        return [], 0

    monkeypatch.setattr(
        WSIRepository,
        "get_datasets_with_total",
        staticmethod(_fake_get_datasets_with_total),
    )
    async def _fake_get_permitted_dataset_ids(*_args):
        return []

    monkeypatch.setattr(wsi_routes, "get_permitted_dataset_ids", _fake_get_permitted_dataset_ids)

    app = FastAPI()
    app.dependency_overrides[wsi_routes.current_active_user] = lambda: _make_user("admin")
    app.dependency_overrides[wsi_routes.get_user_id_filter] = lambda: None
    app.dependency_overrides[wsi_routes.get_db] = lambda: object()
    app.include_router(wsi_routes.router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/wsi/datasets?is_public=false")

    assert response.status_code == 200
    assert captured_filters == [False]


@pytest.mark.asyncio
async def test_list_datasets_passes_public_visibility_filter(monkeypatch):
    captured_filters = []

    async def _fake_get_datasets_with_total(_db, **kwargs):
        captured_filters.append(kwargs.get("is_public"))
        return [], 0

    monkeypatch.setattr(
        WSIRepository,
        "get_datasets_with_total",
        staticmethod(_fake_get_datasets_with_total),
    )
    async def _fake_get_permitted_dataset_ids(*_args):
        return []

    monkeypatch.setattr(wsi_routes, "get_permitted_dataset_ids", _fake_get_permitted_dataset_ids)

    app = FastAPI()
    app.dependency_overrides[wsi_routes.current_active_user] = lambda: _make_user("admin")
    app.dependency_overrides[wsi_routes.get_user_id_filter] = lambda: None
    app.dependency_overrides[wsi_routes.get_db] = lambda: object()
    app.include_router(wsi_routes.router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/wsi/datasets?is_public=true")

    assert response.status_code == 200
    assert captured_filters == [True]
