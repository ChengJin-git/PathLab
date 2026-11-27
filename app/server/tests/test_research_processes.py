"""Real-process deletion: detached descendants, queued work and PID ownership."""
# ruff: noqa: F811 -- pytest injects shared imported fixtures by argument name.

import asyncio
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import psutil
import pytest
from sqlalchemy import select

from backend.autoresearch.engine import jobs, processes, store
from backend.database.models import AutoResearchExperiment, ResearchJob
from backend.services import chat_deletion as service
from test_chat_deletion import fixture as fixture, schedule_cancellation
from test_task_queue_patching import queue as queue

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux process-tree integration')


async def wait_for_cancellation():
    if service._cancellations:
        await asyncio.wait_for(asyncio.gather(*list(service._cancellations.values())), 4)


def live(pid):
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


async def start_tree():
    code = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)'], start_new_session=True); print(p.pid,flush=True); time.sleep(120)"
    parent = await asyncio.create_subprocess_exec(sys.executable, '-c', code, stdout=asyncio.subprocess.PIPE, start_new_session=True)
    child = int(await asyncio.wait_for(parent.stdout.readline(), 5))
    return parent, child


async def test_delete_immediately_stops_real_agent_job_download_and_detached_children(fixture, monkeypatch):
    f = fixture
    monkeypatch.setattr(service, 'schedule_cancellation', schedule_cancellation)
    @asynccontextmanager
    async def database():
        async with f.db() as db: yield db
    for module in [jobs, processes, store]: monkeypatch.setattr(module, 'safe_session', database)
    # Durable cancellation and local stop must work while Redis is unavailable.
    monkeypatch.setattr('backend.common.task_dispatch.publish_task_cancellation', AsyncMock(side_effect=ConnectionError('offline')))
    paths = [f.root / 'runs/run/process.json',
             service.Config.get_autoresearch_dir() / 'runtime/r/process.json',
             f.root / 'downloads/download.process.json']
    trees = []
    unrelated = await asyncio.create_subprocess_exec(sys.executable, '-c', 'import time; time.sleep(120)', start_new_session=True)
    try:
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            parent, child = await start_tree()
            trees.append((parent, child))
            processes.record(path, parent.pid)
        async with f.db() as db:
            (await db.get(ResearchJob, 'run')).status = 'running'
            db.add(ResearchJob(job_id='queued', session_id='r', kind='experiment', status='queued'))
            db.add(ResearchJob(job_id='download', session_id='r', kind='download', status='running'))
            await db.commit()
        start = time.monotonic()
        async with f.db() as db:
            await service.request_deletion(db, 'chat', f.user)
        assert time.monotonic() - start < 4
        await wait_for_cancellation()
        for parent, child in trees:
            await asyncio.wait_for(parent.wait(), 2)
            assert not live(parent.pid) and not live(child)
        assert live(unrelated.pid)
        async with f.db() as db:
            assert (await db.get(ResearchJob, 'queued')).status == 'cancelled'
            assert (await db.get(ResearchJob, 'run')).status == 'cancelling'
        execute = AsyncMock()
        monkeypatch.setattr(jobs, 'execute_experiment', execute)
        await jobs.run(task_id='queued')
        execute.assert_not_awaited()
        await store.job_update('run', 'completed', {'metrics': {'fake': 1}})
        await store.experiment_update('r', 'run', status='completed')
        async with f.db() as db:
            assert (await db.get(ResearchJob, 'run')).status == 'cancelling'
            assert (await db.scalar(select(AutoResearchExperiment))).status == 'cancelling'
        with pytest.raises(asyncio.CancelledError):
            await processes.spawn_owned('r', f.root / 'new.json', [sys.executable, '-c', 'pass'])
    finally:
        await processes.terminate(unrelated.pid)
        await unrelated.wait()
        for parent, child in trees:
            await processes.terminate(parent.pid)
            if live(child): await processes.terminate(child)
            await parent.wait()


