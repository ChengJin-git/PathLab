"""Storage re-exports used by the standalone runtime."""

from __future__ import annotations

from .bootstrap import ensure_server_on_path

ensure_server_on_path()

from gateway.paper_generation.storage import (  # noqa: E402,F401
    PaperRunPaths,
    is_path_allowed_for_download,
    papers_root,
    safe_resolve,
    validate_paper_id,
)

__all__ = [
    "PaperRunPaths",
    "is_path_allowed_for_download",
    "papers_root",
    "safe_resolve",
    "validate_paper_id",
]
