"""PathScientist configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_project_env_path() -> Path:
    """Return the project-local env file used for non-checked-in secrets."""
    return Path(__file__).resolve().parent / ".env.local"


def _parse_env_line(line: str) -> tuple[str, str] | None:
    """Parse one simple dotenv line without expanding variables."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export "):].lstrip()
    if "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key.startswith("PATHSCIENTIST_"):
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return key, value


def load_project_env(path: str | Path | None = None, *, override: bool = False) -> Path | None:
    """Load PATHSCIENTIST_* values from a local env file if it exists.

    Existing process environment values win by default. This keeps shell/CLI
    overrides higher precedence than secrets copied into ``.env.local``.
    """
    env_path_raw = path or os.environ.get("PATHSCIENTIST_ENV_FILE", "")
    env_path = Path(env_path_raw).expanduser() if env_path_raw else _default_project_env_path()
    if not env_path.exists():
        return None

    for line in env_path.read_text().splitlines():
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if override or key not in os.environ:
            os.environ[key] = value
    return env_path


def _first_non_empty(*values: str) -> str:
    """Return the first non-empty string from a precedence-ordered list."""
    for value in values:
        if value:
            return value
    return ""


def env_truthy(name: str) -> bool:
    """Return True for common truthy environment values."""
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def resolve_llm_model(explicit: str = "", default: str = "") -> str:
    """Resolve the model from explicit config, app env, then generic env."""
    return _first_non_empty(
        explicit,
        os.environ.get("PATHSCIENTIST_LLM_MODEL", ""),
        os.environ.get("LLM_MODEL", ""),
        default,
    )


def resolve_llm_api_key(explicit: str = "") -> str:
    """Resolve the API key from explicit config, app env, then generic env."""
    return _first_non_empty(
        explicit,
        os.environ.get("PATHSCIENTIST_LLM_API_KEY", ""),
        os.environ.get("LLM_API_KEY", ""),
    )


def resolve_llm_base_url(explicit: str = "") -> str:
    """Resolve the base URL from explicit config, app env, then generic env."""
    return _first_non_empty(
        explicit,
        os.environ.get("PATHSCIENTIST_LLM_BASE_URL", ""),
        os.environ.get("LLM_BASE_URL", ""),
    )


