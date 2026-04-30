from typing import Any

import os
import sys
from importlib import import_module
from pathlib import Path

_settings_store = import_module("backend.common.settings_store")
read_config = _settings_store.read_config
write_config = _settings_store.write_config
_get_storage_config_file = _settings_store._get_storage_config_file
_get_app_data_dir = _settings_store._get_app_data_dir


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

    STORAGE_CONFIG_FILE: Any = None

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
    _task_timeout: int | None = None  # Runtime cached value

    # Training submit-time preflight settings
    DEFAULT_TRAINING_PREFLIGHT_LOCAL_ROOT_TIMEOUT = 10
    DEFAULT_TRAINING_PREFLIGHT_LOCAL_SAMPLE_TIMEOUT = 10
    DEFAULT_TRAINING_PREFLIGHT_LOCAL_SAMPLE_SIZE = 8
    DEFAULT_TRAINING_PREFLIGHT_EXTERNAL_ROOT_TIMEOUT = 10
    DEFAULT_TRAINING_PREFLIGHT_EXTERNAL_SAMPLE_TIMEOUT = 10
    DEFAULT_TRAINING_PREFLIGHT_EXTERNAL_SAMPLE_SIZE = 5

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
    def _get_storage_config_file(cls) -> Path:
        if cls.STORAGE_CONFIG_FILE is not None:
            return Path(cls.STORAGE_CONFIG_FILE)
        return _get_storage_config_file()

    @classmethod
    def get_uploads_dir(cls) -> Path:
        env_dir = os.environ.get("PATHLAB_UPLOADS_DIR")
        if env_dir:
            return Path(env_dir).expanduser()

        data = read_config(cls.STORAGE_CONFIG_FILE)
        if data.get("uploads_dir"):
            return Path(data["uploads_dir"]).expanduser()

        # Fallback: use the XDG / AppData directory so the app works from
        # read-only mounts (AppImage squashfs, system-wide installs, etc.).
        # ROOT_DIR points inside the read-only bundle in packaged mode.
        return _get_app_data_dir() / "uploads"

    @classmethod
    def get_uploads_dir_source(cls) -> str:
        if os.environ.get("PATHLAB_UPLOADS_DIR"):
            return "env"
        config_file = (
            Path(cls.STORAGE_CONFIG_FILE)
            if cls.STORAGE_CONFIG_FILE
            else _get_storage_config_file()
        )
        if config_file.exists():
            return "config"
        return "default"

    @classmethod
    def set_uploads_dir(cls, uploads_dir: str) -> Path:
        resolved = Path(uploads_dir).expanduser().resolve()
        write_config({"uploads_dir": str(resolved)}, cls.STORAGE_CONFIG_FILE)
        os.environ["PATHLAB_UPLOADS_DIR"] = str(resolved)
        dependencies_module = sys.modules.get("gateway.dependencies")
        if dependencies_module is not None:
            setattr(dependencies_module, "UPLOADS_DIR", resolved)
            manager = getattr(dependencies_module, "storage_manager", None)
            if manager is not None:
                manager.set_uploads_dir(str(resolved))
        return resolved

    @classmethod
    def get_task_timeout(cls) -> int:
        if cls._task_timeout is not None:
            return cls._task_timeout

        data = read_config(cls.STORAGE_CONFIG_FILE)
        timeout = data.get("task_timeout", cls.DEFAULT_TASK_TIMEOUT)
        cls._task_timeout = int(timeout)
        return cls._task_timeout

    @classmethod
    def set_task_timeout(cls, timeout: int) -> int:
        timeout = max(60, min(259200, int(timeout)))
        write_config({"task_timeout": timeout}, cls.STORAGE_CONFIG_FILE)
        cls._task_timeout = timeout
        return timeout

    @classmethod
    def reset_runtime_cache_for_tests(cls) -> None:
        cls._global_settings_cache = None
        cls._global_settings_dirty = True
        cls._task_timeout = None

    @classmethod
    def get_max_concurrent(cls, default: int = 1) -> int:
        data = read_config(cls.STORAGE_CONFIG_FILE)
        value = data.get("max_concurrent", default)
        return max(1, min(10, int(value)))

    @classmethod
    def set_max_concurrent(cls, max_concurrent: int) -> int:
        max_concurrent = max(1, min(10, int(max_concurrent)))
        write_config({"max_concurrent": max_concurrent}, cls.STORAGE_CONFIG_FILE)
        return max_concurrent

    _global_settings_cache: dict[str, Any] | None = None
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
            "exa_api_key": data.get("exa_api_key", ""),
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
            "turnstile_enabled": turnstile_enabled,
            "turnstile_site_key": turnstile_site_key,
            "turnstile_secret_key": turnstile_secret_key,
            "resend_enabled": data.get("resend_enabled", False),
            "resend_api_key": data.get("resend_api_key", ""),
            "admin_notify_email": data.get("admin_notify_email", ""),
            "email_templates": data.get("email_templates", {}),
        }

    @classmethod
    def get_global_settings(cls) -> dict[str, Any]:
        if not cls._global_settings_dirty and cls._global_settings_cache is not None:
            return dict(cls._global_settings_cache)
        data = read_config(cls.STORAGE_CONFIG_FILE)
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
            "exa_api_key",
            "local_vllm_enabled",
            "local_vllm_base_url",
            "local_vllm_model",
            "local_vllm_api_key",
            "local_asr_enabled",
            "local_asr_base_url",
            "local_asr_model",
            "local_asr_api_key",
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
            write_config(filtered, cls.STORAGE_CONFIG_FILE)
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
        (uploads_dir / "ai_results_bundles").mkdir(exist_ok=True)
        (uploads_dir / "training").mkdir(exist_ok=True)
        (uploads_dir / "models").mkdir(exist_ok=True)
        (uploads_dir / "extractor_checkpoints").mkdir(exist_ok=True)
        (uploads_dir / "logs").mkdir(exist_ok=True)
        (uploads_dir / "wsi_files").mkdir(exist_ok=True)
        (uploads_dir / "metadata").mkdir(exist_ok=True)
        (uploads_dir / "progress").mkdir(
            exist_ok=True
        )  # Shared progress files (AI ↔ Gateway)

    # ========== Maintenance Mode ==========
    @classmethod
    def get_maintenance_mode(cls) -> bool:
        return read_config(cls.STORAGE_CONFIG_FILE).get("maintenance_mode", False)

    @classmethod
    def set_maintenance_mode(cls, enabled: bool) -> None:
        write_config({"maintenance_mode": enabled}, cls.STORAGE_CONFIG_FILE)

    @classmethod
    def set_maintenance_mode_state(
        cls, enabled: bool, restore_user_ids: list[str] | None = None
    ) -> None:
        data: dict[str, Any] = {"maintenance_mode": enabled}
        if restore_user_ids is not None:
            data["maintenance_mode_restore_user_ids"] = [
                str(user_id) for user_id in restore_user_ids
            ]
        write_config(data, cls.STORAGE_CONFIG_FILE)

    @classmethod
    def get_maintenance_mode_restore_user_ids(cls) -> list[str]:
        user_ids = read_config(cls.STORAGE_CONFIG_FILE).get(
            "maintenance_mode_restore_user_ids", []
        )
        if isinstance(user_ids, list):
            return [str(user_id) for user_id in user_ids if user_id]
        return []

    @classmethod
    def set_maintenance_mode_restore_user_ids(cls, user_ids: list[str]) -> None:
        write_config(
            {"maintenance_mode_restore_user_ids": [str(uid) for uid in user_ids]},
            cls.STORAGE_CONFIG_FILE,
        )

    @classmethod
    def clear_maintenance_mode_restore_user_ids(cls) -> None:
        write_config({"maintenance_mode_restore_user_ids": []}, cls.STORAGE_CONFIG_FILE)

    # ========== Maintenance Notice (Announcement) ==========
    @classmethod
    def get_maintenance_notice(cls) -> dict[str, Any] | None:
        return read_config(cls.STORAGE_CONFIG_FILE).get("maintenance_notice", None)

    @classmethod
    def set_maintenance_notice(cls, message: str | None) -> dict[str, Any] | None:
        from datetime import datetime, timezone

        if message and message.strip():
            notice = {
                "message": message.strip(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            write_config({"maintenance_notice": notice}, cls.STORAGE_CONFIG_FILE)
            return notice
        else:
            write_config({"maintenance_notice": None}, cls.STORAGE_CONFIG_FILE)
            return None


# Create singleton instance
config = Config()
