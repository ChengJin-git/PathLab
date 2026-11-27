"""The file library is the personal RAG corpus. Metadata operations never parse files."""

import asyncio
import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update, func, or_, and_, cast, String
from backend.auth import current_active_user
from backend.auth.models import User
from backend.database import get_db
from backend.database.models import (
    WorkbenchFile,
    FileLibraryFolder,
    ChatConversation,
    utc_now,
)
from backend.services import file_library as library

router = APIRouter(prefix="/file-library", tags=["File library"])


def file_scope(user, view, owner, q, folder, origin, conversation=""):
    if view == "all" and not user.is_admin():
        raise HTTPException(403, "Administrator access required")
    conditions = [WorkbenchFile.kind == "file", WorkbenchFile.deleted.is_(False)]
    if view == "mine":
        conditions.append(WorkbenchFile.user_id == str(user.id))
    elif owner:
        conditions.append(WorkbenchFile.user_id == owner)
    if q.strip():
        conditions.append(WorkbenchFile.name.icontains(q.strip(), autoescape=True))
    if folder:
        conditions.append(WorkbenchFile.folder_id == folder)
    if origin:
        conditions.append(WorkbenchFile.origin == origin)
    if conversation:
        conditions.append(
            WorkbenchFile.conversation_id.is_(None)
            if conversation == "__unlinked__"
            else WorkbenchFile.conversation_id == conversation
        )
    return conditions


