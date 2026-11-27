"""Bounded MCP Streamable HTTP calls with user-owned credentials and reauthorization."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4
import httpx
from fastapi import HTTPException
from jsonschema import Draft202012Validator, ValidationError, SchemaError
from sqlalchemy import select
from backend.database.models import CapabilityInstallation, utc_now
from backend.common.net_guard import validate_external_url
from .capability_library import get_entry, reveal

MAX_RESPONSE = 1024 * 1024
_slots = asyncio.Semaphore(8)


async def rpc(client, url, headers, method, params=None, *, notify=False):
    await asyncio.to_thread(validate_external_url, url)
    identity = uuid4().hex
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if not notify:
        body["id"] = identity
    async with client.stream(
        "POST", url, headers=headers, json=body, follow_redirects=False
    ) as response:
        if response.status_code in {401, 403}:
            raise ValueError(
                "Connector authentication failed; check your personal token"
            )
        response.raise_for_status()
        if notify:
            return {}, response.headers
        if "text/event-stream" in response.headers.get("content-type", ""):
            size = 0
            parts = []
            async for line in response.aiter_lines():
                size += len(line.encode())
                if size > MAX_RESPONSE:
                    raise ValueError("Connector response exceeds 1 MiB")
                if line.startswith("data:"):
                    parts.append(line[5:].lstrip())
                elif not line and parts:
                    message = json.loads("\n".join(parts))
                    parts = []
                    if isinstance(message, dict) and message.get("id") == identity:
                        break
            else:
                raise ValueError("Connector did not return a complete result")
        else:
            chunks = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE:
                    raise ValueError("Connector response exceeds 1 MiB")
                chunks.append(chunk)
            message = json.loads(b"".join(chunks))
        if (
            not isinstance(message, dict)
            or message.get("id") != identity
            or message.get("error")
        ):
            raise ValueError("Connector rejected the request")
        result = message.get("result", {})
        if not isinstance(result, dict):
            raise ValueError("Invalid MCP result object")
        return result, response.headers


async def request(row, installation, method, params=None):
    config = row.config or {}
    url = config.get("url", "")
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if installation and installation.credential:
        headers["Authorization"] = "Bearer " + reveal(installation.credential)
    try:
        async with asyncio.timeout(25), _slots:
            async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                initialized, response_headers = await rpc(
                    client,
                    url,
                    headers,
                    "initialize",
                    {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "PathLab", "version": "1.0.8"},
                    },
                )
                session_id = response_headers.get("mcp-session-id")
                if session_id:
                    headers["Mcp-Session-Id"] = session_id
                headers["MCP-Protocol-Version"] = initialized.get(
                    "protocolVersion", "2025-03-26"
                )
                try:
                    await rpc(
                        client, url, headers, "notifications/initialized", notify=True
                    )
                    result, _ = await rpc(client, url, headers, method, params)
                    return result
                finally:
                    if session_id:
                        try:
                            await client.delete(
                                url, headers=headers, timeout=2, follow_redirects=False
                            )
                        except httpx.HTTPError:
                            pass
    except TimeoutError:
        raise ValueError("Connector timed out; try again shortly") from None
    except httpx.HTTPError:
        raise ValueError(
            "Connector is unavailable; check the HTTPS endpoint and connection"
        ) from None


async def installation_for(db, user, identity):
    row = await get_entry(db, user, identity)
    installed = await db.get(CapabilityInstallation, (str(user.id), identity))
    if row.kind != "connector" or row.builtin or not installed or not installed.enabled:
        raise HTTPException(403, "Enable this personal connector before using it")
    return row, installed


async def connect(db, user, identity):
    row, installed = await installation_for(db, user, identity)
    revision, credential = row.revision, installed.credential
    result = await request(row, installed, "tools/list")
    tools = result.get("tools", [])
    if not isinstance(tools, list) or len(tools) > 100 or result.get("nextCursor"):
        raise ValueError(
            "This connector exceeds the 100-tool catalog limit; expose a scoped endpoint"
        )
    catalog = []
    for tool in tools:
        if (
            not isinstance(tool, dict)
            or not isinstance(tool.get("name"), str)
            or len(tool["name"]) > 160
        ):
            raise ValueError("Invalid MCP tool catalog")
        schema = tool.get("inputSchema", {"type": "object"})
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError:
            raise ValueError("Invalid connector tool schema") from None

        def check_refs(value):
            if isinstance(value, dict):
                if "$ref" in value and not str(value["$ref"]).startswith("#"):
                    raise ValueError(
                        "Connector schema references must stay inside the schema"
                    )
                for nested in value.values():
                    check_refs(nested)
            elif isinstance(value, list):
                for nested in value:
                    check_refs(nested)

        check_refs(schema)
        annotations = tool.get("annotations") or {}
        if not isinstance(annotations, dict):
            raise ValueError("Invalid connector tool annotations")
        catalog.append(
            {
                "name": tool["name"],
                "description": str(tool.get("description", ""))[:2000],
                "inputSchema": schema,
                "annotations": annotations,
            }
        )
    if len(json.dumps(catalog)) > 48000:
        raise ValueError("Connector catalog exceeds context budget")
    await db.refresh(row)
    installed = await db.scalar(
        select(CapabilityInstallation)
        .where(
            CapabilityInstallation.user_id == str(user.id),
            CapabilityInstallation.entry_id == identity,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        row.archived
        or row.revision != revision
        or not installed
        or not installed.enabled
        or installed.credential != credential
    ):
        raise ValueError(
            "Connector settings changed while connecting; retry with current settings"
        )
    await get_entry(db, user, identity)
    installed.tool_catalog = catalog
    installed.connected_revision = revision
    installed.checked_at = utc_now()
    await db.commit()
    return {"connected": True, "tool_count": len(catalog)}


async def catalog(db, user, identity):
    row, installed = await installation_for(db, user, identity)
    if installed.connected_revision != row.revision:
        raise ValueError("Reconnect this connector after its definition changed")
    return row, installed


async def call(db, user, identity, tool_name, arguments, execution_mode="standard"):
    row, installed = await catalog(db, user, identity)
    tool = next(
        (tool for tool in installed.tool_catalog if tool["name"] == tool_name), None
    )
    if not tool:
        raise ValueError("Tool is not in the connected catalog")
    if (execution_mode == "read_only" or not user.can_use_gpu()) and tool[
        "annotations"
    ].get("readOnlyHint") is not True:
        raise HTTPException(
            403, "This account or workspace permits read-only connector tools"
        )
    if len(json.dumps(arguments)) > 32000:
        raise ValueError("Connector arguments exceed 32 KiB")
    try:
        Draft202012Validator(tool["inputSchema"]).validate(arguments)
    except ValidationError:
        raise ValueError("Arguments do not match this connector tool") from None
    result = await request(
        row, installed, "tools/call", {"name": tool_name, "arguments": arguments}
    )
    # Only text/structured evidence enters model context. No binary payload dumps.
    output = {
        "isError": bool(result.get("isError")),
        "content": [
            item
            for item in result.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        ][:20],
    }
    if "structuredContent" in result:
        output["structuredContent"] = result["structuredContent"]
    encoded = json.dumps(output, ensure_ascii=False)
    if installed.credential:
        encoded = encoded.replace(reveal(installed.credential), "[credential redacted]")
    return encoded[:24000]
