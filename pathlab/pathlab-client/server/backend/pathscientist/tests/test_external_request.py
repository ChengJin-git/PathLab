from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from pathscientist.orchestrator.external_request import infer_external_request
from pathscientist.orchestrator.runner import _apply_external_request_inference
from pathscientist.orchestrator.types import ResearchObjective, ResearchSessionState
from pathscientist.config import PathScientistConfig
from uuid import uuid4


def test_malformed_llm_response_returns_parse_error():
    result = infer_external_request(
        question="Train on BRACS and externally validate on NSCLC.",
        llm_caller=lambda _prompt: "external validation requested: yes",
    )

    assert result.status == "parse_error"
    assert result.enabled is False
    assert result.raw == {}


def test_runner_does_not_cache_transient_parse_error():
    state = ResearchSessionState.create(
        session_id="sess_external_parse",
        conversation_id=uuid4(),
        objective=ResearchObjective(
            question="Train on BRACS and externally validate on NSCLC.",
        ),
    )
    existing = {
        "source": "llm",
        "requested": True,
        "enabled": True,
        "status": "ready",
        "contract": {
            "external_task_type": "mil_classification",
            "external_features_dir": "/data/external/features",
        },
        "missing": [],
    }
    state.grounding = {"external_test_request": dict(existing)}
    config = PathScientistConfig()

    result = _apply_external_request_inference(
        state,
        config,
        selected_skill="mil_classification",
        llm_caller=lambda _prompt: "external validation requested: yes",
    )

    assert result.status == "parse_error"
    assert state.grounding["external_test_request"] == existing
    assert config.external_test_enabled is False
    assert config.external_test_contract == {}


def test_unknown_external_task_type_requires_explicit_task_type(tmp_path):
    external_root = tmp_path / "external segmentation cohort"
    (external_root / "masks").mkdir(parents=True)
    (external_root / "predictions").mkdir()
    (external_root / "masks" / "slide_001.png").write_bytes(b"mask")
    (external_root / "predictions" / "slide_001.png").write_bytes(b"prediction")

    def llm_caller(_prompt: str) -> str:
        return json.dumps(
            {
                "external_validation_requested": True,
                "confidence": "high",
                "reason": "The user requested an independent external cohort.",
                "external_task_type": "external mask audit",
                "training_data": {"paths": [], "dataset_name": "internal"},
                "external_data": {
                    "paths": [str(external_root)],
                    "dataset_name": "independent segmentation cohort",
                    "role": "external_validation",
                },
                "missing": [],
            }
        )

    result = infer_external_request(
        question="Train internally and externally validate segmentation on this cohort.",
        selected_skill="",
        task_profile={},
        llm_caller=llm_caller,
    )

    assert result.requested is True
    assert result.enabled is False
    assert result.status == "unknown_task_type"
    assert "external_task_type" in result.missing
    assert result.contract == {}


def test_known_skill_can_supply_task_type_when_llm_omits_it(tmp_path):
    external_root = tmp_path / "external"
    external_root.mkdir()

    def llm_caller(_prompt: str) -> str:
        return json.dumps(
            {
                "external_validation_requested": True,
                "confidence": "high",
                "external_data": {"paths": [str(external_root)], "dataset_name": "external"},
            }
        )

    result = infer_external_request(
        question="Run an external test on this independent cohort.",
        selected_skill="mil_classification",
        llm_caller=llm_caller,
    )

    assert result.status == "missing_external_data"
    assert result.contract["external_task_type"] == "mil_classification"
