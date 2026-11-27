"""Shared FIFO recovery and worker-interruption semantics.

Persistence and checkpoint restoration belong to each executor. This module owns
ordering, serial recovery, and the distinction between shutdown and user cancel.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime, timezone
from typing import TypeVar

T = TypeVar('T')
RESTART_INTERRUPTION = 'worker_restart'


def timestamp(value: datetime | float) -> float:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).timestamp()
    return float(value)


def fifo_key(submitted_at: datetime | float, sequence: int | str) -> tuple[float, int | str]:
    """Persisted submission time plus a stable tie-breaker, independent of owner."""
    return timestamp(submitted_at), sequence


async def recover_fifo(
    rows: Iterable[T],
    *,
    key: Callable[[T], tuple[float, int | str]],
    restore: Callable[[T], Awaitable[None]],
) -> None:
    """Finish recovery in submission order before an executor admits new work."""
    for row in sorted(rows, key=key):
        await restore(row)


def is_restart_interruption(error: asyncio.CancelledError) -> bool:
    return error.args == (RESTART_INTERRUPTION,)


async def interrupt_for_restart(tasks: Iterable[asyncio.Task]) -> None:
    owned = set(tasks) - {asyncio.current_task()}
    for task in owned:
        # An existing user cancellation must retain its original meaning.
        if not task.done() and not task.cancelling():
            task.cancel(RESTART_INTERRUPTION)
    await asyncio.gather(*owned, return_exceptions=True)
