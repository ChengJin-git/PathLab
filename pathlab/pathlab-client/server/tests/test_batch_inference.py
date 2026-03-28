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


def _mock_batch_task(
    task_id: str = "binfer-test-1", task_type: str = "wsi_classification"
) -> MagicMock:
    from datetime import datetime, timezone

    dg = MagicMock()
    dg.task_type = "batch_inference"
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


def _mock_ai_result(wsi_id: str = "wsi-1", task_id: str = "binfer-test-1") -> MagicMock:
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
    assert result["items"][0]["task_id"] == "binfer-test-1"


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
            task_id="binfer-test-1",
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
            task_id="binfer-test-1", user=_make_user("admin"), db=AsyncMock()
        )
    assert result["task_id"] == "binfer-test-1"
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
            task_id="binfer-test-1", user=_make_user("admin"), db=AsyncMock()
        )
    assert isinstance(result, StreamingResponse)
    assert result.media_type == "text/csv"
    assert "attachment" in result.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_run_batch_inference_routes_to_wsi_classification():
    """task_type=wsi_classification routes to WSI classification handler (mocked)"""
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
            "gateway.routes.inference_batch._run_batch_wsi_classification",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_handler,
        patch(
            "gateway.routes.inference_batch.AIResultRepository.bulk_create",
            new_callable=AsyncMock,
        ),
        patch("gateway.routes.inference_batch.set_progress", new_callable=AsyncMock),
        patch("gateway.routes.inference_batch.clear_progress", new_callable=AsyncMock),
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

    assert mock_handler.call_count == 2


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
            "gateway.routes.inference_batch.is_permission_revoked",
            return_value=True,
        ),
        patch("gateway.routes.inference_batch.clear_revocation"),
        patch("gateway.routes.inference_batch.safe_session") as mock_safe,
        patch("gateway.routes.inference_batch.sql_update"),
        patch("gateway.routes.inference_batch.set_progress", new_callable=AsyncMock),
        patch("gateway.routes.inference_batch.clear_progress", new_callable=AsyncMock),
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
        patch("gateway.routes.inference_batch.set_progress", new_callable=AsyncMock),
        patch("gateway.routes.inference_batch.clear_progress", new_callable=AsyncMock),
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
