"""
Centralized configuration for PathLab backend services
"""
import json
import os
import sys
from pathlib import Path


class Config:
    """Configuration for PathLab services"""

    # Root directory
    ROOT_DIR = Path(__file__).resolve().parents[3]  # pathlab-client/

    # Config file (persisted settings)
    STORAGE_CONFIG_FILE = None

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
    def _get_app_data_dir(cls) -> Path:
        """Get application data directory based on OS."""
        if sys.platform == "win32":
            base_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        elif sys.platform == "darwin":
            base_dir = Path.home() / "Library" / "Application Support"
        else:
            base_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

        data_dir = base_dir / "PathLab"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    @classmethod
    def _get_storage_config_file(cls) -> Path:
        """Resolve storage config file path."""
        if cls.STORAGE_CONFIG_FILE is None:
            cls.STORAGE_CONFIG_FILE = cls._get_app_data_dir() / "storage.json"
        return Path(cls.STORAGE_CONFIG_FILE)

    @classmethod
    def get_uploads_dir(cls) -> Path:
        """Resolve uploads directory from env/config/default."""
        env_dir = os.environ.get("PATHLAB_UPLOADS_DIR")
        if env_dir:
            return Path(env_dir).expanduser()

        config_file = cls._get_storage_config_file()
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("uploads_dir"):
                    return Path(data["uploads_dir"]).expanduser()
            except Exception:
                # Ignore config read errors, fall back to default
                pass

        return cls.ROOT_DIR / "uploads"

    @classmethod
    def get_uploads_dir_source(cls) -> str:
        """Return the source of uploads dir: env, config, or default."""
        if os.environ.get("PATHLAB_UPLOADS_DIR"):
            return "env"
        if cls._get_storage_config_file().exists():
            return "config"
        return "default"

    @classmethod
    def set_uploads_dir(cls, uploads_dir: str) -> Path:
        """Persist uploads directory setting and update env."""
        resolved = Path(uploads_dir).expanduser().resolve()
        config_file = cls._get_storage_config_file()
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump({"uploads_dir": str(resolved)}, f, ensure_ascii=False, indent=2)
        os.environ["PATHLAB_UPLOADS_DIR"] = str(resolved)
        return resolved

    @classmethod
    def ensure_directories(cls):
        """Ensure required directories exist"""
        uploads_dir = cls.get_uploads_dir()
        uploads_dir.mkdir(exist_ok=True, parents=True)
        (uploads_dir / "coordinates").mkdir(exist_ok=True)
        (uploads_dir / "masks").mkdir(exist_ok=True)
        (uploads_dir / "features").mkdir(exist_ok=True)  # Global feature cache
        (uploads_dir / "ai_results").mkdir(exist_ok=True)
        (uploads_dir / "training").mkdir(exist_ok=True)
        (uploads_dir / "models").mkdir(exist_ok=True)
        (uploads_dir / "logs").mkdir(exist_ok=True)
        (uploads_dir / "wsi_files").mkdir(exist_ok=True)


# Create singleton instance
config = Config()

