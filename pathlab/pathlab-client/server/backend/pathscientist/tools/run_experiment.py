"""RunExperiment tool — execute training scripts via SDK workspace."""
from __future__ import annotations

import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Self

from pydantic import Field

from openhands.sdk.llm import TextContent
from openhands.sdk.tool.schema import Action, Observation
from openhands.sdk.tool.tool import ToolAnnotations, ToolDefinition, ToolExecutor

if TYPE_CHECKING:
    from openhands.sdk.conversation import LocalConversation

    from ..runtime.workspace import Workspace


class RunExperimentAction(Action):
    script_path: str = Field(
        default="train.py",
        description="Script path relative to workspace root.",
    )
    quick_check: bool = Field(
        default=False,
        description="If true, run a 2-epoch validation (fast fail check).",
    )
    timeout: int = Field(
        default=600,
        description="Execution timeout in seconds.",
    )


class RunExperimentObservation(Observation):
    exit_code: int = Field(description="Process exit code (0 = success).")
    metrics: dict = Field(default_factory=dict, description="Parsed metrics from metrics.json.")
    duration: float = Field(default=0.0, description="Wall-clock seconds.")
    model_path: str | None = Field(default=None, description="Path to saved model, if any.")


class RunExperimentExecutor(ToolExecutor):
    def __init__(self, workspace: Workspace, config, session_id: str = ""):
        self._workspace = workspace
        self._config = config
        self._session_id = session_id

    def _get_iteration_state(self):
        if not self._session_id:
            return None
        try:
            from ..runtime.session_registry import get_session
            return get_session(self._session_id).iteration_state
        except (KeyError, AttributeError):
            return None

    def __call__(
        self,
        action: RunExperimentAction,
        conversation: "LocalConversation | None" = None,
    ) -> RunExperimentObservation:
        # Enforce iteration policy
        iteration_state = self._get_iteration_state()
        if iteration_state:
            import hashlib
            script_path = self._workspace.root / action.script_path
            if script_path.exists():
                file_hash = hashlib.md5(script_path.read_text().encode()).hexdigest()[:12]
            else:
                file_hash = ""

            try:
                from ..runtime.iteration_state import PolicyViolation
                if action.quick_check:
                    iteration_state.check_can_quick_check(file_hash)
                else:
                    iteration_state.check_can_full_run(file_hash)
            except PolicyViolation as e:
                return RunExperimentObservation(
                    exit_code=-1, metrics={}, duration=0.0,
                    content=[TextContent(text=f"Policy violation: {e}")],
                    is_error=True,
                )

        env_vars = {}
        if action.quick_check:
            env_vars["PATHLAB_QUICK_CHECK"] = "1"
            env_vars["PATHLAB_MAX_EPOCHS"] = "2"

        timeout = (
            self._config.quick_check_timeout if action.quick_check
            else action.timeout
        )

        # Per-run output directory for metrics isolation
        from uuid import uuid4
        run_id = uuid4().hex[:8]
        output_dir = self._config.resolve_output(self._workspace.root)
        run_dir = output_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        env_vars["OUTPUT_DIR"] = str(run_dir)

        # DATA_OUTPUT_DIR: stable user-visible output path for actual data
        # (features, model weights, etc). Scripts should write data artifacts
        # here instead of OUTPUT_DIR when they need a predictable location.
        # Falls back to OUTPUT_DIR if no data mounts configured.
        data_mounts = getattr(self._config, "data_mounts", {}) or {}
        data_output = None
        for host_path, container_path in data_mounts.items():
            if container_path in ("/output", "/results", "/data/output"):
                data_output = host_path
                break
        if data_output:
            env_vars["DATA_OUTPUT_DIR"] = data_output
        else:
            env_vars["DATA_OUTPUT_DIR"] = str(run_dir)

        start = time.time()
        result = self._workspace.run_script(
            script_path=action.script_path,
            env_vars=env_vars,
            timeout=float(timeout),
        )
        duration = time.time() - start

        # Only read metrics from THIS run's output dir, and only on success
        metrics = {}
        model_path = None
        if result.exit_code == 0:
            metrics_path = run_dir / "metrics.json"
            if metrics_path.exists():
                try:
                    metrics = json.loads(metrics_path.read_text())
                except Exception:
                    pass
            best_model = run_dir / "best_model.pth"
            if best_model.exists():
                model_path = str(best_model)

            # Copy metrics to output/latest/ for easy access
            latest = output_dir / "latest"
            latest.mkdir(parents=True, exist_ok=True)
            if metrics:
                (latest / "metrics.json").write_text(json.dumps(metrics, indent=2))

            # Update iteration policy — mark quick check as passed
            if action.quick_check and iteration_state and file_hash:
                iteration_state.mark_quick_check_passed(file_hash)

        # Build output text for LLM
        logs = result.stdout + result.stderr
        if len(logs) > 10000:
            logs = logs[:5000] + "\n...[truncated]...\n" + logs[-5000:]

        text = f"Exit code: {result.exit_code}\nDuration: {duration:.1f}s\n"
        if metrics:
            text += f"Metrics: {json.dumps(metrics, indent=2)}\n"
        if result.exit_code != 0:
            text += f"\nError output:\n{logs}"
            # Add structured error analysis with fix hints
            from ..error_classifier import format_error_analysis
            text += format_error_analysis(logs)
        elif logs:
            text += f"\nOutput (last 2000 chars):\n{logs[-2000:]}"

        return RunExperimentObservation(
            exit_code=result.exit_code,
            metrics=metrics,
            duration=duration,
            model_path=model_path,
            content=[TextContent(text=text)],
            is_error=result.exit_code != 0,
        )


class RunExperimentTool(ToolDefinition[RunExperimentAction, RunExperimentObservation]):
    name = "run_experiment"

    @classmethod
    def create(
        cls,
        conv_state=None,
        session_id: str = "",
        workspace=None,
        config=None,
        **params,
    ) -> Sequence[Self]:
        # Resolve from session registry if session_id provided
        if session_id and (workspace is None or config is None):
            from ..runtime.session_registry import get_session
            deps = get_session(session_id)
            workspace = workspace or deps.workspace
            config = config or deps.config
        return [
            cls(
                description=(
                    "Execute a training/experiment script in the workspace. "
                    "Set quick_check=true for a fast 2-epoch validation run before "
                    "the full experiment. Returns exit code, metrics, and logs."
                ),
                action_type=RunExperimentAction,
                observation_type=RunExperimentObservation,
                executor=RunExperimentExecutor(workspace, config, session_id=session_id),
                annotations=ToolAnnotations(
                    title="Run Experiment",
                    destructiveHint=False,
                    openWorldHint=False,
                ),
            )
        ]
