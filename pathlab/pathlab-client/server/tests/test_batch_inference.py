import pytest
from server.gateway.task_queue import TaskType
from server.gateway.models import BatchInferenceRequest
from pydantic import ValidationError


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
