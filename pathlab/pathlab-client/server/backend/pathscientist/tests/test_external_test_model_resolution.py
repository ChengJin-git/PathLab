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
    schema.Action = Action
    schema.Observation = Observation
    tool.ToolAnnotations = ToolAnnotations
    tool.ToolExecutor = ToolExecutor
    tool.ToolDefinition = ToolDefinition
    sys.modules.setdefault("openhands", openhands)
    sys.modules.setdefault("openhands.sdk", sdk)
    sys.modules.setdefault("openhands.sdk.llm", llm)
    sys.modules.setdefault("openhands.sdk.tool", tool_pkg)
    sys.modules.setdefault("openhands.sdk.tool.schema", schema)
    sys.modules.setdefault("openhands.sdk.tool.tool", tool)


_install_openhands_stubs()

from pathscientist.tools.run_experiment import _build_env_vars_for_test
from pathscientist.orchestrator.runner import (
    _best_run_model_path_from_state,
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
