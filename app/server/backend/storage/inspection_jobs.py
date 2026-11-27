"""Cross-process single-flight inspection jobs with persisted progress and snapshots."""

from __future__ import annotations

import asyncio
from backend.common import file_lock as fcntl
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4
from backend.common.config import Config

_tasks = set()
COOLDOWN = 30


def directory(storage_root=None):
    root = Path(storage_root or Config.get_uploads_dir()) / ".storage-inspections"
    root.mkdir(parents=True, exist_ok=True)
    return root


def key(kind, scope="", storage_root=None):
    return hashlib.sha256(
        json.dumps(
            [str(storage_root or Config.get_uploads_dir()), kind, scope]
        ).encode()
    ).hexdigest()


def write(path, value):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def status(kind, scope="", *, result=False):
    identity = key(kind, scope)
    root = directory()
    value = load(root / (identity + ".json"))
    if not value:
        return {"kind": kind, "status": "idle"}
    if value["status"] in {"queued", "running", "cancelling"}:
        with (root / (identity + ".lock")).open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                value = load(root / (identity + ".json")) or value
                if value["status"] in {"queued", "running", "cancelling"}:
                    value = {
                        **value,
                        "status": "interrupted",
                        "error": "Inspection interrupted; start again to retry",
                    }
                    write(root / (identity + ".json"), value)
    if result and value["status"] == "completed":
        value["result"] = load(root / (identity + ".result.json"))
    return value


class Progress:
    def __init__(self, root, identity, value):
        self.root, self.identity, self.value = root, identity, value
        self.last = 0.0

    def update(self, processed=0, total=None, stage="", *, force=False):
        if (self.root / (self.identity + ".cancel")).exists():
            raise InterruptedError("Inspection cancelled")
        if not force and time.monotonic() - self.last < 0.3:
            return
        self.last = time.monotonic()
        self.value = {
            **self.value,
            "status": "running",
            "processed": processed,
            "total": total,
            "stage": stage,
            "updated_at": time.time(),
        }
        write(self.root / (self.identity + ".json"), self.value)


async def start(kind, scope, runner):
    # Admission is synchronous and short: it never touches the data tree.
    root = directory()
    identity = key(kind, scope)
    lock = (root / (identity + ".lock")).open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return {
            **(load(root / (identity + ".json")) or {"kind": kind, "status": "queued"}),
            "reused": True,
        }
    previous = load(root / (identity + ".json"))
    if (
        previous
        and previous["status"] in {"completed", "failed", "cancelled"}
        and time.time() - previous.get("finished_at", 0) < COOLDOWN
    ):
        lock.close()
        return {**previous, "reused": True}
    value = {
        "id": uuid4().hex,
        "kind": kind,
        "status": "queued",
        "processed": 0,
        "total": None,
        "stage": "queued",
        "started_at": time.time(),
        "updated_at": time.time(),
        "reused": False,
    }
    (root / (identity + ".cancel")).unlink(missing_ok=True)
    write(root / (identity + ".json"), value)

    async def run():
        progress = Progress(root, identity, value)
        global_lock = (root / "heavy-scan.lock").open("a")
        try:
            while True:
                if (root / (identity + ".cancel")).exists():
                    raise InterruptedError("Inspection cancelled")
                try:
                    fcntl.flock(global_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.2)
            progress.update(stage="preparing", force=True)
            result = await runner(progress)
            progress.update(
                progress.value.get("processed", 0),
                progress.value.get("total"),
                stage="complete",
                force=True,
            )
            await asyncio.to_thread(write, root / (identity + ".result.json"), result)
            write(
                root / (identity + ".json"),
                {**progress.value, "status": "completed", "finished_at": time.time()},
            )
        except (InterruptedError, asyncio.CancelledError):
            write(
                root / (identity + ".json"),
                {**progress.value, "status": "cancelled", "finished_at": time.time()},
            )
        except Exception as exc:
            write(
                root / (identity + ".json"),
                {
                    **progress.value,
                    "status": "failed",
                    "error": str(exc)[:500],
                    "finished_at": time.time(),
                },
            )
        finally:
            global_lock.close()
            lock.close()

    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return value


def cancel(kind, scope=""):
    identity = key(kind, scope)
    root = directory()
    value = status(kind, scope)
    if value["status"] in {"queued", "running", "cancelling"}:
        (root / (identity + ".cancel")).touch()
    return value


def invalidate(kind, scope=""):
    root = directory()
    identity = key(kind, scope)
    with (root / (identity + ".lock")).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        (root / (identity + ".json")).unlink(missing_ok=True)
        (root / (identity + ".result.json")).unlink(missing_ok=True)


async def thread_work(function, *args, **kwargs):
    """Keep the single-flight lock until blocking disk work really stops."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise
