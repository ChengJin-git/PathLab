"""Editable, immutable skill package revisions; database points to the published copy."""

from __future__ import annotations

import asyncio
import os
import stat
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from backend.common.config import Config
from backend.autoresearch.engine.skills import inspect_files, safe_path, unpack_zip

MAX_TEXT_BYTES = 256 * 1024


def package_path(row):
    filename = (row.config or {}).get("package_file")
    if not filename:
        return None
    if (
        Path(filename).name != filename
        or not filename.startswith(row.entry_id + "-")
        or not filename.endswith(".zip")
    ):
        raise ValueError("Invalid stored skill package")
    return Config.get_autoresearch_dir() / "capability-packages" / filename


def entrypoint(row):
    return (row.config or {}).get("entrypoint", "SKILL.md")


def read_files(row):
    path = package_path(row)
    if path is None:
        return {entrypoint(row): (row.content.encode("utf-8"), False)}
    return unpack_zip(path.read_bytes(), strip_root=False)


def text_content(data):
    if len(data) > MAX_TEXT_BYTES:
        return None
    try:
        value = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return (
        value
        if not any(ord(char) < 32 and char not in "\n\r\t" for char in value)
        else None
    )


def write_archive(destination, files):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for name, (data, executable) in files.items():
                info = zipfile.ZipInfo(name)
                info.external_attr = (
                    stat.S_IFREG | (0o755 if executable else 0o644)
                ) << 16
                archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


async def publish(db, row, files, selected=None, *, increment=True):
    # Finish the durable write/commit if the client disconnects during publication.
    task = asyncio.create_task(_publish(db, row, files, selected, increment=increment))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


async def _publish(db, row, files, selected=None, *, increment=True):
    """Write before commit, then switch one DB pointer; failed writes never publish."""
    preview, clean = await asyncio.to_thread(inspect_files, files, "", None, selected)
    if len(preview["skills"]) != 1:
        raise ValueError("Choose a package with one skill entrypoint")
    skill = preview["skills"][0]
    old = package_path(row)
    filename = row.entry_id + "-" + uuid4().hex + ".zip"
    destination = Config.get_autoresearch_dir() / "capability-packages" / filename
    try:
        await asyncio.to_thread(write_archive, destination, clean)
        row.config = {**(row.config or {}), "entrypoint": skill["entrypoint"], "package_file": filename}
        row.content = skill["content"]
        if increment:
            row.revision += 1
        await db.commit()
    except BaseException:
        await db.rollback()
        destination.unlink(missing_ok=True)
        raise
    if old:
        old.unlink(missing_ok=True)


def check_revision(row, revision):
    if row.revision != revision:
        raise HTTPException(409, "This skill changed; refresh before saving")


def resource_path(path):
    from backend.autoresearch.engine.skills import SKIP_DIRS

    name = safe_path(path)
    if set(Path(name).parts) & SKIP_DIRS:
        raise ValueError("This directory is excluded from skill packages")
    return name


def read_file(row, path):
    name = resource_path(path)
    if name == entrypoint(row):
        data = row.content.encode("utf-8")
        archive = package_path(row)
        if archive:
            with zipfile.ZipFile(archive) as package:
                return data, bool(package.getinfo(name).external_attr >> 16 & 0o111)
        return data, False
    archive = package_path(row)
    if archive:
        with zipfile.ZipFile(archive) as package:
            if name in package.namelist():
                return package.read(name), bool(
                    package.getinfo(name).external_attr >> 16 & 0o111
                )
    raise HTTPException(404, "Skill file not found")


def manifest(row, query="", after="", limit=50):
    archive = package_path(row)
    if archive:
        with zipfile.ZipFile(archive) as package:
            items = [
                {
                    "path": info.filename,
                    "size": info.file_size,
                    "executable": bool(info.external_attr >> 16 & 0o111),
                }
                for info in package.infolist()
                if not info.is_dir()
            ]
    else:
        items = [
            {
                "path": entrypoint(row),
                "size": len(row.content.encode()),
                "executable": False,
            }
        ]
    items = sorted(
        (
            item
            for item in items
            if query.casefold() in item["path"].casefold() and item["path"] > after
        ),
        key=lambda item: item["path"],
    )
    return {
        "revision": row.revision,
        "entrypoint": entrypoint(row),
        "items": items[:limit],
        "next_cursor": items[limit - 1]["path"] if len(items) > limit else None,
    }