async def test_pid_reuse_record_never_kills_unrelated_process(tmp_path):
    process = await asyncio.create_subprocess_exec(sys.executable, '-c', 'import time; time.sleep(120)', start_new_session=True)
    path = tmp_path / 'process.json'
    path.write_text(json.dumps({'pid': process.pid, 'start_ticks': 'different-birth'}))
    try:
        await processes.stop(path)
        assert live(process.pid)
    finally:
        await processes.terminate(process.pid)
        await process.wait()


async def test_deletion_releases_gpu_lease_and_cancels_waiter_before_dispatch(fixture, queue, monkeypatch):
    from backend.common.task_types import TaskType
    f = fixture
    monkeypatch.setattr(service, 'schedule_cancellation', schedule_cancellation)
    @asynccontextmanager
    async def database():
        async with f.db() as db: yield db
    for module in [store, jobs, processes]: monkeypatch.setattr(module, 'safe_session', database)
    queue._gpu.limit = 1
    monkeypatch.setattr('backend.common.task_dispatch.publish_task_cancellation', queue.cancel_task)
    async with f.db() as db:
        (await db.get(ResearchJob, 'run')).status = 'running'
        db.add(ResearchJob(job_id='waiter', session_id='r', kind='experiment', status='queued'))
        await db.commit()
    started = asyncio.Event()
    process_path = f.root / 'runs/run/process.json'
    async def running(**kwargs):
        process = await processes.spawn_owned('r', process_path,
            [sys.executable, '-c', 'import time; time.sleep(120)'], job_id='run')
        queue.bind_gpu_process('run', process.pid, process_group=True)
        started.set()
        try:
            await process.wait()
        finally:
            await processes.stop(process_path)
            await process.wait()
            await store.job_update('run', 'cancelled')
    execute = AsyncMock()
    monkeypatch.setattr(jobs, 'execute_experiment', execute)
    resource = {'operation': 'custom', 'peak_vram_mb': 4000}
    await queue.start()
    try:
        await queue.submit('run', TaskType.RESEARCH, running, resources=resource)
        await asyncio.wait_for(started.wait(), 3)
        await queue.submit('waiter', TaskType.RESEARCH, jobs.run, resources=resource)
        await asyncio.sleep(.03)
        assert queue._gpu.leases
        async with f.db() as db:
            await service.request_deletion(db, 'chat', f.user)
        await wait_for_cancellation()
        await queue.join()
        assert not queue._gpu.leases and not queue._gpu.pending
        execute.assert_not_awaited()
        assert not live(json.loads(process_path.read_text())['pid'])
    finally:
        await queue.stop()


async def test_failed_pid_publication_reaps_spawned_process(fixture, monkeypatch):
    f = fixture
    @asynccontextmanager
    async def database():
        async with f.db() as db: yield db
    monkeypatch.setattr(processes, 'safe_session', database)
    spawned = []
    def broken_record(path, pid, **kwargs):
        spawned.append(pid)
        raise OSError('disk full')
    monkeypatch.setattr(processes, 'record', broken_record)
    with pytest.raises(OSError, match='disk full'):
        await processes.spawn_owned('r', f.root / 'process.json', [sys.executable, '-c', 'import time; time.sleep(120)'])
    assert spawned and not live(spawned[0])


@pytest.mark.skipif(not os.getenv('PATHLAB_TEST_POSTGRES_URL'), reason='Requires PostgreSQL row-lock semantics')
@pytest.mark.parametrize('job_id', [None, 'run'])
async def test_delete_serializes_with_actual_spawn_and_pid_publication(fixture, monkeypatch, job_id):
    f = fixture
    monkeypatch.setattr(service, 'schedule_cancellation', schedule_cancellation)
    @asynccontextmanager
    async def database():
        async with f.db() as db: yield db
    monkeypatch.setattr(processes, 'safe_session', database)
    monkeypatch.setattr('backend.common.task_dispatch.publish_task_cancellation', AsyncMock())
    async with f.db() as db:
        (await db.get(ResearchJob, 'run')).status = 'running'
        await db.commit()
    entered, release = asyncio.Event(), asyncio.Event()
    create = asyncio.create_subprocess_exec
    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await create(*args, **kwargs)
    monkeypatch.setattr(processes.asyncio, 'create_subprocess_exec', delayed)
    path = (f.root / 'runs/run/process.json') if job_id else (service.Config.get_autoresearch_dir() / 'runtime/r/process.json')
    spawning = asyncio.create_task(processes.spawn_owned('r', path, [sys.executable, '-c', 'import time; time.sleep(120)'], job_id=job_id))
    await asyncio.wait_for(entered.wait(), 3)
    async def delete():
        async with f.db() as db: return await service.request_deletion(db, 'chat', f.user)
    deleting = asyncio.create_task(delete())
    try:
        # Deletion must wait for the held session row, then see the published PID.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(deleting), .1)
        release.set()
        process = await asyncio.wait_for(spawning, 4)
        await asyncio.wait_for(deleting, 4)
        await wait_for_cancellation()
        await asyncio.wait_for(process.wait(), 2)
        assert not live(process.pid)
    finally:
        release.set()
        await asyncio.gather(spawning, deleting, return_exceptions=True)
        await processes.stop(path)


