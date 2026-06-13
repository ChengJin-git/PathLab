"""Tests for the runner's end-of-session IntegrityGuard wiring.

These tests lock down Task 8 of the Session Integrity Hardening plan: the
runner must invoke ``check_session_integrity`` before synthesis, persist the
resulting report onto ``state.integrity_report``, force ``paper_ready`` to
False whenever there are fatal issues, and surface the report through the
CLI and synthesis markdown.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import os

os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

import pytest

from pathscientist.cli_commands import handle_command
from pathscientist.cli_state import InteractiveCLIState
from pathscientist.orchestrator import runner as runner_module
from pathscientist.orchestrator.runner import (
    _run_integrity_check,
    continue_research_session,
)
from pathscientist.orchestrator.state_bridge import (
    dump_research_session_state,
    load_research_session_state,
    persist_research_session_state,
)
from pathscientist.orchestrator.types import (
    STAGE_SYNTHESIS,
    ResearchObjective,
    ResearchSessionState,
    RunRecord,
)


# ---------- helpers ----------


def _init_empty_git_repo(path: Path) -> None:
    """Init a git repo at ``path`` with NO commits — triggers ``no_git_commits``."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--quiet"], cwd=path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test Runner"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _make_broken_state(session_id: str, conversation_id) -> ResearchSessionState:
    """Build a state claiming committed runs — triggers integrity fatals."""
    state = ResearchSessionState.create(
        session_id=session_id,
        conversation_id=conversation_id,
        objective=ResearchObjective(question="Break me"),
    )
    state.max_iterations = 3
    # Research thinks it committed 2 runs, but the workspace's git log will
    # be empty AND no evidence records will exist → multiple fatals.
    state.record_run(RunRecord(run_id="run_a", iteration=0, metric_value=0.70, committed=True))
    state.record_run(RunRecord(run_id="run_b", iteration=1, metric_value=0.72, committed=True))
    state.iteration_index = 2
    state.paper_ready = True  # starts True to prove the guard flips it off
    return state


def _make_happy_state(session_id: str, conversation_id) -> ResearchSessionState:
    """Build a state that should trigger no fatal integrity issues."""
    state = ResearchSessionState.create(
        session_id=session_id,
        conversation_id=conversation_id,
        objective=ResearchObjective(question="Clean session"),
    )
    state.max_iterations = 3
    state.iteration_index = 0
    state.paper_ready = False
    return state


def _make_deps_stub(workspace_root: Path, primary_metric: str = "auc") -> SimpleNamespace:
    """Minimal SessionDeps-shaped stub for _run_integrity_check."""
    tracker = SimpleNamespace(history=[])
    iteration_state = SimpleNamespace(history=[])
    workspace = SimpleNamespace(root=workspace_root)
    config = SimpleNamespace(primary_metric=primary_metric)
    return SimpleNamespace(
        workspace=workspace,
        tracker=tracker,
        iteration_state=iteration_state,
        config=config,
        evidence_skipped_runs=[],
    )


# ---------- Test 1: runner persists integrity report ----------


def test_runner_persists_integrity_report(tmp_path):
    """End-to-end: _run_integrity_check stores report on state with fatal_count >= 1."""
    workspace_root = tmp_path / "workspace"
    _init_empty_git_repo(workspace_root)
    # No .evidence/runs/* so evidence_run_missing also fires for the two
    # committed runs in the broken state.

    state = _make_broken_state("sess_runner_int", uuid4())
    deps = _make_deps_stub(workspace_root)

    _run_integrity_check(state, deps)

    assert isinstance(state.integrity_report, dict)
    assert state.integrity_report.get("fatal_count", 0) >= 1
    # The no_git_commits check should have fired because research_run_history
    # has committed runs but git log is empty.
    codes = [issue["code"] for issue in state.integrity_report.get("issues", [])]
    assert "no_git_commits" in codes
    assert "evidence_run_missing" in codes
    # passed flag must reflect fatality
    assert state.integrity_report.get("passed") is False


# ---------- Test 2: fatal issues force paper_ready=False ----------


def test_fatal_integrity_forces_paper_not_ready(tmp_path):
    """A fatal integrity report must flip state.paper_ready to False."""
    workspace_root = tmp_path / "workspace"
    _init_empty_git_repo(workspace_root)

    state = _make_broken_state("sess_paper_gate", uuid4())
    # Set paper_ready=True up front to prove the guard forces it off.
    state.paper_ready = True
    deps = _make_deps_stub(workspace_root)

    _run_integrity_check(state, deps)

    assert state.integrity_report.get("fatal_count", 0) > 0
    assert state.paper_ready is False, (
        "paper_ready must be forced to False when the integrity guard "
        "reports fatal issues"
    )


# ---------- Test 3: /status CLI surfaces integrity issues ----------


