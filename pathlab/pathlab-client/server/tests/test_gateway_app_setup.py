from fastapi import FastAPI

from backend.common.config import Config
from gateway.app_setup import include_api_routers, mount_static_routes


def test_include_api_routers_registers_expected_paths():
    app = FastAPI()

    include_api_routers(app)

    paths = {route.path for route in app.routes}
    assert "/settings" in paths
    assert "/auth/secure-login" in paths
    assert "/health" not in paths


def test_mount_static_routes_mounts_avatars_only_when_renderer_dist_missing(
    tmp_path, monkeypatch
):
    uploads_dir = tmp_path / "uploads"
    monkeypatch.setattr(Config, "get_uploads_dir", staticmethod(lambda: uploads_dir))

    app = FastAPI()
    mount_static_routes(app, renderer_dist=tmp_path / "missing-renderer")

    mounted = {route.path for route in app.routes}
    assert "/avatars" in mounted
    assert "/assets" not in mounted
    assert "/images" not in mounted


def test_mount_static_routes_mounts_renderer_assets_when_present(tmp_path, monkeypatch):
    uploads_dir = tmp_path / "uploads"
    renderer_dist = tmp_path / "renderer-dist"
    (renderer_dist / "assets").mkdir(parents=True)
    (renderer_dist / "images").mkdir(parents=True)
    monkeypatch.setattr(Config, "get_uploads_dir", staticmethod(lambda: uploads_dir))

    app = FastAPI()
    mount_static_routes(app, renderer_dist=renderer_dist)

    mounted = {route.path for route in app.routes}
    assert "/avatars" in mounted
    assert "/assets" in mounted
    assert "/images" in mounted
