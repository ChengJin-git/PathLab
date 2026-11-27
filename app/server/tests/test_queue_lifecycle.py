import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.common.queue_lifecycle import fifo_key, recover_fifo, interrupt_for_restart, is_restart_interruption, RESTART_INTERRUPTION


async def test_shared_recovery_runs_serially_in_persisted_fifo_order():
    rows = [SimpleNamespace(id=i, at=datetime(2026, 1, i, tzinfo=timezone.utc)) for i in (3, 1, 2)]
    restored = []
    async def restore(row):
        restored.append(row.id)
        await asyncio.sleep(0)
        restored.append(-row.id)
    await recover_fifo(rows, key=lambda row: fifo_key(row.at, row.id), restore=restore)
    assert restored == [1, -1, 2, -2, 3, -3]


async def test_worker_restart_is_distinct_from_user_cancellation():
    entered = [asyncio.Event(), asyncio.Event()]
    causes = {}
    async def job(index):
        entered[index].set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as error:
            causes[index] = is_restart_interruption(error)
            raise
    tasks = [asyncio.create_task(job(i)) for i in range(2)]
    await asyncio.gather(*(event.wait() for event in entered))
    tasks[0].cancel()
    await interrupt_for_restart(tasks)
    assert causes == {0: False, 1: True}


async def test_training_service_restart_keeps_task_resumable_and_user_cancel_wins(monkeypatch):
    from backend.ai import cancellation
    from backend.ai.routes import training
    task = SimpleNamespace(status='training')
    monkeypatch.setattr(training.TrainingTaskRepository, 'get_by_id', AsyncMock(return_value=task))
    update = AsyncMock()
    monkeypatch.setattr(training.TrainingTaskRepository, 'update_status', update)
    db = SimpleNamespace(commit=AsyncMock())
    try:
        await training.cancel_training_task('fixture', for_restart=True)
        await training._safe_update_status(db, 'fixture', 'cancelled', error_message='interrupted')
        assert update.call_args.args[2] == 'resuming'
        await training.cancel_training_task('fixture')
        await training.cancel_training_task('fixture', for_restart=True)
        await training._safe_update_status(db, 'fixture', 'cancelled', error_message='user cancelled')
        assert update.call_args.args[2] == 'cancelled'
    finally:
        cancellation.clear_cancellation('fixture')


@pytest.mark.parametrize('restart', [False, True])
async def test_research_job_shutdown_requeues_original_job_without_new_attempt(monkeypatch, restart):
    from backend.autoresearch.engine import jobs
    job = SimpleNamespace(job_id='original-job', session_id='session', status='queued', kind='experiment')
    session = SimpleNamespace(status='running', recovery_metadata={}, current_iteration=2)
    db = SimpleNamespace(get=AsyncMock(return_value=job), scalar=AsyncMock(return_value=session), commit=AsyncMock(), refresh=AsyncMock())
    @asynccontextmanager
    async def database():
        yield db
    monkeypatch.setattr(jobs, 'safe_session', database)
    monkeypatch.setattr('backend.autoresearch.engine.datasets.validate_access', AsyncMock())
    error = asyncio.CancelledError(RESTART_INTERRUPTION) if restart else asyncio.CancelledError()
    monkeypatch.setattr(jobs, 'execute_experiment', AsyncMock(side_effect=error))
    monkeypatch.setattr(jobs.store, 'job_update', AsyncMock())
    monkeypatch.setattr(jobs.store, 'experiment_update', AsyncMock())
    with pytest.raises(asyncio.CancelledError):
        await jobs.run(task_id='original-job')
    status = 'queued' if restart else 'cancelled'
    assert jobs.store.job_update.call_args.args == ('original-job', status)
    jobs.store.experiment_update.assert_awaited_once_with('session', 'original-job', status=status)
    assert session.current_iteration == 2


async def test_crash_recovery_requeues_saved_research_jobs_in_order_and_keeps_checkpoints(monkeypatch, tmp_path):
    from backend.autoresearch.engine import jobs
    from backend.database.models import ResearchJob
    rows = [ResearchJob(job_id=f'job-{i}', session_id='session', kind='experiment', status=status,
                        created_at=datetime(2026, 1, i), payload={}, result={})
            for i, status in [(3, 'queued'), (2, 'cancelling'), (1, 'running')]]
    checkpoint = tmp_path / 'runs/job-1/output/checkpoint.pt'
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b'saved-weights')
    session = SimpleNamespace(status='running', workspace_path=str(tmp_path), recovery_metadata={}, current_iteration=3)
    @asynccontextmanager
    async def database():
        yield SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: rows)))
    monkeypatch.setattr(jobs, 'safe_session', database)
    monkeypatch.setattr(jobs.store, 'get', AsyncMock(return_value=session))
    monkeypatch.setattr(jobs.store, 'job_update', AsyncMock())
    monkeypatch.setattr(jobs.store, 'experiment_update', AsyncMock())
    enqueue = AsyncMock()
    monkeypatch.setattr(jobs, 'enqueue_task_descriptor', enqueue)
    await jobs.recover()
    assert [call.args[0].job_id for call in enqueue.call_args_list] == ['job-1', 'job-3']
    assert jobs.store.job_update.call_args_list[0].args[:2] == ('job-1', 'queued')
    assert jobs.store.job_update.call_args_list[1].args[:2] == ('job-2', 'cancelled')
    assert checkpoint.read_bytes() == b'saved-weights' and session.current_iteration == 3
