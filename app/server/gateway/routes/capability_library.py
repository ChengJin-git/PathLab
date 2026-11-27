"""Skill/connector library: private management, public discovery, personal installs."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, or_, func, select, delete
from sqlalchemy.orm import defer
from backend.auth import User, current_active_user
from backend.database import get_db
from backend.database.models import CapabilityEntry, CapabilityInstallation
from backend.services import capability_library as service
from backend.services import skill_packages

router = APIRouter(prefix="/capabilities", tags=["Skills and connectors"])
from .skill_files import router as files_router

router.include_router(files_router, prefix="")


class EntryBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["skill", "connector"]
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=1200)
    visibility: Literal["private", "public"] = "private"
    content: str = Field("", max_length=128000)
    url: str = Field("", max_length=2048)
    revision: int | None = None
    source_url: str = Field('', max_length=2048)

    @model_validator(mode="after")
    def valid(self):
        if self.source_url:
            from backend.services.capability_sources import github_url
            github_url(self.source_url)
        if self.kind == "skill":
            from backend.autoresearch.engine.skills import parse_markdown

            parse_markdown(self.content)
            if not self.source_url:
                from backend.services.capability_sources import markdown_source
                self.source_url = markdown_source(self.content)
            if not self.description:
                metadata, body = parse_markdown(self.content)
                self.description = str(
                    metadata.get("description") or body[:300]
                ).replace("\n", " ")[:1200]
        else:
            parsed = urlparse(self.url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "Use an HTTPS MCP endpoint without credentials, query or fragment; store your token separately"
                )
        return self


def payload(row, installation, user, language, detail=False):
    return service.serialize(row, installation, user, language, detail=detail)


@router.get("")
async def listing(
    kind: Literal["skill", "connector"],
    view: Literal["installed", "discover", "mine", "all"] = "installed",
    q: str = Query("", max_length=100),
    cursor: str = Query("", max_length=2048),
    limit: int = Query(20, ge=1, le=20),
    language: Literal["en-US", "zh-CN", "zh-HK"] = "en-US",
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    if view == "all" and not user.is_admin():
        raise HTTPException(403, "Administrator access required")
    installed = CapabilityInstallation
    query = (
        select(CapabilityEntry, installed)
        .options(defer(CapabilityEntry.content))
        .outerjoin(
            installed,
            and_(
                installed.entry_id == CapabilityEntry.entry_id,
                installed.user_id == str(user.id),
            ),
        )
        .where(
            CapabilityEntry.kind == kind,
            CapabilityEntry.archived.is_(False),
            service.visible(user),
        )
    )
    if view == "installed":
        query = query.where(
            or_(
                CapabilityEntry.builtin.is_(True),
                CapabilityEntry.owner_id == str(user.id),
                installed.user_id.isnot(None),
            )
        )
    elif view == "mine":
        query = query.where(CapabilityEntry.owner_id == str(user.id))
    elif view == "discover":
        query = query.where(
            or_(
                CapabilityEntry.visibility == "public",
                CapabilityEntry.builtin.is_(True),
            )
        )
    if q.strip():
        pattern = (
            "%"
            + q.strip()
            .lower()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            + "%"
        )
        from backend.services.command_catalog import LABELS

        builtin_matches = [
            key
            for key, labels in LABELS.items()
            if q.lower()
            in (" ".join(" ".join(pair) for pair in labels) + " " + key).lower()
        ]
        query = query.where(
            or_(
                func.lower(
                    CapabilityEntry.name + " " + CapabilityEntry.description
                ).like(pattern, escape="\\"),
                CapabilityEntry.entry_id.in_(builtin_matches),
            )
        )
    fingerprint = hashlib.sha256(
        json.dumps([str(user.id), user.role, kind, view, q]).encode()
    ).hexdigest()[:16]
    if cursor:
        try:
            data = json.loads(base64.urlsafe_b64decode(cursor))
            if data["scope"] != fingerprint:
                raise ValueError()
            query = query.where(CapabilityEntry.entry_id > data["after"])
        except Exception:
            raise HTTPException(422, "Invalid catalog cursor") from None
    rows = (
        await db.execute(query.order_by(CapabilityEntry.entry_id).limit(limit + 1))
    ).all()
    next_cursor = (
        base64.urlsafe_b64encode(
            json.dumps(
                {"scope": fingerprint, "after": rows[limit - 1][0].entry_id}
            ).encode()
        ).decode()
        if len(rows) > limit
        else None
    )
    return {
        "items": [
            payload(row, installation, user, language)
            for row, installation in rows[:limit]
        ],
        "next_cursor": next_cursor,
    }


@router.post("")
async def create(
    body: EntryBody, user: User = Depends(current_active_user), db=Depends(get_db)
):
    row, installed = await create_record(body, user, db)
    await db.commit()
    return payload(row, installed, user, "en-US", True)


async def create_record(body, user, db):
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy import text

        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "capability-create:" + str(user.id)},
        )
    count = await db.scalar(
        select(func.count())
        .select_from(CapabilityEntry)
        .where(
            CapabilityEntry.owner_id == str(user.id),
            CapabilityEntry.archived.is_(False),
        )
    )
    if count >= 200:
        raise HTTPException(409, "A personal library supports up to 200 definitions")
    identity = "ugc-" + uuid4().hex
    row = CapabilityEntry(
        entry_id=identity,
        owner_id=str(user.id),
        kind=body.kind,
        name=body.name,
        description=body.description,
        visibility=body.visibility,
        content=body.content if body.kind == "skill" else "",
        config={"url": body.url, "transport": "streamable_http"}
        if body.kind == "connector"
        else {},
    )
    installed = CapabilityInstallation(
        user_id=str(user.id), entry_id=identity, enabled=True
    )
    db.add(row)
    if body.source_url:
        row.config = {**row.config, 'github_source': {'url': body.source_url}}
    db.add(installed)
    await db.flush()
    return row, installed


@router.post("/import-skill")
async def import_skill(
    file: UploadFile = File(...),
    visibility: Literal["private", "public"] = "private",
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    from backend.autoresearch.engine.skills import (
        unpack_zip,
        inspect_files,
    )

    data = await file.read(16 * 1024 * 1024 + 1)
    await file.close()
    if len(data) > 16 * 1024 * 1024:
        raise HTTPException(413, "Skill uploads are limited to 16 MiB")
    try:
        files = (
            await asyncio.to_thread(unpack_zip, data)
            if (file.filename or "").lower().endswith((".zip", ".skill"))
            else {"SKILL.md": (data, False)}
        )
        imported, files = await asyncio.to_thread(inspect_files, files, str(user.id))
        if len(imported["skills"]) != 1:
            raise ValueError("Import one skill entrypoint at a time")
        skill = imported["skills"][0]
        from backend.autoresearch.engine.skills import parse_markdown

        metadata, _ = parse_markdown(skill["content"])
        body = EntryBody(
            kind="skill",
            name=skill["name"],
            description=str(metadata.get("description", ""))[:1200],
            content=skill["content"],
            visibility=visibility,
        )
        row, installed = await create_record(body, user, db)
        await skill_packages.publish(
            db, row, files, skill["entrypoint"], increment=False
        )
        return payload(row, installed, user, "en-US", True)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/{identity}")
async def detail(
    identity: str,
    language: Literal["en-US", "zh-CN", "zh-HK"] = "en-US",
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    row = await service.get_entry(db, user, identity)
    return payload(
        row,
        await db.get(CapabilityInstallation, (str(user.id), identity)),
        user,
        language,
        True,
    )


@router.put("/{identity}")
async def edit(
    identity: str,
    body: EntryBody,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    row = await service.get_entry(db, user, identity, edit=True)
    if body.revision != row.revision:
        raise HTTPException(409, "This entry changed; refresh before saving")
    if body.kind != row.kind:
        raise HTTPException(422, "Entry type cannot change")
    row.name = body.name
    row.description = body.description
    row.visibility = body.visibility
    config = dict(row.config or {})
    current_source = config.get('github_source', {})
    if body.source_url and body.source_url != current_source.get('url'):
        config['github_source'] = {'url': body.source_url}
    elif not body.source_url:
        config.pop('github_source', None)
    row.config = config
    if row.kind == "skill":
        files = await asyncio.to_thread(skill_packages.read_files, row)
        entrypoint = skill_packages.entrypoint(row)
        files[entrypoint] = (body.content.encode("utf-8"), files[entrypoint][1])
        await skill_packages.publish(db, row, files, entrypoint)
    else:
        row.content = ""
        row.config = {**config, "url": body.url, "transport": "streamable_http"}
        row.revision += 1
        await db.commit()
    return payload(
        row,
        await db.get(CapabilityInstallation, (str(user.id), identity)),
        user,
        "en-US",
        True,
    )


@router.delete("/{identity}")
async def remove(
    identity: str, user: User = Depends(current_active_user), db=Depends(get_db)
):
    row = await service.get_entry(db, user, identity, edit=True)
    row.archived = True
    await db.execute(
        delete(CapabilityInstallation).where(
            CapabilityInstallation.entry_id == identity
        )
    )
    await db.commit()
    package = skill_packages.package_path(row)
    if package:
        package.unlink(missing_ok=True)
    return {"deleted": True}


class InstallationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    token: str | None = Field(None, max_length=8192)


@router.put("/{identity}/installation")
async def install(
    identity: str,
    body: InstallationBody,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    row = await service.get_entry(db, user, identity)
    installed = await db.get(CapabilityInstallation, (str(user.id), identity))
    if not installed:
        installed = CapabilityInstallation(user_id=str(user.id), entry_id=identity)
        db.add(installed)
    installed.enabled = body.enabled
    if body.token is not None:
        if row.kind != "connector" or row.builtin:
            raise HTTPException(422, "This entry does not accept a personal token")
        installed.credential = service.protect(body.token) if body.token else None
        installed.connected_revision = None
        installed.tool_catalog = []
    if not body.enabled and row.kind == "connector" and not row.builtin:
        installed.connected_revision = None
        installed.tool_catalog = []
    await db.commit()
    return payload(row, installed, user, "en-US")


@router.delete("/{identity}/installation")
async def uninstall(
    identity: str, user: User = Depends(current_active_user), db=Depends(get_db)
):
    await service.get_entry(db, user, identity)
    await db.execute(
        delete(CapabilityInstallation).where(
            CapabilityInstallation.user_id == str(user.id),
            CapabilityInstallation.entry_id == identity,
        )
    )
    await db.commit()
    return {"removed": True}


@router.post("/{identity}/connect")
async def connect(
    identity: str, user: User = Depends(current_active_user), db=Depends(get_db)
):
    from backend.services.personal_connectors import connect as test_connection

    try:
        return await test_connection(db, user, identity)
    except (ValueError, TimeoutError) as exc:
        raise HTTPException(422, str(exc)) from None


class SyncBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int
    source_url: str | None = Field(None, max_length=2048)


@router.post('/{identity}/sync-github')
async def sync_github(identity: str, body: SyncBody, user: User = Depends(current_active_user), db=Depends(get_db)):
    from backend.services import capability_sources
    import httpx
    row = await service.get_entry(db, user, identity)
    try:
        row = await capability_sources.sync(db, row, user, body.revision, body.source_url)
    except (ValueError, TimeoutError, httpx.HTTPError) as exc:
        raise HTTPException(422, str(exc) if isinstance(exc, ValueError) else 'GitHub synchronization unavailable; retry later') from None
    return payload(row, await db.get(CapabilityInstallation, (str(user.id), identity)), user, 'en-US', True)


@router.get('/{identity}/logo')
async def logo(identity: str, user: User = Depends(current_active_user), db=Depends(get_db)):
    from pathlib import Path
    from fastapi.responses import FileResponse
    from backend.common.config import Config
    row = await service.get_entry(db, user, identity)
    filename = ((row.config or {}).get('logo') or {}).get('file', '')
    import re
    if not re.fullmatch(r'[a-f0-9]{64}\.(png|svg)', filename):
        raise HTTPException(404, 'Logo unavailable')
    path = Config.get_autoresearch_dir() / 'capability-icons' / filename
    if not path.is_file(): raise HTTPException(404, 'Logo unavailable')
    return FileResponse(path, headers={'Content-Security-Policy':'sandbox', 'X-Content-Type-Options':'nosniff', 'Cache-Control':'private, max-age=3600'})
