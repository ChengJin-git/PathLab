"""Durable owner-scoped file library shared by Chat, research and knowledge retrieval."""

from __future__ import annotations
import asyncio
import hashlib
import os
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from backend.common.config import Config
from backend.database.models import WorkbenchFile

MAX_FILE_BYTES = 64 * 1024 * 1024


def permitted(user, column=WorkbenchFile.user_id):
    return True if user.is_admin() else column == str(user.id)


async def owned_file(db, user, identity, *, lock=False):
    query = select(WorkbenchFile).where(
        WorkbenchFile.file_id == identity,
        WorkbenchFile.kind == "file",
        WorkbenchFile.deleted.is_(False),
        permitted(user),
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(404, "File not found")
    return row


def indexable(name, size):
    from .file_preview import TEXT_SUFFIXES

    return size <= MAX_FILE_BYTES and Path(name).suffix.lower() in TEXT_SUFFIXES | {
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
    }


def initial_index_status(name, size):
    return "queued" if indexable(name, size) else "unsupported"


def safe_name(value):
    if (
        not value
        or len(value) > 240
        or value != Path(value).name
        or any(c in value for c in "\\/:\x00\n\r")
        or value.startswith(".")
    ):
        raise HTTPException(422, "Use a filename without directories")
    return value


def store_bytes(owner, identity, name, data):
    root = Config.get_uploads_dir() / "chat-files" / str(owner)
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    path = root / (identity + "-" + digest + Path(name).suffix.lower())
    temporary = root / (".upload-" + uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Content-addressed bytes are immutable. Re-publishing identical data
        # must not change mtime and invalidate versioned previews.
        if not path.exists():
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return str(path), digest


def snapshot_file(source, owner, identity):
    """Preserve completed outputs independently of their execution workspace."""
    source = Path(source)
    root = Config.get_uploads_dir() / "chat-files" / str(owner)
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / (".snapshot-" + uuid4().hex)
    digest = hashlib.sha256()
    before = source.stat()
    try:
        with source.open("rb") as stream, temporary.open("xb") as target:
            while chunk := stream.read(1024 * 1024):
                target.write(chunk)
                digest.update(chunk)
            target.flush()
            os.fsync(target.fileno())
        after = source.stat()
        if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            raise ValueError(
                "Output changed while saving; retry after the write finishes"
            )
        revision = digest.hexdigest()
        destination = root / (identity + "-" + revision + source.suffix.lower())
        if not destination.exists():
            os.replace(temporary, destination)
        return str(destination), revision
    finally:
        temporary.unlink(missing_ok=True)


def public_file(row, source_title=None, owner_name=None):
    from .file_preview import TEXT_SUFFIXES

    return {
        "kind": "file",
        "id": row.file_id,
        "name": row.name,
        "revision": row.revision,
        "size": row.size,
        "folder_id": row.folder_id,
        "origin": row.origin,
        "owner_id": row.user_id,
        "owner_name": owner_name,
        "conversation_id": row.conversation_id,
        "source_title": source_title or row.source_title,
        "session_id": row.session_id,
        "updated_at": row.updated_at.isoformat() + "Z",
        "index_status": row.index_status,
        "index_progress": row.index_progress,
        "index_error": row.index_error,
        "indexed_revision": row.indexed_revision,
        "editable_text": Path(row.name).suffix.lower() in TEXT_SUFFIXES
        and row.size <= 1024 * 1024,
    }


async def persist_upload(db, user, file, *, existing=None):
    name = safe_name(file.filename or "file.txt")
    data = await file.read(MAX_FILE_BYTES + 1)
    await file.close()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "Files are limited to 64 MiB")
    identity = existing.file_id if existing else uuid4().hex
    owner = existing.user_id if existing else str(user.id)
    old = existing.storage_path if existing else None
    write = asyncio.create_task(
        asyncio.to_thread(store_bytes, owner, identity, name, data)
    )
    try:
        path, revision = await asyncio.shield(write)
    except asyncio.CancelledError:
        path, _ = await write
        if path != old:
            Path(path).unlink(missing_ok=True)
        raise
    row = existing or WorkbenchFile(
        file_id=identity, user_id=owner, kind="file", origin="upload"
    )
    row.name = name
    row.storage_path = path
    row.path = path if not row.session_id else row.path
    row.revision = revision
    row.size = len(data)
    from backend.database.models import utc_now

    row.updated_at = utc_now()
    row.index_status = initial_index_status(name, len(data))
    row.indexed_revision = None
    row.index_error = None
    row.index_progress = 0
    db.add(row)
    try:
        await db.commit()
    except BaseException:
        if old != path:
            Path(path).unlink(missing_ok=True)
        raise
    # Keep old immutable bytes for in-flight responses; stale versions are never authorized.
    from .document_preview import schedule_preview
    schedule_preview(Path(path), name)
    return row


def file_cleanup_record(row):
    return {
        "id": row.file_id,
        "owner": row.user_id,
        "storage_path": row.storage_path,
        "path": row.path if not row.session_id else None,
    }


def purge_file(record):
    """Remove immutable versions and retrieval entries from managed file storage."""
    from .knowledge import remove_index

    remove_index(record["owner"], record["id"])
    root = Config.get_uploads_dir() / "chat-files" / record["owner"]
    candidates = set(root.glob(record["id"] + "-*")) | set(
        root.glob(record["id"] + ".*")
    )
    candidates.update(
        Path(value)
        for value in [record.get("storage_path"), record.get("path")]
        if value
    )
    for path in candidates:
        if path.parent.resolve() != root.resolve():
            continue
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
        elif path.is_dir() and path.name.endswith('.preview'):
            import shutil
            shutil.rmtree(path)


async def cleanup_deleted_files(limit=30):
    from backend.database.database import safe_session

    async with safe_session() as db:
        rows = (
            await db.scalars(
                select(WorkbenchFile)
                .where(
                    WorkbenchFile.deleted.is_(True),
                    WorkbenchFile.index_status == "deleted",
                )
                .order_by(WorkbenchFile.updated_at)
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        ).all()
        for row in rows:
            try:
                await asyncio.to_thread(purge_file, file_cleanup_record(row))
                row.index_status, row.index_error = "purged", None
            except Exception:
                row.index_error = (
                    "File cleanup pending; the background worker will retry"
                )
        await db.commit()
