"""
SmartResearch AI Service

Clean slate for AI service refactoring.
"""
import os
import sys
from fastapi import FastAPI

# Setup paths
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))  # smartresearch/
sys.path.insert(0, ROOT)

UPLOADS_DIR = os.path.join(ROOT, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

app = FastAPI(title="SmartResearch AI Service")

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


@app.get("/health")
def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "ai"}

