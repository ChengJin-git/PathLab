"""Tests for orchestrator dataset acquisition stage (DD plan T7)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from pathscientist.orchestrator.director import ResearchDirector
from pathscientist.orchestrator.prompts import build_execution_brief
from pathscientist.orchestrator.state_bridge import (
    dump_research_session_state,
    load_research_session_state,
)
from pathscientist.orchestrator.types import (
    STAGE_ACQUISITION,
    STAGE_EXECUTION,
    STAGE_GROUNDING,
    ResearchObjective,
    ResearchSessionState,
)


def _state(question: str = "train a patch classifier") -> ResearchSessionState:
    return ResearchSessionState.create(
        session_id="sid",
        conversation_id=uuid4(),
        objective=ResearchObjective(question=question, success_metric="auc"),
    )


# ---- Stage transition tests ----

def test_director_routes_grounding_to_acquisition_when_enabled():
    state = _state()
    state.advance(STAGE_GROUNDING)
    state.grounding = {
        "task_profile": {
            "task_type": "patch_classification",
            "asset_level": "patch",
        },
        "selected_skill": "patch_classification",
    }
    director = ResearchDirector(auto_approve=True, enable_acquisition=True)
    state = director.advance(state)
    assert state.stage == STAGE_ACQUISITION
    # Director should have copied the task_profile onto state.
    assert state.task_profile == {
        "task_type": "patch_classification",
        "asset_level": "patch",
    }


def test_director_skips_acquisition_when_flag_false():
    state = _state()
    state.advance(STAGE_GROUNDING)
    state.grounding = {
        "task_profile": {
            "task_type": "patch_classification",
            "asset_level": "patch",
        },
    }
    director = ResearchDirector(auto_approve=True, enable_acquisition=False)
    state = director.advance(state)
    assert state.stage == STAGE_EXECUTION


def test_director_advances_acquisition_to_execution():
    state = _state()
    # Drive state up through STAGE_ACQUISITION manually.
    state.advance(STAGE_GROUNDING)
    state.advance(STAGE_ACQUISITION)
    director = ResearchDirector(auto_approve=True)
    state = director.advance(state)
    assert state.stage == STAGE_EXECUTION


# ---- State persistence ----

def test_acquisition_fields_default_to_empty():
    state = _state()
    assert state.task_profile == {}
    assert state.selected_dataset == {}
    assert state.dataset_manifest_path == ""
    assert state.acquisition_status == "none"
    assert state.acquisition_notes == ""


def test_acquisition_fields_round_trip_through_state_bridge():
    state = _state()
    state.task_profile = {"task_type": "mil_classification"}
    state.selected_dataset = {"dataset_id": "demo:x", "name": "Demo"}
    state.dataset_manifest_path = "/workspace/.dataset/manifest.json"
    state.acquisition_status = "prepared"
    state.acquisition_notes = ""
    payload = dump_research_session_state(state)
    restored = load_research_session_state(payload)
    assert restored.task_profile == {"task_type": "mil_classification"}
    assert restored.selected_dataset["name"] == "Demo"
    assert restored.dataset_manifest_path == "/workspace/.dataset/manifest.json"
    assert restored.acquisition_status == "prepared"


def test_state_bridge_back_compat_load_without_acquisition_fields():
    """Older persisted states must still load without raising."""
    state = _state()
    payload = dump_research_session_state(state)
    # Strip the new fields to simulate an older payload.
    for key in (
        "task_profile",
        "dataset_candidates",
        "selected_dataset",
        "dataset_manifest_path",
        "acquisition_status",
        "acquisition_notes",
    ):
        payload.get("state_payload", payload).pop(key, None)
        payload.pop(key, None)
    restored = load_research_session_state(payload)
    assert restored.task_profile == {}
    assert restored.acquisition_status == "none"


# ---- Brief rendering ----

def test_execution_brief_includes_prepared_dataset_info():
    state = _state()
    state.advance(STAGE_GROUNDING)
    state.advance(STAGE_ACQUISITION)
    state.acquisition_status = "prepared"
    state.dataset_manifest_path = "/workspace/.dataset/manifest.json"
    state.selected_dataset = {
        "dataset_id": "demo:x",
        "name": "Demo Dataset",
        "provider": "huggingface",
        "access": "public",
    }
    brief = build_execution_brief(state)
    assert "Selected dataset: Demo Dataset" in brief
    assert "huggingface" in brief
    assert "/workspace/.dataset/manifest.json" in brief


def test_execution_brief_includes_skipped_acquisition_note():
    state = _state()
    state.advance(STAGE_GROUNDING)
    state.advance(STAGE_ACQUISITION)
    state.acquisition_status = "skipped_policy"
    state.acquisition_notes = "access=gated"
    brief = build_execution_brief(state)
    assert "skipped_policy" in brief
    assert "access=gated" in brief


def test_execution_brief_no_dataset_lines_when_none_status():
    """The default acquisition_status=='none' must NOT add any dataset line."""
    state = _state()
    state.advance(STAGE_GROUNDING)
    brief = build_execution_brief(state)
    assert "Selected dataset:" not in brief
    assert "Dataset manifest:" not in brief
    assert "Dataset acquisition:" not in brief


# ---- _run_acquisition_stage helper (unit-level) ----

def test_run_acquisition_stage_skips_when_user_supplied_data_mounts(tmp_path):
    """When config.data_mounts is non-empty, the stage records 'skipped' and
    does NOT touch the registry."""
    from pathscientist.orchestrator.runner import _run_acquisition_stage

    state = _state()
    state.task_profile = {"task_type": "patch_classification"}
    config = type("C", (), {})()
    config.data_mounts = {"/host/path": "/data"}
    session = type("S", (), {})()
    session.persistence_root = tmp_path
    session.workspace = type("W", (), {})()
    session.workspace.root = tmp_path / "workspace"
    session.workspace.root.mkdir()

    state = _run_acquisition_stage(state, session, config)
    assert state.acquisition_status == "skipped"
    assert "user-supplied" in state.acquisition_notes


def test_run_acquisition_stage_fails_when_no_task_profile(tmp_path):
    from pathscientist.orchestrator.runner import _run_acquisition_stage

    state = _state()
    # No task_profile, no grounding["task_profile"]
    config = type("C", (), {})()
    config.data_mounts = {}
    session = type("S", (), {})()
    session.persistence_root = tmp_path
    session.workspace = type("W", (), {})()
    session.workspace.root = tmp_path / "workspace"
    session.workspace.root.mkdir()

    state = _run_acquisition_stage(state, session, config)
    assert state.acquisition_status == "failed"
    assert "task_profile" in state.acquisition_notes
