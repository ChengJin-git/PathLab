from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from gateway.routes.storage_inventory import router
from backend.auth.dependencies import require_admin
from backend.database.database import get_db
from backend.storage.inventory import Inventory, STATES
from backend.storage.references import References


@pytest.fixture
def app(tmp_path, monkeypatch):
    from gateway.routes import storage_inventory as routes

    monkeypatch.setattr(routes.Config, "get_uploads_dir", lambda: tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/storage")

    async def db():
        yield SimpleNamespace(scalar=AsyncMock(return_value=None))

    app.dependency_overrides[get_db] = db
    return app, tmp_path


async def test_inventory_is_admin_only(app):
    application, _ = app
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        for path in (
            "/storage/inventory",
            "/storage/inventory/items",
        ):
            assert (await client.get(path)).status_code in {401, 403}


async def test_bounded_pages_invalid_cursor_and_stale_generation(app, monkeypatch):
    application, root = app
    application.dependency_overrides[require_admin] = lambda: SimpleNamespace(
        id="owner"
    )
    monkeypatch.setattr("backend.storage.inventory.GRACE_SECONDS", -1)
    for i in range(120):
        path = root / f"metadata/wsi_{i:016x}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text("{}")
    inventory = Inventory(root)
    summary = inventory.scan(References())
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/storage/inventory/items?limit=50&state=orphaned")
        assert response.status_code == 200 and len(response.json()["items"]) == 50
        assert response.json()["total"] == 120
        assert response.json()["allocated"] >= sum(
            item["allocated"] for item in response.json()["items"]
        )
        assert response.json()["next_cursor"]
        assert (
            await client.get("/storage/inventory/items?limit=1000")
        ).status_code == 422
        assert (
            await client.get("/storage/inventory/items?cursor=invalid")
        ).status_code == 422
        assert (
            await client.post(
                "/storage/inventory/cleanup",
                json={"generation": "0" * 32, "scope": "all"},
            )
        ).status_code == 409
        response = await client.get("/storage/inventory")
        assert response.json()["generation"] == summary["generation"]
        assert len(response.content) < 3000


async def test_all_state_filters_work_when_categories_have_different_states(
    app, monkeypatch
):
    application, root = app
    application.dependency_overrides[require_admin] = lambda: SimpleNamespace(
        id="owner"
    )
    monkeypatch.setattr("backend.storage.inventory.GRACE_SECONDS", -1)
    for relative in (
        "models/owned/weights.pth",
        "metadata/wsi_0123456789abcdef.json",
        "extractor_checkpoints/uni/weights.pth",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"content")
    inventory = Inventory(root)
    summary = inventory.scan(References(owners={"owned"}))
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        for state in STATES:
            response = await client.get(
                "/storage/inventory/items", params={"state": state}
            )
            assert response.status_code == 200
            expected = sum(
                group["states"][state]["items"] for group in summary["categories"]
            )
            assert response.json()["total"] == expected
            assert len(response.json()["items"]) == expected
        assert (await client.get("/storage/inventory/records")).status_code == 404
        assert (
            await client.post("/storage/inventory/records/cleanup")
        ).status_code == 404


async def test_cleanup_requires_an_explicit_nonempty_selection(app):
    application, _ = app
    application.dependency_overrides[require_admin] = lambda: SimpleNamespace(
        id="owner"
    )
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        for selection in (
            {},
            {"scope": "selected", "ids": []},
            {"scope": "all", "ids": ["one"]},
            {"scope": "selected", "ids": ["one"], "excluded_ids": ["two"]},
        ):
            response = await client.post(
                "/storage/inventory/cleanup", json={"generation": "a" * 32, **selection}
            )
            assert response.status_code == 422
