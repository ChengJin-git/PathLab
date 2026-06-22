# pyright: reportImplicitRelativeImport=false

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.common.config import Config
from gateway.app_setup import include_api_routers, mount_static_routes


def _route_paths(app: FastAPI) -> set[str]:
    paths: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.add(path)
    return paths


def test_include_api_routers_registers_expected_paths():
    app = FastAPI()

    include_api_routers(app)

    paths = _route_paths(app)
    assert "/settings" in paths
    assert "/auth/secure-login" in paths
    assert "/pathscientist/sessions" in paths
    assert "/health" not in paths


def test_include_api_routers_also_registers_api_prefixed_paths():
    app = FastAPI()

    include_api_routers(app)

    paths = _route_paths(app)
    assert "/api/settings" in paths
    assert "/api/auth/secure-login" in paths
    assert "/api/pathscientist/sessions" in paths


def test_mount_static_routes_mounts_avatars_only_when_renderer_dist_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    uploads_dir = tmp_path / "uploads"
    monkeypatch.setattr(Config, "get_uploads_dir", staticmethod(lambda: uploads_dir))

    app = FastAPI()
    mount_static_routes(app, renderer_dist=tmp_path / "missing-renderer")

    mounted = _route_paths(app)
    assert "/avatars" in mounted
    assert "/assets" not in mounted
    assert "/images" not in mounted


def test_mount_static_routes_mounts_renderer_assets_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    uploads_dir = tmp_path / "uploads"
    renderer_dist = tmp_path / "renderer-dist"
    (renderer_dist / "assets").mkdir(parents=True)
    (renderer_dist / "images").mkdir(parents=True)
    monkeypatch.setattr(Config, "get_uploads_dir", staticmethod(lambda: uploads_dir))

    app = FastAPI()
    mount_static_routes(app, renderer_dist=renderer_dist)

    mounted = _route_paths(app)
    assert "/avatars" in mounted
    assert "/assets" in mounted
    assert "/images" in mounted


def test_mount_static_routes_serves_spa_entrypoint_when_renderer_dist_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    uploads_dir = tmp_path / "uploads"
    renderer_dist = tmp_path / "renderer-dist"
    renderer_dist.mkdir(parents=True)
    _ = (renderer_dist / "index.html").write_text(
        "<div>PathLab SPA</div>", encoding="utf-8"
    )
    monkeypatch.setattr(Config, "get_uploads_dir", staticmethod(lambda: uploads_dir))

    app = FastAPI()
    mount_static_routes(app, renderer_dist=renderer_dist)

    client = TestClient(app)
    response = client.get("/wsi-list")
    index_response = client.get("/index.html")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "PathLab SPA" in response.text
    assert index_response.status_code == 200
    assert index_response.headers["content-type"].startswith("text/html")
    assert "PathLab SPA" in index_response.text


def test_mount_static_routes_serves_top_level_renderer_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    uploads_dir = tmp_path / "uploads"
    renderer_dist = tmp_path / "renderer-dist"
    renderer_dist.mkdir(parents=True)
    _ = (renderer_dist / "manifest.webmanifest").write_text(
        '{"name":"PathLab"}', encoding="utf-8"
    )
    monkeypatch.setattr(Config, "get_uploads_dir", staticmethod(lambda: uploads_dir))

    app = FastAPI()
    mount_static_routes(app, renderer_dist=renderer_dist)

    response = TestClient(app).get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.json() == {"name": "PathLab"}