def resolve_required_llm_model(explicit: str = "", component: str = "this operation") -> str:
    """Resolve a required LLM model or raise a clear configuration error."""
    model = resolve_llm_model(explicit, default="")
    if model:
        return model
    raise RuntimeError(
        f"No LLM model configured for {component}. "
        "Set --model, PATHSCIENTIST_LLM_MODEL, or LLM_MODEL."
    )


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
    llm_profile: str = ""                   # "" | "codex-relay"
    llm_wire_api: str = ""                  # "" | "responses" | "completion"
    codex_config_path: str = ""             # override for ~/.codex/config.toml
    codex_auth_path: str = ""               # override for ~/.codex/auth.json

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
    manual_approval: bool = False
    stop_before_execution: bool = False

    # Literature RAG
    literature_rag_enabled: bool = False
    literature_corpus_dir: str = ""      # directory of local papers for RAG ingestion
    literature_rag_top_k: int = 3
    # Online literature search
    literature_online_enabled: bool = False
    literature_online_provider: str = "openalex"
    literature_online_max_results: int = 5
    literature_online_timeout: int = 15
    refresh_sota: bool = False

    literature_rag_embedding_model: str = "Qwen/Qwen3-Embedding-8B"
    literature_rag_embedding_base_url: str = "http://dgx-24.cm.cluster:9001/v1"
    literature_rag_embedding_api_key: str = "sk-pathlab"

    # Dataset acquisition
    auto_acquire_data: bool = False
    download_policy: str = "public_only"  # "public_only" | "manual_only" | "disabled"
    max_download_size_gb: float = 20.0
    allow_large_downloads: bool = False
    dataset_cache_dir: str = ""

    # Logging
    log_dir: str = ""

    @classmethod
    def from_env(cls) -> PathScientistConfig:
        """Build config from environment variables."""
        load_project_env()
        return cls(
            workspace_dir=os.environ.get("PATHSCIENTIST_WORKSPACE", ""),
            output_dir=os.environ.get("PATHSCIENTIST_OUTPUT", ""),
            gpu_ids=os.environ.get("CUDA_VISIBLE_DEVICES", "0").split(","),
            primary_metric=os.environ.get("PATHSCIENTIST_METRIC", "auc"),
            max_iterations=int(os.environ.get("PATHSCIENTIST_MAX_ITER", "5")),
            execution_timeout=int(os.environ.get("PATHSCIENTIST_TIMEOUT", "600")),
            llm_model=resolve_llm_model(default=""),
            llm_api_key=resolve_llm_api_key(),
            llm_base_url=resolve_llm_base_url(),
            llm_profile=os.environ.get("PATHSCIENTIST_LLM_PROFILE", ""),
            llm_wire_api=os.environ.get("PATHSCIENTIST_LLM_WIRE_API", ""),
            codex_config_path=os.environ.get("PATHSCIENTIST_CODEX_CONFIG", ""),
            codex_auth_path=os.environ.get("PATHSCIENTIST_CODEX_AUTH", ""),
            sandbox_mode=os.environ.get("PATHSCIENTIST_SANDBOX", "auto"),
            sandbox_image=os.environ.get("PATHSCIENTIST_SANDBOX_IMAGE", ""),
            skill_name=os.environ.get("PATHSCIENTIST_SKILL", ""),
            conversation_persistence_dir=os.environ.get("PATHSCIENTIST_PERSISTENCE_DIR", ""),
            resume_conversation_id=os.environ.get("PATHSCIENTIST_RESUME_CONVERSATION", ""),
            manual_approval=env_truthy("PATHSCIENTIST_MANUAL_APPROVAL"),
            stop_before_execution=env_truthy("PATHSCIENTIST_STOP_BEFORE_EXECUTION"),
            literature_online_enabled=env_truthy("PATHSCIENTIST_LITERATURE_ONLINE"),
            literature_online_provider=os.environ.get("PATHSCIENTIST_LITERATURE_ONLINE_PROVIDER", "openalex"),
            literature_online_max_results=int(os.environ.get("PATHSCIENTIST_LITERATURE_ONLINE_MAX_RESULTS", "5")),
            literature_online_timeout=int(os.environ.get("PATHSCIENTIST_LITERATURE_ONLINE_TIMEOUT", "15")),
            refresh_sota=env_truthy("PATHSCIENTIST_REFRESH_SOTA"),
            literature_rag_enabled=env_truthy("PATHSCIENTIST_RAG"),
            literature_corpus_dir=os.environ.get("PATHSCIENTIST_RAG_CORPUS_DIR", ""),
            literature_rag_top_k=int(os.environ.get("PATHSCIENTIST_RAG_TOP_K", "3")),
            literature_rag_embedding_model=os.environ.get(
                "PATHSCIENTIST_RAG_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"),
            literature_rag_embedding_base_url=os.environ.get(
                "PATHSCIENTIST_RAG_EMBEDDING_BASE_URL", "http://dgx-24.cm.cluster:9001/v1"),
            literature_rag_embedding_api_key=os.environ.get(
                "PATHSCIENTIST_RAG_EMBEDDING_API_KEY", "sk-pathlab"),
            auto_acquire_data=env_truthy("PATHSCIENTIST_AUTO_ACQUIRE_DATA"),
            download_policy=os.environ.get("PATHSCIENTIST_DOWNLOAD_POLICY", "public_only"),
            max_download_size_gb=float(os.environ.get("PATHSCIENTIST_MAX_DOWNLOAD_SIZE_GB", "20.0")),
            allow_large_downloads=env_truthy("PATHSCIENTIST_ALLOW_LARGE_DOWNLOADS"),
            dataset_cache_dir=os.environ.get("PATHSCIENTIST_DATASET_CACHE_DIR", ""),
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
