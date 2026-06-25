"""AutoResearch configuration."""
from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_LITERATURE_ONLINE_PROVIDERS = "openalex,europepmc,semantic_scholar,pubmed"


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
    if not key.startswith("AUTORESEARCH_"):
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return key, value


def load_project_env(path: str | Path | None = None, *, override: bool = False) -> Path | None:
    """Load AUTORESEARCH_* values from a local env file if it exists.

    Existing process environment values win by default. This keeps shell/CLI
    overrides higher precedence than secrets copied into ``.env.local``.
    """
    env_path_raw = path or os.environ.get("AUTORESEARCH_ENV_FILE", "")
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


def parse_json_object(value: str) -> dict[str, str]:
    """Parse an env JSON object into a string-keyed dict, failing soft."""
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items() if v is not None}


def parse_provider_list(value: str, *, fallback: str = "openalex") -> list[str]:
    """Parse comma/space separated provider names with stable de-dup."""
    raw = value or fallback
    providers: list[str] = []
    for item in raw.replace(";", ",").replace(" ", ",").split(","):
        provider = item.strip().lower().replace("-", "_")
        if provider and provider not in providers:
            providers.append(provider)
    return providers or [fallback]


def resolve_llm_model(explicit: str = "", default: str = "") -> str:
    """Resolve the model from explicit config, app env, then generic env."""
    return _first_non_empty(
        explicit,
        os.environ.get("AUTORESEARCH_LLM_MODEL", ""),
        os.environ.get("LLM_MODEL", ""),
        default,
    )


def resolve_llm_api_key(explicit: str = "") -> str:
    """Resolve the API key from explicit config, app env, then generic env."""
    return _first_non_empty(
        explicit,
        os.environ.get("AUTORESEARCH_LLM_API_KEY", ""),
        os.environ.get("LLM_API_KEY", ""),
    )


def resolve_llm_base_url(explicit: str = "") -> str:
    """Resolve the base URL from explicit config, app env, then generic env."""
    return _first_non_empty(
        explicit,
        os.environ.get("AUTORESEARCH_LLM_BASE_URL", ""),
        os.environ.get("LLM_BASE_URL", ""),
    )


def resolve_huggingface_token(explicit: str = "") -> str:
    """Resolve the Hugging Face token from AutoResearch or standard HF env."""
    return _first_non_empty(
        explicit,
        os.environ.get("AUTORESEARCH_HUGGINGFACE_TOKEN", ""),
        os.environ.get("HF_TOKEN", ""),
        os.environ.get("HUGGING_FACE_HUB_TOKEN", ""),
    )


def resolve_required_llm_model(explicit: str = "", component: str = "this operation") -> str:
    """Resolve a required LLM model or raise a clear configuration error."""
    model = resolve_llm_model(explicit, default="")
    if model:
        return model
    raise RuntimeError(
        f"No LLM model configured for {component}. "
        "Set --model, AUTORESEARCH_LLM_MODEL, or LLM_MODEL."
    )


