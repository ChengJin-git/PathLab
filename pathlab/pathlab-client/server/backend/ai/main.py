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

UPLOADS_DIR = os.path.join(ROOT, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

app = FastAPI(title="PathLab AI Service")

# Enable CORS
try:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
except Exception:
    pass

# Routers
from backend.ai.routes.training import router as training_router
from backend.ai.routes.inference import router as inference_router
app.include_router(training_router, prefix="/api/ai")
app.include_router(inference_router, prefix="/api/ai")


@app.get("/health")
def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "ai"}

