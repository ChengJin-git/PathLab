"""Cover synthesis.context.build_synthesis_context's acquisition payload.
T8a from docs/plans/2026-04-25-autoresearch-dataset-download-next-implementation-plan.md
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from autoresearch.orchestrator.types import ResearchObjective, ResearchSessionState
from autoresearch.synthesis.context import build_synthesis_context


def _state() -> ResearchSessionState:
    return ResearchSessionState.create(
        session_id="sid", conversation_id=uuid4(),
        objective=ResearchObjective(question="train", success_metric="auc"),
    )


def test_acquisition_payload_defaults_to_none_status():
    ctx = build_synthesis_context(_state())
    assert ctx["acquisition"]["status"] == "none"
    assert ctx["acquisition"]["manifest_path"] == ""
    assert ctx["acquisition"]["selected_dataset"] == {}
    assert ctx["acquisition"]["notes"] == ""


def test_acquisition_payload_carries_prepared_state():
    state = _state()
    state.acquisition_status = "prepared"
    state.dataset_manifest_path = "/workspace/.dataset/manifest.json"
    state.selected_dataset = {
        "dataset_id": "hf:demo/x", "name": "Demo", "provider": "huggingface",
        "access": "public", "license": "CC-BY-4.0",
    }
    state.acquisition_notes = ""
    ctx = build_synthesis_context(state)
    acq = ctx["acquisition"]
    assert acq["status"] == "prepared"
    assert acq["manifest_path"] == "/workspace/.dataset/manifest.json"
    assert acq["selected_dataset"]["name"] == "Demo"
    assert acq["selected_dataset"]["license"] == "CC-BY-4.0"


def test_acquisition_payload_carries_skipped_status_with_notes():
    state = _state()
    state.acquisition_status = "skipped_policy"
    state.acquisition_notes = "access=gated"
    ctx = build_synthesis_context(state)
    assert ctx["acquisition"]["status"] == "skipped_policy"
    assert ctx["acquisition"]["notes"] == "access=gated"
    # selected_dataset should be empty since policy refused before pick.
    assert ctx["acquisition"]["selected_dataset"] == {}
