from types import SimpleNamespace

import pytest
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.common.chat_timeline import visible_messages
from backend.database.models import ChatConversation, ChatMessage
from backend.database.repositories.chat import ChatRepository
from gateway.routes import chat_conversation


@pytest.fixture
async def sessions():
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    for model in (ChatConversation, ChatMessage):
        model.__table__.to_metadata(metadata)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add_all(
            [
                ChatConversation(conversation_id="one", user_id="alice"),
                ChatConversation(conversation_id="two", user_id="bob"),
            ]
        )
        for identity, role, content in [
            (1, "user", "Question"),
            (2, "assistant", "Old answer"),
            (3, "user", "Old followup"),
            (4, "assistant", "Old followup answer"),
        ]:
            db.add(
                ChatMessage(
                    id=identity, conversation_id="one", role=role, content=content
                )
            )
        await db.commit()
    yield factory
    await engine.dispose()


async def test_retry_branch_survives_new_session_and_multiple_regenerations(
    sessions, monkeypatch
):
    async with sessions() as db:
        # A source registered during generation is beyond the captured boundary.
        db.add(
            ChatMessage(
                id=5,
                conversation_id="one",
                role="user",
                content="[PDF_CONTEXT]new source[/PDF_CONTEXT]",
            )
        )
        group = await ChatRepository.prepare_variant_group(
            db, 2, conversation_id="one", through_message_id=4
        )
        db.add(
            ChatMessage(
                id=6,
                conversation_id="one",
                role="assistant",
                content="New answer",
                variant_group_id=group,
            )
        )
        await db.commit()
    async with sessions() as db:
        rows = (
            await db.scalars(
                select(ChatMessage).where(ChatMessage.conversation_id == "one")
            )
        ).all()
        assert [m.id for m in visible_messages(rows)] == [1, 6, 5]
        assert (await db.get(ChatMessage, 3)).content == "Old followup"
        # Retry an older sibling; every sibling must be deactivated atomically.
        group2 = await ChatRepository.prepare_variant_group(
            db, 2, conversation_id="one", through_message_id=6
        )
        assert group2 == group
        db.add(
            ChatMessage(
                id=7,
                conversation_id="one",
                role="assistant",
                content="Latest answer",
                variant_group_id=group,
            )
        )
        await db.commit()
    async with sessions() as db:
        rows = (
            await db.scalars(
                select(ChatMessage).where(ChatMessage.conversation_id == "one")
            )
        ).all()
        assert [m.id for m in visible_messages(rows)] == [1, 7]
        assert [
            m.id for m in rows if m.variant_group_id == group and m.is_active_variant
        ] == [7]
        db.add(
            ChatMessage(
                id=8, conversation_id="one", role="user", content="New followup"
            )
        )
        db.add(
            ChatMessage(
                id=9,
                conversation_id="one",
                role="assistant",
                content="New followup answer",
            )
        )
        await db.commit()
        assert await ChatRepository.activate_variant(db, 2, conversation_id="one")
        await db.commit()
    async with sessions() as db:
        conversation = await ChatRepository.get_conversation(db, "one")

        async def allowed(*args, **kwargs):
            return conversation

        monkeypatch.setattr(chat_conversation, "require_conversation_access", allowed)
        result = await chat_conversation.get_conversation("one", SimpleNamespace(), db)
        assert [m["id"] for m in result["messages"]] == [1, 2, 8, 9]
        assert [
            m["id"] for m in result["messages"][1]["variants"] if m["is_active_variant"]
        ] == [2]


async def test_variant_operations_are_conversation_scoped(sessions):
    async with sessions() as db:
        with pytest.raises(ValueError):
            await ChatRepository.prepare_variant_group(
                db, 2, conversation_id="two", through_message_id=4
            )
        group = await ChatRepository.prepare_variant_group(
            db, 2, conversation_id="one", through_message_id=4
        )
        db.add(
            ChatMessage(
                id=5,
                conversation_id="one",
                role="assistant",
                content="new",
                variant_group_id=group,
            )
        )
        db.add(
            ChatMessage(
                id=6,
                conversation_id="two",
                role="assistant",
                content="cloned group",
                variant_group_id=group,
            )
        )
        await db.commit()
        assert not await ChatRepository.activate_variant(db, 2, conversation_id="two")
        assert await ChatRepository.activate_variant(db, 2, conversation_id="one")
        assert (await db.get(ChatMessage, 6)).is_active_variant


def test_legacy_multiple_active_variants_show_one_answer_at_original_position():
    def msg(identity, group=None, active=True):
        return SimpleNamespace(
            id=identity, variant_group_id=group, is_active_variant=active
        )

    rows = [msg(1), msg(2, "group"), msg(3), msg(4, "group")]
    assert [m.id for m in visible_messages(rows)] == [1, 4, 3]
