"""Unified Chat workbench: bounded catalogs, references and durable research links."""

from __future__ import annotations

import asyncio
import hashlib
import httpx
from pathlib import Path
from uuid import uuid4
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    UploadFile,
    File,
    BackgroundTasks,
)
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from sqlalchemy import exists, or_, select
from sqlalchemy.exc import DBAPIError

from backend.auth import User, current_active_user
from backend.auth.dependencies import require_chat_access
from backend.common.config import Config
from backend.database import get_db
from backend.database.models import AutoResearchSession, WorkbenchFile
from backend.autoresearch.engine import store
from backend.services.workbench import (
    ResourceReference,
    resolve_references,
    search_resources,
    file_path,
)
from backend.services.research_questions import ResearchQuestion
from gateway.chat.permissions import require_conversation_access

router = APIRouter(
    prefix="/workbench",
    tags=["Chat workbench"],
    dependencies=[Depends(require_chat_access)],
)
_search_slots = asyncio.Semaphore(12)
_index_slots = asyncio.Semaphore(2)
_indexing: set[tuple[str, str]] = set()
_preview_slots = asyncio.Semaphore(4)
_office_preview_slots = asyncio.Semaphore(2)
_side_question_slots = asyncio.Semaphore(4)


async def _run_preview(function, *args):
    from backend.services.document_preview import OFFICE_SUFFIXES
    # Cold Office conversion must not occupy all image/text/PDF preview slots.
    slots = _office_preview_slots if len(args) > 1 and Path(args[1]).suffix.lower() in OFFICE_SUFFIXES else _preview_slots
    try:
        await asyncio.wait_for(slots.acquire(), 2)
    except TimeoutError:
        raise HTTPException(503, "File preview is busy. Try again shortly.") from None
    task = asyncio.create_task(asyncio.to_thread(function, *args))

    # A disconnected request cannot release a still-running converter's slot.
    def finished(result):
        slots.release()
        if not result.cancelled():
            result.exception()

    task.add_done_callback(finished)
    try:
        return await asyncio.shield(task)
    except FileNotFoundError:
        raise HTTPException(404, "File is no longer available") from None


