"""Tests for the relaxed stall detection rules (Finding 6, 2026-04-22 review).

Before the fix, ``MAX_CONSECUTIVE_STALLS = 2`` and every non-finalized turn
incremented ``stall_count``, so a normal post-commit ``think → edit``
sequence killed session_3f1795098784 at ``iteration_index=1`` of a
5-iteration budget.

After the fix, the runner keeps two counters:

- ``consecutive_idle_turns`` — turns with no ``ActionEvent`` at all
- ``consecutive_non_finalized_turns`` — turns that called tools but did
  not ratchet

A stall is declared when ``consecutive_idle_turns >= MAX_IDLE_TURNS``
(default 2) OR ``consecutive_non_finalized_turns >= MAX_NON_FINALIZED_TURNS``
(default 6). Either counter resets to zero on a successful
``ratchet_commit`` / ``ratchet_revert``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from pathscientist.orchestrator.types import (
    MAX_IDLE_TURNS,
    MAX_NON_FINALIZED_TURNS,
    STAGE_EXECUTION,
    ResearchObjective,
    ResearchSessionState,
)


def _make_execution_state(**overrides) -> ResearchSessionState:
    defaults = dict(
        session_id="sess_stall",
        conversation_id=uuid4(),
        objective=ResearchObjective(question="Improve AUC on BRACS"),
    )
    defaults.update(overrides)
    state = ResearchSessionState.create(**defaults)
    state.stage = STAGE_EXECUTION
    state.max_iterations = 5
    return state


class _StopExecutionLoop(Exception):
    """Sentinel exception raised to exit the runner's execution while loop.

    The runner's ``while state.stage == STAGE_EXECUTION`` loop only ends
    when the director moves the stage off EXECUTION or when the stall
    guard trips. Tests that want to stop after a specific number of
    scripted turns raise this marker — the helper catches it and returns
    the state as-is, preserving everything the runner stamped onto it.
    """


def _run_execution_loop(
    *,
    tmp_path: Path,
    monkeypatch,
    turn_script,
    max_iterations: int = 5,
    initial_iteration_index: int = 0,
):
    """Drive ``continue_research_session`` through a scripted sequence of
    agent turns and return the final state + how many turns actually ran.

    ``turn_script`` is a list of callables. Each callable is invoked on one
    ``conversation.run()`` call and receives ``(conversation, tracker)``; it
    decides what happens on that turn (append tracker entries, push
    ActionEvent fakes, or do nothing at all).

    When the script is exhausted, the helper raises ``_StopExecutionLoop``
    so tests can pin down exactly how many turns ran — otherwise the
    runner would keep pumping no-op turns (which, post-fix, look idle and
    eventually trip the idle-turn guard, obscuring the thing under test).

    ``synthesis`` / ``integrity`` are short-circuited so only the
    execution loop is exercised.
    """
    from persistence_helpers import build_test_conversation, make_test_config

    from pathscientist.orchestrator import runner as runner_module
    from pathscientist.orchestrator.runner import continue_research_session
    from pathscientist.runtime.session_registry import get_session

    conversation, session = build_test_conversation(tmp_path)
    config = make_test_config(tmp_path)
    deps = get_session(session.session_id)

    state = _make_execution_state(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
    )
    state.max_iterations = max_iterations
    state.iteration_index = initial_iteration_index

    turn_counter = {"turns": 0}

    def fake_send_message(msg):
        return None

    def fake_run():
        idx = turn_counter["turns"]
        if idx >= len(turn_script):
            # Script exhausted — bail out instead of running phantom no-op
            # turns that would pollute the stall counters.
            raise _StopExecutionLoop()
        turn_counter["turns"] += 1
        turn_script[idx](conversation, deps.tracker)

    monkeypatch.setattr(conversation, "send_message", fake_send_message)
    monkeypatch.setattr(conversation, "run", fake_run)
    monkeypatch.setattr(runner_module, "_run_synthesis_stage", lambda s, *a, **kw: s)
    monkeypatch.setattr(runner_module, "_run_integrity_check", lambda *a, **kw: None)
    monkeypatch.setattr(
        "pathscientist.orchestrator.runner.build_session_summary",
        lambda *a, **kw: "",
    )

    try:
        final_state, _, _ = continue_research_session(
            config,
            state,
            session,
            conversation,
            auto_approve=True,
        )
    except _StopExecutionLoop:
        final_state = state
    return final_state, turn_counter["turns"]


def _make_action_event():
    """Build a minimal ``ActionEvent`` for stall-detection tests.

    The stall counter only cares that ``isinstance(event, ActionEvent)`` is
    true; field values are irrelevant for the counter logic.
    """
    from openhands.sdk.event import ActionEvent
    from openhands.sdk.llm import MessageToolCall

    return ActionEvent(
        thought=[],
        tool_name="think",
        tool_call_id="tc_test",
        tool_call=MessageToolCall(
            id="tc_test",
            name="think",
            arguments="{}",
            origin="completion",
        ),
        llm_response_id="llm_test",
    )


# ---------------------------------------------------------------------------
# Unit-level tests on the helpers themselves — they don't need a conversation.
# ---------------------------------------------------------------------------


def test_finalized_turn_resets_stall_count():
    """When the runner sees the tracker grow, both counters drop to zero."""
    from pathscientist.orchestrator.runner import _reset_stall_counters

    state = _make_execution_state()
    state.consecutive_idle_turns = 1
    state.consecutive_non_finalized_turns = 3
    state.stall_count = 3

    _reset_stall_counters(state)

    assert state.consecutive_idle_turns == 0
    assert state.consecutive_non_finalized_turns == 0
    assert state.stall_count == 0


def test_bump_stall_counters_tracks_both_flavours():
    """_bump_stall_counters advances the right counter and keeps stall_count
    as the max, preserving the legacy field for older consumers."""
    from pathscientist.orchestrator.runner import _bump_stall_counters

    state = _make_execution_state()

    # Two productive-but-unfinalized turns — non-finalized goes up.
    _bump_stall_counters(state, idle=False)
    _bump_stall_counters(state, idle=False)
    assert state.consecutive_idle_turns == 0
    assert state.consecutive_non_finalized_turns == 2
    assert state.stall_count == 2

    # One idle turn — idle goes up, non-finalized keeps its prior value.
    _bump_stall_counters(state, idle=True)
    assert state.consecutive_idle_turns == 1
    assert state.consecutive_non_finalized_turns == 2
    assert state.stall_count == 2


def test_stall_limit_reached_honours_both_thresholds():
    """Either counter crossing its threshold must trip the guard.

    The idle-turn threshold is deliberately tighter than the
    non-finalized-turn threshold (default 2 vs 6) because a truly idle
    agent is the unambiguous "frozen" case — but we still want working
    turns to have plenty of room.
    """
    from pathscientist.orchestrator.runner import _stall_limit_reached

    # idle threshold triggers
    s = _make_execution_state()
    s.consecutive_idle_turns = MAX_IDLE_TURNS
    assert _stall_limit_reached(s) is True

    # non-finalized threshold triggers
    s = _make_execution_state()
    s.consecutive_non_finalized_turns = MAX_NON_FINALIZED_TURNS
    assert _stall_limit_reached(s) is True

    # Below both thresholds — no stall.
    s = _make_execution_state()
    s.consecutive_idle_turns = MAX_IDLE_TURNS - 1
    s.consecutive_non_finalized_turns = MAX_NON_FINALIZED_TURNS - 1
    assert _stall_limit_reached(s) is False


# ---------------------------------------------------------------------------
# Integration tests — exercise the runner's execution loop end-to-end.
# ---------------------------------------------------------------------------


def test_non_finalized_working_turn_does_not_stall_immediately(tmp_path, monkeypatch):
    """Agent runs 3-4 turns of tool activity without ratcheting. Under the
    old rule this was a stall at turn 2; now it is well within the
    non-finalized budget of 6."""

    def working_turn(conversation, tracker):
        # Simulate tool activity (think / validate / edit) — append an
        # ActionEvent but do NOT append to tracker.history.
        conversation.state.events.append(_make_action_event())

    # 4 productive turns, zero ratchets — stall must not fire yet.
    script = [working_turn] * 4

    final_state, turns_run = _run_execution_loop(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        turn_script=script,
        max_iterations=5,
    )

    assert final_state.consecutive_non_finalized_turns == 4
    assert final_state.consecutive_idle_turns == 0
    assert final_state.stall_count == 4
    # 4 working turns is still below non-finalized threshold — session keeps
    # the execution loop alive. Runner must not force stall_limit.
    assert final_state.stop_reason != "stall_limit"
    assert turns_run == 4


def test_true_idle_turns_eventually_stall(tmp_path, monkeypatch):
    """A truly frozen agent — zero tool calls, no ratchets — must still
    trip the stall guard, but it should take at least ``MAX_IDLE_TURNS``
    idle turns (default 2). The guard fires on the THIRD iteration of the
    execution loop: the first two idle turns each bump the counter; the
    third iteration sees ``consecutive_idle_turns >= MAX_IDLE_TURNS`` and
    transitions to synthesis without pumping another agent turn.
    """

    def idle_turn(conversation, tracker):
        # Zero tracker entries, zero ActionEvents. Pure idle.
        return

    script = [idle_turn] * 10  # Plenty of idle turns available.

    final_state, turns_run = _run_execution_loop(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        turn_script=script,
        max_iterations=5,
    )

    assert final_state.stop_reason == "stall_limit"
    assert final_state.consecutive_idle_turns >= MAX_IDLE_TURNS
    # Exactly MAX_IDLE_TURNS turns get pumped — the next iteration of the
    # while loop sees the counter at the threshold and breaks.
    assert turns_run == MAX_IDLE_TURNS


def test_non_finalized_turns_eventually_stall(tmp_path, monkeypatch):
    """Six+ back-to-back non-finalized working turns should eventually
    trip the guard via ``consecutive_non_finalized_turns`` — otherwise a
    truly broken agent that keeps calling tools without ever ratcheting
    would loop forever."""

    def working_turn(conversation, tracker):
        conversation.state.events.append(_make_action_event())

    script = [working_turn] * 10

    final_state, turns_run = _run_execution_loop(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        turn_script=script,
        max_iterations=5,
    )

    assert final_state.stop_reason == "stall_limit"
    assert final_state.consecutive_non_finalized_turns >= MAX_NON_FINALIZED_TURNS
    assert turns_run == MAX_NON_FINALIZED_TURNS


def test_stall_after_one_commit_requires_many_idle_turns(tmp_path, monkeypatch):
    """Reproduces Finding 6 exactly.

    Session_3f1795098784 completed one ``ratchet_commit`` then did two
    normal post-commit "think → edit → validate" turns. The old rule
    counted every non-finalized turn as a stall and hit
    ``MAX_CONSECUTIVE_STALLS=2`` immediately.

    Under the new rule:
    - the commit resets both counters to zero
    - the two following working turns only bump
      ``consecutive_non_finalized_turns`` (to 2), which is well below the
      threshold of 6
    - the session must stay in STAGE_EXECUTION, NOT stop with
      ``stop_reason="stall_limit"``
    """

    def committing_turn(conversation, tracker):
        # Simulate the agent producing one ratchet_commit in this turn.
        conversation.state.events.append(_make_action_event())
        tracker.history.append({
            "run_id": "run_0001",
            "metrics": {"auc": 0.85},
            "committed": True,
        })

    def working_turn(conversation, tracker):
        # Post-commit "think → edit → validate" turn — tool activity but
        # nothing finalized.
        conversation.state.events.append(_make_action_event())

    # Commit, then 2 back-to-back working turns. This exactly mirrors the
    # Finding 6 scenario.
    script = [committing_turn, working_turn, working_turn]

    final_state, turns_run = _run_execution_loop(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        turn_script=script,
        max_iterations=5,
    )

    # Session must NOT have been killed by the stall guard. It should have
    # consumed all three scripted turns and still be waiting to make
    # progress — stop_reason is clean.
    assert final_state.stop_reason != "stall_limit", (
        f"stall_limit fired after only {turns_run} turns with one commit — "
        f"this is exactly the Finding 6 regression. "
        f"consecutive_idle_turns={final_state.consecutive_idle_turns}, "
        f"consecutive_non_finalized_turns={final_state.consecutive_non_finalized_turns}"
    )
    assert final_state.iteration_index == 1
    assert final_state.consecutive_non_finalized_turns == 2
    assert final_state.consecutive_idle_turns == 0
    assert turns_run == 3


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
