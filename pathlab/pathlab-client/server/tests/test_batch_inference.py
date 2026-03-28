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
