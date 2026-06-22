from __future__ import annotations

from collections.abc import Mapping, Awaitable, Callable
from importlib import import_module
from typing import Any, cast

_ALLOWED_CHAT_PATCH_RUNNERS = {
    ("gateway.routes.chat_patch_inference", "_run_chat_patch_task"),
}


_REQUIRED_TASK_FIELDS = (
    "task_id",
    "conversation_id",
    "message_id",
    "user_id",
    "inference_type",
    "model_id",
    "model_name",
    "image_path",
    "created_at",
    "updated_at",
)


def run_chat_patch_inference(module_name: str, runner_name: str) -> Callable[..., Awaitable[object]]:
    _ensure_allowed_chat_patch_runner(module_name, runner_name)
    mod = import_module(module_name)
    return cast(Callable[..., Awaitable[object]], getattr(mod, runner_name))


def _ensure_allowed_chat_patch_runner(module_name: str, runner_name: str) -> None:
    if (module_name, runner_name) not in _ALLOWED_CHAT_PATCH_RUNNERS:
        raise ValueError(
            f"Chat patch runner is not in allowlist: {module_name}.{runner_name}"
        )


async def register_chat_patch_task_from_payload(payload: Mapping[str, object]) -> None:
    validate_chat_patch_payload(payload)

    module = import_module("gateway.routes.chat_patch_inference")
    values: dict[str, Any] = {field: payload[field] for field in _REQUIRED_TASK_FIELDS}
    task = module.ChatPatchTask(
        task_id=str(values["task_id"]),
        conversation_id=str(values["conversation_id"]),
        message_id=int(values["message_id"]),
        user_id=str(values["user_id"]),
        inference_type=str(values["inference_type"]),
        model_id=str(values["model_id"]),
        model_name=str(values["model_name"]),
        image_path=str(values["image_path"]),
        source=(None if payload.get("source") is None else str(payload["source"])),
        created_at=str(values["created_at"]),
        updated_at=str(values["updated_at"]),
    )

    lock = module._TASK_LOCK
    async with lock:
        module._TASKS[task.task_id] = task
        module._CONVERSATION_INDEX.setdefault(task.conversation_id, set()).add(task.task_id)


async def run_chat_patch_task_from_payload(payload: Mapping[str, object]) -> object:
    validate_chat_patch_payload(payload)
    module_name = payload.get("runner_module")
    runner_name = payload.get("runner_name")
    if not module_name or not runner_name:
        raise ValueError(
            "chat.patch_inference descriptor is missing runner metadata "
            + "(runner_module and runner_name)."
        )

    task_id = payload.get("task_id")
    if task_id is None:
        raise ValueError("chat.patch_inference descriptor is missing task_id")

    runner_kwargs: dict[str, object] = {"task_id": str(task_id)}
    raw_runner_kwargs = payload.get("runner_kwargs")
    if isinstance(raw_runner_kwargs, Mapping):
        runner_kwargs = {str(k): v for k, v in raw_runner_kwargs.items()}

    fn = run_chat_patch_inference(str(module_name), str(runner_name))
    return await fn(**runner_kwargs)


def validate_chat_patch_payload(payload: Mapping[str, object]) -> None:
    module_name = payload.get("runner_module")
    runner_name = payload.get("runner_name")
    if not module_name or not runner_name:
        raise ValueError(
            "chat.patch_inference descriptor is missing runner metadata "
            + "(runner_module and runner_name)."
        )
    _ensure_allowed_chat_patch_runner(str(module_name), str(runner_name))

    missing = [field for field in _REQUIRED_TASK_FIELDS if payload.get(field) is None]
    if missing:
        raise ValueError(
            "chat.patch_inference descriptor missing required task metadata: "
            + ", ".join(missing)
        )
