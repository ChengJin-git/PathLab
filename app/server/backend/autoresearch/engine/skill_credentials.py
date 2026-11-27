"""Operator-provided optional service credentials, outside research artifacts."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from backend.common.config import Config

# The model provider key is deliberately separate: an image service may use a
# different endpoint/account from the configured research text model.
ENVIRONMENT_KEYS = (
    "PUBMED_EMAIL",
    "NCBI_API_KEY",
    "UNPAYWALL_EMAIL",
    "PADDLE_OCR_TOKEN",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "IMAGE2PPT_IMAGE_MODEL",
    "IMAGE2PPT_IMAGE_BACKEND",
    "IMAGE2PPT_IMAGE_USER_AGENT",
)


def credentials_directory() -> Path:
    return Config.get_autoresearch_dir() / "credentials"


def skill_environment() -> dict[str, str]:
    path = credentials_directory() / "skills.env"
    local = dotenv_values(path, interpolate=False) if path.is_file() else {}
    values = {
        name: str(local.get(name) or os.environ.get(name) or "")
        for name in ENVIRONMENT_KEYS
    }
    values = {name: value for name, value in values.items() if value}
    if (credentials_directory() / "lit-dl").is_dir():
        values["LIT_DL_CONFIG_DIR"] = "/opt/pathlab/lit-dl"
    return values
