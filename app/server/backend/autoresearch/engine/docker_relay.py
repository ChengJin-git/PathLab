"""Per-session HTTP relay from Docker Desktop to the loopback-only Gateway.

Only two exact MCP paths are accepted, with the session's existing bearer token.
No general HTTP proxy or unauthenticated health/admin endpoint is exposed.
"""
import asyncio
import hmac
import httpx
from backend.common.config import Config


async def start_relay(session_id, token):
    allowed = {f'/research/internal/{session_id}/tools', f'/research/internal/{session_id}/call'}

    async def handle(reader, writer):
        try:
            headers = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
            lines = headers.decode('latin1').split('\r\n')
            method, path, _ = lines[0].split(' ', 2)
            values = dict(line.split(':', 1) for line in lines[1:] if ':' in line)
            values = {key.lower(): value.strip() for key, value in values.items()}
            if path not in allowed or method not in {'GET', 'POST'} or not hmac.compare_digest(values.get('authorization', ''), 'Bearer ' + token):
                writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'); return
            size = int(values.get('content-length', '0'))
            if not 0 <= size <= 2 * 1024**2 or 'transfer-encoding' in values:
                raise ValueError('Unsupported request body')
            body = await asyncio.wait_for(reader.readexactly(size), 30)
            async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
                response = await client.request(method, Config.GATEWAY_SERVICE_URL + path, content=body,
                    headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
            writer.write(f'HTTP/1.1 {response.status_code} Response\r\nContent-Type: application/json\r\nContent-Length: {len(response.content)}\r\nConnection: close\r\n\r\n'.encode() + response.content)
        except Exception:
            writer.write(b'HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        finally:
            try: await writer.drain()
            finally: writer.close(); await writer.wait_closed()
    server = await asyncio.start_server(handle, '0.0.0.0', 0, limit=16384)
    return server, server.sockets[0].getsockname()[1]
