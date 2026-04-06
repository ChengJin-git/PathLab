"""Session identity — ensures workspace isolation across concurrent runs."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from ..persistence.layout import get_persistence_root


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

        base = Path(base_dir or os.environ.get(
            "PATHSCIENTIST_BASE_DIR",
            "/project/vcompath/storage/ywangrm/tmp/pathscientist",
        ))

        if workspace_dir:
            ws = Path(workspace_dir)
        else:
            ws = base / f"session_{session_id}"

        ws.mkdir(parents=True, exist_ok=True)

        if output_dir:
            out = Path(output_dir)
        else:
            out = ws / "output"
        out.mkdir(parents=True, exist_ok=True)

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
