"""
PathLab Gateway Service

Main entry point that registers all route modules.
Most route logic has been moved to separate files in routes/ directory.
"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .dependencies import logger
from .app_setup import include_api_routers, mount_static_routes
from .startup import (
    initialize_gateway_runtime,
    shutdown_gateway_runtime,
)
from backend.common.config import Config

# Ensure required upload directories exist at import time so that the
# StaticFiles mount below never crashes on a missing "avatars" directory.
# (Config.ensure_directories() is also called in the lifespan for safety,
#  but StaticFiles validates the path during app-object construction,
#  i.e. before the lifespan fires.)
Config.ensure_directories()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.

    Startup: Initialize database and task queue, resume interrupted tasks.
    Shutdown: Shutdown task queue and close database connections.
    """
    # === Startup ===
    training_rag_prewarm_task: asyncio.Task[None] | None = None
    chat_context_prewarm_task: asyncio.Task[None] | None = None

    (
        training_rag_prewarm_task,
        chat_context_prewarm_task,
    ) = await initialize_gateway_runtime(app)

    try:
        yield  # Application runs here
    finally:
        await shutdown_gateway_runtime(
            app,
            training_rag_prewarm_task,
            chat_context_prewarm_task,
        )


# Create FastAPI app with lifespan
app = FastAPI(title="PathLab Gateway", lifespan=lifespan)

# Enable CORS for dev and on-prem SPA
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

mount_static_routes(app)


@app.get("/health")
def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "gateway"}


include_api_routers(app)

logger.info("Gateway service initialized with all route modules")
