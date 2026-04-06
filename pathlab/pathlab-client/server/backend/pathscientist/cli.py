"""PathScientist interactive CLI — chat with the code agent.

Usage:
    python -m pathscientist
    python -m pathscientist --skill mil_classification
    python -m pathscientist --model openai/Qwen/Qwen3.5-397B-A17B-FP8 --base-url http://dgx-52.cm.cluster:8000/v1
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import warnings

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

# Silence noisy cost-calculation warnings for unmapped LLMs (e.g. local vLLM Qwen)
warnings.filterwarnings("ignore", message="Cost calculation failed:.*")

from .agent import create_agent, create_conversation
from .config import PathScientistConfig

logging.basicConfig(level=logging.WARNING, format="%(message)s")

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


def _print_banner():
    print(f"""
{BOLD}╔══════════════════════════════════════════╗
║  {CYAN}PathScientist{RESET}{BOLD}  — Code Agent CLI          ║
║  Type your task, watch the agent work.   ║
║  Send follow-ups anytime.                ║
║  {YELLOW}/status{RESET}{BOLD}  {YELLOW}/help{RESET}{BOLD}  {YELLOW}/quit{RESET}{BOLD}                    ║
╚══════════════════════════════════════════╝{RESET}
""")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PathScientist Interactive CLI")
    parser.add_argument("--skill", default="", help="Skill (e.g., mil_classification)")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--metric", default="auc")
    parser.add_argument("--max-iter", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--gpu", default="0")
    parser.add_argument("--model", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--data-mount", action="append", default=[])
    parser.add_argument("--sandbox", choices=["local", "apptainer", "auto"], default="auto",
                        help="Sandbox mode for script execution (default: auto)")
    parser.add_argument("--sandbox-image", default="",
                        help="Path to .sif image (empty = auto-detect)")
    return parser.parse_args()


def main():
    args = parse_args()

    data_mounts = {}
    for mount in args.data_mount:
        if ":" in mount:
            host, container = mount.split(":", 1)
            data_mounts[host] = container

    config = PathScientistConfig(
        workspace_dir=args.workspace,
        output_dir=args.output,
        data_mounts=data_mounts,
        gpu_ids=args.gpu.split(","),
        primary_metric=args.metric,
        max_iterations=args.max_iter,
        execution_timeout=args.timeout,
        llm_model=args.model,
        llm_api_key=args.api_key,
        llm_base_url=args.base_url,
        skill_name=args.skill,
        sandbox_mode=args.sandbox,
        sandbox_image=args.sandbox_image,
    )

    _print_banner()

    model_name = config.llm_model or os.environ.get("PATHSCIENTIST_LLM_MODEL", "(not set)")
    print(f"{DIM}Model: {model_name}{RESET}")
    if config.skill_name:
        print(f"{DIM}Skill: {config.skill_name}{RESET}")
    print(f"{DIM}Metric: {config.primary_metric} | Max iter: {config.max_iterations}{RESET}")
    print()

    agent = None
    workspace = None
    tracker = None
    conversation = None

    while True:
        try:
            user_input = input(f"{BOLD}You >{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Bye!{RESET}")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/quit", "/exit", "/q"):
            if tracker and tracker.best_value > 0:
                print(f"\n{GREEN}Best {tracker.primary_metric}: {tracker.best_value:.4f}{RESET}")
            if workspace:
                print(f"{DIM}Workspace: {workspace.root}{RESET}")
            break

        if user_input.lower() == "/status":
            if tracker:
                print(f"  Best {tracker.primary_metric}: {tracker.best_value:.4f}")
                print(f"  Iterations: {tracker.iteration}")
            if workspace:
                print(f"  Workspace: {workspace.root}")
                print(f"  Files: {workspace.list_files()}")
                print(f"  Commits: {len(workspace.get_history())}")
            else:
                print(f"  {DIM}No session yet.{RESET}")
            continue

        if user_input.lower() == "/help":
            print(f"""
  {BOLD}/status{RESET}  — metrics, workspace, commits
  {BOLD}/quit{RESET}    — exit
  {BOLD}/help{RESET}    — this help

  Type any message to interact with the agent.
  The agent will edit code, run experiments, and track improvements.
  SDK visualizer shows all actions and results in real-time.
""")
            continue

        # Init on first message
        if agent is None:
            print(f"{DIM}Initializing agent...{RESET}")
            agent, workspace, tracker, session = create_agent(config, research_question=user_input)
            conversation = create_conversation(agent, workspace, session)
            print(f"{DIM}Conversation: {session.conversation_id}{RESET}")
            print(f"{DIM}Workspace: {workspace.root}{RESET}")
            print(f"{DIM}Tools: {[t.name for t in agent.tools]}{RESET}\n")

        # Send and run — SDK DefaultConversationVisualizer prints events in real-time
        try:
            conversation.send_message(user_input)
            conversation.run()
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Interrupted.{RESET} Send another message or /quit.")
            continue
        except Exception as e:
            print(f"\n{RED}Error: {e}{RESET}")
            continue

        if tracker and tracker.best_value > 0:
            print(f"\n{DIM}Best {tracker.primary_metric}: {tracker.best_value:.4f}{RESET}")


if __name__ == "__main__":
    main()
