import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from server.gateway.task_queue import TaskType
from server.gateway.models import BatchInferenceRequest, IndependentInferenceRequest
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


def test_independent_inference_request_valid():
    req = IndependentInferenceRequest(model_id="model-1", wsi_ids=["wsi-1"])
    assert req.model_id == "model-1"
    assert req.wsi_ids == ["wsi-1"]
    assert req.rerun_from_task_id is None


def test_independent_inference_request_requires_wsi_ids():
    with pytest.raises(ValidationError):
        IndependentInferenceRequest(model_id="model-1", wsi_ids=[])


def test_independent_inference_uses_batch_inference_mode_helpers():
    from gateway.routes.inference_external_validation import (
        _artifact_prefix_for_mode,
        _is_batch_inference_mode,
    )

    assert _is_batch_inference_mode("batch_inference") is True
    assert _is_batch_inference_mode("independent_inference") is True
    assert _is_batch_inference_mode("external_validation") is False
    assert _artifact_prefix_for_mode("independent_inference") == "binfer"


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


@pytest.mark.asyncio
async def test_segmentation_batch_inference_treats_imported_gt_as_labeled():
    from gateway.routes.results import _is_dataset_unlabeled_for_batch_inference

    db = AsyncMock()
    query_result = MagicMock()
    query_result.scalar.return_value = 2
    db.execute.return_value = query_result

    result = await _is_dataset_unlabeled_for_batch_inference(
        db, "ds-seg-labeled", "patch_segmentation"
    )

    assert result is False


@pytest.mark.asyncio
async def test_segmentation_batch_inference_allows_viewer_only_annotations():
    from gateway.routes.results import _is_dataset_unlabeled_for_batch_inference

    db = AsyncMock()
    query_result = MagicMock()
    query_result.scalar.return_value = 0
    db.execute.return_value = query_result

    result = await _is_dataset_unlabeled_for_batch_inference(
        db, "ds-seg-viewer-only", "patch_segmentation"
    )

    assert result is True


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
    m.task_id = "model-task-1"
    m.is_active = is_active
    m.user_id = "user-1"
    m.classes = ["A", "B"]
    m.feature_extractor = "resnet50"
    return m


def _mock_wsi(
    wsi_id: str,
    dataset_id: str = "ds-unlabeled",
    task_type: str = "wsi_classification",
    data_type: str = "wsi",
    label=None,
) -> MagicMock:
    dg = MagicMock()
    dg.group_id = "targetgroup-1"
    dg.task_type = task_type
    dg.data_type = data_type
    dg.aggregation_level = "file"

    ds = MagicMock()
    ds.dataset_id = dataset_id
    ds.name = "Uploaded images"
    ds.user_id = "user-1"
    ds.data_group = dg
    ds.is_public = False

    wsi = MagicMock()
    wsi.wsi_id = wsi_id
    wsi.original_filename = f"{wsi_id}.svs"
    wsi.dataset_id = dataset_id
    wsi.dataset = ds
    wsi.user_id = "user-1"
    wsi.label = label
    wsi.case_id = "case-1"
    wsi.event_time = None
    wsi.event_status = None
    wsi.data_type = data_type
    wsi.created_at = None
    return wsi


