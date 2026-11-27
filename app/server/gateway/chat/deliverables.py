"""Turn explicit file deliveries into durable conversation artifacts.

Model blocks describe content. Only the server creates IDs and saved-file cards.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from dataclasses import dataclass

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from backend.common.config import Config
from backend.database.database import safe_session
from backend.database.models import (
    ChatConversation,
    ChatMessage,
    StorageTask,
    WorkbenchFile,
)
from backend.services.chat_deletion import deletion_id

TAG = "DELIVER_FILE"
PATTERN = re.compile(r"\[DELIVER_FILE\]\s*(.*?)\s*\[/DELIVER_FILE\]", re.S)
RESERVED = re.compile(r"\[(FILE_DELIVERY|RESEARCH_RUN)\][\s\S]*?\[/\1\]")


@dataclass(frozen=True)
class DownloadedPdf:
    """Server-owned source; never deserialized from a model delivery block."""

    filename: str
    source: Path

    def read(self) -> bytes:
        from backend.services.articles.reader import get_pdf_cache_dir

        path = self.source.resolve()
        if (
            path.parent != get_pdf_cache_dir().resolve()
            or path.suffix != ".pdf"
            or path.stat().st_size > 50 * 1024 * 1024
        ):
            raise ValueError("Invalid cached article source")
        data = path.read_bytes()
        if not data.lstrip().startswith(b"%PDF-"):
            raise ValueError("Downloaded article is not a PDF")
        return data


class TextDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=180)
    content: str = Field(min_length=1, max_length=250000)

    @field_validator("filename")
    @classmethod
    def filename_only(cls, value):
        if (
            value != Path(value).name
            or any(c in value for c in "\\/:\x00\n\r")
            or value.startswith(".")
        ):
            raise ValueError("Use a filename, not a path")
        if Path(value).suffix.lower() not in {
            ".md",
            ".txt",
            ".csv",
            ".tsv",
            ".json",
            ".html",
            ".py",
            ".r",
            ".tex",
            ".yaml",
            ".yml",
        }:
            raise ValueError("This format requires the research runtime")
        return value


def parse_deliveries(content: str) -> list[TextDelivery]:
    matches = list(PATTERN.finditer(content))
    if not matches:
        return []
    if len(matches) > 4:
        raise ValueError("At most four files can be delivered in one reply")
    files = [TextDelivery.model_validate_json(match.group(1)) for match in matches]
    if len({item.filename for item in files}) != len(files):
        raise ValueError("Duplicate output filenames")
    if len(content.encode("utf-8")) > 1024 * 1024:
        raise ValueError("File delivery exceeds the per-turn content budget")
    return files


def without_delivery_blocks(content: str) -> str:
    content = PATTERN.sub("", content)
    return content.split("[DELIVER_FILE]", 1)[0].strip()


def without_model_receipts(content: str) -> str:
    content = RESERVED.sub("", content)
    for marker in ("[FILE_DELIVERY]", "[RESEARCH_RUN]"):
        content = content.split(marker, 1)[0]
    return content


async def save_deliveries(
    conversation_id: str,
    message_id: int,
    user,
    files: list[TextDelivery | DownloadedPdf],
    prose: str,
) -> tuple[str, list[dict]]:
    root = Config.get_uploads_dir() / "chat-files" / str(user.id)
    root.mkdir(parents=True, exist_ok=True)
    created = []
    results = []
    async with safe_session() as db:
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
        if (
            not conversation
            or deleting
            or (conversation.user_id != str(user.id) and not user.is_admin())
        ):
            raise HTTPException(409, "Conversation is unavailable for file delivery")
        message = await db.get(ChatMessage, message_id)
        if not message or message.conversation_id != conversation_id:
            raise HTTPException(404, "Delivery message not found")
        try:
            for index, item in enumerate(files):
                identity = hashlib.sha256(
                    f"{conversation_id}:{message_id}:{index}".encode()
                ).hexdigest()
                path = root / (identity + Path(item.filename).suffix.lower())
                data = (
                    await asyncio.to_thread(item.read)
                    if isinstance(item, DownloadedPdf)
                    else item.content.encode("utf-8")
                )
                digest = hashlib.sha256(data).hexdigest()
                existing = await db.get(WorkbenchFile, identity)
                if not existing:

                    def write():
                        fd, temp = tempfile.mkstemp(dir=root, prefix=".delivery-")
                        try:
                            with os.fdopen(fd, "wb") as stream:
                                stream.write(data)
                                stream.flush()
                                os.fsync(stream.fileno())
                            os.replace(temp, path)
                        finally:
                            Path(temp).unlink(missing_ok=True)

                    # Cancellation must not leave a writer creating an orphan after
                    # rollback has already removed the file.
                    writer = asyncio.create_task(asyncio.to_thread(write))
                    try:
                        await asyncio.shield(writer)
                    except asyncio.CancelledError:
                        await writer
                        created.append(path)
                        raise
                    created.append(path)
                    from backend.services.file_library import initial_index_status
                    db.add(
                        WorkbenchFile(
                            file_id=identity,
                            user_id=str(user.id),
                            workspace_id=conversation.workspace_id,
                            conversation_id=conversation_id,
                            name=item.filename,
                            path=str(path),
                            storage_path=str(path),
                            origin='generated',
                            index_status=initial_index_status(item.filename,len(data)),
                            source_title=conversation.title,
                            size=len(data),
                            revision=digest,
                        )
                    )
                results.append(
                    dict(
                        kind="file",
                        id=identity,
                        name=existing.name if existing else item.filename,
                        size=existing.size if existing else len(data),
                        revision=existing.revision if existing else digest,
                    )
                )
            final = (
                prose.strip()
                + "\n\n[FILE_DELIVERY]"
                + json.dumps({"files": results}, ensure_ascii=False)
                + "[/FILE_DELIVERY]"
            )
            message.content = final.strip()
            message.extra_metadata = {
                **(message.extra_metadata or {}),
                "delivered_files": results,
            }
            await db.commit()
            return message.content, results
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
