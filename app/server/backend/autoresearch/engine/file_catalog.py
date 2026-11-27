"""Incremental metadata catalog. Directory walking is background work, never search.

Each DB batch and emitted artifact summary is bounded. Large generated collections
remain directories and can be indexed explicitly through the browse endpoint.
"""

import asyncio
import hashlib
import os
import time
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import delete, select, case
from backend.database.database import safe_session
from backend.database.models import AutoResearchSession, WorkbenchFile, utc_now

EXCLUDED = {".git", ".opencode", ".venv", "node_modules", "__pycache__"}


def batches(root, directory, row):
    stack, batch = [directory], []
    while stack:
        parent = stack.pop()
        try:
            with os.scandir(parent) as entries:
                for entry in entries:
                    if (
                        entry.name.startswith(".")
                        or entry.name in EXCLUDED
                        or entry.name in {"opencode.json", "AGENTS.md"}
                        or entry.is_symlink()
                    ):
                        continue
                    relative = str(Path(entry.path).relative_to(root))
                    try:
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    is_dir = entry.is_dir(follow_symlinks=False)
                    batch.append(
                        dict(
                            file_id=hashlib.sha256(
                                f"{row.session_id}:{relative}".encode()
                            ).hexdigest(),
                            user_id=row.user_id,
                            workspace_id=(row.recovery_metadata or {}).get(
                                "workspace_id"
                            ),
                            session_id=row.session_id,
                            conversation_id=row.chat_conversation_id,
                            name=entry.name,
                            path=relative,
                            parent=""
                            if Path(relative).parent == Path(".")
                            else str(Path(relative).parent),
                            kind="directory" if is_dir else "file",
                            size=stat.st_size,
                            revision=f"{stat.st_mtime_ns}:{stat.st_size}",
                            updated_at=utc_now(),
                        )
                    )
                    # Lazy directory browsing: never recursively enumerate an
                    # experiment's tiles, dependencies or previous run snapshots.
                    if len(batch) == 200:
                        yield batch
                        batch = []
        except (FileNotFoundError, PermissionError):
            continue
    if batch:
        yield batch


