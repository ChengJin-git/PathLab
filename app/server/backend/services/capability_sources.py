"""GitHub-backed capability revisions and locally served, validated artwork."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit

import httpx
from fastapi import HTTPException

from backend.common.config import Config
from backend.autoresearch.engine.skill_imports import fetch
from backend.autoresearch.engine.skills import unpack_zip, inspect_files


def github_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname
        not in {"github.com", "www.github.com", "raw.githubusercontent.com"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Use a public GitHub repository, directory or SKILL.md URL")
    parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
    if len(parts) < 2 or any(
        not part or part in {".", ".."} or not re.fullmatch(r"[\w. -]+", part)
        for part in parts
    ):
        raise ValueError("Invalid GitHub source path")
    return value.strip().rstrip("/")


def source_for(row):
    config = row.config or {}
    if config.get("github_source"):
        return config["github_source"]
    if config.get("source_url"):
        try:
            return {"url": github_url(config["source_url"])}
        except ValueError:
            pass
    if row.builtin and row.kind == "skill":
        from backend.autoresearch.engine.builtin_skills import catalog, LIBRARY

        entry = next(
            (entry for entry in catalog() if entry["id"] == row.entry_id), None
        )
        if entry and entry.get("repository"):
            lock = json.loads((LIBRARY / "sources.lock.json").read_text())
            origin = next(
                item
                for item in lock["sources"]
                if item["repository"] == entry["repository"]
            )
            relative = str(
                PurePosixPath(entry["entry"]).relative_to(origin["directory"])
            )
            return {
                "url": entry["repository"],
                "path": relative,
                "commit": entry["commit"],
            }
    return None


def markdown_source(content):
    from backend.autoresearch.engine.skills import parse_markdown

    metadata, _ = parse_markdown(content)
    for key in ("source_url", "repository", "homepage"):
        value = metadata.get(key)
        if isinstance(value, str):
            try:
                return github_url(value)
            except ValueError:
                pass
    return ""


def sync_allowed(row, user):
    return user.is_admin() or (not row.builtin and row.owner_id == str(user.id))


async def download_source(url: str, selected_path: str = "", selected_ref: str = ""):
    github_url(url)
    parsed = urlsplit(url)
    parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
    owner, repo = parts[:2]
    repo = repo.removesuffix(".git")
    rest = (
        parts[2:]
        if parsed.hostname == "raw.githubusercontent.com"
        else parts[3:]
        if len(parts) > 2 and parts[2] in {"tree", "blob"}
        else []
    )
    if (
        len(parts) > 2
        and parsed.hostname != "raw.githubusercontent.com"
        and parts[2] not in {"tree", "blob"}
    ):
        raise ValueError("Use a repository, tree or blob URL")
    api = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}"
    async with (
        asyncio.timeout(90),
        httpx.AsyncClient(timeout=30, trust_env=False) as client,
    ):
        metadata = json.loads((await fetch(client, api))[0])
        ref = selected_ref or metadata["default_branch"]
        path = selected_path
        if rest:
            resolved = False
            for count in range(min(len(rest), 8), 0, -1):
                try:
                    commit = json.loads(
                        (
                            await fetch(
                                client,
                                api
                                + "/commits/"
                                + quote("/".join(rest[:count]), safe=""),
                            )
                        )[0]
                    )["sha"]
                    ref = "/".join(rest[:count])
                    path = "/".join(rest[count:])
                    resolved = True
                    break
                except ValueError:
                    continue
            if not resolved:
                raise ValueError("GitHub branch or path not found")
        else:
            commit = json.loads(
                (await fetch(client, api + "/commits/" + quote(ref, safe="")))[0]
            )["sha"]
        data = (
            await fetch(
                client, f"https://codeload.github.com/{owner}/{repo}/zip/{commit}"
            )
        )[0]
    files = await asyncio.to_thread(unpack_zip, data)
    return files, {
        "url": f"https://github.com/{owner}/{repo}",
        "ref": ref,
        "path": path,
        "commit": commit,
        "description": (metadata.get("description") or "")[:1200],
        "license": (metadata.get("license") or {}).get("spdx_id") or "NOASSERTION",
    }


def store_logo(data: bytes, suffix: str, origin: dict, path: str):
    if len(data) > 2 * 1024 * 1024:
        return None
    if suffix == ".svg":
        from xml.etree import ElementTree as ET

        if b"<!" in data or b"\x00" in data:
            return None
        try:
            root = ET.fromstring(data)
            if root.tag.split("}")[-1] != "svg":
                return None
            allowed = {
                "svg",
                "g",
                "path",
                "rect",
                "circle",
                "ellipse",
                "line",
                "polyline",
                "polygon",
                "defs",
                "linearGradient",
                "radialGradient",
                "stop",
                "clipPath",
                "mask",
                "title",
                "desc",
                "use",
                "symbol",
            }
            for element in root.iter():
                if element.tag.split("}")[-1] not in allowed:
                    return None
                for key, value in element.attrib.items():
                    name = key.split("}")[-1].lower()
                    if (
                        name.startswith("on")
                        or name == "style"
                        or (name in {"href", "src"} and not value.startswith("#"))
                        or (
                            "url(" in value
                            and not re.fullmatch(r"url\(#[\w-]+\)", value)
                        )
                    ):
                        return None
        except Exception:
            return None
    else:
        from PIL import Image
        from io import BytesIO

        try:
            image = Image.open(BytesIO(data))
            if image.width * image.height > 4_000_000:
                return None
            image.thumbnail((512, 512))
            output = BytesIO()
            image.convert("RGBA").save(output, format="PNG")
            data = output.getvalue()
            suffix = ".png"
        except Exception:
            return None
    identity = hashlib.sha256(data).hexdigest() + suffix
    directory = Config.get_autoresearch_dir() / "capability-icons"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / identity
    if not target.exists():
        target.write_bytes(data)
    return {
        "file": identity,
        "source": f"{origin['url']}/blob/{origin['commit']}/{path}",
        "license": origin["license"],
        "kind": "repository",
    }


def find_logo(files, origin):
    path = origin.get("path", "")
    base = str(PurePosixPath(path).parent) if path.endswith(".md") else path
    candidates = [
        name
        for name in files
        if PurePosixPath(name).suffix.lower() in {".png", ".svg"}
        and re.search(r"(?:^|[/_.-])(logo|icon)(?:[/_.-]|$)", name, re.I)
    ]
    # Some projects name their artwork after the project. Read explicit logo references.
    import posixpath

    for name, (content, _) in files.items():
        if (
            PurePosixPath(name).name.lower() not in {"readme.md", "skill.md"}
            or len(content) > 128_000
        ):
            continue
        document = content.decode("utf-8", errors="replace")
        references = re.findall(
            r"!\[[^\]]*(?:logo|icon)[^\]]*\]\(([^\s)]+)", document, re.I
        )
        for tag in re.findall(r"<img\b[^>]+>", document, re.I):
            if re.search(r'(?:alt|class)=["\'][^"\']*(?:logo|icon)', tag, re.I):
                references.extend(re.findall(r'src=["\']([^"\']+)', tag, re.I))
        for reference in references:
            candidate = posixpath.normpath(
                posixpath.join(posixpath.dirname(name), reference)
            )
            if candidate in files and PurePosixPath(candidate).suffix.lower() in {
                ".png",
                ".svg",
            }:
                candidates.append(candidate)
    candidates.sort(
        key=lambda name: (
            not name.startswith(base + "/") if base else False,
            len(PurePosixPath(name).parts),
            len(files[name][0]),
        )
    )
    for name in candidates[:12]:
        logo = store_logo(
            files[name][0], PurePosixPath(name).suffix.lower(), origin, name
        )
        if logo:
            return logo
    return None


async def sync(db, row, user, revision: int, source_url: str | None = None):
    from . import capability_library, skill_packages
    from backend.database.models import CapabilityInstallation
    from sqlalchemy import update

    if not sync_allowed(row, user):
        raise HTTPException(
            403, "Only the owner or administrator can synchronize this entry"
        )
    if revision != row.revision:
        raise HTTPException(409, "This entry changed; refresh before synchronizing")
    source = source_for(row) or {}
    url = source_url or source.get("url")
    if not url:
        raise HTTPException(422, "Add a GitHub source first")
    identity = row.entry_id
    await db.commit()
    files, origin = await download_source(
        url,
        source.get("path", "")
        if not source_url or source_url == source.get("url")
        else "",
        source.get("ref", "")
        if not source_url or source_url == source.get("url")
        else "",
    )
    selected = None
    if row.kind == "skill":
        preview, files = await asyncio.to_thread(
            inspect_files, files, "", url, origin["path"] or None
        )
        if len(preview["skills"]) != 1:
            raise HTTPException(
                422, "Use a directory or SKILL.md URL identifying one skill"
            )
        selected = preview["skills"][0]["entrypoint"]
        origin["path"] = selected
    logo = await asyncio.to_thread(find_logo, files, origin)
    await capability_library.get_entry(db, user, identity, read=False)
    from backend.database.models import CapabilityEntry
    from sqlalchemy import select

    row = await db.scalar(
        select(CapabilityEntry)
        .where(
            CapabilityEntry.entry_id == identity, CapabilityEntry.archived.is_(False)
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not row or not sync_allowed(row, user):
        raise HTTPException(404, "Capability unavailable")
    if row.revision != revision:
        raise HTTPException(
            409, "This entry changed while downloading; refresh before synchronizing"
        )
    from datetime import datetime, timezone

    origin["synced_at"] = datetime.now(timezone.utc).isoformat()
    config = {**(row.config or {}), "github_source": origin}
    if logo:
        config["logo"] = logo
    else:
        config.pop("logo", None)
    row.config = config
    if row.kind == "skill":
        await skill_packages.publish(db, row, files, selected)
    else:
        # Connector endpoint and private credentials are never taken from a README.
        row.revision += 1
        await db.execute(
            update(CapabilityInstallation)
            .where(
                CapabilityInstallation.entry_id == identity,
                CapabilityInstallation.connected_revision == revision,
            )
            .values(connected_revision=row.revision)
        )
        await db.commit()
    return row
