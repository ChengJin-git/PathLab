"""GetMetrics tool — read experiment results and history."""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Self

from pydantic import Field

from openhands.sdk.llm import TextContent
from openhands.sdk.tool.schema import Action, Observation
from openhands.sdk.tool.tool import ToolAnnotations, ToolDefinition, ToolExecutor

if TYPE_CHECKING:
    from openhands.sdk.conversation import LocalConversation

    from ..runtime.workspace import Workspace


class GetMetricsAction(Action):
    """No parameters needed — reads current state."""
    pass


class GetMetricsObservation(Observation):
    best_metric: float = Field(default=0.0, description="Best metric value so far.")
    best_metric_name: str = Field(default="auc", description="Name of the primary metric.")
    iteration: int = Field(default=0, description="Number of finalized metric-bearing iterations.")
    history: list[dict] = Field(default_factory=list, description="All iterations: metrics + status.")


class MetricsTracker:
    """Tracks experiment metrics across iterations."""

    def __init__(self, primary_metric: str = "auc"):
        self.primary_metric = primary_metric
        self.best_value: float = 0.0
        self.iteration: int = 0
        self.history: list[dict] = []

    def record(self, metrics: dict, committed: bool, iteration: int, run_id: str = "") -> None:
        from ..orchestrator.metrics_utils import resolve_primary_metric
        value = resolve_primary_metric(metrics, self.primary_metric)
        if committed and value > self.best_value:
            self.best_value = value
        self.history.append({
            "iteration": iteration,
            "metrics": metrics,
            "committed": committed,
            "run_id": run_id,
            f"best_{self.primary_metric}": self.best_value,
        })
        self.iteration = iteration


