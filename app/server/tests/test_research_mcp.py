import io
import json
from unittest.mock import AsyncMock, Mock
from urllib.error import HTTPError, URLError

import httpx
import pytest

from backend.autoresearch.engine import mcp_stdio
from backend.autoresearch.engine.client import OpenCodeClient


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setenv('PATHLAB_GATEWAY_URL', 'http://gateway')
    monkeypatch.setenv('PATHLAB_RESEARCH_ID', 'session')
    monkeypatch.setenv('PATHLAB_RESEARCH_TOKEN', 'token')
    monkeypatch.setattr(mcp_stdio.time, 'sleep', Mock())
    return monkeypatch


def test_catalog_recovers_from_gateway_startup_race(bridge):
    response = io.BytesIO(b'{"tools": [{"name": "submit_experiment"}]}')
    transport = Mock(side_effect=[URLError('connection refused'), response])
    bridge.setattr(mcp_stdio, 'urlopen', transport)
    assert mcp_stdio.request('tools')['tools'][0]['name'] == 'submit_experiment'
    assert transport.call_count == 2
    mcp_stdio.time.sleep.assert_called_once_with(.5)


@pytest.mark.parametrize('path,error,expected_calls', [
    ('call', URLError('connection reset'), 1),
    ('tools', HTTPError('http://gateway', 403, 'forbidden', {}, None), 1),
    ('tools', URLError('connection refused'), 4),
])
def test_tool_calls_are_never_replayed_and_discovery_retries_are_bounded(bridge, path, error, expected_calls):
    transport = Mock(side_effect=error)
    bridge.setattr(mcp_stdio, 'urlopen', transport)
    with pytest.raises(URLError):
        mcp_stdio.request(path, {'name': 'submit_experiment'} if path == 'call' else None)
    assert transport.call_count == expected_calls


def test_discovery_errors_use_json_rpc_error_not_tool_result(monkeypatch, capsys):
    monkeypatch.setattr(mcp_stdio.sys, 'stdin', io.StringIO(
        json.dumps({'id': 1, 'method': 'tools/list'}) + '\n'
        + json.dumps({'id': 2, 'method': 'tools/call', 'params': {'name': 'get_research_context'}}) + '\n'))
    monkeypatch.setattr(mcp_stdio, 'request', Mock(side_effect=URLError('gateway unavailable')))
    mcp_stdio.main()
    discovery, call = map(json.loads, capsys.readouterr().out.splitlines())
    assert discovery['error']['code'] == -32603
    assert 'gateway unavailable' in discovery['error']['message']
    assert 'result' not in discovery
    assert call['result']['isError'] is True


@pytest.mark.parametrize('statuses,reconnected,connects', [
    (['connected'], False, 0),
    ([None, 'pending', 'connected'], False, 0),
    (['failed', 'connected'], True, 1),
    (['disconnected', 'failed', 'connected'], True, 2),
])
async def test_native_mcp_connection_recovers_at_the_session_location(monkeypatch, statuses, reconnected, connects):
    monkeypatch.setattr('backend.autoresearch.engine.client.asyncio.sleep', AsyncMock())
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.params['location[directory]'] == '/research/session'
        if request.method == 'POST':
            assert request.url.path == '/api/experimental/mcp/pathlab/connect'
            return httpx.Response(204)
        status = statuses.pop(0)
        return httpx.Response(200, json={'data': [{'name': 'pathlab', 'status': {'status': status}}] if status else []})
    client = OpenCodeClient('http://native', 'password')
    await client.http.aclose()
    client.http = httpx.AsyncClient(base_url='http://native', transport=httpx.MockTransport(handler))
    try:
        assert await client.ensure_research_tools('/research/session') is reconnected
        assert sum(r.method == 'POST' for r in requests) == connects
    finally:
        await client.close()


async def test_persistent_missing_tools_do_not_allow_an_empty_tool_research_loop(monkeypatch):
    monkeypatch.setattr('backend.autoresearch.engine.client.asyncio.sleep', AsyncMock())
    client = OpenCodeClient('http://native', 'password')
    async def request(method, path, **kwargs):
        if method == 'GET':
            return {'data': [{'name': 'pathlab', 'status': {'status': 'failed', 'error': 'catalog unavailable'}}]}
    client.request = AsyncMock(side_effect=request)
    try:
        with pytest.raises(RuntimeError, match='could not reconnect'):
            await client.ensure_research_tools('/research/session')
        assert len([call for call in client.request.call_args_list if call.args[0] == 'POST']) == 3
    finally:
        await client.close()
