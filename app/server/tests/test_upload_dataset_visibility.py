"""Exercise upload choices with real SQL, paging and detail lookups."""

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.auth.models import User
from backend.database.models import (
    DataGroup, Dataset, DatasetTask, DatasetStats, Workspace, WSISlide,
)
from gateway.routes import wsi


@pytest.fixture
async def upload_api():
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    for model in [User, DataGroup, Dataset, DatasetTask, DatasetStats, Workspace, WSISlide]:
        model.__table__.to_metadata(metadata)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner = User(id=uuid.uuid4(), username="uploader", hashed_password="unused", role="pathologist")
    other = User(id=uuid.uuid4(), username="other-uploader", hashed_password="unused", role="pathologist")
    admin = User(id=uuid.uuid4(), username="admin", hashed_password="unused", role="admin")
    async with sessions() as db:
        db.add_all([owner, other, admin])
        db.add(DataGroup(group_id="g", name="Images", data_type="patch", task_type="patch_classification", aggregation_level="file"))
        for identity, user, public in [
            ("own-private", owner, False), ("own-public", owner, True),
            ("other-public", other, True), ("other-private", other, False),
            ("other-granted", other, False),
        ]:
            db.add(Dataset(dataset_id=identity, name=identity, data_type="patch", aggregation_level="file", tasks=[DatasetTask(task_type="patch_classification")], user_id=str(user.id), is_public=public))
            db.add(DatasetStats(dataset_id=identity, file_count=1, split_train_count=1))
        db.add(Workspace(workspace_id="limited", user_id=str(owner.id), name="Subset", dataset_ids=["own-public", "other-public", "other-granted"]))
        await db.commit()

    current = {"user": owner}
    async def get_db():
        async with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(wsi.router)
    app.dependency_overrides[wsi.current_active_user] = lambda: current["user"]
    app.dependency_overrides[wsi.get_db] = get_db
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        yield client, current, admin
    await engine.dispose()


async def test_upload_choices_exclude_other_public_and_granted_datasets_before_paging(upload_api):
    client, _, _ = upload_api
    first = await client.get("/wsi/datasets", params={"purpose": "upload", "page_size": 1})
    second = await client.get("/wsi/datasets", params={"purpose": "upload", "page_size": 1, "page": 2})
    assert first.status_code == second.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 2
    assert {page.json()["items"][0]["dataset_id"] for page in [first, second]} == {"own-private", "own-public"}
    assert all("username" not in page.json()["items"][0] for page in [first, second])
    search = await client.get("/wsi/datasets", params={"purpose": "upload", "search": "other"})
    assert search.json()["items"] == []
    assert search.json()["total"] == 0
    public = await client.get("/wsi/datasets", params={"purpose": "upload", "is_public": "true"})
    assert [item["dataset_id"] for item in public.json()["items"]] == ["own-public"]


async def test_upload_scope_intersects_workspace_and_checks_direct_selection(upload_api):
    client, _, _ = upload_api
    headers = {"X-Workspace-ID": "limited"}
    response = await client.get("/wsi/datasets?purpose=upload", headers=headers)
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["dataset_id"] == "own-public"
    for identity in ["other-public", "other-granted", "other-private"]:
        assert (await client.get(f"/wsi/datasets/{identity}?purpose=upload")).status_code == 403
    assert (await client.get("/wsi/datasets/own-private?purpose=upload", headers=headers)).status_code == 403
    detail = await client.get("/wsi/datasets/own-public?purpose=upload", headers=headers)
    assert detail.status_code == 200
    assert "username" not in detail.json()


async def test_admin_sees_all_upload_choices_and_owner_display_field(upload_api):
    client, current, admin = upload_api
    current["user"] = admin
    response = await client.get("/wsi/datasets?purpose=upload")
    assert response.status_code == 200
    assert response.json()["total"] == 5
    assert all("username" in item for item in response.json()["items"])
    assert (await client.get("/wsi/datasets/other-private?purpose=upload")).status_code == 200


async def test_browse_access_distinguishes_private_and_public(upload_api):
    client, _, _ = upload_api
    response = await client.get("/wsi/datasets")
    assert response.status_code == 200
    assert {item["dataset_id"] for item in response.json()["items"]} == {
        "own-private", "own-public", "other-public",
    }
    assert (await client.get("/wsi/datasets?purpose=invalid")).status_code == 422
