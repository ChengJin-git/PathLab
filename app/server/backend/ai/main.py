"""
PathLab AI Service

ResNet50 feature extraction + ABMIL training endpoints.
"""
import os
import sys
from fastapi import FastAPI

# Setup paths
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))  # pathlab/
sys.path.insert(0, ROOT)

from backend.common.config import Config

UPLOADS_DIR = str(Config.get_uploads_dir())
Config.ensure_directories()

app = FastAPI(title="PathLab AI Service")

# Enable CORS - MUST be before routers
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from backend.ai.routes.training import router as training_router
from backend.ai.routes.inference import router as inference_router
app.include_router(training_router, prefix="/api/ai")
app.include_router(inference_router, prefix="/api/ai")


@app.get("/health")
def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "ai", "pid": os.getpid()}