def test_cli_status_surfaces_integrity_issues():
    """/status must render fatal_count / warning_count when integrity_report is set."""
    cli_state = InteractiveCLIState(mode="research")
    cli_state.conversation = object()  # pretend session is active
    cli_state.research_state = SimpleNamespace(
        stage="completed",
        integrity_report={
            "passed": False,
            "fatal_count": 2,
            "warning_count": 1,
            "issues": [
                {
                    "code": "no_git_commits",
                    "severity": "fatal",
                    "message": "history claims committed but git log empty",
                    "context": {},
                },
                {
                    "code": "tracker_run_id_blank",
                    "severity": "fatal",
                    "message": "tracker entry #0 has blank run_id",
                    "context": {},
                },
                {
                    "code": "history_length_mismatch",
                    "severity": "warning",
                    "message": "tracker has 5 entries but research has 3",
                    "context": {},
                },
            ],
        },
    )

    result = handle_command("/status", cli_state)

    assert result.handled is True
    # Summary counts appear
    assert "fatal" in result.output.lower()
    assert "2" in result.output  # fatal_count
    # Individual issue codes appear so users can act on them
    assert "no_git_commits" in result.output
    assert "tracker_run_id_blank" in result.output


# ---------- Supplementary tests ----------


def test_state_bridge_round_trips_integrity_report(tmp_path):
    """integrity_report must survive serialize / deserialize."""
    from persistence_helpers import build_test_conversation

    conversation, session = build_test_conversation(tmp_path)
    state = ResearchSessionState.create(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        objective=ResearchObjective(question="Round trip check"),
    )
    state.integrity_report = {
        "passed": False,
        "fatal_count": 1,
        "warning_count": 0,
        "issues": [
            {
                "code": "no_git_commits",
                "severity": "fatal",
                "message": "git log empty",
                "context": {"workspace_root": "/tmp/x"},
            }
        ],
    }

    # Round-trip through dump and persist
    payload = dump_research_session_state(state)
    assert payload["integrity_report"]["fatal_count"] == 1

    persist_research_session_state(conversation, state)
    loaded = load_research_session_state(conversation)
    assert loaded is not None
    assert loaded.integrity_report["fatal_count"] == 1
    assert loaded.integrity_report["issues"][0]["code"] == "no_git_commits"


def test_happy_state_passes_integrity_check(tmp_path):
    """A clean workspace with no committed runs should pass all checks."""
    workspace_root = tmp_path / "workspace"
    _init_empty_git_repo(workspace_root)

    state = _make_happy_state("sess_happy", uuid4())
    deps = _make_deps_stub(workspace_root)

    _run_integrity_check(state, deps)

    assert state.integrity_report.get("fatal_count", 0) == 0
    assert state.integrity_report.get("passed") is True
    # paper_ready must not be flipped to False by a passing check — it stays
    # whatever synthesis set it to.
    assert state.paper_ready is False  # was False to start; stays False


def test_synthesis_report_includes_integrity_issues_section(tmp_path):
    """When integrity_report has fatal issues, report.md must include
    the ## Integrity Issues section."""
    from pathscientist.config import PathScientistConfig
    from pathscientist.orchestrator.runner import _run_synthesis_stage

    workspace = SimpleNamespace(root=tmp_path / "workspace")
    workspace.root.mkdir(parents=True, exist_ok=True)

    config = PathScientistConfig(
        workspace_dir=str(workspace.root),
        output_dir=str(tmp_path / "output"),
        gpu_ids=[],
        sandbox_mode="local",
        max_iterations=3,
        primary_metric="auc",
        conversation_persistence_dir=str(tmp_path / "persistence"),
        llm_model="",
        llm_api_key="",
        llm_base_url="",
    )

    state = ResearchSessionState.create(
        session_id="sess_integrity_md",
        conversation_id=uuid4(),
        objective=ResearchObjective(question="Detect broken integrity in md"),
    )
    state.record_run(RunRecord(run_id="run_fake", iteration=0, metric_value=0.5, committed=True))
    state.integrity_report = {
        "passed": False,
        "fatal_count": 1,
        "warning_count": 1,
        "issues": [
            {
                "code": "no_git_commits",
                "severity": "fatal",
                "message": "claims committed runs but git log is empty",
                "context": {},
            },
            {
                "code": "runs_all_identical_metric",
                "severity": "warning",
                "message": "3 runs share auc=0.5",
                "context": {},
            },
        ],
    }

    _run_synthesis_stage(state, workspace=workspace, session=None, config=config)

    md_text = Path(state.report_markdown_path).read_text()
    assert "## Integrity Issues" in md_text
    assert "no_git_commits" in md_text
    assert "runs_all_identical_metric" in md_text
    # fatal issues mean paper_ready must be False even if verification passed
    assert state.paper_ready is False


def test_cli_report_shows_integrity_counts():
    """/report must include integrity fatal/warning counts when set."""
    cli_state = InteractiveCLIState()
    cli_state.research_state = SimpleNamespace(
        report_markdown_path="/tmp/report.md",
        paper_draft_path="/tmp/paper_draft.md",
        claim_count=4,
        integrity_report={
            "passed": False,
            "fatal_count": 2,
            "warning_count": 1,
            "issues": [
                {"code": "no_git_commits", "severity": "fatal", "message": "x", "context": {}},
            ],
        },
    )
    result = handle_command("/report", cli_state)
    assert "2" in result.output  # fatal_count
    assert "Integrity" in result.output or "integrity" in result.output.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
