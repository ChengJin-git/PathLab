"""Compatibility bootstrap for the relocated paper-agent implementation."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_paper_agent_src_on_path() -> Path:
    """Make `server/paper_agent/src` importable from Gateway modules."""
    server_root = Path(__file__).resolve().parents[2]
    paper_agent_src = server_root / "paper_agent" / "src"
    src_str = str(paper_agent_src)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)
    return paper_agent_src
