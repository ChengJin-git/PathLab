"""Runtime bootstrap helpers for the standalone paper agent."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


def server_root() -> Path:
    """Return `pathlab/pathlab-client/server` for this checkout."""
    return Path(__file__).resolve().parents[3]


def ensure_server_on_path() -> Path:
    """Make PathLab's `backend.*` and `gateway.*` packages importable."""
    root = server_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


def configure_uploads_dir(uploads_dir: Optional[str | Path]) -> Optional[Path]:
    """Override `Config.get_uploads_dir()` for standalone dev commands.

    Gateway normally owns Config. The standalone CLI/service accepts an explicit
    uploads root so each stage can be tested without launching Electron.
    """
    ensure_server_on_path()
    if uploads_dir is None:
        return None

    resolved = Path(uploads_dir).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    os.environ["PATHLAB_UPLOADS_DIR"] = str(resolved)

    from backend.common.config import Config

    Config.get_uploads_dir = classmethod(lambda cls: resolved)  # type: ignore[method-assign]
    return resolved
