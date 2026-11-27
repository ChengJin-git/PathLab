from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from collections.abc import Awaitable, Callable, Mapping
from importlib import import_module
from typing import Any

from backend.common.task_dispatch import TaskDescriptor
from task_worker.jobs import analysis as analysis_jobs
from task_worker.jobs import chat_patch as chat_patch_jobs
from task_worker.jobs import inference as inference_jobs
from task_worker.jobs import training as training_jobs


class UnknownTaskHandlerError(Exception):
    def __init__(self, handler_name: str) -> None:
        super().__init__(f"Unknown task handler: {handler_name!r}")
        self.handler_name = handler_name


_REGISTRY: dict[str, Callable[[TaskDescriptor], Awaitable[None]]] = {}


def _register(name: str, fn: Callable[[TaskDescriptor], Awaitable[None]]) -> None:
    _REGISTRY[name] = fn


def resolve_handler(handler_name: str) -> Callable[[TaskDescriptor], Awaitable[None]]:
    try:
        return _REGISTRY[handler_name]
    except KeyError:
        raise UnknownTaskHandlerError(handler_name)


async def dispatch_descriptor(descriptor: TaskDescriptor) -> None:
    handler = resolve_handler(descriptor.handler)
    await handler(descriptor)


def _task_queue_parts():
    module = import_module("task_worker.task_queue")
    return module.get_task_queue, module.TaskType


def _payload_kwargs(payload: Mapping[str, object]) -> dict[str, object]:
    return {str(k): v for k, v in payload.items() if k != "task_id"}


