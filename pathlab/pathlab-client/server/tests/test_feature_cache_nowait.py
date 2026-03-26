import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from backend.ai.tasks.feature_cache import (
    LockBusyError,
    try_file_lock_nowait,
    try_acquire_feature_lock_nowait,
    get_lock_path,
)


@pytest.fixture
def tmp_uploads(tmp_path):
    (tmp_path / "features" / ".locks" / "resnet50" / "abc12345").mkdir(parents=True)
    return tmp_path


@pytest.mark.asyncio
async def test_try_file_lock_nowait_acquires_when_free(tmp_path):
    lock_path = tmp_path / "test.lock"
    acquired = False
    async with try_file_lock_nowait(lock_path):
        acquired = True
    assert acquired


@pytest.mark.asyncio
async def test_try_file_lock_nowait_raises_when_busy(tmp_path):
    lock_path = tmp_path / "test.lock"
    lock_path.write_text("")
    # fcntl locks are per-process on Linux — must use subprocess to hold the lock
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import fcntl, time; f = open('{lock_path}', 'w'); "
            f"fcntl.flock(f, fcntl.LOCK_EX); time.sleep(10)",
        ]
    )
    await asyncio.sleep(0.15)
    try:
        with pytest.raises(LockBusyError):
            async with try_file_lock_nowait(lock_path):
                pass
    finally:
        holder.terminate()
        holder.wait()


@pytest.mark.asyncio
async def test_try_file_lock_nowait_releases_on_exit(tmp_path):
    lock_path = tmp_path / "test.lock"
    async with try_file_lock_nowait(lock_path):
        pass
    async with try_file_lock_nowait(lock_path):
        pass


@pytest.mark.asyncio
async def test_try_acquire_feature_lock_nowait_raises_when_busy(tmp_uploads):
    uploads_root = tmp_uploads
    wsi_id = "wsi-001"
    extractor = "resnet50"
    params_hash = "abc12345"
    lock_path = get_lock_path(uploads_root, extractor, params_hash, wsi_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("")
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import fcntl, time; f = open('{lock_path}', 'w'); "
            f"fcntl.flock(f, fcntl.LOCK_EX); time.sleep(10)",
        ]
    )
    await asyncio.sleep(0.15)
    try:
        with pytest.raises(LockBusyError) as exc_info:
            async with try_acquire_feature_lock_nowait(
                uploads_root, extractor, params_hash, wsi_id
            ):
                pass
        assert wsi_id in str(exc_info.value) or "busy" in str(exc_info.value).lower()
    finally:
        holder.terminate()
        holder.wait()


@pytest.mark.asyncio
async def test_try_acquire_feature_lock_nowait_succeeds_when_free(tmp_uploads):
    acquired = False
    async with try_acquire_feature_lock_nowait(
        tmp_uploads, "resnet50", "abc12345", "wsi-002"
    ):
        acquired = True
    assert acquired
