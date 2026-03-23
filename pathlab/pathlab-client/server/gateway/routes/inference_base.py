"""Shared helpers for all inference_* route modules."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional


def resolve_device(assigned_device: Optional[str] = None) -> str:
    import torch

    if assigned_device:
        return assigned_device
    return "cuda" if torch.cuda.is_available() else "cpu"


async def report_progress(
    progress_callback: Optional[Callable[[float], Awaitable[Any]]],
    idx: int,
    total: int,
    start: float = 0.1,
    end: float = 0.9,
) -> None:
    if progress_callback is not None and total > 0:
        value = start + (end - start) * (idx / total)
        await progress_callback(value)
