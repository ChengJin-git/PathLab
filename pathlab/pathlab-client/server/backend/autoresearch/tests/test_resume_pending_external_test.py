"""Regression tests for resume with a queued external_test step."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from autoresearch.config import AutoResearchConfig
from autoresearch.orchestrator.types import (
    STAGE_EXECUTION,
    ResearchObjective,
    ResearchSessionState,
)


class _StopAfterFirstBrief(Exception):
    """Stop the runner after it has sent the resumed execution brief."""


class _FakeConversation:
    def __init__(self):
        self.state = SimpleNamespace(events=[], agent_state={})

    def send_message(self, message):
        raise NotImplementedError

    def run(self):
        raise NotImplementedError


def _make_test_config(tmp_path: Path) -> AutoResearchConfig:
    return AutoResearchConfig(
        workspace_dir=str(tmp_path / "workspace"),
        output_dir=str(tmp_path / "output"),
        gpu_ids=[],
        sandbox_mode="local",
        max_iterations=2,
        primary_metric="auc",
        conversation_persistence_dir=str(tmp_path),
    )


def _build_fake_runtime(tmp_path: Path):
    from autoresearch.runtime.session_registry import SessionDeps, register_session

    workspace_dir = tmp_path / "workspace"
    output_dir = tmp_path / "output"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    session_id = uuid4().hex[:12]
    conversation_id = uuid4()
    session = SimpleNamespace(
        session_id=session_id,
        conversation_id=conversation_id,
        workspace_dir=workspace_dir,
        output_dir=output_dir,
        persistence_root=tmp_path,
    )
    workspace = SimpleNamespace(root=workspace_dir)
    tracker = SimpleNamespace(history=[], best_value=0.0, iteration=0)
    config = _make_test_config(tmp_path)
    register_session(
        session_id,
        SessionDeps(
            workspace=workspace,
            tracker=tracker,
            config=config,
            iteration_state=SimpleNamespace(history=[]),
        ),
    )
    conversation = _FakeConversation()
    return config, session, conversation


def test_external_test_resume_state_round_trips():
    """Persistence must preserve queued external validation state."""
    from autoresearch.orchestrator.state_bridge import (
        dump_research_session_state,
        load_research_session_state,
    )

    external_contract = {
        "external_task_type": "mil_classification",
        "external_features_dir": "/data/external/features",
        "external_splits_file": "/data/external/splits.json",
        "model_source": "best_run",
    }
    state = ResearchSessionState.create(
        session_id="session_ext7",
        conversation_id=uuid4(),
        objective=ResearchObjective(question="resume external validation"),
    )
    state.stage = STAGE_EXECUTION
    state.grounding = {
        "external_test_request": {
            "requested": True,
            "enabled": True,
            "status": "ready",
            "missing": [],
            "contract": dict(external_contract),
        }
    }
    state.execution_plan = {
        "status": "ready",
        "current_step": 1,
        "steps": [
            {"id": "train_downstream", "skill": "mil_classification"},
            {"id": "external_test", "skill": "external_test", "inputs": external_contract},
        ],
    }
    state.external_test_history = [
        {"run_id": "external_run_001", "metrics": {"auc": 0.91}},
    ]

    restored = load_research_session_state(dump_research_session_state(state))

    assert restored is not None
    assert restored.stage == STAGE_EXECUTION
    assert restored.grounding["external_test_request"]["contract"] == external_contract
    assert restored.execution_plan["steps"][1]["skill"] == "external_test"
    assert restored.execution_plan["current_step"] == 1
    assert restored.external_test_history[0]["run_id"] == "external_run_001"


def test_resume_external_test_config_keeps_step_model_path(tmp_path):
    """Runtime config restore must preserve model_path injected into the step."""
    from autoresearch.orchestrator.runner import _sync_external_test_config_from_state

    config = _make_test_config(tmp_path)
    grounding_contract = {
        "external_task_type": "mil_classification",
        "external_features_dir": "/data/external/features",
        "external_splits_file": "/data/external/splits.json",
        "model_source": "best_run",
    }
    state = ResearchSessionState.create(
        session_id="session_ext7_model",
        conversation_id=uuid4(),
        objective=ResearchObjective(question="resume external model path"),
    )
    state.grounding = {
        "external_test_request": {
            "requested": True,
            "enabled": True,
            "status": "ready",
            "missing": [],
            "contract": dict(grounding_contract),
        }
    }
    state.execution_plan = {
        "status": "ready",
        "current_step": 1,
        "steps": [
            {"id": "train_downstream", "skill": "mil_classification"},
            {
                "id": "external_test",
                "skill": "external_test",
                "inputs": {
                    **grounding_contract,
                    "model_path": "/tmp/best_model.pt",
                },
            },
        ],
    }

    _sync_external_test_config_from_state(state, config)

    assert config.external_test_enabled is True
    assert config.external_test_contract["model_path"] == "/tmp/best_model.pt"
    assert (
        state.grounding["external_test_request"]["contract"]["model_path"]
        == "/tmp/best_model.pt"
    )


def test_resume_execution_keeps_pending_external_test_step(tmp_path, monkeypatch):
    """Resume must not rebuild over a persisted external_test execution step."""
    from autoresearch.orchestrator import runner as runner_module
    from autoresearch.orchestrator.runner import continue_research_session

    config, session, conversation = _build_fake_runtime(tmp_path)

    external_contract = {
        "external_task_type": "mil_classification",
        "external_features_dir": "/data/external/features",
        "external_splits_file": "/data/external/splits.json",
        "model_source": "best_run",
        "datasets": [
            {
                "role": "external",
                "dataset_name": "External Cohort",
                "paths": ["/data/external"],
            }
        ],
    }
    external_step = {
        "id": "external_test",
        "skill": "external_test",
        "inputs": dict(external_contract),
        "outputs": {"report": "$OUTPUT_DIR/external_test_report.json"},
    }
    persisted_plan = {
        "primary_skill": "mil_classification",
        "status": "ready",
        "current_step": 1,
        "steps": [
            {"id": "train_downstream", "skill": "mil_classification", "inputs": {}},
            external_step,
        ],
    }
    state = ResearchSessionState.create(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        objective=ResearchObjective(
            question="Train internally, then validate on the external cohort",
            success_metric="auc",
        ),
    )
    state.stage = STAGE_EXECUTION
    state.max_iterations = 1
    state.iteration_index = 1
    state.grounding = {
        "selected_skill": "mil_classification",
        "task_profile": {
            "task_type": "mil_classification",
            "asset_level": "slide",
            "input_modality": "features",
            "label_granularity": "slide",
            "preferred_skill": "mil_classification",
        },
        "external_test_request": {
            "source": "llm",
            "requested": True,
            "enabled": True,
            "status": "ready",
            "missing": [],
            "contract": dict(external_contract),
        },
        "execution_plan": dict(persisted_plan),
    }
    state.execution_plan = dict(persisted_plan)

    def fail_if_replanned(*args, **kwargs):
        raise AssertionError(
            "continue_research_session must not rebuild a persisted pending "
            "external_test execution plan on resume"
        )

    captured: dict[str, str] = {}

    def fake_send_message(message):
        captured["brief"] = message
        raise _StopAfterFirstBrief()

    monkeypatch.setattr(
        runner_module,
        "_prepare_data_readiness_and_execution_plan",
        fail_if_replanned,
    )
    monkeypatch.setattr(conversation, "send_message", fake_send_message)
    monkeypatch.setattr(conversation, "run", lambda: None)

    try:
        continue_research_session(
            config,
            state,
            session,
            conversation,
            auto_approve=True,
        )
    except _StopAfterFirstBrief:
        pass

    assert state.stage == STAGE_EXECUTION
    assert state.execution_plan["current_step"] == 1
    assert state.execution_plan["steps"][1]["skill"] == "external_test"
    assert config.external_test_enabled is True
    assert config.external_test_contract["external_features_dir"] == "/data/external/features"
    assert "External validation requested" in captured["brief"]
    assert "External test contract" in captured["brief"]
