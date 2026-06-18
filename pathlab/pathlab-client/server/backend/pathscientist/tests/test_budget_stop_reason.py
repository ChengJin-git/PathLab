"""Tests for budget overflow stop_reason enforcement.

Motivated by session_142a4acaed08 which had iteration_index=6,
max_iterations=5, stop_reason=""  — a budget overrun with no
persisted reason. The director had a local ``reason`` variable that
was logged but never assigned to ``state.stop_reason``.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os

os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

import types
from typing import Any

from pydantic import BaseModel, Field


def _install_openhands_stubs() -> None:
    """Provide the tiny SDK surface imported by lightweight tool modules."""

    try:
        import openhands.sdk.tool.schema  # noqa: F401
        import openhands.sdk.tool.tool  # noqa: F401
        import openhands.sdk.llm  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    if "openhands.sdk.tool.schema" in sys.modules:
        return

    openhands_mod = types.ModuleType("openhands")
    sdk_mod = types.ModuleType("openhands.sdk")
    llm_mod = types.ModuleType("openhands.sdk.llm")
    tool_pkg = types.ModuleType("openhands.sdk.tool")
    schema_mod = types.ModuleType("openhands.sdk.tool.schema")
    tool_mod = types.ModuleType("openhands.sdk.tool.tool")

    class TextContent(BaseModel):
        text: str = ""

    class Action(BaseModel):
        pass

    class Observation(BaseModel):
        content: list[Any] = Field(default_factory=list)
        is_error: bool = False

    class ToolExecutor:
        pass

    class ToolAnnotations(BaseModel):
        title: str = ""
        destructiveHint: bool = False
        openWorldHint: bool = False

    class ToolDefinition:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        def __class_getitem__(cls, _item):
            return cls

    llm_mod.TextContent = TextContent
    schema_mod.Action = Action
    schema_mod.Observation = Observation
    tool_mod.ToolExecutor = ToolExecutor
    tool_mod.ToolAnnotations = ToolAnnotations
    tool_mod.ToolDefinition = ToolDefinition
    tool_pkg.schema = schema_mod
    tool_pkg.tool = tool_mod
    sdk_mod.llm = llm_mod
    sdk_mod.tool = tool_pkg
    openhands_mod.sdk = sdk_mod

    sys.modules.setdefault("openhands", openhands_mod)
    sys.modules.setdefault("openhands.sdk", sdk_mod)
    sys.modules.setdefault("openhands.sdk.llm", llm_mod)
    sys.modules.setdefault("openhands.sdk.tool", tool_pkg)
    sys.modules.setdefault("openhands.sdk.tool.schema", schema_mod)
    sys.modules.setdefault("openhands.sdk.tool.tool", tool_mod)


_install_openhands_stubs()

from pathscientist.orchestrator.director import ResearchDirector
from pathscientist.orchestrator.types import (
    STAGE_EXECUTION,
    STAGE_REVIEW,
    STAGE_SYNTHESIS,
    ResearchObjective,
    ResearchSessionState,
)
from pathscientist.config import PathScientistConfig
from pathscientist.runtime.iteration_state import IterationState
from pathscientist.runtime.session_registry import (
    SessionDeps,
    register_session,
    remove_session,
)
from pathscientist.tools.metrics import MetricsTracker


@dataclass
class _FakeSession:
    session_id: str
    conversation_id: object
    workspace_dir: str
    persistence_root: Path


@dataclass
class _FakeConversationState:
    events: list = field(default_factory=list)


class _FakeConversation:
    def __init__(self):
        self.state = _FakeConversationState()
        self.sent_messages: list[str] = []

    def send_message(self, text: str) -> None:
        self.sent_messages.append(text)

    def run(self) -> None:
        pass


@dataclass
class _FakeWorkspace:
    root: Path


def _make_runner_test_context(tmp_path: Path):
    session_id = f"test_budget_{uuid4().hex[:8]}"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    session = _FakeSession(
        session_id=session_id,
        conversation_id=uuid4(),
        workspace_dir=str(workspace_dir),
        persistence_root=tmp_path,
    )
    conversation = _FakeConversation()
    config = PathScientistConfig(
        workspace_dir=str(workspace_dir),
        output_dir=str(tmp_path / "output"),
        gpu_ids=[],
        sandbox_mode="local",
        max_iterations=5,
        primary_metric="auc",
        conversation_persistence_dir=str(tmp_path),
        auto_acquire_data=False,
    )
    deps = SessionDeps(
        workspace=_FakeWorkspace(workspace_dir),
        tracker=MetricsTracker(primary_metric="auc"),
        config=config,
        iteration_state=IterationState(max_iterations=5),
        conversation=conversation,
    )
    register_session(session_id, deps)
    return config, session, conversation, deps, lambda: remove_session(session_id)


def _make_review_state(**overrides) -> ResearchSessionState:
    """Build a state parked at STAGE_REVIEW, ready for director to route."""
    defaults = dict(
        session_id="sess_budget",
        conversation_id=uuid4(),
        objective=ResearchObjective(question="Improve AUC on BRACS"),
    )
    defaults.update(overrides)
    state = ResearchSessionState.create(**defaults)
    state.stage = STAGE_REVIEW
    state.max_iterations = 5
    state.iteration_index = state.max_iterations
    return state


def test_exact_budget_sets_stop_reason():
    """When iteration_index == max_iterations, director must persist
    ``state.stop_reason='budget_exhausted'`` on the review -> synthesis
    transition, not merely log a local ``reason`` variable.
    """
    director = ResearchDirector(auto_approve=True)
    state = _make_review_state()
    assert state.stop_reason == ""  # precondition

    updated = director.advance(state)

    assert updated.stage == STAGE_SYNTHESIS
    assert updated.stop_reason == "budget_exhausted"


def test_overrun_forces_stop_reason_in_runner(tmp_path, monkeypatch):
    """When iteration_index > max_iterations (e.g. due to a resumed or
    otherwise mis-advanced session), the runner's belt-and-suspenders
    safety net must force stop_reason='budget_exhausted' before entering
    the synthesis stage.
    """
    from pathscientist.orchestrator import runner as runner_module
    from pathscientist.orchestrator.runner import continue_research_session

    config, session, conversation, _deps, cleanup = _make_runner_test_context(tmp_path)

    state = ResearchSessionState.create(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        objective=ResearchObjective(question="Overrun check"),
    )
    # Park the state directly at SYNTHESIS with an illegal overrun and
    # NO stop_reason — mimics a resumed / mis-advanced session.
    state.stage = STAGE_SYNTHESIS
    state.max_iterations = 5
    state.iteration_index = state.max_iterations + 2
    state.stop_reason = ""

    # Capture the stop_reason observed by _run_synthesis_stage at entry.
    captured: dict[str, str] = {}

    def fake_synthesis(state_arg, *args, **kwargs):
        captured["stop_reason"] = state_arg.stop_reason
        return state_arg

    monkeypatch.setattr(runner_module, "_run_synthesis_stage", fake_synthesis)
    # build_session_summary is touched right after synthesis — keep it cheap.
    monkeypatch.setattr(
        "pathscientist.orchestrator.runner.build_session_summary",
        lambda *args, **kwargs: "",
    )
    monkeypatch.setattr(
        "pathscientist.orchestrator.runner.build_ui_run_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(runner_module, "persist_research_session_state", lambda *a, **kw: None)
    monkeypatch.setattr(runner_module, "_run_integrity_check", lambda *a, **kw: None)

    try:
        continue_research_session(
            config,
            state,
            session,
            conversation,
            auto_approve=True,
        )
    finally:
        cleanup()

    # The runner's safety net must have force-set budget_exhausted BEFORE
    # calling _run_synthesis_stage.
    assert captured.get("stop_reason") == "budget_exhausted"
    assert state.stop_reason == "budget_exhausted"


def test_explicit_stop_reason_preserved():
    """If stop_reason is already set (e.g. 'user_cancelled'), the director
    must not overwrite it with 'budget_exhausted', even if the iteration
    budget has been exceeded.
    """
    director = ResearchDirector(auto_approve=True)
    state = _make_review_state()
    state.stop_reason = "user_cancelled"

    updated = director.advance(state)

    assert updated.stage == STAGE_SYNTHESIS
    assert updated.stop_reason == "user_cancelled"


def test_over_budget_skips_next_execution(tmp_path, monkeypatch):
    """A single ``conversation.run()`` can finalize many iterations in one
    turn; before the fix the resulting ``iteration_index`` shot far past
    ``max_iterations`` because the runner faithfully incremented for every
    new tracker history entry with no per-turn cap. Reproduces
    session_b14b074d2268 which had max_iterations=5 but iteration_index=17
    because the agent ratcheted 17 times inside a single agent turn and the
    runner only re-checked the budget at ``REVIEW`` — far too late.

    After the fix:
    - ``iteration_index`` is capped at ``max_iterations`` per run
    - ``stop_reason='budget_exhausted'`` is set the moment the runner drops
      an over-budget ratchet entry
    - the next ``while state.stage == STAGE_EXECUTION:`` iteration does NOT
      start another execution turn (director routes REVIEW → SYNTHESIS)
    """
    from pathscientist.orchestrator import runner as runner_module
    from pathscientist.orchestrator.runner import continue_research_session
    from pathscientist.orchestrator.types import STAGE_EXECUTION

    config, session, conversation, deps, cleanup = _make_runner_test_context(tmp_path)

    state = ResearchSessionState.create(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        objective=ResearchObjective(question="Budget overrun check"),
    )
    state.stage = STAGE_EXECUTION
    state.max_iterations = 5
    state.iteration_index = 0

    # Fake agent turn: one ``conversation.run()`` appends MANY new tracker
    # entries, mimicking a buggy / greedy agent that calls ratchet_commit
    # 17 times in a single turn. Count how many turns the runner launches.
    AGENT_RATCHETS_PER_TURN = 17
    turn_counter = {"turns": 0}

    def fake_run():
        turn_counter["turns"] += 1
        for i in range(AGENT_RATCHETS_PER_TURN):
            deps.tracker.history.append({
                "run_id": f"run_{turn_counter['turns']:03d}_{i:03d}",
                "metrics": {"auc": 0.5 + 0.001 * len(deps.tracker.history)},
                "committed": True,
            })

    monkeypatch.setattr(conversation, "run", fake_run)

    # Short-circuit synthesis so the test focuses on the execution loop.
    def fake_synthesis(state_arg, *args, **kwargs):
        return state_arg

    monkeypatch.setattr(runner_module, "_run_synthesis_stage", fake_synthesis)
    monkeypatch.setattr(runner_module, "_run_integrity_check", lambda *a, **kw: None)
    monkeypatch.setattr(
        "pathscientist.orchestrator.runner.build_session_summary",
        lambda *args, **kwargs: "",
    )
    monkeypatch.setattr(
        "pathscientist.orchestrator.runner.build_ui_run_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(runner_module, "persist_research_session_state", lambda *a, **kw: None)

    try:
        final_state, _, _ = continue_research_session(
            config,
            state,
            session,
            conversation,
            auto_approve=True,
        )
    finally:
        cleanup()

    # Runner must have pumped EXACTLY one execution turn — the single turn
    # that overshot budget. No second execution turn is allowed because the
    # first already set stop_reason='budget_exhausted' and the director
    # routes REVIEW → SYNTHESIS. Before the fix, iteration_index would have
    # reached AGENT_RATCHETS_PER_TURN (17) with no cap.
    assert turn_counter["turns"] == 1, (
        f"expected exactly 1 execution turn, got {turn_counter['turns']} "
        f"(budget halt is not enforced)"
    )
    assert final_state.iteration_index == state.max_iterations, (
        f"iteration_index must be capped at max_iterations "
        f"({state.max_iterations}), got {final_state.iteration_index}"
    )
    assert final_state.stop_reason == "budget_exhausted"
    assert final_state.stage != STAGE_EXECUTION


def test_budget_stop_does_not_skip_pending_external_test():
    """A queued external_test must still run after training exhausts budget."""
    director = ResearchDirector(auto_approve=True)
    state = _make_review_state()
    state.stop_reason = "budget_exhausted"
    state.execution_plan = {
        "current_step": 0,
        "steps": [{"id": "external", "skill": "external_test"}],
    }

    updated = director.advance(state)

    assert updated.stage == STAGE_EXECUTION
    assert updated.stop_reason == "budget_exhausted"


def test_stall_stop_does_not_skip_pending_external_test():
    """Stall limit should not silently drop a user-requested external_test."""
    director = ResearchDirector(auto_approve=True)
    state = _make_review_state()
    state.stop_reason = "stall_limit"
    state.execution_plan = {
        "current_step": 0,
        "steps": [{"id": "external", "skill": "external_test"}],
    }

    updated = director.advance(state)

    assert updated.stage == STAGE_EXECUTION
    assert updated.stop_reason == "stall_limit"


def test_user_stop_still_skips_pending_external_test():
    """Explicit user stops must still route directly to synthesis."""
    director = ResearchDirector(auto_approve=True)
    state = _make_review_state()
    state.stop_reason = "user_cancelled"
    state.execution_plan = {
        "current_step": 0,
        "steps": [{"id": "external", "skill": "external_test"}],
    }

    updated = director.advance(state)

    assert updated.stage == STAGE_SYNTHESIS
    assert updated.stop_reason == "user_cancelled"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
