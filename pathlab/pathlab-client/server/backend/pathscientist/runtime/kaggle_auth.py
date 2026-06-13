"""Kaggle credential helpers shared by providers and sandbox wiring."""
from __future__ import annotations

import json
import os
from pathlib import Path


def resolve_kaggle_config_dir() -> Path | None:
    """Return the host Kaggle config dir, if one exists."""
    raw = os.getenv("KAGGLE_CONFIG_DIR", "").strip()
    if raw:
        path = Path(raw).expanduser()
        return path if path.is_dir() else None
    default = Path(os.path.expanduser("~")) / ".kaggle"
    return default if default.is_dir() else None


def _read_text(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _read_kaggle_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _candidate_kaggle_json_paths(kaggle_json_path: Path | None = None) -> list[Path]:
    if kaggle_json_path is not None:
        return [Path(kaggle_json_path).expanduser()]
    config_dir = resolve_kaggle_config_dir()
    if config_dir is None:
        return []
    return [config_dir / "kaggle.json"]


def resolve_kaggle_api_token(kaggle_json_path: Path | None = None) -> str:
    """Resolve a bearer token for the new Kaggle KGAT auth flow.

    The modern Kaggle CLI accepts ``KAGGLE_API_TOKEN`` as Bearer auth. A token
    shaped like ``KGAT_...`` stored under the legacy ``kaggle.json`` ``key``
    field does not work with competition endpoints as username/key basic auth,
    so expose it through ``KAGGLE_API_TOKEN`` instead.
    """
    env_token = os.getenv("KAGGLE_API_TOKEN", "").strip()
    if env_token:
        return env_token

    config_dir = resolve_kaggle_config_dir()
    if config_dir is not None:
        for name in ("access_token", "access_token.txt"):
            token = _read_text(config_dir / name)
            if token:
                return token

    for path in _candidate_kaggle_json_paths(kaggle_json_path):
        key = str(_read_kaggle_json(path).get("key", "")).strip()
        if key.startswith("KGAT_"):
            return key
    return ""


def kaggle_credentials_present(kaggle_json_path: Path | None = None) -> bool:
    if resolve_kaggle_api_token(kaggle_json_path):
        return True
    env_user = os.getenv("KAGGLE_USERNAME", "").strip()
    env_key = os.getenv("KAGGLE_KEY", "").strip()
    if env_user and env_key:
        return True
    return any(path.exists() for path in _candidate_kaggle_json_paths(kaggle_json_path))


def build_kaggle_cli_env(kaggle_json_path: Path | None = None) -> dict[str, str]:
    """Return subprocess env with KGAT tokens mapped to KAGGLE_API_TOKEN."""
    env = os.environ.copy()
    token = resolve_kaggle_api_token(kaggle_json_path)
    if token and not env.get("KAGGLE_API_TOKEN"):
        env["KAGGLE_API_TOKEN"] = token
    return env
