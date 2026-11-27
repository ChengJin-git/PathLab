"""Inspection responsiveness, real file checks, cancellation and cross-process admission."""

import asyncio
import fcntl
import multiprocessing
from types import SimpleNamespace
import pytest
from backend.storage import inspection_jobs as jobs
from gateway.routes import storage_inspections as routes


@pytest.fixture
def root(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs.Config, "get_uploads_dir", lambda: tmp_path)
    return tmp_path


async def test_duplicate_burst_is_one_scan_with_real_progress_and_cooldown(root):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def run(progress):
        calls.append(1)
        progress.update(7, 20, "external-health", force=True)
        started.set()
        await release.wait()
        return {"checked": 20}

    responses = await asyncio.gather(
        *(jobs.start("external-health", "", run) for _ in range(20))
    )
    await started.wait()
    assert len(calls) == 1 and len({item["id"] for item in responses}) == 1
    status = jobs.status("external-health")
    assert status["processed"] == 7 and status["total"] == 20
    release.set()
    await asyncio.gather(*list(jobs._tasks))
    assert jobs.status("external-health", result=True)["result"] == {"checked": 20}
    reused = await jobs.start("external-health", "", run)
    assert reused["reused"] and len(calls) == 1


def hold_lock(path, ready, release):
    with open(path, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ready.set()
        release.wait(60)


async def test_second_process_reuses_lock_and_interrupted_job_is_retryable(root):
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    path = jobs.directory() / (jobs.key("orphaned") + ".lock")
    jobs.write(
        path.with_suffix(".json"),
        {"id": "held", "kind": "orphaned", "status": "running"},
    )
    child = context.Process(target=hold_lock, args=(str(path), ready, release))
    child.start()
    assert await asyncio.to_thread(ready.wait, 30)

    async def unexpected(_):
        raise AssertionError("duplicate scan")

    try:
        assert (await jobs.start("orphaned", "", unexpected))["id"] == "held"
        assert jobs.status("orphaned")["status"] == "running"
    finally:
        release.set()
        await asyncio.to_thread(child.join, 5)
    assert jobs.status("orphaned")["status"] == "interrupted"

    async def run(progress):
        return {"ok": True}

    result = await jobs.start("orphaned", "", run)
    assert result["id"] != "held"
    await asyncio.gather(*list(jobs._tasks))


async def test_heavy_scans_serialize_and_cancel_waiting_job(root):
    started = asyncio.Event()
    release = asyncio.Event()
    second = []

    async def first(progress):
        started.set()
        await release.wait()
        return {}

    async def other(progress):
        second.append(True)
        return {}

    await jobs.start("orphaned", "", first)
    await started.wait()
    await jobs.start("external-health", "", other)
    assert jobs.status("external-health")["status"] == "queued"
    jobs.cancel("external-health")
    release.set()
    await asyncio.gather(*list(jobs._tasks))
    assert not second and jobs.status("external-health")["status"] == "cancelled"


def test_health_checks_real_files_and_associated_assets(root):
    (root / "slide.mrxs").write_bytes(b"1")
    (root / "slide").mkdir()
    (root / "ok.tmap").write_bytes(b"2")
    (root / "patch.png").write_bytes(b"3")
    items = [
        {"wsi_id": str(i), "wsi_path": str(root / name), "associated_files": associated}
        for i, (name, associated) in enumerate(
            [
                ("slide.mrxs", {}),
                (
                    "ok.tmap",
                    {"format_type": "tmap", "dt_files": [str(root / "missing.dt1")]},
                ),
                ("patch.png", None),
                ("gone.svs", None),
            ]
        )
    ]
    calls = []
    progress = SimpleNamespace(update=lambda *args, **kw: calls.append(args))
    ok, bad = routes.check_batch(items, progress, 0, 4)
    assert {item["wsi_id"] for item in ok} == {"0", "2"}
    assert {item["wsi_id"] for item in bad} == {"1", "3"}
    assert calls[-1][0] == 4


async def test_cancellation_does_not_report_false_completed_results(root):
    started = asyncio.Event()
    release = asyncio.Event()

    async def run(progress):
        started.set()
        await release.wait()
        progress.update(1, 2, "check", force=True)
        return {"bad": "must not publish"}

    await jobs.start("external-health", "", run)
    await started.wait()
    jobs.cancel("external-health")
    release.set()
    await asyncio.gather(*list(jobs._tasks))
    value = jobs.status("external-health", result=True)
    assert value["status"] == "cancelled" and "result" not in value


async def test_directory_admission_uses_real_database_and_reuses_active_job(root):
    from sqlalchemy import MetaData,select
    from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
    from backend.database.models import StorageTask
    from gateway.routes import storage_scan
    from gateway.models import StartScanDirectoryTaskRequest
    from fastapi import BackgroundTasks
    engine=create_async_engine('sqlite+aiosqlite://');metadata=MetaData();StorageTask.__table__.to_metadata(metadata)
    async with engine.begin() as conn:await conn.run_sync(metadata.create_all)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    request=StartScanDirectoryTaskRequest(directory_path=str(root),task_type='patch_classification',page_size=100)
    async with sessions() as db:
        first=BackgroundTasks();second=BackgroundTasks()
        a=await storage_scan.start_scan_directory_task(request,first,SimpleNamespace(id='a'),db)
        b=await storage_scan.start_scan_directory_task(request,second,SimpleNamespace(id='a'),db)
        assert a['task_id']==b['task_id'] and b['reused']
        assert len(first.tasks)==1 and len(second.tasks)==0
        assert len((await db.scalars(select(StorageTask))).all())==1
    await engine.dispose()
