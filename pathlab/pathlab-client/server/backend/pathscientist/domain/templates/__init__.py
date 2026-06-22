"""
Auto Research Agent — Training Script Templates

Registry of pre-built training templates that the Code Agent modifies.
Each template has MODIFIABLE zones (model, loss, hyperparams) and FIXED zones
(data loading, metrics computation, result saving).
"""
from __future__ import annotations

from pathlib import Path

_TEMPLATES_DIR = Path(__file__).parent

TEMPLATES = {
    "classification": "classification_template.py",
    "patch_classification": "patch_classification_template.py",
    "survival": "survival_template.py",
}


def get_template_path(task_type: str) -> Path:
    """Return absolute path to the template file for the given task type."""
    filename = TEMPLATES.get(task_type)
    if not filename:
        raise ValueError(
            f"Unknown task type: {task_type!r}. "
            f"Available: {list(TEMPLATES.keys())}"
        )
    path = _TEMPLATES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    return path


def get_template_content(task_type: str) -> str:
    """Return the template source code as a string."""
    return get_template_path(task_type).read_text(encoding="utf-8")


def get_common_dir() -> Path:
    """Return the path to the common/ utilities directory (for Docker COPY)."""
    return _TEMPLATES_DIR / "common"
