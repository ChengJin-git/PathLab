import os
import sys
import httpx
from pathlib import Path
from typing import AsyncGenerator
from dotenv import load_dotenv
from fastapi import Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.common import get_logger
from backend.common.config import Config
from backend.storage import StorageManager


class PaginationParams(BaseModel):
    page: int = Query(default=1, ge=1)
    page_size: int = Query(default=20, ge=1, le=1000)

    @property
    def skip(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


# Setup paths
ROOT = Path(__file__).resolve().parents[2]  # pathlab/
sys.path.insert(0, str(ROOT))

# Load .env file
env_path = ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Initialize logger
logger = get_logger("Gateway")

# Directories
UPLOADS_DIR = Config.get_uploads_dir()

# Initialize storage manager
storage_manager = StorageManager(str(UPLOADS_DIR))

# Initialize migration manager
from backend.storage.migration import migration_manager

# Service URLs (internal communication)
AI_SERVICE_URL = Config.AI_SERVICE_URL
PREPROCESSING_SERVICE_URL = Config.PREPROCESSING_SERVICE_URL


def get_ai_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.ai_client


def get_preprocessing_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.preprocessing_client


def make_sse_response(generator: AsyncGenerator) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
