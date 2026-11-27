import asyncio
import os
import random
from collections.abc import Awaitable, Sequence
from collections import defaultdict
from dataclasses import dataclass
from importlib import import_module
from typing import Callable

from fastapi import HTTPException


Config = import_module("backend.common.config").Config


PathCheckItem = tuple[object, str, str]
PathExistsFn = Callable[[str], Awaitable[bool]]
SampleFn = Callable[[Sequence[PathCheckItem], int], list[PathCheckItem]]
WarnFn = Callable[[str], None]


@dataclass(frozen=True)
class PreflightPolicy:
    local_root_timeout_seconds: float
    local_sample_timeout_seconds: float
    local_sample_size: int
    external_root_timeout_seconds: float
    external_sample_timeout_seconds: float
    external_sample_size: int


@dataclass(frozen=True)
class PreflightCheckResult:
    inaccessible: list[str]


async def _default_path_exists(path: str) -> bool:
    return await asyncio.to_thread(os.path.exists, path)


def _default_sample(items: Sequence[PathCheckItem], size: int) -> list[PathCheckItem]:
    if size <= 0:
        return []
    if len(items) <= size:
        return list(items)
    return random.sample(list(items), size)


def _mount_root(path: str) -> str:
    abs_path = os.path.abspath(path)
    try:
        with open("/proc/mounts") as f:
            mounts = [line.split()[1] for line in f if len(line.split()) >= 2]
        return max(
            (
                m
                for m in mounts
                if abs_path == m.rstrip("/")
                or abs_path.startswith(m.rstrip("/") + "/")
            ),
            key=len,
            default="/",
        )
    except OSError:
        cur = abs_path
        while cur != "/":
            parent = os.path.dirname(cur)
            if os.path.ismount(cur):
                return cur
            cur = parent
        return "/"


async def _check_root(
    root: str,
    timeout_seconds: float,
    path_exists_fn: PathExistsFn,
    *,
    timeout_status: int,
    timeout_detail: str,
    missing_status: int,
    missing_detail: str,
) -> None:
    try:
        accessible = await asyncio.wait_for(
            path_exists_fn(root),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=timeout_status, detail=timeout_detail) from exc

    if not accessible:
        raise HTTPException(status_code=missing_status, detail=missing_detail)


async def _sample_paths(
    items: Sequence[PathCheckItem],
    sample_size: int,
    timeout_seconds: float,
    path_exists_fn: PathExistsFn,
    sample_fn: SampleFn,
) -> list[str]:
    sample = sample_fn(items, sample_size)
    if not sample:
        return []

    async def _stat(
        wsi_id: object, path: str, filename: str
    ) -> tuple[object, str, str, bool]:
        exists = await path_exists_fn(path)
        return (wsi_id, path, filename, exists)

    results = await asyncio.wait_for(
        asyncio.gather(*[_stat(wid, p, fn) for wid, p, fn in sample]),
        timeout=timeout_seconds,
    )
    return [fn or str(wid) for wid, _, fn, ok in results if not ok]


def build_training_preflight_policy() -> PreflightPolicy:
    return PreflightPolicy(
        local_root_timeout_seconds=Config.DEFAULT_TRAINING_PREFLIGHT_LOCAL_ROOT_TIMEOUT,
        local_sample_timeout_seconds=Config.DEFAULT_TRAINING_PREFLIGHT_LOCAL_SAMPLE_TIMEOUT,
        local_sample_size=Config.DEFAULT_TRAINING_PREFLIGHT_LOCAL_SAMPLE_SIZE,
        external_root_timeout_seconds=Config.DEFAULT_TRAINING_PREFLIGHT_EXTERNAL_ROOT_TIMEOUT,
        external_sample_timeout_seconds=Config.DEFAULT_TRAINING_PREFLIGHT_EXTERNAL_SAMPLE_TIMEOUT,
        external_sample_size=Config.DEFAULT_TRAINING_PREFLIGHT_EXTERNAL_SAMPLE_SIZE,
    )


async def check_training_inputs(
    paths_to_check: Sequence[PathCheckItem],
    uploads_dir: str,
    policy: PreflightPolicy,
    path_exists_fn: PathExistsFn | None = None,
    sample_fn: SampleFn | None = None,
    warn_fn: WarnFn | None = None,
) -> PreflightCheckResult:
    # Submit-time preflight verifies storage health and obvious corruption signals.
    # It intentionally avoids exhaustive per-file enumeration for large patch datasets.
    # Full file traversal belongs to the runtime pipeline, where failures can be logged
    # against the exact worker, stage, and sample being processed.
    path_exists = path_exists_fn or _default_path_exists
    sample = sample_fn or _default_sample
    uploads_root = os.path.abspath(uploads_dir)
    uploads_boundary = uploads_root.rstrip(os.sep) + os.sep

    local_paths = [
        (wid, p, fn)
        for wid, p, fn in paths_to_check
        if os.path.abspath(p) == uploads_root
        or os.path.abspath(p).startswith(uploads_boundary)
    ]
    external_paths = [
        (wid, p, fn)
        for wid, p, fn in paths_to_check
        if not (
            os.path.abspath(p) == uploads_root
            or os.path.abspath(p).startswith(uploads_boundary)
        )
    ]

    inaccessible: list[str] = []

    if local_paths:
        await _check_root(
            uploads_dir,
            policy.local_root_timeout_seconds,
            path_exists,
            timeout_status=503,
            timeout_detail=(
                f"Local storage I/O timeout after {policy.local_root_timeout_seconds}s. "
                "The server may be experiencing disk issues."
            ),
            missing_status=503,
            missing_detail=(
                "Local storage root is not accessible. Please verify local storage and try again."
            ),
        )
        try:
            inaccessible.extend(
                await _sample_paths(
                    local_paths,
                    policy.local_sample_size,
                    policy.local_sample_timeout_seconds,
                    path_exists,
                    sample,
                )
            )
        except asyncio.TimeoutError:
            if warn_fn is not None:
                warn_fn(
                    "Local storage sample check timed out but storage root is accessible — allowing submission to proceed."
                )

    if external_paths:
        paths_by_root: dict[str, list[PathCheckItem]] = defaultdict(list)
        for item in external_paths:
            paths_by_root[_mount_root(item[1])].append(item)

        for root in paths_by_root:
            await _check_root(
                root,
                policy.external_root_timeout_seconds,
                path_exists,
                timeout_status=408,
                timeout_detail=(
                    "External storage not responding "
                    f"(timed out after {policy.external_root_timeout_seconds}s): {root}. "
                    "Please check your network storage connection and try again."
                ),
                missing_status=503,
                missing_detail=(
                    f"External storage mount is not accessible: {root}. "
                    "Please ensure the network storage is mounted and try again."
                ),
            )

        for root, items in paths_by_root.items():
            try:
                inaccessible.extend(
                    await _sample_paths(
                        items,
                        policy.external_sample_size,
                        policy.external_sample_timeout_seconds,
                        path_exists,
                        sample,
                    )
                )
            except asyncio.TimeoutError:
                if warn_fn is not None:
                    warn_fn(
                        f"External storage sample check timed out but mount roots are accessible — allowing submission to proceed. Root: {root}"
                    )

    return PreflightCheckResult(inaccessible=inaccessible)
