from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from helpers import _make_user
from gateway.task_dispatch import build_task_descriptor


def _mock_model_task(task_type: str = "wsi_classification", data_type: str = "wsi") -> MagicMock:
    dg = MagicMock()
    dg.group_id = "group-1"
    dg.task_type = task_type
    dg.data_type = data_type
    dg.aggregation_level = "file"

    task = MagicMock()
    task.task_id = "model-task-1"
    task.task_name = "Model Task"
    task.user_id = "user-1"
    task.data_group = dg
    task.preprocessing_config = {}
    task.model_config = {}
    task.classes = ["A", "B"]
    return task


def _mock_trained_model() -> MagicMock:
    model = MagicMock()
    model.model_id = "model-1"
    model.task_id = "model-task-1"
    model.model_name = "Model One"
    model.is_active = True
    model.user_id = "user-1"
    model.classes = ["A", "B"]
    model.feature_extractor = "resnet50"
    model.aggregator = "mean"
    return model


def _mock_dataset(dataset_id: str = "ds-1") -> MagicMock:
    dg = MagicMock()
    dg.group_id = "group-1"
    dg.task_type = "wsi_classification"
    dg.data_type = "wsi"
    dg.aggregation_level = "file"

    ds = MagicMock()
    ds.dataset_id = dataset_id
    ds.name = "Dataset"
    ds.user_id = "user-1"
    ds.data_group = dg
    ds.is_public = False
    ds.parent_dataset_id = None
    return ds


