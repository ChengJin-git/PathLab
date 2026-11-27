"""Owner-scoped folders and bounded Chat navigation; folders never alter execution scope."""

import base64
import json
from datetime import datetime
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update, func, and_, or_, text
from backend.auth import User, current_active_user
from backend.database import get_db
from backend.database.models import ChatConversation, ChatFolder, StorageTask

router = APIRouter(prefix="/chat-navigation", tags=["Chat navigation"])


class FolderBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)


async def owned_folder(db, user, identity, *, edit=False):
    query = select(ChatFolder).where(
        ChatFolder.user_id == str(user.id), ChatFolder.folder_id == identity
    )
    row = await db.scalar(query.with_for_update(read=not edit))
    if row is None:
        raise HTTPException(404, "Folder not found")
    return row


@router.get("/folders")
async def folders(
    after: str = Query("", max_length=64),
    limit: int = Query(30, ge=1, le=50),
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    rows = (
        await db.scalars(
            select(ChatFolder)
            .where(ChatFolder.user_id == str(user.id), ChatFolder.folder_id > after)
            .order_by(ChatFolder.folder_id)
            .limit(limit + 1)
        )
    ).all()
    return {
        "items": [{"id": row.folder_id, "name": row.name} for row in rows[:limit]],
        "next_cursor": rows[limit - 1].folder_id if len(rows) > limit else None,
    }


@router.post("/folders")
async def create_folder(
    body: FolderBody, user: User = Depends(current_active_user), db=Depends(get_db)
):
    if db.bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "chat-folder:" + str(user.id)},
        )
    count = await db.scalar(
        select(func.count())
        .select_from(ChatFolder)
        .where(ChatFolder.user_id == str(user.id))
    )
    if count >= 100:
        raise HTTPException(409, "A library supports up to 100 chat folders")
    row = ChatFolder(folder_id=uuid4().hex, user_id=str(user.id), name=body.name)
    db.add(row)
    await db.commit()
    return {"id": row.folder_id, "name": row.name}


@router.patch("/folders/{identity}")
async def rename_folder(
    identity: str,
    body: FolderBody,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    row = await owned_folder(db, user, identity, edit=True)
    row.name = body.name
    await db.commit()
    return {"id": row.folder_id, "name": row.name}


@router.delete("/folders/{identity}")
async def delete_folder(
    identity: str, user: User = Depends(current_active_user), db=Depends(get_db)
):
    row = await owned_folder(db, user, identity, edit=True)
    await db.execute(
        update(ChatConversation)
        .where(
            ChatConversation.user_id == str(user.id),
            ChatConversation.folder_id == identity,
        )
        .values(folder_id=None, updated_at=ChatConversation.updated_at)
    )
    await db.delete(row)
    await db.commit()
    return {"deleted": True}


class FilingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_id: str | None = Field(None, max_length=64)
    pinned: bool | None = None
    title: str | None = Field(None, min_length=1, max_length=500)


@router.patch("/chats/{identity}")
async def file_chat(
    identity: str,
    body: FilingBody,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    if "folder_id" in body.model_fields_set and body.folder_id:
        await owned_folder(db, user, body.folder_id)
    row = await db.scalar(
        select(ChatConversation)
        .where(
            ChatConversation.conversation_id == identity,
            ChatConversation.user_id == str(user.id),
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Chat not found")
    changes = body.model_dump(exclude_unset=True)
    if (
        "title" in changes
        and (changes["title"] is None or not changes["title"].strip())
    ) or ("pinned" in changes and changes["pinned"] is None):
        raise HTTPException(422, "Provide a title or a valid pin state")
    await db.execute(
        update(ChatConversation)
        .where(ChatConversation.id == row.id)
        .values(**changes, updated_at=ChatConversation.updated_at)
    )
    await db.commit()
    return {"updated": True}


@router.get("/chats")
async def chats(
    folder: str = Query("", max_length=64),
    q: str = Query("", max_length=100),
    cursor: str = Query("", max_length=2048),
    limit: int = Query(30, ge=1, le=50),
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    q = q.strip()
    query = (
        select(ChatConversation, ChatFolder.name.label("folder_name"))
        .outerjoin(
            ChatFolder,
            and_(
                ChatFolder.folder_id == ChatConversation.folder_id,
                ChatFolder.user_id == str(user.id),
            ),
        )
        .where(
            ChatConversation.user_id == str(user.id),
            ~select(StorageTask.id)
            .where(
                StorageTask.user_id == str(user.id),
                StorageTask.task_type == "chat_delete",
                StorageTask.params["conversation_id"].as_string()
                == ChatConversation.conversation_id,
            )
            .exists(),
        )
    )
    if q:
        query = query.where(ChatConversation.title.icontains(q, autoescape=True))
    else:
        if folder:
            await owned_folder(db, user, folder)
        query = query.where(
            ChatConversation.folder_id == folder
            if folder
            else ChatConversation.folder_id.is_(None)
        )
    if cursor:
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor))
            if value["scope"] != [str(user.id), folder, q]:
                raise ValueError()
            pin = value["pin"]
            date = datetime.fromisoformat(value["date"])
            identity = value["id"]
            if type(pin) is not bool or not isinstance(identity, str):
                raise ValueError()
            query = query.where(
                or_(
                    and_(ChatConversation.pinned.is_(False), pin),
                    and_(
                        ChatConversation.pinned == pin,
                        or_(
                            ChatConversation.updated_at < date,
                            and_(
                                ChatConversation.updated_at == date,
                                ChatConversation.conversation_id < identity,
                            ),
                        ),
                    ),
                )
            )
        except (ValueError, KeyError, TypeError):
            raise HTTPException(422, "Invalid chat cursor") from None
    rows = (
        await db.execute(
            query.order_by(
                ChatConversation.pinned.desc(),
                ChatConversation.updated_at.desc(),
                ChatConversation.conversation_id.desc(),
            ).limit(limit + 1)
        )
    ).all()
    last = rows[limit - 1][0] if len(rows) > limit else None
    next_cursor = (
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "scope": [str(user.id), folder, q],
                    "pin": last.pinned,
                    "date": last.updated_at.isoformat(),
                    "id": last.conversation_id,
                }
            ).encode()
        ).decode()
        if last
        else None
    )
    return {
        "items": [{**row.to_dict(), "folder_name": name} for row, name in rows[:limit]],
        "next_cursor": next_cursor,
    }
