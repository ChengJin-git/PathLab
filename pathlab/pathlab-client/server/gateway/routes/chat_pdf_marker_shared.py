from __future__ import annotations

import contextvars
import hashlib
from contextlib import contextmanager

MARKER_CACHE_SUFFIX = ".marker.md"
STRUCTURED_CACHE_SUFFIX = ".structured.json"
PDF_PARSE_METHOD_MARKER = "marker"
PDF_PARSE_METHOD_PYMUPDF = "pymupdf"

_marker_gpu_queue_override: contextvars.ContextVar[bool | None] = (
    contextvars.ContextVar(
        "marker_gpu_queue_override",
        default=None,
    )
)


def get_url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


@contextmanager
def override_marker_gpu_queue(skip: bool):
    token = _marker_gpu_queue_override.set(bool(skip))
    try:
        yield
    finally:
        _marker_gpu_queue_override.reset(token)


def get_marker_gpu_queue_override() -> bool | None:
    return _marker_gpu_queue_override.get()
