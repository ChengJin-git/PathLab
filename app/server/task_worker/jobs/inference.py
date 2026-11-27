from __future__ import annotations

from typing import Any


async def run_inference_via_ai_service(**kwargs: Any) -> Any:
    from gateway.routes.ai_tasks import run_inference_via_ai_service as impl

    return await impl(**kwargs)


async def run_batch_inference(**kwargs: Any) -> Any:
    from gateway.routes.inference_batch import _run_batch_inference as impl

    return await impl(**kwargs)


async def run_external_validation(**kwargs: Any) -> Any:
    from gateway.routes.inference_external_validation import _run_external_validation as impl

    return await impl(**kwargs)
