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


@pytest.mark.asyncio
async def test_chat_context_stats_uses_labeled_data_group_columns():
    from backend.database.repositories.wsi import WSIRepository

    stats_row = SimpleNamespace(total_count=1, wsi_count=1, patch_count=0)
    dataset_row = SimpleNamespace(
        dataset_id="dataset_1",
        dataset_name="Canonical WSI",
        dataset_owner_id="user_1",
        is_public=False,
        source_organ="lung",
        group_data_type="wsi",
        group_task_type="wsi_classification",
        aggregation_level="case",
        file_count=1,
        wsi_count=1,
        patch_count=0,
    )
    db = _SequentialDb(
        [
            _AsyncResult(one_value=stats_row),
            _AsyncResult(all_values=[]),
            _AsyncResult(all_values=[dataset_row]),
            _AsyncResult(all_values=[]),
            _AsyncResult(all_values=[]),
            _AsyncResult(all_values=[]),
            _AsyncResult(all_values=[]),
            _AsyncResult(all_values=[]),
        ]
    )

    stats = await WSIRepository.get_chat_context_stats(db)

    assert stats["datasets"][0]["data_type"] == "wsi"
    assert stats["datasets"][0]["group_task_type"] == "wsi_classification"


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


@pytest.mark.asyncio
async def test_external_validation_progress_uses_extval_prefix_not_task_type(monkeypatch):
    from gateway.routes import results as results_routes

    task = SimpleNamespace(
        task_id="extval_123",
        status="running",
        progress=45,
        error_message=None,
        data_group=SimpleNamespace(task_type="wsi_classification"),
        model_config={"total_wsi": 10, "processed_wsi": 0, "model_id": "m1"},
    )
    monkeypatch.setattr(
        results_routes,
        "_get_task_with_access",
        lambda *args, **kwargs: _async_value((task, None)),
    )
    monkeypatch.setattr(results_routes, "get_progress", lambda _task_id: _async_value(None))

    response = await results_routes.get_validation_progress(
        "extval_123",
        user=SimpleNamespace(id="user_1"),
        db=SimpleNamespace(),
    )

    assert response["task_id"] == "extval_123"
    assert response["total_wsi"] == 10
    assert response["processed_wsi"] == 5


@pytest.mark.asyncio
async def test_delete_training_task_returns_after_db_delete_without_waiting_for_storage_cleanup(monkeypatch):
    from gateway.routes import training as training_routes

    task = SimpleNamespace(
        task_id="task_123",
        user_id="user_1",
        status="completed",
    )
    model = SimpleNamespace(model_id="model_123")
    db = SimpleNamespace(commit=_async_value_none)
    scheduled = []

    def create_background_task(coro):
        scheduled.append(coro)
        coro.close()
        return SimpleNamespace()

    def fail_if_cleanup_runs_inline(*_args, **_kwargs):
        raise AssertionError("storage cleanup should be scheduled after the response")

    monkeypatch.setattr(
        training_routes.TrainingTaskRepository,
        "get_by_id",
        lambda *_args, **_kwargs: _async_value(task),
    )
    monkeypatch.setattr(
        training_routes.TrainedModelRepository,
        "get_by_task_id",
        lambda *_args, **_kwargs: _async_value([model]),
    )
    monkeypatch.setattr(
        training_routes.AIResultRepository,
        "delete_by_task_id",
        lambda *_args, **_kwargs: _async_value(0),
    )
    monkeypatch.setattr(
        training_routes.TrainingTaskRepository,
        "delete",
        lambda *_args, **_kwargs: _async_value(True),
    )
    monkeypatch.setattr(training_routes, "invalidate_chat_context", lambda *_args: _async_value(None))
    monkeypatch.setattr(training_routes.storage_manager, "delete_training_task_files", fail_if_cleanup_runs_inline)
    monkeypatch.setattr(training_routes.asyncio, "create_task", create_background_task)

    response = await training_routes.delete_training_task(
        "task_123",
        mode="standard",
        user=SimpleNamespace(id="user_1", role="pathologist", is_admin=lambda: False),
        db=db,
    )

    assert response["task_id"] == "task_123"
    assert response["storage_cleanup"]["status"] == "scheduled"
    assert scheduled


def test_gateway_startup_detects_extval_by_task_id_prefix():
    from gateway import startup

    assert startup._is_external_validation_task_id("extval_123") is True
    assert startup._is_external_validation_task_id("train_123") is False


async def _async_value(value):
    return value


async def _async_value_none():
    return None
