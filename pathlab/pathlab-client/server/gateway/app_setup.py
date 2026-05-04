from __future__ import annotations

from importlib import import_module
from pathlib import Path

from fastapi import FastAPI
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
from .paper_generation.routes import router as paper_generation_router


def get_renderer_dist_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "src" / "renderer" / "dist"


def _get_uploads_dir() -> Path:
    config_module = import_module("backend.common.config")
    return config_module.Config.get_uploads_dir()


def include_api_routers(app: FastAPI) -> None:
    app.include_router(auth_router)
    app.include_router(stats_router)
    app.include_router(wsi_router)
    app.include_router(wsi_upload_router)
    app.include_router(training_router)
    app.include_router(ai_tasks_router)
    app.include_router(results_router)
    app.include_router(models_router)
    app.include_router(chat_router)
    app.include_router(storage_router)
    app.include_router(queue_router)
    app.include_router(asr_router)
    app.include_router(heatmap_router)
    app.include_router(settings_router)
    app.include_router(gpu_router)
    app.include_router(annotation_router)
    app.include_router(training_options_router)
    app.include_router(paper_generation_router)


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
