from typing import Any

"""
Centralized configuration for PathLab backend services
"""

import json
import os
import sys
from pathlib import Path


class Config:
    """Configuration for PathLab services"""

    # ========== Default Ports (for debug mode) ==========
    DEFAULT_GATEWAY_PORT = 6100
    DEFAULT_PREPROCESSING_PORT = 6101
    DEFAULT_AI_PORT = 6102

    # ========== Default URLs ==========
    DATABASE_URL_DEFAULT = "postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab"
    REDIS_URL_DEFAULT = "redis://localhost:6379/0"

    # Root directory
    ROOT_DIR = Path(__file__).resolve().parents[3]  # pathlab-client/

    # Config file (persisted settings)
    STORAGE_CONFIG_FILE = None

    # Service URLs (internal communication)
    # These will be dynamically set when services start with auto-discovered ports
    AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", f"http://127.0.0.1:{DEFAULT_AI_PORT}")
    PREPROCESSING_SERVICE_URL = os.getenv(
        "PREPROCESSING_SERVICE_URL", f"http://127.0.0.1:{DEFAULT_PREPROCESSING_PORT}"
    )
    GATEWAY_SERVICE_URL = os.getenv(
        "GATEWAY_SERVICE_URL", f"http://127.0.0.1:{DEFAULT_GATEWAY_PORT}"
    )

    # Cache settings
    SLIDE_CACHE_SIZE = int(os.getenv("SLIDE_CACHE_SIZE", "8"))
    DZG_CACHE_SIZE = int(os.getenv("DZG_CACHE_SIZE", "16"))

    # File upload limits (in bytes)
    MAX_UPLOAD_SIZE = int(
        os.getenv("MAX_UPLOAD_SIZE", str(10 * 1024 * 1024 * 1024))
    )  # 10GB default

    # Task timeout settings (in seconds)
    # Default: 3 days (259200 seconds), configurable via settings
    DEFAULT_TASK_TIMEOUT = 86400 * 3  # 3 days
    _task_timeout: int = None  # Runtime cached value

    # ========== Centralized Constants ==========
    # Authentication
    JWT_LIFETIME_SECONDS = 3600 * 24 * 7  # 7 days
    MAX_TIMESTAMP_DIFF_SECONDS = 300  # 5 minutes - tolerance for timestamp validation

    # Database operations
    # Timeout for database operations (used by scoped_db, ScopedLogger, etc.)
    # With PostgreSQL, this guards against long-running queries or connection issues.
    DB_OPERATION_TIMEOUT = 90  # seconds

    # GPU/VRAM settings
    DEFAULT_MIN_VRAM_MB = 2000  # 2GB - minimum VRAM for task execution
    MIN_INFERENCE_OVERHEAD_MB = 500  # Buffer for CUDA context, activations, etc.
    MARKER_GPU_QUEUE_WAIT_TIMEOUT_SECONDS = float(
        os.getenv("MARKER_GPU_QUEUE_WAIT_TIMEOUT_SECONDS", "30")
    )

    # Feature cache
    FEATURE_LOCK_TIMEOUT = (
        1800  # 30 minutes - large WSI feature extraction can take a while
    )
    COORDS_LOCK_TIMEOUT = int(
        os.getenv("COORDS_LOCK_TIMEOUT", str(FEATURE_LOCK_TIMEOUT))
    )
    PREPROCESSING_MAX_CONCURRENT_COMPUTE_PATCHES = int(
        os.getenv("PREPROCESSING_MAX_CONCURRENT_COMPUTE_PATCHES", "2")
    )

    # Storage cache TTL
    STORAGE_STATS_CACHE_TTL = 3600  # 1 hour for fresh data
    STORAGE_STATS_STALE_TTL = 86400  # 24 hours for stale data
    ORPHAN_CACHE_TTL = 3600  # 1 hour for fresh data
    ORPHAN_STALE_TTL = 86400  # 24 hours for stale data

    # Task cleanup
    CLEANUP_OLD_TASKS_DAYS = 7  # Days to keep old finished tasks

    # Aslide color correction supported formats (case-insensitive check)
    COLOR_CORRECTION_FORMATS: frozenset[Any] = frozenset[Any](
        {
            ".sdpc",
            ".dyqx",
            ".dyj",
            ".kfb",
            ".mds",
            ".mdsx",
            ".tmap",
        }
    )

    @classmethod
    def _get_app_data_dir(cls) -> Path:
        """Get application data directory based on OS."""
        if sys.platform == "win32":
            base_dir = Path(
                os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
            )
        elif sys.platform == "darwin":
            base_dir = Path.home() / "Library" / "Application Support"
        else:
            base_dir = Path(
                os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
            )

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
    def _read_config(cls) -> dict[str, Any]:
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
    def _write_config(cls, data: dict[str, Any]) -> None:
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

    @classmethod
    def get_max_concurrent(cls, default: int = 1) -> int:
        """
        Get max concurrent GPU tasks from config.

        Args:
            default: Default value if not configured (typically 1)

        Returns:
            Max concurrent tasks (1-10)
        """
        data = cls._read_config()
        value = data.get("max_concurrent", default)
        # Clamp to valid range
        return max(1, min(10, int(value)))

    @classmethod
    def set_max_concurrent(cls, max_concurrent: int) -> int:
        """
        Set max concurrent GPU tasks. Persisted to config file.

        Args:
            max_concurrent: Number of concurrent tasks (1-10)

        Returns:
            The saved value (clamped to valid range)
        """
        max_concurrent = max(1, min(10, int(max_concurrent)))
        cls._write_config({"max_concurrent": max_concurrent})
        return max_concurrent

    _global_settings_cache: dict[str, Any] = None
    _global_settings_dirty: bool = True

    @classmethod
    def _build_global_settings(cls, data: dict[str, Any]) -> dict[str, Any]:
        def str_to_bool(value: str) -> bool:
            if isinstance(value, bool):
                return value
            return value.lower() in ("true", "1", "yes")

        turnstile_enabled_env = os.getenv("TURNSTILE_ENABLED")
        turnstile_enabled = (
            str_to_bool(turnstile_enabled_env)
            if turnstile_enabled_env is not None
            else data.get("turnstile_enabled", False)
        )
        turnstile_site_key = os.getenv("TURNSTILE_SITE_KEY") or data.get(
            "turnstile_site_key", ""
        )
        turnstile_secret_key = os.getenv("TURNSTILE_SECRET_KEY") or data.get(
            "turnstile_secret_key", ""
        )

        return {
            "openrouter_api_key": data.get("openrouter_api_key", ""),
            "openrouter_base_url": data.get(
                "openrouter_base_url", "https://openrouter.ai/api/v1"
            ),
            "openrouter_model": data.get("openrouter_model", "qwen/qwen3.5-plus-02-15"),
            "huggingface_token": data.get("huggingface_token", ""),
            "dashscope_api_key": data.get("dashscope_api_key", ""),
            "search_provider": data.get("search_provider", "tavily"),
            "exa_api_key": data.get("exa_api_key", ""),
            "tavily_api_key": data.get("tavily_api_key", ""),
            "jina_api_key": data.get("jina_api_key", ""),
            "local_vllm_enabled": data.get("local_vllm_enabled", False),
            "local_vllm_base_url": data.get(
                "local_vllm_base_url", "http://127.0.0.1:8000/v1"
            ),
            "local_vllm_model": data.get("local_vllm_model", ""),
            "local_vllm_api_key": data.get("local_vllm_api_key", ""),
            "local_asr_enabled": data.get("local_asr_enabled", False),
            "local_asr_base_url": data.get(
                "local_asr_base_url", "ws://127.0.0.1:8001/api-ws/v1/realtime"
            ),
            "local_asr_model": data.get("local_asr_model", ""),
            "local_asr_api_key": data.get("local_asr_api_key", ""),
            "kaggle_username": data.get("kaggle_username", ""),
            "kaggle_key": data.get("kaggle_key", ""),
            "turnstile_enabled": turnstile_enabled,
            "turnstile_site_key": turnstile_site_key,
            "turnstile_secret_key": turnstile_secret_key,
            "resend_enabled": data.get("resend_enabled", False),
            "resend_api_key": data.get("resend_api_key", ""),
            "admin_notify_email": data.get("admin_notify_email", ""),
            "email_templates": data.get("email_templates", {}),
        }

    @classmethod
    def resolve_search_provider(cls, settings: dict) -> str:
        """Resolve the active search provider from settings dict. Returns 'exa' or 'tavily'."""
        provider = settings.get("search_provider", "exa")
        return provider if provider in ("exa", "tavily") else "exa"

    @classmethod
    def get_global_settings(cls) -> dict[str, Any]:
        if not cls._global_settings_dirty and cls._global_settings_cache is not None:
            return dict(cls._global_settings_cache)
        data = cls._read_config()
        result = cls._build_global_settings(data)
        cls._global_settings_cache = result
        cls._global_settings_dirty = False
        return dict(result)

    @classmethod
    def update_global_settings(cls, settings: dict[str, Any]) -> dict[str, Any]:
        allowed_keys = {
            "openrouter_api_key",
            "openrouter_base_url",
            "openrouter_model",
            "huggingface_token",
            "dashscope_api_key",
            "search_provider",
            # Exa Search API key
            "exa_api_key",
            # Tavily API key
            "tavily_api_key",
            # Jina Reader API key
            "jina_api_key",
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
            # Kaggle credentials
            "kaggle_username",
            "kaggle_key",
            # Cloudflare Turnstile settings
            "turnstile_enabled",
            "turnstile_site_key",
            "turnstile_secret_key",
            "resend_enabled",
            "resend_api_key",
            "admin_notify_email",
            "email_templates",
        }
        filtered = {k: v for k, v in settings.items() if k in allowed_keys}
        if filtered:
            cls._write_config(filtered)
        cls._global_settings_dirty = True
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
        (uploads_dir / "progress").mkdir(
            exist_ok=True
        )  # Shared progress files (AI ↔ Gateway)

    # ========== Maintenance Mode ==========
    @classmethod
    def get_maintenance_mode(cls) -> bool:
        """Get current maintenance mode status."""
        config_data = cls._read_config()
        return config_data.get("maintenance_mode", False)

    @classmethod
    def set_maintenance_mode(cls, enabled: bool) -> None:
        """Set maintenance mode status."""
        cls._write_config({"maintenance_mode": enabled})

    @classmethod
    def set_maintenance_mode_state(
        cls, enabled: bool, restore_user_ids: list[str] | None = None
    ) -> None:
        """Persist maintenance mode status together with its restoration snapshot."""
        data = {"maintenance_mode": enabled}
        if restore_user_ids is not None:
            data["maintenance_mode_restore_user_ids"] = [
                str(user_id) for user_id in restore_user_ids
            ]
        cls._write_config(data)

    @classmethod
    def get_maintenance_mode_restore_user_ids(cls) -> list[str]:
        """Get non-admin user IDs that should be restored when maintenance ends."""
        config_data = cls._read_config()
        user_ids = config_data.get("maintenance_mode_restore_user_ids", [])
        if isinstance(user_ids, list):
            return [str(user_id) for user_id in user_ids if user_id]
        return []

    @classmethod
    def set_maintenance_mode_restore_user_ids(cls, user_ids: list[str]) -> None:
        """Persist non-admin user IDs that were active before maintenance mode."""
        cls._write_config(
            {
                "maintenance_mode_restore_user_ids": [
                    str(user_id) for user_id in user_ids
                ]
            }
        )

    @classmethod
    def clear_maintenance_mode_restore_user_ids(cls) -> None:
        """Clear the stored maintenance-mode restoration snapshot."""
        cls._write_config({"maintenance_mode_restore_user_ids": []})

    # ========== Maintenance Notice (Announcement) ==========
    @classmethod
    def get_maintenance_notice(cls) -> dict[str, Any] | None:
        """Get current maintenance notice. Returns {message, updated_at} or None."""
        config_data = cls._read_config()
        return config_data.get("maintenance_notice", None)

    @classmethod
    def set_maintenance_notice(cls, message: str | None) -> dict[str, Any] | None:
        """Set or clear maintenance notice. Returns the saved notice or None."""
        from datetime import datetime, timezone

        if message and message.strip():
            notice = {
                "message": message.strip(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            cls._write_config({"maintenance_notice": notice})
            return notice
        else:
            cls._write_config({"maintenance_notice": None})
            return None


# Create singleton instance
config = Config()