@router.get("/commands")
async def commands(
    q: str = Query("", max_length=100),
    after: str = "",
    limit: int = Query(20, ge=1, le=20),
    language: Literal["en-US", "zh-CN", "zh-HK"] = "en-US",
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    from backend.services.command_catalog import commands as localized_commands

    entries = localized_commands(language)
    from backend.database.models import CapabilityEntry, CapabilityInstallation
    from backend.services.capability_library import visible
    from sqlalchemy import and_
    from sqlalchemy.orm import defer

    disabled = set(
        (
            await db.scalars(
                select(CapabilityInstallation.entry_id).where(
                    CapabilityInstallation.user_id == str(user.id),
                    CapabilityInstallation.enabled.is_(False),
                )
            )
        ).all()
    )
    entries = [item for item in entries if item.get("skill_id") not in disabled]
    needle = q.strip().lower()
    matches = [item for item in entries if not needle or needle in item["search_text"]]
    if after and not after.startswith("ugc-"):
        index = next((i for i, item in enumerate(matches) if item["id"] == after), None)
        if index is None:
            raise HTTPException(422, "Invalid command cursor")
        matches = matches[index + 1 :]
    elif after:
        matches = []
    installation = CapabilityInstallation
    query = (
        select(CapabilityEntry)
        .options(defer(CapabilityEntry.content))
        .outerjoin(
            installation,
            and_(
                installation.entry_id == CapabilityEntry.entry_id,
                installation.user_id == str(user.id),
            ),
        )
        .where(
            CapabilityEntry.kind == "skill",
            CapabilityEntry.builtin.is_(False),
            CapabilityEntry.archived.is_(False),
            visible(user),
            or_(
                CapabilityEntry.owner_id == str(user.id),
                installation.user_id.isnot(None),
            ),
            or_(installation.enabled.is_(True), installation.user_id.is_(None)),
        )
    )
    if after.startswith("ugc-"):
        query = query.where(CapabilityEntry.entry_id > after)
    if needle:
        query = query.where(
            or_(
                CapabilityEntry.name.icontains(needle, autoescape=True),
                CapabilityEntry.description.icontains(needle, autoescape=True),
            )
        )
    if len(matches) <= limit:
        custom = (
            await db.scalars(query.order_by(CapabilityEntry.entry_id).limit(limit + 1))
        ).all()
        matches.extend(
            {
                "id": item.entry_id,
                "library_skill_id": item.entry_id,
                "name": item.name,
                "description": item.description,
                "mode": "skill",
            }
            for item in custom
        )
    items = [
        {
            **{key: value for key, value in item.items() if key != "search_text"},
            "library_skill_id": item.get("library_skill_id") or item.get("skill_id"),
            "available": item["mode"] != "research" or user.can_use_gpu(),
        }
        for item in matches[:limit]
    ]
    return {
        "items": items,
        "next_cursor": items[-1]["id"] if len(matches) > limit else None,
    }


@router.get("/resources")
async def resources(
    request: Request,
    kind: str = Query("dataset", pattern="^(dataset|slide|task|model|file|research|conversation)$"),
    q: str = Query("", max_length=120),
    cursor: str = Query("", max_length=2048),
    limit: int = Query(20, ge=1, le=20),
    workspace_id: str | None = None,
    dataset_id: str = "",
    session_id: str = "",
    conversation_id: str = "",
    parent: str = Query("", max_length=1000),
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    header = request.headers.get("X-Workspace-ID")
    if header and workspace_id and header != workspace_id:
        raise HTTPException(409, "Conflicting workspace scope")
    try:
        async with asyncio.timeout(1.2):
            async with _search_slots:
                return await search_resources(
                    db,
                    user,
                    workspace_id or header,
                    kind,
                    q,
                    cursor,
                    limit,
                    dataset_id,
                    session_id,
                    conversation_id,
                    parent,
                )
    except (TimeoutError, DBAPIError):
        await db.rollback()
        raise HTTPException(
            503, "Search is busy. Narrow the scope or try again."
        ) from None


class ReferencesRequest(BaseModel):
    workspace_id: str | None = None
    references: list[ResourceReference] = Field(default_factory=list, max_length=16)


@router.post("/resolve")
async def resolve(
    body: ReferencesRequest,
    request: Request,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    header = request.headers.get("X-Workspace-ID")
    if header and body.workspace_id and header != body.workspace_id:
        raise HTTPException(409, "Conflicting workspace scope")
    return {
        "items": [
            {k: v for k, v in item.items() if k not in {"path", "storage_path"}}
            for item in await resolve_references(
                db, user, body.workspace_id or header, body.references
            )
        ]
    }


@router.post("/uploads")
async def upload(
    workspace_id: str | None = None,
    conversation_id: str | None = None,
    file: UploadFile = File(...),
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    from backend.services.workspaces import resolve_scope

    await resolve_scope(db, user, workspace_id)
    if conversation_id:
        conversation = await require_conversation_access(
            db, conversation_id, user, include_messages=False
        )
        if conversation.workspace_id != workspace_id:
            raise HTTPException(409, "Conversation belongs to a different workspace")
    name = Path(file.filename or "attachment").name[:240]
    fid = uuid4().hex
    root = Config.get_uploads_dir() / "chat-files" / str(user.id)
    root.mkdir(parents=True, exist_ok=True)
    path = root / (fid + Path(name).suffix)
    digest, size = hashlib.sha256(), 0
    try:
        with path.open("xb") as output:
            while chunk := await file.read(64 * 1024):
                size += len(chunk)
                if size > 32 * 1024 * 1024:
                    raise HTTPException(413, "Attachments are limited to 32 MiB")
                digest.update(chunk)
                await asyncio.to_thread(output.write, chunk)
        from backend.services.file_library import initial_index_status

        row = WorkbenchFile(
            file_id=fid,
            user_id=str(user.id),
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            name=name,
            path=str(path),
            storage_path=str(path),
            index_status=initial_index_status(name, size),
            size=size,
            revision=digest.hexdigest(),
        )
        if conversation_id:
            from backend.database.models import ChatConversation, StorageTask
            from backend.services.chat_deletion import deletion_id

            conversation = await db.scalar(
                select(ChatConversation)
                .where(ChatConversation.conversation_id == conversation_id)
                .with_for_update()
            )
            deleting = await db.scalar(
                select(StorageTask.task_id).where(
                    StorageTask.task_id == deletion_id(conversation_id),
                    StorageTask.status != "completed",
                )
            )
            if conversation is None or deleting:
                raise HTTPException(409, "Conversation is being deleted")
        db.add(row)
        await db.commit()
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    from backend.services.document_preview import schedule_preview
    schedule_preview(path, name)
    return {
        "kind": "file",
        "id": fid,
        "name": name,
        "revision": digest.hexdigest(),
        "size": size,
    }


@router.get("/files/{file_id}")
async def preview(
    file_id: str,
    request: Request,
    workspace_id: str | None = None,
    sheet: str = Query("", max_length=200),
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    header = request.headers.get("X-Workspace-ID")
    if header and workspace_id and header != workspace_id:
        raise HTTPException(409, "Conflicting workspace scope")
    item = (
        await resolve_references(
            db,
            user,
            workspace_id or header,
            [ResourceReference(kind="file", id=file_id)],
        )
    )[0]
    from backend.services.file_preview import preview as preview_file

    path = file_path(item)

    return {"file_id": file_id, **await _run_preview(preview_file, path, item["name"], sheet)}


@router.get("/files/{file_id}/pages/{page}")
async def file_page(
    file_id: str,
    page: int,
    request: Request,
    revision: str = Query(min_length=1, max_length=100),
    workspace_id: str | None = None,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    header = request.headers.get("X-Workspace-ID")
    if header and workspace_id and header != workspace_id:
        raise HTTPException(409, "Conflicting workspace scope")
    item = (await resolve_references(db, user, workspace_id or header,
                                    [ResourceReference(kind="file", id=file_id)]))[0]
    path = file_path(item)
    stat = path.stat()
    if revision != f"{stat.st_mtime_ns}:{stat.st_size}":
        raise HTTPException(409, "previewChanged")
    from backend.services.document_preview import render_page, MAX_PAGES
    if not 1 <= page <= MAX_PAGES:
        raise HTTPException(404, "previewPageNotFound")
    try:
        image = await _run_preview(render_page, path, item["name"], page)
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(404 if code == "previewPageNotFound" else 422,
                            code if code.startswith("preview") else "previewUnavailable") from None
    return FileResponse(image, media_type="image/png", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    })


@router.get("/files/{file_id}/content")
async def file_content(
    file_id: str,
    request: Request,
    workspace_id: str | None = None,
    download: bool = False,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    header = request.headers.get("X-Workspace-ID")
    if header and workspace_id and header != workspace_id:
        raise HTTPException(409, "Conflicting workspace scope")
    item = (
        await resolve_references(
            db,
            user,
            workspace_id or header,
            [ResourceReference(kind="file", id=file_id)],
        )
    )[0]
    path = file_path(item)
    from backend.services.file_preview import MEDIA_TYPES, MEDIA_LIMIT

    media_type = MEDIA_TYPES.get(Path(item["name"]).suffix.lower())
    if not download and (not media_type or path.stat().st_size > MEDIA_LIMIT):
        raise HTTPException(413, "Download this file to view it")
    return FileResponse(
        path,
        filename=item["name"],
        media_type=media_type or "application/octet-stream",
        content_disposition_type="attachment" if download else "inline",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            **({"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"} if media_type == "image/svg+xml" else {}),
        },
    )


@router.get("/conversations/{conversation_id}/files")
async def conversation_files(
    conversation_id: str,
    request: Request,
    session_id: str = "",
    parent: str = Query("", max_length=1000),
    q: str = Query("", max_length=120),
    cursor: str = Query("", max_length=2048),
    view: Literal["uploads", "all"] = "uploads",
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    conversation = await require_conversation_access(
        db, conversation_id, user, include_messages=False
    )
    session = None
    if session_id:
        session = await db.scalar(
            select(AutoResearchSession).where(
                AutoResearchSession.session_id == session_id,
                AutoResearchSession.chat_conversation_id == conversation_id,
            )
        )
        if session is None or (session.recovery_metadata or {}).get("delete_requested"):
            raise HTTPException(404, "Research not found in this conversation")
    try:
        async with asyncio.timeout(1.2):
            async with _search_slots:
                page = await search_resources(
                    db,
                    user,
                    conversation.workspace_id,
                    "file",
                    q,
                    cursor,
                    20,
                    session_id=session_id,
                    conversation_id=conversation_id,
                    parent=parent,
                    all_conversation_files=view == "all",
                )
    except (TimeoutError, DBAPIError):
        await db.rollback()
        raise HTTPException(
            503, "File search is busy. Narrow the search or try again."
        ) from None
    state = (session.recovery_metadata or {}).get("file_index", {}) if session else {}
    return {
        **page,
        "indexing": (session_id, parent) in _indexing,
        "partial": state.get("status") == "partial" and state.get("path", "") == parent,
    }


@router.get("/conversations/{conversation_id}/research")
async def research_links(
    conversation_id: str, user: User = Depends(current_active_user), db=Depends(get_db)
):
    await require_conversation_access(db, conversation_id, user, include_messages=False)
    query = select(
        AutoResearchSession.session_id,
        AutoResearchSession.chat_conversation_id,
        AutoResearchSession.research_question.label("question"),
        AutoResearchSession.recovery_metadata['title'].as_string().label('title'),
        AutoResearchSession.status,
        AutoResearchSession.max_iterations,
        AutoResearchSession.current_iteration,
        AutoResearchSession.created_at,
    ).where(AutoResearchSession.chat_conversation_id == conversation_id)
    if not user.is_admin():
        query = query.where(AutoResearchSession.user_id == str(user.id))
    rows = (
        (
            await db.execute(
                query.order_by(AutoResearchSession.created_at.desc()).limit(30)
            )
        )
        .mappings()
        .all()
    )
    from datetime import timezone

    return {
        "items": [
            {
                **dict(row),
                "created_at": row["created_at"]
                .replace(tzinfo=timezone.utc)
                .timestamp(),
            }
            for row in rows
        ]
    }


@router.post('/research/{session_id}/questions')
async def research_side_question(session_id: str, body: ResearchQuestion,
                                 user: User = Depends(current_active_user), db=Depends(get_db)):
    from .autoresearch import owned
    from backend.services.research_questions import answer_question, question_context
    session = await owned(session_id, user)
    context = await question_context(db, session, body)
    await db.rollback()  # Release the read transaction before waiting for the model.
    try:
        async with asyncio.timeout(2):
            await _side_question_slots.acquire()
    except TimeoutError:
        raise HTTPException(429, 'Side questions are busy; research continues normally') from None
    try:
        answer = await answer_question(context, body)
    except (httpx.HTTPError, TimeoutError, ValueError, KeyError) as error:
        raise HTTPException(503, 'The side-question response is unavailable; research is unaffected') from error
    finally:
        _side_question_slots.release()
    return {'answer': answer, 'research_unchanged': True,
            'evidence_sequences': [item['sequence'] for item in context['recent_evidence']],
            'selected_sequence': body.event_seq}


class ConversationStatuses(BaseModel):
    conversation_ids: list[str] = Field(default_factory=list, max_length=100)


@router.post("/research-statuses")
async def research_statuses(
    body: ConversationStatuses,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    from backend.database.models import ChatConversation

    query = (
        select(AutoResearchSession.chat_conversation_id, AutoResearchSession.status)
        .join(
            ChatConversation,
            ChatConversation.conversation_id
            == AutoResearchSession.chat_conversation_id,
        )
        .where(
            ChatConversation.conversation_id.in_(body.conversation_ids),
            ChatConversation.user_id == str(user.id),
            AutoResearchSession.status.in_(store.ACTIVE | {"blocked", "paused"}),
        )
    )
    rows = (await db.execute(query.distinct())).all()
    states = {}
    priority = {
        "running": 0,
        "waiting": 1,
        "preparing": 2,
        "pausing": 3,
        "stopping": 4,
        "queued": 5,
        "blocked": 6,
        "paused": 7,
    }
    for cid, status in rows:
        if cid not in states or priority[status] < priority[states[cid]]:
            states[cid] = status
    file_conversations = (
        await db.scalars(
            select(ChatConversation.conversation_id).where(
                ChatConversation.conversation_id.in_(body.conversation_ids),
                ChatConversation.user_id == str(user.id),
                or_(
                    exists(
                        select(WorkbenchFile.file_id).where(
                            WorkbenchFile.conversation_id
                            == ChatConversation.conversation_id
                        )
                    ),
                    exists(
                        select(AutoResearchSession.session_id).where(
                            AutoResearchSession.chat_conversation_id
                            == ChatConversation.conversation_id
                        )
                    ),
                ),
            )
        )
    ).all()
    return {"states": states, "file_conversations": file_conversations}


@router.get("/conversations/{conversation_id}/files/{file_id}/download")
async def download_conversation_file(
    conversation_id: str,
    file_id: str,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    conversation = await require_conversation_access(
        db, conversation_id, user, include_messages=False
    )
    file = await db.scalar(
        select(WorkbenchFile).where(
            WorkbenchFile.file_id == file_id,
            WorkbenchFile.conversation_id == conversation_id,
        )
    )
    if file is None:
        raise HTTPException(404, "File does not belong to this conversation")
    item = (
        await resolve_references(
            db,
            user,
            conversation.workspace_id,
            [ResourceReference(kind="file", id=file_id)],
        )
    )[0]
    return FileResponse(
        file_path(item),
        filename=item["name"],
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/research/{session_id}/index")
async def refresh_files(
    session_id: str,
    request: Request,
    background: BackgroundTasks,
    path: str = "",
    user: User = Depends(current_active_user),
):
    from gateway.routes.autoresearch import owned
    from backend.autoresearch.engine.jobs import contained
    from backend.autoresearch.engine.file_catalog import index_tree

    row = await owned(session_id, user)
    header = request.headers.get("X-Workspace-ID")
    if header and header != (row.recovery_metadata or {}).get("workspace_id"):
        raise HTTPException(409, "Conflicting workspace scope")
    root = Path(row.workspace_path)
    try:
        directory = contained(root, path or ".")
    except ValueError:
        raise HTTPException(403, "Directory is outside the workspace") from None
    from backend.autoresearch.engine.file_catalog import EXCLUDED

    if (
        any(
            part.startswith(".") or part in EXCLUDED
            for part in directory.relative_to(root).parts
        )
        or not directory.is_dir()
    ):
        raise HTTPException(404, "Directory not found")
    key = (session_id, "" if directory == root else str(directory.relative_to(root)))
    if key in _indexing:
        return {"status": "indexing"}
    if len(_indexing) >= 8:
        raise HTTPException(429, "File indexing is busy")
    _indexing.add(key)

    async def run():
        try:
            async with _index_slots:
                result = await index_tree(row, directory)
                await store.update(
                    session_id,
                    meta={
                        "file_index": {
                            "path": path,
                            "status": "partial" if result["truncated"] else "ready",
                            "count": result["count"],
                        }
                    },
                    event={
                        "kind": "file_index",
                        "path": path,
                        "truncated": result["truncated"],
                    },
                )
        finally:
            _indexing.discard(key)

    background.add_task(run)
    return {"status": "indexing"}


class FilePathReference(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    include_preview: bool = False


@router.post("/research/{session_id}/file-reference")
async def reference_path(
    session_id: str,
    body: FilePathReference,
    request: Request,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    """An exact authorized path remains usable even in a partially indexed folder."""
    from gateway.routes.autoresearch import owned
    from backend.autoresearch.engine.jobs import contained
    from backend.autoresearch.engine.file_catalog import EXCLUDED
    from backend.database.models import utc_now

    row = await owned(session_id, user)
    header = request.headers.get("X-Workspace-ID")
    if header and header != (row.recovery_metadata or {}).get("workspace_id"):
        raise HTTPException(409, "Conflicting workspace scope")
    relative = Path(body.path)
    if any(
        part.startswith(".") or part in EXCLUDED for part in relative.parts
    ) or relative.name in {"opencode.json", "AGENTS.md"}:
        raise HTTPException(403, "Internal runtime files cannot be referenced")
    row = await db.scalar(
        select(AutoResearchSession)
        .where(AutoResearchSession.session_id == session_id)
        .with_for_update()
    )
    if row is None or (row.recovery_metadata or {}).get("delete_requested"):
        raise HTTPException(404, "Research session is being removed")
    try:
        path = contained(Path(row.workspace_path), body.path)
    except ValueError:
        raise HTTPException(403, "File is outside the workspace") from None
    if not path.is_file():
        raise HTTPException(404, "File not found")
    canonical = str(path.relative_to(Path(row.workspace_path)))
    identity = hashlib.sha256(f"{session_id}:{canonical}".encode()).hexdigest()
    stat = path.stat()
    entry = await db.scalar(
        select(WorkbenchFile).where(WorkbenchFile.file_id == identity).with_for_update()
    )
    if entry and entry.deleted:
        raise HTTPException(404, "File was removed from the library")
    if entry is None:
        entry = WorkbenchFile(
            file_id=identity,
            user_id=row.user_id,
            session_id=session_id,
            workspace_id=(row.recovery_metadata or {}).get("workspace_id"),
            conversation_id=row.chat_conversation_id,
            path=canonical,
            parent=""
            if path.parent == Path(row.workspace_path)
            else str(path.parent.relative_to(Path(row.workspace_path))),
            name=path.name,
        )
        db.add(entry)
    from backend.services.file_library import snapshot_file

    source_revision = f"{stat.st_mtime_ns}:{stat.st_size}"
    async def receipt():
        item = {"kind": "file", "id": identity, "name": entry.name, "path": canonical,
                "session_id": session_id, "revision": entry.revision}
        if body.include_preview:
            from backend.services.file_preview import preview as preview_file
            item['preview'] = {"file_id": identity, **await _run_preview(preview_file, Path(entry.storage_path), entry.name)}
        return item

    if entry.source_revision == source_revision and entry.storage_path:
        # Release publication locks before potentially waiting on a conversion.
        await db.commit()
        return await receipt()
    write = asyncio.create_task(
        asyncio.to_thread(snapshot_file, path, row.user_id, identity)
    )
    try:
        stored, revision = await asyncio.shield(write)
    except asyncio.CancelledError:
        stored, _ = await write
        if stored != entry.storage_path:
            Path(stored).unlink(missing_ok=True)
        raise
    entry.source_revision = source_revision
    entry.storage_path = stored
    entry.origin = "generated"
    entry.source_title = row.recovery_metadata['title']
    if entry.revision != revision:
        from backend.services.file_library import initial_index_status

        entry.index_status = initial_index_status(entry.name, stat.st_size)
        entry.indexed_revision = None
    entry.revision, entry.size, entry.updated_at = (
        revision,
        stat.st_size,
        utc_now(),
    )
    await db.commit()
    from backend.services.document_preview import schedule_preview
    schedule_preview(Path(stored), entry.name)
    return await receipt()


@router.get("/research/{session_id}/activity")
async def activity(
    session_id: str,
    before: int = Query(0, ge=0),
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    from gateway.routes.autoresearch import owned
    from backend.autoresearch.engine import store
    from backend.autoresearch.engine.activity import project_event

    session = await owned(session_id, user)
    page = await store.activity(session_id, before=before)
    language = (session.recovery_metadata or {}).get('language', 'en-US')
    return {**page, "items": [project_event(event, language) for event in page["items"]]}
