"""Outbox transaction, restart retry, stale selections and cache deregistration."""

from contextlib import asynccontextmanager
import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import MetaData, select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from backend.database.models import (
    StorageTask,
    FeatureArtifact,
    WSISlide,
    Dataset,
    DatasetTask,
)
from backend.storage import deletion
from backend.storage.inventory import Inventory
from backend.storage.references import References


@pytest.fixture
async def fixture(tmp_path, monkeypatch):
    url = os.environ.get("PATHLAB_TEST_POSTGRES_URL")
    schema = "storage_test_" + uuid.uuid4().hex
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
    if url:
        from backend.database.models import Base
        import backend.auth.models  # noqa: F401 - register authentication tables

        for table in Base.metadata.tables.values():
            table.to_metadata(metadata)
    else:
        for model in (Dataset, DatasetTask, WSISlide, FeatureArtifact, StorageTask):
            model.__table__.to_metadata(metadata)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def safe():
        async with sessions() as db:
            yield db

    monkeypatch.setattr(deletion, "safe_session", safe)

    @asynccontextmanager
    async def window(*args):
        async with sessions() as db:
            yield References(), db, None

    if not url:
        monkeypatch.setattr(deletion, "deletion_window", window)
    monkeypatch.setattr(
        deletion.Config, "get_uploads_dir", classmethod(lambda cls: tmp_path)
    )
    monkeypatch.setattr("backend.storage.inventory.GRACE_SECONDS", -1)
    refs = References()
    monkeypatch.setattr(
        deletion, "references", AsyncMock(side_effect=lambda *a, **k: refs)
    )
    redis = SimpleNamespace(
        get=AsyncMock(return_value=json.dumps({"running_count": 0}))
    )
    monkeypatch.setattr("backend.common.redis_client.get_redis", lambda: redis)
    yield SimpleNamespace(root=tmp_path, db=sessions, refs=refs)
    await engine.dispose()
    if admin:
        async with admin.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()


async def test_outbox_rolls_back_with_object_transaction_and_coalesces(fixture):
    f = fixture
    async with f.db() as db:
        await deletion.enqueue(db, "owner", paths=["models/a"])
        await db.rollback()
    async with f.db() as db:
        assert not (await db.scalars(select(StorageTask))).all()
        first = await deletion.enqueue(db, "owner", paths=["models/a"])
        second = await deletion.enqueue(db, "owner", paths=["models/b"])
        assert first.task_id == second.task_id
        await db.commit()
    async with f.db() as db:
        task = await db.scalar(select(StorageTask))
        assert set(task.params["paths"]) == {"models/a", "models/b"}


async def test_failed_file_cleanup_retries_after_worker_recreation(
    fixture, monkeypatch
):
    f = fixture
    p = f.root / "models/orphan/weights.pth"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"weights")
    async with f.db() as db:
        task = await deletion.enqueue(db, "owner", paths=["models/orphan"])
        await db.commit()
    original = deletion.stage_directory
    monkeypatch.setattr(
        deletion, "stage_directory", lambda *a: (_ for _ in ()).throw(OSError("busy"))
    )
    await deletion.StorageQueue().run(task.task_id)
    assert p.exists()
    async with f.db() as db:
        saved = await db.scalar(select(StorageTask))
        assert saved.status == "failed"
        assert saved.params["paths"] == ["models/orphan"]
    monkeypatch.setattr(deletion, "stage_directory", original)
    await deletion.StorageQueue().run(task.task_id)
    assert not p.exists()
    async with f.db() as db:
        saved = await db.scalar(select(StorageTask))
        assert saved.status == "completed"
        assert saved.results["deleted"] == 1


async def test_selection_rechecks_references_and_file_fingerprint(fixture):
    f = fixture
    for name in ("orphan", "new-reference", "changed"):
        p = f.root / f"models/{name}/weights"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"original")
    inventory = Inventory(f.root)
    summary = inventory.scan(f.refs)
    async with f.db() as db:
        task = await deletion.enqueue(
            db,
            "owner",
            task_type="storage_cleanup",
            selection={
                "generation": summary["generation"],
                "scope": "all",
                "state": "orphaned",
                "category": "models",
            },
        )
        await db.commit()
    f.refs.owners.add("new-reference")
    (f.root / "models/changed/weights").write_bytes(b"changed content")
    await deletion.StorageQueue().run(task.task_id)
    assert not (f.root / "models/orphan").exists()
    assert (f.root / "models/new-reference/weights").exists()
    assert (f.root / "models/changed/weights").exists()
    async with f.db() as db:
        saved = await db.scalar(select(StorageTask))
        assert saved.status == "completed"
        assert saved.results["deleted"] == 1 and saved.results["skipped"] == 2


async def test_active_tasks_prevent_cleanup(fixture):
    f = fixture
    p = f.root / "models/orphan"
    p.mkdir(parents=True)
    f.refs.active.add("training")
    async with f.db() as db:
        task = await deletion.enqueue(db, "owner", paths=["models/orphan"])
        await db.commit()
    await deletion.StorageQueue().run(task.task_id)
    assert p.exists()
    async with f.db() as db:
        assert (await db.scalar(select(StorageTask))).status == "failed"


