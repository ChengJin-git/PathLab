"""Public GitHub/repository, archive and Markdown import resolution."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote, unquote, urljoin, urlsplit

import httpx

from backend.common.net_guard import validate_external_url

from .skills import MAX_IMPORT_BYTES, SkillImportError, import_files, unpack_zip


async def fetch(client: httpx.AsyncClient, url: str) -> tuple[bytes, str, str]:
    for _ in range(6):
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.scheme not in {"http", "https"}:
            raise SkillImportError("skillUnsupportedUrl")
        try:
            target = await asyncio.to_thread(validate_external_url, url)
        except ValueError as exc:
            raise SkillImportError("skillUnsupportedUrl") from exc
        async with client.stream(
            "GET",
            target,
            follow_redirects=False,
            headers={
                "Accept": "application/vnd.github+json, application/zip, text/markdown, text/plain"
            },
        ) as response:
            if response.is_redirect:
                url = urljoin(target, response.headers.get("location", ""))
                continue
            if response.status_code in {401, 403, 404, 429}:
                raise SkillImportError("skillSourceUnavailable")
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_IMPORT_BYTES:
                    raise SkillImportError("skillTooLarge")
            return bytes(data), response.headers.get("content-type", ""), target
    raise SkillImportError("skillUnsupportedUrl")


async def import_skill(url: str, user_id: str) -> dict:
    async with (
        asyncio.timeout(90),
        httpx.AsyncClient(timeout=30, trust_env=False) as client,
    ):
        parsed = urlsplit(url.strip())
        parts = [unquote(p) for p in parsed.path.strip("/").split("/")]
        if parsed.username or parsed.password or parsed.scheme not in {"http", "https"}:
            raise SkillImportError("skillUnsupportedUrl")
        if parsed.hostname in {
            "github.com",
            "www.github.com",
            "raw.githubusercontent.com",
        }:
            if len(parts) < 2 or any(not p or p in {".", ".."} for p in parts):
                raise SkillImportError("skillUnsupportedUrl")
            owner, repo = parts[:2]
            repo = repo.removesuffix(".git")
            if parsed.hostname == "raw.githubusercontent.com":
                rest = parts[2:]
            elif len(parts) == 2:
                rest = []
            elif parts[2] in {"tree", "blob"}:
                rest = parts[3:]
            elif parts[2] == "archive":
                data, _, _ = await fetch(client, url)
                return await asyncio.to_thread(import_archive, data, user_id, url)
            else:
                raise SkillImportError("skillUnsupportedUrl")
            api = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
            if not rest:
                data, _, _ = await fetch(client, api)
                ref = json.loads(data)["default_branch"]
                data, _, _ = await fetch(client, api + '/commits/' + quote(ref, safe=''))
                ref = json.loads(data)['sha']
                selected = None
            else:
                # Resolve branch names containing slashes instead of silently
                # importing a different branch or treating it as a directory.
                ref, selected = None, None
                lengths = range(min(len(rest), 8), 0, -1)
                for length in lengths:
                    candidate = "/".join(rest[:length])
                    try:
                        data, _, _ = await fetch(
                            client, api + "/commits/" + quote(candidate, safe="")
                        )
                    except SkillImportError as exc:
                        if str(exc) == "skillSourceUnavailable":
                            continue
                        raise
                    ref = json.loads(data)["sha"]
                    selected = "/".join(rest[length:]) or None
                    break
                if not ref:
                    raise SkillImportError("skillSourceUnavailable")
            data, _, _ = await fetch(
                client,
                f"https://codeload.github.com/{owner}/{repo}/zip/{quote(ref, safe='')}",
            )
            return await asyncio.to_thread(
                import_archive, data, user_id, url, selected
            )
        data, content_type, resolved = await fetch(client, url)
        if data.startswith(b"PK\x03\x04") or parsed.path.lower().endswith(
            (".zip", ".skill")
        ):
            return await asyncio.to_thread(import_archive, data, user_id, resolved)
        else:
            if "html" in content_type.lower() or not parsed.path.lower().endswith(
                (".md", ".markdown")
            ):
                raise SkillImportError("skillUnsupportedUrl")
            files = {"SKILL.md": (data, False)}
        return await asyncio.to_thread(import_files, files, user_id, resolved)


def import_archive(data: bytes, user_id: str, url: str, selected: str | None = None) -> dict:
    return import_files(unpack_zip(data), user_id, url, selected)
