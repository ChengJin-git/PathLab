"""PathScientist interactive CLI — research agent shell.

Usage:
    python -m pathscientist                           # interactive research mode
    python -m pathscientist --mode code               # interactive code agent mode
    python -m pathscientist --resume <uuid>            # resume saved session
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import warnings

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
warnings.filterwarnings("ignore", message="Cost calculation failed:.*")

from .agent import create_agent, create_conversation
from .cli_commands import handle_command
from .cli_input import configure_line_editing, expand_file_mentions, parse_bang_command, read_user_input
from .cli_render import build_status_line
from .cli_state import InteractiveCLIState
from .config import (
    PathScientistConfig,
    env_truthy,
    load_project_env,
    resolve_llm_api_key,
    resolve_llm_base_url,
    resolve_llm_model,
)

logging.basicConfig(level=logging.WARNING, format="%(message)s")

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
PURPLE = "\033[38;2;167;133;214m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


def _print_banner():
    print(f"""{PURPLE}
  ██████╗  █████╗ ████████╗██╗  ██╗
  ██╔══██╗██╔══██╗╚══██╔══╝██║  ██║
  ██████╔╝███████║   ██║   ███████║
  ██╔═══╝ ██╔══██║   ██║   ██╔══██║
  ██║     ██║  ██║   ██║   ██║  ██║
  ╚═╝     ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝
  ███████╗ ██████╗██╗███████╗███╗   ██╗████████╗██╗███████╗████████╗
  ██╔════╝██╔════╝██║██╔════╝████╗  ██║╚══██╔══╝██║██╔════╝╚══██╔══╝
  ███████╗██║     ██║█████╗  ██╔██╗ ██║   ██║   ██║███████╗   ██║
  ╚════██║██║     ██║██╔══╝  ██║╚██╗██║   ██║   ██║╚════██║   ██║
  ███████║╚██████╗██║███████╗██║ ╚████║   ██║   ██║███████║   ██║
  ╚══════╝ ╚═════╝╚═╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝╚══════╝   ╚═╝{RESET}
{DIM}  Autonomous Research Agent for Computational Pathology{RESET}
{DIM}  Type your research goal to start. /help for commands.{RESET}
""")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PathScientist Interactive CLI")
    parser.add_argument("--skill", default="")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--metric", default="auc")
    parser.add_argument("--max-iter", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--gpu", default="0")
    parser.add_argument("--model", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--llm-profile", choices=["", "codex-relay"], default="")
    parser.add_argument("--codex-config", default="", help="Path to Codex config.toml for --llm-profile codex-relay")
    parser.add_argument("--codex-auth", default="", help="Path to Codex auth.json for --llm-profile codex-relay")
    parser.add_argument("--data-mount", action="append", default=[])
    parser.add_argument("--sandbox", choices=["local", "apptainer", "auto"], default="auto")
    parser.add_argument("--sandbox-image", default="")
    parser.add_argument("--mode", choices=["research", "code"], default="research")
    parser.add_argument("--resume", default="", help="Resume conversation by UUID")
    parser.add_argument("--manual-approval", action="store_true", help="Pause after grounding and wait for /approve or /reject")
    parser.add_argument("--stop-before-execution", action="store_true", help="Run intake/grounding/acquisition and stop before the code agent executes")
    parser.add_argument("--literature-online", action="store_true", help="Enable online literature search (OpenAlex)")
    parser.add_argument("--literature-online-provider", default="openalex", help="Online search provider")
    parser.add_argument("--literature-online-max-results", type=int, default=5, help="Max online search results")
    parser.add_argument("--refresh-sota", action="store_true", help="Bypass cached SOTA lookup results for this session")
    parser.add_argument("--rag", action="store_true", help="Enable literature RAG retrieval")
    parser.add_argument("--rag-corpus-dir", default="", help="Local directory of papers for RAG ingestion")
    parser.add_argument("--rag-top-k", type=int, default=3, help="Number of passages to retrieve")
    parser.add_argument("--auto-acquire-data", action="store_true", help="Enable dataset acquisition before execution")
    parser.add_argument("--download-policy", choices=["public_only", "manual_only", "disabled"], default=None)
    parser.add_argument("--max-download-size-gb", type=float, default=None)
    parser.add_argument("--allow-large-downloads", action="store_true")
    parser.add_argument("--dataset-cache-dir", default="")
    parser.add_argument("--no-banner", action="store_true")
    return parser.parse_args(argv)


def _build_config(args: argparse.Namespace) -> PathScientistConfig:
    load_project_env()
    data_mounts = {}
    for mount in args.data_mount:
        if ":" in mount:
            host, container = mount.split(":", 1)
            data_mounts[host] = container
    return PathScientistConfig(
        workspace_dir=args.workspace,
        output_dir=args.output,
        data_mounts=data_mounts,
        gpu_ids=args.gpu.split(","),
        primary_metric=args.metric,
        max_iterations=args.max_iter,
        execution_timeout=args.timeout,
        llm_model=resolve_llm_model(args.model, default=""),
        llm_api_key=resolve_llm_api_key(args.api_key),
        llm_base_url=resolve_llm_base_url(args.base_url),
        llm_profile=args.llm_profile or os.environ.get("PATHSCIENTIST_LLM_PROFILE", ""),
        llm_wire_api=os.environ.get("PATHSCIENTIST_LLM_WIRE_API", ""),
        codex_config_path=args.codex_config or os.environ.get("PATHSCIENTIST_CODEX_CONFIG", ""),
        codex_auth_path=args.codex_auth or os.environ.get("PATHSCIENTIST_CODEX_AUTH", ""),
        skill_name=args.skill,
        sandbox_mode=args.sandbox,
        sandbox_image=args.sandbox_image,
        manual_approval=args.manual_approval or env_truthy("PATHSCIENTIST_MANUAL_APPROVAL"),
        stop_before_execution=args.stop_before_execution or env_truthy("PATHSCIENTIST_STOP_BEFORE_EXECUTION"),
        literature_online_enabled=args.literature_online or env_truthy("PATHSCIENTIST_LITERATURE_ONLINE"),
        literature_online_provider=args.literature_online_provider,
        literature_online_max_results=args.literature_online_max_results,
        literature_online_timeout=int(os.environ.get("PATHSCIENTIST_LITERATURE_ONLINE_TIMEOUT", "15")),
        refresh_sota=args.refresh_sota or env_truthy("PATHSCIENTIST_REFRESH_SOTA"),
        literature_rag_enabled=args.rag or env_truthy("PATHSCIENTIST_RAG"),
        literature_corpus_dir=args.rag_corpus_dir or os.environ.get("PATHSCIENTIST_RAG_CORPUS_DIR", ""),
        literature_rag_top_k=args.rag_top_k,
        literature_rag_embedding_model=os.environ.get("PATHSCIENTIST_RAG_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"),
        literature_rag_embedding_base_url=os.environ.get("PATHSCIENTIST_RAG_EMBEDDING_BASE_URL", "http://dgx-24.cm.cluster:9001/v1"),
        literature_rag_embedding_api_key=os.environ.get("PATHSCIENTIST_RAG_EMBEDDING_API_KEY", "sk-pathlab"),
        auto_acquire_data=args.auto_acquire_data or env_truthy("PATHSCIENTIST_AUTO_ACQUIRE_DATA"),
        download_policy=args.download_policy or os.environ.get("PATHSCIENTIST_DOWNLOAD_POLICY", "public_only"),
        max_download_size_gb=float(
            args.max_download_size_gb
            if args.max_download_size_gb is not None
            else os.environ.get("PATHSCIENTIST_MAX_DOWNLOAD_SIZE_GB", "20.0")
        ),
        allow_large_downloads=args.allow_large_downloads or env_truthy("PATHSCIENTIST_ALLOW_LARGE_DOWNLOADS"),
        dataset_cache_dir=args.dataset_cache_dir or os.environ.get("PATHSCIENTIST_DATASET_CACHE_DIR", ""),
    )


def main(argv: list[str] | None = None):
    args = parse_args(argv)
    config = _build_config(args)
    state = InteractiveCLIState(mode=args.mode)
    history_base_dir = config.conversation_persistence_dir or os.environ.get(
        "PATHSCIENTIST_BASE_DIR",
        "/project/vcompath/storage/ywangrm/tmp/pathscientist",
    )

    model_name = resolve_llm_model(config.llm_model, default="") or "(not set)"
    sandbox_mode = config.sandbox_mode

    if not args.no_banner:
        _print_banner()
        print(f"{DIM}Mode: {state.mode} | Model: {model_name}{RESET}")
        if config.skill_name:
            print(f"{DIM}Skill: {config.skill_name}{RESET}")
        print()

    # Handle --resume from CLI args
    if args.resume:
        _handle_resume(state, config, args.resume)

    configure_line_editing(history_base_dir)

    # Main REPL loop
    while True:
        # Status line
        if state.ready:
            print(build_status_line(state, model_name, sandbox_mode))

        try:
            user_input = read_user_input(f"{BOLD}You >{RESET} ", history_base_dir).strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Bye!{RESET}")
            break

        if not user_input:
            continue

        # !shell command
        bang = parse_bang_command(user_input)
        if bang is not None:
            try:
                result = subprocess.run(bang, shell=True, capture_output=True, text=True, timeout=30)
                if result.stdout:
                    print(result.stdout, end="")
                if result.stderr:
                    print(f"{RED}{result.stderr}{RESET}", end="")
            except subprocess.TimeoutExpired:
                print(f"{RED}Command timed out (30s){RESET}")
            continue

        # Slash commands
        cmd_result = handle_command(user_input, state)
        if cmd_result.handled:
            if cmd_result.should_exit:
                _print_exit(state)
                break
            # Special handling for /sessions, /resume, /approve
            if cmd_result.output == "__list_sessions__":
                _handle_list_sessions(config)
            elif cmd_result.output.startswith("__resume__:"):
                conv_id = cmd_result.output.split(":", 1)[1]
                if conv_id:
                    _handle_resume(state, config, conv_id)
                else:
                    print(f"{YELLOW}Usage: /resume <conversation-uuid>{RESET}")
            elif cmd_result.output == "__approve__":
                _handle_approved(state, config)
            elif cmd_result.output == "__reject__":
                _handle_rejected(state, config)
            elif cmd_result.output.startswith("__search__:"):
                query = cmd_result.output.split(":", 1)[1]
                _handle_search(config, query)
            elif cmd_result.output:
                print(cmd_result.output)
            continue

        # Regular message → start or continue session
        if state.mode == "research":
            _handle_research_message(state, config, user_input)
        else:
            _handle_code_message(state, config, user_input)


def _handle_research_message(state: InteractiveCLIState, config: PathScientistConfig, message: str):
    """Handle a user message in research mode."""
    if state.ready:
        rs = state.research_state
        if rs and rs.stage in ("completed", "synthesis"):
            # Session finished — allow starting a follow-up research session
            state.reset_session()
            _start_research_session(state, config, message)
            return
        if rs and rs.stage in ("execution", "review"):
            print(f"{YELLOW}Session interrupted at stage '{rs.stage}'. "
                  f"Use /new to start fresh, or /status to inspect.{RESET}")
            return
        if rs and getattr(rs, "approval_status", "none") == "pending":
            print(f"{YELLOW}Session is waiting for approval. Use /approve or /reject.{RESET}")
            return
        print(f"{YELLOW}Session already running. Use /new to start a new session.{RESET}")
        return

    _start_research_session(state, config, message)


def _start_research_session(state: InteractiveCLIState, config: PathScientistConfig, message: str):
    """Create and run a new research session, then hydrate CLI state."""
    print(f"{DIM}Starting research session...{RESET}")
    try:
        from openhands.sdk.conversation.visualizer import DefaultConversationVisualizer
        from .orchestrator.runner import run_research_session
        from .runtime.session_registry import get_session
        research_state, session, conversation = run_research_session(
            config,
            message,
            auto_approve=not config.manual_approval,
            visualizer=DefaultConversationVisualizer,
        )
        # Hydrate CLI state so /status /metrics /workspace /summary all work
        deps = get_session(session.session_id)
        state.research_state = research_state
        state.session = session
        state.conversation = conversation
        state.workspace = deps.workspace
        state.tracker = deps.tracker
        if research_state.approval_status == "pending":
            print(
                f"\n{YELLOW}Grounding ready. Session is waiting for approval; "
                f"use /approve or /reject.{RESET}"
            )
        else:
            print(f"\n{GREEN}Session completed: {research_state.stage}{RESET}")
            if research_state.best_run_id:
                print(f"{GREEN}Best {research_state.objective.success_metric}: "
                      f"{research_state.best_metric_value:.4f} ({research_state.best_run_id}){RESET}")
            if research_state.final_summary:
                print(f"\n{research_state.final_summary}")
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted.{RESET}")
    except Exception as e:
        print(f"\n{RED}Error: {e}{RESET}")


def _handle_code_message(state: InteractiveCLIState, config: PathScientistConfig, message: str):
    """Handle a user message in code mode."""
    # Init on first message
    if not state.ready:
        print(f"{DIM}Initializing agent...{RESET}")
        from openhands.sdk.conversation.visualizer import DefaultConversationVisualizer
        agent, workspace, tracker, session = create_agent(config, research_question=message)
        conversation = create_conversation(agent, workspace, session, visualizer=DefaultConversationVisualizer)
        state.agent = agent
        state.workspace = workspace
        state.tracker = tracker
        state.session = session
        state.conversation = conversation
        print(f"{DIM}Conversation: {session.conversation_id}{RESET}")
        print(f"{DIM}Workspace: {workspace.root}{RESET}\n")

    # Expand @file references
    if state.workspace:
        message = expand_file_mentions(message, state.workspace.root)

    try:
        state.conversation.send_message(message)
        state.conversation.run()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted.{RESET} Send another message or /quit.")
    except Exception as e:
        print(f"\n{RED}Error: {e}{RESET}")

    if state.tracker and state.tracker.best_value > 0:
        print(f"\n{DIM}Best {state.tracker.primary_metric}: {state.tracker.best_value:.4f}{RESET}")


def _handle_search(config: PathScientistConfig, query: str):
    """Search for papers online and display results."""
    try:
        from .literature_search import print_results, save_papers, search_papers
        print(f"{DIM}Searching OpenAlex for: {query}{RESET}")
        papers = search_papers(
            query,
            provider=config.literature_online_provider,
            top_k=config.literature_online_max_results,
            timeout=config.literature_online_timeout,
        )
        if not papers:
            print(f"{YELLOW}No papers found.{RESET}")
            return
        print_results(papers)

        # Interactive save prompt
        try:
            answer = input(f"{BOLD}Save to local store? [y/N] {RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer in ("y", "yes"):
            saved = save_papers(
                papers,
                os.environ.get(
                    "PATHSCIENTIST_BASE_DIR",
                    "/project/vcompath/storage/ywangrm/tmp/pathscientist",
                ),
            )
            print(f"{GREEN}Saved {saved} paper(s) to local store.{RESET}")
    except Exception as e:
        print(f"{RED}Search failed: {e}{RESET}")


def _handle_approved(state: InteractiveCLIState, config: PathScientistConfig):
    """Resume research session after /approve."""
    if not state.ready or not state.research_state or not state.conversation:
        print(f"{RED}No active session to approve.{RESET}")
        return
    print(f"{DIM}Approved. Continuing research session...{RESET}")
    try:
        from .orchestrator.runner import continue_research_session
        from .runtime.session_registry import get_session
        research_state, session, conversation = continue_research_session(
            config,
            state.research_state,
            state.session,
            state.conversation,
            auto_approve=not config.manual_approval,
        )
        deps = get_session(session.session_id)
        state.research_state = research_state
        state.session = session
        state.conversation = conversation
        state.workspace = deps.workspace
        state.tracker = deps.tracker
        print(f"\n{GREEN}Session completed: {research_state.stage}{RESET}")
        if research_state.best_run_id:
            print(f"{GREEN}Best {research_state.objective.success_metric}: "
                  f"{research_state.best_metric_value:.4f} ({research_state.best_run_id}){RESET}")
        if research_state.final_summary:
            print(f"\n{research_state.final_summary}")
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted.{RESET}")
    except Exception as e:
        print(f"\n{RED}Error: {e}{RESET}")


def _handle_rejected(state: InteractiveCLIState, config: PathScientistConfig):
    """Terminate a pending research session after /reject."""
    if not state.ready or not state.research_state or not state.conversation:
        print(f"{RED}No active session to reject.{RESET}")
        return
    print(f"{DIM}Rejected. Terminating research session...{RESET}")
    try:
        from .orchestrator.runner import continue_research_session
        from .runtime.session_registry import get_session

        research_state, session, conversation = continue_research_session(
            config,
            state.research_state,
            state.session,
            state.conversation,
            auto_approve=not config.manual_approval,
        )
        deps = get_session(session.session_id)
        state.research_state = research_state
        state.session = session
        state.conversation = conversation
        state.workspace = deps.workspace
        state.tracker = deps.tracker
        print(f"\n{GREEN}Session completed: {research_state.stage}{RESET}")
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted.{RESET}")
    except Exception as e:
        print(f"\n{RED}Error: {e}{RESET}")


def _handle_resume(state: InteractiveCLIState, config: PathScientistConfig, conv_id: str):
    """Resume a saved conversation."""
    try:
        from .cli_sessions import start_resumed_session
        start_resumed_session(state, config, conv_id)
        print(f"{GREEN}Resumed: {conv_id[:12]}...{RESET}")
    except Exception as e:
        print(f"{RED}Resume failed: {e}{RESET}")


def _handle_list_sessions(config: PathScientistConfig):
    """List saved conversations."""
    try:
        from .persistence.history import list_conversations
        from .persistence.layout import get_persistence_root
        root = get_persistence_root(
            config.conversation_persistence_dir or
            os.environ.get("PATHSCIENTIST_BASE_DIR", "/project/vcompath/storage/ywangrm/tmp/pathscientist")
        )
        conversations = list_conversations(root)
        if not conversations:
            print(f"{DIM}No saved sessions.{RESET}")
            return
        for c in conversations[:10]:
            status = c.get("execution_status", "?")
            conv_id = c.get("conversation_id", "?")
            summary = c.get("research_summary", "")[:60]
            print(f"  {conv_id[:12]}  {status:10s}  {summary}")
    except Exception as e:
        print(f"{RED}Error listing sessions: {e}{RESET}")


def _print_exit(state: InteractiveCLIState):
    """Print exit summary and clean up resources."""
    if state.tracker and state.tracker.best_value > 0:
        print(f"\n{GREEN}Best {state.tracker.primary_metric}: {state.tracker.best_value:.4f}{RESET}")
    if state.workspace:
        print(f"{DIM}Workspace: {state.workspace.root}{RESET}")
    state.reset_session()


if __name__ == "__main__":
    main()
