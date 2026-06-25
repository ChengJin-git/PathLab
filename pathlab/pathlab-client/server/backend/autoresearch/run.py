"""AutoResearch CLI entry point.

Usage:
    python -m autoresearch.run --question "Improve AUC on BRACS classification"
    python -m autoresearch.run --question "..." --skill mil_classification
    python -m autoresearch.run --question "..." --mode code    # skip orchestrator
"""
from __future__ import annotations

import argparse
import logging
import warnings

# Silence noisy cost-calculation warnings for unmapped LLMs (e.g. local vLLM Qwen)
warnings.filterwarnings("ignore", message="Cost calculation failed:.*")

from .agent import create_agent, create_conversation
from .config import (
    DEFAULT_LITERATURE_ONLINE_PROVIDERS,
    AutoResearchConfig,
    env_truthy,
    load_project_env,
    parse_provider_list,
    resolve_llm_api_key,
    resolve_llm_base_url,
    resolve_llm_model,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("autoresearch")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AutoResearch — Autonomous Research Agent")
    parser.add_argument(
        "--question", "-q", required=True,
        help="Research question or task description",
    )
    parser.add_argument(
        "--mode", choices=["research", "code"], default="research",
        help="research = orchestrated session (default); code = direct code agent",
    )
    parser.add_argument("--skill", default="", help="Skill name (e.g., mil_classification)")
    parser.add_argument("--workspace", default="", help="Workspace directory")
    parser.add_argument("--output", default="", help="Output directory")
    parser.add_argument("--metric", default="auc", help="Primary metric name")
    parser.add_argument("--max-iter", type=int, default=5, help="Max iterations")
    parser.add_argument("--timeout", type=int, default=None, help="Execution timeout (seconds)")
    parser.add_argument("--gpu", default="0", help="GPU IDs (comma-separated)")
    parser.add_argument("--model", default="", help="LLM model name")
    parser.add_argument("--api-key", default="", help="LLM API key")
    parser.add_argument("--base-url", default="", help="LLM base URL")
    parser.add_argument("--llm-profile", choices=["", "codex-relay"], default="", help="Explicit LLM profile")
    parser.add_argument("--codex-config", default="", help="Path to Codex config.toml for --llm-profile codex-relay")
    parser.add_argument("--codex-auth", default="", help="Path to Codex auth.json for --llm-profile codex-relay")
    parser.add_argument("--data-mount", action="append", default=[], help="Data mount host:container")
    parser.add_argument("--sandbox", choices=["local", "apptainer", "auto"], default=None)
    parser.add_argument("--sandbox-image", default="")
    parser.add_argument("--manual-approval", action="store_true", help="Pause after grounding for manual approval")
    parser.add_argument("--stop-before-execution", action="store_true", help="Run intake/grounding/acquisition and stop before the code agent executes")
    parser.add_argument("--literature-online", action="store_true", help="Enable online literature search")
    parser.add_argument("--literature-online-provider", default="", help="Single online search provider override")
    parser.add_argument("--literature-online-providers", default="", help="Comma-separated online search providers")
    parser.add_argument("--literature-online-max-results", type=int, default=5, help="Max online results")
    parser.add_argument("--refresh-sota", action="store_true", help="Bypass cached SOTA lookup results for this session")
    parser.add_argument("--rag", action="store_true", help="Enable literature RAG retrieval")
    parser.add_argument("--rag-corpus-dir", default="", help="Local directory of papers for RAG ingestion")
    parser.add_argument("--rag-top-k", type=int, default=3, help="Number of passages to retrieve")
    parser.add_argument("--auto-acquire-data", action="store_true", help="Enable dataset acquisition before execution")
    parser.add_argument("--download-policy", choices=["public_only", "manual_only", "public_or_manual", "all", "disabled"], default=None)
    parser.add_argument("--max-download-size-gb", type=float, default=None)
    parser.add_argument("--allow-large-downloads", action="store_true")
    parser.add_argument("--dataset-cache-dir", default="")
    return parser.parse_args(argv)


def _build_config(args: argparse.Namespace) -> AutoResearchConfig:
    load_project_env()
    data_mounts = {}
    for mount in args.data_mount:
        if ":" in mount:
            host, container = mount.split(":", 1)
            data_mounts[host] = container

    import os
    return AutoResearchConfig(
        workspace_dir=args.workspace,
        output_dir=args.output,
        data_mounts=data_mounts,
        gpu_ids=args.gpu.split(","),
        primary_metric=args.metric,
        max_iterations=args.max_iter,
        quick_check_timeout=int(
            os.environ.get("AUTORESEARCH_QUICK_CHECK_TIMEOUT", "3600")
        ),
        execution_timeout=(
            args.timeout
            if args.timeout is not None
            else int(os.environ.get("AUTORESEARCH_TIMEOUT", "3600"))
        ),
        feature_extraction_timeout=int(
            os.environ.get("AUTORESEARCH_FEATURE_EXTRACTION_TIMEOUT", "86400")
        ),
        feature_extraction_quick_timeout=int(
            os.environ.get("AUTORESEARCH_FEATURE_EXTRACTION_QUICK_TIMEOUT", "3600")
        ),
        llm_model=resolve_llm_model(args.model, default=""),
        llm_api_key=resolve_llm_api_key(args.api_key),
        llm_base_url=resolve_llm_base_url(args.base_url),
        llm_profile=args.llm_profile or os.environ.get("AUTORESEARCH_LLM_PROFILE", ""),
        llm_wire_api=os.environ.get("AUTORESEARCH_LLM_WIRE_API", ""),
        codex_config_path=args.codex_config or os.environ.get("AUTORESEARCH_CODEX_CONFIG", ""),
        codex_auth_path=args.codex_auth or os.environ.get("AUTORESEARCH_CODEX_AUTH", ""),
        skill_name=args.skill,
        sandbox_mode=args.sandbox or os.environ.get("AUTORESEARCH_SANDBOX", "auto"),
        sandbox_image=args.sandbox_image or os.environ.get("AUTORESEARCH_SANDBOX_IMAGE", ""),
        manual_approval=args.manual_approval or env_truthy("AUTORESEARCH_MANUAL_APPROVAL"),
        stop_before_execution=args.stop_before_execution or env_truthy("AUTORESEARCH_STOP_BEFORE_EXECUTION"),
        literature_online_enabled=args.literature_online or env_truthy("AUTORESEARCH_LITERATURE_ONLINE"),
        literature_online_provider=args.literature_online_provider or os.environ.get("AUTORESEARCH_LITERATURE_ONLINE_PROVIDER", "openalex"),
        literature_online_providers=parse_provider_list(
            args.literature_online_providers
            or os.environ.get("AUTORESEARCH_LITERATURE_ONLINE_PROVIDERS", "")
            or args.literature_online_provider
            or os.environ.get("AUTORESEARCH_LITERATURE_ONLINE_PROVIDER", "")
            or DEFAULT_LITERATURE_ONLINE_PROVIDERS,
        ),
        literature_online_max_results=args.literature_online_max_results,
        literature_online_timeout=int(os.environ.get("AUTORESEARCH_LITERATURE_ONLINE_TIMEOUT", "15")),
        refresh_sota=args.refresh_sota or env_truthy("AUTORESEARCH_REFRESH_SOTA"),
        literature_rag_enabled=args.rag or env_truthy("AUTORESEARCH_RAG"),
        literature_corpus_dir=args.rag_corpus_dir or os.environ.get("AUTORESEARCH_RAG_CORPUS_DIR", ""),
        literature_rag_top_k=args.rag_top_k,
        literature_rag_embedding_model=os.environ.get("AUTORESEARCH_RAG_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"),
        literature_rag_embedding_base_url=os.environ.get("AUTORESEARCH_RAG_EMBEDDING_BASE_URL", "http://dgx-24.cm.cluster:9001/v1"),
        literature_rag_embedding_api_key=os.environ.get("AUTORESEARCH_RAG_EMBEDDING_API_KEY", "sk-pathlab"),
        auto_acquire_data=args.auto_acquire_data or env_truthy("AUTORESEARCH_AUTO_ACQUIRE_DATA"),
        download_policy=args.download_policy or os.environ.get("AUTORESEARCH_DOWNLOAD_POLICY", "public_only"),
        max_download_size_gb=float(
            args.max_download_size_gb
            if args.max_download_size_gb is not None
            else os.environ.get("AUTORESEARCH_MAX_DOWNLOAD_SIZE_GB", "20.0")
        ),
        allow_large_downloads=args.allow_large_downloads or env_truthy("AUTORESEARCH_ALLOW_LARGE_DOWNLOADS"),
        dataset_cache_dir=args.dataset_cache_dir or os.environ.get("AUTORESEARCH_DATASET_CACHE_DIR", ""),
    )


def run_code_mode(config: AutoResearchConfig, question: str) -> None:
    """Direct code-agent mode — no orchestrator, single conversation.run()."""
    agent, workspace, tracker, session = create_agent(config, research_question=question)

    logger.info(f"  Workspace: {workspace.root}")
    logger.info(f"  Conversation: {session.conversation_id}")
    logger.info(f"Agent created with {len(agent.tools)} tools")

    conversation = create_conversation(agent, workspace, session)

    logger.info(f"LLM: {agent.llm.model}")
    logger.info(f"Tools: {[t.name for t in agent.tools]}")

    conversation.send_message(question)
    conversation.run()

    print(f"\nBest {tracker.primary_metric}: {tracker.best_value:.4f}")
    print(f"Iterations: {tracker.iteration}")
    print(f"Workspace: {workspace.root}")


def run_research_session(config: AutoResearchConfig, question: str) -> None:
    """Orchestrated research session — staged execution with director."""
    from .orchestrator.runner import run_research_session as _run

    state, session, _ = _run(config, question, auto_approve=not config.manual_approval)

    if state.approval_status == "pending":
        print(f"\nSession paused: {state.stage}")
        print("Approval status: pending")
        print(f"Resume with: python -m autoresearch --resume {session.conversation_id}")
    else:
        print(f"\nSession completed: {state.stage}")
    if state.best_run_id:
        print(f"Best {state.objective.success_metric}: {state.best_metric_value:.4f} ({state.best_run_id})")
    print(f"Iterations: {len(state.run_history)}")
    if state.report_markdown_path:
        print(f"Report: {state.report_markdown_path}")
    if state.paper_draft_path:
        print(f"Paper draft: {state.paper_draft_path}")
    if state.claim_count:
        print(f"Claims: {state.claim_count}")
    if hasattr(state, "paper_ready"):
        print(f"Paper ready: {'Yes' if state.paper_ready else 'No'}")
    if state.final_summary:
        print(f"\n{state.final_summary}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = _build_config(args)

    logger.info("Starting AutoResearch")
    logger.info(f"  Question: {args.question}")
    logger.info(f"  Mode: {args.mode}")
    logger.info(f"  Skill: {config.skill_name or '(none)'}")
    logger.info(f"  Max iterations: {config.max_iterations}")

    if args.mode == "code":
        run_code_mode(config, args.question)
    else:
        run_research_session(config, args.question)


if __name__ == "__main__":
    main()
