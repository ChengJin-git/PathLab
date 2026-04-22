"""Bridge between PathScientist runtime state and OpenHands agent_state persistence.

Tools call ``update_agent_state()`` to persist runtime metadata. On resume,
the ``resume`` module reads these values back to rebuild runtime objects.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openhands.sdk.conversation.impl.local_conversation import LocalConversation
    from ..tools.metrics import MetricsTracker
    from ..runtime.iteration_state import IterationState


def update_agent_state(conversation: LocalConversation, **patch: Any) -> None:
    """Merge key-value pairs into conversation.state.agent_state.

    OpenHands auto-persists to base_state.json on reassignment.
    Mutation alone does NOT trigger the ``__setattr__`` hook.
    """
    state = dict(conversation.state.agent_state)
    state.update(patch)
    conversation.state.agent_state = state


def read_agent_state(conversation: LocalConversation, key: str, default: Any = None) -> Any:
    """Read a value from persisted agent_state."""
    return conversation.state.agent_state.get(key, default)


def dump_tracker_state(tracker: MetricsTracker) -> dict[str, Any]:
    """Serialize MetricsTracker state for persistence."""
    return {
        "primary_metric": tracker.primary_metric,
        "best_value": tracker.best_value,
        "iteration": tracker.iteration,
        "history": tracker.history,
    }


def dump_iteration_state(iteration_state: IterationState) -> dict[str, Any]:
    """Serialize IterationState for persistence."""
    return {
        "max_iterations": iteration_state.max_iterations,
        "iteration_index": iteration_state.iteration_index,
        "remaining_budget": iteration_state.remaining_budget,
        "current_file_hash": iteration_state.current_file_hash,
        "last_validated_hash": iteration_state.last_validated_hash,
        "last_validated_path": iteration_state.last_validated_path,
        "last_quick_check_hash": iteration_state.last_quick_check_hash,
        "last_run_id": iteration_state.last_run_id,
        "history": iteration_state.history,
    }
