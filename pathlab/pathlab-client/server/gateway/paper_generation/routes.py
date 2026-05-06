"""Gateway compatibility mount for the paper-agent API.

The implementation lives under `server/paper_agent/src/pathlab_paper_agent/api`.
This module stays in Gateway only so existing `app_setup.py` imports and the
front-end `/papers` API do not change.
"""

from __future__ import annotations

from ._paper_agent_path import ensure_paper_agent_src_on_path

ensure_paper_agent_src_on_path()

from pathlab_paper_agent.api.routes import router  # noqa: E402,F401

__all__ = ["router"]
