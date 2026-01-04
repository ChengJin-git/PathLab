"""
Shared dependencies and utilities for Gateway service
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from backend.common import get_logger
from backend.storage import StorageManager

# Setup paths
ROOT = Path(__file__).resolve().parents[2]  # pathlab/
sys.path.insert(0, str(ROOT))

# Load .env file
env_path = ROOT / '.env'
if env_path.exists():
    load_dotenv(env_path)

# Initialize logger
logger = get_logger("Gateway")

# Directories
UPLOADS_DIR = ROOT / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True, parents=True)

# Initialize storage manager
storage_manager = StorageManager(str(UPLOADS_DIR))

# Service URLs (internal communication)
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:6102")
PREPROCESSING_SERVICE_URL = os.getenv("PREPROCESSING_SERVICE_URL", "http://127.0.0.1:6101")

