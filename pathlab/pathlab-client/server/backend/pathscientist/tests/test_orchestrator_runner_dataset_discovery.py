"""Tests for runner integration of literature-grounded dataset discovery.

Phase C T7 of docs/plans/2026-04-30-pathscientist-literature-grounded-dataset-discovery-plan.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class _Session:
    def __init__(self, root: Path):
        self.workspace_dir = Path(root) / "ws"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.persistence_root = Path(root)


class _Config:
    """Minimal stand-in for PathScientistConfig in acquisition tests."""

    data_mounts: dict = {}
    dataset_cache_dir: str = ""
    download_policy: str = "disabled"
    max_download_size_gb: float = 1.0
    allow_large_downloads: bool = False


def _msi_state(tmp_path):
    from pathscientist.orchestrator.types import (
        ResearchObjective,
        ResearchSessionState,
    )
    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(question="CRC MSI prediction from H&E"),
    )
    state.task_profile = {
        "task_type": "patch_classification",
        "asset_level": "patch",
        "input_modality": "patch_images",
        "label_granularity": "patch",
        "organ": "colorectal",
        "prediction_target": "microsatellite_instability",
        "required_label_keywords": ["MSI", "MSI-H", "MSS"],
    }
    return state


def test_runner_writes_discovery_artifact_when_grounding_has_baselines(tmp_path):
    from pathscientist.dataset.discovery_store import load_discovery_records
    from pathscientist.orchestrator.runner import _run_acquisition_stage

    state = _msi_state(tmp_path)
    state.grounding = {
        "baselines": [
            {"dataset": "CRC-MSI", "paper_id": "openalex:W1", "context": "AUC on CRC-MSI"},
        ],
    }
    cfg = _Config()
    cfg.data_mounts = {}     # let acquisition stage fire
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, _Session(tmp_path), cfg)

    discovery_path = tmp_path / "ws" / ".dataset" / "discovery.json"
    assert discovery_path.exists()
    records = load_discovery_records(discovery_path)
    assert [r.name for r in records] == ["CRC-MSI"]


def test_runner_persists_discovery_and_plan_paths_in_grounding(tmp_path):
    from pathscientist.orchestrator.runner import _run_acquisition_stage

    state = _msi_state(tmp_path)
    state.grounding = {
        "baselines": [
            {"dataset": "CRC-MSI", "paper_id": "openalex:W1"},
        ],
    }
    cfg = _Config()
    cfg.data_mounts = {}
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, _Session(tmp_path), cfg)

    assert "dataset_discovery_path" in state.grounding
    assert "dataset_acquisition_plan_path" in state.grounding
    assert Path(state.grounding["dataset_discovery_path"]).exists()
    assert Path(state.grounding["dataset_acquisition_plan_path"]).exists()


def test_runner_writes_acquisition_plan_artifact(tmp_path):
    from pathscientist.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )
    from pathscientist.orchestrator.runner import _run_acquisition_stage

    state = _msi_state(tmp_path)
    state.grounding = {"baselines": [{"dataset": "CRC-MSI", "paper_id": "openalex:W1"}]}
    cfg = _Config()
    cfg.data_mounts = {}
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, _Session(tmp_path), cfg)

    plan_path = acquisition_plan_path_for_workspace(tmp_path / "ws")
    assert plan_path.exists()
    payload = json.loads(plan_path.read_text())
    assert "considered" in payload


def test_runner_skips_discovery_when_data_mounts_provided(tmp_path):
    """Sanity: if user already provided data_mounts, acquisition is skipped
    and so is discovery. No discovery.json should appear."""
    from pathscientist.orchestrator.runner import _run_acquisition_stage

    state = _msi_state(tmp_path)
    state.grounding = {"baselines": [{"dataset": "CRC-MSI", "paper_id": "openalex:W1"}]}
    cfg = _Config()
    cfg.data_mounts = {"/host": "/data"}   # user-supplied → skip path

    _run_acquisition_stage(state, _Session(tmp_path), cfg)
    discovery_path = tmp_path / "ws" / ".dataset" / "discovery.json"
    assert not discovery_path.exists()
    assert state.acquisition_status == "skipped"


def test_runner_continues_when_grounding_is_empty(tmp_path):
    """Empty grounding → discovery returns []; acquisition still proceeds with curated registry."""
    from pathscientist.orchestrator.runner import _run_acquisition_stage

    state = _msi_state(tmp_path)
    state.grounding = {}
    cfg = _Config()
    cfg.data_mounts = {}
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, _Session(tmp_path), cfg)
    # Discovery file gets created with [] (empty list) so the brief can still
    # link to it; acquisition runs as before.
    discovery_path = tmp_path / "ws" / ".dataset" / "discovery.json"
    assert discovery_path.exists()
    records = json.loads(discovery_path.read_text())
    assert records == []


def test_runner_records_session_registry_path_in_grounding(tmp_path):
    """Task 0 blocker #2: session_registry_path needs to be in grounding so the
    brief / reviewers can find the merged curated+discovered registry."""
    from pathscientist.orchestrator.runner import _run_acquisition_stage

    state = _msi_state(tmp_path)
    state.grounding = {
        "baselines": [{"dataset": "CRC-MSI", "paper_id": "openalex:W1"}],
    }
    cfg = _Config()
    cfg.data_mounts = {}
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, _Session(tmp_path), cfg)

    assert "dataset_session_registry_path" in state.grounding
    assert Path(state.grounding["dataset_session_registry_path"]).exists()


def test_runner_does_not_mutate_seed_registry(tmp_path):
    """Plan T7 step 3 spec: do not mutate dataset/seed_data/pathology_datasets.json."""
    from pathscientist.orchestrator.runner import _run_acquisition_stage

    seed_path = (
        Path(__file__).parent.parent / "dataset" / "seed_data"
        / "pathology_datasets.json"
    )
    seed_before = seed_path.read_text()

    state = _msi_state(tmp_path)
    state.grounding = {"baselines": [{"dataset": "CRC-MSI", "paper_id": "openalex:W1"}]}
    cfg = _Config()
    cfg.data_mounts = {}
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, _Session(tmp_path), cfg)
    assert seed_path.read_text() == seed_before
