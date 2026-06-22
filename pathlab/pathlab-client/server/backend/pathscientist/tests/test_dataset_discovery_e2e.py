"""End-to-end smoke for literature-grounded dataset discovery.

Phase E T12 of docs/plans/2026-04-30-pathscientist-literature-grounded-dataset-discovery-plan.md.

The full ``run_research_session`` entrypoint creates an agent + conversation,
which is too heavyweight (and network-dependent) for unit tests. This smoke
instead exercises the actual integration we care about:

  ``_run_acquisition_stage`` + ``_stop_before_execution`` →
  artifacts written + ``state.stage == "pre_execution_ready"``

— matching what the orchestrator will do when ``cfg.stop_before_execution=True``
fires in production.
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


class _ConvState:
    def __init__(self):
        self.agent_state: dict = {}


class _StubConversation:
    """Minimal stand-in for OpenHands LocalConversation: only state.agent_state matters."""

    def __init__(self):
        self.state = _ConvState()


class _Config:
    data_mounts: dict = {}
    dataset_cache_dir: str = ""
    download_policy: str = "disabled"
    max_download_size_gb: float = 1.0
    allow_large_downloads: bool = False
    stop_before_execution: bool = True


def _state_with_grounding(question="CRC MSI prediction from H&E"):
    from pathscientist.orchestrator.types import (
        ResearchObjective,
        ResearchSessionState,
        STAGE_ACQUISITION,
        STAGE_GROUNDING,
    )
    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(question=question),
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
    state.grounding = {
        "baselines": [
            {"dataset": "CRC-MSI", "paper_id": "openalex:W1", "context": "AUC on CRC-MSI"},
        ],
        "passages": [
            {
                "paper_id": "openalex:W2",
                "section": "Data availability",
                "text": "The CRC-MSI dataset is available at https://zenodo.org/records/12345.",
            },
        ],
    }
    state.advance(STAGE_GROUNDING)
    state.advance(STAGE_ACQUISITION)
    return state


def test_e2e_stop_before_execution_writes_discovery_and_plan_and_brief(tmp_path):
    """Full Phase A→C integration:
    - acquisition stage runs discovery + writes artifacts
    - stop_before_execution short-circuits to pre_execution_ready
    - execution brief surfaces both paths"""
    from pathscientist.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )
    from pathscientist.dataset.discovery_store import (
        discovery_path_for_workspace,
        load_discovery_records,
    )
    from pathscientist.orchestrator.runner import (
        _run_acquisition_stage,
        _stop_before_execution,
    )
    from pathscientist.orchestrator.types import STAGE_PRE_EXECUTION_READY

    state = _state_with_grounding()
    session = _Session(tmp_path)
    cfg = _Config()
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    # 1. Run the acquisition stage — discovery + plan + manifest written.
    _run_acquisition_stage(state, session, cfg)

    discovery_path = discovery_path_for_workspace(session.workspace_dir)
    plan_path = acquisition_plan_path_for_workspace(session.workspace_dir)
    assert discovery_path.exists(), "T7 must write discovery.json"
    assert plan_path.exists(), "T8 must write acquisition_plan.json"

    # Discovery should have surfaced CRC-MSI from grounding baselines.
    records = load_discovery_records(discovery_path)
    assert any(r.name == "CRC-MSI" for r in records)

    # Plan considered list should be non-empty with structured per-candidate keys.
    plan_payload = json.loads(plan_path.read_text())
    assert "considered" in plan_payload
    sample = plan_payload["considered"][0]
    for key in ("dataset_id", "name", "provider", "access", "score", "relevant", "allowed"):
        assert key in sample

    # 2. stop_before_execution advances state.stage and persists brief.
    state = _stop_before_execution(state, session, conversation=_StubConversation())
    assert state.stage == STAGE_PRE_EXECUTION_READY
    assert state.execution_brief, "execution brief must be persisted"
    # Brief must reference the discovery + plan paths (T9 wiring).
    assert "Dataset discovery:" in state.execution_brief
    assert "Dataset acquisition plan:" in state.execution_brief
    assert str(discovery_path) in state.execution_brief
    assert str(plan_path) in state.execution_brief


def test_e2e_with_empty_grounding_still_produces_artifacts(tmp_path):
    """Even an MSI prompt with empty grounding (network disabled, no literature)
    must produce both artifacts so reviewers can see ``considered=[]`` rather
    than silently exiting."""
    from pathscientist.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )
    from pathscientist.dataset.discovery_store import (
        discovery_path_for_workspace,
    )
    from pathscientist.orchestrator.runner import _run_acquisition_stage

    state = _state_with_grounding()
    state.grounding = {}     # no baselines / passages / sota
    session = _Session(tmp_path)
    cfg = _Config()
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, session, cfg)

    assert discovery_path_for_workspace(session.workspace_dir).exists()
    assert acquisition_plan_path_for_workspace(session.workspace_dir).exists()


def test_e2e_artifacts_persist_even_when_acquisition_status_is_failed(tmp_path):
    """``download_policy=disabled`` means no download fires, but plan + discovery
    must still be on disk so the brief can surface them."""
    from pathscientist.orchestrator.runner import _run_acquisition_stage

    state = _state_with_grounding()
    session = _Session(tmp_path)
    cfg = _Config()
    cfg.download_policy = "disabled"
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, session, cfg)

    # Both artifact paths persisted into grounding for the brief.
    assert "dataset_discovery_path" in state.grounding
    assert "dataset_acquisition_plan_path" in state.grounding
    assert Path(state.grounding["dataset_discovery_path"]).exists()
    assert Path(state.grounding["dataset_acquisition_plan_path"]).exists()
    # acquisition_status reflects whatever the policy/scout decided —
    # NOT prepared, but artifacts are still on disk.
    assert state.acquisition_status in {"failed", "skipped_policy", "skipped"}
