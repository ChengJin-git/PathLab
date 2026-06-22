import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database.models import Base, WSISlide
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


def _make_wsi_app(user_role: str = "admin") -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[wsi_routes.current_active_user] = lambda: _make_user(user_role)
    app.dependency_overrides[wsi_routes.get_user_id_filter] = lambda: None
    app.dependency_overrides[wsi_routes.get_db] = lambda: object()
    app.include_router(wsi_routes.router)
    return app


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


@pytest.mark.asyncio
async def test_list_datasets_rejects_unbounded_page_size(monkeypatch):
    async def _fake_get_datasets_with_total(*_args, **_kwargs):
        return [], 0

    async def _fake_get_permitted_dataset_ids(*_args):
        return []

    monkeypatch.setattr(
        WSIRepository,
        "get_datasets_with_total",
        staticmethod(_fake_get_datasets_with_total),
    )
    monkeypatch.setattr(wsi_routes, "get_permitted_dataset_ids", _fake_get_permitted_dataset_ids)

    async with AsyncClient(
        transport=ASGITransport(app=_make_wsi_app()), base_url="http://test"
    ) as client:
        response = await client.get("/wsi/datasets?page_size=0")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_wsi_rejects_unbounded_page_size(monkeypatch):
    async def _fake_get_all_with_dataset(*_args, **_kwargs):
        return []

    async def _fake_count(*_args, **_kwargs):
        return 0

    async def _fake_get_permitted_dataset_ids(*_args):
        return []

    monkeypatch.setattr(
        WSIRepository,
        "get_all_with_dataset",
        staticmethod(_fake_get_all_with_dataset),
    )
    monkeypatch.setattr(WSIRepository, "count", staticmethod(_fake_count))
    monkeypatch.setattr(wsi_routes, "get_permitted_dataset_ids", _fake_get_permitted_dataset_ids)

    async with AsyncClient(
        transport=ASGITransport(app=_make_wsi_app()), base_url="http://test"
    ) as client:
        response = await client.get("/wsi?page_size=0")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_dataset_source_options_uses_lightweight_repository(monkeypatch):
    async def _fake_get_dataset_source_options(_db, **kwargs):
        assert kwargs["user_id"] is None
        assert kwargs["elevated_dataset_ids"] == []
        assert kwargs["data_type"] == "wsi"
        return ["Breast", "Lung", "__unknown__"]

    async def _fake_get_permitted_dataset_ids(*_args):
        return []

    async def _forbid_availability_lookup(*_args, **_kwargs):
        raise AssertionError("source options must not load WSI path refs")

    monkeypatch.setattr(
        WSIRepository,
        "get_dataset_source_options",
        staticmethod(_fake_get_dataset_source_options),
        raising=False,
    )
    monkeypatch.setattr(
        DatasetRepository,
        "get_wsi_path_refs_batch",
        staticmethod(_forbid_availability_lookup),
    )
    monkeypatch.setattr(wsi_routes, "get_permitted_dataset_ids", _fake_get_permitted_dataset_ids)

    async with AsyncClient(
        transport=ASGITransport(app=_make_wsi_app()), base_url="http://test"
    ) as client:
        response = await client.get("/wsi/dataset-source-options?data_type=wsi")

    assert response.status_code == 200
    assert response.json() == {"items": ["Breast", "Lung", "__unknown__"]}


def test_wsi_model_has_case_pagination_indexes():
    index_columns_by_name = {
        index.name: tuple(column.name for column in index.columns)
        for index in WSISlide.__table__.indexes
    }

    assert index_columns_by_name["idx_wsi_dataset_case"] == ("dataset_id", "case_id")
    assert index_columns_by_name["idx_wsi_dataset_type_case"] == (
        "dataset_id",
        "data_type",
        "case_id",
    )


@pytest.mark.asyncio
async def test_external_wsi_path_refs_filters_upload_root_in_database(monkeypatch):
    uploads_dir = "/tmp/Path_lab/uploads"
    monkeypatch.setattr(
        "backend.database.repositories.dataset.Config.get_uploads_dir",
        lambda: uploads_dir,
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as db:
            await db.execute(
                WSISlide.__table__.insert(),
                [
                    {
                        "wsi_id": "internal",
                        "dataset_id": "ds-1",
                        "wsi_path": f"{uploads_dir}/wsi_files/internal.svs",
                    },
                    {
                        "wsi_id": "external",
                        "dataset_id": "ds-1",
                        "wsi_path": "/mnt/external/external.svs",
                    },
                    {
                        "wsi_id": "sibling-with-like-wildcard",
                        "dataset_id": "ds-1",
                        "wsi_path": "/tmp/PathXlab/uploads/external.svs",
                    },
                    {
                        "wsi_id": "other-dataset",
                        "dataset_id": "ds-2",
                        "wsi_path": "/mnt/external/other.svs",
                    },
                ]
            )
            await db.commit()

            refs = await DatasetRepository.get_external_wsi_path_refs_batch(
                db, ["ds-1"]
            )

        assert {ref["wsi_id"] for ref in refs["ds-1"]} == {
            "external",
            "sibling-with-like-wildcard",
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_original_filenames_by_dataset_filters_candidates_in_database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as db:
            await db.execute(
                WSISlide.__table__.insert(),
                [
                    {
                        "wsi_id": "target-a",
                        "dataset_id": "ds-1",
                        "original_filename": "a.svs",
                        "wsi_path": "/mnt/external/a.svs",
                    },
                    {
                        "wsi_id": "target-b",
                        "dataset_id": "ds-1",
                        "original_filename": "b.svs",
                        "wsi_path": "/mnt/external/b.svs",
                    },
                    {
                        "wsi_id": "other-dataset",
                        "dataset_id": "ds-2",
                        "original_filename": "a.svs",
                        "wsi_path": "/mnt/external/other.svs",
                    },
                ],
            )
            await db.commit()

            existing = await WSIRepository.get_original_filenames_by_dataset(
                db, "ds-1", ["a.svs", "missing.svs"]
            )

        assert existing == {"a.svs"}
    finally:
        await engine.dispose()


def test_startup_ddl_creates_case_pagination_indexes_for_existing_tables():
    database_source = (
        Path(__file__).parents[1] / "backend" / "database" / "database.py"
    ).read_text()

    assert "CREATE INDEX IF NOT EXISTS idx_wsi_dataset_case" in database_source
    assert "CREATE INDEX IF NOT EXISTS idx_wsi_dataset_type_case" in database_source
