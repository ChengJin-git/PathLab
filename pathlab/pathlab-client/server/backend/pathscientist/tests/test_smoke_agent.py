"""Smoke test: run PathScientist code agent with real LLM on a trivial task.

Uses Qwen3.5 on dgx-52:8000 with a simple "write a script that saves metrics" task.
Validates the full ratchet loop: workspace → edit → validate → run → commit.
"""
import json
import sys
from pathlib import Path

# Ensure pathscientist is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from pathscientist.config import PathScientistConfig
from pathscientist.agent import create_agent, create_conversation


def test_smoke_agent():
    """Run agent on a trivial task and verify it completes."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="pathscientist_smoke_") as tmpdir:
        config = PathScientistConfig(
            workspace_dir=tmpdir,
            output_dir=str(Path(tmpdir) / "output"),
            primary_metric="accuracy",
            max_iterations=2,
            quick_check_timeout=30,
            execution_timeout=60,
            llm_model="openai/Qwen/Qwen3.5-397B-A17B-FP8",
            llm_api_key="sk-pathlab",
            llm_base_url="http://dgx-52.cm.cluster:8000/v1",
            llm_temperature=0.2,
        )

        question = (
            "Write a simple Python script called train.py that:\n"
            "1. Creates an output directory from OUTPUT_DIR env var (default /tmp/output)\n"
            "2. Computes accuracy = 0.85\n"
            "3. Saves {'test': {'accuracy': 0.85}} to OUTPUT_DIR/metrics.json\n"
            "4. Has if __name__ == '__main__' entry point\n"
            "This is a test task — keep it very simple, no ML needed."
        )

        print(f"\n{'='*60}")
        print(f"PathScientist Smoke Test")
        print(f"LLM: {config.llm_model}")
        print(f"Workspace: {tmpdir}")
        print(f"Task: trivial metrics script")
        print(f"{'='*60}\n")

        agent, workspace, tracker, session = create_agent(config, research_question=question)
        conversation = create_conversation(agent, workspace, session)

        print(f"Agent tools: {[t.name for t in agent.tools]}")
        print(f"Sending task to agent...\n")

        conversation.send_message(question)
        conversation.run()

        # Check results
        print(f"\n{'='*60}")
        print(f"RESULTS")
        print(f"{'='*60}")

        # Check workspace has files
        files = workspace.list_files()
        print(f"Workspace files: {files}")

        # Check git history
        history = workspace.get_history()
        print(f"Git commits: {len(history)}")
        for h in history:
            print(f"  {h.hash[:8]} {h.message}")

        # Check metrics
        output_dir = Path(config.output_dir)
        metrics_path = output_dir / "metrics.json"
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text())
            print(f"Metrics: {metrics}")
        else:
            print(f"No metrics.json found at {metrics_path}")

        # Check tracker
        print(f"Tracker best: {tracker.best_value:.4f} ({tracker.primary_metric})")
        print(f"Tracker iterations: {tracker.iteration}")

        # Basic assertions
        assert "train.py" in files or any("train" in f for f in files), \
            f"Expected train.py in workspace, got: {files}"

        # Check metrics were produced
        assert metrics_path.exists(), f"Expected metrics.json at {metrics_path}"

        print(f"\nSMOKE TEST PASSED")


if __name__ == "__main__":
    test_smoke_agent()
