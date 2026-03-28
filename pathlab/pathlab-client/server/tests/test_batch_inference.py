import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from server.gateway.task_queue import TaskType
from server.gateway.models import BatchInferenceRequest
from pydantic import ValidationError
from helpers import _make_user


def test_batch_inference_task_type_exists():
    assert TaskType.BATCH_INFERENCE == "batch_inference"


def test_batch_inference_request_valid():
    req = BatchInferenceRequest(model_task_id="task-123", dataset_id="ds-456")
    assert req.model_task_id == "task-123"
    assert req.dataset_id == "ds-456"
    assert req.rerun_from_task_id is None


def test_batch_inference_request_with_rerun():
    req = BatchInferenceRequest(
        model_task_id="task-123", dataset_id="ds-456", rerun_from_task_id="task-000"
    )
    assert req.rerun_from_task_id == "task-000"


def test_batch_inference_request_missing_required():
    with pytest.raises(ValidationError):
        BatchInferenceRequest(model_task_id="task-123")  # missing dataset_id


def _mock_dataset(dataset_id: str, task_type: str, name: str = "Dataset") -> MagicMock:
    dg = MagicMock()
    dg.task_type = task_type
    dg.data_type = "wsi"
    dg.aggregation_level = "file"

    ds = MagicMock()
    ds.dataset_id = dataset_id
    ds.name = name
    ds.user_id = "user-1"
    ds.data_group = dg
    ds.is_public = False
    return ds


