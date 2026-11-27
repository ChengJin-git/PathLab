"""Skill package file management, authorized on every request."""

from __future__ import annotations

import asyncio
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from backend.auth import User, current_active_user
from backend.database import get_db
from backend.services.capability_library import get_entry
from backend.services import skill_packages as packages
from backend.autoresearch.engine.skills import MAX_FILE_BYTES, unpack_zip

router = APIRouter(tags=["Skill package files"])


async def skill(db, user, identity, revision=None):
    row = await get_entry(
        db, user, identity, edit=revision is not None, read=revision is None
    )
    if row.kind != "skill" or row.builtin:
        raise HTTPException(422, "Choose a user-created skill")
    if revision is not None:
        packages.check_revision(row, revision)
    return row


@router.get("/{identity}/files")
async def listing(
    identity: str,
    q: str = Query("", max_length=100),
    after: str = Query("", max_length=512),
    limit: int = Query(50, ge=1, le=50),
    revision: int | None = None,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    row = await skill(db, user, identity)
    if revision is not None:
        packages.check_revision(row, revision)
    return await asyncio.to_thread(packages.manifest, row, q, after, limit)


@router.get("/{identity}/file")
async def read(
    identity: str,
    path: str = Query(..., max_length=512),
    download: bool = False,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    row = await skill(db, user, identity)
    try:
        data, executable = await asyncio.to_thread(packages.read_file, row, path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if download:
        return Response(
            data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(path.split("/")[-1], safe=""),
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )
    return {
        "path": path,
        "revision": row.revision,
        "size": len(data),
        "executable": executable,
        "text": packages.text_content(data),
    }


class FileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=packages.MAX_TEXT_BYTES)
    executable: bool = False
    overwrite: bool = False


async def put_file(db, row, path, data, executable, overwrite):
    name = packages.resource_path(path)
    files = await asyncio.to_thread(packages.read_files, row)
    if name in files and not overwrite:
        raise HTTPException(409, "A file with this path already exists")
    files[name] = (
        data,
        executable if executable is not None else files.get(name, (b"", False))[1],
    )
    await packages.publish(db, row, files, packages.entrypoint(row))
    return {"revision": row.revision, "path": name}


@router.put("/{identity}/file")
async def edit(
    identity: str,
    body: FileBody,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    row = await skill(db, user, identity, body.revision)
    data = body.content.encode("utf-8")
    if packages.text_content(data) is None:
        raise HTTPException(
            422, "Use a UTF-8 text file up to 256 KiB, or upload the file"
        )
    try:
        return await put_file(db, row, body.path, data, body.executable, body.overwrite)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/{identity}/file")
async def upload(
    identity: str,
    revision: int = Query(..., ge=1),
    path: str = Query(..., max_length=512),
    overwrite: bool = False,
    executable: bool | None = None,
    file: UploadFile = File(...),
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    row = await skill(db, user, identity, revision)
    data = await file.read(MAX_FILE_BYTES + 1)
    await file.close()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "Skill files are limited to 16 MiB")
    try:
        return await put_file(db, row, path, data, executable, overwrite)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.delete("/{identity}/file")
async def remove(
    identity: str,
    revision: int = Query(..., ge=1),
    path: str = Query(..., max_length=512),
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    row = await skill(db, user, identity, revision)
    try:
        name = packages.resource_path(path)
        if name == packages.entrypoint(row):
            raise HTTPException(
                422, "Keep the skill entrypoint; replace the package to change it"
            )
        files = await asyncio.to_thread(packages.read_files, row)
        if name not in files:
            raise HTTPException(404, "Skill file not found")
        del files[name]
        await packages.publish(db, row, files, packages.entrypoint(row))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"revision": row.revision}


@router.put("/{identity}/package")
async def replace(
    identity: str,
    revision: int = Query(..., ge=1),
    file: UploadFile = File(...),
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    row = await skill(db, user, identity, revision)
    data = await file.read(MAX_FILE_BYTES + 1)
    await file.close()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "Skill uploads are limited to 16 MiB")
    try:
        files = await asyncio.to_thread(unpack_zip, data)
        await packages.publish(db, row, files)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"revision": row.revision, "entrypoint": packages.entrypoint(row)}
