"""
PathLab Gateway Service

Main entry point that registers all route modules.
Most route logic has been moved to separate files in routes/ directory.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pathlab.services.backend.database import init_db, close_db
from .dependencies import logger
from .routes import (
    stats_router,
    wsi_router,
    wsi_upload_router,
    training_router,
    ai_tasks_router,
    results_router,
    models_router,
    chat_router,
    parse_router,
    storage_router,
)

# Create FastAPI app
app = FastAPI(title="PathLab Gateway")

# Enable CORS for dev and on-prem SPA
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    logger.info("Initializing database...")
    await init_db()
    logger.info("✓ Database initialized")


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connections on shutdown"""
    logger.info("Closing database connections...")
    await close_db()
    logger.info("✓ Database connections closed")


@app.get("/health")
def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "gateway"}


# Register route modules
app.include_router(stats_router)
app.include_router(wsi_router)
app.include_router(wsi_upload_router)
app.include_router(training_router)
app.include_router(ai_tasks_router)
app.include_router(results_router)
app.include_router(models_router)
app.include_router(chat_router)
app.include_router(parse_router)
app.include_router(storage_router)

logger.info("Gateway service initialized with all route modules")

