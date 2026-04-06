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
    iteration: int = Field(default=0, description="Current iteration number.")
    history: list[dict] = Field(default_factory=list, description="All iterations: metrics + status.")


class MetricsTracker:
    """Tracks experiment metrics across iterations."""

    def __init__(self, primary_metric: str = "auc"):
        self.primary_metric = primary_metric
        self.best_value: float = 0.0
        self.iteration: int = 0
        self.history: list[dict] = []

    def record(self, metrics: dict, committed: bool, iteration: int) -> None:
        test_metrics = metrics.get("test", metrics)
        value = test_metrics.get(self.primary_metric, 0.0)
        if committed and value > self.best_value:
            self.best_value = value
        self.history.append({
            "iteration": iteration,
            "metrics": metrics,
            "committed": committed,
            f"best_{self.primary_metric}": self.best_value,
        })
        self.iteration = iteration


class GetMetricsExecutor(ToolExecutor):
    def __init__(self, tracker: MetricsTracker):
        self._tracker = tracker

    def __call__(
        self,
        action: GetMetricsAction,
        conversation: "LocalConversation | None" = None,
    ) -> GetMetricsObservation:
        text = (
            f"Primary metric: {self._tracker.primary_metric}\n"
            f"Best value: {self._tracker.best_value:.4f}\n"
            f"Iteration: {self._tracker.iteration}\n"
            f"History ({len(self._tracker.history)} entries):\n"
        )
        for entry in self._tracker.history:
            text += f"  iter {entry['iteration']}: {entry['metrics']} "
            text += f"({'committed' if entry['committed'] else 'reverted'})\n"

        return GetMetricsObservation(
            best_metric=self._tracker.best_value,
            best_metric_name=self._tracker.primary_metric,
            iteration=self._tracker.iteration,
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
                executor=GetMetricsExecutor(tracker),
                annotations=ToolAnnotations(
                    title="Get Metrics",
                    readOnlyHint=True,
                    destructiveHint=False,
                    openWorldHint=False,
                ),
            )
        ]
