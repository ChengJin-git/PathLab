"""PathScientist CLI entry point.

Usage:
    python -m pathscientist.run --question "Improve AUC on BRACS classification"
    python -m pathscientist.run --question "..." --skill mil_classification
    python -m pathscientist.run --question "..." --max-iter 3
"""
from __future__ import annotations

import argparse
import logging
import warnings

# Silence noisy cost-calculation warnings for unmapped LLMs (e.g. local vLLM Qwen)
warnings.filterwarnings("ignore", message="Cost calculation failed:.*")

from .agent import create_agent, create_conversation
from .config import PathScientistConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("pathscientist")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PathScientist — Autonomous Research Agent")
    parser.add_argument(
        "--question", "-q", required=True,
        help="Research question or task description",
    )
    parser.add_argument("--skill", default="", help="Skill name (e.g., mil_classification)")
    parser.add_argument("--workspace", default="", help="Workspace directory")
    parser.add_argument("--output", default="", help="Output directory")
    parser.add_argument("--metric", default="auc", help="Primary metric name")
    parser.add_argument("--max-iter", type=int, default=5, help="Max iterations")
    parser.add_argument("--timeout", type=int, default=600, help="Execution timeout (seconds)")
    parser.add_argument("--gpu", default="0", help="GPU IDs (comma-separated)")
    parser.add_argument("--model", default="", help="LLM model name")
    parser.add_argument("--api-key", default="", help="LLM API key")
    parser.add_argument("--base-url", default="", help="LLM base URL")
    parser.add_argument("--data-mount", action="append", default=[], help="Data mount host:container")
    return parser.parse_args()


def main():
    args = parse_args()

    # Parse data mounts
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
    )

    logger.info("Starting PathScientist agent")
    logger.info(f"  Question: {args.question}")
    logger.info(f"  Skill: {config.skill_name or '(none)'}")
    logger.info(f"  Max iterations: {config.max_iterations}")

    agent, workspace, tracker, session = create_agent(config, research_question=args.question)

    logger.info(f"  Workspace: {workspace.root}")
    logger.info(f"  Conversation: {session.conversation_id}")
    logger.info(f"Agent created with {len(agent.tools)} tools")

    # Create conversation with SDK stuck detection and persistence
    conversation = create_conversation(agent, workspace, session)

    logger.info(f"Agent: {agent.name}")
    logger.info(f"LLM: {agent.llm.model}")
    logger.info(f"Tools: {[t.name for t in agent.tools]}")

    # Run the agent loop
    conversation.send_message(args.question)
    conversation.run()

    # Report results
    print(f"\nBest {tracker.primary_metric}: {tracker.best_value:.4f}")
    print(f"Iterations: {tracker.iteration}")
    print(f"Workspace: {workspace.root}")


if __name__ == "__main__":
    main()
