"""Upload metadata/duplicates and bounded incremental dataset statistics."""

import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import MetaData, select, event, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.database.models import Dataset, DatasetTask, DataGroup, DatasetStats, WSISlide
from backend.database.repositories.dataset_stats import DatasetStatsRepository
from gateway.models import CheckUploadDuplicates, UploadByPathRequest
from gateway.routes import wsi


@pytest.fixture
async def database():
    url = os.getenv("PATHLAB_TEST_POSTGRES_URL")
    schema = "upload_" + uuid.uuid4().hex
    admin = None
    if url:
        admin = create_async_engine(url)
        async with admin.begin() as conn:
            await conn.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_async_engine(
            url, connect_args={"server_settings": {"search_path": schema}}
        )
    else:
        engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    for cls in [Dataset, DatasetTask, DataGroup, DatasetStats, WSISlide]:
        cls.__table__.to_metadata(metadata)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    statements = []
    event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        lambda c, cur, sql, p, ctx, m: statements.append(sql),
    )
    async with sessions() as db:
        db.add(
            DataGroup(
                group_id="g",
                name="Cases",
                data_type="wsi",
                task_type="wsi_classification",
                aggregation_level="case",
            )
        )
        db.add_all(
            [
                Dataset(
                    dataset_id=identity, name=identity, data_type="wsi", aggregation_level="case",
                    tasks=[DatasetTask(task_type="wsi_classification")], user_id="owner"
                )
                for identity in ["a", "b"]
            ]
        )
        await db.commit()
    yield sessions, statements
    await engine.dispose()
    if admin:
        async with admin.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()


async def add(sessions, identity, case, split, size=10):
    async with sessions() as db:
        fields = dict(
            wsi_id=identity,
            case_id=case,
            split=split,
            file_size=size,
            dataset_id="a",
            wsi_path="/fixture/" + identity,
            original_filename=identity + ".svs",
        )
        db.add(WSISlide(**fields))
        await db.flush()
        await DatasetStatsRepository.record_upload(db, "a", fields)
        await db.commit()


async def test_upload_counters_preserve_case_units_without_full_rescan(database):
    sessions, statements = database
    await add(sessions, "one", "patient", "train")
    statements.clear()
    await add(sessions, "two", "patient", "train", 20)
    await add(sessions, "three", "other", "val", 30)
    assert not any(
        "count(" in sql.lower() or "sum(" in sql.lower() for sql in statements
    )
    async with sessions() as db:
        stats = await db.get(DatasetStats, "a")
        assert (
            stats.file_count,
            stats.total_size,
            stats.split_train_count,
            stats.split_val_count,
        ) == (3, 60, 1, 1)
    with pytest.raises(ValueError, match="different"):
        await add(sessions, "leak", "patient", "test")
    async with sessions() as db:
        assert (
            await db.scalar(select(WSISlide).where(WSISlide.wsi_id == "leak")) is None
        )


async def test_duplicates_are_target_dataset_scoped_and_write_authorized(
    database, monkeypatch
):
    sessions, _ = database
    await add(sessions, "one", "patient", "train")
    monkeypatch.setattr(
        wsi,
        "get_dataset_with_access",
        AsyncMock(
            return_value=SimpleNamespace(user_id="owner", parent_dataset_id=None)
        ),
    )
    check = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "backend.auth.dependencies.check_dataset_write_permission", check
    )
    body = CheckUploadDuplicates(dataset_id="b", filenames=["one.svs"])
    async with sessions() as db:
        assert await wsi.check_duplicate_filenames(body, SimpleNamespace(), db) == {
            "duplicates": [],
            "new": ["one.svs"],
        }
        body.dataset_id = "a"
        assert (await wsi.check_duplicate_filenames(body, SimpleNamespace(), db))[
            "duplicates"
        ] == ["one.svs"]
        check.return_value = False
        with pytest.raises(HTTPException):
            await wsi.check_duplicate_filenames(body, SimpleNamespace(), db)


async def test_real_multipart_upload_preserves_metadata_and_rejects_only_same_dataset_duplicates(database, monkeypatch, tmp_path):
    import io
    import httpx
    from PIL import Image
    from fastapi import FastAPI
    from gateway.routes import wsi_upload
    from unittest.mock import Mock
    sessions,_=database
    async with sessions() as db:
        db.add(DataGroup(group_id='patch',name='Patch',data_type='patch',task_type='patch_classification',aggregation_level='file'))
        db.add_all([Dataset(dataset_id=d,name=d,data_type='patch',aggregation_level='file',tasks=[DatasetTask(task_type='patch_classification')],user_id='owner') for d in ['images','other-images']])
        await db.commit()
    app=FastAPI();app.include_router(wsi_upload.router)
    async def get_db():
        async with sessions() as db:yield db
    app.dependency_overrides[wsi_upload.get_db]=get_db
    app.dependency_overrides[wsi_upload.current_active_user]=lambda:SimpleNamespace(id='owner',role='pathologist',is_admin=lambda:False)
    monkeypatch.setattr(wsi_upload.Config,'get_uploads_dir',lambda:tmp_path)
    monkeypatch.setattr(wsi_upload,'invalidate_chat_context',AsyncMock())
    monkeypatch.setattr(wsi_upload.storage_manager,'save_wsi_metadata',Mock())
    image=io.BytesIO();Image.new('RGB',(16,16),'white').save(image,format='PNG')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
        metadata={'dataset_id':'images','task_type':'patch_classification','label':'tumor','case_id':'original-patient','split':'val','age':'0'}
        response=await client.post('/wsi/upload/file',data=metadata,files={'file':('sample.png',image.getvalue(),'image/png')})
        assert response.status_code==200,response.text
        identity=response.json()['wsi_id']
        retry=await client.post('/wsi/upload/file',data={**metadata,'wsi_id':identity},files={'file':('sample.png',image.getvalue(),'image/png')})
        assert retry.status_code==200 and retry.json()['wsi_id']==identity
        async with sessions() as db:
            row=await db.scalar(select(WSISlide).where(WSISlide.wsi_id==identity))
            assert (row.case_id,row.split,row.age,row.label)==('original-patient','val',0,'tumor')
            stats=await db.get(DatasetStats,'images')
            assert stats.file_count==1 and stats.split_val_count==1
        duplicate=await client.post('/wsi/upload/file',data=metadata,files={'file':('sample.png',image.getvalue(),'image/png')})
        assert duplicate.status_code==409
        other=await client.post('/wsi/upload/file',data={**metadata,'dataset_id':'other-images'},files={'file':('sample.png',image.getvalue(),'image/png')})
        assert other.status_code==200,other.text


def test_upload_split_is_a_validated_contract():
    assert (
        UploadByPathRequest(wsi_path="/fixture/a.svs", split="train").split == "train"
    )
    with pytest.raises(ValueError):
        UploadByPathRequest(wsi_path="/fixture/a.svs", split="random")
    with pytest.raises(ValueError):
        CheckUploadDuplicates(dataset_id="a", filenames=["x"] * 1001)


@pytest.mark.skipif(
    not os.getenv("PATHLAB_TEST_POSTGRES_URL"), reason="PostgreSQL concurrent locking"
)
async def test_concurrent_uploads_increment_exactly_once_without_foreign_key_deadlock(
    database,
):
    import asyncio

    sessions, _ = database
    await asyncio.wait_for(
        asyncio.gather(*(add(sessions, str(i), "same", "train") for i in range(12))), 15
    )
    async with sessions() as db:
        stats = await db.get(DatasetStats, "a")
        assert (stats.file_count, stats.total_size, stats.split_train_count) == (
            12,
            120,
            1,
        )
