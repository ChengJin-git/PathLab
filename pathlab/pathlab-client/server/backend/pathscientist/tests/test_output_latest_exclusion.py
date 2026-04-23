"""Regression for Finding 4 of
``docs/review/2026-04-22-pathscientist-session-8e48c15d38cb-review-results.md``.

Before the fix, ``RunExperimentTool`` copied metrics into
``output/latest/metrics.json`` for every successful run, including
quick_check ones. Session_8e48c15d38cb ended up with
``output/latest/metrics.json`` holding ``auc=0.8643, epochs=2`` (quick
check) while ``results/metrics.json`` (agent-side) held the real full
run ``auc=0.8436, epochs=50`` — two authoritative-looking surfaces
disagreeing by 2pp.

The fix skips the ``output/latest/`` copy when ``action.quick_check`` is
True, so "latest" only ever reflects the most recent non-provisional run.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from openhands.sdk.workspace.models import CommandResult

from pathscientist.config import PathScientistConfig
from pathscientist.runtime.iteration_state import IterationState
from pathscientist.runtime.session_registry import (
    SessionDeps,
    register_session,
    remove_session,
)
from pathscientist.runtime.workspace import Workspace
from pathscientist.tools.metrics import MetricsTracker
from pathscientist.tools.run_experiment import (
    RunExperimentAction,
    RunExperimentExecutor,
)


class _StubWorkspace:
    """Workspace stand-in that side-writes metrics.json into OUTPUT_DIR.

    run_experiment reads ``<run_dir>/metrics.json`` after the subprocess
    returns (to populate last_experiment["metrics"]). We emulate that
    write so the code path that copies to ``output/latest/`` actually
    fires — this is what we're asserting on.
    """

    def __init__(self, real_workspace, metrics: dict):
        self._real = real_workspace
        self.root = real_workspace.root
        self._metrics = metrics

    def run_script(self, script_path, env_vars=None, timeout=600.0):
        env = env_vars or {}
        out_dir = env.get("OUTPUT_DIR")
        if out_dir:
            p = Path(out_dir)
            p.mkdir(parents=True, exist_ok=True)
            (p / "metrics.json").write_text(json.dumps(self._metrics))
        return CommandResult(
            command=f"python {script_path}",
            exit_code=0,
            stdout="",
            stderr="",
            timeout_occurred=False,
        )


def _register(tmp_path: Path, metrics: dict) -> tuple[str, SessionDeps, _StubWorkspace, object]:
    ws_dir = tmp_path / "workspace"
    real_ws = Workspace(ws_dir)
    train_src = (
        'import json, os\n'
        'from pathlib import Path\n'
        'def main():\n'
        '    p = Path(os.environ["OUTPUT_DIR"])\n'
        '    p.mkdir(parents=True, exist_ok=True)\n'
        '    (p / "metrics.json").write_text(json.dumps({"auc": 0.5}))\n'
        'if __name__ == "__main__":\n'
        '    main()\n'
    )
    real_ws.write_file("train.py", train_src)
    real_ws.commit("baseline")

    stub = _StubWorkspace(real_ws, metrics)
    iteration_state = IterationState(max_iterations=5)
    # Pre-authorize this train.py hash so the F1 validate→run handoff gate
    # doesn't refuse the call. In a real session the agent would have run
    # validate_script right before run_experiment; we inline that hash write
    # so these tests stay focused on the output/latest/ copy behavior.
    import hashlib
    # run_experiment/validate_script both use md5 truncated to 12 hex chars.
    h12 = hashlib.md5(
        (ws_dir / "train.py").read_text().encode()
    ).hexdigest()[:12]
    iteration_state.last_validated_hash = h12
    iteration_state.last_validated_path = "train.py"
    iteration_state.current_file_hash = h12
    # Full runs require a prior quick_check for the same hash; inline that too.
    iteration_state.last_quick_check_hash = h12

    config = PathScientistConfig(
        workspace_dir=str(ws_dir),
        output_dir=str(tmp_path / "output"),
        gpu_ids=[],
        sandbox_mode="local",
        max_iterations=5,
        primary_metric="auc",
        conversation_persistence_dir=str(tmp_path),
    )
    deps = SessionDeps(
        workspace=stub,
        tracker=MetricsTracker(primary_metric="auc"),
        config=config,
        iteration_state=iteration_state,
        conversation=None,
    )
    sid = f"test_latest_{tmp_path.name}"
    register_session(sid, deps)
    return sid, deps, stub, lambda: remove_session(sid)


def _run(session_id: str, workspace, config, *, quick_check: bool):
    executor = RunExperimentExecutor(
        workspace=workspace, config=config, session_id=session_id,
    )
    return executor(RunExperimentAction(
        script_path="train.py", quick_check=quick_check, timeout=60,
    ))


def test_full_run_copies_metrics_to_output_latest(tmp_path):
    """A non-quick_check run must populate output/latest/metrics.json so
    the next turn can inspect the most recent authoritative result."""
    sid, deps, stub, cleanup = _register(tmp_path, {"auc": 0.85, "epochs": 50})
    try:
        _run(sid, stub, deps.config, quick_check=False)
        latest = Path(deps.config.output_dir) / "latest" / "metrics.json"
        assert latest.exists(), (
            f"output/latest/metrics.json must exist for non-quick_check runs; "
            f"output_dir contents: {list(Path(deps.config.output_dir).iterdir())}"
        )
        assert json.loads(latest.read_text())["auc"] == 0.85
    finally:
        cleanup()


def test_quick_check_run_does_not_overwrite_output_latest(tmp_path):
    """A quick_check run must NOT write to output/latest/ — otherwise a
    2-epoch sanity check gets promoted to the session's latest
    authoritative result (the F4 failure mode)."""
    sid, deps, stub, cleanup = _register(tmp_path, {"auc": 0.86, "epochs": 2})
    try:
        _run(sid, stub, deps.config, quick_check=True)
        latest = Path(deps.config.output_dir) / "latest" / "metrics.json"
        assert not latest.exists(), (
            "output/latest/metrics.json must NOT exist after a quick_check "
            "run — quick-check results cannot be promoted to 'latest'. "
            f"Found: {latest.read_text() if latest.exists() else '(absent)'}"
        )
    finally:
        cleanup()


def test_quick_check_does_not_overwrite_existing_latest(tmp_path):
    """Reproduces the exact F4 failure mode: a full run lands latest=0.84,
    then a subsequent quick_check produces a better-looking 0.86. The
    quick_check must leave the full-run value in place, not clobber it."""
    sid, deps, stub, cleanup = _register(tmp_path, {"auc": 0.84, "epochs": 50})
    try:
        _run(sid, stub, deps.config, quick_check=False)
        latest = Path(deps.config.output_dir) / "latest" / "metrics.json"
        assert latest.exists()
        assert json.loads(latest.read_text())["auc"] == 0.84

        # Now a quick_check with a misleadingly-better number.
        stub._metrics = {"auc": 0.86, "epochs": 2}
        _run(sid, stub, deps.config, quick_check=True)

        # Latest must STILL be the full run's 0.84, not the quick_check's 0.86.
        assert json.loads(latest.read_text())["auc"] == 0.84, (
            "Latest snapshot was clobbered by a quick_check — this is the "
            "exact F4 bug from session_8e48c15d38cb."
        )
    finally:
        cleanup()
