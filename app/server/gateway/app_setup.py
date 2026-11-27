# pyright: reportImplicitRelativeImport=false

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .routes.workspaces import router as workspace_router
from .routes.reports import router as reports_router
from .routes.result_workbench import router as result_workbench_router
from .routes.dataset_catalog import router as dataset_catalog_router
from .routes.viewer import router as viewer_router
from .workspace_access import enforce_workspace_request

from .routes.annotation import router as annotation_router
from .routes.ai_tasks import router as ai_tasks_router
from .routes.asr import router as asr_router
from .routes.auth import router as auth_router
from .routes.chat import router as chat_router
from .routes.gpu import router as gpu_router
from .routes.heatmap import router as heatmap_router
from .routes.models import router as models_router
from .routes.autoresearch import router as autoresearch_router
from .routes.queue import router as queue_router
from .routes.results import router as results_router
from .routes.settings import router as settings_router
from .routes.stats import router as stats_router
from .routes.storage import router as storage_router
from .routes.training_options import router as training_options_router
from .routes.training import router as training_router
from .routes.wsi import router as wsi_router
from .routes.wsi_upload import router as wsi_upload_router


API_ROUTERS: tuple[APIRouter, ...] = (
    workspace_router,
    auth_router,
    stats_router,
    dataset_catalog_router,
    viewer_router,
    wsi_router,
    wsi_upload_router,
    training_router,
    ai_tasks_router,
    result_workbench_router,
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
    reports_router,
)


def get_renderer_dist_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "src" / "renderer" / "dist"


def _get_uploads_dir() -> Path:
    from backend.common.config import Config

    return Config.get_uploads_dir()


def include_api_routers(app: FastAPI) -> None:
    for router in API_ROUTERS:
        app.include_router(router, dependencies=[Depends(enforce_workspace_request)])
        app.include_router(router, prefix="/api", dependencies=[Depends(enforce_workspace_request)])


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
        for path in ("/datasets", "/upload", "/reports", "/autoresearch", "/autoresearch/new", "/autoresearch/sessions/{session_id}"):
            app.add_api_route(path, serve_spa_entrypoint, methods=["GET"], include_in_schema=False)

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
