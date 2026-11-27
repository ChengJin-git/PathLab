"""Transactional file-deletion outbox, shared by object and Settings deletion.

Intent is saved in the same PostgreSQL transaction as the object deletion. The
ResearchWorker retries failed/interrupted work; paths survive their owner's row.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import time
from contextlib import ExitStack, asynccontextmanager
from uuid import uuid4

from sqlalchemy import select, text
from backend.common.config import Config
from backend.database.database import safe_session
from backend.database.models import StorageTask, utc_now
from .inventory import Inventory, measure
from .references import collect, add_result_catalog, add_runtime
from backend.common import file_lock

log = logging.getLogger(__name__)
INTERNAL_TYPES = (
    "chat_delete",
    "file_cleanup",
    "storage_scan",
    "storage_cleanup",
)


@asynccontextmanager
async def deletion_window(items, root, checkpoint=None):
    """Short mutation barrier, after the expensive scan and before each batch.

    SHARE locks allow normal reads, but close the check/delete race with new
    experiments, analyses and dataset registrations. Batches are bounded; a busy
    writer causes retry instead of holding up the request path.
    """
    from backend.database import models as m
    from .references import References

    async with safe_session() as db:
        postgres = db.bind.dialect.name == "postgresql"
        if postgres:
            await db.execute(text("SET LOCAL lock_timeout='1000ms'"))
            await db.execute(
                text(
                    "LOCK TABLE training_tasks,training_task_wsi,ai_tasks,ai_results,wsi_slides,"
                    "auto_research_sessions,auto_research_experiments,auto_research_jobs,result_analyses,"
                    "result_sources,analysis_runs,workbench_files,trained_models,chat_messages,"
                    "manuscripts,result_conversations,result_recipes,workspaces,datasets,feature_artifacts IN SHARE MODE"
                )
            )
        next_checkpoint = (
            await db.scalar(
                text("SELECT txid_snapshot_xmin(txid_current_snapshot()) % 4294967296")
            )
            if postgres
            else None
        )
        if (
            next_checkpoint is not None
            and checkpoint is not None
            and next_checkpoint < checkpoint
        ):
            checkpoint = None
        refs = References()
        identities = {item["owner"] for item in items}
        for model in (
            m.TrainingTask,
            m.AITask,
            m.AutoResearchSession,
            m.AutoResearchExperiment,
            m.ResearchJob,
            m.ResultAnalysis,
            m.ResultSource,
            m.AnalysisRun,
            m.WorkbenchFile,
            m.TrainedModel,
            m.ChatMessage,
            m.Manuscript,
            m.ResultConversation,
            m.ResultRecipe,
            m.Workspace,
            m.Dataset,
        ):
            statement = select(model.__table__)
            if postgres and checkpoint is not None:
                statement = statement.where(
                    text("xmin::text::bigint >= :checkpoint")
                ).params(checkpoint=checkpoint)
            stream = await db.stream(statement)
            async for row in stream.mappings():
                refs.add(
                    {
                        key: value
                        for key, value in row.items()
                        if key not in {"id", "user_id", "dataset_id", "wsi_id"}
                    },
                    root,
                )
                identity_column = {
                    m.TrainingTask: "task_id",
                    m.AITask: "task_id",
                    m.AutoResearchSession: "session_id",
                    m.ResearchJob: "job_id",
                    m.ResultAnalysis: "analysis_id",
                    m.AnalysisRun: "analysis_id",
                    m.TrainedModel: "model_id",
                    m.WorkbenchFile: "file_id",
                }.get(model)
                if identity_column and row.get(identity_column):
                    refs.used_ids.add(str(row[identity_column]))
                if model in (
                    m.TrainingTask,
                    m.AITask,
                    m.ResearchJob,
                    m.ResultAnalysis,
                ) and row.get("status") in {
                    "pending",
                    "queued",
                    "running",
                    "patching",
                    "extracting",
                    "training",
                    "resuming",
                    "cancelling",
                    "stopping",
                }:
                    refs.active.add("writer")
                if (
                    model is m.AutoResearchSession
                    and row["status"] in {"running", "queued", "stopping"}
                ):
                    refs.active.add("research")
        if refs.active:
            raise RuntimeError("Waiting for active tasks before deleting files")
        for model, column in (
            (m.TrainingTaskWSI, m.TrainingTaskWSI.wsi_id),
            (m.AIResult, m.AIResult.wsi_id),
        ):
            refs.used_ids.update(
                (
                    await db.scalars(
                        select(column).where(column.in_(identities)).distinct()
                    )
                ).all()
            )
        images = (
            await db.execute(
                select(
                    m.WSISlide.wsi_id, m.WSISlide.wsi_path, m.WSISlide.associated_files
                ).where(m.WSISlide.wsi_id.in_(identities))
            )
        ).all()
        refs.image_ids.update(identity for identity, _, _ in images)
        for wsi_id, path, associated in images:
            source = References()
            source.add(path, root)
            refs.paths.update(source.paths)
            refs.add(associated, root)
        if postgres:
            statement = select(
                m.WSISlide.wsi_id, m.WSISlide.wsi_path, m.WSISlide.associated_files
            )
            if checkpoint is not None:
                statement = statement.where(
                    text("xmin::text::bigint >= :checkpoint")
                ).params(checkpoint=checkpoint)
            stream = await db.stream(statement.execution_options(yield_per=512))
            async for wsi_id, path, associated in stream:
                refs.image_ids.add(wsi_id)
                source = References()
                source.add(path, root)
                refs.paths.update(source.paths)
                refs.add(associated, root)
        yield refs, db, next_checkpoint


async def enqueue(
    db,
    user_id,
    *,
    paths=(),
    task_ids=(),
    image_ids=(),
    task_type="file_cleanup",
    selection=None,
):
    if task_type == "file_cleanup":
        # Coalesce only an unclaimed row. The transactional row lock prevents the
        # worker from claiming a manifest while a bulk delete appends to it.
        pending = await db.scalar(
            select(StorageTask)
            .where(
                StorageTask.task_type == task_type,
                StorageTask.status == "pending",
                StorageTask.user_id == str(user_id),
            )
            .order_by(StorageTask.created_at)
            .limit(1)
            .with_for_update()
        )
        if pending and (pending.params or {}).get("root") == str(
            Config.get_uploads_dir().absolute()
        ):
            params = pending.params
            if len(params.get("image_ids", [])) + len(image_ids) <= 10000:
                pending.params = {
                    **params,
                    "paths": list(set(params.get("paths", [])) | set(paths)),
                    "task_ids": list(set(params.get("task_ids", [])) | set(task_ids)),
                    "image_ids": [*params.get("image_ids", []), *image_ids],
                }
                await db.flush()
                return pending
    task = StorageTask(
        task_id="cleanup_" + uuid4().hex,
        user_id=str(user_id),
        task_type=task_type,
        status="pending",
        params={
            "root": str(Config.get_uploads_dir().absolute()),
            "paths": list(paths),
            "task_ids": list(task_ids),
            "image_ids": list(image_ids),
            **(selection or {}),
        },
    )
    db.add(task)
    await db.flush()
    return task


def owned_path(root, path):
    root = Path(os.path.abspath(root))
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    p = Path(os.path.abspath(p))
    if not p.is_relative_to(root) or p == root or len(p.relative_to(root).parts) < 2:
        raise ValueError("Invalid cleanup path")
    if not p.parent.resolve().is_relative_to(root.resolve()):
        raise ValueError("Cleanup ancestor escapes storage")
    return p


async def references(root, progress=lambda *a, **k: None):
    async with safe_session() as db:
        refs = await collect(db, root, progress)
    await asyncio.to_thread(add_result_catalog, refs, root)
    await add_runtime(refs, root)
    return refs


def remove_item(inventory, item):
    with ExitStack() as stack:
        parts = Path(item["path"]).parts
        if parts[0] == "features" and len(parts) == 4:
            lock = (
                inventory.root
                / "features/.locks"
                / parts[1]
                / parts[2]
                / (item["owner"] + ".lock")
            )
        elif parts[0] == "coordinates" and len(parts) == 3:
            lock = (
                inventory.root
                / "coordinates/.locks"
                / parts[1]
                / (item["owner"] + ".lock")
            )
        else:
            lock = None
        if lock:
            lock.parent.mkdir(parents=True, exist_ok=True)
            handle = stack.enter_context(lock.open("a+b"))
            try:
                file_lock.flock(handle.fileno(), file_lock.LOCK_EX | file_lock.LOCK_NB)
            except BlockingIOError:
                return None
        return _remove_item(inventory, item)


def _remove_item(inventory, item):
    root = inventory.root
    p = owned_path(root, item["path"])
    if not os.path.lexists(p):
        return 0
    if measure(p)["fingerprint"] != item["fingerprint"]:
        return None
    # Keep result bundle/staging/catalog deletion under the result store's lock.
    if item["category"] == "results" and item["path"].startswith("ai_results_bundles/"):
        from backend.ai.result_store import AIResultStore

        store = AIResultStore(root)
        with store._task_lock(item["owner"]):
            if measure(p)["fingerprint"] != item["fingerprint"]:
                return None
            if p.is_symlink() or p.is_file():
                p.unlink()
            else:
                shutil.rmtree(p)
            if p.name.endswith(".zarr.zip"):
                store.catalog.remove_task(item["owner"])
    elif p.is_symlink() or p.is_file():
        p.unlink()
    else:
        shutil.rmtree(p)
    return item["allocated"]


def stage_directory(inventory, item, task_id):
    """Atomically detach a validated directory while reference mutations are locked.

    Recursive unlink happens after releasing PostgreSQL's mutation barrier. A
    private receipt is written first so a process crash can resume the purge.
    """
    path = owned_path(inventory.root, item["path"])
    if (
        path.is_symlink()
        or not path.is_dir()
        or item["path"].startswith("ai_results_bundles/")
    ):
        return remove_item(inventory, item), None
    if measure(path)["fingerprint"] != item["fingerprint"]:
        return None, None
    parent = inventory.directory / "trash" / task_id
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / item["id"]
    receipt = parent / (item["id"] + ".json")
    with receipt.open("w") as stream:
        json.dump({"allocated": item["allocated"], "source": item["path"]}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(path, destination)
    return item["allocated"], destination


def purge_directory(path):
    if path.exists():
        shutil.rmtree(path)
    path.with_name(path.name + ".json").unlink(missing_ok=True)


def task_paths(task_id, models=()):
    return [
        f"training/{task_id}",
        f"logs/training/{task_id}",
        f"logs/analysis/{task_id}",
        f"ai_results_bundles/{task_id}.zarr.zip",
        f"ai_results_bundles/.staging/{task_id}.zarr",
        *(f"models/{identity}" for identity in models),
    ]


def image_paths(root, wsi_id, wsi_path=None):
    """Direct paths plus bounded extractor/parameter directories; no per-slide tree walks."""
    paths = [f"masks/{wsi_id}_mask.png", f"metadata/{wsi_id}.json"]
    if wsi_path:
        p = Path(wsi_path).absolute()
        if p.is_relative_to(root) and p != root:
            paths.append(str(p.relative_to(root)))
            if p.suffix.lower() == ".mrxs":
                paths.append(str(p.with_suffix("").relative_to(root)))
            if p.suffix.lower() == ".tmap":
                paths.extend(
                    str(p.with_suffix(f".DT{i}").relative_to(root)) for i in range(10)
                )
    coordinates = root / "coordinates"
    if coordinates.is_dir():
        paths.extend(
            str(p.relative_to(root) / f"{wsi_id}_coords.h5")
            for p in coordinates.iterdir()
            if p.name != ".locks" and not p.is_symlink() and p.is_dir()
        )
    features = root / "features"
    if features.is_dir():
        for extractor in features.iterdir():
            if (
                extractor.name == ".locks"
                or extractor.is_symlink()
                or not extractor.is_dir()
            ):
                continue
            for params in extractor.iterdir():
                if not params.is_symlink() and params.is_dir():
                    paths.extend(
                        str(params.relative_to(root) / f"{wsi_id}{suffix}")
                        for suffix in (".pt", ".feature.json")
                    )
    return paths


class StorageQueue:
    """One deployment supervisor; persistent admission and filesystem writer lock."""

    def __init__(self):
        self.task = None
        self.stopping = threading.Event()

    async def tick(self):
        if self.task and not self.task.done():
            return
        async with safe_session() as db:
            rows = (
                await db.scalars(
                    select(StorageTask)
                    .where(
                        StorageTask.task_type.in_(INTERNAL_TYPES[1:]),
                        StorageTask.status.in_(["pending", "processing", "failed"]),
                        (StorageTask.params["retry_after"].as_float().is_(None))
                        | (StorageTask.params["retry_after"].as_float() <= time.time()),
                    )
                    .order_by(StorageTask.created_at)
                    .limit(20)
                )
            ).all()
        for row in rows:
            if (row.params or {}).get("retry_after", 0) <= time.time():
                self.task = asyncio.create_task(self.run(row.task_id))
                break

    async def shutdown(self):
        self.stopping.set()
        if self.task:
            # Threaded deletions must finish before releasing the deployment lock.
            await self.task

    async def run(self, task_id):
        loop = asyncio.get_running_loop()
        updates = asyncio.Queue(maxsize=1)
        cancelled = threading.Event()
        last_progress = 0.0

        def progress(processed=0, total=None, stage="", **kwargs):
            nonlocal last_progress
            if cancelled.is_set() or self.stopping.is_set():
                raise InterruptedError("Storage operation cancelled")
            now = time.monotonic()
            if now - last_progress < 0.5 and not kwargs.get("force"):
                return
            last_progress = now
            value = (processed, total, stage)

            def post():
                if updates.full():
                    updates.get_nowait()
                updates.put_nowait(value)

            loop.call_soon_threadsafe(post)

        async def report():
            while True:
                processed, total, stage = await updates.get()
                async with safe_session() as db:
                    row = await db.scalar(
                        select(StorageTask).where(StorageTask.task_id == task_id)
                    )
                    if row.status == "cancelled":
                        cancelled.set()
                        continue
                    row.processed_items = processed
                    row.total_items = total or 0
                    row.results = {"stage": stage}
                    await db.commit()
                await asyncio.sleep(0.5)

        reporter = asyncio.create_task(report())
        try:
            async with safe_session() as db:
                task = await db.scalar(
                    select(StorageTask)
                    .where(StorageTask.task_id == task_id)
                    .with_for_update()
                )
                params, kind = dict(task.params), task.task_type
                if task.status in {"cancelled", "completed"}:
                    return
                task.status, task.started_at, task.error_message = (
                    "processing",
                    utc_now(),
                    None,
                )
                await db.commit()
            root = Path(params["root"])
            if params.get("task_ids"):
                from backend.common.task_dispatch import publish_task_cancellation

                for identity in params["task_ids"]:
                    await publish_task_cancellation(identity)
            inventory = await asyncio.to_thread(Inventory, root)
            with inventory.lock():
                refs = await references(root, progress)
                if kind != "storage_scan" and refs.active:
                    raise RuntimeError(
                        "Waiting for active tasks to finish before storage cleanup"
                    )
                if kind == "storage_scan":
                    result = await asyncio.to_thread(inventory.scan, refs, progress)
                else:
                    result = await self.clean(
                        inventory, task_id, params, refs, progress, kind
                    )
            reporter.cancel()
            await asyncio.gather(reporter, return_exceptions=True)
            async with safe_session() as db:
                row = await db.scalar(
                    select(StorageTask).where(StorageTask.task_id == task_id)
                )
                if row.status != "cancelled":
                    row.status, row.progress, row.completed_at = (
                        "completed",
                        100,
                        utc_now(),
                    )
                    row.results = result
                    row.success_count = result.get("deleted", 0)
                    row.skipped_count = result.get("skipped", 0)
                    await db.commit()
        except ValueError as exc:
            async with safe_session() as db:
                row = await db.scalar(
                    select(StorageTask).where(StorageTask.task_id == task_id)
                )
                if row:
                    row.status = "cancelled"
                    row.error_message = str(exc)[:1000]
                    await db.commit()
        except Exception as exc:
            interrupted = isinstance(exc, InterruptedError) or (
                isinstance(exc, sqlite3.OperationalError)
                and exc.sqlite_errorcode == sqlite3.SQLITE_INTERRUPT
            )
            expected_stop = interrupted and (
                self.stopping.is_set() or cancelled.is_set()
            )
            if not expected_stop:
                log.exception("Storage operation %s will retry", task_id)
            async with safe_session() as db:
                row = await db.scalar(
                    select(StorageTask).where(StorageTask.task_id == task_id)
                )
                if row and row.status != "cancelled":
                    if expected_stop:
                        row.status, row.error_message = "pending", None
                        row.params = {**row.params, "retry_after": 0}
                        log.info(
                            "Storage operation %s paused for shutdown; it will resume",
                            task_id,
                        )
                    else:
                        row.status, row.error_message = "failed", str(exc)[:1000]
                        row.params = {
                            **row.params,
                            "retry_after": max(
                                (row.params or {}).get("retry_after", 0),
                                time.time() + 60,
                            ),
                        }
                    await db.commit()
        finally:
            reporter.cancel()
            await asyncio.gather(reporter, return_exceptions=True)

    async def clean(self, inventory, task_id, params, refs, progress, kind):
        # Selection is copied into a durable operation manifest before the refresh.
        # Retrying preserves that exact set, including per-item completion receipts.
        with inventory.connect() as db:
            existing = db.execute(
                "SELECT 1 FROM operations WHERE task_id=? LIMIT 1", (task_id,)
            ).fetchone()
            if not existing:
                if kind == "storage_cleanup":
                    generation = params["generation"]
                    if generation != inventory.summary()["generation"]:
                        raise ValueError("Storage scan changed; refresh the selection")
                    query = "SELECT id,path,allocated,fingerprint FROM items WHERE generation=? AND state IN ('orphaned','cached')"
                    args = [generation]
                    if params.get("ids"):
                        query += (
                            " AND id IN (" + ",".join("?" for _ in params["ids"]) + ")"
                        )
                        args.extend(params["ids"])
                    if params.get("excluded_ids"):
                        query += (
                            " AND id NOT IN ("
                            + ",".join("?" for _ in params["excluded_ids"])
                            + ")"
                        )
                        args.extend(params["excluded_ids"])
                    if params.get("category"):
                        query += " AND category=?"
                        args.append(params["category"])
                    if params.get("state"):
                        query += " AND state=?"
                        args.append(params["state"])
                    rows = db.execute(query, args)
                    db.executemany(
                        "INSERT INTO operations VALUES(?,?,?,?,?,NULL,?)",
                        (
                            (
                                task_id,
                                row["id"],
                                row["path"],
                                row["allocated"],
                                "pending",
                                row["fingerprint"],
                            )
                            for row in rows
                        ),
                    )
                else:
                    paths = set(params.get("paths", []))
                    for image in params.get("image_ids", []):
                        paths.update(
                            image_paths(inventory.root, image["id"], image.get("path"))
                        )
                    for path in paths:
                        relative = str(
                            owned_path(inventory.root, path).relative_to(inventory.root)
                        )
                        key = hashlib.sha256(relative.encode()).hexdigest()[:32]
                        db.execute(
                            "INSERT OR IGNORE INTO operations VALUES(?,?,?,?,?,NULL,NULL)",
                            (task_id, key, relative, 0, "pending"),
                        )
        # Incremental manifest parsing + a fresh no-follow inventory rechecks every
        # inbound reference, including links created since the user's last scan.
        with inventory.connect() as db:
            deleted_paths = (
                [
                    row[0]
                    for row in db.execute(
                        "SELECT path FROM operations WHERE task_id=?", (task_id,)
                    )
                ]
                if kind == "file_cleanup"
                else []
            )
        snapshot = await asyncio.to_thread(
            inventory.scan, refs, progress, deleted_paths=deleted_paths
        )
        with inventory.connect() as db:
            total = db.execute(
                "SELECT count(*) FROM operations WHERE task_id=?", (task_id,)
            ).fetchone()[0]
        if total == 0:
            return {"deleted": 0, "skipped": 0, "freed": 0}
        if kind == "file_cleanup":
            with inventory.connect() as db:
                # Previously requested deletions may have been retained by a
                # now-deleted analysis. The last consumer's deletion closes that
                # loop without making administrators resubmit the old owner.
                db.execute(
                    """INSERT OR IGNORE INTO operations
                    SELECT ?,i.id,i.path,i.allocated,'pending',NULL,i.fingerprint
                    FROM operations o JOIN items i ON i.generation=? AND i.path=o.path
                    WHERE o.status='retained' AND i.state IN ('orphaned','cached')""",
                    (task_id, snapshot["generation"]),
                )
                parents = db.execute(
                    "SELECT path FROM operations WHERE task_id=?", (task_id,)
                ).fetchall()
                for parent in parents:
                    prefix = parent["path"].rstrip("/") + "/"
                    db.execute(
                        """INSERT OR IGNORE INTO operations
                        SELECT ?,id,path,allocated,'pending',NULL,NULL FROM items
                        WHERE generation=? AND path>=? AND path<?""",
                        (task_id, snapshot["generation"], prefix, prefix + "\uffff"),
                    )
                # A deleted input workspace releases its outgoing cache inputs.
                # Live consumers were resolved by the inventory; only unused
                # feature/patching units may join this object's cleanup manifest.
                db.execute(
                    """INSERT OR IGNORE INTO operations
                    SELECT ?,i.id,i.path,i.allocated,'pending',NULL,NULL FROM operations o
                    JOIN edges e ON e.generation=? AND e.source=o.item_id AND e.kind='path'
                    JOIN items i ON i.generation=e.generation AND i.path=e.target
                    WHERE o.task_id=? AND i.category IN ('features','patching')
                    AND i.state IN ('orphaned','cached')""",
                    (task_id, snapshot["generation"], task_id),
                )
                db.execute(
                    """INSERT OR IGNORE INTO operations
                    SELECT ?,p.id,p.path,p.allocated,'pending',NULL,NULL FROM operations o
                    JOIN items f ON f.generation=? AND f.id=o.item_id AND f.category='features'
                    JOIN items p ON p.generation=f.generation AND p.owner=f.owner AND p.category='patching'
                    WHERE o.task_id=? AND p.state IN ('orphaned','cached')""",
                    (task_id, snapshot["generation"], task_id),
                )
        refs = await references(inventory.root, progress)
        if refs.active:
            raise RuntimeError(
                "Waiting for active tasks to finish before storage cleanup"
            )
        snapshot = await asyncio.to_thread(
            inventory.revalidate, refs, progress, deleted_paths=deleted_paths
        )
        deleted = skipped = freed = 0
        cursor = ""
        checkpoint = refs.checkpoint
        deferred = False
        while True:
            async with safe_session() as db:
                row = await db.scalar(
                    select(StorageTask).where(StorageTask.task_id == task_id)
                )
                if row.status == "cancelled":
                    break
            if self.stopping.is_set():
                raise InterruptedError("Storage worker stopping")
            with inventory.connect() as db:
                batch = db.execute(
                    "SELECT * FROM operations WHERE task_id=? AND item_id>? ORDER BY item_id LIMIT 128",
                    (task_id, cursor),
                ).fetchall()
            if not batch:
                break
            from backend.common.redis_client import get_redis

            runtime = await get_redis().get("pathlab:task_worker:runtime_status")
            if not runtime or any(
                json.loads(runtime).get(key, 0)
                for key in (
                    "running_count",
                    "pending_count",
                    "patching_count",
                    "descriptor_processing_count",
                    "descriptor_pending_count",
                )
            ):
                raise RuntimeError("Waiting for idle TaskWorker")
            receipts = []
            forgotten = []
            purges = []
            with inventory.connect() as db:
                item_map = {
                    row["id"]: dict(row)
                    for row in db.execute(
                        "SELECT * FROM items WHERE generation=? AND id IN ("
                        + ",".join("?" for _ in batch)
                        + ")",
                        [snapshot["generation"], *(op["item_id"] for op in batch)],
                    )
                }
            from .inventory import IDENTITY

            async with deletion_window(
                list(item_map.values()), inventory.root, checkpoint
            ) as (current, guard_db, next_checkpoint):
                if current.paths - refs.paths or current.used_ids - (
                    refs.used_ids | refs.owners | refs.image_ids
                ):
                    # A new root can pin another workspace's inputs transitively.
                    # Rebuild reachability rather than checking direct paths only.
                    raise RuntimeError(
                        "References changed; rechecking storage before cleanup"
                    )
                for operation in batch:
                    cursor = operation["item_id"]
                    if operation["status"] == "deleted":
                        deleted += 1
                        freed += operation["allocated"]
                        continue
                    staged = inventory.directory / "trash" / task_id / cursor
                    receipt = staged.with_name(cursor + ".json")
                    if (
                        receipt.exists()
                        and not staged.exists()
                        and not os.path.lexists(inventory.root / operation["path"])
                    ):
                        saved = json.loads(receipt.read_text())
                        receipt.unlink()
                        deleted += 1
                        freed += saved["allocated"]
                        receipts.append(
                            ("deleted", saved["allocated"], task_id, cursor)
                        )
                        continue
                    if staged.exists():
                        saved = json.loads(
                            staged.with_name(cursor + ".json").read_text()
                        )
                        deleted += 1
                        freed += saved["allocated"]
                        purges.append(staged)
                        receipts.append(
                            ("deleted", saved["allocated"], task_id, cursor)
                        )
                        continue
                    item = item_map.get(cursor)
                    if item is None and not os.path.lexists(
                        inventory.root / operation["path"]
                    ):
                        if operation["path"].startswith(
                            "ai_results_bundles/"
                        ) and operation["path"].endswith(".zarr.zip"):
                            from backend.ai.result_store import AIResultStore

                            owner = Path(operation["path"]).name.removesuffix(
                                ".zarr.zip"
                            )
                            await asyncio.to_thread(
                                AIResultStore(inventory.root).catalog.remove_task, owner
                            )
                        if operation["path"].startswith(("features/", "coordinates/")):
                            forgotten.append(str(inventory.root / operation["path"]))
                        receipts.append(("deleted", 0, task_id, cursor))
                        deleted += 1
                        continue
                    referenced = item and (
                        item["owner"] in current.used_ids
                        or bool(set(IDENTITY.findall(item["owner"])) & current.used_ids)
                        or any(
                            path == item["path"]
                            or path.startswith(item["path"] + "/")
                            or item["path"].startswith(path + "/")
                            for path in current.paths
                        )
                        or (
                            item["category"] in {"images", "metadata"}
                            and item["owner"] in current.image_ids
                        )
                    )
                    if item and kind == "file_cleanup" and item["state"] == "recent":
                        deferred = True
                        continue
                    if (
                        not item
                        or referenced
                        or item["state"] not in {"orphaned", "cached"}
                        or (
                            operation["fingerprint"]
                            and item["fingerprint"] != operation["fingerprint"]
                        )
                    ):
                        skipped += 1
                        status, size = (
                            (
                                "retained"
                                if kind == "file_cleanup"
                                and item
                                and (referenced or item["state"] == "referenced")
                                else "skipped"
                            ),
                            0,
                        )
                    else:
                        size, staged = await asyncio.to_thread(
                            stage_directory, inventory, dict(item), task_id
                        )
                        if staged:
                            purges.append(staged)
                        status = "deleted" if size is not None else "skipped"
                        if size is not None:
                            deleted += 1
                            freed += size
                            if item["category"] in {"features", "patching"}:
                                forgotten.append(str(inventory.root / item["path"]))
                        else:
                            skipped += 1
                            if kind == "file_cleanup":
                                deferred = True
                    receipts.append((status, size or 0, task_id, cursor))
                if forgotten:
                    await self.forget_cache(forgotten, db=guard_db)
                checkpoint = next_checkpoint
            for staged in purges:
                await asyncio.to_thread(purge_directory, staged)
            with inventory.connect() as db:
                for status, size, _, key in receipts:
                    db.execute(
                        "UPDATE operations SET status=?,allocated=? WHERE task_id=? AND item_id=?",
                        (status, size or 0, task_id, key),
                    )
                    if status == "deleted":
                        db.execute(
                            "DELETE FROM items WHERE generation=? AND id=?",
                            (snapshot["generation"], key),
                        )
                        db.execute(
                            "DELETE FROM edges WHERE generation=? AND source=?",
                            (snapshot["generation"], key),
                        )
                        db.execute(
                            "DELETE FROM item_ids WHERE generation=? AND item_id=?",
                            (snapshot["generation"], key),
                        )
                        db.execute(
                            "DELETE FROM reachable WHERE generation=? AND item_id=?",
                            (snapshot["generation"], key),
                        )
                        path = next(op["path"] for op in batch if op["item_id"] == key)
                        prefix = path.rstrip("/") + "/"
                        db.execute(
                            "DELETE FROM manifests WHERE path=? OR (path>=? AND path<?)",
                            (path, prefix, prefix + "\uffff"),
                        )
                        db.execute(
                            "DELETE FROM operations WHERE path=? AND status='retained'",
                            (path,),
                        )
            progress(deleted + skipped, None, "cleanup")
        with inventory.connect() as db:
            inventory._publish(db, snapshot["generation"], time.time())
        trash = inventory.directory / "trash" / task_id
        if trash.exists() and not any(trash.iterdir()):
            trash.rmdir()
        if deferred:
            async with safe_session() as db:
                row = await db.scalar(
                    select(StorageTask).where(StorageTask.task_id == task_id)
                )
                row.params = {**row.params, "retry_after": time.time() + 3600}
                await db.commit()
            raise RuntimeError("Waiting for recently written files to become stable")
        return {"deleted": deleted, "skipped": skipped, "freed": freed}

    async def forget_cache(self, paths, *, db=None):
        from sqlalchemy import delete, or_, update, exists
        from backend.database.models import FeatureArtifact, WSISlide

        async def forget(db):
            removed = await db.scalars(
                delete(FeatureArtifact)
                .where(
                    or_(
                        FeatureArtifact.feature_path.in_(paths),
                        FeatureArtifact.coordinates_path.in_(paths),
                    )
                )
                .returning(FeatureArtifact.wsi_id)
            )
            ids = set(removed.all())
            if ids:
                await db.execute(
                    update(WSISlide)
                    .where(
                        WSISlide.wsi_id.in_(ids),
                        ~exists(
                            select(FeatureArtifact.artifact_id).where(
                                FeatureArtifact.wsi_id == WSISlide.wsi_id
                            )
                        ),
                    )
                    .values(feature_extracted=False)
                )
            await db.commit()

        if db is not None:
            await forget(db)
        else:
            async with safe_session() as session:
                await forget(session)
