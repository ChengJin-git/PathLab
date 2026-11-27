from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import Integer, MetaData, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database.models import TrainingTask, ResearchJob, AutoResearchSession, DataGroup, utc_now
from backend.database.repositories.training import TrainingTaskRepository
from backend.autoresearch.engine import registration


async def test_list_count_and_statistics_exclude_non_experiment_jobs():
    engine = create_async_engine('sqlite+aiosqlite://')
    metadata = MetaData()
    for model in [DataGroup, AutoResearchSession, ResearchJob, TrainingTask]:
        model.__table__.to_metadata(metadata)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add(DataGroup(group_id='g', name='WSI', data_type='wsi', aggregation_level='case', task_type='wsi_classification'))
        db.add(AutoResearchSession(session_id='s', user_id='alice', research_question='test'))
        for task_id, kind in [('training', None), ('experiment', 'experiment'), ('metrics', 'computation'), ('download', 'download')]:
            db.add(TrainingTask(task_id=task_id, task_name=task_id, user_id='alice', group_id='g', status='completed'))
            if kind:
                db.add(ResearchJob(job_id=task_id, session_id='s', kind=kind, status='completed', payload={}, result={}))
        await db.commit()
        assert {task.task_id for task in await TrainingTaskRepository.get_all(db, user_id='alice')} == {'training', 'experiment'}
        assert await TrainingTaskRepository.count(db, user_id='alice') == 2
        assert (await TrainingTaskRepository.get_status_counts(db, user_id='alice'))['total'] == 2
        assert await TrainingTaskRepository.count(db, user_id='bob') == 0
    await engine.dispose()


async def test_registration_writes_extractor_and_actual_execution_timestamps(monkeypatch, tmp_path):
    (tmp_path / 'model.pkl').write_bytes(b'test model')
    finish = utc_now()
    job = SimpleNamespace(kind='experiment', status='completed', session_id='s', updated_at=finish, result={'duration_seconds': 31.43})
    row = SimpleNamespace(workspace_path=str(tmp_path), user_id='alice', recovery_metadata={'datasets': [{'dataset_id': 'd'}]})
    db = SimpleNamespace(get=AsyncMock(return_value=job), scalar=AsyncMock(side_effect=[SimpleNamespace(data_type='wsi', aggregation_level='file', tasks=[SimpleNamespace(task_type='wsi_classification')]), None, None]), scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])), add=Mock(), add_all=Mock(), commit=AsyncMock(), flush=AsyncMock())
    monkeypatch.setattr('backend.database.repositories.DataGroupRepository.get_or_create', AsyncMock(return_value=SimpleNamespace(group_id='g', task_type='wsi_classification')))
    @asynccontextmanager
    async def database():
        yield db
    monkeypatch.setattr(registration, 'safe_session', database)
    monkeypatch.setattr(registration.store, 'get', AsyncMock(return_value=row))
    monkeypatch.setattr(registration.store, 'experiments', AsyncMock(return_value=[{'run_id': 'run', 'status': 'completed', 'config': {}, 'metrics': {}}]))
    monkeypatch.setattr(registration.store, 'update', AsyncMock())
    monkeypatch.setattr(registration.Config, 'get_uploads_dir', lambda: tmp_path / 'uploads')
    monkeypatch.setattr('backend.services.research_prediction.prepare_predictor', Mock(return_value={'contract':'pathlab-predictor-v1','classes':[]}))
    index_task = AsyncMock()
    monkeypatch.setattr('backend.services.result_analysis.sources.index_task', index_task)
    await registration.register_model('s', run_id='run', path='model.pkl', dataset_id='d', name='CONCH model', feature_extractor='conch', aggregator='mean_pooling_mlp', prediction={'runtime':'sklearn','task_type':'wsi_classification'})
    task = next(call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], TrainingTask))
    assert task.preprocessing_config['feature_extractor'] == 'conch'
    assert task.finished_at == finish
    assert (task.finished_at - task.started_at).total_seconds() == 31.43
    index_task.assert_awaited_once_with(db, 'run')
    job.kind = 'computation'
    with pytest.raises(ValueError, match='Only a completed experiment'):
        await registration.register_model('s', run_id='run', path='model.pkl', dataset_id='d', name='metrics', feature_extractor='conch', aggregator='mean')