@pytest.mark.skipif(not os.getenv('PATHLAB_TEST_POSTGRES_URL'), reason='Requires PostgreSQL concurrency')
async def test_slow_source_copy_cannot_delay_deletion_or_publish_after_it(fixture, monkeypatch):
    import threading
    f = fixture
    @asynccontextmanager
    async def database():
        async with f.db() as db: yield db
    for module in [jobs, store]: monkeypatch.setattr(module, 'safe_session', database)
    (f.root / 'train.py').write_text('print("fixture")')
    entered, release = threading.Event(), threading.Event()
    copy = jobs.shutil.copy2
    def slow_copy(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return copy(*args, **kwargs)
    monkeypatch.setattr(jobs.shutil, 'copy2', slow_copy)
    publish = AsyncMock()
    monkeypatch.setattr(jobs, 'enqueue_task_descriptor', publish)
    task = asyncio.create_task(jobs.submit('r', 'experiment', {'name':'race', 'device':'cpu', 'command':['python','train.py']}))
    assert await asyncio.to_thread(entered.wait, 3)
    try:
        async with f.db() as db:
            await asyncio.wait_for(service.request_deletion(db, 'chat', f.user), 2)
        release.set()
        with pytest.raises(ValueError, match='paused or stopped'):
            await task
        publish.assert_not_awaited()
        assert not list(service.Config.get_autoresearch_dir().joinpath('staging').iterdir())
        assert {p.name for p in (f.root/'runs').iterdir()} == {'run'}
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.skipif(os.getenv('PATHLAB_TEST_APPTAINER') != '1', reason='Explicit real sandbox integration')
async def test_staged_snapshot_executes_in_real_sandbox_and_survives_agent_pause(fixture, monkeypatch):
    from backend.autoresearch.engine import file_catalog
    f = fixture
    @asynccontextmanager
    async def database():
        async with f.db() as db: yield db
    for module in [jobs, store, processes]: monkeypatch.setattr(module, 'safe_session', database)
    monkeypatch.setattr(jobs, 'enqueue_task_descriptor', AsyncMock())
    monkeypatch.setattr(file_catalog, 'index_tree', AsyncMock(return_value={'items': [], 'count':0, 'truncated':False}))
    (f.root/'train.py').write_text("import json,os; from pathlib import Path; Path(os.environ['OUTPUT_DIR'],'metrics.json').write_text(json.dumps({'val': {'accuracy': .75}}))\ntry:Path('not-writable').write_text('bad');raise AssertionError('source is writable')\nexcept OSError:pass\n")
    submitted = await jobs.submit('r', 'experiment', {'device':'cpu','name':'sandbox fixture','command':['python','train.py']})
    # Later agent edits must not mutate this execution's source snapshot.
    (f.root/'train.py').write_text('raise RuntimeError("workspace version must not execute")')
    await store.update('r', status='paused')
    async with f.db() as db:
        job = await db.get(ResearchJob, submitted['job_id'])
        job.status='running'
        await db.commit()
    result = await jobs.execute_experiment(await store.get('r'), job, 'cpu')
    assert result['metrics'] == {'val.accuracy': .75}
    assert not (f.root/'runs'/job.job_id/'process.json').exists()
