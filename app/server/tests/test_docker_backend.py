import asyncio
import json
import os
from pathlib import Path
import subprocess
import pytest
from backend.autoresearch.runtime import container_backend as containers


def test_windows_mount_and_path_contract():
    assert containers.split_mount(r'C:\User\Data:C:\User\Data:ro') == (r'C:\User\Data', r'C:\User\Data', 'ro')
    assert containers.split_mount('/data:/research-data:ro') == ('/data', '/research-data', 'ro')
    assert containers.container_path(r'C:\User\Data\image.tif') == '/pathlab-host/c/User/Data/image.tif'


def test_mcp_paths_roundtrip_between_windows_and_container(monkeypatch):
    from backend.autoresearch.engine.mcp_stdio import translate_paths
    mapping = {r'C:\User\Research': '/pathlab-host/c/User/Research'}
    output = translate_paths({'content': [{'text': json.dumps({'manifest_path': r'C:\User\Research\datasets\a.json'})}]}, mapping)
    assert json.loads(output['content'][0]['text'])['manifest_path'] == '/pathlab-host/c/User/Research/datasets/a.json'
    back = translate_paths({'path': '/pathlab-host/c/User/Research/metrics.json'}, {v:k for k,v in mapping.items()})
    assert back['path'].replace('\\', '/') == 'C:/User/Research/metrics.json'


def test_docker_preserves_mount_modes_and_does_not_expose_socket(tmp_path, monkeypatch):
    monkeypatch.setenv('PATHLAB_SANDBOX_BACKEND', 'docker')
    src = tmp_path / 'source'; src.mkdir()
    cmd, env, name = containers.prepare(['apptainer','exec','--contain','--bind',f'{src}:/data:ro','--pwd','/data','unused.sif','python','job.py'],
        {'APPTAINERENV_SECRET': 'private-token'}, name='pathlab-test')
    assert '--read-only' in cmd and '--cap-drop=ALL' in cmd
    assert any('target=/data,readonly' in arg for arg in cmd)
    assert 'private-token' not in cmd and env['SECRET'] == 'private-token'
    assert not any('docker.sock' in arg or arg == '--privileged' for arg in cmd)
    assert name == 'pathlab-test'


@pytest.mark.asyncio
async def test_relay_rejects_other_sessions_and_admin_paths(monkeypatch):
    from backend.autoresearch.engine.docker_relay import start_relay
    server, port = await start_relay('one', 'secret')
    try:
        import httpx
        async with httpx.AsyncClient(trust_env=False) as client:
            for path in ['/health','/settings','/research/internal/two/tools']:
                response = await client.get(f'http://127.0.0.1:{port}{path}', headers={'Authorization':'Bearer secret'})
                assert response.status_code == 403
    finally: server.close(); await server.wait_closed()