def _runner_kwargs(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("runner_kwargs must be a JSON object")
    return {str(k): v for k, v in value.items()}


def _json_object(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a JSON object")
    return {str(k): v for k, v in value.items()}


def _paths_to_check(value: object) -> list[list[Any]]:
    if not isinstance(value, list):
        raise ValueError("paths_to_check must be a JSON array")
    paths: list[list[Any]] = []
    for item in value:
        if not isinstance(item, list):
            raise ValueError("paths_to_check entries must be JSON arrays")
        paths.append(item)
    return paths


async def handle_training_preflight(descriptor: TaskDescriptor) -> None:
    payload = descriptor.payload
    task_id = str(payload["task_id"])
    get_task_queue, _ = _task_queue_parts()
    if get_task_queue().is_task_in_queue(task_id):
        return
    paths_to_check = _paths_to_check(payload["paths_to_check"])
    uploads_dir = str(payload["uploads_dir"])
    pipeline_kwargs = _json_object(payload["pipeline_kwargs"], "pipeline_kwargs")
    await training_jobs.validate_files_and_enqueue(
        task_id, paths_to_check, uploads_dir, pipeline_kwargs
    )


async def handle_inference_single(descriptor: TaskDescriptor) -> None:
    get_task_queue, TaskType = _task_queue_parts()
    payload = descriptor.payload
    task_id = str(payload["task_id"])
    kwargs = _payload_kwargs(payload)
    await get_task_queue().submit(
        task_id=task_id,
        task_type=TaskType.INFERENCE,
        coro_func=inference_jobs.run_inference_via_ai_service,
        **kwargs,
    )


async def handle_inference_batch(descriptor: TaskDescriptor) -> None:
    get_task_queue, TaskType = _task_queue_parts()
    payload = descriptor.payload
    task_id = str(payload["task_id"])
    kwargs = _payload_kwargs(payload)
    await get_task_queue().submit(
        task_id=task_id,
        task_type=TaskType.BATCH_INFERENCE,
        coro_func=inference_jobs.run_batch_inference,
        **kwargs,
    )


async def handle_external_validation(descriptor: TaskDescriptor) -> None:
    get_task_queue, TaskType = _task_queue_parts()
    payload = descriptor.payload
    task_id = str(payload["task_id"])
    kwargs = _payload_kwargs(payload)

    async def _run_external_validation_without_queue_metadata(**queue_kwargs: object) -> object:
        runner_kwargs = dict(queue_kwargs)
        runner_kwargs.pop("preprocessing_config", None)
        return await inference_jobs.run_external_validation(**runner_kwargs)

    await get_task_queue().submit(
        task_id=task_id,
        task_type=TaskType.EXTERNAL_VALIDATION,
        coro_func=_run_external_validation_without_queue_metadata,
        **kwargs,
    )


async def handle_analysis(descriptor: TaskDescriptor) -> None:
    get_task_queue, TaskType = _task_queue_parts()
    payload = descriptor.payload
    task_id = str(payload["task_id"])
    module_name = str(payload["runner_module"])
    runner_name = str(payload["runner_name"])
    runner_kwargs = _runner_kwargs(payload.get("runner_kwargs"))
    _ = runner_kwargs.pop("task_id", None)
    fn = analysis_jobs.run_analysis_pipeline(module_name, runner_name)
    await get_task_queue().submit(
        task_id=task_id,
        task_type=TaskType.ANALYSIS,
        coro_func=fn,
        **runner_kwargs,
    )


async def handle_chat_patch_inference(descriptor: TaskDescriptor) -> None:
    get_task_queue, TaskType = _task_queue_parts()
    payload = descriptor.payload
    task_id = str(payload["task_id"])
    chat_patch_jobs.validate_chat_patch_payload(payload)

    async def _run_registered_chat_patch(**_queue_kwargs: object) -> object:
        return await chat_patch_jobs.run_chat_patch_task_from_payload(payload)

    await get_task_queue().submit(
        task_id=task_id,
        task_type=TaskType.ANALYSIS,
        coro_func=_run_registered_chat_patch,
    )


async def handle_training_run(descriptor: TaskDescriptor) -> None:
    get_task_queue, TaskType = _task_queue_parts()
    payload = descriptor.payload
    task_id = str(payload["task_id"])
    kwargs = _payload_kwargs(payload)
    await get_task_queue().submit(
        task_id=task_id,
        task_type=TaskType.TRAINING,
        coro_func=training_jobs.run_training_pipeline,
        staged=True,
        **kwargs,
    )


async def handle_training_patch_then_run(descriptor: TaskDescriptor) -> None:
    get_task_queue, _TaskType = _task_queue_parts()
    payload = descriptor.payload
    task_id = str(payload["task_id"])
    queue = get_task_queue()
    if queue.is_task_in_queue(task_id):
        return
    pipeline_kwargs = _payload_kwargs(payload)
    patching_coro = training_jobs.run_patching_then_submit(task_id, pipeline_kwargs)
    if not isinstance(patching_coro, Coroutine):
        raise TypeError("run_patching_then_submit must return a coroutine")
    patching_task = asyncio.create_task(patching_coro)
    queue.register_patching_task(task_id, patching_task)


async def handle_research(descriptor: TaskDescriptor) -> None:
    from backend.autoresearch.engine.jobs import run
    from backend.database.database import safe_session
    from backend.database.models import ResearchJob
    task_id = str(descriptor.payload["task_id"])
    async with safe_session() as db:
        job = await db.get(ResearchJob, task_id)
    if job is None or job.status != "queued":
        return
    get_task_queue, TaskType = _task_queue_parts()
    queue = get_task_queue()
    if queue.is_task_in_queue(task_id):
        return
    if job.kind == "download" or job.payload.get("device") == "cpu":
        task = asyncio.create_task(run(task_id=task_id))
        queue.register_patching_task(task_id, task)
        task.add_done_callback(lambda _task: queue.deregister_patching_task(task_id))
    else:
        if not job.payload.get('resources'):
            await queue._ensure_task_failed(task_id, TaskType.RESEARCH,
                'GPU resource description is missing. Resubmit with resources (operation/model/batch/input size or custom peak_vram_mb).')
            return
        await queue.submit(task_id=task_id, task_type=TaskType.RESEARCH, coro_func=run,
                           resources=job.payload['resources'])


_analysis_slots = asyncio.Semaphore(2)


async def handle_result_analysis(descriptor: TaskDescriptor) -> None:
    from backend.services.result_analysis.runs import execute_run
    get_task_queue, _ = _task_queue_parts()
    queue = get_task_queue()
    task_id = str(descriptor.payload["task_id"])
    if queue.is_task_in_queue(task_id):
        return

    async def run():
        async with _analysis_slots:
            await execute_run(task_id)

    task = asyncio.create_task(run())
    queue.register_patching_task(task_id, task)
    task.add_done_callback(lambda _: queue.deregister_patching_task(task_id))


_register("research.run", handle_research)
_register("results.analysis", handle_result_analysis)
_register("training.preflight", handle_training_preflight)
_register("training.run", handle_training_run)
_register("training.patch_then_run", handle_training_patch_then_run)
_register("inference.single", handle_inference_single)
_register("inference.batch", handle_inference_batch)
_register("external_validation.run", handle_external_validation)
_register("analysis.task", handle_analysis)
_register("chat.patch_inference", handle_chat_patch_inference)
