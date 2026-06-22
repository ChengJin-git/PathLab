# pyright: reportAny=false, reportArgumentType=false, reportAttributeAccessIssue=false, reportImplicitOverride=false, reportImplicitRelativeImport=false, reportIncompatibleMethodOverride=false, reportMissingParameterType=false, reportMissingTypeArgument=false, reportPrivateLocalImportUsage=false, reportPrivateUsage=false, reportUnannotatedClassAttribute=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnusedParameter=false

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.database.models import TrainedModel, TrainingTask


SERVER_ROOT = Path(__file__).resolve().parents[1]


async def _not_implemented_repository_method(*args, **kwargs):
    raise NotImplementedError


class _DataGroupRepositoryStub:
    get_or_create = staticmethod(_not_implemented_repository_method)


class _WSIRepositoryStub:
    bulk_update_feature_extracted = staticmethod(_not_implemented_repository_method)


def install_lightweight_repositories_import():
    package = types.ModuleType("backend.database.repositories")
    package.__path__ = [str(SERVER_ROOT / "backend" / "database" / "repositories")]
    package.DataGroupRepository = _DataGroupRepositoryStub
    package.WSIRepository = _WSIRepositoryStub
    sys.modules["backend.database.repositories"] = package

    module_name = "backend.database.repositories.auto_research"
    spec = importlib.util.spec_from_file_location(
        module_name,
        SERVER_ROOT / "backend" / "database" / "repositories" / "auto_research.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    package.AutoResearchRepository = module.AutoResearchRepository
    return module.AutoResearchRepository


AutoResearchRepository = install_lightweight_repositories_import()
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
        self.commits = 0

    async def execute(self, statement):
        self.executed.append(statement)
        return _ScalarResult(self.scalar)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushed += 1

    async def refresh(self, value):
        self.refreshed.append(value)

    async def commit(self):
        self.commits += 1


class _ModelRegistrationDB(_FakeDB):
    def __init__(self):
        super().__init__()
        self.by_type: dict[type, dict[str, object]] = {}

    def add(self, value):
        super().add(value)
        if isinstance(value, TrainingTask):
            self.by_type.setdefault(TrainingTask, {})[value.task_id] = value
        if isinstance(value, TrainedModel):
            self.by_type.setdefault(TrainedModel, {})[value.model_id] = value


class _SafeSession:
    def __init__(self, db):
        self.db = db
        self.commits = 0

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_get_session_scopes_query_by_user_id_when_provided():
    db = _FakeDB(scalar=None)

    result = await AutoResearchRepository.get_session(
        db,
        "session-owned",
        user_id="user-other",
    )

    assert result is None
    compiled = str(db.executed[-1].compile(compile_kwargs={"literal_binds": True}))
    assert "auto_research_sessions.session_id = 'session-owned'" in compiled
    assert "auto_research_sessions.user_id = 'user-other'" in compiled


@pytest.mark.asyncio
async def test_delete_session_scopes_query_by_user_id_when_provided():
    class _DeleteResult:
        rowcount = 0

    class _DeleteDB(_FakeDB):
        async def execute(self, statement):
            self.executed.append(statement)
            return _DeleteResult()

    db = _DeleteDB()

    deleted = await AutoResearchRepository.delete_session(
        db,
        "session-owned",
        user_id="user-other",
    )

    assert deleted is False
    compiled = str(db.executed[-1].compile(compile_kwargs={"literal_binds": True}))
    assert "auto_research_sessions.session_id = 'session-owned'" in compiled
    assert "auto_research_sessions.user_id = 'user-other'" in compiled


@pytest.mark.asyncio
async def test_upsert_session_does_not_overwrite_existing_owner():
    existing = SimpleNamespace(
        id=1,
        session_id="s1",
        user_id="user-owner",
        status="running",
        created_at=object(),
    )
    db = _FakeDB(scalar=existing)

    result = await AutoResearchRepository.upsert_session(
        db,
        {
            "session_id": "s1",
            "user_id": "user-other",
            "status": "completed",
        },
    )

    assert result is existing
    assert existing.user_id == "user-owner"
    assert existing.status == "completed"
    assert db.flushed == 1


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


@pytest.mark.asyncio
async def test_persist_event_syncs_session_summary_from_state_event(monkeypatch):
    db = _FakeDB()
    captured: dict[str, dict] = {}

    async def fake_append_event_once(_db, session_id, payload, sequence):
        captured["event"] = {
            "session_id": session_id,
            "payload": payload,
            "sequence": sequence,
        }
        return True

    async def fake_upsert_session(_db, payload):
        captured["session"] = payload
        return SimpleNamespace(**payload)

    monkeypatch.setattr(
        pathscientist_persistence,
        "safe_session",
        lambda: _SafeSession(db),
    )
    monkeypatch.setattr(
        pathscientist_persistence.AutoResearchRepository,
        "append_event_once",
        fake_append_event_once,
    )
    monkeypatch.setattr(
        pathscientist_persistence.AutoResearchRepository,
        "upsert_session",
        fake_upsert_session,
    )

    await pathscientist_persistence._persist_event(
        session_id="s1",
        sequence=11,
        event={
            "seq": 11,
            "kind": "state",
            "status": "running",
            "stage": "execution",
            "state": {
                "stage": "execution",
                "iteration_index": 1,
                "max_iterations": 1,
                "objective": {"question": "train nsclc", "success_metric": "auc"},
            },
        },
    )

    assert captured["event"]["sequence"] == 11
    assert captured["session"]["session_id"] == "s1"
    assert captured["session"]["status"] == "running"
    assert captured["session"]["phase"] == "execution"
    assert captured["session"]["current_iteration"] == 1
    assert captured["session"]["max_iterations"] == 1
    assert captured["session"]["research_question"] == "train nsclc"


def test_state_event_status_infers_terminal_stage_without_explicit_status():
    status = pathscientist_persistence._event_status(
        {"kind": "state"},
        state={"stage": "completed"},
        existing_status="running",
    )

    assert status == "completed"


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


def test_experiment_payload_records_pathlab_artifact_linkage():
    payloads = pathscientist_persistence._experiment_payloads(
        session_id="s1",
        state={
            "run_history": [
                {
                    "run_id": "run_a",
                    "pathlab_training_task_id": "task_123",
                    "metrics": {"auc": 0.91},
                    "committed": True,
                    "run_kind": "training",
                    "run_dir": "uploads/pathscientist/session_abc/output/runs/run_a",
                    "model_path": "uploads/training/task_123/models/best_model.pth",
                    "data_output_dir": "uploads/features/conch/abc123",
                    "data_output_artifacts": [
                        "uploads/features/conch/abc123/slide_1.pt",
                    ],
                    "pathlab": {
                        "uploads_dir": "uploads",
                        "training_task_id": "task_123",
                        "training_dir": "uploads/training/task_123",
                        "features_dir": "uploads/features/conch/abc123",
                        "model_path": "uploads/training/task_123/models/best_model.pth",
                    },
                }
            ]
        },
        metric="auc",
    )

    assert payloads[0]["training_task_id"] == "task_123"
    hyperparams = payloads[0]["hyperparams"]
    assert hyperparams["pathlab_linkage"] == {
        "uploads_dir": "uploads",
        "training_task_id": "task_123",
        "training_dir": "uploads/training/task_123",
        "features_dir": "uploads/features/conch/abc123",
        "model_path": "uploads/training/task_123/models/best_model.pth",
    }
    assert hyperparams["run_id"] == "run_a"
    assert hyperparams["run_kind"] == "training"


def test_session_payload_compact_run_exposes_pathlab_linkage():
    state = {
        "stage": "completed",
        "run_history": [
            {
                "run_id": "run_a",
                "pathlab_training_task_id": "task_123",
                "metrics": {"auc": 0.91},
                "committed": True,
                "pathlab": {
                    "training_task_id": "task_123",
                    "training_dir": "uploads/training/task_123",
                    "features_dir": "uploads/features/conch/abc123",
                },
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
        max_iterations=1,
        metric="auc",
        model="gpt-5.5",
        workspace_path="/tmp/session_s1",
    )

    compact = payload["comparison_results"]["run_history"][0]
    assert compact["pathlab_linkage"] == {
        "training_task_id": "task_123",
        "training_dir": "uploads/training/task_123",
        "features_dir": "uploads/features/conch/abc123",
    }


@pytest.mark.asyncio
async def test_persist_session_state_records_pathlab_model_registration(monkeypatch):
    db = _FakeDB()
    captured: dict[str, dict] = {}

    async def fake_register(_db, **kwargs):
        return {
            "registered": True,
            "training_task_id": "pathscientist_s1_run_a",
            "model_id": "pathscientist_s1_run_a_model",
        }

    async def fake_upsert_session(_db, payload):
        captured["session"] = payload
        return SimpleNamespace(**payload)

    async def fake_upsert_experiment_by_run_id(_db, payload):
        captured.setdefault("experiments", []).append(payload)
        return SimpleNamespace(**payload)

    monkeypatch.setattr(
        pathscientist_persistence,
        "safe_session",
        lambda: _SafeSession(db),
    )
    monkeypatch.setattr(
        pathscientist_persistence,
        "_safe_register_pathlab_trained_model",
        fake_register,
    )
    monkeypatch.setattr(
        pathscientist_persistence.AutoResearchRepository,
        "upsert_session",
        fake_upsert_session,
    )
    monkeypatch.setattr(
        pathscientist_persistence.AutoResearchRepository,
        "upsert_experiment_by_run_id",
        fake_upsert_experiment_by_run_id,
    )

    await pathscientist_persistence._persist_session_state(
        session_id="s1",
        user_id="u1",
        question="train model",
        status="completed",
        stage="completed",
        state={"stage": "completed", "run_history": []},
        max_iterations=1,
        metric="auc",
        model="gpt-5.5",
        workspace_path="/tmp/session_s1",
    )

    registration = captured["session"]["recovery_metadata"][
        "pathlab_model_registration"
    ]
    assert registration["registered"] is True
    assert registration["model_id"] == "pathscientist_s1_run_a_model"


def test_pathscientist_model_candidate_requires_completed_training_model(tmp_path):
    model_path = tmp_path / "best_model.pth"
    model_path.write_text("weights", encoding="utf-8")

    state = {
        "stage": "completed",
        "best_run_id": "run_good",
        "run_history": [
            {
                "run_id": "run_external",
                "committed": True,
                "run_kind": "external_test",
                "model_path": str(model_path),
            },
            {
                "run_id": "run_quick",
                "committed": True,
                "quick_check": True,
                "model_path": str(model_path),
            },
            {
                "run_id": "run_good",
                "committed": True,
                "exit_code": 0,
                "metric_name": "auc",
                "metric_value": 0.87,
                "metrics": {"auc": 0.87},
                "model_path": str(model_path),
                "feature_extractor": "conch",
                "aggregator": "ABMIL",
            },
        ],
    }

    candidate = pathscientist_persistence._pathlab_model_candidate(
        state=state,
        status="completed",
        stage="completed",
    )

    assert candidate is not None
    assert candidate["run_id"] == "run_good"
    assert candidate["model_path"] == str(model_path)


def test_pathscientist_model_candidate_skips_non_terminal_or_missing_model(tmp_path):
    missing_path = tmp_path / "missing.pth"

    assert (
        pathscientist_persistence._pathlab_model_candidate(
            state={
                "run_history": [
                    {
                        "run_id": "run_a",
                        "committed": True,
                        "exit_code": 0,
                        "model_path": str(missing_path),
                    }
                ]
            },
            status="running",
            stage="execution",
        )
        is None
    )

    assert (
        pathscientist_persistence._pathlab_model_candidate(
            state={
                "run_history": [
                    {
                        "run_id": "run_a",
                        "committed": True,
                        "exit_code": 0,
                        "model_path": str(missing_path),
                    }
                ]
            },
            status="completed",
            stage="completed",
        )
        is None
    )


def test_pathscientist_model_classes_extracts_common_mapping_shapes():
    assert pathscientist_persistence._model_classes(
        {},
        {
            "metrics": {
                "class_to_idx": {"LUAD": 0, "LUSC": 1},
            }
        },
    ) == ["LUAD", "LUSC"]

    assert pathscientist_persistence._model_classes(
        {},
        {
            "metrics": {
                "idx_to_class": {"0": "tumor", "1": "normal"},
            }
        },
    ) == ["tumor", "normal"]


@pytest.mark.asyncio
async def test_register_pathscientist_model_links_features_and_marks_wsi_extracted(
    tmp_path, monkeypatch
):
    features_dir = tmp_path / "features" / "virchow2" / "paramsabc"
    features_dir.mkdir(parents=True)
    for slide_id in ("slide_001", "slide_002"):
        (features_dir / f"{slide_id}.pt").write_bytes(b"feature")
    model_path = tmp_path / "runs" / "run_a" / "best_model.pth"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"model")

    db = _ModelRegistrationDB()
    captured_group: dict[str, object] = {}
    captured_feature_flags: dict[str, object] = {}

    async def fake_get_by_id(_db, model_cls, pk_field, pk_value):
        return _db.by_type.get(model_cls, {}).get(pk_value)

    async def fake_get_or_create(
        _db,
        data_type,
        aggregation_level,
        task_type,
        name=None,
        description=None,
    ):
        captured_group.update(
            {
                "data_type": data_type,
                "aggregation_level": aggregation_level,
                "task_type": task_type,
                "name": name,
                "description": description,
            }
        )
        return SimpleNamespace(group_id="group_wsi_file_classification")

    async def fake_bulk_update_feature_extracted(_db, wsi_ids, extracted=True):
        captured_feature_flags["wsi_ids"] = list(wsi_ids)
        captured_feature_flags["extracted"] = extracted
        return len(wsi_ids)

    monkeypatch.setattr(pathscientist_persistence, "_get_by_pk", fake_get_by_id)
    monkeypatch.setattr(
        pathscientist_persistence.DataGroupRepository,
        "get_or_create",
        fake_get_or_create,
    )
    monkeypatch.setattr(
        pathscientist_persistence.WSIRepository,
        "bulk_update_feature_extracted",
        fake_bulk_update_feature_extracted,
    )

    result = await pathscientist_persistence._register_pathlab_trained_model(
        db,
        session_id="session-abc",
        user_id="user-1",
        question="train tcga nsclc with ABMIL",
        state={
            "stage": "completed",
            "best_run_id": "run_a",
            "run_history": [
                {
                    "run_id": "run_a",
                    "committed": True,
                    "exit_code": 0,
                    "model_path": str(model_path),
                    "feature_extractor": "virchow2",
                    "aggregator": "ABMIL",
                    "pathlab": {"features_dir": str(features_dir)},
                }
            ],
        },
        status="completed",
        stage="completed",
        metric="auc",
    )

    task_features_dir = (
        tmp_path
        / "training"
        / "pathscientist_session-abc_run_a"
        / "features"
    )
    assert result["features_registered"] == 2
    assert result["task_features_dir"] == str(task_features_dir)
    for slide_id in ("slide_001", "slide_002"):
        link = task_features_dir / f"{slide_id}.pt"
        assert link.is_symlink()
        assert link.resolve() == features_dir / f"{slide_id}.pt"
    assert captured_feature_flags == {
        "wsi_ids": ["slide_001", "slide_002"],
        "extracted": True,
    }
    task = db.by_type[TrainingTask]["pathscientist_session-abc_run_a"]
    assert task.preprocessing_config["task_features_dir"] == str(task_features_dir)


@pytest.mark.asyncio
async def test_register_pathscientist_model_upserts_training_task_and_model(
    monkeypatch, tmp_path
):
    db = _ModelRegistrationDB()
    model_path = tmp_path / "best_model.pth"
    model_path.write_text("weights", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    captured_group = {}

    async def fake_get_by_id(_db, model_cls, pk_field, pk_value):
        return _db.by_type.get(model_cls, {}).get(pk_value)

    async def fake_get_or_create(
        _db,
        data_type,
        aggregation_level,
        task_type,
        name=None,
        description=None,
    ):
        captured_group.update(
            {
                "data_type": data_type,
                "aggregation_level": aggregation_level,
                "task_type": task_type,
                "name": name,
                "description": description,
            }
        )
        return SimpleNamespace(group_id="group_wsi_file_classification")

    monkeypatch.setattr(
        pathscientist_persistence,
        "_get_by_pk",
        fake_get_by_id,
    )
    monkeypatch.setattr(
        pathscientist_persistence.DataGroupRepository,
        "get_or_create",
        fake_get_or_create,
    )

    result = await pathscientist_persistence._register_pathlab_trained_model(
        db,
        session_id="session-abc",
        user_id="user-1",
        question="train tcga nsclc with ABMIL",
        state={
            "stage": "completed",
            "best_run_id": "run_a",
            "run_history": [
                {
                    "run_id": "run_a",
                    "iteration": 2,
                    "committed": True,
                    "exit_code": 0,
                    "metric_name": "auc",
                    "metric_value": 0.91,
                    "metrics": {"auc": 0.91, "accuracy": 0.8},
                    "model_path": str(model_path),
                    "feature_extractor": "conch",
                    "aggregator": "ABMIL",
                    "pathlab": {
                        "training_task_id": "pathlab_task_existing",
                        "features_dir": str(tmp_path / "features"),
                    },
                }
            ],
        },
        status="completed",
        stage="completed",
        metric="auc",
    )

    assert result["registered"] is True
    assert result["training_task_id"] == "pathscientist_session-abc_run_a"
    assert result["model_id"] == "pathscientist_session-abc_run_a_model"
    assert captured_group["data_type"] == "wsi"
    assert captured_group["aggregation_level"] == "file"
    assert captured_group["task_type"] == "classification"

    task = db.by_type[TrainingTask]["pathscientist_session-abc_run_a"]
    assert task.task_name == "PathScientist: train tcga nsclc with ABMIL"
    assert task.status == "completed"
    assert task.progress == 100
    assert task.preprocessing_config["source"] == "pathscientist"
    assert task.preprocessing_config["features_dir"].endswith("features")
    assert task.model_config["aggregator"] == "ABMIL"

    model = db.by_type[TrainedModel]["pathscientist_session-abc_run_a_model"]
    assert model.task_id == task.task_id
    assert model.user_id == "user-1"
    assert model.model_path == str(model_path)
    assert model.config_path == str(config_path)
    assert model.feature_extractor == "conch"
    assert model.aggregator == "ABMIL"
    assert model.val_metrics == {"auc": 0.91, "accuracy": 0.8}
