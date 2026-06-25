from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from autoresearch.orchestrator.external_request import infer_external_request
from autoresearch.orchestrator.runner import _apply_external_request_inference
from autoresearch.orchestrator.types import ResearchObjective, ResearchSessionState
from autoresearch.config import AutoResearchConfig
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
    config = AutoResearchConfig()

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


def test_runner_keeps_ready_external_contract_when_later_inference_is_missing():
    from autoresearch.orchestrator.external_request import ExternalRequestInference
    import autoresearch.orchestrator.runner as runner

    state = ResearchSessionState.create(
        session_id="sess_external_ready",
        conversation_id=uuid4(),
        objective=ResearchObjective(
            question="Train on local - tcga-nsclc-subset4 then validate on nsclc_external_test.",
        ),
    )
    existing = {
        "source": "llm",
        "requested": True,
        "enabled": True,
        "status": "enabled",
        "contract": {
            "model_source": "best_run",
            "external_task_type": "mil_classification",
            "external_features_dir": "/data/nsclc_external_test/features/virchow2/paramsabc",
            "external_splits_file": "/data/nsclc_external_test/splits.json",
            "datasets": [
                {
                    "role": "internal",
                    "dataset_name": "local - tcga-nsclc-subset4",
                    "paths": ["/data/TCGA-NSCLC-subset4"],
                },
                {
                    "role": "external",
                    "dataset_name": "nsclc_external_test",
                    "paths": ["/data/nsclc_external_test"],
                },
            ],
        },
        "missing": [],
    }
    state.grounding = {"external_test_request": dict(existing)}
    config = AutoResearchConfig()

    def worse_inference(**_kwargs):
        return ExternalRequestInference(
            requested=True,
            enabled=False,
            confidence="high",
            status="missing_external_data",
            reason="later inference lost the mounted external dataset",
            contract={
                "model_source": "best_run",
                "external_task_type": "mil_classification",
                "datasets": [
                    {
                        "role": "internal",
                        "dataset_name": "local - tcga-nsclc-subset4",
                        "paths": ["/data", "/data/raw"],
                    },
                    {"role": "external", "dataset_name": "nsclc_external_test"},
                ],
            },
            missing=["external_data_path"],
            training_data={"paths": ["/data", "/data/raw"]},
            external_data={"paths": []},
            raw={},
            source="llm",
        )

    original = runner.infer_external_request
    runner.infer_external_request = worse_inference
    try:
        result = _apply_external_request_inference(
            state,
            config,
            selected_skill="mil_classification",
        )
    finally:
        runner.infer_external_request = original

    assert result is None
    request = state.grounding["external_test_request"]
    assert request["enabled"] is True
    assert request["missing"] == []
    assert request["contract"]["external_features_dir"] == (
        "/data/nsclc_external_test/features/virchow2/paramsabc"
    )
    assert request["contract"]["datasets"][0]["paths"] == ["/data/TCGA-NSCLC-subset4"]
    assert request["contract"]["datasets"][1]["paths"] == ["/data/nsclc_external_test"]
    assert config.external_test_enabled is True
    assert config.external_test_contract["external_features_dir"] == (
        "/data/nsclc_external_test/features/virchow2/paramsabc"
    )


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
