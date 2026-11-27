"""Minimal stdio MCP transport; business implementations stay in PathLab.

Uses only Python's standard library so it runs in the existing training image.
"""

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def translate_paths(value, mapping):
    if isinstance(value, dict): return {key: translate_paths(item, mapping) for key, item in value.items()}
    if isinstance(value, list): return [translate_paths(item, mapping) for item in value]
    if isinstance(value, str):
        # Tool responses include JSON serialized into MCP text content.
        if value.startswith(('{', '[')):
            try: return json.dumps(translate_paths(json.loads(value), mapping), ensure_ascii=False)
            except ValueError: pass
        for source, target in sorted(mapping.items(), key=lambda pair: len(pair[0]), reverse=True):
            if value == source or value.startswith(source + '/') or value.startswith(source + '\\'):
                return target + value[len(source):].replace('\\', '/')
    return value


def request(path, data=None):
    mapping = json.loads(os.environ.get('PATHLAB_PATH_MAP', '{}'))
    if data is not None: data = translate_paths(data, {target: source for source, target in mapping.items()})
    base = os.environ["PATHLAB_GATEWAY_URL"].rstrip("/")
    sid = os.environ["PATHLAB_RESEARCH_ID"]
    headers = {
        "Authorization": "Bearer " + os.environ["PATHLAB_RESEARCH_TOKEN"],
        "Content-Type": "application/json",
    }
    req = Request(
        f"{base}/research/internal/{sid}/{path}",
        data=json.dumps(data).encode() if data is not None else None,
        headers=headers,
    )
    # Gateway and ResearchWorker start concurrently. Retry only discovery reads;
    # a timed-out tool call may already have submitted work and must not replay.
    attempts = 4 if path == 'tools' else 1
    for attempt in range(attempts):
        try:
            with urlopen(req, timeout=5 if path == 'tools' else 180) as response:
                return translate_paths(json.load(response), mapping)
        except (URLError, TimeoutError) as exc:
            if (attempt + 1 == attempts
                    or isinstance(exc, HTTPError) and exc.code not in {429, 502, 503, 504}):
                raise
            time.sleep(0.5 * 2 ** attempt)


def main():
    for line in sys.stdin:
        message = {}
        try:
            message = json.loads(line)
            if "id" not in message:
                continue
            method = message.get("method")
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "pathlab-research", "version": "1.0"},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = request("tools")
            elif method == "tools/call":
                result = request("call", message["params"])
            else:
                print(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "error": {"code": -32601, "message": "Method not found"},
                        }
                    ),
                    flush=True,
                )
                continue
            print(
                json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}),
                flush=True,
            )
        except Exception as exc:
            error = str(exc)
            if message.get('method') == 'tools/call':
                payload = {'result': {'isError': True, 'content': [{'type': 'text', 'text': error}]}}
            else:
                # isError/content is a CallToolResult, never a tools/list result.
                payload = {'error': {'code': -32603, 'message': error}}
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        **payload,
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
