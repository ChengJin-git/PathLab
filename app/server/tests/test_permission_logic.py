"""Dataset visibility: owners and admins manage, public datasets are readable by everyone."""

from uuid import uuid4

import pytest
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.auth.dependencies import (
    check_dataset_write_permission,
    check_dataset_access_permission,
    get_permitted_dataset_ids,
    check_wsi_access_permission,
)
from backend.auth.models import User
from backend.database.models import Dataset, DatasetTask
from backend.database.repositories.annotation import (
    SegmentationAnnotationRepository,
)
from backend.services.dataset_access import can_manage_dataset
from backend.services.workspaces import WorkspaceScope


@pytest.fixture
async def access_db():
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    for model in [Dataset, DatasetTask, User]:
        model.__table__.to_metadata(metadata)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        reader = User(id=uuid4(), username="reader", hashed_password="fixture", role="pathologist", is_active=True)
        admin = User(id=uuid4(), username="admin", hashed_password="fixture", role="admin", is_active=True)
        db.add_all([reader, admin])
        for identity, owner, public, parent in [
            ("own", str(reader.id), False, None),
            ("public", "owner", True, None),
            ("private", "owner", False, None),
            ("child", "owner", False, "public"),
        ]:
            db.add(
                Dataset(
                    dataset_id=identity,
                    name=identity,
                    user_id=owner,
                    is_public=public,
                    data_type="wsi",
                    aggregation_level="file",
                    parent_dataset_id=parent,
                )
            )
        await db.commit()
        yield db, reader, admin
    await engine.dispose()


async def test_readers_see_owned_and_public_datasets_in_every_scope(access_db):
    db, reader, _ = access_db
    expected = {"own", "public"}
    assert set(await get_permitted_dataset_ids(reader, db)) == expected
    assert set((await db.scalars(WorkspaceScope().datasets(reader))).all()) == expected
    for identity in ["own", "public", "private", "child"]:
        dataset = await db.scalar(select(Dataset).where(Dataset.dataset_id == identity))
        visible = identity in expected
        assert await check_dataset_access_permission(reader, identity, dataset.user_id, db) == visible
        assert await check_wsi_access_permission(reader, identity, "owner", db) == visible


async def test_only_owners_and_admins_write_or_manage(access_db):
    db, reader, admin = access_db
    assert await check_dataset_write_permission(reader, "own", str(reader.id), db)
    assert not await check_dataset_write_permission(reader, "public", "owner", db)
    assert await check_dataset_write_permission(admin, "private", "owner", db)
    assert await get_permitted_dataset_ids(admin, db) is None
    public = await db.scalar(select(Dataset).where(Dataset.dataset_id == "public"))
    own = await db.scalar(select(Dataset).where(Dataset.dataset_id == "own"))
    assert not await can_manage_dataset(db, reader, public)
    assert await can_manage_dataset(db, reader, own)
    assert await can_manage_dataset(db, admin, public)


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class DB:
    def __init__(self, value):
        self.value = value

    async def execute(self, _statement):
        return Result(self.value)


async def test_upsert_raises_on_cross_user_draft_conflict():
    with pytest.raises(ValueError,match='viewer regions'):
        await SegmentationAnnotationRepository.upsert(
            DB("owner-1"),
            annotation_id="draft-1",
            user_id="owner-2",
            annotations={},
            source_dataset_id="ds-1",
            status="draft",
        )
