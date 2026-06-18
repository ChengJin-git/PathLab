import sys
import types
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pydantic import BaseModel


def _install_openhands_stubs() -> None:
    """Provide the tiny OpenHands surface needed to import run_experiment."""
    openhands = types.ModuleType("openhands")
    sdk = types.ModuleType("openhands.sdk")
    llm = types.ModuleType("openhands.sdk.llm")
    event = types.ModuleType("openhands.sdk.event")
    tool_pkg = types.ModuleType("openhands.sdk.tool")
    schema = types.ModuleType("openhands.sdk.tool.schema")
    tool = types.ModuleType("openhands.sdk.tool.tool")

    class TextContent(BaseModel):
        text: str = ""

    class Action(BaseModel):
        pass

    class Observation(BaseModel):
        content: list = []
        is_error: bool = False

    class ObservationEvent:
        def __init__(self, tool_name="", observation=None):
            self.tool_name = tool_name
            self.observation = observation

    class ToolAnnotations(BaseModel):
        title: str = ""
        readOnlyHint: bool = False
        destructiveHint: bool = False
        openWorldHint: bool = False

    class ToolExecutor:
        pass

    class ToolDefinition:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

        def __class_getitem__(cls, _item):
            return cls

    llm.TextContent = TextContent
    event.ObservationEvent = ObservationEvent
    schema.Action = Action
    schema.Observation = Observation
    tool.ToolAnnotations = ToolAnnotations
    tool.ToolExecutor = ToolExecutor
    tool.ToolDefinition = ToolDefinition
    sys.modules.setdefault("openhands", openhands)
    sys.modules.setdefault("openhands.sdk", sdk)
    sys.modules.setdefault("openhands.sdk.llm", llm)
    sys.modules.setdefault("openhands.sdk.event", event)
    sys.modules.setdefault("openhands.sdk.tool", tool_pkg)
    sys.modules.setdefault("openhands.sdk.tool.schema", schema)
    sys.modules.setdefault("openhands.sdk.tool.tool", tool)


_install_openhands_stubs()

from pathscientist.tools.run_experiment import (
    _build_env_vars_for_test,
    _materialize_durable_model_artifact_for_test,
)
from pathscientist.orchestrator.runner import (
    _best_run_model_path_from_state,
    _promote_embedded_external_validation,
    _run_record_from_tracker_entry,
)
from pathscientist.orchestrator.types import (
    ResearchObjective,
    ResearchSessionState,
)


def test_external_test_resolves_best_run_model_path_from_history(tmp_path):
    """best_run external tests should survive after last_experiment is cleared."""
    model_path = tmp_path / "output" / "runs" / "run_best" / "best_model.pth"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"checkpoint")

    config = SimpleNamespace(
        data_mounts={},
        external_test_contract={"model_source": "best_run"},
        planned_data_output_dir="",
        planned_feature_wsi_dir="",
        planned_feature_extractor="",
        planned_mil_model="",
        run_history=[
            {
                "run_id": "run_old",
                "committed": True,
                "metric_value": 0.80,
                "model_path": str(tmp_path / "missing.pth"),
            },
            {
                "run_id": "run_best",
                "committed": True,
                "metric_value": 0.94,
                "model_path": str(model_path),
                "pathlab": {"model_path": str(model_path)},
            },
        ],
    )

    env = _build_env_vars_for_test(
        config=config,
        run_dir=tmp_path / "external_run",
        script_text="print('external')",
        run_kind="external_test",
        last_experiment=None,
    )

    assert env["PATHSCIENTIST_MODEL_PATH"] == str(model_path)


def test_run_record_preserves_model_metadata_for_best_run_resolution(tmp_path):
    model_path = tmp_path / "output" / "runs" / "run_best" / "best_model.pth"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"checkpoint")

    entry = {
        "run_id": "run_best",
        "metrics": {"auc": 0.94},
        "committed": True,
        "run_dir": "output/runs/run_best",
        "data_output_dir": str(tmp_path / "output"),
        "model_path": str(model_path),
        "pathlab": {"model_path": str(model_path), "training_task_id": "task_123"},
        "run_kind": "training",
    }
    record = _run_record_from_tracker_entry(
        entry=entry,
        iteration=0,
        metric_name="auc",
        metric_value=0.94,
        committed=True,
        run_id="run_best",
    )

    state = ResearchSessionState.create(
        session_id="s1",
        conversation_id=UUID("00000000-0000-0000-0000-000000000001"),
        objective=ResearchObjective(question="external test", success_metric="auc"),
    )
    state.record_run(record)

    assert state.run_history[0].model_path == str(model_path)
    assert state.run_history[0].pathlab["training_task_id"] == "task_123"
    assert _best_run_model_path_from_state(state) == str(model_path)


def test_best_run_model_path_falls_back_to_latest_successful_model(tmp_path):
    """external_test should still have a model after a zero/null-AUC debug run."""
    model_path = tmp_path / "model_artifacts" / "sess" / "run_zero" / "best_model.pth"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"checkpoint")

    config = SimpleNamespace(
        data_mounts={},
        external_test_contract={"model_source": "best_run"},
        planned_data_output_dir="",
        planned_feature_wsi_dir="",
        planned_feature_extractor="",
        planned_mil_model="",
        run_history=[
            {
                "run_id": "run_zero",
                "committed": False,
                "metric_value": 0.0,
                "metrics": {"auc": None, "internal_test": {"auc": None}},
                "model_path": str(model_path),
                "run_kind": "training",
            }
        ],
    )

    env = _build_env_vars_for_test(
        config=config,
        run_dir=tmp_path / "external_run",
        script_text="print('external')",
        run_kind="external_test",
        last_experiment=None,
    )

    assert env["PATHSCIENTIST_MODEL_PATH"] == str(model_path)



def test_state_best_run_model_path_falls_back_to_latest_successful_model(tmp_path):
    model_path = tmp_path / "model_artifacts" / "sess" / "run_zero" / "best_model.pth"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"checkpoint")

    state = ResearchSessionState.create(
        session_id="s1",
        conversation_id=UUID("00000000-0000-0000-0000-000000000002"),
        objective=ResearchObjective(question="external test", success_metric="auc"),
    )
    state.record_run(
        _run_record_from_tracker_entry(
            entry={
                "run_id": "run_zero",
                "metrics": {"auc": None, "internal_test": {"auc": None}},
                "committed": False,
                "model_path": str(model_path),
                "run_kind": "training",
            },
            iteration=0,
            metric_name="auc",
            metric_value=0.0,
            committed=False,
            run_id="run_zero",
        )
    )

    assert _best_run_model_path_from_state(state) == str(model_path)



def test_durable_model_artifact_survives_workspace_revert_path(tmp_path):
    workspace = tmp_path / "workspace"
    run_dir = workspace / "output" / "runs" / "run_zero"
    run_dir.mkdir(parents=True)
    source = run_dir / "best_model.pth"
    source.write_bytes(b"checkpoint")

    config = SimpleNamespace(data_mounts={})
    durable = _materialize_durable_model_artifact_for_test(
        config=config,
        workspace_root=workspace,
        session_id="sess123",
        run_id="run_zero",
        model_path=str(source),
    )

    assert durable
    durable_path = Path(durable)
    assert durable_path.exists()
    assert durable_path.read_bytes() == b"checkpoint"
    assert workspace not in durable_path.parents
    artifact_root = durable_path.parents[2]
    assert config.data_mounts[str(artifact_root)] == str(artifact_root)



def test_embedded_external_validation_promoted_to_session_external_test(tmp_path):
    model_path = tmp_path / "model_artifacts" / "sess" / "run_train" / "best_model.pth"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"checkpoint")

    state = ResearchSessionState.create(
        session_id="s1",
        conversation_id=UUID("00000000-0000-0000-0000-000000000003"),
        objective=ResearchObjective(question="external test", success_metric="auc"),
    )
    record = _run_record_from_tracker_entry(
        entry={
            "run_id": "run_train",
            "metrics": {
                "auc": None,
                "internal_test": {"accuracy": 0.0, "auc": None},
                "external_validation": {
                    "status": "ok",
                    "coverage": {"usable_count": 2, "missing_feature_count": 0},
                    "metrics": {"accuracy": 0.5, "auc": 0.0},
                },
            },
            "committed": False,
            "model_path": str(model_path),
            "run_kind": "training",
        },
        iteration=0,
        metric_name="auc",
        metric_value=0.0,
        committed=False,
        run_id="run_train",
    )
    state.record_run(record)

    promoted = _promote_embedded_external_validation(state, record)

    assert promoted is True
    assert state.external_test["status"] == "completed"
    assert state.external_test["run_id"] == "run_train"
    assert state.external_test["metrics"]["accuracy"] == 0.5
    assert state.external_test["coverage"]["missing_feature_count"] == 0
    assert state.external_test_history[-1] == state.external_test
