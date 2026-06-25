# pyright: reportImplicitRelativeImport=false

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routes import (
    annotation_router,
    ai_tasks_router,
    asr_router,
    auth_router,
    chat_router,
    gpu_router,
    heatmap_router,
    models_router,
    autoresearch_router,
    queue_router,
    results_router,
    settings_router,
    stats_router,
    storage_router,
    training_options_router,
    training_router,
    wsi_router,
    wsi_upload_router,
)


API_ROUTERS: tuple[APIRouter, ...] = (
    auth_router,
    stats_router,
    wsi_router,
    wsi_upload_router,
    training_router,
    ai_tasks_router,
    results_router,
    models_router,
    chat_router,
    storage_router,
    queue_router,
    asr_router,
    heatmap_router,
    settings_router,
    gpu_router,
    annotation_router,
    training_options_router,
    autoresearch_router,
)


def get_renderer_dist_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "src" / "renderer" / "dist"


def _get_uploads_dir() -> Path:
    from backend.common.config import Config

    return Config.get_uploads_dir()


def include_api_routers(app: FastAPI) -> None:
    for router in API_ROUTERS:
        app.include_router(router)
        app.include_router(router, prefix="/api")


def mount_static_routes(app: FastAPI, renderer_dist: Path | None = None) -> None:
    avatars_dir = _get_uploads_dir() / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/avatars",
        StaticFiles(directory=str(avatars_dir)),
        name="avatars",
    )

    resolved_renderer_dist = renderer_dist or get_renderer_dist_path()
    if not resolved_renderer_dist.is_dir():
        return

    images_dir = resolved_renderer_dist / "images"
    if images_dir.is_dir():
        app.mount(
            "/images", StaticFiles(directory=str(images_dir)), name="frontend-images"
        )

    assets_dir = resolved_renderer_dist / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets"
        )

    index_html = resolved_renderer_dist / "index.html"
    if index_html.is_file():
        def serve_spa_entrypoint() -> FileResponse:
            return FileResponse(index_html, media_type="text/html")

        app.add_api_route(
            "/", serve_spa_entrypoint, methods=["GET"], include_in_schema=False
        )
        app.add_api_route(
            "/index.html", serve_spa_entrypoint, methods=["GET"], include_in_schema=False
        )
        app.add_api_route(
            "/wsi-list", serve_spa_entrypoint, methods=["GET"], include_in_schema=False
        )

    for renderer_file in resolved_renderer_dist.iterdir():
        if not renderer_file.is_file() or renderer_file.name == "index.html":
            continue

        def serve_renderer_file(file_path: Path = renderer_file) -> FileResponse:
            return FileResponse(file_path)

        app.add_api_route(
            f"/{renderer_file.name}",
            serve_renderer_file,
            methods=["GET"],
            include_in_schema=False,
        )
