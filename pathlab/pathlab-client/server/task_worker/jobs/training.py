from __future__ import annotations

from collections.abc import Awaitable, Sequence
from typing import Any


async def validate_files_and_enqueue(
    task_id: str,
    paths_to_check: Sequence[Sequence[Any]],
    uploads_dir: str,
    pipeline_kwargs: dict[str, Any],
) -> None:
    from gateway.pipeline import resolve_training_input_ref
    from gateway.routes.training import _validate_files_and_enqueue as impl

    resolved_kwargs, resolved_paths_to_check = await resolve_training_input_ref(
        task_id, pipeline_kwargs
    )
    await impl(task_id, resolved_paths_to_check, uploads_dir, resolved_kwargs)


async def run_training_pipeline(**kwargs: Any) -> Any:
    from gateway.pipeline import run_training_pipeline as impl

    return await impl(**kwargs)


def run_patching_then_submit(task_id: str, pipeline_kwargs: dict[str, Any]) -> Awaitable[Any]:
    from gateway.pipeline import run_patching_then_submit as impl

    return impl(task_id, pipeline_kwargs)
