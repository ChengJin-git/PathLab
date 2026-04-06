"""PathScientist configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PathScientistConfig:
    """Top-level configuration for PathScientist agent."""

    # Workspace
    workspace_dir: str = ""
    output_dir: str = ""
    data_mounts: dict[str, str] = field(default_factory=dict)

    # GPU
    gpu_ids: list[str] = field(default_factory=lambda: ["0"])

    # Experiment
    primary_metric: str = "auc"
    max_iterations: int = 5
    quick_check_timeout: int = 120
    execution_timeout: int = 600

    # LLM
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_temperature: float = 0.2

    # Sandbox
    sandbox_mode: str = "auto"          # "local" | "apptainer" | "auto"
    sandbox_image: str = ""             # .sif path, empty = auto-detect
    sandbox_memory_limit: str = "64G"
    sandbox_cpus: str = "16"

    # Skill
    skill_name: str = ""

    # Conversation persistence
    conversation_persistence_dir: str = ""   # override for persistence root
    resume_conversation_id: str = ""         # UUID hex to resume

    # Logging
    log_dir: str = ""

    @classmethod
    def from_env(cls) -> PathScientistConfig:
        """Build config from environment variables."""
        return cls(
            workspace_dir=os.environ.get("PATHSCIENTIST_WORKSPACE", ""),
            output_dir=os.environ.get("PATHSCIENTIST_OUTPUT", ""),
            gpu_ids=os.environ.get("CUDA_VISIBLE_DEVICES", "0").split(","),
            primary_metric=os.environ.get("PATHSCIENTIST_METRIC", "auc"),
            max_iterations=int(os.environ.get("PATHSCIENTIST_MAX_ITER", "5")),
            execution_timeout=int(os.environ.get("PATHSCIENTIST_TIMEOUT", "600")),
            llm_model=os.environ.get("PATHSCIENTIST_LLM_MODEL", ""),
            llm_api_key=os.environ.get("PATHSCIENTIST_LLM_API_KEY", ""),
            llm_base_url=os.environ.get("PATHSCIENTIST_LLM_BASE_URL", ""),
            sandbox_mode=os.environ.get("PATHSCIENTIST_SANDBOX", "auto"),
            sandbox_image=os.environ.get("PATHSCIENTIST_SANDBOX_IMAGE", ""),
            skill_name=os.environ.get("PATHSCIENTIST_SKILL", ""),
            conversation_persistence_dir=os.environ.get("PATHSCIENTIST_PERSISTENCE_DIR", ""),
            resume_conversation_id=os.environ.get("PATHSCIENTIST_RESUME_CONVERSATION", ""),
            log_dir=os.environ.get("PATHSCIENTIST_LOG_DIR", ""),
        )

    def create_session(self, research_question: str = ""):
        """Create a new isolated session with unique workspace/output dirs."""
        from .runtime.session import PathScientistSession
        return PathScientistSession.create(
            research_question=research_question,
            workspace_dir=self.workspace_dir,
            output_dir=self.output_dir,
            conversation_persistence_dir=self.conversation_persistence_dir,
            resume_conversation_id=self.resume_conversation_id,
        )

    def resolve_workspace(self, research_question: str = "") -> Path:
        """Resolve workspace directory. Use create_session() for isolation."""
        if self.workspace_dir:
            ws = Path(self.workspace_dir)
        else:
            # Use session-based unique path
            session = self.create_session(research_question)
            return session.workspace_dir
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    def resolve_output(self, workspace: Path) -> Path:
        """Resolve output directory."""
        if self.output_dir:
            out = Path(self.output_dir)
        else:
            out = workspace / "output"
        out.mkdir(parents=True, exist_ok=True)
        return out
