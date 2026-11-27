"""Real relational filing: ownership, persistence, paging and scope preservation."""

from types import SimpleNamespace
from datetime import datetime, timedelta
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from backend.database.models import ChatFolder, ChatConversation, StorageTask
from gateway.routes import chat_navigation as routes


@pytest.fixture
async def api():
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    for model in [ChatFolder, ChatConversation, StorageTask]:
        model.__table__.to_metadata(metadata)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor = SimpleNamespace(user=SimpleNamespace(id="a"))

    async def db():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.current_active_user] = lambda: actor.user
    app.dependency_overrides[routes.get_db] = db
    async with sessions() as session:
        session.add(
            ChatConversation(
                conversation_id="a-chat",
                user_id="a",
                title="Own chat",
                workspace_id="scope-a",
            )
        )
        session.add(
            ChatConversation(
                conversation_id="b-chat",
                user_id="b",
                title="Private chat",
                workspace_id="scope-b",
            )
        )
        await session.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        yield SimpleNamespace(client=client, db=sessions, actor=actor)
    await engine.dispose()


async def test_create_rename_move_delete_keeps_chat_and_scope(api):
    root = "/chat-navigation"
    folder = (await api.client.post(root + "/folders", json={"name": "Study"})).json()
    assert (
        await api.client.patch(
            root + "/folders/" + folder["id"], json={"name": "Renamed"}
        )
    ).json()["name"] == "Renamed"
    async with api.db() as db:
        before = await db.scalar(
            select(ChatConversation).where(ChatConversation.conversation_id == "a-chat")
        )
        timestamp = before.updated_at
    assert (
        await api.client.patch(
            root + "/chats/a-chat", json={"folder_id": folder["id"], "pinned": True}
        )
    ).status_code == 200
    assert not (await api.client.get(root + "/chats")).json()["items"]
    filed = (
        await api.client.get(root + "/chats", params={"folder": folder["id"]})
    ).json()["items"][0]
    assert (
        filed["folder_name"] == "Renamed"
        and filed["pinned"]
        and filed["workspace_id"] == "scope-a"
    )
    assert (
        await api.client.delete(root + "/folders/" + folder["id"])
    ).status_code == 200
    rows = (await api.client.get(root + "/chats")).json()["items"]
    assert len(rows) == 1 and rows[0]["folder_id"] is None
    async with api.db() as db:
        row = await db.scalar(
            select(ChatConversation).where(ChatConversation.conversation_id == "a-chat")
        )
        assert row.workspace_id == "scope-a" and row.updated_at == timestamp


async def test_owner_isolation_including_admin_and_invalid_destination(api):
    root = "/chat-navigation"
    folder = (await api.client.post(root + "/folders", json={"name": "Private"})).json()
    api.actor.user = SimpleNamespace(id="b", role="admin")
    assert not (await api.client.get(root + "/folders")).json()["items"]
    for method, payload in [("patch", {"json": {"name": "Stolen"}}), ("delete", {})]:
        assert (
            await getattr(api.client, method)(
                root + "/folders/" + folder["id"], **payload
            )
        ).status_code == 404
    assert (
        await api.client.patch(root + "/chats/b-chat", json={"folder_id": folder["id"]})
    ).status_code == 404
    assert (
        await api.client.patch(root + "/chats/a-chat", json={"title": "Stolen"})
    ).status_code == 404
    assert (
        await api.client.get(root + "/chats", params={"folder": folder["id"]})
    ).status_code == 404
    assert [
        row["conversation_id"]
        for row in (await api.client.get(root + "/chats", params={"q": "chat"})).json()[
            "items"
        ]
    ] == ["b-chat"]


async def test_keyset_search_includes_folders_pins_and_no_duplicates(api):
    root = "/chat-navigation"
    folder = (await api.client.post(root + "/folders", json={"name": "Folder"})).json()
    async with api.db() as db:
        for i in range(75):
            db.add(
                ChatConversation(
                    conversation_id=f"c-{i:03}",
                    user_id="a",
                    title=f"needle {i}",
                    folder_id=folder["id"] if i % 2 else None,
                    pinned=i % 5 == 0,
                    updated_at=datetime(2026, 1, 1) + timedelta(minutes=i),
                )
            )
        db.add(
            ChatConversation(conversation_id="literal", user_id="a", title="literal %_")
        )
        await db.commit()
    cursor = ""
    seen = []
    pins = []
    while True:
        response = await api.client.get(
            root + "/chats", params={"q": "needle", "cursor": cursor}
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert len(page["items"]) <= 30
        seen.extend(row["conversation_id"] for row in page["items"])
        pins.extend(row["pinned"] for row in page["items"])
        if not page["next_cursor"]:
            break
        cursor = page["next_cursor"]
    assert len(seen) == len(set(seen)) == 75 and pins == sorted(pins, reverse=True)
    assert (
        await api.client.get(
            root + "/chats", params={"q": "different", "cursor": cursor}
        )
    ).status_code == 422
    assert [
        row["conversation_id"]
        for row in (await api.client.get(root + "/chats", params={"q": "%_"})).json()[
            "items"
        ]
    ] == ["literal"]
    assert (await api.client.get(root + "/chats?limit=1000")).status_code == 422


async def test_blank_names_rejected_and_folders_paged(api):
    root = "/chat-navigation"
    assert (
        await api.client.post(root + "/folders", json={"name": "   "})
    ).status_code == 422
    async with api.db() as db:
        for i in range(55):
            db.add(ChatFolder(folder_id=f"f-{i:03}", user_id="a", name=f"Folder {i}"))
        await db.commit()
    first = (await api.client.get(root + "/folders")).json()
    assert len(first["items"]) == 30
    second = (
        await api.client.get(root + "/folders", params={"after": first["next_cursor"]})
    ).json()
    assert len(second["items"]) == 25
    assert not set(row["id"] for row in first["items"]) & set(
        row["id"] for row in second["items"]
    )


async def test_pending_deletion_leaves_navigation_immediately(api):
    async with api.db() as db:
        db.add(
            StorageTask(
                task_id="cleanup-a",
                user_id="a",
                task_type="chat_delete",
                status="pending",
                params={"conversation_id": "a-chat"},
            )
        )
        await db.commit()
    assert not (await api.client.get("/chat-navigation/chats")).json()["items"]
