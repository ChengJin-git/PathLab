import io
import shutil
import stat
import zipfile
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.autoresearch.engine import jobs, skill_imports, skills, store
from backend.database.models import AutoResearchExperiment, ResearchJob
from gateway.routes import autoresearch as routes


def test_skill_snapshots_have_isolated_ids_and_survive_restart(tmp_path):
    source = skills.ResearchSkill(
        name="pathlab-research",
        content="---\nname: pathlab-research\ndescription: Compare baselines\n---\n# Steps\nUse patient splits.",
    )
    saved = skills.snapshot_skills([source])
    assert saved[0]["id"] == "user-skill-1"
    base = tmp_path / ".opencode/skills/pathlab-research/SKILL.md"
    base.parent.mkdir(parents=True)
    base.write_text("system workflow")
    skills.install_skills(tmp_path, saved)
    custom = tmp_path / ".opencode/skills/user-skill-1/SKILL.md"
    assert "Use patient splits." in custom.read_text()
    custom.unlink()
    skills.install_skills(tmp_path, saved)
    assert custom.read_text() == saved[0]["content"]
    assert base.read_text() == "system workflow"


@pytest.mark.parametrize(
    "content",
    [
        "",
        "<!DOCTYPE html><html>login</html>",
        "---\nname: x\n---",
        "---\n- not-a-mapping\n---\nbody",
    ],
)
def test_invalid_skill_is_rejected(content):
    with pytest.raises(ValueError):
        skills.ResearchSkill(name="Test", content=content)


async def test_import_github_file_link_keeps_code_and_sibling_references(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(skills.Config, "get_autoresearch_dir", lambda: tmp_path)
    requested = []
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(
            "repo-sha/skills/validation/SKILL.md",
            "---\nname: crc-validation\ndescription: Patient-level evaluation\n---\n# Evaluate\nUse [shared](../shared/rules.md).",
        )
        archive.writestr(
            "repo-sha/skills/validation/scripts/evaluate.py", 'print("real code")'
        )
        archive.writestr("repo-sha/skills/shared/rules.md", "# Patient separation")

    def handle(request):
        requested.append(str(request.url))
        if "api.github.com" in str(request.url):
            return httpx.Response(200, json={"sha": "abc123"}) if request.url.path.endswith('/commits/main') else httpx.Response(404)
        return httpx.Response(200, content=data.getvalue())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(skill_imports.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, "", ("93.184.216.34", 443))],
    )
    result = await skill_imports.import_skill(
        "https://github.com/team/repo/blob/main/skills/validation/SKILL.md", "owner"
    )
    assert requested[-2:] == ["https://api.github.com/repos/team/repo/commits/main", "https://codeload.github.com/team/repo/zip/abc123"]
    assert result["skills"][0]["name"] == "crc-validation"
    assert not result["warnings"]
    root = tmp_path / "session"
    root.mkdir()
    snapshots = skills.snapshot_skills(
        [skills.ResearchSkill(**result["skills"][0])], root, "owner"
    )
    shutil.rmtree(skills.package_directory("owner"))
    skills.install_skills(root, snapshots)
    package = root / ".opencode/packages" / snapshots[0]["package_id"]
    assert (package / "skills/shared/rules.md").read_text() == "# Patient separation"
    assert (
        package / "skills/validation/scripts/evaluate.py"
    ).read_text() == 'print("real code")'
    assert (
        str(package / "skills/validation/SKILL.md")
        in (root / ".opencode/skills/user-skill-1/SKILL.md").read_text()
    )


async def test_import_blocks_redirects_to_internal_hosts(monkeypatch):
    def handle(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(skill_imports.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, "", ("93.184.216.34", 443))],
    )
    with pytest.raises(ValueError, match="skillUnsupportedUrl"):
        await skill_imports.import_skill("https://example.org/SKILL.md", "owner")


@pytest.mark.parametrize(
    "content,content_type",
    [("x" * 128001, "text/plain"), ("<html>Page</html>", "text/html")],
)
async def test_import_rejects_oversized_and_html_documents(
    monkeypatch, content, content_type
):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=content, headers={"content-type": content_type}
            )
        )
    )
    monkeypatch.setattr(skill_imports.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, "", ("93.184.216.34", 443))],
    )
    with pytest.raises(ValueError):
        await skill_imports.import_skill("https://example.org/SKILL.md", "owner")


def test_guest_cannot_import_or_invoke_network(monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(routes, "import_skill", fetch)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.current_active_user] = lambda: SimpleNamespace(
        role="guest"
    )
    assert (
        TestClient(app)
        .post("/research/skills/import", json={"url": "https://example.org/SKILL.md"})
        .status_code
        == 403
    )
    fetch.assert_not_awaited()


def test_package_ownership_and_binary_resource_preservation(tmp_path, monkeypatch):
    monkeypatch.setattr(skills.Config, "get_autoresearch_dir", lambda: tmp_path)
    imported = skills.import_files(
        {
            "skill/SKILL.md": (b"# Instructions", False),
            "skill/assets/image.png": (b"\x89PNG\x00binary", False),
            "skill/scripts/run.sh": (b"#!/bin/sh\necho ok", True),
        },
        "alice",
    )
    selected = [skills.ResearchSkill(**imported["skills"][0])]
    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(skills.SkillImportError, match="skillImportExpired"):
        skills.snapshot_skills(selected, root, "bob")
    snapshots = skills.snapshot_skills(selected, root, "alice")
    package = root / ".opencode/packages" / snapshots[0]["package_id"]
    assert (package / "skill/assets/image.png").read_bytes() == b"\x89PNG\x00binary"
    assert (package / "skill/scripts/run.sh").stat().st_mode & 0o111
    assert snapshots[0]["entrypoint"] == "skill/SKILL.md"
    skills.install_skills(root, snapshots)
    assert (
        "resource base directory"
        in (root / ".opencode/skills/user-skill-1/SKILL.md").read_text()
    )


