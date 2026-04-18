"""Tests for budget overflow stop_reason enforcement.

Motivated by session_142a4acaed08 which had iteration_index=6,
max_iterations=5, stop_reason=""  — a budget overrun with no
persisted reason. The director had a local ``reason`` variable that
was logged but never assigned to ``state.stop_reason``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os

os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from pathscientist.orchestrator.director import ResearchDirector
from pathscientist.orchestrator.types import (
    STAGE_REVIEW,
    STAGE_SYNTHESIS,
    ResearchObjective,
    ResearchSessionState,
)


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
    sys.path.insert(0, str(Path(__file__).parent))
    from persistence_helpers import build_test_conversation, make_test_config

    from pathscientist.orchestrator import runner as runner_module
    from pathscientist.orchestrator.runner import continue_research_session

    conversation, session = build_test_conversation(tmp_path)
    config = make_test_config(tmp_path)

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

    continue_research_session(
        config,
        state,
        session,
        conversation,
        auto_approve=True,
    )

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


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
