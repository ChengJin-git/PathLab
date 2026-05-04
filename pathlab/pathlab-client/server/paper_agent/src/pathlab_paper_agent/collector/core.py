"""Synchronous entrypoint for the deterministic collector stage.

The collector package is intentionally importable without `backend.*` on
sys.path. The DB code path (`collect_from_db`) lazily imports `backend.database`
internally, so importing this module does NOT pull the PathLab server tree.
This lets the collector be tested standalone (`pytest tests/test_collector.py`)
without going through `pathlab_paper_agent.pipeline` (which calls
`bootstrap.ensure_server_on_path()` as a side effect).
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Awaitable, TypeVar

from ..schemas import PaperConfig
from ._clock import utc_now
from .analysis import discover_analysis_runs
from .dataset import build_dataset_summary
from .db import collect_from_db
from .external_validation import build_external_validation_summary
from .model import build_model_summary
from .qualitative import build_qualitative_summary
from .role_dispatcher import descriptors_from_config
from .schemas import CollectorBundle, CollectorStatus, MissingEvidence
from .split import build_split_summary
from .task import missing_task_summary

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _run_coro_sync(coro: Awaitable[T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: T | None = None
    error: BaseException | None = None

    def _target() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive thread bridge
            error = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    return result  # type: ignore[return-value]


def collect_pathlab_evidence(
    config: PaperConfig,
    *,
    uploads_dir: Path,
    mode: str | None = None,
) -> CollectorBundle:
    requested_mode = (mode or os.getenv("PATHLAB_PAPER_AGENT_COLLECTOR_MODE", "auto")).lower()
    if requested_mode in {"off", "filesystem", "scaffold"}:
        return collect_filesystem_only(config, uploads_dir, mode=requested_mode)

    descriptors = descriptors_from_config(config)
    if requested_mode == "auto" and all(
        descriptor.task_id.startswith("paper_dev_source") for descriptor in descriptors
    ):
        return collect_filesystem_only(config, uploads_dir, mode="auto_scaffold")

    try:
        return _run_coro_sync(collect_from_db(config, uploads_dir))
    except Exception as exc:
        bundle = collect_filesystem_only(config, uploads_dir, mode="db_unavailable")
        bundle.collector_errors.append(str(exc))
        return bundle


def collect_filesystem_only(
    config: PaperConfig,
    uploads_dir: Path,
    *,
    mode: str = "filesystem",
) -> CollectorBundle:
    descriptors = descriptors_from_config(config)
    task_summaries = [
        missing_task_summary(
            descriptor,
            reason="DB collector was not available; only filesystem analysis artifacts were scanned.",
        )
        for descriptor in descriptors
    ]
    dataset_summaries = [build_dataset_summary(descriptor, []) for descriptor in descriptors]
    split_summaries = [build_split_summary(descriptor, []) for descriptor in descriptors]
    model_summaries = [build_model_summary(descriptor, []) for descriptor in descriptors]
    analysis_summaries = [discover_analysis_runs(uploads_dir, descriptor) for descriptor in descriptors]
    qualitative_summaries = [
        build_qualitative_summary(uploads_dir, descriptor, analysis)
        for descriptor, analysis in zip(descriptors, analysis_summaries)
    ]
    external_validation = build_external_validation_summary(
        descriptors,
        task_summaries,
        {item.task_id: item.status for item in analysis_summaries},
    )
    missing = _bundle_missing(
        task_summaries,
        dataset_summaries,
        split_summaries,
        model_summaries,
        analysis_summaries,
        qualitative_summaries,
        external_validation.missing_evidence,
    )
    return CollectorBundle(
        paper_id=config.paper_id,
        mode=mode,
        status=CollectorStatus.missing,
        collected_at=utc_now(),
        source_tasks=descriptors,
        task_summaries=task_summaries,
        dataset_summaries=dataset_summaries,
        split_summaries=split_summaries,
        model_summaries=model_summaries,
        analysis_summaries=analysis_summaries,
        external_validation_summary=external_validation,
        qualitative_summaries=qualitative_summaries,
        missing_evidence=missing,
    )


def _bundle_missing(*groups: object) -> list[MissingEvidence]:
    missing: list[MissingEvidence] = []
    for group in groups:
        if isinstance(group, list):
            for item in group:
                missing.extend(getattr(item, "missing_evidence", []) or [])
        else:
            missing.extend(getattr(group, "missing_evidence", []) or [])
    return missing