@pytest.mark.parametrize(
    "path", ["../escape.py", "/absolute.py", "a/../../escape", "C:\\escape.py"]
)
def test_archive_rejects_traversal(path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(path, "code")
    with pytest.raises(skills.SkillImportError, match="skillUnsafePath"):
        skills.unpack_zip(output.getvalue())


def test_archive_rejects_symlinks_and_expansion_limit(monkeypatch):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        item = zipfile.ZipInfo("link")
        item.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(item, "/etc/passwd")
    with pytest.raises(skills.SkillImportError, match="skillUnsafePath"):
        skills.unpack_zip(output.getvalue())
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", "x" * 1024)
    monkeypatch.setattr(skills, "MAX_PACKAGE_BYTES", 512)
    with pytest.raises(skills.SkillImportError, match="skillTooLarge"):
        skills.unpack_zip(output.getvalue())


async def test_github_branch_with_slash_is_not_mistaken_for_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(skills.Config, 'get_autoresearch_dir', lambda: tmp_path)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('repo-sha/SKILL.md', '# Correct branch')
        output.writestr('repo-sha/scripts/run.py', 'print(1)')
    def handle(request):
        if '/commits/' in request.url.path:
            if request.url.path.endswith('/commits/feature/new'):
                return httpx.Response(200, json={'sha': 'resolved-sha'})
            return httpx.Response(404)
        assert 'resolved-sha' in str(request.url)
        return httpx.Response(200, content=archive.getvalue())
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(skill_imports.httpx, 'AsyncClient', lambda **kwargs: client)
    monkeypatch.setattr('socket.getaddrinfo', lambda *args, **kwargs: [(None, None, None, '', ('93.184.216.34', 443))])
    result = await skill_imports.import_skill('https://github.com/team/repo/tree/feature/new', 'alice')
    assert result['skills'][0]['name'] == 'Correct branch'


def test_upload_api_reports_concrete_error_and_all_files(tmp_path, monkeypatch):
    monkeypatch.setattr(skills.Config, "get_autoresearch_dir", lambda: tmp_path)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.current_active_user] = lambda: SimpleNamespace(
        id="alice", role="admin"
    )
    client = TestClient(app)
    response = client.post(
        "/research/skills/upload",
        files=[
            ("files", ("test/SKILL.md", "# 测试\nUse scripts/run.py".encode())),
            ("files", ("test/scripts/run.py", b"print(1)")),
        ],
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["files"]) == 2
    assert response.json()["skills"][0]["name"] == "测试"
    missing = client.post(
        "/research/skills/upload", files={"files": ("readme.txt", b"not a skill")}
    )
    assert (
        missing.status_code == 422 and missing.json()["detail"] == "skillMissingEntry"
    )


def test_frontmatter_keeps_portable_rules_but_does_not_install_hooks(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(skills.Config, "get_autoresearch_dir", lambda: tmp_path)
    result = skills.import_files(
        {
            "SKILL.md": (
                b"---\nname: X\nallowed-tools: [Read, Bash]\n---\n# Work\nRead [missing](references/missing.md).",
                False,
            )
        },
        "alice",
    )
    assert set(result["warnings"]) == {
        "skillRuntimeRequirements",
        "skillMissingResources",
    }


async def test_computation_has_no_experiment_record_or_budget_charge(
    monkeypatch, tmp_path
):
    from backend.common.config import Config
    monkeypatch.setattr(Config, 'get_autoresearch_dir', lambda: tmp_path.parent / 'storage')
    (tmp_path / "analysis.py").write_text("print(1)")
    row = SimpleNamespace(
        status="running",
        workspace_path=str(tmp_path),
        current_iteration=8,
        max_iterations=8,
        recovery_metadata={},
    )
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=row), add=Mock(), commit=AsyncMock()
    )

    @asynccontextmanager
    async def database():
        yield db

    monkeypatch.setattr(jobs, "safe_session", database)
    monkeypatch.setattr(store, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(store, "update", AsyncMock())
    monkeypatch.setattr(jobs, "enqueue_task_descriptor", AsyncMock())
    result = await jobs.submit(
        "s",
        "computation",
        {"name": "Calculate metrics", "command": ["python", "analysis.py"]},
    )
    assert row.current_iteration == 8
    added = [call.args[0] for call in db.add.call_args_list]
    assert not any(isinstance(item, AutoResearchExperiment) for item in added)
    assert len(added) == 1 and isinstance(added[0], ResearchJob)
    assert added[0].kind == "computation" and added[0].payload["device"] == "cpu"
    assert (tmp_path / "runs" / result["job_id"] / "source/analysis.py").is_file()


async def test_download_keeps_skill_resources_without_opencode_config(tmp_path, monkeypatch):
    root = tmp_path / 'session'
    package = root / '.opencode/packages/hash/scripts'
    package.mkdir(parents=True)
    (package / 'run.py').write_text('print(1)')
    (root / 'opencode.json').write_text('private runtime config')
    (root / '.opencode/private.json').write_text('private runtime data')
    monkeypatch.setattr(routes, 'owned', AsyncMock(return_value=SimpleNamespace(workspace_path=str(root))))
    monkeypatch.setattr(routes.Config, 'get_autoresearch_dir', lambda: tmp_path)
    response = await routes.archive('session', '', SimpleNamespace())
    with zipfile.ZipFile(response.path) as archive:
        assert archive.namelist() == ['.opencode/packages/hash/scripts/run.py']
    await response.background()