@pytest.mark.parametrize("scope", ["selected", "all"])
async def test_bulk_selection_respects_page_or_all_filtered_with_exclusions(
    fixture, scope
):
    f = fixture
    for i in range(65):
        path = f.root / f"models/orphan_{i:03d}/weights"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"weights")
    other = f.root / "training/other/input"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"other category")
    inventory = Inventory(f.root)
    snapshot = inventory.scan(f.refs)
    first = inventory.page("models", "orphaned")
    assert first["total"] == 65 and len(first["items"]) == 50
    selected = [item["id"] for item in first["items"]]
    selection = {
        "generation": snapshot["generation"],
        "scope": scope,
        "category": "models",
        "state": "orphaned",
    }
    selection.update(
        {"ids": selected} if scope == "selected" else {"excluded_ids": [selected[0]]}
    )
    async with f.db() as db:
        task = await deletion.enqueue(
            db, "owner", task_type="storage_cleanup", selection=selection
        )
        await db.commit()
    await deletion.StorageQueue().run(task.task_id)
    remaining = list((f.root / "models").glob("*/weights"))
    assert len(remaining) == (15 if scope == "selected" else 1)
    if scope == "all":
        assert (f.root / first["items"][0]["path"] / "weights").exists()
    assert other.exists()
    async with f.db() as db:
        saved = await db.scalar(select(StorageTask))
        assert saved.status == "completed"
        assert saved.results["deleted"] == (50 if scope == "selected" else 64)


async def test_last_consumer_deletion_revisits_retained_artifacts(fixture):
    f = fixture
    p = f.root / "models/model_shared/weights"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"model")
    f.refs.owners.add("model_shared")
    async with f.db() as db:
        first = await deletion.enqueue(db, "owner", paths=["models/model_shared"])
        await db.commit()
    await deletion.StorageQueue().run(first.task_id)
    assert p.exists()
    f.refs.owners.clear()
    async with f.db() as db:
        second = await deletion.enqueue(
            db, "owner", paths=["analysis-workbench/deleted-analysis"]
        )
        await db.commit()
    await deletion.StorageQueue().run(second.task_id)
    assert not p.exists()


async def test_cache_cleanup_deregisters_feature_and_clears_slide_flag(fixture):
    f = fixture
    identity = "wsi_0123456789abcdef"
    path = f.root / f"features/uni/hash/{identity}.pt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"feature")
    f.refs.image_ids.add(identity)
    async with f.db() as db:
        db.add(
            WSISlide(
                wsi_id=identity, wsi_path="/external/source.svs", feature_extracted=True
            )
        )
        await db.flush()
        db.add(
            FeatureArtifact(
                artifact_id="artifact",
                wsi_id=identity,
                model_id="uni",
                feature_path=str(path),
                feature_revision="1",
                rows=1,
                dimensions=1,
            )
        )
        await db.commit()
    inventory = Inventory(f.root)
    summary = inventory.scan(f.refs)
    async with f.db() as db:
        task = await deletion.enqueue(
            db,
            "owner",
            task_type="storage_cleanup",
            selection={
                "generation": summary["generation"],
                "scope": "all",
                "state": "cached",
                "category": "features",
            },
        )
        await db.commit()
    await deletion.StorageQueue().run(task.task_id)
    assert not path.exists()
    async with f.db() as db:
        assert await db.scalar(select(FeatureArtifact)) is None
        assert not await db.scalar(select(WSISlide.feature_extracted))


async def test_partial_directory_removal_retries_private_receipt(fixture, monkeypatch):
    f = fixture
    p = f.root / "models/model_crash/weights"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"model")
    async with f.db() as db:
        task = await deletion.enqueue(db, "owner", paths=["models/model_crash"])
        await db.commit()
    original = deletion.purge_directory
    monkeypatch.setattr(
        deletion,
        "purge_directory",
        lambda *_: (_ for _ in ()).throw(OSError("interrupted purge")),
    )
    await deletion.StorageQueue().run(task.task_id)
    assert not p.exists()
    assert list((f.root / ".storage-inventory/trash" / task.task_id).glob("*/weights"))
    monkeypatch.setattr(deletion, "purge_directory", original)
    await deletion.StorageQueue().run(task.task_id)
    assert not (f.root / ".storage-inventory/trash" / task.task_id).exists()


async def test_cancelled_scan_keeps_previous_inventory(fixture):
    f = fixture
    path = f.root / "models/owned/weights"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"weights")
    inventory = Inventory(f.root)
    before = inventory.scan(f.refs)
    async with f.db() as db:
        task = await deletion.enqueue(db, "owner", task_type="storage_scan")
        task.status = "cancelled"
        await db.commit()
    await deletion.StorageQueue().run(task.task_id)
    assert inventory.summary()["generation"] == before["generation"]
    assert path.exists()


async def test_worker_shutdown_reschedules_scan_without_error_traceback(
    fixture, caplog, monkeypatch
):
    import sqlite3

    f = fixture
    async with f.db() as db:
        task = await deletion.enqueue(db, "owner", task_type="storage_scan")
        await db.commit()
    queue = deletion.StorageQueue()

    def interrupted(*args, **kwargs):
        queue.stopping.set()
        error = sqlite3.OperationalError("interrupted")
        error.sqlite_errorcode = sqlite3.SQLITE_INTERRUPT
        raise error

    monkeypatch.setattr(Inventory, "scan", interrupted)
    await queue.run(task.task_id)
    async with f.db() as db:
        saved = await db.scalar(
            select(StorageTask).where(StorageTask.task_id == task.task_id)
        )
        assert saved.status == "pending"
        assert saved.error_message is None
        assert saved.params["retry_after"] == 0
    assert not any(record.exc_info for record in caplog.records)