@router.get("/groups")
async def groups(
    q: str = Query("", max_length=120),
    folder: str = Query("", max_length=64),
    origin: Literal["", "upload", "generated"] = "",
    view: Literal["mine", "all"] = "mine",
    owner: str = Query("", max_length=255),
    cursor: str = Query("", max_length=2048),
    limit: int = Query(30, ge=1, le=50),
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    identity = func.coalesce(WorkbenchFile.conversation_id, "__unlinked__")
    grouped = (
        select(
            identity.label("id"),
            func.max(WorkbenchFile.updated_at).label("updated_at"),
            func.count().label("file_count"),
            func.sum(WorkbenchFile.size).label("total_size"),
        )
        .where(*file_scope(user, view, owner, q, folder, origin))
        .group_by(identity)
        .subquery()
    )
    query = select(grouped, ChatConversation.title).outerjoin(
        ChatConversation, ChatConversation.conversation_id == grouped.c.id
    )
    scope = [str(user.id), view, owner, q, folder, origin, "groups"]
    if cursor:
        try:
            date, key, bound = json.loads(base64.urlsafe_b64decode(cursor))
            if bound != scope:
                raise ValueError()
            date = datetime.fromisoformat(date)
            query = query.where(
                or_(
                    grouped.c.updated_at < date,
                    and_(grouped.c.updated_at == date, grouped.c.id < key),
                )
            )
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(422, "Invalid group cursor") from None
    rows = (
        (
            await db.execute(
                query.order_by(grouped.c.updated_at.desc(), grouped.c.id.desc()).limit(
                    limit + 1
                )
            )
        )
        .mappings()
        .all()
    )
    last = rows[limit - 1] if len(rows) > limit else None
    return {
        "items": [
            {**row, "updated_at": row["updated_at"].isoformat() + "Z"}
            for row in rows[:limit]
        ],
        "next_cursor": (
            base64.urlsafe_b64encode(
                json.dumps([last["updated_at"].isoformat(), last["id"], scope]).encode()
            ).decode()
            if last
            else None
        ),
    }


@router.get("")
async def listing(
    q: str = Query("", max_length=120),
    folder: str = Query("", max_length=64),
    origin: Literal["", "upload", "generated"] = "",
    view: Literal["mine", "all"] = "mine",
    owner: str = Query("", max_length=255),
    cursor: str = Query("", max_length=2048),
    limit: int = Query(30, ge=1, le=50),
    conversation: str = Query("", max_length=255),
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    if view == "all" and not user.is_admin():
        raise HTTPException(403, "Administrator access required")
    statement = (
        select(WorkbenchFile, ChatConversation.title, User.username)
        .outerjoin(
            ChatConversation,
            ChatConversation.conversation_id == WorkbenchFile.conversation_id,
        )
        .outerjoin(User, cast(User.id, String) == WorkbenchFile.user_id)
        .where(*file_scope(user, view, owner, q, folder, origin, conversation))
    )
    scope = [str(user.id), view, owner, q, folder, origin, conversation]
    if cursor:
        try:
            date, identity, bound = json.loads(base64.urlsafe_b64decode(cursor))
            if bound != scope:
                raise ValueError()
            date = datetime.fromisoformat(date)
            statement = statement.where(
                or_(
                    WorkbenchFile.updated_at < date,
                    and_(
                        WorkbenchFile.updated_at == date,
                        WorkbenchFile.file_id < identity,
                    ),
                )
            )
        except (ValueError, TypeError):
            raise HTTPException(422, "Invalid file cursor") from None
    rows = (
        await db.execute(
            statement.order_by(
                WorkbenchFile.updated_at.desc(), WorkbenchFile.file_id.desc()
            ).limit(limit + 1)
        )
    ).all()
    last = rows[limit - 1][0] if len(rows) > limit else None
    return {
        "items": [
            library.public_file(row, title, username)
            for row, title, username in rows[:limit]
        ],
        "next_cursor": (
            base64.urlsafe_b64encode(
                json.dumps([last.updated_at.isoformat(), last.file_id, scope]).encode()
            ).decode()
            if last
            else None
        ),
    }


@router.get("/owners")
async def owners(user=Depends(current_active_user), db=Depends(get_db)):
    if not user.is_admin():
        raise HTTPException(403, "Administrator access required")
    rows = (
        await db.execute(
            select(User.id, User.username)
            .where(
                cast(User.id, String).in_(
                    select(WorkbenchFile.user_id).where(
                        WorkbenchFile.deleted.is_(False)
                    )
                )
            )
            .order_by(User.username)
            .limit(200)
        )
    ).all()
    return {"items": [{"id": str(identity), "name": name} for identity, name in rows]}


@router.post("/upload")
async def upload(
    file: UploadFile = File(...), user=Depends(current_active_user), db=Depends(get_db)
):
    return library.public_file(await library.persist_upload(db, user, file))


class Named(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)


@router.get("/folders")
async def folders(
    view: Literal["mine", "all"] = "mine",
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    query = select(FileLibraryFolder).where(
        library.permitted(user, FileLibraryFolder.user_id)
    )
    if view == "mine":
        query = query.where(FileLibraryFolder.user_id == str(user.id))
    elif not user.is_admin():
        raise HTTPException(403, "Administrator access required")
    rows = (await db.scalars(query.order_by(FileLibraryFolder.name).limit(200))).all()
    return {
        "items": [
            {"id": row.folder_id, "name": row.name, "owner_id": row.user_id}
            for row in rows
        ]
    }


@router.post("/folders")
async def create_folder(
    body: Named, user=Depends(current_active_user), db=Depends(get_db)
):
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy import text

        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "file-folders:" + str(user.id)},
        )
    if (
        await db.scalar(
            select(func.count())
            .select_from(FileLibraryFolder)
            .where(FileLibraryFolder.user_id == str(user.id))
        )
    ) >= 100:
        raise HTTPException(409, "Up to 100 file folders per account")
    row = FileLibraryFolder(folder_id=uuid4().hex, user_id=str(user.id), name=body.name)
    db.add(row)
    await db.commit()
    return {"id": row.folder_id, "name": row.name}


@router.patch("/folders/{identity}")
async def rename_folder(
    identity: str, body: Named, user=Depends(current_active_user), db=Depends(get_db)
):
    row = await db.scalar(
        select(FileLibraryFolder)
        .where(
            FileLibraryFolder.folder_id == identity,
            library.permitted(user, FileLibraryFolder.user_id),
        )
        .with_for_update()
    )
    if not row:
        raise HTTPException(404, "Folder not found")
    row.name = body.name
    await db.commit()
    return {"updated": True}


@router.delete("/folders/{identity}")
async def delete_folder(
    identity: str, user=Depends(current_active_user), db=Depends(get_db)
):
    row = await db.scalar(
        select(FileLibraryFolder)
        .where(
            FileLibraryFolder.folder_id == identity,
            library.permitted(user, FileLibraryFolder.user_id),
        )
        .with_for_update()
    )
    if not row:
        raise HTTPException(404, "Folder not found")
    await db.execute(
        update(WorkbenchFile)
        .where(WorkbenchFile.folder_id == identity)
        .values(folder_id=None, updated_at=utc_now())
    )
    await db.delete(row)
    await db.commit()
    return {"deleted": True}


class SearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    file_ids: list[str] = Field(default_factory=list, max_length=16)
    folder: str = Field("", max_length=64)
    all_users: bool = False
    owner: str = Field("", max_length=255)


@router.post("/search")
async def search(
    body: SearchBody, user=Depends(current_active_user), db=Depends(get_db)
):
    from backend.services.knowledge import retrieve

    return {
        "items": await retrieve(
            db,
            user,
            body.query,
            file_ids=body.file_ids,
            folder=body.folder,
            all_users=body.all_users,
            owner=body.owner,
        )
    }


@router.get("/files/{identity}")
async def detail(identity: str, user=Depends(current_active_user), db=Depends(get_db)):
    row = await library.owned_file(db, user, identity)
    title = (
        await db.scalar(
            select(ChatConversation.title).where(
                ChatConversation.conversation_id == row.conversation_id
            )
        )
        if row.conversation_id
        else None
    )
    return library.public_file(row, title)


class FileEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=1, max_length=100)
    updated_at: datetime
    name: str | None = Field(None, max_length=240)
    folder_id: str | None = Field(None, max_length=64)


class BatchFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    revision: str = Field(min_length=1, max_length=100)
    updated_at: datetime
    name: str | None = Field(None, min_length=1, max_length=240)


class BatchEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[BatchFile] = Field(min_length=1, max_length=100)
    operation: Literal["edit", "delete"]
    folder_id: str | None = Field(None, max_length=64)


def check_file_version(row, revision, updated_at):
    timestamp = (
        updated_at.astimezone(timezone.utc).replace(tzinfo=None)
        if updated_at.tzinfo
        else updated_at
    )
    if row.revision != revision or row.updated_at != timestamp:
        raise HTTPException(409, "File changed; reload before editing")


@router.post("/batch")
async def batch_edit(
    body: BatchEdit, user=Depends(current_active_user), db=Depends(get_db)
):
    ids = [file.id for file in body.files]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "Duplicate file IDs")
    target_folder = None
    if body.folder_id:
        target_folder = await db.scalar(
            select(FileLibraryFolder)
            .where(
                FileLibraryFolder.folder_id == body.folder_id,
                library.permitted(user, FileLibraryFolder.user_id),
            )
            .with_for_update(read=True)
        )
        if not target_folder:
            raise HTTPException(404, "Folder not found")
    rows = (
        await db.scalars(
            select(WorkbenchFile)
            .where(
                WorkbenchFile.file_id.in_(ids),
                WorkbenchFile.kind == "file",
                WorkbenchFile.deleted.is_(False),
                library.permitted(user),
            )
            .order_by(WorkbenchFile.file_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    if len(rows) != len(ids):
        raise HTTPException(404, "One or more files are unavailable")
    requested = {file.id: file for file in body.files}
    for row in rows:
        item = requested[row.file_id]
        check_file_version(row, item.revision, item.updated_at)
        if item.name is not None:
            library.safe_name(item.name)
            if Path(item.name).suffix.lower() != Path(row.name).suffix.lower():
                raise HTTPException(422, "Keep the file extension when renaming")
        if target_folder and target_folder.user_id != row.user_id:
            raise HTTPException(422, "Files and folders must have the same owner")
    for row in rows:
        if body.operation == "delete":
            row.deleted = True
            row.index_status = "deleted"
            row.indexed_revision = None
        else:
            if requested[row.file_id].name is not None:
                row.name = requested[row.file_id].name
            if "folder_id" in body.model_fields_set:
                row.folder_id = body.folder_id
        row.updated_at = utc_now()
    await db.commit()
    if body.operation == "delete":
        for row in rows:
            try:
                await asyncio.to_thread(
                    library.purge_file, library.file_cleanup_record(row)
                )
                row.index_status = "purged"
            except Exception:
                row.index_error = (
                    "File cleanup pending; the background worker will retry"
                )
        await db.commit()
    return {
        "updated": len(rows),
        "items": (
            [library.public_file(row) for row in rows]
            if body.operation == "edit"
            else []
        ),
    }


@router.patch("/files/{identity}")
async def edit(
    identity: str, body: FileEdit, user=Depends(current_active_user), db=Depends(get_db)
):
    folder = None
    if body.folder_id:
        folder = await db.scalar(
            select(FileLibraryFolder)
            .where(
                FileLibraryFolder.folder_id == body.folder_id,
                library.permitted(user, FileLibraryFolder.user_id),
            )
            .with_for_update(read=True)
        )
        if not folder:
            raise HTTPException(404, "Folder not found")
    row = await library.owned_file(db, user, identity, lock=True)
    check_file_version(row, body.revision, body.updated_at)
    if folder and folder.user_id != row.user_id:
        raise HTTPException(422, "Files and folders must have the same owner")
    if body.name is not None:
        if Path(body.name).suffix.lower() != Path(row.name).suffix.lower():
            raise HTTPException(422, "Keep the file extension when renaming")
        row.name = library.safe_name(body.name)
    if "folder_id" in body.model_fields_set:
        row.folder_id = body.folder_id
    row.updated_at = utc_now()
    await db.commit()
    return library.public_file(row)


@router.get("/files/{identity}/text")
async def read_text(
    identity: str, user=Depends(current_active_user), db=Depends(get_db)
):
    row = await library.owned_file(db, user, identity)
    if not library.public_file(row)["editable_text"]:
        raise HTTPException(422, "Use Replace file to update this file type")
    path = Path(row.storage_path or row.path)
    root = library.Config.get_uploads_dir() / "chat-files" / row.user_id
    if not path.resolve().is_relative_to(root.resolve()):
        raise HTTPException(404, "Stored file unavailable")

    def read_bounded():
        with path.open("rb") as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise HTTPException(413, "Text editing is limited to 1 MiB")
        return data.decode("utf-8-sig")

    try:
        content = await asyncio.to_thread(read_bounded)
    except (OSError, UnicodeError):
        raise HTTPException(422, "File is not editable UTF-8 text") from None
    return {"content": content, "revision": row.revision}


class TextEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=1, max_length=100)
    content: str = Field(max_length=1024 * 1024)


@router.put("/files/{identity}/text")
async def edit_text(
    identity: str, body: TextEdit, user=Depends(current_active_user), db=Depends(get_db)
):
    import io

    row = await library.owned_file(db, user, identity, lock=True)
    if row.revision != body.revision:
        raise HTTPException(409, "File changed; reload before editing")
    if not library.public_file(row)["editable_text"]:
        raise HTTPException(422, "Use Replace file to update this file type")
    data = body.content.encode("utf-8")
    if len(data) > 1024 * 1024:
        raise HTTPException(413, "Text editing is limited to 1 MiB")
    file = UploadFile(filename=row.name, file=io.BytesIO(data))
    return library.public_file(
        await library.persist_upload(db, user, file, existing=row)
    )


@router.put("/files/{identity}/content")
async def replace(
    identity: str,
    revision: str,
    file: UploadFile = File(...),
    user=Depends(current_active_user),
    db=Depends(get_db),
):
    row = await library.owned_file(db, user, identity, lock=True)
    if row.revision != revision:
        raise HTTPException(409, "File changed; reload before replacing")
    return library.public_file(
        await library.persist_upload(db, user, file, existing=row)
    )


@router.post("/files/{identity}/index")
async def index(identity: str, user=Depends(current_active_user), db=Depends(get_db)):
    row = await library.owned_file(db, user, identity, lock=True)
    if not library.indexable(row.name, row.size):
        raise HTTPException(
            422, "This file type is available for download, not text search"
        )
    if row.index_status not in ["processing", "queued"]:
        row.index_status = "queued"
        row.index_progress = 0
        row.index_error = None
        row.indexed_revision = None
    await db.commit()
    return {"status": row.index_status}


@router.delete("/files/{identity}/index")
async def cancel_index(
    identity: str, user=Depends(current_active_user), db=Depends(get_db)
):
    row = await library.owned_file(db, user, identity, lock=True)
    row.index_status = "cancelled"
    row.indexed_revision = None
    await db.commit()
    return {"cancelled": True}


@router.delete("/files/{identity}")
async def remove(identity: str, user=Depends(current_active_user), db=Depends(get_db)):
    row = await library.owned_file(db, user, identity, lock=True)
    row.deleted = True
    row.index_status = "deleted"
    row.indexed_revision = None
    row.updated_at = utc_now()
    await db.commit()
    try:
        await asyncio.to_thread(library.purge_file, library.file_cleanup_record(row))
        row.index_status = "purged"
    except Exception:
        row.index_error = "File cleanup pending; the background worker will retry"
    await db.commit()
    return {"deleted": True}
