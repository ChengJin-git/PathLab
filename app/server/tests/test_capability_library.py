"""UGC visibility, activation and execution boundaries with real relational queries."""

from types import SimpleNamespace
import io, json, zipfile
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from backend.database.models import CapabilityEntry, CapabilityInstallation
from backend.services import capability_library as service, personal_connectors
from gateway.routes import capability_library as routes


@pytest.fixture
async def library(monkeypatch, tmp_path):
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    for model in [CapabilityEntry, CapabilityInstallation]:
        model.__table__.to_metadata(metadata)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    def user(name, role="pathologist"):
        return SimpleNamespace(
            id=name,
            role=role,
            is_admin=lambda: role == "admin",
            can_use_gpu=lambda: role != "guest",
        )

    users = {
        "a": user("a"),
        "b": user("b"),
        "admin": user("admin", "admin"),
        "guest": user("guest", "guest"),
    }
    actor = SimpleNamespace(user=users["a"])

    async def get_db():
        async with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.current_active_user] = lambda: actor.user
    app.dependency_overrides[routes.get_db] = get_db
    monkeypatch.setattr(service.Config, "get_autoresearch_dir", lambda: tmp_path)
    async with sessions() as db:
        db.add(
            CapabilityEntry(
                entry_id="nature-statistics",
                kind="skill",
                builtin=True,
                name="Statistical review",
                description="Review statistics",
                visibility="public",
                translations={
                    "zh-CN": {"name": "统计审查", "description": "统计方法审查"}
                },
            )
        )
        await db.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        yield SimpleNamespace(client=client, db=sessions, actor=actor, users=users)
    await engine.dispose()