class GetMetricsExecutor(ToolExecutor):
    def __init__(self, tracker: MetricsTracker, session_id: str = ""):
        self._tracker = tracker
        self._session_id = session_id

    def _pending_last_experiment(self) -> dict:
        if not self._session_id:
            return {}
        try:
            from ..runtime.session_registry import get_session

            deps = get_session(self._session_id)
        except Exception:
            return {}
        exp = getattr(deps, "last_experiment", None) or {}
        if not isinstance(exp, dict):
            return {}
        metrics = exp.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            return {}
        return exp

    def _budget_status(self) -> tuple[int | None, int | None]:
        """Return ``(max_iterations, remaining_budget)`` when session state exists."""
        if not self._session_id:
            return None, None
        try:
            from ..runtime.session_registry import get_session

            deps = get_session(self._session_id)
        except Exception:
            return None, None
        iteration_state = getattr(deps, "iteration_state", None)
        if iteration_state is not None:
            return (
                getattr(iteration_state, "max_iterations", None),
                getattr(iteration_state, "remaining_budget", None),
            )
        config = getattr(deps, "config", None)
        return getattr(config, "max_iterations", None), None

    def __call__(
        self,
        action: GetMetricsAction,
        conversation: "LocalConversation | None" = None,
    ) -> GetMetricsObservation:
        # Plan-2026-04-29 P0 #1: compute effective best including the
        # pending last_experiment so the agent's commit decision sees
        # the latest successful full run, not just the tracker's
        # already-committed best. Pre-fix, get_metrics showed
        # `Best value: 0.8126` immediately after a full run achieved
        # 0.8166 — the agent could (and did) make commit decisions on
        # stale data (session_7a23f8edcce9 event-00161/00162).
        pending = self._pending_last_experiment()
        pending_metric: float | None = None
        pending_run_id = ""
        pending_is_clean_full_run = False
        pending_is_synthetic = False
        if pending:
            pending_run_id = pending.get("run_id", "")
            try:
                from ..orchestrator.metrics_utils import (
                    is_invalid_synthetic_run,
                    resolve_primary_metric,
                )
                pending_metric = float(
                    resolve_primary_metric(
                        pending.get("metrics") or {},
                        self._tracker.primary_metric,
                    )
                )
                pending_is_synthetic = is_invalid_synthetic_run(
                    pending.get("metrics") or {}
                )
            except Exception:
                pending_metric = None
            # Only treat the pending run as a candidate best when it
            # cleanly completed a full (non-quick_check) pass — failed
            # runs (exit_code != 0 or error_type set) and quick checks
            # must NOT influence the effective best.
            pending_is_clean_full_run = bool(
                pending.get("exit_code", 0) == 0
                and not pending.get("error_type", "")
                and not pending.get("quick_check", False)
                and not pending_is_synthetic
                and pending_metric is not None
                and pending_metric > 0.0
            )

        committed_best = self._tracker.best_value
        if pending_is_clean_full_run and pending_metric is not None:
            effective_best = max(committed_best, pending_metric)
        else:
            effective_best = committed_best

        completed_iterations = len(self._tracker.history)
        max_iterations, remaining_budget = self._budget_status()

        text = (
            f"Primary metric: {self._tracker.primary_metric}\n"
            f"Best value (committed): {committed_best:.4f}\n"
        )
        if effective_best != committed_best:
            text += (
                f"Best value (effective, includes pending): "
                f"{effective_best:.4f}  ← latest run beats committed best\n"
            )
        if max_iterations is not None:
            text += f"Completed iterations: {completed_iterations} / {max_iterations}\n"
        else:
            text += f"Completed iterations: {completed_iterations}\n"
        if remaining_budget is not None:
            status = (
                "exhausted"
                if remaining_budget <= 0
                else f"{remaining_budget} remaining"
            )
            text += f"Budget status: {status}\n"
        if self._tracker.history:
            text += f"Last finalized iteration index: {self._tracker.iteration}\n"
        text += f"History ({len(self._tracker.history)} entries):\n"
        for entry in self._tracker.history:
            text += f"  iter {entry['iteration']}: {entry['metrics']} "
            text += f"({'committed' if entry['committed'] else 'reverted'})\n"

        if pending:
            kind = (
                "INVALID synthetic_data" if pending_is_synthetic
                else "FAILED" if pending.get("exit_code", 0) != 0 or pending.get("error_type", "")
                else ("quick_check" if pending.get("quick_check") else "full run")
            )
            verdict = ""
            if pending_is_synthetic:
                verdict = (
                    " — invalid: synthetic/mock/demo data cannot be used as "
                    "a scientific best; fix data readiness and rerun on real data"
                )
            elif pending_is_clean_full_run and pending_metric is not None:
                if pending_metric > committed_best:
                    verdict = " — beats committed best, ratchet_commit would record a new best"
                else:
                    verdict = " — does not beat committed best; ratchet_revert is the right call"
            text += (
                f"\nPending last run (not yet ratcheted): "
                f"{pending_run_id} [{kind}] metrics={pending.get('metrics', {})}{verdict}\n"
            )

        return GetMetricsObservation(
            # Surface the effective best so callers (LLM included) see
            # the latest pending value when it's the new best. The old
            # committed-only behavior is still recoverable via tracker.history.
            best_metric=effective_best,
            best_metric_name=self._tracker.primary_metric,
            iteration=completed_iterations,
            history=self._tracker.history,
            content=[TextContent(text=text)],
        )


class GetMetricsTool(ToolDefinition[GetMetricsAction, GetMetricsObservation]):
    name = "get_metrics"

    @classmethod
    def create(cls, conv_state=None, session_id: str = "", tracker=None, **params) -> Sequence[Self]:
        if session_id and tracker is None:
            from ..runtime.session_registry import get_session
            tracker = get_session(session_id).tracker
        return [
            cls(
                description=(
                    "Get current experiment metrics: best metric value, "
                    "iteration count, and full history of all runs. "
                    "Use this to decide whether to commit or revert."
                ),
                action_type=GetMetricsAction,
                observation_type=GetMetricsObservation,
                executor=GetMetricsExecutor(tracker, session_id=session_id),
                annotations=ToolAnnotations(
                    title="Get Metrics",
                    readOnlyHint=True,
                    destructiveHint=False,
                    openWorldHint=False,
                ),
            )
        ]
