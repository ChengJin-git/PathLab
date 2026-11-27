"""Contracts at the new runtime's execution and access boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from backend.autoresearch.engine import tools
from backend.autoresearch.engine.client import OpenCodeClient
from backend.autoresearch.engine.jobs import contained, numeric_metrics
from backend.common.model_config import ModelConfig
from gateway.routes.autoresearch import StartResearch, claims_user, owned


@pytest.mark.parametrize('active,parents,expected', [
    ({'root': {}}, {}, True),
    ({'child': {}}, {'child': 'root'}, True),
    ({'grandchild': {}}, {'grandchild': 'child', 'child': 'root'}, True),
    ({'other': {}}, {'other': 'unrelated', 'unrelated': None}, False),
    ({}, {}, False),
])
async def test_native_activity_includes_only_own_background_descendants(active, parents, expected):
    client = OpenCodeClient('http://test', 'test')
    async def request(method, path, **kwargs):
        if path == '/api/session/active':
            return {'data': active}
        if path.endswith('/inbox') or path == '/api/shell':
            return {'data': []}
        identity = path.rsplit('/', 1)[-1]
        return {'data': {'id': identity, 'parentID': parents.get(identity), 'location': {'directory': '/test'}}}
    client.request = AsyncMock(side_effect=request)
    try:
        assert await client.active('root') is expected
    finally:
        await client.close()


def test_metrics_keep_split_and_aggregation_and_reject_nonfinite():
    assert numeric_metrics(
        {
            "test": {"case": {"auc": 0, "accuracy": 0.4}},
            "val": {"auc": 1},
            "nan": float("nan"),
            "infinity": float("inf"),
            "valid": True,
        }
    ) == {"test.case.auc": 0, "test.case.accuracy": 0.4, "val.auc": 1}


def test_artifact_path_cannot_escape_through_symlink(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    other = tmp_path / "other"
    other.write_text("private")
    (root / "link").symlink_to(other)
    with pytest.raises(ValueError):
        contained(root, "link")
    with pytest.raises(ValueError):
        contained(root, "../other")


def test_same_workspace_artifact_reference_gets_read_only_alias_mount(tmp_path, monkeypatch):
    from backend.autoresearch.engine import runtime
    root = tmp_path / 'session_s'
    root.mkdir()
    artifact = root / 'metrics.json'
    artifact.write_text('{}')
    image = tmp_path / 'sandbox.sif'
    image.touch()
    monkeypatch.setattr(runtime, '_resolve_default_image', lambda: str(image))
    monkeypatch.setattr(runtime, '_resolve_apptainer_bin', lambda: 'apptainer')
    monkeypatch.setattr(runtime.Config, 'get_autoresearch_dir', lambda: tmp_path)
    monkeypatch.setattr(runtime.Config, 'get_uploads_dir', lambda: tmp_path)
    command = runtime.sandbox_command(root, {str(artifact): '/research-data/references/metrics.json'})
    assert f'{artifact}:/research-data/references/metrics.json:ro' in command


def test_model_alias_preserves_upstream_slashes_and_credentials_reference():
    config = ModelConfig(
        "compatible", "vendor/custom-model", "https://example.test/v1", "secret"
    )
    assert (
        config.opencode_provider()["models"]["research"]["modelID"]
        == "vendor/custom-model"
    )
    assert "secret" not in str(config.public())
    assert config.opencode_provider()["settings"]["apiKey"] == "{env:PATHLAB_MODEL_KEY}"


def test_scoped_stream_token_cannot_download_other_session():
    user = SimpleNamespace(id="owner", role="pathologist")
    claims = {
        "typ": "autoresearch_access",
        "sid": "one",
        "purpose": "events",
        "user": user,
    }
    assert claims_user(claims, "one", "events") is user
    with pytest.raises(HTTPException):
        claims_user(claims, "two", "events")
    with pytest.raises(HTTPException):
        claims_user(claims, "one", "session_download")


def test_research_contract_rejects_old_model_and_iteration_fields():
    with pytest.raises(ValueError):
        StartResearch(question="Research", model="hardcoded", max_iter=5)


@pytest.mark.asyncio
async def test_owner_access_is_enforced(monkeypatch):
    monkeypatch.setattr(
        "gateway.routes.autoresearch.store.get",
        AsyncMock(return_value=SimpleNamespace(user_id="a")),
    )
    with pytest.raises(HTTPException) as error:
        await owned("s", SimpleNamespace(id="b", role="pathologist", is_admin=lambda: False))
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_paused_research_cannot_launch_tool(monkeypatch):
    monkeypatch.setattr(
        tools.store, "get", AsyncMock(return_value=SimpleNamespace(status="paused", recovery_metadata={}))
    )
    with pytest.raises(ValueError, match="paused"):
        await tools.call(
            "s",
            "submit_experiment",
            {"name": "experiment", "command": ["python", "train.py"]},
        )


@pytest.mark.asyncio
async def test_opencode_v2_prompt_is_durable_and_native():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": {"id": "inbox"}})

    client = OpenCodeClient("http://localhost", "password")
    await client.http.aclose()
    client.http = httpx.AsyncClient(
        base_url="http://localhost", transport=httpx.MockTransport(handler)
    )
    try:
        await client.prompt("ses_example", "Continue", "msg_test")
        assert requests[0].url.path == "/api/session/ses_example/synthetic"
        import json

        assert json.loads(requests[0].content) == {
            "text": "Continue",
            "delivery": "queue",
            "id": "msg_test",
            "metadata": {"pathlabInternal": True},
            "resume": True,
        }
    finally:
        await client.close()


async def test_startup_failure_reports_current_launch_and_redacts_credentials(tmp_path, monkeypatch):
    from backend.autoresearch.engine import runtime
    from backend.autoresearch.engine.recovery import classify_error

    monkeypatch.setattr(runtime.Config, 'get_autoresearch_dir', lambda: tmp_path)
    monkeypatch.setattr(runtime.Config, 'get_autoresearch_sessions_dir', lambda: tmp_path / 'sessions')
    monkeypatch.setattr(runtime.container_backend, 'backend', lambda: 'apptainer')
    monkeypatch.setattr(runtime.container_backend, 'prepare', lambda cmd, env, **kwargs: (cmd, env, None))
    monkeypatch.setenv('PATHLAB_OPENCODE_BIN', '/bin/true')
    monkeypatch.setattr(runtime.subprocess, 'check_output', lambda *args, **kwargs: f'opencode v{runtime.OPENCODE_VERSION}')
    monkeypatch.setattr(runtime, 'sandbox_command', lambda *args: ['apptainer', 'exec', '--no-home', 'image.sif'])
    monkeypatch.setattr(runtime, 'install_domain_skills', lambda *args: None)
    monkeypatch.setattr(runtime, 'install_skills', lambda *args: None)
    monkeypatch.setattr(runtime.pathtrove, 'install', lambda: None)
    agent = runtime.AgentRuntime('session')
    key = runtime.credentials('session')
    (agent.private / 'server.log').write_text('OLD FAILURE MUST NOT APPEAR\n')

    async def spawn(*args, **kwargs):
        kwargs['stderr'].write(f'FATAL: argument size limit; {key["password"]} {key["tool_token"]} model-secret\n')
        return SimpleNamespace(returncode=255)

    monkeypatch.setattr(runtime, 'spawn_owned', spawn)
    try:
        with pytest.raises(RuntimeError, match='argument size limit') as error:
            await agent.start(ModelConfig('compatible', 'model', 'https://model', 'model-secret'), {})
        detail = str(error.value)
        assert 'OLD FAILURE' not in detail
        assert all(secret not in detail for secret in [*key.values(), 'model-secret'])
        assert classify_error(error.value) == 'service'
    finally:
        if agent.client:
            await agent.client.close()


def test_runtime_opencode_version_matches_package_pin():
    import json
    from pathlib import Path
    from backend.autoresearch.engine import runtime

    package = json.loads((Path(__file__).resolve().parents[2] / 'package.json').read_text())
    assert runtime.OPENCODE_VERSION == package['opencodeVersion']


def test_opencode_binary_falls_back_to_installed_location(monkeypatch, tmp_path):
    from backend.autoresearch.engine.runtime import opencode_binary

    installed = tmp_path / '.opencode/bin/opencode'
    installed.parent.mkdir(parents=True)
    installed.write_text('#!/bin/sh\n')
    installed.chmod(0o755)
    monkeypatch.delenv('PATHLAB_OPENCODE_BIN', raising=False)
    monkeypatch.setenv('PATH', str(tmp_path / 'empty'))
    monkeypatch.setenv('HOME', str(tmp_path))
    assert opencode_binary() == str(installed)
    installed.unlink()
    assert opencode_binary() is None
