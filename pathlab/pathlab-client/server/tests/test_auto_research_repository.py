from types import SimpleNamespace

import pytest

from backend.database.repositories.auto_research import AutoResearchRepository
from gateway import pathscientist_persistence


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDB:
    def __init__(self, scalar=None):
        self.scalar = scalar
        self.added = []
        self.flushed = 0
        self.refreshed = []
        self.executed = []

    async def execute(self, statement):
        self.executed.append(statement)
        return _ScalarResult(self.scalar)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushed += 1

    async def refresh(self, value):
        self.refreshed.append(value)


@pytest.mark.asyncio
async def test_upsert_experiment_by_run_id_updates_existing_row():
    existing = SimpleNamespace(
        id=1,
        session_id="s1",
        training_task_id="run_old",
        status="pending",
        metrics={},
        created_at=object(),
    )
    db = _FakeDB(scalar=existing)

    result = await AutoResearchRepository.upsert_experiment_by_run_id(
        db,
        {
            "session_id": "s1",
            "training_task_id": "run_a",
            "status": "completed",
            "metrics": {"auc": 0.91},
        },
    )

    assert result is existing
    assert existing.training_task_id == "run_a"
    assert existing.status == "completed"
    assert existing.metrics == {"auc": 0.91}
    assert not db.added
    assert db.flushed == 1


@pytest.mark.asyncio
async def test_append_event_once_skips_existing_sequence():
    db = _FakeDB(scalar=123)

    inserted = await AutoResearchRepository.append_event_once(
        db,
        "s1",
        {"event_type": "state", "event_data": {"kind": "state"}},
        7,
    )

    assert inserted is False
    assert not db.added


def test_session_payload_keeps_large_artifacts_as_paths_and_metrics_as_json():
    state = {
        "stage": "completed",
        "objective": {"question": "train model", "success_metric": "auc"},
        "best_run_id": "run_a",
        "best_metric_value": 0.93,
        "run_history": [
            {
                "run_id": "run_a",
                "iteration": 1,
                "metric_name": "auc",
                "metric_value": 0.93,
                "committed": True,
                "metrics": {"auc": 0.93},
                "run_dir": "output/runs/run_a",
                "model_path": "output/runs/run_a/best_model.pth",
            }
        ],
    }

    payload = pathscientist_persistence._session_payload(
        session_id="s1",
        user_id="u1",
        question="train model",
        status="completed",
        stage="completed",
        state=state,
        max_iterations=5,
        metric="auc",
        model="gpt-5.5",
        workspace_path="/tmp/session_s1",
    )

    assert payload["session_id"] == "s1"
    assert payload["best_metric"] == 0.93
    assert payload["best_experiment"]["run_id"] == "run_a"
    assert payload["workspace_path"] == "/tmp/session_s1"
    assert payload["event_source_version"] == "gateway-v1"
    assert payload["resume_available"] is False
    assert payload["comparison_results"]["run_history"][0]["model_path"].endswith(
        "best_model.pth"
    )


def test_session_payload_records_recovery_metadata_and_review_content(tmp_path):
    conversation_dir = tmp_path / "convabc"
    conversation_dir.mkdir()
    (conversation_dir / "base_state.json").write_text("{}", encoding="utf-8")
    state = {
        "stage": "interrupted",
        "conversation_id": "convabc",
        "persistence_dir": str(conversation_dir),
        "workspace_dir": str(tmp_path / "workspace"),
        "review_history": [{"decision": "continue_execution"}],
        "external_test_history": [{"run_id": "external_1", "auc": 0.82}],
        "integrity_report": {"status": "passed"},
    }

    payload = pathscientist_persistence._session_payload(
        session_id="s1",
        user_id="u1",
        question="resume me",
        status="interrupted",
        stage="interrupted",
        state=state,
        max_iterations=3,
        metric="auc",
        model="gpt-5.5",
        workspace_path="",
    )

    assert payload["conversation_id"] == "convabc"
    assert payload["persistence_dir"] == str(conversation_dir)
    assert payload["workspace_path"].endswith("workspace")
    assert payload["resume_available"] is True
    assert payload["recovery_metadata"]["integrity_report"] == {"status": "passed"}
    assert payload["comparison_results"]["review_history"][0]["decision"] == "continue_execution"
    assert payload["comparison_results"]["external_test_history"][0]["run_id"] == "external_1"


def test_experiment_payload_uses_run_id_as_training_task_id():
    payloads = pathscientist_persistence._experiment_payloads(
        session_id="s1",
        state={
            "run_history": [
                {
                    "run_id": "run_a",
                    "metrics": {"auc": 0.9},
                    "committed": True,
                }
            ]
        },
        metric="auc",
    )

    assert payloads == [
        {
            "session_id": "s1",
            "experiment_name": "run_a",
            "training_task_id": "run_a",
            "dataset_id": None,
            "feature_extractor": None,
            "aggregator": None,
            "hyperparams": {
                "metric_name": "auc",
                "committed": True,
            },
            "status": "completed",
            "metrics": {"auc": 0.9},
            "iteration": 1,
        }
    ]
