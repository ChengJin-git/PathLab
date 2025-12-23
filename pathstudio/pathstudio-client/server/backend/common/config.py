"""
Centralized configuration for PathStudio backend services
"""
import os
from pathlib import Path


class Config:
    """Configuration for PathStudio services"""

    # Root directory
    ROOT_DIR = Path(__file__).resolve().parents[3]  # pathstudio-client/
    UPLOADS_DIR = ROOT_DIR / "uploads"

    # Service URLs (internal communication)
    # These will be dynamically set when services start with auto-discovered ports
    AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:6102")
    PREPROCESSING_SERVICE_URL = os.getenv("PREPROCESSING_SERVICE_URL", "http://127.0.0.1:6101")
    GATEWAY_SERVICE_URL = os.getenv("GATEWAY_SERVICE_URL", "http://127.0.0.1:6100")

    # Cache settings
    SLIDE_CACHE_SIZE = int(os.getenv("SLIDE_CACHE_SIZE", "8"))
    DZG_CACHE_SIZE = int(os.getenv("DZG_CACHE_SIZE", "16"))

    # File upload limits (in bytes)
    MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(10 * 1024 * 1024 * 1024)))  # 10GB default

    @classmethod
    def ensure_directories(cls):
        """Ensure required directories exist"""
        cls.UPLOADS_DIR.mkdir(exist_ok=True, parents=True)
        (cls.UPLOADS_DIR / "coordinates").mkdir(exist_ok=True)
        (cls.UPLOADS_DIR / "thumbnails").mkdir(exist_ok=True)
        (cls.UPLOADS_DIR / "masks").mkdir(exist_ok=True)
        (cls.UPLOADS_DIR / "ai_results").mkdir(exist_ok=True)
        (cls.UPLOADS_DIR / "training").mkdir(exist_ok=True)
        (cls.UPLOADS_DIR / "models").mkdir(exist_ok=True)
        (cls.UPLOADS_DIR / "logs").mkdir(exist_ok=True)


# Create singleton instance
config = Config()

