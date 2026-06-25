"""Tests for orchestrator dataset acquisition stage (DD plan T7)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from autoresearch.orchestrator.director import ResearchDirector
from autoresearch.orchestrator.prompts import build_execution_brief
from autoresearch.orchestrator.state_bridge import (
    dump_research_session_state,
    load_research_session_state,
)
from autoresearch.orchestrator.types import (
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
    from autoresearch.orchestrator.runner import _run_acquisition_stage

    state = _state()
    state.task_profile = {"task_type": "patch_classification"}
    config = type("C", (), {})()
    config.data_mounts = {"/host/path": "/data"}
    session = type("S", (), {})()
    session.persistence_root = tmp_path
    session.workspace_dir = tmp_path / "workspace"
    session.workspace_dir.mkdir()

    state = _run_acquisition_stage(state, session, config)
    assert state.acquisition_status == "skipped"
    assert "user-supplied" in state.acquisition_notes


def test_run_acquisition_stage_fails_when_no_task_profile(tmp_path):
    from autoresearch.orchestrator.runner import _run_acquisition_stage

    state = _state()
    # No task_profile, no grounding["task_profile"]
    config = type("C", (), {})()
    config.data_mounts = {}
    session = type("S", (), {})()
    session.persistence_root = tmp_path
    session.workspace_dir = tmp_path / "workspace"
    session.workspace_dir.mkdir()

    state = _run_acquisition_stage(state, session, config)
    assert state.acquisition_status == "failed"
    assert "task_profile" in state.acquisition_notes


def test_run_acquisition_stage_works_with_real_session(tmp_path, monkeypatch):
    """Regression for review P0 #1: a real AutoResearchSession exposes
    `workspace_dir`, not `workspace.root`. Pre-fix this test crashed silently
    inside the broad except and recorded
    'service_error: ... has no attribute "workspace"'.
    """
    from autoresearch.dataset.acquisition import AcquisitionResult
    from autoresearch.dataset.types import DatasetManifest
    from autoresearch.orchestrator import runner as runner_mod
    from autoresearch.orchestrator.runner import _run_acquisition_stage
    from autoresearch.runtime.session import AutoResearchSession

    base = tmp_path / "base"
    base.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = AutoResearchSession.create(
        research_question="crc patch",
        base_dir=str(base),
        workspace_dir=str(workspace),
    )

    state = ResearchSessionState.create(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        objective=ResearchObjective(question="crc patch", success_metric="auc"),
    )
    state.advance(STAGE_GROUNDING)
    state.advance(STAGE_ACQUISITION)
    state.task_profile = {
        "task_type": "patch_classification", "asset_level": "patch",
        "input_modality": "patch_images", "label_granularity": "patch",
        "organ": "colorectal",
    }

    # Fake the service so we don't hit the network. We must patch BOTH the
    # alias on `runner_mod` and the original symbol on
    # `autoresearch.dataset.acquisition`, because runner does a function-local
    # import that re-binds the name from the source module each call.
    fake_manifest = DatasetManifest(
        dataset_id="demo:fake", provider="huggingface",
        selected_for_task="patch_classification",
        raw_root=str(tmp_path / "raw"), prepared_root=str(tmp_path / "prepared"),
        data_mounts={str(tmp_path / "prepared"): "/data"},
        prepared_contract={"task_type": "patch_classification"},
        access="public", status="prepared",
    )
    class _FakeCandidate:
        class _Rec:
            dataset_id = "demo:fake"
            name = "Fake"
            provider = "huggingface"
            access = "public"
            license = "MIT"
        record = _Rec()
        score = 5.0
        reasons = []
    fake_result = AcquisitionResult(
        status="prepared",
        manifest=fake_manifest,
        manifest_path=workspace / ".dataset" / "manifest.json",
        candidate=_FakeCandidate(),
    )

    class _FakeService:
        def __init__(self, **kwargs): pass
        def acquire(self, profile, workspace_root):
            # CRITICAL: this is the real production call.
            # Pre-fix it raised AttributeError on session.workspace.root.
            # Post-fix it receives workspace_dir.
            assert workspace_root == workspace, (
                f"acquire received workspace_root={workspace_root}, expected {workspace}"
            )
            (workspace / ".dataset").mkdir(parents=True, exist_ok=True)
            (workspace / ".dataset" / "manifest.json").write_text("{}")
            return fake_result

    import autoresearch.dataset.acquisition as acq_mod
    monkeypatch.setattr(runner_mod, "DatasetAcquisitionService", _FakeService, raising=False)
    monkeypatch.setattr(acq_mod, "DatasetAcquisitionService", _FakeService, raising=True)

    config = type("Cfg", (), {})()
    config.data_mounts = {}
    config.dataset_cache_dir = ""
    config.download_policy = "public_only"
    config.max_download_size_gb = 20.0
    config.allow_large_downloads = False

    state = _run_acquisition_stage(state, session, config)

    assert state.acquisition_status == "prepared", (
        f"acquisition_status={state.acquisition_status}, "
        f"notes={state.acquisition_notes}"
    )
    # Belt and braces: ensure the silent-failure mode is gone.
    assert "service_error" not in state.acquisition_notes
    assert "has no attribute" not in state.acquisition_notes