async def index_tree(row, directory=None):
    root = Path(row.workspace_path)
    directory = directory or root
    iterator = iter(batches(root, directory, row))
    count, sample = 0, []
    started = utc_now()
    deadline = time.monotonic() + 20
    truncated = False
    # Register ancestors so an output catalog is reachable from the root browser.
    ancestors = []
    current = directory
    while current != root and current.is_relative_to(root):
        relative = str(current.relative_to(root))
        ancestors.append(
            dict(
                file_id=hashlib.sha256(
                    f"{row.session_id}:{relative}".encode()
                ).hexdigest(),
                user_id=row.user_id,
                workspace_id=(row.recovery_metadata or {}).get("workspace_id"),
                session_id=row.session_id,
                conversation_id=row.chat_conversation_id,
                name=current.name,
                path=relative,
                parent=""
                if current.parent == root
                else str(current.parent.relative_to(root)),
                kind="directory",
                size=0,
                revision="",
                updated_at=utc_now(),
            )
        )
        current = current.parent
    if ancestors:
        async with safe_session() as db:
            current = await db.scalar(
                select(AutoResearchSession)
                .where(AutoResearchSession.session_id == row.session_id)
                .with_for_update()
            )
            if current is None or (current.recovery_metadata or {}).get(
                "delete_requested"
            ):
                return {"items": [], "count": 0, "truncated": False}
            statement = insert(WorkbenchFile).values(ancestors)
            await db.execute(
                statement.on_conflict_do_nothing(index_elements=[WorkbenchFile.file_id])
            )
            await db.commit()
    try:
        while batch := await asyncio.to_thread(next, iterator, None):
            from backend.services.file_library import (
                snapshot_file,
                initial_index_status,
            )

            async with safe_session() as db:
                current = await db.scalar(
                    select(AutoResearchSession)
                    .where(AutoResearchSession.session_id == row.session_id)
                    .with_for_update()
                )
                if current is None or (current.recovery_metadata or {}).get(
                    "delete_requested"
                ):
                    return {"items": [], "count": 0, "truncated": False}
                # Serialize snapshot publication with file edits/deletion and chat cleanup.
                existing = {
                    item.file_id: item
                    for item in (
                        await db.scalars(
                            select(WorkbenchFile)
                            .where(
                                WorkbenchFile.file_id.in_(
                                    [entry["file_id"] for entry in batch]
                                )
                            )
                            .order_by(WorkbenchFile.file_id)
                            .with_for_update()
                        )
                    ).all()
                }
                batch = [
                    entry
                    for entry in batch
                    if entry["file_id"] not in existing
                    or (
                        not existing[entry["file_id"]].deleted
                        and (
                            entry["kind"] == "directory"
                            or existing[entry["file_id"]].source_revision
                            != entry["revision"]
                        )
                    )
                ]
                if not batch:
                    if time.monotonic() >= deadline:
                        truncated = True
                        break
                    continue
                for entry in batch:
                    old = existing.get(entry["file_id"])
                    entry.update(
                        storage_path=None,
                        origin="generated",
                        source_title=row.recovery_metadata['title'],
                    )
                    entry["source_revision"] = entry["revision"]
                    if old:
                        entry["name"] = old.name
                    if entry["kind"] == "file":
                        write = asyncio.create_task(
                            asyncio.to_thread(
                                snapshot_file,
                                root / entry["path"],
                                row.user_id,
                                entry["file_id"],
                            )
                        )
                        try:
                            (
                                entry["storage_path"],
                                entry["revision"],
                            ) = await asyncio.shield(write)
                        except asyncio.CancelledError:
                            saved, _ = await write
                            if not old or old.storage_path != saved:
                                Path(saved).unlink(missing_ok=True)
                            raise
                    entry["index_status"] = (
                        initial_index_status(entry["name"], entry["size"])
                        if entry["kind"] == "file"
                        else "none"
                    )
                statement = insert(WorkbenchFile).values(batch)
                await db.execute(
                    statement.on_conflict_do_update(
                        index_elements=[WorkbenchFile.file_id],
                        set_={
                            key: getattr(statement.excluded, key)
                            for key in (
                                "name",
                                "parent",
                                "kind",
                                "size",
                                "revision",
                                "updated_at",
                                "conversation_id",
                                "storage_path",
                                "source_revision",
                                "origin",
                                "source_title",
                            )
                        }
                        | {
                            "index_status": case(
                                (
                                    WorkbenchFile.revision
                                    != statement.excluded.revision,
                                    statement.excluded.index_status,
                                ),
                                else_=WorkbenchFile.index_status,
                            )
                        },
                        where=WorkbenchFile.deleted.is_(False),
                    )
                )
                await db.commit()
            from backend.services.document_preview import schedule_preview
            for entry in batch:
                if entry.get("storage_path"):
                    schedule_preview(Path(entry["storage_path"]), entry["name"])
            count += len(batch)
            sample.extend(
                {
                    "path": r["path"],
                    "name": r["name"],
                    "size": r["size"],
                    "kind": r["kind"],
                }
                for r in batch[: max(0, 40 - len(sample))]
            )
            await asyncio.sleep(0)
            if count >= 10000 or time.monotonic() >= deadline:
                truncated = True
                break
    finally:
        iterator.close()
    if not truncated:
        async with safe_session() as db:
            parent = "" if directory == root else str(directory.relative_to(root))
            await db.execute(
                delete(WorkbenchFile).where(
                    WorkbenchFile.session_id == row.session_id,
                    WorkbenchFile.parent == parent,
                    WorkbenchFile.updated_at < started,
                    WorkbenchFile.kind == "directory",
                )
            )
            await db.commit()
    return {"items": sample, "count": count, "truncated": truncated}