@pytest.mark.asyncio
async def test_datasets_for_inference_returns_list():
    with patch(
        "gateway.routes.results.DatasetRepository.get_all",
        new_callable=AsyncMock,
        return_value=[],
    ):
        from gateway.routes.results import get_datasets_for_inference

        user = _make_user("admin")
        result = await get_datasets_for_inference(
            unlabeled_only=True, task_type=None, user=user, db=AsyncMock()
        )
    assert "items" in result
    assert "total" in result
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_datasets_for_inference_labeled_dataset_excluded():
    ds = _mock_dataset("ds-labeled", "wsi_classification")
    with (
        patch(
            "gateway.routes.results.DatasetRepository.get_all",
            new_callable=AsyncMock,
            return_value=[ds],
        ),
        patch(
            "gateway.routes.results.DatasetRepository.get_wsi_ids",
            new_callable=AsyncMock,
            return_value=["wsi-1"],
        ),
        patch(
            "gateway.routes.results.DatasetRepository.get_distinct_label_count",
            new_callable=AsyncMock,
            return_value=3,
        ),
    ):
        from gateway.routes.results import get_datasets_for_inference

        result = await get_datasets_for_inference(
            unlabeled_only=True,
            task_type=None,
            user=_make_user("admin"),
            db=AsyncMock(),
        )
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_datasets_for_inference_unlabeled_dataset_included():
    ds = _mock_dataset("ds-unlabeled", "wsi_classification")
    with (
        patch(
            "gateway.routes.results.DatasetRepository.get_all",
            new_callable=AsyncMock,
            return_value=[ds],
        ),
        patch(
            "gateway.routes.results.DatasetRepository.get_wsi_ids",
            new_callable=AsyncMock,
            return_value=["wsi-1", "wsi-2"],
        ),
        patch(
            "gateway.routes.results.DatasetRepository.get_distinct_label_count",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        from gateway.routes.results import get_datasets_for_inference

        result = await get_datasets_for_inference(
            unlabeled_only=True,
            task_type=None,
            user=_make_user("admin"),
            db=AsyncMock(),
        )
    assert result["total"] == 1
    assert result["items"][0]["dataset_id"] == "ds-unlabeled"
    assert result["items"][0]["slide_count"] == 2


def _mock_model_task(task_type: str, data_type: str = "wsi") -> MagicMock:
    dg = MagicMock()
    dg.task_type = task_type
    dg.data_type = data_type
    dg.aggregation_level = "file"

    task = MagicMock()
    task.task_id = "model-task-1"
    task.task_name = "My Model Task"
    task.user_id = "user-1"
    task.data_group = dg
    task.preprocessing_config = {}
    task.model_config = {}
    return task


def _mock_trained_model(is_active: bool = True) -> MagicMock:
    m = MagicMock()
    m.model_id = "model-1"
    m.is_active = is_active
    m.user_id = "user-1"
    m.classes = ["A", "B"]
    m.feature_extractor = "resnet50"
    return m


@pytest.mark.asyncio
async def test_batch_inference_submit_inactive_model_raises():
    model_task = _mock_model_task("wsi_classification")
    inactive_model = _mock_trained_model(is_active=False)

    with (
        patch(
            "gateway.routes.results.TrainingTaskRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=model_task,
        ),
        patch(
            "gateway.routes.results.TrainedModelRepository.get_by_task_id",
            new_callable=AsyncMock,
            return_value=[inactive_model],
        ),
    ):
        from gateway.routes.results import start_batch_inference
        from gateway.models import BatchInferenceRequest
        from fastapi import HTTPException

        req = BatchInferenceRequest(model_task_id="model-task-1", dataset_id="ds-1")
        with pytest.raises(HTTPException) as exc_info:
            await start_batch_inference(
                req=req, user=_make_user("admin"), db=AsyncMock()
            )
    assert exc_info.value.status_code == 400
    assert "not active" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_batch_inference_submit_incompatible_types_raises():
    model_task = _mock_model_task("wsi_classification", "wsi")
    trained_model = _mock_trained_model()

    dataset_dg = MagicMock()
    dataset_dg.task_type = "wsi_survival"
    dataset_dg.data_type = "wsi"
    dataset_dg.aggregation_level = "file"
    target_dataset = MagicMock()
    target_dataset.dataset_id = "ds-survival"
    target_dataset.name = "Survival Dataset"
    target_dataset.user_id = "user-1"
    target_dataset.data_group = dataset_dg
    target_dataset.is_public = False
    target_dataset.parent_dataset_id = None

    with (
        patch(
            "gateway.routes.results.TrainingTaskRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=model_task,
        ),
        patch(
            "gateway.routes.results.TrainedModelRepository.get_by_task_id",
            new_callable=AsyncMock,
            return_value=[trained_model],
        ),
        patch(
            "gateway.routes.results._require_task_access",
            new_callable=AsyncMock,
        ),
        patch(
            "gateway.routes.results.DatasetRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=target_dataset,
        ),
        patch(
            "gateway.routes.results._has_external_validation_dataset_access",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "gateway.routes.results.check_dataset_gpu_permission",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        from gateway.routes.results import start_batch_inference
        from gateway.models import BatchInferenceRequest
        from fastapi import HTTPException

        req = BatchInferenceRequest(
            model_task_id="model-task-1", dataset_id="ds-survival"
        )
        with pytest.raises(HTTPException) as exc_info:
            await start_batch_inference(
                req=req, user=_make_user("admin"), db=AsyncMock()
            )
    assert exc_info.value.status_code == 400
    assert "incompatible" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_batch_inference_submit_success():
    model_task = _mock_model_task("wsi_classification", "wsi")
    trained_model = _mock_trained_model()

    dataset_dg = MagicMock()
    dataset_dg.task_type = "wsi_classification"
    dataset_dg.data_type = "wsi"
    dataset_dg.aggregation_level = "file"
    target_dataset = MagicMock()
    target_dataset.dataset_id = "ds-unlabeled"
    target_dataset.name = "Unlabeled Dataset"
    target_dataset.user_id = "user-1"
    target_dataset.data_group = dataset_dg
    target_dataset.is_public = False
    target_dataset.parent_dataset_id = None

    mock_batch_dg = MagicMock()
    mock_batch_dg.group_id = "batchgroup-1"

    mock_queue = MagicMock()
    mock_queue.submit = AsyncMock()

    with (
        patch(
            "gateway.routes.results.TrainingTaskRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=model_task,
        ),
        patch(
            "gateway.routes.results.TrainedModelRepository.get_by_task_id",
            new_callable=AsyncMock,
            return_value=[trained_model],
        ),
        patch("gateway.routes.results._require_task_access", new_callable=AsyncMock),
        patch(
            "gateway.routes.results.DatasetRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=target_dataset,
        ),
        patch(
            "gateway.routes.results._has_external_validation_dataset_access",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "gateway.routes.results.check_dataset_gpu_permission",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "gateway.routes.results.DataGroupRepository.get_or_create",
            new_callable=AsyncMock,
            return_value=mock_batch_dg,
        ),
        patch("gateway.routes.results.get_task_queue", return_value=mock_queue),
    ):
        from gateway.routes.results import start_batch_inference
        from gateway.models import BatchInferenceRequest

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        req = BatchInferenceRequest(
            model_task_id="model-task-1", dataset_id="ds-unlabeled"
        )
        result = await start_batch_inference(
            req=req, user=_make_user("admin"), db=mock_db
        )

    assert "task_id" in result
    assert result["status"] == "pending"
    mock_queue.submit.assert_awaited_once()
