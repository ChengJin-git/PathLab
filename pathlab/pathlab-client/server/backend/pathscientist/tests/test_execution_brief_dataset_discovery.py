"""Tests for execution brief surfacing dataset discovery + plan paths.

Phase C T9 of docs/plans/2026-04-30-pathscientist-literature-grounded-dataset-discovery-plan.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _state(question="CRC MSI prediction"):
    from pathscientist.orchestrator.types import (
        ResearchObjective,
        ResearchSessionState,
    )
    return ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(question=question),
    )


def test_brief_mentions_discovery_paths_when_acquisition_failed(tmp_path):
    from pathscientist.orchestrator.prompts import build_execution_brief

    state = _state()
    state.acquisition_status = "failed"
    state.acquisition_notes = "no_relevant_candidate"
    state.grounding = {
        "dataset_discovery_path": str(tmp_path / ".dataset" / "discovery.json"),
        "dataset_acquisition_plan_path": str(
            tmp_path / ".dataset" / "acquisition_plan.json"
        ),
    }
    brief = build_execution_brief(state)
    assert "Dataset discovery:" in brief
    assert "Dataset acquisition plan:" in brief
    assert str(tmp_path / ".dataset" / "discovery.json") in brief
    assert str(tmp_path / ".dataset" / "acquisition_plan.json") in brief


def test_brief_mentions_discovery_paths_when_acquisition_skipped_policy(tmp_path):
    from pathscientist.orchestrator.prompts import build_execution_brief

    state = _state()
    state.acquisition_status = "skipped_policy"
    state.acquisition_notes = "download_policy=disabled"
    state.grounding = {
        "dataset_discovery_path": str(tmp_path / ".dataset" / "discovery.json"),
        "dataset_acquisition_plan_path": str(
            tmp_path / ".dataset" / "acquisition_plan.json"
        ),
    }
    brief = build_execution_brief(state)
    assert "Dataset discovery:" in brief
    assert "Dataset acquisition plan:" in brief


def test_brief_mentions_discovery_paths_when_acquisition_prepared(tmp_path):
    """Even on success, the agent benefits from seeing the plan/discovery paths."""
    from pathscientist.orchestrator.prompts import build_execution_brief

    state = _state()
    state.acquisition_status = "prepared"
    state.dataset_manifest_path = str(tmp_path / ".dataset" / "manifest.json")
    state.selected_dataset = {
        "name": "CRC-MSI",
        "provider": "huggingface",
        "access": "public",
        "dataset_id": "discovered:crc-msi",
        "license": "",
    }
    state.grounding = {
        "dataset_discovery_path": str(tmp_path / ".dataset" / "discovery.json"),
        "dataset_acquisition_plan_path": str(
            tmp_path / ".dataset" / "acquisition_plan.json"
        ),
    }
    brief = build_execution_brief(state)
    assert "Dataset discovery:" in brief
    assert "Dataset acquisition plan:" in brief


def test_failed_brief_lists_artifact_paths_before_failure_reason(tmp_path):
    """Task 0 blocker #3: discovery + plan paths must appear BEFORE
    `Dataset acquisition: failed (...)` so the agent reads where to look
    before reading why it failed."""
    from pathscientist.orchestrator.prompts import build_execution_brief

    state = _state()
    state.acquisition_status = "failed"
    state.acquisition_notes = "no_relevant_candidate"
    state.grounding = {
        "dataset_discovery_path": str(tmp_path / ".dataset" / "discovery.json"),
        "dataset_acquisition_plan_path": str(
            tmp_path / ".dataset" / "acquisition_plan.json"
        ),
    }
    brief = build_execution_brief(state)
    failure_idx = brief.index("Dataset acquisition: failed")
    assert brief.index("Dataset discovery:") < failure_idx
    assert brief.index("Dataset acquisition plan:") < failure_idx


def test_skipped_policy_brief_lists_artifact_paths_before_failure_reason(tmp_path):
    """Same ordering rule applies to skipped_policy."""
    from pathscientist.orchestrator.prompts import build_execution_brief

    state = _state()
    state.acquisition_status = "skipped_policy"
    state.acquisition_notes = "policy_block_manual"
    state.grounding = {
        "dataset_discovery_path": str(tmp_path / ".dataset" / "discovery.json"),
        "dataset_acquisition_plan_path": str(
            tmp_path / ".dataset" / "acquisition_plan.json"
        ),
    }
    brief = build_execution_brief(state)
    failure_idx = brief.index("Dataset acquisition: skipped_policy")
    assert brief.index("Dataset discovery:") < failure_idx
    assert brief.index("Dataset acquisition plan:") < failure_idx


def test_brief_renders_selected_dataset_candidate_under_skipped_policy(tmp_path):
    """Task 8: when acquisition is skipped_policy AND selected_dataset is
    set, the brief must surface the candidate's name + provider + access
    so the agent knows *which* dataset got blocked."""
    from pathscientist.orchestrator.prompts import build_execution_brief

    state = _state("train Gleason grading on WSI")
    state.acquisition_status = "skipped_policy"
    state.acquisition_notes = "too_large"
    state.selected_dataset = {
        "dataset_id": "kaggle:prostate-cancer-grade-assessment",
        "name": "PANDA — Prostate cANcer graDe Assessment",
        "provider": "kaggle",
        "access": "manual",
        "license": "CC-BY-SA-NC-4.0",
    }
    state.grounding = {
        "dataset_discovery_path": str(tmp_path / ".dataset" / "discovery.json"),
        "dataset_acquisition_plan_path": str(
            tmp_path / ".dataset" / "acquisition_plan.json"
        ),
    }
    brief = build_execution_brief(state)
    assert "Selected dataset candidate:" in brief
    assert "PANDA" in brief
    assert "kaggle" in brief
    assert "access: manual" in brief
    assert "too_large" in brief


def test_brief_renders_selected_dataset_candidate_under_failed(tmp_path):
    """Same rendering applies to ``failed`` outcomes when a candidate was chosen."""
    from pathscientist.orchestrator.prompts import build_execution_brief

    state = _state()
    state.acquisition_status = "failed"
    state.acquisition_notes = "no_provider:kaggle"
    state.selected_dataset = {
        "dataset_id": "kaggle:panda",
        "name": "PANDA",
        "provider": "kaggle",
        "access": "manual",
        "license": "",
    }
    state.grounding = {
        "dataset_acquisition_plan_path": str(
            tmp_path / ".dataset" / "acquisition_plan.json"
        ),
    }
    brief = build_execution_brief(state)
    assert "Selected dataset candidate:" in brief
    assert "PANDA" in brief


def test_brief_omits_discovery_lines_when_paths_not_set():
    """No grounding paths → no spurious lines."""
    from pathscientist.orchestrator.prompts import build_execution_brief

    state = _state()
    state.acquisition_status = "skipped"
    state.grounding = {}    # no dataset_discovery_path / dataset_acquisition_plan_path
    brief = build_execution_brief(state)
    assert "Dataset discovery:" not in brief
    assert "Dataset acquisition plan:" not in brief
