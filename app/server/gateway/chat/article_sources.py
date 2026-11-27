"""Conversation-owned source numbering, serialized with the conversation lock."""

from sqlalchemy import select
import time
import json
import re
from backend.database.models import ChatConversation, ChatMessage, StorageTask
from backend.services.articles.identity import get_url_hash, normalize_article_url
from backend.services.articles.document import split_md_into_pages


def citation_source(source: dict, markdown: str) -> dict:
    """Send bounded, retrieved page evidence before answer tokens arrive."""
    pages = {}
    for number, body in split_md_into_pages(markdown):
        if number < 1 or not body.strip():
            continue
        body = re.sub(r"!\[[^]]*\]\([^)]*\)", "", body)
        paragraphs = [re.sub(r"\s+", " ", part).strip() for part in body.split("\n\n")]
        excerpt = next(
            (part for part in paragraphs if len(part) >= 80), " ".join(paragraphs)
        )
        pages[str(number)] = excerpt[:240]
    return {
        "source_id": source["source_id"],
        "source_index": source["index"],
        "title": source["title"],
        "url": source["url"],
        "pages": pages,
    }


async def load_sources(db, conversation_id: str) -> list[dict]:
    metadata = await db.scalar(
        select(ChatMessage.extra_metadata)
        .where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.extra_metadata["superseded_by_regeneration"]
            .as_string()
            .is_(None),
            ChatMessage.extra_metadata["article_sources"][0]["source_id"]
            .as_string()
            .isnot(None),
        )
        .order_by(ChatMessage.id.desc())
        .limit(1)
    )
    sources = [dict(source) for source in (metadata or {}).get("article_sources", [])]
    if not sources:
        return sources
    recent = (
        await db.scalars(
            select(ChatMessage.content)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.role == "assistant",
                ChatMessage.is_active_variant.is_(True),
                ChatMessage.extra_metadata["superseded_by_regeneration"]
                .as_string()
                .is_(None),
                ChatMessage.content.contains("[CITATION_CONTEXTS]"),
            )
            .order_by(ChatMessage.id.desc())
            .limit(8)
        )
    ).all()
    pages = {}
    for content in recent:
        for raw in re.findall(
            r"\[CITATION_CONTEXTS\](.*?)\[/CITATION_CONTEXTS\]", content, re.S
        ):
            try:
                contexts = json.loads(raw)
            except ValueError:
                continue
            for value in contexts.values():
                identity, page = value.get("source_id"), value.get("page")
                if identity and isinstance(page, int) and page > 0:
                    values = pages.setdefault(identity, [])
                    if page not in values and len(values) < 8:
                        values.append(page)
    for source in sources:
        source["recent_pages"] = pages.get(source["source_id"], [])
    return sources


async def register_source(
    conversation_id: str, url: str, title: str, read: bool = True
) -> list[dict]:
    from backend.database.database import safe_session

    async with safe_session() as db:
        conversation = await db.scalar(
            select(ChatConversation)
            .where(ChatConversation.conversation_id == conversation_id)
            .with_for_update()
        )
        if conversation is None:
            raise ValueError("Conversation is unavailable")
        from backend.services.chat_deletion import deletion_id

        if await db.scalar(
            select(StorageTask.task_id).where(
                StorageTask.task_id == deletion_id(conversation_id),
                StorageTask.status != "completed",
            )
        ):
            raise ValueError("Conversation is being deleted")
        sources = list(await load_sources(db, conversation_id))
        identity = get_url_hash(url)
        existing = next(
            (source for source in sources if source["source_id"] == identity), None
        )
        if existing:
            sources = [
                (
                    {**source, "last_read_at": time.time()}
                    if source["source_id"] == identity and read
                    else source
                )
                for source in sources
            ]
        else:
            if len(sources) >= 64:
                raise ValueError("A conversation supports at most 64 article sources")
            sources.append(
                {
                    "index": len(sources) + 1,
                    "source_id": identity,
                    "url": normalize_article_url(url),
                    "title": title[:500],
                    "last_read_at": time.time() if read else 0,
                }
            )
        db.add(
            ChatMessage(
                conversation_id=conversation_id,
                role="user",
                content="[PDF_CONTEXT]\nSource registry updated.\n[/PDF_CONTEXT]",
                extra_metadata={"article_sources": sources},
            )
        )
        await db.commit()
        return sources
