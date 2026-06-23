from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

_CONFIG_FILE_OVERRIDE: Optional[str] = None


def _get_app_data_dir() -> Path:
    if sys.platform == "win32":
        base_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base_dir = Path.home() / "Library" / "Application Support"
    else:
        base_dir = Path(
            os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        )
    data_dir = base_dir / "PathLab"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _get_storage_config_file() -> Path:
    if _CONFIG_FILE_OVERRIDE is not None:
        return Path(_CONFIG_FILE_OVERRIDE)
    return _get_app_data_dir() / "storage.json"


def read_config(config_file_override: Optional[str] = None) -> Dict[str, Any]:
    config_file = (
        Path(config_file_override)
        if config_file_override
        else _get_storage_config_file()
    )
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def write_config(
    data: Dict[str, Any], config_file_override: Optional[str] = None
) -> None:
    config_file = (
        Path(config_file_override)
        if config_file_override
        else _get_storage_config_file()
    )
    config_file.parent.mkdir(parents=True, exist_ok=True)
    existing = read_config(config_file_override)
    existing.update(data)
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
