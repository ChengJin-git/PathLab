from __future__ import annotations

from importlib import import_module
from typing import cast
from collections.abc import Awaitable, Callable


_ALLOWED_ANALYSIS_RUNNERS: set[tuple[str, str]] = {
    ("gateway.routes.results", "run_analysis_pipeline"),
}


def run_analysis_pipeline(module_name: str, runner_name: str) -> Callable[..., Awaitable[object]]:
    if (module_name, runner_name) not in _ALLOWED_ANALYSIS_RUNNERS:
        raise ValueError(
            f"Analysis runner ({module_name!r}, {runner_name!r}) is not in allowlist"
        )
    mod = import_module(module_name)
    return cast(Callable[..., Awaitable[object]], getattr(mod, runner_name))