@pytest.mark.skipif(os.environ.get('PATHLAB_TEST_DOCKER') != '1', reason='Explicit Docker integration run')
def test_real_container_readonly_inputs_and_output(tmp_path, monkeypatch):
    monkeypatch.setenv('PATHLAB_SANDBOX_BACKEND', 'docker')
    monkeypatch.setenv('PATHLAB_DOCKER_IMAGE', 'python:3.9-slim')
    inputs = tmp_path / 'inputs'; inputs.mkdir(); (inputs/'file').write_text('value')
    output = tmp_path / 'output'; output.mkdir()
    script = "from pathlib import Path; assert Path('/inputs/file').read_text()=='value'; Path('/output/result').write_text('done');\ntry: Path('/inputs/file').write_text('bad'); raise AssertionError('writable')\nexcept OSError: pass"
    cmd, env, _ = containers.prepare(['apptainer','exec','--bind',f'{inputs}:/inputs:ro','--bind',f'{output}:/output:rw','unused','python','-c',script], {})
    subprocess.run(cmd, env=env, check=True, timeout=60)
    assert (output/'result').read_text() == 'done'
    assert (inputs/'file').read_text() == 'value'


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get('PATHLAB_TEST_RESEARCH_DOCKER') != '1', reason='Requires the published PathLab OCI image')
async def test_real_research_job_runs_frozen_source_and_persists_metrics(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.autoresearch.engine import jobs, processes
    from backend.autoresearch.engine import file_catalog
    from backend.common.config import Config
    monkeypatch.setenv('PATHLAB_SANDBOX_BACKEND', 'docker')
    monkeypatch.setenv('PATHLAB_UPLOADS_DIR', str(tmp_path / 'storage'))
    root = tmp_path / 'session_test'; source = root / 'runs/research_test/source'
    source.mkdir(parents=True)
    (source / 'train.py').write_text("import os,json;from pathlib import Path\noutput=Path(os.environ['OUTPUT_DIR']);output.joinpath('metrics.json').write_text(json.dumps({'accuracy':0.75}));assert os.environ['PATHLAB_DEVICE']=='cpu'\ntry:Path('should-not-write').write_text('bad');raise AssertionError('source writable')\nexcept OSError:pass\n")
    @asynccontextmanager
    async def session():
        yield SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(status='running', session_id='test')),
                              scalar=AsyncMock(return_value=SimpleNamespace(status='running', recovery_metadata={})), commit=AsyncMock())
    monkeypatch.setattr(jobs, 'safe_session', session)
    monkeypatch.setattr(processes, 'safe_session', session)
    monkeypatch.setattr(jobs.store, 'update', AsyncMock())
    monkeypatch.setattr(jobs.store, 'experiment_update', AsyncMock())
    monkeypatch.setattr(Config, 'get_global_settings', lambda: {})
    monkeypatch.setattr(file_catalog, 'index_tree', AsyncMock(return_value={'items':[], 'count':0, 'truncated':False}))
    result = await jobs.execute_experiment(
        SimpleNamespace(workspace_path=str(root), recovery_metadata={}, session_id='test'),
        SimpleNamespace(job_id='research_test', kind='experiment', payload={'source':str(source),'command':['python','train.py'],'timeout':60}),
        'cpu')
    assert result['metrics'] == {'accuracy':0.75}
    assert not (source / 'should-not-write').exists()
    assert not (source.parent / 'process.json').exists()


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get('PATHLAB_TEST_RESEARCH_DOCKER') != '1', reason='Requires the published PathLab OCI image')
async def test_cancel_quiet_research_container_reaps_container(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.autoresearch.engine import jobs, processes
    from backend.common.config import Config
    monkeypatch.setenv('PATHLAB_SANDBOX_BACKEND', 'docker')
    monkeypatch.setenv('PATHLAB_UPLOADS_DIR', str(tmp_path / 'storage'))
    root = tmp_path / 'session_cancel'; source = root / 'runs/research_cancel/source'
    source.mkdir(parents=True)
    (source / 'job.py').write_text('import time; time.sleep(120)')
    @asynccontextmanager
    async def session():
        yield SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(status='cancelling')))
    @asynccontextmanager
    async def spawn_session():
        yield SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(status='running', session_id='cancel')),
                              scalar=AsyncMock(return_value=SimpleNamespace(status='running', recovery_metadata={})), commit=AsyncMock())
    monkeypatch.setattr(jobs, 'safe_session', session)
    monkeypatch.setattr(processes, 'safe_session', spawn_session)
    monkeypatch.setattr(jobs.store, 'experiment_update', AsyncMock())
    monkeypatch.setattr(Config, 'get_global_settings', lambda: {})
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(jobs.execute_experiment(
            SimpleNamespace(workspace_path=str(root), recovery_metadata={}, session_id='cancel'),
            SimpleNamespace(job_id='research_cancel', kind='experiment', payload={'source':str(source),'command':['python','job.py'],'timeout':60}),
            'cpu'), timeout=20)
    result = subprocess.run(['docker','inspect','pathlab-job-research_cancel'], capture_output=True)
    assert result.returncode != 0
    assert not (source.parent / 'process.json').exists()


@pytest.mark.skipif(os.environ.get('PATHLAB_TEST_RESEARCH_DOCKER') != '1', reason='Requires the published PathLab OCI image')
def test_docker_prediction_protocol_uses_real_isolated_adapter(tmp_path, monkeypatch):
    from backend.services.research_prediction import prepare_predictor, PredictorProcess
    monkeypatch.setenv('PATHLAB_SANDBOX_BACKEND', 'docker')
    monkeypatch.setenv('PATHLAB_UPLOADS_DIR', str(tmp_path / 'storage'))
    model = tmp_path / 'model.bin'; model.write_bytes(b'fixture')
    adapter = tmp_path / 'adapter'; adapter.mkdir()
    (adapter / 'predict.py').write_text("import numpy as np\nclass Predictor:\n feature_dim=3\n def predict(self,inputs,context):return {'probabilities':np.array([[0.25,0.75]])}\ndef load_predictor(model_path,config):return Predictor()\n")
    spec = {'runtime':'python','task_type':'wsi_classification','input_kind':'features','pooling':'none','classes':['a','b'],'entrypoint':'predict.py'}
    manifest = prepare_predictor(model, 'test-encoder', spec, adapter)
    assert manifest['classes'] == ['a','b']
    assert manifest['feature_dim'] == 3
