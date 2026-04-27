import json
from types import SimpleNamespace

import pytest


class _AsyncResult:
    def __init__(self, *, one_value=None, all_values=None):
        self._one_value = one_value
        self._all_values = all_values or []

    def one(self):
        return self._one_value

    def all(self):
        return self._all_values


class _SequentialDb:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _query):
        if not self._results:
            raise AssertionError("Unexpected execute call")
        return self._results.pop(0)


class _AsyncContext:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _parse_sse_payload(event: str):
    assert event.startswith("data: ")
    return json.loads(event.removeprefix("data: ").strip())


def _extval_task_dict():
    return {
        "task_id": "extval_123",
        "task_name": "External validation",
        "task_type": "wsi_classification",
        "status": "completed",
        "progress": 100,
        "model_config": {"total_wsi": 7},
    }


@pytest.mark.asyncio
async def test_training_list_uses_extval_prefix_for_total_wsi_count(monkeypatch):
    from gateway.routes import training as training_routes

    task = SimpleNamespace(task_id="extval_123", to_dict=_extval_task_dict)
    monkeypatch.setattr(
        training_routes.TrainingTaskRepository,
        "get_all",
        lambda *args, **kwargs: _async_value([task]),
    )
    monkeypatch.setattr(
        training_routes.TrainingTaskRepository,
        "count",
        lambda *args, **kwargs: _async_value(1),
    )
    monkeypatch.setattr(
        training_routes.TrainingTaskRepository,
        "get_status_counts",
        lambda *args, **kwargs: _async_value({}),
    )
    monkeypatch.setattr(
        training_routes.TrainingTaskRepository,
        "get_wsi_counts_batch",
        lambda *args, **kwargs: _async_value({"extval_123": 0}),
    )
    monkeypatch.setattr(
        training_routes.TrainingTaskRepository,
        "get_source_dataset_ids_batch",
        lambda *args, **kwargs: _async_value({}),
    )
    monkeypatch.setattr(
        "backend.common.progress_store.get_all_progress",
        lambda: _async_value({}),
    )

    response = await training_routes.list_training_tasks(
        page=1,
        page_size=10,
        search=None,
        status_filter="all",
        sort_by="updated",
        user=SimpleNamespace(is_admin=lambda: False),
        user_id_filter="user_1",
        db=SimpleNamespace(),
    )

    assert response["items"][0]["task_type"] == "wsi_classification"
    assert response["items"][0]["wsi_count"] == 7


@pytest.mark.asyncio
async def test_training_detail_uses_extval_prefix_for_total_wsi_count(monkeypatch):
    from gateway.routes import training as training_routes

    task = SimpleNamespace(
        task_id="extval_123",
        user_id="user_1",
        model_config={"total_wsi": 7},
        to_dict=_extval_task_dict,
    )
    monkeypatch.setattr(
        training_routes.TrainingTaskRepository,
        "get_by_id",
        lambda *args, **kwargs: _async_value(task),
    )
    monkeypatch.setattr(
        training_routes.TrainingTaskRepository,
        "get_wsi_ids",
        lambda *args, **kwargs: _async_value([]),
    )
    monkeypatch.setattr(
        "backend.common.progress_store.get_progress",
        lambda _task_id: _async_value(None),
    )

    response = await training_routes.get_training_task(
        "extval_123",
        user=SimpleNamespace(id="user_1", is_admin=lambda: False),
        db=SimpleNamespace(),
    )

    assert response["task_type"] == "wsi_classification"
    assert response["wsi_count"] == 7


@pytest.mark.asyncio
async def test_training_stream_uses_extval_prefix_for_total_wsi_count(monkeypatch):
    from gateway.routes import training as training_routes

    task = SimpleNamespace(
        task_id="extval_123",
        model_config={"total_wsi": 7},
        to_dict=_extval_task_dict,
    )
    monkeypatch.setattr(training_routes, "safe_session", lambda: _AsyncContext(SimpleNamespace()))
    monkeypatch.setattr(training_routes, "make_sse_response", lambda generator: generator)
    monkeypatch.setattr(
        training_routes.TrainingTaskRepository,
        "get_all",
        lambda *args, **kwargs: _async_value([task]),
    )
    monkeypatch.setattr(
        training_routes.TrainingTaskRepository,
        "get_wsi_counts_batch",
        lambda *args, **kwargs: _async_value({"extval_123": 0}),
    )
    monkeypatch.setattr(
        "backend.common.progress_store.get_all_progress",
        lambda: _async_value({}),
    )

    stream = await training_routes.stream_training_tasks(
        user=SimpleNamespace(id="user_1", is_admin=lambda: False)
    )
    payload = _parse_sse_payload(await anext(stream))

    assert payload["items"][0]["task_type"] == "wsi_classification"
    assert payload["items"][0]["wsi_count"] == 7

    await stream.aclose()


@pytest.mark.asyncio
async def test_training_log_stream_uses_extval_prefix_for_total_wsi_count(monkeypatch):
    from gateway.routes import training as training_routes

    task = SimpleNamespace(
        task_id="extval_123",
        user_id="user_1",
        status="training",
        model_config={"total_wsi": 7},
        to_dict=_extval_task_dict,
    )
    monkeypatch.setattr(training_routes, "async_session", lambda: _AsyncContext(SimpleNamespace()))
    monkeypatch.setattr(training_routes, "safe_session", lambda: _AsyncContext(SimpleNamespace()))
    monkeypatch.setattr(training_routes, "make_sse_response", lambda generator: generator)
    monkeypatch.setattr(
        training_routes.TrainingTaskRepository,
        "get_by_id",
        lambda *args, **kwargs: _async_value(task),
    )
    monkeypatch.setattr(
        training_routes.TrainingTaskRepository,
        "get_wsi_ids",
        lambda *args, **kwargs: _async_value([]),
    )
    monkeypatch.setattr(
        training_routes.TrainingLogRepository,
        "get_recent",
        lambda *args, **kwargs: _async_value([]),
    )
    monkeypatch.setattr(
        "backend.common.progress_store.get_progress",
        lambda _task_id: _async_value(None),
    )

    stream = await training_routes.stream_training_logs(
        "extval_123",
        user=SimpleNamespace(id="user_1", is_admin=lambda: False),
    )
    payload = _parse_sse_payload(await anext(stream))

    assert payload["task"]["task_type"] == "wsi_classification"
    assert payload["task"]["wsi_count"] == 7

    await stream.aclose()


async def _async_value(value):
    return value