@pytest.mark.asyncio
async def test_independent_inference_wsi_list_reports_no_models():
    with (
        patch(
            "gateway.routes.results.TrainedModelRepository.get_active_models",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "gateway.routes.results.WSIRepository.get_all_with_dataset",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        from gateway.routes.results import get_wsi_for_independent_inference

        result = await get_wsi_for_independent_inference(user=_make_user("admin"), db=AsyncMock())

    assert result["models_available"] is False
    assert result["items"] == []
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_independent_inference_wsi_list_includes_unlabeled_uploads():
    wsi = _mock_wsi("wsi-1")
    with (
        patch(
            "gateway.routes.results.TrainedModelRepository.get_active_models",
            new_callable=AsyncMock,
            return_value=[_mock_trained_model()],
        ),
        patch(
            "gateway.routes.results.WSIRepository.get_all_with_dataset",
            new_callable=AsyncMock,
            return_value=[wsi],
        ),
        patch(
            "gateway.routes.results.DatasetRepository.get_distinct_label_count",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        from gateway.routes.results import get_wsi_for_independent_inference

        result = await get_wsi_for_independent_inference(user=_make_user("admin"), db=AsyncMock())

    assert result["models_available"] is True
    assert result["total"] == 1
    assert result["items"][0]["wsi_id"] == "wsi-1"
    assert result["items"][0]["original_filename"] == "wsi-1.svs"
    assert result["items"][0]["task_type"] == "wsi_classification"


@pytest.mark.asyncio
async def test_independent_inference_submit_success():
    model_task = _mock_model_task("wsi_classification", "wsi")
    trained_model = _mock_trained_model()
    wsi = _mock_wsi("wsi-1")
    mock_queue = MagicMock()
    mock_queue.submit = AsyncMock()

    with (
        patch(
            "gateway.routes.results.TrainedModelRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=trained_model,
        ),
        patch(
            "gateway.routes.results.TrainingTaskRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=model_task,
        ),
        patch("gateway.routes.results._require_task_access", new_callable=AsyncMock),
        patch(
            "gateway.routes.results.WSIRepository.get_by_ids_with_dataset",
            new_callable=AsyncMock,
            return_value={"wsi-1": wsi},
        ),
        patch(
            "gateway.routes.results.DatasetRepository.get_distinct_label_count",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch("gateway.routes.results.get_task_queue", return_value=mock_queue),
    ):
        from gateway.routes.results import start_independent_inference
        from gateway.models import IndependentInferenceRequest

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        result = await start_independent_inference(
            req=IndependentInferenceRequest(model_id="model-1", wsi_ids=["wsi-1"]),
            user=_make_user("admin"),
            db=mock_db,
        )

    assert result["task_id"].startswith("indinfer_")
    assert result["status"] == "pending"
    assert result["total_wsi"] == 1
    created_task = mock_db.add.call_args.args[0]
    assert created_task.model_config["wsi_ids"] == ["wsi-1"]
    mock_queue.submit.assert_awaited_once()
    submit_kwargs = mock_queue.submit.await_args.kwargs
    assert submit_kwargs["wsi_ids"] == ["wsi-1"]
    assert submit_kwargs["execution_mode"] == "independent_inference"


@pytest.mark.asyncio
async def test_independent_inference_submit_allows_elevated_dataset_access():
    model_task = _mock_model_task("wsi_classification", "wsi")
    trained_model = _mock_trained_model()
    wsi = _mock_wsi("wsi-1")
    wsi.user_id = "other-user"
    mock_queue = MagicMock()
    mock_queue.submit = AsyncMock()

    with (
        patch(
            "gateway.routes.results.TrainedModelRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=trained_model,
        ),
        patch(
            "gateway.routes.results.TrainingTaskRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=model_task,
        ),
        patch("gateway.routes.results._require_task_access", new_callable=AsyncMock),
        patch("gateway.routes.results._get_elevated_dataset_ids", new_callable=AsyncMock, return_value=["ds-unlabeled"]),
        patch(
            "gateway.routes.results.WSIRepository.get_by_ids_with_dataset",
            new_callable=AsyncMock,
            return_value={"wsi-1": wsi},
        ),
        patch(
            "gateway.routes.results.DatasetRepository.get_distinct_label_count",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch("gateway.routes.results.get_task_queue", return_value=mock_queue),
    ):
        from gateway.routes.results import start_independent_inference
        from gateway.models import IndependentInferenceRequest

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        result = await start_independent_inference(
            req=IndependentInferenceRequest(model_id="model-1", wsi_ids=["wsi-1"]),
            user=_make_user("user-1"),
            db=mock_db,
        )

    assert result["total_wsi"] == 1
    assert result["skipped"] == []
    mock_queue.submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_independent_inference_submit_hides_unauthorized_wsi_existence():
    from fastapi import HTTPException

    model_task = _mock_model_task("wsi_classification", "wsi")
    trained_model = _mock_trained_model()
    unauthorized = _mock_wsi("secret-wsi")
    unauthorized.user_id = "other-user"

    with (
        patch(
            "gateway.routes.results.TrainedModelRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=trained_model,
        ),
        patch(
            "gateway.routes.results.TrainingTaskRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=model_task,
        ),
        patch("gateway.routes.results._require_task_access", new_callable=AsyncMock),
        patch("gateway.routes.results._get_elevated_dataset_ids", new_callable=AsyncMock, return_value=[]),
        patch(
            "gateway.routes.results.WSIRepository.get_by_ids_with_dataset",
            new_callable=AsyncMock,
            return_value={"secret-wsi": unauthorized},
        ),
    ):
        from gateway.routes.results import start_independent_inference
        from gateway.models import IndependentInferenceRequest

        with pytest.raises(HTTPException) as exc_info:
            await start_independent_inference(
                req=IndependentInferenceRequest(model_id="model-1", wsi_ids=["secret-wsi", "missing-wsi"]),
                user=_make_user("user-1"),
                db=AsyncMock(),
            )

    detail = exc_info.value.detail
    skipped = detail["skipped"]
    assert {item["wsi_id"] for item in skipped} == {"secret-wsi", "missing-wsi"}
    assert {item["reason"] for item in skipped} == {"unavailable"}


@pytest.mark.asyncio
async def test_independent_inference_submit_rejects_mixed_datasets():
    from fastapi import HTTPException

    model_task = _mock_model_task("wsi_classification", "wsi")
    trained_model = _mock_trained_model()
    user = _make_user("user")
    first = _mock_wsi("wsi-1", dataset_id="dataset-a")
    second = _mock_wsi("wsi-2", dataset_id="dataset-b")
    first.user_id = str(user.id)
    second.user_id = str(user.id)
    mock_queue = MagicMock()
    mock_queue.submit = AsyncMock()

    with (
        patch(
            "gateway.routes.results.TrainedModelRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=trained_model,
        ),
        patch(
            "gateway.routes.results.TrainingTaskRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=model_task,
        ),
        patch("gateway.routes.results._require_task_access", new_callable=AsyncMock),
        patch("gateway.routes.results._get_elevated_dataset_ids", new_callable=AsyncMock, return_value=[]),
        patch(
            "gateway.routes.results.WSIRepository.get_by_ids_with_dataset",
            new_callable=AsyncMock,
            return_value={"wsi-1": first, "wsi-2": second},
        ),
        patch(
            "gateway.routes.results.DatasetRepository.get_distinct_label_count",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch("gateway.routes.results.get_task_queue", return_value=mock_queue),
    ):
        from gateway.routes.results import start_independent_inference
        from gateway.models import IndependentInferenceRequest

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await start_independent_inference(
                req=IndependentInferenceRequest(model_id="model-1", wsi_ids=["wsi-1", "wsi-2"]),
                user=user,
                db=mock_db,
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["message"] == "Select images from a single dataset"
    mock_db.add.assert_not_called()
    mock_queue.submit.assert_not_awaited()


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
    dataset_dg.group_id = "targetgroup-1"
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
            "gateway.routes.results.DatasetRepository.get_distinct_label_count",
            new_callable=AsyncMock,
            return_value=0,
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
    created_task = mock_db.add.call_args.args[0]
    assert created_task.group_id == "targetgroup-1"
    mock_queue.submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_inference_submit_labeled_dataset_raises():
    model_task = _mock_model_task("wsi_classification", "wsi")
    trained_model = _mock_trained_model()

    dataset_dg = MagicMock()
    dataset_dg.task_type = "wsi_classification"
    dataset_dg.data_type = "wsi"
    dataset_dg.aggregation_level = "file"
    target_dataset = MagicMock()
    target_dataset.dataset_id = "ds-labeled"
    target_dataset.name = "Labeled Dataset"
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
            "gateway.routes.results.DatasetRepository.get_distinct_label_count",
            new_callable=AsyncMock,
            return_value=2,
        ),
    ):
        from fastapi import HTTPException
        from gateway.models import BatchInferenceRequest
        from gateway.routes.results import start_batch_inference

        req = BatchInferenceRequest(model_task_id="model-task-1", dataset_id="ds-labeled")
        with pytest.raises(HTTPException) as exc_info:
            await start_batch_inference(
                req=req, user=_make_user("admin"), db=AsyncMock()
            )

    assert exc_info.value.status_code == 400
    assert "unlabeled datasets" in exc_info.value.detail.lower()


def _mock_batch_task(
    task_id: str = "binfer_test_1", task_type: str = "wsi_classification"
) -> MagicMock:
    from datetime import datetime, timezone

    dg = MagicMock()
    dg.task_type = task_type
    dg.data_type = "wsi"
    dg.aggregation_level = "file"

    task = MagicMock()
    task.task_id = task_id
    task.task_name = f"Batch {task_id}"
    task.user_id = "user-1"
    task.status = "completed"
    task.progress = 100
    task.error_message = None
    task.data_group = dg
    task.model_config = {
        "model_task_id": "mt-1",
        "model_id": "m-1",
        "dataset_id": "ds-1",
        "model_task_type": task_type,
        "model_data_type": "wsi",
        "total_wsi": 10,
        "results_count": 10,
    }
    task.created_at = datetime(2026, 3, 28, 0, 0, 0, tzinfo=timezone.utc).replace(
        tzinfo=None
    )
    task.finished_at = datetime(2026, 3, 28, 1, 0, 0, tzinfo=timezone.utc).replace(
        tzinfo=None
    )
    return task


def _mock_ai_result(wsi_id: str = "wsi-1", task_id: str = "binfer_test_1") -> MagicMock:
    from datetime import datetime, timezone

    r = MagicMock()
    r.wsi_id = wsi_id
    r.task_id = task_id
    r.user_id = "user-1"
    r.pred = "ClassA"
    r.probs = {"ClassA": 0.9, "ClassB": 0.1}
    r.extra_metadata = {}
    r.created_at = datetime(2026, 3, 28, 0, 30, 0, tzinfo=timezone.utc).replace(
        tzinfo=None
    )
    r.wsi_slide = MagicMock()
    r.wsi_slide.original_filename = f"{wsi_id}.svs"
    r.wsi_slide.case_id = "case-1"
    r.to_dict = MagicMock(
        return_value={
            "wsi_id": wsi_id,
            "task_id": task_id,
            "pred": "ClassA",
            "probs": {"ClassA": 0.9, "ClassB": 0.1},
            "extra_metadata": {},
        }
    )
    return r


@pytest.mark.asyncio
async def test_list_batch_inference_tasks_returns_items():
    mock_task = _mock_batch_task()
    with (
        patch(
            "gateway.routes.results.TrainingTaskRepository.get_batch_inference_tasks",
            new_callable=AsyncMock,
            return_value=[mock_task],
        ),
        patch(
            "gateway.routes.results.TrainingTaskRepository.count_batch_inference_tasks",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "gateway.routes.results.get_progress",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        from gateway.routes.results import list_batch_inference_tasks

        result = await list_batch_inference_tasks(
            skip=0, limit=50, user=_make_user("admin"), db=AsyncMock()
        )
    assert "items" in result
    assert "total" in result
    assert result["total"] == 1
    assert result["items"][0]["task_id"] == "binfer_test_1"


@pytest.mark.asyncio
async def test_get_batch_inference_results_not_found():
    with patch(
        "gateway.routes.results.TrainingTaskRepository.get_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        from gateway.routes.results import get_batch_inference_results
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_batch_inference_results(
                task_id="nonexistent",
                skip=0,
                limit=100,
                user=_make_user("admin"),
                db=AsyncMock(),
            )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_batch_inference_results_returns_paginated():
    mock_task = _mock_batch_task()
    mock_results = [_mock_ai_result(f"wsi-{i}") for i in range(3)]
    with (
        patch(
            "gateway.routes.results.TrainingTaskRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=mock_task,
        ),
        patch(
            "gateway.routes.results.AIResultRepository.get_by_task_paginated",
            new_callable=AsyncMock,
            return_value=mock_results,
        ),
        patch(
            "gateway.routes.results.AIResultRepository.count_by_task",
            new_callable=AsyncMock,
            return_value=3,
        ),
    ):
        from gateway.routes.results import get_batch_inference_results

        result = await get_batch_inference_results(
            task_id="binfer_test_1",
            skip=0,
            limit=100,
            user=_make_user("admin"),
            db=AsyncMock(),
        )
    assert result["total"] == 3
    assert len(result["items"]) == 3
    assert "task_type" in result
    assert "data_type" in result


@pytest.mark.asyncio
async def test_get_batch_inference_summary_classification():
    mock_task = _mock_batch_task()
    mock_results = [_mock_ai_result(f"wsi-{i}") for i in range(5)]
    with (
        patch(
            "gateway.routes.results.TrainingTaskRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=mock_task,
        ),
        patch(
            "gateway.routes.results.AIResultRepository.get_by_task_paginated",
            new_callable=AsyncMock,
            return_value=mock_results,
        ),
    ):
        from gateway.routes.results import get_batch_inference_summary

        result = await get_batch_inference_summary(
            task_id="binfer_test_1", user=_make_user("admin"), db=AsyncMock()
        )
    assert result["task_id"] == "binfer_test_1"
    assert result["total_slides"] == 5
    assert "class_distribution" in result
    assert result["class_distribution"]["ClassA"] == 5


@pytest.mark.asyncio
async def test_get_batch_inference_summary_not_found():
    with patch(
        "gateway.routes.results.TrainingTaskRepository.get_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        from gateway.routes.results import get_batch_inference_summary
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_batch_inference_summary(
                task_id="nonexistent", user=_make_user("admin"), db=AsyncMock()
            )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_export_batch_inference_csv_returns_streaming():
    mock_task = _mock_batch_task()
    mock_results = [_mock_ai_result("wsi-1"), _mock_ai_result("wsi-2")]
    with (
        patch(
            "gateway.routes.results.TrainingTaskRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=mock_task,
        ),
        patch(
            "gateway.routes.results.AIResultRepository.get_by_task_paginated",
            new_callable=AsyncMock,
            return_value=mock_results,
        ),
    ):
        from gateway.routes.results import export_batch_inference_csv
        from fastapi.responses import StreamingResponse

        result = await export_batch_inference_csv(
            task_id="binfer_test_1", user=_make_user("admin"), db=AsyncMock()
        )
    assert isinstance(result, StreamingResponse)
    assert result.media_type == "text/csv"
    assert "attachment" in result.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_run_batch_inference_routes_to_wsi_classification():
    """task_type=wsi_classification delegates to shared WSI inference path once."""
    from unittest.mock import patch, AsyncMock, MagicMock

    mock_task = MagicMock()
    mock_task.data_group.task_type = "wsi_classification"
    mock_task.data_group.data_type = "wsi"

    mock_model = MagicMock()
    mock_model.model_id = "m-1"

    wsi_ids = [f"wsi-{i}" for i in range(55)]

    with (
        patch(
            "gateway.routes.inference_batch.TrainingTaskRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=mock_task,
        ),
        patch(
            "gateway.routes.inference_batch.TrainedModelRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=mock_model,
        ),
        patch(
            "gateway.routes.inference_batch.DatasetRepository.get_wsi_ids",
            new_callable=AsyncMock,
            return_value=wsi_ids,
        ),
        patch(
            "gateway.routes.inference_batch.is_permission_revoked",
            return_value=False,
        ),
        patch(
            "gateway.routes.inference_batch.clear_revocation",
        ),
        patch(
            "gateway.routes.inference_batch.AIResultRepository.delete_by_task_id",
            new_callable=AsyncMock,
        ),
        patch(
            "gateway.routes.inference_batch._run_external_validation",
            new_callable=AsyncMock,
        ) as mock_handler,
        patch("gateway.routes.inference_batch.safe_session"),
        patch("gateway.routes.inference_batch.sql_update"),
    ):
        from gateway.routes.inference_batch import _run_batch_inference

        with patch("gateway.routes.inference_batch.safe_session") as mock_safe:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_safe.return_value = mock_ctx

            await _run_batch_inference(
                task_id="binfer-1",
                model_task_id="mt-1",
                model_id="m-1",
                dataset_id="ds-1",
                assigned_device="cpu",
            )

    assert mock_handler.call_count == 1
    call_kwargs = mock_handler.await_args.kwargs
    assert call_kwargs["execution_mode"] == "batch_inference"
    assert call_kwargs["auto_trigger_analysis"] is False
    assert call_kwargs["wsi_ids"] == wsi_ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("task_type", "data_type", "handler_path"),
    [
        (
            "wsi_classification",
            "wsi",
            "gateway.routes.inference_batch._run_external_validation",
        ),
        (
            "wsi_survival",
            "wsi",
            "gateway.routes.inference_batch._run_external_validation",
        ),
        (
            "patch_classification",
            "patch",
            "gateway.routes.inference_batch._run_external_validation_patch_classification",
        ),
        (
            "patch_segmentation",
            "patch",
            "gateway.routes.inference_batch._run_external_validation_patch_segmentation",
        ),
    ],
)
async def test_run_batch_inference_threads_independent_mode_to_all_task_handlers(
    task_type, data_type, handler_path
):
    mock_task = MagicMock()
    mock_task.data_group.task_type = task_type
    mock_task.data_group.data_type = data_type

    mock_model = MagicMock()
    mock_model.model_id = "m-1"
    mock_model.classes = ["A", "B"]

    wsi_ids = ["wsi-1"]
    with (
        patch(
            "gateway.routes.inference_batch.TrainingTaskRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=mock_task,
        ),
        patch(
            "gateway.routes.inference_batch.TrainedModelRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=mock_model,
        ),
        patch(
            "gateway.routes.inference_batch.DatasetRepository.get_wsi_ids",
            new_callable=AsyncMock,
            return_value=wsi_ids,
        ),
        patch(
            "gateway.routes.inference_batch.AIResultRepository.delete_by_task_id",
            new_callable=AsyncMock,
        ),
        patch("gateway.routes.inference_batch.is_permission_revoked", return_value=False),
        patch("gateway.routes.inference_batch.clear_revocation"),
        patch(handler_path, new_callable=AsyncMock) as mock_handler,
        patch("gateway.routes.inference_batch.safe_session") as mock_safe,
        patch("gateway.routes.inference_batch.sql_update"),
    ):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_safe.return_value = mock_ctx

        from gateway.routes.inference_batch import _run_batch_inference

        await _run_batch_inference(
            task_id="indinfer-1",
            model_task_id="mt-1",
            model_id="m-1",
            dataset_id="ds-1",
            assigned_device="cpu",
            wsi_ids=wsi_ids,
            execution_mode="independent_inference",
        )

    mock_handler.assert_awaited_once()
    call_kwargs = mock_handler.await_args.kwargs
    assert call_kwargs["execution_mode"] == "independent_inference"
    assert call_kwargs["wsi_ids"] == wsi_ids


@pytest.mark.asyncio
async def test_run_batch_inference_revocation_raises():
    """Permission revoked before first chunk → PermissionRevokedException"""
    from gateway.routes.inference_batch import (
        _run_batch_inference,
        PermissionRevokedException,
    )

    mock_task = MagicMock()
    mock_task.data_group.task_type = "wsi_classification"
    mock_task.data_group.data_type = "wsi"

    with (
        patch(
            "gateway.routes.inference_batch.TrainingTaskRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=mock_task,
        ),
        patch(
            "gateway.routes.inference_batch.TrainedModelRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
        patch(
            "gateway.routes.inference_batch.DatasetRepository.get_wsi_ids",
            new_callable=AsyncMock,
            return_value=["wsi-1"],
        ),
        patch(
            "gateway.routes.inference_batch.AIResultRepository.delete_by_task_id",
            new_callable=AsyncMock,
        ),
        patch(
            "gateway.routes.inference_batch.is_permission_revoked",
            return_value=True,
        ),
        patch("gateway.routes.inference_batch.clear_revocation"),
        patch("gateway.routes.inference_batch.safe_session") as mock_safe,
        patch("gateway.routes.inference_batch.sql_update"),
    ):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_safe.return_value = mock_ctx

        with pytest.raises(PermissionRevokedException):
            await _run_batch_inference(
                task_id="binfer-revoked",
                model_task_id="mt-1",
                model_id="m-1",
                dataset_id="ds-1",
                assigned_device="cpu",
            )


@pytest.mark.asyncio
async def test_clear_revocation_called_in_finally():
    """clear_revocation is called even when an unexpected exception occurs"""
    from gateway.routes.inference_batch import _run_batch_inference

    mock_task = MagicMock()
    mock_task.data_group.task_type = "wsi_classification"
    mock_task.data_group.data_type = "wsi"

    with (
        patch(
            "gateway.routes.inference_batch.TrainingTaskRepository.get_by_id",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB down"),
        ),
        patch("gateway.routes.inference_batch.clear_revocation") as mock_clear,
        patch("gateway.routes.inference_batch.safe_session") as mock_safe,
        patch("gateway.routes.inference_batch.sql_update"),
    ):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_safe.return_value = mock_ctx

        with pytest.raises(RuntimeError):
            await _run_batch_inference(
                task_id="binfer-err",
                model_task_id="mt-1",
                model_id="m-1",
                dataset_id="ds-1",
                assigned_device="cpu",
            )
    mock_clear.assert_called_once_with("binfer-err")
