"""Resume a persisted PathScientist conversation.

Rebuilds all runtime dependencies (Workspace, MetricsTracker, IterationState,
SessionRegistry) from persisted ``agent_state``, then delegates to OpenHands
``ConversationState.create()`` for event log recovery and agent compatibility
verification.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import UUID, uuid4

from openhands.sdk.conversation import LocalConversation

from ..config import PathScientistConfig
from ..persistence.layout import get_persistence_root
from ..persistence.state_bridge import update_agent_state
from ..runtime.iteration_state import IterationState
from ..runtime.session import PathScientistSession
from ..runtime.session_registry import SessionDeps, register_session
from ..runtime.workspace import Workspace
from ..tools.metrics import MetricsTracker

logger = logging.getLogger(__name__)


def _read_agent_state_from_disk(conversation_dir: Path) -> dict:
    """Read agent_state from base_state.json without creating a full conversation."""
    base_state_path = conversation_dir / "base_state.json"
    if not base_state_path.exists():
        raise FileNotFoundError(f"No base_state.json found in {conversation_dir}")
    data = json.loads(base_state_path.read_text(encoding="utf-8"))
    return data.get("agent_state", {})


def _rebuild_tracker(agent_state: dict, config: PathScientistConfig) -> MetricsTracker:
    """Rebuild MetricsTracker from persisted tracker_state."""
    tracker_data = agent_state.get("tracker_state", {})
    primary_metric = tracker_data.get("primary_metric", config.primary_metric)
    tracker = MetricsTracker(primary_metric=primary_metric)
    tracker.best_value = tracker_data.get("best_value", 0.0)
    tracker.iteration = tracker_data.get("iteration", 0)
    tracker.history = tracker_data.get("history", [])
    return tracker


def _rebuild_iteration_state(agent_state: dict, config: PathScientistConfig) -> IterationState:
    """Rebuild IterationState from persisted iteration_state."""
    iter_data = agent_state.get("iteration_state", {})
    state = IterationState(
        max_iterations=iter_data.get("max_iterations", config.max_iterations),
    )
    state.iteration_index = iter_data.get("iteration_index", 0)
    state.remaining_budget = iter_data.get("remaining_budget", state.max_iterations)
    state.current_file_hash = iter_data.get("current_file_hash", "")
    state.last_validated_hash = iter_data.get("last_validated_hash", "")
    state.last_quick_check_hash = iter_data.get("last_quick_check_hash", "")
    state.last_run_id = iter_data.get("last_run_id", "")
    state.history = iter_data.get("history", [])
    return state


def resume_conversation(
    config: PathScientistConfig,
    conversation_id: UUID,
) -> tuple[LocalConversation, PathScientistSession]:
    """Resume a previously persisted PathScientist conversation.

    Rebuilds Workspace, MetricsTracker, IterationState, and SessionDeps
    from the persisted agent_state, then creates a LocalConversation in
    resume mode (OpenHands detects existing base_state.json).

    Returns (conversation, session).
    """
    from ..agent import create_agent

    # Resolve persistence root
    if config.conversation_persistence_dir:
        persistence_root = get_persistence_root(config.conversation_persistence_dir)
    else:
        from ..persistence.layout import get_persistence_root as _get_root
        base_dir = config.workspace_dir or "/project/vcompath/storage/ywangrm/tmp/pathscientist"
        # Walk up to the base dir (workspace_dir might be base/session_xxx)
        persistence_root = _get_root(Path(base_dir).parent if "session_" in str(base_dir) else base_dir)

    conversation_dir = persistence_root / conversation_id.hex

    # Read agent_state from disk before creating the conversation
    agent_state = _read_agent_state_from_disk(conversation_dir)

    # Resolve workspace from persisted state, falling back to config
    workspace_dir = agent_state.get("workspace_dir", config.workspace_dir)
    output_dir = agent_state.get("output_dir", config.output_dir)

    # Create a fresh session_id (process-local only)
    session_id = uuid4().hex[:12]
    session = PathScientistSession(
        session_id=session_id,
        conversation_id=conversation_id,
        research_question=agent_state.get("research_question", ""),
        workspace_dir=Path(workspace_dir),
        output_dir=Path(output_dir),
        persistence_root=persistence_root,
    )

    # Rebuild runtime dependencies
    workspace = Workspace(Path(workspace_dir))
    tracker = _rebuild_tracker(agent_state, config)
    iteration_state = _rebuild_iteration_state(agent_state, config)

    # Register session deps so tools can resolve via session_id
    register_session(session_id, SessionDeps(
        workspace=workspace,
        tracker=tracker,
        config=config,
        iteration_state=iteration_state,
    ))

    # Rebuild the agent (same tools, same LLM config)
    agent, _, _, _ = create_agent(config, research_question=session.research_question)

    # Create conversation — OpenHands detects base_state.json and enters resume mode
    conversation = LocalConversation(
        agent=agent,
        workspace=workspace.sdk_workspace,
        persistence_dir=str(persistence_root),
        conversation_id=conversation_id,
        stuck_detection=True,
        visualizer=None,
        delete_on_close=False,
        tags={
            "project": "pathscientist",
        },
    )

    # Store conversation in deps
    from ..runtime.session_registry import get_session
    deps = get_session(session_id)
    deps.conversation = conversation

    logger.info(
        f"Resumed conversation {conversation_id} "
        f"(iteration={iteration_state.iteration_index}, "
        f"best={tracker.best_value:.4f})"
    )

    return conversation, session
