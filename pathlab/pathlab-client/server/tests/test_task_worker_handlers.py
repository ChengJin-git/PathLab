"""Tests for task_worker handler registry."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

from gateway.task_dispatch import build_task_descriptor


# ---------------------------------------------------------------------------
# Registry resolution tests
# ---------------------------------------------------------------------------

def test_resolve_training_preflight_handler():
    from task_worker.handlers import resolve_handler

    assert resolve_handler("training.preflight").__name__ == "handle_training_preflight"


def test_resolve_inference_single_handler():
    from task_worker.handlers import resolve_handler

    assert resolve_handler("inference.single").__name__ == "handle_inference_single"


def test_resolve_inference_batch_handler():
    from task_worker.handlers import resolve_handler

    assert resolve_handler("inference.batch").__name__ == "handle_inference_batch"


def test_resolve_external_validation_handler():
    from task_worker.handlers import resolve_handler

    assert resolve_handler("external_validation.run").__name__ == "handle_external_validation"


def test_resolve_analysis_handler():
    from task_worker.handlers import resolve_handler

    assert resolve_handler("analysis.task").__name__ == "handle_analysis"


def test_resolve_chat_patch_inference_handler():
    from task_worker.handlers import resolve_handler

    assert resolve_handler("chat.patch_inference").__name__ == "handle_chat_patch_inference"


def test_resolve_training_run_handler():
    from task_worker.handlers import resolve_handler

    assert resolve_handler("training.run").__name__ == "handle_training_run"


def test_resolve_training_patch_then_run_handler():
    from task_worker.handlers import resolve_handler

    assert resolve_handler("training.patch_then_run").__name__ == "handle_training_patch_then_run"


def test_unknown_handler_raises():
    from task_worker.handlers import resolve_handler, UnknownTaskHandlerError

    with pytest.raises(UnknownTaskHandlerError):
        resolve_handler("missing.handler")


# ---------------------------------------------------------------------------
# dispatch_descriptor tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_descriptor_routes_to_handler(monkeypatch):
    from task_worker.handlers import dispatch_descriptor

    called_with = {}

    async def fake_handler(descriptor):
        called_with["descriptor"] = descriptor

    monkeypatch.setattr(
        "task_worker.handlers.resolve_handler", lambda name: fake_handler
    )

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="training",
        handler="training.preflight",
        payload={"task_id": "t1"},
    )
    await dispatch_descriptor(descriptor)
    assert called_with["descriptor"] is descriptor


@pytest.mark.asyncio
async def test_dispatch_descriptor_unknown_handler(monkeypatch):
    from task_worker.handlers import dispatch_descriptor, UnknownTaskHandlerError

    monkeypatch.setattr(
        "task_worker.handlers.resolve_handler",
        lambda name: (_ for _ in ()).throw(UnknownTaskHandlerError(name)),
    )

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="training",
        handler="no.such.handler",
        payload={},
    )
    with pytest.raises(UnknownTaskHandlerError):
        await dispatch_descriptor(descriptor)


# ---------------------------------------------------------------------------
# Handler behaviour tests (monkeypatched so no real heavy work runs)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_queue(monkeypatch):
    queue = MagicMock()
    queue.submit = AsyncMock()
    monkeypatch.setattr(
        "gateway.task_queue.get_task_queue", lambda: queue
    )
    return queue


@pytest.mark.asyncio
async def test_training_preflight_calls_validate_files_and_enqueue(monkeypatch):
    from task_worker.handlers import handle_training_preflight
    from gateway.task_dispatch import build_task_descriptor

    called = {}

    async def fake_validate(task_id, paths_to_check, uploads_dir, pipeline_kwargs):
        called["args"] = {
            "task_id": task_id,
            "paths_to_check": paths_to_check,
            "uploads_dir": uploads_dir,
            "pipeline_kwargs": pipeline_kwargs,
        }

    monkeypatch.setattr(
        "task_worker.jobs.training.validate_files_and_enqueue", fake_validate
    )

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="training",
        handler="training.preflight",
        payload={
            "task_id": "t1",
            "paths_to_check": [["a", "b"]],
            "uploads_dir": "/uploads",
            "pipeline_kwargs": {"data_type": "patch"},
        },
    )
    await handle_training_preflight(descriptor)
    assert called["args"]["task_id"] == "t1"
    assert called["args"]["paths_to_check"] == [["a", "b"]]
    assert called["args"]["uploads_dir"] == "/uploads"
    assert called["args"]["pipeline_kwargs"] == {"data_type": "patch"}


@pytest.mark.asyncio
async def test_inference_single_submits_to_queue(mock_queue, monkeypatch):
    from task_worker.handlers import handle_inference_single
    from gateway.task_dispatch import build_task_descriptor
    from gateway.task_queue import TaskType

    async def fake_inference(*args, **kwargs):
        pass

    monkeypatch.setattr(
        "task_worker.jobs.inference.run_inference_via_ai_service", fake_inference
    )

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="inference",
        handler="inference.single",
        payload={"task_id": "t1", "wsi_id": "w1", "model_id": "m1", "extra": 1},
    )
    await handle_inference_single(descriptor)

    mock_queue.submit.assert_awaited_once()
    call_kwargs = mock_queue.submit.await_args.kwargs
    assert call_kwargs["task_id"] == "t1"
    assert call_kwargs["task_type"] == TaskType.INFERENCE
    assert call_kwargs["coro_func"] is fake_inference
    assert call_kwargs["wsi_id"] == "w1"
    assert call_kwargs["model_id"] == "m1"
    assert call_kwargs["extra"] == 1


@pytest.mark.asyncio
async def test_inference_batch_submits_to_queue(mock_queue, monkeypatch):
    from task_worker.handlers import handle_inference_batch
    from gateway.task_dispatch import build_task_descriptor
    from gateway.task_queue import TaskType

    async def fake_batch(*args, **kwargs):
        pass

    monkeypatch.setattr(
        "task_worker.jobs.inference.run_batch_inference", fake_batch
    )

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="inference",
        handler="inference.batch",
        payload={"task_id": "t1", "dataset_id": "d1"},
    )
    await handle_inference_batch(descriptor)

    mock_queue.submit.assert_awaited_once()
    call_kwargs = mock_queue.submit.await_args.kwargs
    assert call_kwargs["task_id"] == "t1"
    assert call_kwargs["task_type"] == TaskType.BATCH_INFERENCE
    assert call_kwargs["coro_func"] is fake_batch
    assert call_kwargs["dataset_id"] == "d1"


@pytest.mark.asyncio
async def test_external_validation_submits_to_queue(mock_queue, monkeypatch):
    from task_worker.handlers import handle_external_validation
    from gateway.task_dispatch import build_task_descriptor
    from gateway.task_queue import TaskType

    async def fake_extval(*args, **kwargs):
        pass

    monkeypatch.setattr(
        "task_worker.jobs.inference.run_external_validation", fake_extval
    )

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="validation",
        handler="external_validation.run",
        payload={"task_id": "t1", "dataset_id": "d1"},
    )
    await handle_external_validation(descriptor)

    mock_queue.submit.assert_awaited_once()
    call_kwargs = mock_queue.submit.await_args.kwargs
    assert call_kwargs["task_id"] == "t1"
    assert call_kwargs["task_type"] == TaskType.EXTERNAL_VALIDATION
    assert call_kwargs["coro_func"] is fake_extval
    assert call_kwargs["dataset_id"] == "d1"


@pytest.mark.asyncio
async def test_external_validation_preserves_preprocessing_config_for_queue_submit(
    mock_queue, monkeypatch
):
    from task_worker.handlers import handle_external_validation
    from gateway.task_dispatch import build_task_descriptor

    async def fake_extval(*args, **kwargs):
        pass

    monkeypatch.setattr(
        "task_worker.jobs.inference.run_external_validation", fake_extval
    )

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="validation",
        handler="external_validation.run",
        payload={
            "task_id": "t1",
            "dataset_id": "d1",
            "preprocessing_config": {"feature_extractor": "resnet50"},
        },
    )

    await handle_external_validation(descriptor)

    call_kwargs = mock_queue.submit.await_args.kwargs
    assert call_kwargs["preprocessing_config"] == {"feature_extractor": "resnet50"}
    assert call_kwargs["dataset_id"] == "d1"


@pytest.mark.asyncio
async def test_analysis_submits_to_queue(mock_queue, monkeypatch):
    from task_worker.handlers import handle_analysis
    from gateway.task_dispatch import build_task_descriptor
    from gateway.task_queue import TaskType

    async def fake_runner(*args, **kwargs):
        pass

    def fake_analysis_adapter(module_name, runner_name):
        assert module_name == "gateway.routes.results"
        assert runner_name == "run_analysis_pipeline"
        return fake_runner

    monkeypatch.setattr(
        "task_worker.jobs.analysis.run_analysis_pipeline", fake_analysis_adapter
    )

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="analysis",
        handler="analysis.task",
        payload={
            "task_id": "t1",
            "task_type": "custom_analysis",
            "runner_module": "gateway.routes.results",
            "runner_name": "run_analysis_pipeline",
            "runner_kwargs": {"foo": "bar"},
        },
    )
    await handle_analysis(descriptor)

    mock_queue.submit.assert_awaited_once()
    call_kwargs = mock_queue.submit.await_args.kwargs
    assert call_kwargs["task_id"] == "t1"
    assert call_kwargs["task_type"] == TaskType.ANALYSIS
    assert call_kwargs["coro_func"] is fake_runner
    assert call_kwargs["foo"] == "bar"


@pytest.mark.asyncio
async def test_analysis_allows_runner_kwargs_to_include_task_id(mock_queue, monkeypatch):
    from task_worker.handlers import handle_analysis
    from gateway.task_dispatch import build_task_descriptor

    async def fake_runner(*args, **kwargs):
        pass

    monkeypatch.setattr(
        "task_worker.jobs.analysis.run_analysis_pipeline",
        lambda _module_name, _runner_name: fake_runner,
    )

    descriptor = build_task_descriptor(
        job_id="analysis-1",
        job_kind="analysis",
        handler="analysis.task",
        payload={
            "task_id": "analysis-1",
            "runner_module": "gateway.routes.results",
            "runner_name": "run_analysis_pipeline",
            "runner_kwargs": {
                "task_id": "analysis-1",
                "analysis_id": "analysis-1",
                "training_task_id": "train-1",
            },
        },
    )

    await handle_analysis(descriptor)

    mock_queue.submit.assert_awaited_once()
    call_kwargs = mock_queue.submit.await_args.kwargs
    assert call_kwargs["task_id"] == "analysis-1"
    assert call_kwargs["analysis_id"] == "analysis-1"
    assert call_kwargs["training_task_id"] == "train-1"


@pytest.mark.asyncio
async def test_analysis_rejects_unauthorized_runner(mock_queue):
    from task_worker.handlers import handle_analysis
    from gateway.task_dispatch import build_task_descriptor

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="analysis",
        handler="analysis.task",
        payload={
            "task_id": "t1",
            "runner_module": "os",
            "runner_name": "system",
        },
    )
    with pytest.raises(ValueError, match="not in allowlist"):
        await handle_analysis(descriptor)


@pytest.mark.asyncio
async def test_chat_patch_inference_submits_to_queue(mock_queue, monkeypatch):
    from task_worker.handlers import handle_chat_patch_inference
    from gateway.task_dispatch import build_task_descriptor
    from gateway.task_queue import TaskType

    runner_calls = []

    async def fake_runner(*args, **kwargs):
        runner_calls.append((args, kwargs))
        pass

    def fake_chat_patch_adapter(module_name, runner_name):
        assert module_name == "gateway.routes.chat_patch_inference"
        assert runner_name == "_run_chat_patch_task"
        return fake_runner

    monkeypatch.setattr(
        "task_worker.jobs.chat_patch.run_chat_patch_inference", fake_chat_patch_adapter
    )

    run_from_payload_mock = AsyncMock()
    monkeypatch.setattr("task_worker.jobs.chat_patch.run_chat_patch_task_from_payload", run_from_payload_mock)

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="chat",
        handler="chat.patch_inference",
        payload={
            "task_id": "t1",
            "conversation_id": "c1",
            "message_id": 3,
            "user_id": "u1",
            "inference_type": "classification",
            "model_id": "m1",
            "model_name": "Model One",
            "image_path": "/tmp/input.png",
            "source": "llm",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "runner_module": "gateway.routes.chat_patch_inference",
            "runner_name": "_run_chat_patch_task",
            "runner_kwargs": {"task_id": "t1"},
        },
    )
    await handle_chat_patch_inference(descriptor)

    run_from_payload_mock.assert_not_awaited()
    mock_queue.submit.assert_awaited_once()
    call_kwargs = mock_queue.submit.await_args.kwargs
    assert call_kwargs["task_id"] == "t1"
    assert call_kwargs["task_type"] == TaskType.ANALYSIS
    await call_kwargs["coro_func"]()
    run_from_payload_mock.assert_awaited_once_with(descriptor.payload)
    assert runner_calls == []


@pytest.mark.asyncio
async def test_chat_patch_inference_missing_runner_raises():
    from task_worker.handlers import handle_chat_patch_inference
    from gateway.task_dispatch import build_task_descriptor

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="chat",
        handler="chat.patch_inference",
        payload={"task_id": "t1"},
    )
    with pytest.raises(ValueError, match="runner metadata"):
        await handle_chat_patch_inference(descriptor)


@pytest.mark.asyncio
async def test_chat_patch_inference_missing_required_task_metadata_raises():
    from task_worker.handlers import handle_chat_patch_inference
    from gateway.task_dispatch import build_task_descriptor

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="chat",
        handler="chat.patch_inference",
        payload={
            "task_id": "t1",
            "runner_module": "gateway.routes.chat_patch_inference",
            "runner_name": "_run_chat_patch_task",
            "runner_kwargs": {"task_id": "t1"},
        },
    )
    with pytest.raises(ValueError, match="missing required task metadata"):
        await handle_chat_patch_inference(descriptor)


@pytest.mark.asyncio
async def test_chat_patch_inference_rejects_unauthorized_runner(mock_queue):
    from task_worker.handlers import handle_chat_patch_inference
    from gateway.task_dispatch import build_task_descriptor

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="chat",
        handler="chat.patch_inference",
        payload={
            "task_id": "t1",
            "conversation_id": "c1",
            "message_id": 3,
            "user_id": "u1",
            "inference_type": "classification",
            "model_id": "m1",
            "model_name": "Model One",
            "image_path": "/tmp/input.png",
            "source": "llm",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "runner_module": "os",
            "runner_name": "system",
            "runner_kwargs": {"task_id": "t1"},
        },
    )

    with pytest.raises(ValueError, match="not in allowlist"):
        await handle_chat_patch_inference(descriptor)

    mock_queue.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_training_run_submits_to_queue(mock_queue, monkeypatch):
    from task_worker.handlers import handle_training_run
    from gateway.task_dispatch import build_task_descriptor
    from gateway.task_queue import TaskType

    async def fake_pipeline(*args, **kwargs):
        pass

    monkeypatch.setattr(
        "task_worker.jobs.training.run_training_pipeline", fake_pipeline
    )

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="training",
        handler="training.run",
        payload={
            "task_id": "t1",
            "data_type": "patch",
            "wsi_ids": ["img1"],
            "preprocessing_config": {"foo": "bar"},
            "model_config": {"epochs": 5},
            "training_task_type": "patch_classification",
        },
    )
    await handle_training_run(descriptor)

    mock_queue.submit.assert_awaited_once()
    call_kwargs = mock_queue.submit.await_args.kwargs
    assert call_kwargs["task_id"] == "t1"
    assert call_kwargs["task_type"] == TaskType.TRAINING
    assert call_kwargs["coro_func"] is fake_pipeline
    assert call_kwargs["data_type"] == "patch"
    assert call_kwargs["wsi_ids"] == ["img1"]
    assert call_kwargs["preprocessing_config"] == {"foo": "bar"}
    assert call_kwargs["model_config"] == {"epochs": 5}
    assert call_kwargs["training_task_type"] == "patch_classification"


@pytest.mark.asyncio
async def test_training_patch_then_run_registers_patching_task(mock_queue, monkeypatch):
    from task_worker.handlers import handle_training_patch_then_run
    from gateway.task_dispatch import build_task_descriptor

    patching_task = MagicMock()

    async def fake_patching(task_id, pipeline_kwargs):
        return patching_task

    monkeypatch.setattr(
        "task_worker.jobs.training.run_patching_then_submit", fake_patching
    )

    def fake_create_task(coro):
        coro.close()
        return patching_task

    monkeypatch.setattr(
        "task_worker.handlers.asyncio.create_task", fake_create_task
    )

    descriptor = build_task_descriptor(
        job_id="j1",
        job_kind="training",
        handler="training.patch_then_run",
        payload={
            "task_id": "t1",
            "data_type": "wsi",
            "wsi_ids": ["w1"],
            "preprocessing_config": {"foo": "bar"},
            "model_config": {"epochs": 10},
            "training_task_type": "wsi_classification",
        },
    )
    await handle_training_patch_then_run(descriptor)

    mock_queue.register_patching_task.assert_called_once_with("t1", patching_task)


# ---------------------------------------------------------------------------
# Lazy-import isolation test
# ---------------------------------------------------------------------------

def test_importing_handlers_does_not_import_heavy_modules():
    """Importing task_worker.handlers must not pull in route modules, torch, or task_queue internals."""
    import sys

    # Determine what modules are already loaded before importing handlers.
    preloaded = set(sys.modules.keys())

    import importlib
    import task_worker.handlers as handlers_module
    importlib.reload(handlers_module)

    newly_loaded = set(sys.modules.keys()) - preloaded

    # The handlers module itself and gateway.task_dispatch are fine.
    # gateway.task_queue is *not* fine because it imports torch indirectly.
    assert "gateway.task_queue" not in newly_loaded, (
        f"gateway.task_queue was loaded as a side-effect: {newly_loaded}"
    )
    assert "torch" not in newly_loaded, (
        f"torch was loaded as a side-effect: {newly_loaded}"
    )
