# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Runtime stop-request registry for cooperative cancellation."""

from __future__ import annotations

from threading import Lock

_lock = Lock()
_requested_threads: set[str] = set()


def request_stop(thread_id: str) -> None:
    if not thread_id:
        return
    with _lock:
        _requested_threads.add(thread_id)


def clear_stop(thread_id: str) -> None:
    if not thread_id:
        return
    with _lock:
        _requested_threads.discard(thread_id)


def is_stop_requested(thread_id: str) -> bool:
    if not thread_id:
        return False
    with _lock:
        return thread_id in _requested_threads

