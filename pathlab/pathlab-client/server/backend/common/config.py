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

    # Task timeout settings (in seconds)
    # Default: 3 days (259200 seconds), configurable via settings
    DEFAULT_TASK_TIMEOUT = 86400 * 3  # 3 days
    _task_timeout: int = None  # Runtime cached value

    # ========== Centralized Constants ==========
    # Authentication
    JWT_LIFETIME_SECONDS = 3600 * 24 * 7  # 7 days
    MAX_TIMESTAMP_DIFF_SECONDS = 300  # 5 minutes - tolerance for timestamp validation

    # Database operations
    DB_OPERATION_TIMEOUT = 90  # seconds

    # GPU/VRAM settings
    DEFAULT_MIN_VRAM_MB = 2000  # 2GB - minimum VRAM for task execution
    MIN_INFERENCE_OVERHEAD_MB = 500  # Buffer for CUDA context, activations, etc.

    # Feature cache
    FEATURE_LOCK_TIMEOUT = 1800  # 30 minutes - large WSI feature extraction can take a while

    # Storage cache TTL
    STORAGE_STATS_CACHE_TTL = 3600  # 1 hour for fresh data
    STORAGE_STATS_STALE_TTL = 86400  # 24 hours for stale data
    ORPHAN_CACHE_TTL = 3600  # 1 hour for fresh data
    ORPHAN_STALE_TTL = 86400  # 24 hours for stale data

    # Task cleanup
    CLEANUP_OLD_TASKS_DAYS = 7  # Days to keep old finished tasks

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
    def _read_config(cls) -> dict:
        """Read all config from storage.json."""
        config_file = cls._get_storage_config_file()
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    @classmethod
    def _write_config(cls, data: dict) -> None:
        """Write config to storage.json (merges with existing)."""
        config_file = cls._get_storage_config_file()
        config_file.parent.mkdir(parents=True, exist_ok=True)
        existing = cls._read_config()
        existing.update(data)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

    @classmethod
    def set_uploads_dir(cls, uploads_dir: str) -> Path:
        """Persist uploads directory setting and update env."""
        resolved = Path(uploads_dir).expanduser().resolve()
        cls._write_config({"uploads_dir": str(resolved)})
        os.environ["PATHLAB_UPLOADS_DIR"] = str(resolved)
        return resolved

    @classmethod
    def get_task_timeout(cls) -> int:
        """Get task timeout in seconds. Default: 3 days (259200s)."""
        if cls._task_timeout is not None:
            return cls._task_timeout

        data = cls._read_config()
        timeout = data.get("task_timeout", cls.DEFAULT_TASK_TIMEOUT)
        cls._task_timeout = int(timeout)
        return cls._task_timeout

    @classmethod
    def set_task_timeout(cls, timeout: int) -> int:
        """Set task timeout in seconds. Min: 60, Max: 259200 (3 days)."""
        timeout = max(60, min(259200, int(timeout)))
        cls._write_config({"task_timeout": timeout})
        cls._task_timeout = timeout
        return timeout

    # ========== Global Settings (AI Configuration) ==========
    # These settings are shared across all users

    @classmethod
    def get_global_settings(cls) -> dict:
        """Get all global settings."""
        data = cls._read_config()
        return {
            "openrouter_api_key": data.get("openrouter_api_key", ""),
            "openrouter_base_url": data.get("openrouter_base_url", "https://openrouter.ai/api/v1"),
            "openrouter_model": data.get("openrouter_model", "qwen/qwen3-vl-235b-a22b-instruct"),
            "huggingface_token": data.get("huggingface_token", ""),
            "dashscope_api_key": data.get("dashscope_api_key", ""),
            # Local vLLM settings (OpenAI-compatible server for LLM)
            "local_vllm_enabled": data.get("local_vllm_enabled", False),
            "local_vllm_base_url": data.get("local_vllm_base_url", "http://127.0.0.1:8000/v1"),
            "local_vllm_model": data.get("local_vllm_model", ""),
            "local_vllm_api_key": data.get("local_vllm_api_key", ""),
            # Local ASR settings (WebSocket server for ASR, e.g., ws://host:port/api-ws/v1/realtime)
            "local_asr_enabled": data.get("local_asr_enabled", False),
            "local_asr_base_url": data.get("local_asr_base_url", "ws://127.0.0.1:8001/api-ws/v1/realtime"),
            "local_asr_model": data.get("local_asr_model", ""),
            "local_asr_api_key": data.get("local_asr_api_key", ""),
        }

    @classmethod
    def update_global_settings(cls, settings: dict) -> dict:
        """Update global settings. Only updates provided keys."""
        allowed_keys = {
            "openrouter_api_key",
            "openrouter_base_url",
            "openrouter_model",
            "huggingface_token",
            "dashscope_api_key",
            # Local vLLM settings
            "local_vllm_enabled",
            "local_vllm_base_url",
            "local_vllm_model",
            "local_vllm_api_key",
            # Local ASR settings
            "local_asr_enabled",
            "local_asr_base_url",
            "local_asr_model",
            "local_asr_api_key",
        }
        # Filter to only allowed keys
        filtered = {k: v for k, v in settings.items() if k in allowed_keys}
        if filtered:
            cls._write_config(filtered)
        return cls.get_global_settings()

    @classmethod
    def ensure_directories(cls):
        """Ensure required directories exist"""
        uploads_dir = cls.get_uploads_dir()
        uploads_dir.mkdir(exist_ok=True, parents=True)
        (uploads_dir / "avatars").mkdir(exist_ok=True)
        (uploads_dir / "coordinates").mkdir(exist_ok=True)
        (uploads_dir / "masks").mkdir(exist_ok=True)
        (uploads_dir / "features").mkdir(exist_ok=True)  # Global feature cache
        (uploads_dir / "ai_results").mkdir(exist_ok=True)
        (uploads_dir / "training").mkdir(exist_ok=True)
        (uploads_dir / "models").mkdir(exist_ok=True)
        (uploads_dir / "logs").mkdir(exist_ok=True)
        (uploads_dir / "wsi_files").mkdir(exist_ok=True)
        (uploads_dir / "metadata").mkdir(exist_ok=True)


# Create singleton instance
config = Config()

