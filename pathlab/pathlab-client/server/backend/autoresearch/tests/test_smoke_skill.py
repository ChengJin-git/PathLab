"""Smoke test: AutoResearch code agent with mil_classification skill.

Loads skill template, generates mock data, agent modifies code and runs experiment.
Uses real LLM (Qwen3.5 on dgx-52).
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from autoresearch.config import AutoResearchConfig
from autoresearch.agent import create_agent, create_conversation


def test_smoke_skill():
    with tempfile.TemporaryDirectory(prefix="autoresearch_skill_") as tmpdir:
        workspace_dir = str(Path(tmpdir) / "workspace")
        output_dir = str(Path(tmpdir) / "output")
        data_dir = str(Path(tmpdir) / "data")

        # Generate mock data from skill
        from autoresearch.domain.skills import registry
        skill = registry.get("mil_classification")
        skill.generate_mock_data(data_dir)

        config = AutoResearchConfig(
            workspace_dir=workspace_dir,
            output_dir=output_dir,
            data_mounts={
                f"{data_dir}/features": "/data/features",
                f"{data_dir}/splits.json": "/data/splits.json",
            },
            primary_metric="auc",
            max_iterations=1,
            quick_check_timeout=120,
            execution_timeout=300,
            llm_model="openai/Qwen/Qwen3.5-397B-A17B-FP8",
            llm_api_key="sk-pathlab",
            llm_base_url="http://dgx-52.cm.cluster:8000/v1",
            llm_temperature=0.2,
            skill_name="mil_classification",
        )

        question = (
            "Run the MIL classification experiment with the provided template and mock data. "
            "The data is at /data/features (pre-extracted .pt files) and /data/splits.json. "
            "But since we're running locally (not in container), the actual paths are:\n"
            f"  - Features: {data_dir}/features/\n"
            f"  - Splits: {data_dir}/splits.json\n"
            f"  - Output: {output_dir}/\n"
            "The template is already loaded as train.py in the workspace. "
            "Fix any import errors, make sure paths point to the actual data, "
            "and run a quick check first. "
            "Use only CPU (no CUDA) since this is a test with mock data. "
            "Keep max_epochs=2 for speed."
        )

        print(f"\n{'='*60}")
        print("AutoResearch Skill Integration Test")
        print(f"Skill: {skill.name}")
        print(f"Template: {skill.template} ({len(skill.get_template_content())} chars)")
        print(f"Mock data: {data_dir}")
        print(f"Workspace: {workspace_dir}")
        print(f"{'='*60}\n")

        agent, workspace, tracker, session = create_agent(config, research_question=question)

        print(f"Agent tools: {[t.name for t in agent.tools]}")

        # Verify baseline template was loaded
        train_py = workspace.read_file("train.py")
        assert train_py is not None, "Skill template should be loaded as train.py"
        print(f"Baseline template loaded: {len(train_py)} chars")

        conversation = create_conversation(agent, workspace, session)

        print("Sending task to agent...\n")
        conversation.send_message(question)
        conversation.run()

        # Results
        print(f"\n{'='*60}")
        print("RESULTS")
        print(f"{'='*60}")

        files = workspace.list_files()
        print(f"Workspace files: {files}")

        history = workspace.get_history()
        print(f"Git commits: {len(history)}")
        for h in history:
            print(f"  {h.hash[:8]} {h.message}")

        metrics_path = Path(output_dir) / "metrics.json"
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text())
            print(f"Metrics: {json.dumps(metrics, indent=2)}")
        else:
            print("No metrics.json produced (may be expected if script errored)")

        print(f"Tracker best: {tracker.best_value:.4f} ({tracker.primary_metric})")

        # Assert template was loaded
        assert "train.py" in files, f"Expected train.py, got: {files}"
        print("\nSKILL SMOKE TEST PASSED")


if __name__ == "__main__":
    test_smoke_skill()
