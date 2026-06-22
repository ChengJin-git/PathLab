"""Session identity — ensures workspace isolation across concurrent runs."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from uuid import UUID, uuid4

from ..persistence.layout import get_persistence_root


def _default_base_dir() -> Path:
    try:
        config_module = import_module("backend.common.config")
        return config_module.Config.get_autoresearch_dir()
    except Exception:
        env_uploads = os.environ.get("PATHLAB_UPLOADS_DIR", "")
        if env_uploads:
            return Path(env_uploads).expanduser() / "autoresearch"
        return Path(__file__).resolve().parents[4] / "uploads" / "autoresearch"


DEFAULT_BASE_DIR = str(_default_base_dir())


def _session_workspace_root(base: Path) -> Path:
    if base.name == "autoresearch_sessions":
        return base
    return base / "autoresearch_sessions"


def _resolve_base_dir(
    *,
    base_dir: str = "",
    workspace_dir: str = "",
    conversation_persistence_dir: str = "",
) -> Path:
    """Resolve the session base dir without forcing tests into cluster storage."""
    if base_dir:
        return Path(base_dir).expanduser()
    env_base = os.environ.get("PATHSCIENTIST_BASE_DIR", "")
    if env_base:
        return Path(env_base).expanduser()
    if conversation_persistence_dir:
        return Path(conversation_persistence_dir).expanduser()
    if workspace_dir:
        return Path(workspace_dir).expanduser().parent / ".pathscientist"
    return _default_base_dir().expanduser()


def _mkdir_or_explain(path: Path, *, purpose: str) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        message = (
            f"Cannot create PathScientist {purpose} directory at {path}: {exc}. "
            + "Set PATHSCIENTIST_BASE_DIR=/tmp/autoresearch or pass --workspace "
            + "and --output to writable locations."
        )
        raise RuntimeError(
            message
        ) from exc


@dataclass
class PathScientistSession:
    """Unique session with isolated workspace, output, and conversation persistence."""

    session_id: str = field(default_factory=lambda: uuid4().hex[:12])
    conversation_id: UUID = field(default_factory=uuid4)
    research_question: str = ""
    workspace_dir: Path = field(default_factory=lambda: Path())
    output_dir: Path = field(default_factory=lambda: Path())
    persistence_root: Path = field(default_factory=lambda: Path())

    @classmethod
    def create(
        cls,
        research_question: str = "",
        base_dir: str = "",
        workspace_dir: str = "",
        output_dir: str = "",
        conversation_persistence_dir: str = "",
        resume_conversation_id: str = "",
    ) -> PathScientistSession:
        """Create a new session with unique directories.

        If workspace_dir/output_dir are provided, use them directly.
        Otherwise, generate unique paths under base_dir.
        """
        session_id = uuid4().hex[:12]

        # Conversation identity
        if resume_conversation_id:
            conversation_id = UUID(resume_conversation_id)
        else:
            conversation_id = uuid4()

        base = _resolve_base_dir(
            base_dir=base_dir,
            workspace_dir=workspace_dir,
            conversation_persistence_dir=conversation_persistence_dir,
        )

        if workspace_dir:
            ws = Path(workspace_dir)
        else:
            ws = _session_workspace_root(base) / f"session_{session_id}"

        _mkdir_or_explain(ws, purpose="workspace")

        if output_dir:
            out = Path(output_dir)
        else:
            out = ws / "output"
        _mkdir_or_explain(out, purpose="output")

        # Conversation persistence root
        persistence_base = conversation_persistence_dir or str(base)
        persistence_root = get_persistence_root(persistence_base)

        return cls(
            session_id=session_id,
            conversation_id=conversation_id,
            research_question=research_question,
            workspace_dir=ws,
            output_dir=out,
            persistence_root=persistence_root,
        )
