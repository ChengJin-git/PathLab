"""File lifecycle, knowledge permissions and stale-index authorization on real SQL."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from backend.database.models import WorkbenchFile, FileLibraryFolder, ChatConversation
from backend.auth.models import User
from backend.services import file_library, knowledge
from gateway.routes import file_library as routes


@pytest.fixture
async def api(monkeypatch, tmp_path):
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    for model in [User, WorkbenchFile, FileLibraryFolder, ChatConversation]:
        model.__table__.to_metadata(metadata)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor = SimpleNamespace(user=SimpleNamespace(id="a", is_admin=lambda: False))

    async def get_db():
        async with sessions() as db:
            yield db

    @asynccontextmanager
    async def safe_session():
        async with sessions() as db:
            yield db

    monkeypatch.setattr(file_library.Config, "get_uploads_dir", lambda: tmp_path)
    monkeypatch.setattr(knowledge, "safe_session", safe_session)
    monkeypatch.setattr("backend.database.database.safe_session", safe_session)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.current_active_user] = lambda: actor.user
    app.dependency_overrides[routes.get_db] = get_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        yield SimpleNamespace(client=client, db=sessions, actor=actor, root=tmp_path)
    await engine.dispose()


async def upload(api, name="reference.txt", content=b"Original evidence 38 minutes."):
    response = await api.client.post(
        "/file-library/upload", files={"file": (name, content)}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_owner_admin_visibility_folders_and_replacement(api):
    file = await upload(api)
    folder = (
        await api.client.post("/file-library/folders", json={"name": "Research"})
    ).json()
    result = await api.client.patch(
        "/file-library/files/" + file["id"],
        json={
            "revision": file["revision"],
            "updated_at": file["updated_at"],
            "name": "renamed.txt",
            "folder_id": folder["id"],
        },
    )
    assert result.status_code == 200
    assert (
        await api.client.get("/file-library", params={"folder": folder["id"]})
    ).json()["items"][0]["name"] == "renamed.txt"
    api.actor.user = SimpleNamespace(id="b", is_admin=lambda: False)
    assert not (await api.client.get("/file-library")).json()["items"]
    assert (
        await api.client.get("/file-library/files/" + file["id"])
    ).status_code == 404
    assert (
        await api.client.delete("/file-library/files/" + file["id"])
    ).status_code == 404
    assert (await api.client.get("/file-library?view=all")).status_code == 403
    api.actor.user = SimpleNamespace(id="admin", is_admin=lambda: True)
    assert len((await api.client.get("/file-library?view=all")).json()["items"]) == 1
    assert not (await api.client.get("/file-library")).json()["items"]
    result = await api.client.put(
        "/file-library/files/" + file["id"] + "/content",
        params={"revision": file["revision"]},
        files={"file": ("new.txt", b"Updated evidence 52 minutes.")},
    )
    assert result.status_code == 200
    assert (
        result.json()["revision"] != file["revision"]
        and result.json()["owner_id"] == "a"
    )
    assert (
        await api.client.patch(
            "/file-library/files/" + file["id"],
            json={
                "revision": file["revision"],
                "updated_at": file["updated_at"],
                "name": "stale.txt",
            },
        )
    ).status_code == 409
    await api.client.delete("/file-library/folders/" + folder["id"])
    assert (await api.client.get("/file-library/files/" + file["id"])).json()[
        "folder_id"
    ] is None


async def test_automatic_index_update_cancel_delete(api, monkeypatch):
    file = await upload(api)
    root = "/file-library"
    assert file["index_status"] == "queued"

    # A production worker must compare committed revision before publishing.
    async def parse(path):
        return [{"text": "38 minutes", "page": 1}]

    monkeypatch.setattr(knowledge, "parse_file", parse)
    monkeypatch.setattr(knowledge, "index_chunks", lambda *args: 1)
    monkeypatch.setattr(knowledge, "remove_index", lambda *args: None)
    assert await knowledge.process_one()
    assert (await api.client.get(root + "/files/" + file["id"])).json()[
        "index_status"
    ] == "ready"
    response = await api.client.put(
        root + "/files/" + file["id"] + "/content",
        params={"revision": file["revision"]},
        files={"file": ("reference.txt", b"52 minutes")},
    )
    assert response.status_code == 200
    assert (
        response.json()["index_status"] == "queued"
        and response.json()["indexed_revision"] is None
    )
    await api.client.delete(root + "/files/" + file["id"] + "/index")
    assert not await knowledge.process_one()
    await api.client.post(root + "/files/" + file["id"] + "/index")
    assert await knowledge.process_one()
    await api.client.delete(root + "/files/" + file["id"])
    assert not (await api.client.get(root)).json()["items"]
    assert not list((api.root / "chat-files" / "a").glob(file["id"] + "*"))


async def test_retrieval_filters_before_search_and_revokes_during_search(
    api, monkeypatch
):
    file = await upload(api)
    async with api.db() as db:
        row = await db.get(WorkbenchFile, file["id"])
        row.index_status = "ready"
        row.indexed_revision = row.revision
        await db.commit()
    calls = []

    def search(owner, files, query, limit):
        calls.append((owner, files))
        return [
            {
                "file_id": file["id"],
                "revision": file["revision"],
                "text": "Evidence",
                "page": 2,
                "section": "Protocol",
                "score": 1,
            }
        ]

    monkeypatch.setattr(knowledge, "search_owner", search)
    api.actor.user = SimpleNamespace(id="b", is_admin=lambda: False)
    response = await api.client.post(
        "/file-library/search", json={"query": "protocol", "file_ids": [file["id"]]}
    )
    assert response.status_code == 404 and not calls
    assert (
        await api.client.post("/file-library/search", json={"query": "protocol"})
    ).json()["items"] == [] and not calls
    api.actor.user = SimpleNamespace(id="a", is_admin=lambda: False)
    response = await api.client.post("/file-library/search", json={"query": "protocol"})
    assert response.status_code == 200, response.text
    assert calls == [("a", [(file["id"], file["revision"])])]
    assert response.json()["items"][0]["page"] == 2
    async with api.db() as db:
        row = await db.get(WorkbenchFile, file["id"])
        row.revision = "new-version"
        await db.commit()
    response = await api.client.post("/file-library/search", json={"query": "protocol"})
    assert response.json()["items"] == []


async def test_file_list_pagination_search_is_metadata_only(api):
    async with api.db() as db:
        for index in range(65):
            db.add(
                WorkbenchFile(
                    file_id=f"f{index:03}",
                    user_id="a",
                    name=f"evidence-{index}.txt",
                    path="/not/read",
                    storage_path="/not/read",
                    size=10,
                    revision="r",
                )
            )
        await db.commit()
    first = (await api.client.get("/file-library?q=evidence")).json()
    assert len(first["items"]) == 30 and first["next_cursor"]
    second = (
        await api.client.get(
            "/file-library", params={"q": "evidence", "cursor": first["next_cursor"]}
        )
    ).json()
    assert not set(item["id"] for item in first["items"]) & set(
        item["id"] for item in second["items"]
    )
    assert "storage_path" not in str(first)
    assert (
        await api.client.get(
            "/file-library", params={"q": "different", "cursor": first["next_cursor"]}
        )
    ).status_code == 422


async def test_retrieval_rechecks_deletion_after_search_and_keeps_bound_user_valid(
    api, monkeypatch
):
    import uuid, asyncio

    identity = uuid.uuid4()
    async with api.db() as db:
        user = User(
            id=identity,
            username="bound-user",
            hashed_password="fixture",
            role="pathologist",
            is_active=True,
        )
        row = WorkbenchFile(
            file_id="revoked",
            user_id=str(identity),
            name="private.txt",
            path="/unused",
            revision="r",
            indexed_revision="r",
            index_status="ready",
        )
        db.add_all([user, row])
        await db.commit()
    loop = asyncio.get_running_loop()

    async def revoke():
        async with api.db() as db:
            row = await db.get(WorkbenchFile, "revoked")
            row.deleted = True
            await db.commit()

    def search(*args):
        asyncio.run_coroutine_threadsafe(revoke(), loop).result(timeout=5)
        return [
            {
                "file_id": "revoked",
                "revision": "r",
                "text": "secret",
                "page": 1,
                "section": "",
                "score": 1,
            }
        ]

    monkeypatch.setattr(knowledge, "search_owner", search)
    async with api.db() as db:
        user = await db.get(User, identity)
        assert await knowledge.retrieve(db, user, "secret") == []
        assert (
            user.is_admin() is False
        )  # Retrieval must not expire its authenticated user.


@pytest.mark.parametrize("action", ["replace", "delete", "cancel"])
async def test_index_publication_cannot_restore_a_revoked_version(
    api, monkeypatch, action
):
    import asyncio

    file = await upload(api)
    endpoint = "/file-library/files/" + file["id"]
    loop = asyncio.get_running_loop()
    removed = []

    async def parse(_path):
        return [{"text": "Original evidence", "page": 1}]

    async def revoke():
        if action == "replace":
            response = await api.client.put(
                endpoint + "/content",
                params={"revision": file["revision"]},
                files={"file": ("updated.txt", b"New evidence")},
            )
        else:
            response = await api.client.delete(
                endpoint + ("/index" if action == "cancel" else "")
            )
        assert response.status_code == 200

    def index(*_args):
        asyncio.run_coroutine_threadsafe(revoke(), loop).result(timeout=5)
        return 1

    monkeypatch.setattr(knowledge, "parse_file", parse)
    monkeypatch.setattr(knowledge, "index_chunks", index)
    monkeypatch.setattr(knowledge, "remove_index", lambda *args: removed.append(args))
    assert await knowledge.process_one()
    async with api.db() as db:
        row = await db.get(WorkbenchFile, file["id"])
        assert row.index_status != "ready" and row.indexed_revision is None
        if action == "replace":
            assert row.revision != file["revision"] and row.index_status == "queued"
        elif action == "delete":
            assert row.deleted
    assert ("a", file["id"]) in removed


async def test_failed_index_is_explicit_and_can_be_retried(api, monkeypatch):
    file = await upload(api)
    endpoint = "/file-library/files/" + file["id"]

    async def invalid(_path):
        raise ValueError("No readable text found")

    monkeypatch.setattr(knowledge, "parse_file", invalid)
    assert await knowledge.process_one()
    row = (await api.client.get(endpoint)).json()
    assert row["index_status"] == "failed" and "No readable text" in row["index_error"]
    assert not await knowledge.process_one()

    async def valid(_path):
        return [{"text": "Recovered evidence", "page": 1}]

    monkeypatch.setattr(knowledge, "parse_file", valid)
    monkeypatch.setattr(knowledge, "index_chunks", lambda *_: 1)
    assert (await api.client.post(endpoint + "/index")).status_code == 200
    assert await knowledge.process_one()
    row = (await api.client.get(endpoint)).json()
    assert row["index_status"] == "ready" and row["index_error"] is None


async def test_conversation_groups_have_bounded_owner_scoped_pages(api):
    async with api.db() as db:
        for index in range(35):
            identity = f"chat-{index:02}"
            db.add(
                ChatConversation(conversation_id=identity, user_id="a", title=identity)
            )
            db.add(
                WorkbenchFile(
                    file_id=f"file-{index}",
                    conversation_id=identity,
                    user_id="a",
                    name="note.txt",
                    path="/unused",
                    size=20,
                    revision="r",
                )
            )
        db.add(
            WorkbenchFile(
                file_id="private",
                conversation_id="secret-chat",
                user_id="b",
                name="private.txt",
                path="/unused",
            )
        )
        await db.commit()
    first = (await api.client.get("/file-library/groups")).json()
    assert len(first["items"]) == 30 and first["next_cursor"]
    second = (
        await api.client.get(
            "/file-library/groups", params={"cursor": first["next_cursor"]}
        )
    ).json()
    assert len(second["items"]) == 5 and not second["next_cursor"]
    assert not {item["id"] for item in first["items"]} & {
        item["id"] for item in second["items"]
    }
    item = first["items"][0]
    assert item["file_count"] == 1 and item["total_size"] == 20
    files = (
        await api.client.get("/file-library", params={"conversation": item["id"]})
    ).json()["items"]
    assert len(files) == 1 and files[0]["conversation_id"] == item["id"]
    assert (await api.client.get("/file-library/groups?view=all")).status_code == 403
    assert (
        await api.client.get(
            "/file-library/groups", params={"cursor": first["next_cursor"], "q": "note"}
        )
    ).status_code == 422
    assert (
        await api.client.get("/file-library/groups?cursor=invalid")
    ).status_code == 422


async def test_batch_edit_is_atomic_owner_checked_and_detects_metadata_conflicts(api):
    first, second = await upload(api), await upload(api, "second.txt")

    def item(file, name=None):
        return {key: file[key] for key in ["id", "revision", "updated_at"]} | (
            {"name": name} if name else {}
        )

    response = await api.client.post(
        "/file-library/batch",
        json={
            "operation": "edit",
            "files": [item(first, "one.txt"), item(second, "two.txt")],
        },
    )
    assert response.status_code == 200, response.text
    assert {value["name"] for value in response.json()["items"]} == {
        "one.txt",
        "two.txt",
    }
    assert (
        await api.client.patch(
            "/file-library/files/" + first["id"],
            json={
                "revision": first["revision"],
                "updated_at": first["updated_at"],
                "name": "stale.txt",
            },
        )
    ).status_code == 409
    latest = response.json()["items"]
    api.actor.user = SimpleNamespace(id="b", is_admin=lambda: False)
    other = await upload(api)
    api.actor.user = SimpleNamespace(id="a", is_admin=lambda: False)
    assert (
        await api.client.post(
            "/file-library/batch",
            json={"operation": "delete", "files": [item(latest[0]), item(other)]},
        )
    ).status_code == 404
    assert len((await api.client.get("/file-library")).json()["items"]) == 2
    assert (
        await api.client.post(
            "/file-library/batch",
            json={"operation": "delete", "files": [item(file) for file in latest]},
        )
    ).status_code == 200
    assert not (await api.client.get("/file-library")).json()["items"]
    assert not list((api.root / "chat-files" / "a").glob("*"))
    assert list((api.root / "chat-files" / "b").glob("*"))


async def test_text_edit_reindexes_and_rejects_stale_or_unauthorized_writes(api):
    file = await upload(api)
    endpoint = "/file-library/files/" + file["id"] + "/text"
    assert (await api.client.get(endpoint)).json()[
        "content"
    ] == "Original evidence 38 minutes."
    response = await api.client.put(
        endpoint,
        json={"revision": file["revision"], "content": "Updated to 52 minutes."},
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["index_status"] == "queued"
        and response.json()["revision"] != file["revision"]
    )
    assert (
        await api.client.put(
            endpoint, json={"revision": file["revision"], "content": "stale"}
        )
    ).status_code == 409
    api.actor.user = SimpleNamespace(id="b", is_admin=lambda: False)
    assert (await api.client.get(endpoint)).status_code == 404
    assert (
        await api.client.put(
            endpoint,
            json={"revision": response.json()["revision"], "content": "unauthorized"},
        )
    ).status_code == 404


async def test_delete_retries_byte_cleanup_after_failure(api, monkeypatch):
    file = await upload(api)
    original = file_library.purge_file

    def fail(_record):
        raise OSError("busy")

    monkeypatch.setattr(file_library, "purge_file", fail)
    assert (
        await api.client.delete("/file-library/files/" + file["id"])
    ).status_code == 200
    assert not (await api.client.get("/file-library")).json()["items"]
    assert list((api.root / "chat-files" / "a").glob("*"))
    monkeypatch.setattr(file_library, "purge_file", original)
    await file_library.cleanup_deleted_files()
    assert not list((api.root / "chat-files" / "a").glob("*"))
