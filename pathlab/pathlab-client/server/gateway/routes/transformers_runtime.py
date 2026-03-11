"""Thread-safe warmup helpers for shared Transformers runtime imports.

This module prevents a race where concurrent first-time imports of
`sentence_transformers` and `docling` can observe a partially initialized
`transformers` package. We pre-import the specific symbols that Docling needs
under a process-local lock, and reuse the helper from both code paths.
"""

from __future__ import annotations

import threading

from ..dependencies import logger

_transformers_runtime_ready = False
_transformers_runtime_lock = threading.Lock()


def ensure_transformers_runtime_ready(reason: str | None = None) -> None:
    """Warm up `transformers` imports once per process in a thread-safe way."""
    global _transformers_runtime_ready

    if _transformers_runtime_ready:
        return

    with _transformers_runtime_lock:
        if _transformers_runtime_ready:
            return

        suffix = f" for {reason}" if reason else ""
        logger.info(f"[TransformersRuntime] Warming up shared transformers imports{suffix}")

        import transformers
        from transformers import StoppingCriteria

        # Touch the imported objects so the warmup is explicit and lint-friendly.
        _ = transformers.__version__
        _ = StoppingCriteria

        _transformers_runtime_ready = True
        logger.info("[TransformersRuntime] Shared transformers warmup complete")

