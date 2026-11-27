"""GitHub synchronization publishes actual resources and preserves connection settings."""

import json
from unittest.mock import AsyncMock
import pytest
from backend.database.models import CapabilityInstallation
from backend.services import (
    capability_sources as sources,
    capability_library,
    skill_packages,
)
from test_capability_library import create

pytest_plugins = ["test_capability_library"]


def repository():
    return {
        "skills/demo/SKILL.md": (
            b"---\nname: demo\ndescription: A useful skill\n---\n# Synced\nRead resources.txt.",
            False,
        ),
        "skills/demo/resources.txt": (b"measured source", False),
        "skills/demo/logo.svg": (
            b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h10v10z"/></svg>',
            False,
        ),
    }, {
        "url": "https://github.com/example/skills",
        "path": "skills/demo/SKILL.md",
        "commit": "a" * 40,
        "ref": "main",
        "license": "MIT",
        "description": "Source",
    }


async def test_sync_publishes_resources_logo_and_keeps_source_after_file_edits(
    library, monkeypatch
):
    entry = await create(library)
    monkeypatch.setattr(
        sources, "download_source", AsyncMock(return_value=repository())
    )
    response = await library.client.post(
        f"/capabilities/{entry['id']}/sync-github",
        json={
            "revision": 1,
            "source_url": "https://github.com/example/skills/tree/main/skills/demo",
        },
    )
    assert response.status_code == 200, response.text
    synced = response.json()
    assert synced["revision"] == 2 and synced["github_source"]["commit"] == "a" * 40
    assert synced["logo"]["license"] == "MIT"
    assert (
        await library.client.get(f"/capabilities/{entry['id']}/logo")
    ).status_code == 200
    async with library.db() as db:
        row = await capability_library.get_entry(db, library.users["a"], entry["id"])
        assert (
            skill_packages.read_files(row)["skills/demo/resources.txt"][0]
            == b"measured source"
        )
        files = skill_packages.read_files(row)
        files["skills/demo/resources.txt"] = (b"local edit", False)
        await skill_packages.publish(db, row, files, "skills/demo/SKILL.md")
        assert row.config["github_source"]["commit"] == "a" * 40
    stale = await library.client.post(
        f"/capabilities/{entry['id']}/sync-github", json={"revision": 2}
    )
    assert stale.status_code == 409


async def test_sync_permissions_and_builtin_execution(library, monkeypatch):
    entry = await create(library, visibility="public")
    download = AsyncMock(return_value=repository())
    monkeypatch.setattr(sources, "download_source", download)
    library.actor.user = library.users["b"]
    assert (
        await library.client.post(
            f"/capabilities/{entry['id']}/sync-github",
            json={"revision": 1, "source_url": "https://github.com/example/skills"},
        )
    ).status_code == 403
    download.assert_not_called()
    library.actor.user = library.users["admin"]
    response = await library.client.post(
        "/capabilities/nature-statistics/sync-github", json={"revision": 1}
    )
    assert response.status_code == 200, response.text
    async with library.db() as db:
        row = await capability_library.get_entry(
            db, library.users["a"], "nature-statistics"
        )
        loaded = json.loads(
            await capability_library.load_chat_skill(
                db, library.users["a"], {"id": row.entry_id}
            )
        )
        assert "# Synced" in loaded["instructions"]
        assert loaded["entrypoint"] == "skills/demo/SKILL.md"
        assert (
            await capability_library.research_skill(row, library.users["a"]) is not None
        )


async def test_connector_sync_keeps_endpoint_credentials_and_connection(
    library, monkeypatch
):
    entry = await create(library, kind="connector")
    async with library.db() as db:
        installed = await db.get(CapabilityInstallation, ("a", entry["id"]))
        installed.credential = "encrypted-private"
        installed.connected_revision = 1
        installed.tool_catalog = [{"name": "lookup"}]
        await db.commit()
    monkeypatch.setattr(
        sources, "download_source", AsyncMock(return_value=repository())
    )
    response = await library.client.post(
        f"/capabilities/{entry['id']}/sync-github",
        json={"revision": 1, "source_url": "https://github.com/example/server"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["config"]["url"] == "https://example.org/mcp"
    assert response.json()["connected"]
    assert "encrypted-private" not in response.text


def test_logo_rejects_active_svg_and_source_rejects_external_urls(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sources.Config, "get_autoresearch_dir", lambda: tmp_path)
    _, origin = repository()
    assert (
        sources.store_logo(
            b"<svg><script>alert(1)</script></svg>", ".svg", origin, "logo.svg"
        )
        is None
    )
    assert (
        sources.store_logo(
            b'<svg><use href="https://example.com/private"/></svg>',
            ".svg",
            origin,
            "logo.svg",
        )
        is None
    )
    with pytest.raises(ValueError):
        sources.github_url("http://127.0.0.1/private")
    with pytest.raises(ValueError):
        sources.github_url("https://github.com/a/../b")