@dataclass
class AutoResearchConfig:
    """Top-level configuration for AutoResearch agent."""

    # Workspace
    workspace_dir: str = ""
    output_dir: str = ""
    data_mounts: dict[str, str] = field(default_factory=dict)

    # GPU
    gpu_ids: list[str] = field(default_factory=lambda: ["0"])

    # Experiment
    primary_metric: str = "auc"
    max_iterations: int = 5
    quick_check_timeout: int = 3600
    execution_timeout: int = 3600
    feature_extraction_timeout: int = 86400
    feature_extraction_quick_timeout: int = 3600

    # 2026-05-10 P0-2 fix: orchestrator-chosen stable path for
    # feature_extraction outputs. Set by the runner from
    # ``execution_plan.steps[feature_extraction].inputs.data_output_dir``
    # before the agent fires. RunExperimentTool reads this when the
    # script looks like feature_extraction so features land at a
    # workspace-stable path (``.dataset/generated_features``) instead
    # of the per-run ``output/runs/<run_id>/`` directory that gets
    # purged when the session ends. Empty for non-feature_extraction
    # plans (training stays per-run).
    planned_data_output_dir: str = ""
    planned_feature_wsi_dir: str = ""
    planned_feature_extractor: str = ""
    planned_mil_model: str = ""
    planned_features_dir: str = ""
    planned_splits_file: str = ""
    external_test_enabled: bool = False
    external_test_contract: dict[str, Any] = field(default_factory=dict)
    run_history: list[dict[str, Any]] = field(default_factory=list)

    # LLM
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_temperature: float = 0.2
    llm_profile: str = ""                   # "" | "codex-relay"
    llm_wire_api: str = ""                  # "" | "responses" | "completion"
    codex_config_path: str = ""             # override for ~/.codex/config.toml
    codex_auth_path: str = ""               # override for ~/.codex/auth.json
    huggingface_token: str = ""

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
    literature_online_providers: list[str] = field(
        default_factory=lambda: parse_provider_list(DEFAULT_LITERATURE_ONLINE_PROVIDERS)
    )
    literature_online_max_results: int = 5
    literature_online_timeout: int = 15
    refresh_sota: bool = False

    literature_rag_embedding_model: str = "Qwen/Qwen3-Embedding-8B"
    literature_rag_embedding_base_url: str = "http://dgx-24.cm.cluster:9001/v1"
    literature_rag_embedding_api_key: str = "sk-pathlab"

    # Dataset acquisition
    auto_acquire_data: bool = False
    download_policy: str = "public_only"  # "public_only" | "manual_only" | "public_or_manual" | "all" | "disabled"
    max_download_size_gb: float = 20.0
    allow_large_downloads: bool = False
    dataset_cache_dir: str = ""
    pathlab_user_id: str = ""

    # Logging
    log_dir: str = ""

    def __post_init__(self) -> None:
        default_providers = parse_provider_list(DEFAULT_LITERATURE_ONLINE_PROVIDERS)
        if self.literature_online_provider and self.literature_online_providers == ["openalex"]:
            self.literature_online_providers = parse_provider_list(self.literature_online_provider)
        elif (
            self.literature_online_provider
            and self.literature_online_provider != "openalex"
            and self.literature_online_providers == default_providers
        ):
            self.literature_online_providers = parse_provider_list(self.literature_online_provider)

    @classmethod
    def from_env(cls) -> AutoResearchConfig:
        """Build config from environment variables."""
        load_project_env()
        return cls(
            workspace_dir=os.environ.get("AUTORESEARCH_WORKSPACE", ""),
            output_dir=os.environ.get("AUTORESEARCH_OUTPUT", ""),
            gpu_ids=os.environ.get("CUDA_VISIBLE_DEVICES", "0").split(","),
            primary_metric=os.environ.get("AUTORESEARCH_METRIC", "auc"),
            max_iterations=int(os.environ.get("AUTORESEARCH_MAX_ITER", "5")),
            quick_check_timeout=int(
                os.environ.get("AUTORESEARCH_QUICK_CHECK_TIMEOUT", "3600")
            ),
            execution_timeout=int(os.environ.get("AUTORESEARCH_TIMEOUT", "3600")),
            feature_extraction_timeout=int(
                os.environ.get("AUTORESEARCH_FEATURE_EXTRACTION_TIMEOUT", "86400")
            ),
            feature_extraction_quick_timeout=int(
                os.environ.get("AUTORESEARCH_FEATURE_EXTRACTION_QUICK_TIMEOUT", "3600")
            ),
            external_test_enabled=env_truthy("AUTORESEARCH_EXTERNAL_TEST"),
            external_test_contract=parse_json_object(
                os.environ.get("AUTORESEARCH_EXTERNAL_TEST_CONTRACT", "")
            ),
            llm_model=resolve_llm_model(default=""),
            llm_api_key=resolve_llm_api_key(),
            llm_base_url=resolve_llm_base_url(),
            llm_profile=os.environ.get("AUTORESEARCH_LLM_PROFILE", ""),
            llm_wire_api=os.environ.get("AUTORESEARCH_LLM_WIRE_API", ""),
            codex_config_path=os.environ.get("AUTORESEARCH_CODEX_CONFIG", ""),
            codex_auth_path=os.environ.get("AUTORESEARCH_CODEX_AUTH", ""),
            huggingface_token=resolve_huggingface_token(),
            sandbox_mode=os.environ.get("AUTORESEARCH_SANDBOX", "auto"),
            sandbox_image=os.environ.get("AUTORESEARCH_SANDBOX_IMAGE", ""),
            skill_name=os.environ.get("AUTORESEARCH_SKILL", ""),
            conversation_persistence_dir=os.environ.get("AUTORESEARCH_PERSISTENCE_DIR", ""),
            resume_conversation_id=os.environ.get("AUTORESEARCH_RESUME_CONVERSATION", ""),
            manual_approval=env_truthy("AUTORESEARCH_MANUAL_APPROVAL"),
            stop_before_execution=env_truthy("AUTORESEARCH_STOP_BEFORE_EXECUTION"),
            literature_online_enabled=env_truthy("AUTORESEARCH_LITERATURE_ONLINE"),
            literature_online_provider=os.environ.get("AUTORESEARCH_LITERATURE_ONLINE_PROVIDER", "openalex"),
            literature_online_providers=parse_provider_list(
                os.environ.get("AUTORESEARCH_LITERATURE_ONLINE_PROVIDERS", "")
                or os.environ.get("AUTORESEARCH_LITERATURE_ONLINE_PROVIDER", "")
                or DEFAULT_LITERATURE_ONLINE_PROVIDERS
            ),
            literature_online_max_results=int(os.environ.get("AUTORESEARCH_LITERATURE_ONLINE_MAX_RESULTS", "5")),
            literature_online_timeout=int(os.environ.get("AUTORESEARCH_LITERATURE_ONLINE_TIMEOUT", "15")),
            refresh_sota=env_truthy("AUTORESEARCH_REFRESH_SOTA"),
            literature_rag_enabled=env_truthy("AUTORESEARCH_RAG"),
            literature_corpus_dir=os.environ.get("AUTORESEARCH_RAG_CORPUS_DIR", ""),
            literature_rag_top_k=int(os.environ.get("AUTORESEARCH_RAG_TOP_K", "3")),
            literature_rag_embedding_model=os.environ.get(
                "AUTORESEARCH_RAG_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"),
            literature_rag_embedding_base_url=os.environ.get(
                "AUTORESEARCH_RAG_EMBEDDING_BASE_URL", "http://dgx-24.cm.cluster:9001/v1"),
            literature_rag_embedding_api_key=os.environ.get(
                "AUTORESEARCH_RAG_EMBEDDING_API_KEY", "sk-pathlab"),
            auto_acquire_data=env_truthy("AUTORESEARCH_AUTO_ACQUIRE_DATA"),
            download_policy=os.environ.get("AUTORESEARCH_DOWNLOAD_POLICY", "public_only"),
            max_download_size_gb=float(os.environ.get("AUTORESEARCH_MAX_DOWNLOAD_SIZE_GB", "20.0")),
            allow_large_downloads=env_truthy("AUTORESEARCH_ALLOW_LARGE_DOWNLOADS"),
            dataset_cache_dir=os.environ.get("AUTORESEARCH_DATASET_CACHE_DIR", ""),
            pathlab_user_id=os.environ.get("AUTORESEARCH_PATHLAB_USER_ID", ""),
            log_dir=os.environ.get("AUTORESEARCH_LOG_DIR", ""),
        )

    def create_session(self, research_question: str = ""):
        """Create a new isolated session with unique workspace/output dirs."""
        from .runtime.session import AutoResearchSession
        return AutoResearchSession.create(
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
