"""Regression tests for AutoResearch code agent runtime correctness.

These tests expose bugs that must be fixed before the agent is production-safe:
1. Workspace isolation: same question must create distinct workspaces
2. Stale metrics: failed run must not reuse previous metrics.json
3. Metrics history: tracker must reflect real commit/revert outcomes
4. Quick check policy: full run must require prior quick check pass
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

import pytest

from autoresearch.config import AutoResearchConfig
from autoresearch.tools.metrics import MetricsTracker


# ---- Test 1: Session isolation ----

def test_same_question_creates_distinct_session_workspaces():
    """Two sessions for the same question must get different workspace dirs."""
    cfg = AutoResearchConfig(sandbox_mode="local")
    ws_a = cfg.resolve_workspace("same question")
    ws_b = cfg.resolve_workspace("same question")
    # BUG: both resolve to ws_{same_hash} — they collide
    assert ws_a != ws_b, (
        f"Same question produced identical workspace: {ws_a}. "
        "Sessions must be isolated even for the same research question."
    )


# ---- Test 2: Stale metrics ----

def test_failed_run_does_not_reuse_previous_metrics():
    """A failed experiment must return empty metrics, not stale ones."""
    with tempfile.TemporaryDirectory(prefix="stale_metrics_") as tmpdir:
        ws_dir = Path(tmpdir) / "workspace"
        ws_dir.mkdir()
        out_dir = Path(tmpdir) / "output"
        out_dir.mkdir()

        # Simulate a previous successful run that left metrics.json
        old_metrics = {"test": {"auc": 0.9, "accuracy": 0.85}}
        (out_dir / "metrics.json").write_text(json.dumps(old_metrics))

        # Write a script that fails
        (ws_dir / "train.py").write_text("raise RuntimeError('crash')\n")

        from autoresearch.runtime.workspace import Workspace
        workspace = Workspace(ws_dir)

        from autoresearch.tools.run_experiment import RunExperimentExecutor

        class FakeConfig:
            quick_check_timeout = 30
            def resolve_output(self, ws): return out_dir

        executor = RunExperimentExecutor(workspace, FakeConfig())
        from autoresearch.tools.run_experiment import RunExperimentAction
        obs = executor(RunExperimentAction(script_path="train.py", timeout=10))

        # BUG: executor reads out_dir/metrics.json which still has old data
        assert obs.exit_code != 0, "Script should have crashed"
        assert obs.metrics == {}, (
            f"Failed run returned stale metrics: {obs.metrics}. "
            "Must return empty dict when the run itself failed."
        )


def test_run_experiment_passes_deduped_data_mounts_to_workspace(tmp_path):
    from autoresearch.tools.run_experiment import RunExperimentAction, RunExperimentExecutor
    from autoresearch.runtime.sandbox import SandboxResult

    workspace_root = tmp_path / "autoresearch_sessions" / "session_abc"
    output_root = workspace_root / "output"
    current_contract = workspace_root / ".dataset" / "pathlab_registered" / "nanfang_contract"
    stale_contract = tmp_path / "pathlab_datasets" / "session_inputs" / "old" / "nanfang_contract"
    current_contract.mkdir(parents=True)
    stale_contract.mkdir(parents=True)
    output_root.mkdir(parents=True)
    (workspace_root / "train.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    captured = {}

    class FakeWorkspace:
        root = workspace_root

        def run_script(self, *_, data_mounts=None, **__):
            captured["data_mounts"] = dict(data_mounts or {})
            return SandboxResult(exit_code=1, stdout="", stderr="failed")

    class FakeConfig:
        quick_check_timeout = 30
        execution_timeout = 30
        data_mounts = {
            str(stale_contract): "/data/nanfang_contract",
            str(current_contract): "/data/nanfang_contract",
        }

        def resolve_output(self, _ws):
            return output_root

    executor = RunExperimentExecutor(FakeWorkspace(), FakeConfig())
    obs = executor(RunExperimentAction(script_path="train.py", timeout=10))

    assert obs.exit_code != 0
    assert captured["data_mounts"] == {str(current_contract): "/data/nanfang_contract"}


# ---- Test 3: Metrics history ----

def test_metrics_tool_reflects_real_history_after_commit_and_revert():
    """MetricsTracker.record() must be called by ratchet tools."""
    tracker = MetricsTracker(primary_metric="auc")

    # Simulate: iteration 0 committed with auc=0.8
    tracker.record({"test": {"auc": 0.8}}, committed=True, iteration=0)
    assert tracker.best_value == 0.8
    assert len(tracker.history) == 1

    # Simulate: iteration 1 reverted (no improvement)
    tracker.record({"test": {"auc": 0.7}}, committed=False, iteration=1)
    assert tracker.best_value == 0.8  # unchanged
    assert len(tracker.history) == 2
    assert tracker.history[1]["committed"] is False

    # This test passes if record() works correctly.
    # The real bug is that ratchet_commit/ratchet_revert tools
    # don't call tracker.record() — that's tested by smoke tests.


# ---- Test 4: Quick check policy ----

def test_full_run_requires_quick_check_for_current_revision():
    """Runtime should reject a full run if quick check hasn't passed for current code."""
    # This test documents the desired behavior.
    # Currently the runtime does NOT enforce this — it's prompt-only.
    # After Task 5, this should be enforced by IterationState.

    # For now, just verify the config has the right defaults
    cfg = AutoResearchConfig()
    assert cfg.quick_check_timeout > 0, "Quick check must be enabled by default"
    assert cfg.max_iterations > 0, "Must have iteration budget"

    # TODO: After Task 5, add runtime enforcement test:
    # state = IterationState(max_iterations=5)
    # with pytest.raises(PolicyViolation):
    #     state.allow_full_run("train.py")  # no quick check yet


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