async def create(library, name="Personal style", visibility="private", kind="skill"):
    response = await library.client.post(
        "/capabilities",
        json={
            "kind": kind,
            "name": name,
            "description": "Apply when writing a clinical handoff",
            "content": "# Handoff\nUse headings Facts, Uncertainty, Next step."
            if kind == "skill"
            else "",
            "url": "https://example.org/mcp" if kind == "connector" else "",
            "visibility": visibility,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_private_owner_admin_and_public_discovery(library):
    private = await create(library)
    public = await create(library, "Shared style", "public")
    library.actor.user = library.users["b"]
    assert (
        await library.client.get("/capabilities/" + private["id"])
    ).status_code == 404
    installed = (await library.client.get("/capabilities?kind=skill")).json()["items"]
    assert [row["id"] for row in installed] == ["nature-statistics"]
    discovery = (
        await library.client.get("/capabilities?kind=skill&view=discover")
    ).json()["items"]
    assert public["id"] in [row["id"] for row in discovery]
    assert (
        await library.client.put(
            "/capabilities/" + public["id"],
            json={
                "kind": "skill",
                "name": "Stolen",
                "content": "changed",
                "revision": 1,
            },
        )
    ).status_code == 403
    assert (
        await library.client.get("/capabilities?kind=skill&view=all")
    ).status_code == 403
    library.actor.user = library.users["admin"]
    assert (
        await library.client.get("/capabilities/" + private["id"])
    ).status_code == 200
    assert (
        len(
            (await library.client.get("/capabilities?kind=skill&view=all")).json()[
                "items"
            ]
        )
        == 3
    )


async def test_preload_is_bounded_metadata_and_load_rechecks_activation(library):
    entry = await create(library)
    async with library.db() as db:
        context, _ = await service.chat_context(db, library.users["a"], None)
        assert entry["id"] in context and "LOAD_SKILL" in context
        assert "Use headings Facts" not in context
        loaded = await service.load_chat_skill(
            db, library.users["a"], {"id": entry["id"]}
        )
        assert "Use headings Facts" in loaded
    await library.client.put(
        "/capabilities/" + entry["id"] + "/installation", json={"enabled": False}
    )
    async with library.db() as db:
        context, _ = await service.chat_context(db, library.users["a"], None)
        assert entry["id"] not in context
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            await service.load_chat_skill(db, library.users["a"], {"id": entry["id"]})


async def test_search_recovers_enabled_skill_beyond_initial_preload(library):
    async with library.db() as db:
        for index in range(80):
            db.add(
                CapabilityEntry(
                    entry_id=f"ugc-{index:04}",
                    kind="skill",
                    owner_id="a",
                    name=f"User skill {index}",
                    description="Custom workflow "
                    + ("rare recovery" if index == 79 else "other"),
                    content="Keep actual values.",
                    visibility="private",
                )
            )
        await db.commit()
        context, _ = await service.chat_context(db, library.users["a"], None)
        assert "ugc-0079" not in context
        recovered = json.loads(
            await service.load_chat_skill(
                db, library.users["a"], {"query": "rare recovery"}
            )
        )
        assert [row["id"] for row in recovered] == ["ugc-0079"]


async def test_unpublished_public_skill_is_immediately_revoked(library):
    entry = await create(library, visibility="public")
    library.actor.user = library.users["b"]
    assert (
        await library.client.put(
            "/capabilities/" + entry["id"] + "/installation", json={"enabled": True}
        )
    ).status_code == 200
    library.actor.user = library.users["a"]
    response = await library.client.put(
        "/capabilities/" + entry["id"],
        json={
            "kind": "skill",
            "name": entry["name"],
            "description": "Changed",
            "content": "# Private now",
            "visibility": "private",
            "revision": 1,
        },
    )
    assert response.status_code == 200
    library.actor.user = library.users["b"]
    assert (await library.client.get("/capabilities/" + entry["id"])).status_code == 404
    assert entry["id"] not in str(
        (await library.client.get("/capabilities?kind=skill")).json()
    )


async def test_connector_tokens_remain_personal_and_never_appear_in_catalog(
    library, monkeypatch
):
    entry = await create(library, kind="connector", visibility="public")
    result = await library.client.put(
        "/capabilities/" + entry["id"] + "/installation",
        json={"enabled": True, "token": "a-secret"},
    )
    assert result.json()["has_credential"] and "a-secret" not in result.text
    async with library.db() as db:
        installed = await db.get(CapabilityInstallation, ("a", entry["id"]))
        assert (
            installed.credential != "a-secret"
            and service.reveal(installed.credential) == "a-secret"
        )
    library.actor.user = library.users["b"]
    assert not (await library.client.get("/capabilities/" + entry["id"])).json()[
        "has_credential"
    ]
    await library.client.put(
        "/capabilities/" + entry["id"] + "/installation",
        json={"enabled": True, "token": "b-secret"},
    )
    async with library.db() as db:
        installed = await db.get(CapabilityInstallation, ("b", entry["id"]))
        assert service.reveal(installed.credential) == "b-secret"
    library.actor.user = library.users["admin"]
    assert not (await library.client.get("/capabilities/" + entry["id"])).json()[
        "has_credential"
    ]


async def test_mcp_catalog_and_execution_are_real_protocol_and_read_only_scoped(
    library, monkeypatch
):
    entry = await create(library, kind="connector")
    seen = []
    original = httpx.AsyncClient

    async def handler(request):
        if request.method == "DELETE":
            return httpx.Response(204)
        body = json.loads(request.content)
        seen.append(body["method"])
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        result = {"protocolVersion": "2025-03-26"}
        if body["method"] == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "lookup",
                        "description": "Lookup",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"value": {"type": "number"}},
                            "required": ["value"],
                        },
                        "annotations": {"readOnlyHint": True},
                    },
                    {"name": "write", "inputSchema": {"type": "object"}},
                ]
            }
        if body["method"] == "tools/call":
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": str(body["params"]["arguments"]["value"] * 2),
                    }
                ]
            }
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "result": result},
            headers={"mcp-session-id": "s"},
        )

    monkeypatch.setattr(personal_connectors, "validate_external_url", lambda url: url)
    monkeypatch.setattr(
        personal_connectors.httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    async with library.db() as db:
        assert (await personal_connectors.connect(db, library.users["a"], entry["id"]))[
            "tool_count"
        ] == 2
        result = await personal_connectors.call(
            db, library.users["a"], entry["id"], "lookup", {"value": 21}, "read_only"
        )
        assert "42" in result
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            await personal_connectors.call(
                db, library.users["a"], entry["id"], "write", {}, "read_only"
            )
        with pytest.raises(ValueError):
            await personal_connectors.call(
                db, library.users["a"], entry["id"], "lookup", {"value": "invalid"}
            )
    assert seen.count("tools/call") == 1


async def test_pagination_localization_and_body_lazy_loading(library):
    async with library.db() as db:
        for index in range(44):
            db.add(
                CapabilityEntry(
                    entry_id=f"ugc-{index:04}",
                    kind="skill",
                    owner_id="a",
                    name=f"Skill {index}",
                    description="fixture",
                    content="large body " * 1000,
                    visibility="private",
                )
            )
        await db.commit()
    first = (await library.client.get("/capabilities?kind=skill&language=zh-CN")).json()
    assert len(first["items"]) == 20 and first["next_cursor"]
    assert first["items"][0]["name"] == "统计审查" and "large body" not in str(first)
    second = (
        await library.client.get(
            "/capabilities",
            params={
                "kind": "skill",
                "cursor": first["next_cursor"],
                "language": "zh-CN",
            },
        )
    ).json()
    assert not {r["id"] for r in first["items"]} & {r["id"] for r in second["items"]}
    assert (
        await library.client.get(
            "/capabilities",
            params={"kind": "connector", "cursor": first["next_cursor"]},
        )
    ).status_code == 422


async def test_imported_skill_preserves_resources_and_rejects_escape(library):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "bundle/SKILL.md",
            "---\nname: Handoff\ndescription: Clinical handoff style\n---\nRead [guide](guide.md).",
        )
        archive.writestr("bundle/guide.md", "Use exact measured values.")
    response = await library.client.post(
        "/capabilities/import-skill",
        files={"file": ("handoff.zip", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 200, response.text
    async with library.db() as db:
        body = await service.load_chat_skill(
            db, library.users["a"], {"id": response.json()["id"], "path": "guide.md"}
        )
        assert body == "Use exact measured values."
        with pytest.raises(ValueError):
            await service.load_chat_skill(
                db,
                library.users["a"],
                {"id": response.json()["id"], "path": "../private"},
            )


async def test_full_package_editing_updates_chat_and_executable_snapshot(
    library, tmp_path
):
    from backend.services import skill_packages
    from backend.autoresearch.engine.skills import snapshot_skills, install_skills
    import subprocess

    entry = await create(library)
    base = "/capabilities/" + entry["id"]

    async def save(path, content, revision, **kwargs):
        result = await library.client.put(
            base + "/file",
            json={"path": path, "content": content, "revision": revision, **kwargs},
        )
        assert result.status_code == 200, result.text
        return result.json()["revision"]

    revision = await save(
        "scripts/run.py",
        'from pathlib import Path\nprint(Path(__file__).parents[1].joinpath("assets/payload.bin").read_bytes().hex())\n',
        1,
        executable=True,
    )
    binary = b"\x00\xff\x10\x80"
    uploaded = await library.client.post(
        base + "/file",
        params={"path": "assets/payload.bin", "revision": revision},
        files={"file": ("payload.bin", binary)},
    )
    assert uploaded.status_code == 200, uploaded.text
    revision = uploaded.json()["revision"]
    assert (
        await library.client.get(base + "/file", params={"path": "assets/payload.bin"})
    ).json()["text"] is None
    assert (
        await library.client.get(
            base + "/file", params={"path": "assets/payload.bin", "download": "true"}
        )
    ).content == binary
    revision = await save("config/rules.json", '{"label":"updated"}', revision)
    revision = await save(
        "SKILL.md",
        "# Updated\nRead [rules](config/rules.json); run scripts/run.py when execution is requested.",
        revision,
        overwrite=True,
    )
    async with library.db() as db:
        row = await service.selected_skill(db, library.users["a"], entry["id"])
        assert row.revision == revision and row.content.startswith("# Updated")
        assert "updated" in await service.load_chat_skill(
            db, library.users["a"], {"id": entry["id"], "path": "config/rules.json"}
        )
        research = await service.research_skill(row, library.users["a"])
        root = tmp_path / "session"
        snapshots = snapshot_skills([research], root, "a")
        install_skills(root, snapshots)
        script = root / ".opencode/packages" / research.package_id / "scripts/run.py"
        assert script.stat().st_mode & 0o111
        assert (
            subprocess.check_output(["python", str(script)], text=True).strip()
            == binary.hex()
        )
        assert "# Updated" in script.parents[1].joinpath("SKILL.md").read_text()
        package = skill_packages.package_path(row)
    revision = await save(
        "config/rules.json", '{"label":"newer"}', revision, overwrite=True
    )
    assert not package.exists()
    removed = await library.client.delete(
        base + "/file", params={"path": "config/rules.json", "revision": revision}
    )
    assert removed.status_code == 200
    assert (
        await library.client.get(base + "/file", params={"path": "config/rules.json"})
    ).status_code == 404
    # Earlier research snapshots remain self-contained after a library edit/delete.
    assert (
        script.parents[1].joinpath("config/rules.json").read_text()
        == '{"label":"updated"}'
    )
    listing = (await library.client.get(base + "/files")).json()
    assert listing["entrypoint"] == "SKILL.md" and len(listing["items"]) == 3
    await library.client.delete(base)
    assert not list((tmp_path / "capability-packages").glob("*.zip"))


async def test_package_permissions_conflicts_and_replacement(library):
    entry = await create(library, visibility="public")
    base = "/capabilities/" + entry["id"]
    body = {"path": "script.py", "content": "print(42)\n", "revision": 1}
    library.actor.user = library.users["b"]
    assert (await library.client.get(base + "/files")).status_code == 200
    assert (await library.client.put(base + "/file", json=body)).status_code == 403
    library.actor.user = library.users["a"]
    assert (await library.client.put(base + "/file", json=body)).status_code == 200
    assert (await library.client.put(base + "/file", json=body)).status_code == 409
    body["revision"] = 2
    assert (await library.client.put(base + "/file", json=body)).status_code == 409
    for path in [
        "../private",
        "/etc/passwd",
        "scripts/../secret",
        "a\\b",
        ".git/config",
        "script.py/child",
    ]:
        assert (
            await library.client.put(base + "/file", json={**body, "path": path})
        ).status_code == 422
    assert (
        await library.client.delete(
            base + "/file", params={"path": "SKILL.md", "revision": 2}
        )
    ).status_code == 422
    library.actor.user = library.users["admin"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("bundle/SKILL.md", "# Replacement\nUse scripts/step.sh")
        archive.writestr("bundle/scripts/step.sh", "echo replacement\n")
    response = await library.client.put(
        base + "/package",
        params={"revision": 2},
        files={"file": ("replace.zip", buffer.getvalue())},
    )
    assert response.status_code == 200, response.text
    detail = (await library.client.get(base)).json()
    assert (
        detail["owner_id"] == "a"
        and detail["visibility"] == "public"
        and detail["revision"] == 3
    )
    assert (
        detail["content"].startswith("# Replacement")
        and "package_file" not in detail["config"]
    )
    assert (
        await library.client.get(base + "/file", params={"path": "script.py"})
    ).status_code == 404
    library.actor.user = library.users["a"]
    await library.client.put(
        base,
        json={
            "kind": "skill",
            "name": "Private now",
            "content": detail["content"],
            "revision": 3,
            "visibility": "private",
        },
    )
    library.actor.user = library.users["b"]
    assert (await library.client.get(base + "/files")).status_code == 404
    assert (
        await library.client.get(
            base + "/file", params={"path": "SKILL.md", "download": "true"}
        )
    ).status_code == 404


async def test_failed_package_write_does_not_publish_or_lose_previous_files(
    library, monkeypatch, tmp_path
):
    from backend.services import skill_packages

    entry = await create(library)
    base = "/capabilities/" + entry["id"]
    assert (
        await library.client.put(
            base + "/file",
            json={"path": "rules.json", "content": '{"v":1}', "revision": 1},
        )
    ).status_code == 200

    def fail(destination, files):
        destination.write_bytes(b"partial archive")
        raise ValueError("Simulated write failure")

    monkeypatch.setattr(skill_packages, "write_archive", fail)
    response = await library.client.put(
        base + "/file",
        json={
            "path": "rules.json",
            "content": '{"v":2}',
            "overwrite": True,
            "revision": 2,
        },
    )
    assert response.status_code == 422
    assert (await library.client.get(base)).json()["revision"] == 2
    assert (
        await library.client.get(base + "/file", params={"path": "rules.json"})
    ).json()["text"] == '{"v":1}'
    assert len(list((tmp_path / "capability-packages").glob("*.zip"))) == 1


async def test_file_list_is_paginated_and_text_edit_does_not_trim_scripts(library):
    entry = await create(library)
    base = "/capabilities/" + entry["id"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", "# Files\nUse resources.")
        for index in range(60):
            archive.writestr(f"scripts/step-{index:02}.py", "print(1)\n")
    assert (
        await library.client.put(
            base + "/package",
            params={"revision": 1},
            files={"file": ("files.zip", buffer.getvalue())},
        )
    ).status_code == 200
    first = (await library.client.get(base + "/files")).json()
    assert len(first["items"]) == 50 and first["next_cursor"]
    second = (
        await library.client.get(
            base + "/files",
            params={"after": first["next_cursor"], "revision": first["revision"]},
        )
    ).json()
    assert len(second["items"]) == 11 and not set(
        i["path"] for i in first["items"]
    ) & set(i["path"] for i in second["items"])
    script = "  indented\n\n"
    response = await library.client.put(
        base + "/file",
        json={
            "path": "scripts/step-00.py",
            "content": script,
            "revision": 2,
            "overwrite": True,
        },
    )
    assert response.status_code == 200
    assert (
        await library.client.get(base + "/file", params={"path": "scripts/step-00.py"})
    ).json()["text"] == script
    assert (
        await library.client.get(
            base + "/files", params={"after": first["next_cursor"], "revision": 2}
        )
    ).status_code == 409


async def test_cancellation_waits_for_package_publication(library, monkeypatch):
    import asyncio
    import threading
    from backend.services import skill_packages

    entry = await create(library)
    started = threading.Event()
    finish = threading.Event()
    write = skill_packages.write_archive

    def delayed(destination, files):
        started.set()
        assert finish.wait(5)
        write(destination, files)

    monkeypatch.setattr(skill_packages, "write_archive", delayed)
    async with library.db() as db:
        row = await service.get_entry(db, library.users["a"], entry["id"], edit=True)
        task = asyncio.create_task(
            skill_packages.publish(db, row, {"SKILL.md": (b"# New rules", False)})
        )
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    detail = (await library.client.get("/capabilities/" + entry["id"])).json()
    assert detail["revision"] == 2 and detail["content"] == "# New rules"
    assert (
        await library.client.get(
            "/capabilities/" + entry["id"] + "/file", params={"path": "SKILL.md"}
        )
    ).json()["text"] == "# New rules"