@pytest.mark.asyncio
async def test_start_batch_inference_enqueues_descriptor_not_local_queue():
    from gateway.models import BatchInferenceRequest
    from gateway.routes.results import start_batch_inference

    model_task = _mock_model_task()
    trained_model = _mock_trained_model()
    dataset = _mock_dataset("ds-unlabeled")
    db = AsyncMock()
    db.add = MagicMock()

    with (
        patch("gateway.routes.results.TrainingTaskRepository.get_by_id", new=AsyncMock(return_value=model_task)),
        patch("gateway.routes.results.TrainedModelRepository.get_by_task_id", new=AsyncMock(return_value=[trained_model])),
        patch("gateway.routes.results._require_task_access", new=AsyncMock()),
        patch("gateway.routes.results.DatasetRepository.get_by_id", new=AsyncMock(return_value=dataset)),
        patch("gateway.routes.results._has_external_validation_dataset_access", new=AsyncMock(return_value=True)),
        patch("gateway.routes.results.check_dataset_gpu_permission", new=AsyncMock(return_value=True)),
        patch("gateway.routes.results.DatasetRepository.get_distinct_label_count", new=AsyncMock(return_value=0)),
        patch("gateway.routes.results.is_worker_healthy", new=AsyncMock(return_value=True)),
        patch("gateway.routes.results.get_task_queue", side_effect=AssertionError("local queue must not be used"), create=True),
        patch("gateway.routes.results.build_task_descriptor", side_effect=build_task_descriptor) as mock_build,
        patch("gateway.routes.results.enqueue_task_descriptor", new=AsyncMock()) as mock_enqueue,
    ):
        result = await start_batch_inference(
            req=BatchInferenceRequest(model_task_id="model-task-1", dataset_id="ds-unlabeled"),
            user=_make_user("admin"),
            db=db,
        )

    assert result["status"] == "pending"
    mock_build.assert_called_once()
    payload = mock_build.call_args.kwargs["payload"]
    assert payload["model_task_id"] == "model-task-1"
    assert payload["model_id"] == "model-1"
    assert payload["dataset_id"] == "ds-unlabeled"
    mock_enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_independent_inference_enqueues_descriptor_not_local_queue():
    from gateway.models import IndependentInferenceRequest
    from gateway.routes.results import start_independent_inference

    model_task = _mock_model_task()
    trained_model = _mock_trained_model()
    dataset = _mock_dataset("ds-unlabeled")
    wsi = MagicMock()
    wsi.wsi_id = "wsi-1"
    wsi.dataset_id = "ds-unlabeled"
    wsi.dataset = dataset
    wsi.user_id = "user-1"
    wsi.data_type = "wsi"

    db = AsyncMock()
    db.add = MagicMock()

    with (
        patch("gateway.routes.results.TrainedModelRepository.get_by_id", new=AsyncMock(return_value=trained_model)),
        patch("gateway.routes.results.TrainingTaskRepository.get_by_id", new=AsyncMock(return_value=model_task)),
        patch("gateway.routes.results._require_task_access", new=AsyncMock()),
        patch("gateway.routes.results._get_elevated_dataset_ids", new=AsyncMock(return_value=[])),
        patch("gateway.routes.results.WSIRepository.get_by_ids_with_dataset", new=AsyncMock(return_value={"wsi-1": wsi})),
        patch("gateway.routes.results.DatasetRepository.get_distinct_label_count", new=AsyncMock(return_value=0)),
        patch("gateway.routes.results._is_wsi_unlabeled_for_independent_inference", new=AsyncMock(return_value=True)),
        patch("gateway.routes.results.is_worker_healthy", new=AsyncMock(return_value=True)),
        patch("gateway.routes.results.get_task_queue", side_effect=AssertionError("local queue must not be used"), create=True),
        patch("gateway.routes.results.build_task_descriptor", side_effect=build_task_descriptor) as mock_build,
        patch("gateway.routes.results.enqueue_task_descriptor", new=AsyncMock()) as mock_enqueue,
    ):
        result = await start_independent_inference(
            req=IndependentInferenceRequest(model_id="model-1", wsi_ids=["wsi-1"]),
            user=_make_user("admin"),
            db=db,
        )

    assert result["status"] == "pending"
    payload = mock_build.call_args.kwargs["payload"]
    assert payload["model_id"] == "model-1"
    assert payload["dataset_id"] == "ds-unlabeled"
    assert payload["wsi_ids"] == ["wsi-1"]
    assert payload["execution_mode"] == "batch_inference"
    mock_enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_external_validation_enqueues_descriptor_not_local_queue():
    from gateway.models import ExternalValidationRequest
    from gateway.routes.results import start_external_validation

    model_task = _mock_model_task()
    trained_model = _mock_trained_model()
    dataset = _mock_dataset("ds-ext")
    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: []))

    with (
        patch("gateway.routes.results.TrainedModelRepository.get_by_id", new=AsyncMock(return_value=trained_model)),
        patch("gateway.routes.results.TrainingTaskRepository.get_by_id", new=AsyncMock(return_value=model_task)),
        patch("gateway.routes.results._require_task_access", new=AsyncMock()),
        patch("gateway.routes.results.DatasetRepository.get_by_id", new=AsyncMock(return_value=dataset)),
        patch("gateway.routes.results._has_external_validation_dataset_access", new=AsyncMock(return_value=True)),
        patch("gateway.routes.results.check_dataset_gpu_permission", new=AsyncMock(return_value=True)),
        patch("gateway.routes.results.DatasetRepository.get_wsi_ids", new=AsyncMock(return_value=["wsi-1"])),
        patch("gateway.routes.results.TrainingTaskRepository.get_wsi_ids", new=AsyncMock(return_value=[])),
        patch("gateway.routes.results.DatasetRepository.get_distinct_labels", new=AsyncMock(return_value=[])),
        patch("gateway.routes.results.check_extval_compatibility", return_value=None),
        patch("gateway.routes.results._check_existing_extval_results_from_store", return_value=(0, None, [])),
        patch("gateway.routes.results.is_worker_healthy", new=AsyncMock(return_value=True)),
        patch("gateway.routes.results.get_task_queue", side_effect=AssertionError("local queue must not be used"), create=True),
        patch("gateway.routes.results.build_task_descriptor", side_effect=build_task_descriptor) as mock_build,
        patch("gateway.routes.results.enqueue_task_descriptor", new=AsyncMock()) as mock_enqueue,
    ):
        result = await start_external_validation(
            req=ExternalValidationRequest(model_id="model-1", dataset_id="ds-ext"),
            user=_make_user("admin"),
            db=db,
        )

    assert result["status"] == "pending"
    assert mock_build.call_args.kwargs["handler"] == "external_validation.run"
    payload = mock_build.call_args.kwargs["payload"]
    assert payload["model_id"] == "model-1"
    assert payload["dataset_id"] == "ds-ext"
    assert payload["wsi_ids"] == ["wsi-1"]
    mock_enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_cached_external_validation_enqueues_analysis_descriptor_not_direct_call():
    from gateway.models import ExternalValidationRequest
    from gateway.routes.results import start_external_validation

    model_task = _mock_model_task()
    trained_model = _mock_trained_model()
    dataset = _mock_dataset("ds-ext")
    existing_task = MagicMock()
    existing_task.task_id = "extval_existing"
    db = AsyncMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: []))
    analysis_state = AsyncMock()

    with (
        patch("gateway.routes.results.TrainedModelRepository.get_by_id", new=AsyncMock(return_value=trained_model)),
        patch("gateway.routes.results.TrainingTaskRepository.get_by_id", new=AsyncMock(side_effect=[model_task, existing_task])),
        patch("gateway.routes.results._require_task_access", new=AsyncMock()),
        patch("gateway.routes.results.DatasetRepository.get_by_id", new=AsyncMock(return_value=dataset)),
        patch("gateway.routes.results._has_external_validation_dataset_access", new=AsyncMock(return_value=True)),
        patch("gateway.routes.results.check_dataset_gpu_permission", new=AsyncMock(return_value=True)),
        patch("gateway.routes.results.DatasetRepository.get_wsi_ids", new=AsyncMock(return_value=["wsi-1"])),
        patch("gateway.routes.results.DatasetRepository.get_distinct_labels", new=AsyncMock(return_value=[])),
        patch("gateway.routes.results.check_extval_compatibility", return_value=None),
        patch("gateway.routes.results._check_existing_extval_results_from_store", return_value=(1, "extval_existing", [])),
        patch("gateway.routes.results._iter_complete_analysis_runs", return_value=[]),
        patch("gateway.routes.results.is_worker_healthy", new=AsyncMock(return_value=True)),
        patch("gateway.routes.results.get_analysis_state", return_value=analysis_state),
        patch("gateway.routes.results._auto_trigger_external_validation_analysis", new=AsyncMock(side_effect=AssertionError("direct analysis call must not be used"))),
        patch("gateway.routes.results.build_task_descriptor", side_effect=build_task_descriptor) as mock_build,
        patch("gateway.routes.results.enqueue_task_descriptor", new=AsyncMock()) as mock_enqueue,
    ):
        result = await start_external_validation(
            req=ExternalValidationRequest(model_id="model-1", dataset_id="ds-ext"),
            user=_make_user("admin"),
            db=db,
        )

    assert result["task_id"] == "extval_existing"
    assert result["status"] == "analysis_started"
    assert mock_build.call_args.kwargs["handler"] == "analysis.task"
    payload = mock_build.call_args.kwargs["payload"]
    assert "task_id" in payload
    assert payload["task_id"].endswith("_auto")
    assert payload["runner_kwargs"]["task_type_str"] == "external_validation"
    analysis_state.create.assert_awaited_once()
    mock_enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_task_analysis_enqueues_analysis_descriptor_no_queue_or_create_task():
    from gateway.routes.results import AnalysisRequest, run_task_analysis

    task = MagicMock()
    task.task_id = "task-1"
    task.task_name = "Task 1"
    task.model_config = {}
    task.preprocessing_config = {}
    task.data_group = SimpleNamespace(task_type="wsi_classification")

    analysis_state = AsyncMock()
    analysis_state.get_by_task_id.return_value = []
    db = AsyncMock()
    db.add = MagicMock()

    with (
        patch("gateway.routes.results._get_task_with_access", new=AsyncMock(return_value=(task, "ds-1"))),
        patch("gateway.routes.results.DatasetRepository.get_by_id", new=AsyncMock(return_value=None)),
        patch("gateway.routes.results._require_task_gpu_permission", new=AsyncMock()),
        patch("gateway.routes.results.get_analysis_state", return_value=analysis_state),
        patch("gateway.routes.results._check_task_resources", new=AsyncMock(return_value={"has_ai_results": True, "has_training_metrics": True})),
        patch("gateway.routes.results.is_worker_healthy", new=AsyncMock(return_value=True)),
        patch("gateway.routes.results.get_task_queue", side_effect=AssertionError("local queue must not be used"), create=True),
        patch("gateway.routes.results.asyncio.create_task", side_effect=AssertionError("create_task must not be used")),
        patch("gateway.routes.results.build_task_descriptor", side_effect=build_task_descriptor) as mock_build,
        patch("gateway.routes.results.enqueue_task_descriptor", new=AsyncMock()) as mock_enqueue,
    ):
        result = await run_task_analysis(
            task_id="task-1",
            request=AnalysisRequest(metrics=["accuracy"], charts=["roc_curve"]),
            user=_make_user("admin"),
            db=db,
        )

    assert result["status"] == "pending"
    assert mock_build.call_args.kwargs["handler"] == "analysis.task"
    payload = mock_build.call_args.kwargs["payload"]
    assert payload["task_id"] == result["analysis_id"]
    assert payload["runner_module"] == "gateway.routes.results"
    assert payload["runner_name"] == "run_analysis_pipeline"
    assert payload["runner_kwargs"]["task_id"] == result["analysis_id"]
    mock_enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_task_analysis_publishes_cancellation_for_active_analysis():
    from gateway.routes.results import delete_task_analysis

    task = MagicMock()
    task.task_id = "task-1"
    task.user_id = "user-1"

    analysis_state = AsyncMock()
    analysis_state.get.return_value = {
        "analysis_id": "analysis-1",
        "status": "running",
    }

    fake_dir = MagicMock()
    fake_dir.exists.return_value = True
    fake_dir.is_dir.return_value = True

    with (
        patch("gateway.routes.results.TrainingTaskRepository.get_by_id", new=AsyncMock(return_value=task)),
        patch("gateway.routes.results.get_analysis_state", return_value=analysis_state),
        patch("gateway.routes.results.publish_task_cancellation", new=AsyncMock()) as mock_publish,
        patch("gateway.routes.results.Config.get_uploads_dir", return_value=MagicMock()),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_dir", return_value=True),
        patch("gateway.routes.results.shutil.rmtree") as mock_rmtree,
    ):
        result = await delete_task_analysis(
            task_id="task-1",
            analysis_id="analysis-1",
            user=_make_user("admin"),
            db=AsyncMock(),
        )

    assert result["message"] == "Analysis analysis-1 deleted successfully"
    mock_publish.assert_awaited_once_with("analysis-1")
    analysis_state.cancel_running_task.assert_awaited_once_with("analysis-1")
    analysis_state.set_cancelled.assert_awaited_once_with("analysis-1")
    mock_rmtree.assert_called_once()
