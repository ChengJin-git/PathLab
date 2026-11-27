"""Small OpenCode V2 HTTP client. No CLI-output parsing or V1 protocol branches."""

from __future__ import annotations

import asyncio
import json

import httpx


class OpenCodeClient:
    def __init__(self, url: str, password: str):
        self.http = httpx.AsyncClient(
            base_url=url, auth=("opencode", password), timeout=30, trust_env=False
        )

    async def close(self):
        await self.http.aclose()

    async def request(self, method: str, path: str, **kwargs):
        for attempt in range(3):
            try:
                response = await self.http.request(method, path, **kwargs)
                break
            except httpx.TransportError:
                if method != "GET" or attempt == 2:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))
        response.raise_for_status()
        if response.status_code == 204:
            return None
        return response.json()

    async def create(self, directory: str, title: str) -> str:
        from ..runtime.container_backend import backend, container_path
        if backend() == 'docker': directory = container_path(directory)
        result = await self.request(
            "POST",
            "/api/session",
            json={
                "location": {"directory": directory},
                "title": title,
                "model": {"providerID": "pathlab", "id": "research"},
            },
        )
        return result["data"]["id"]

    async def ensure_research_tools(self, directory: str) -> bool:
        """Repair failed discovery before the agent runs without its core tools."""
        from ..runtime.container_backend import backend, container_path

        if backend() == 'docker':
            directory = container_path(directory)
        params = {'location[directory]': directory}
        reconnected = False
        attempts = 0
        try:
            async with asyncio.timeout(60):
                while True:
                    result = await self.request('GET', '/api/mcp', params=params)
                    server = next((item for item in result['data'] if item['name'] == 'pathlab'), None)
                    # Location/config discovery is asynchronous even after /api/info
                    # is healthy. Do not reconnect an in-flight initialization.
                    if server is None or server['status']['status'] == 'pending':
                        await asyncio.sleep(1)
                        continue
                    status = server['status']['status']
                    if status == 'connected':
                        return reconnected
                    if status == 'needs_auth':
                        raise RuntimeError('PathLab MCP authentication is unavailable')
                    if attempts == 3:
                        break
                    if attempts:
                        await asyncio.sleep(attempts)
                    await self.request('POST', '/api/experimental/mcp/pathlab/connect', params=params)
                    attempts += 1
                    reconnected = True
        except TimeoutError as exc:
            raise RuntimeError('PathLab MCP discovery did not become ready within 60 seconds; check Gateway availability and workspace configuration') from exc
        raise RuntimeError('PathLab MCP tools could not reconnect after three attempts; check Gateway availability and the research credential')

    async def prompt(
        self,
        session_id: str,
        text: str,
        message_id: str | None = None,
        *,
        internal: bool = True,
        delivery: str = 'queue',
    ):
        body = {
            "text": text,
            "delivery": delivery,
            "metadata": {"pathlabInternal": internal},
        }
        if message_id:
            body["id"] = message_id
        if internal:
            body["resume"] = True
        return await self.request(
            "POST",
            f"/api/session/{session_id}/{'synthetic' if internal else 'prompt'}",
            json=body,
        )

    async def interrupt(self, session_id: str):
        return await self.request(
            "POST", f"/api/session/{session_id}/interrupt", json={}
        )

    async def messages(self, session_id: str) -> list[dict]:
        result = await self.request(
            "GET",
            f"/api/session/{session_id}/message",
            params={"limit": "100", "order": "desc"},
        )
        return list(reversed(result["data"]))

    async def active(self, session_id: str) -> bool:
        state = await self.work_state(session_id)
        return bool(state['root_active'] or state['children'] or state['shells'] or state['inbox'])

    async def work_state(self, session_id: str) -> dict:
        """Observe root execution, descendants, queued delivery and native shells."""
        active, root, inbox = await asyncio.gather(
            self.request('GET', '/api/session/active'),
            self.request('GET', f'/api/session/{session_id}'),
            self.request('GET', f'/api/session/{session_id}/inbox'),
        )
        parents = {session_id: root['data']}
        children = []
        for identity in active['data']:
            current, seen = identity, set()
            while current and current not in seen:
                if current == session_id:
                    if identity != session_id:
                        children.append({'id': identity, 'title': parents[identity].get('title', '')})
                    break
                seen.add(current)
                if current not in parents:
                    try:
                        parents[current] = (await self.request('GET', f'/api/session/{current}'))['data']
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 404:
                            raise
                        break
                current = parents[current].get('parentID')
        directory = root['data']['location']['directory']
        shells = await self.request('GET', '/api/shell', params={'location[directory]': directory})
        return {'root_active': session_id in active['data'], 'children': children,
                'inbox': len(inbox['data']),
                'shells': [{'id': s['id'], 'status': s['status']} for s in shells['data'] if s['status'] == 'running']}

    async def interrupted_children(self, session_id: str) -> list[dict]:
        """Recover unfinished descendants even when a crash wrote no outcome.

        OpenCode 2.2.5 retains time.busy and running tool messages across a hard
        service exit; it does not necessarily append an interrupted outcome.
        """
        active = (await self.request('GET', '/api/session/active'))['data']
        pending, seen, interrupted = [session_id], set(), []
        while pending:
            parent = pending.pop()
            if parent in seen:
                continue
            seen.add(parent)
            params = {'parentID': parent, 'limit': '100'}
            while True:
                result = await self.request('GET', '/api/session', params=params)
                for child in result['data']:
                    pending.append(child['id'])
                    clock = child.get('time', {})
                    unfinished = clock.get('busy', 0) > clock.get('idle', 0)
                    if child['id'] not in active and (unfinished or child.get('outcome') in {'interrupted', 'failed'}):
                        interrupted.append({'id': child['id'], 'title': child.get('title'),
                                            'outcome': 'interrupted' if unfinished else child['outcome']})
                cursor = result.get('cursor', {}).get('next')
                if not cursor:
                    break
                params = {**params, 'cursor': cursor}
        return interrupted

    async def forms(self, session_id: str) -> list[dict]:
        return (await self.request("GET", f"/api/session/{session_id}/form"))["data"]

    async def reply_form(self, session_id: str, form_id: str, answer: dict):
        return await self.request(
            "POST",
            f"/api/session/{session_id}/form/{form_id}/reply",
            json={"answer": answer},
        )

    async def events(self):
        async with self.http.stream("GET", "/api/event", timeout=None) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    value = json.loads(line[5:].strip())
                    if isinstance(value, str):
                        value = json.loads(value)
                    yield value
