"""Non-blocking storage inspections; all status/result reads are admin-only."""

import asyncio
import os
import queue
import threading
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from backend.auth.dependencies import require_admin
from backend.database.database import safe_session
from backend.database.models import WSISlide, Dataset
from backend.storage import inspection_jobs as jobs
from backend.common.config import Config

router = APIRouter()
Kind = Literal["external-health"]
_health_slots = threading.BoundedSemaphore(8)


def external_filter():
    root = os.path.abspath(str(Config.get_uploads_dir())).rstrip("/")
    return and_(
        WSISlide.wsi_path != root,
        ~WSISlide.wsi_path.startswith(root + "/", autoescape=True),
    )


async def external_summary(db):
    rows = (
        await db.execute(
            select(WSISlide.dataset_id, Dataset.name, func.count())
            .outerjoin(Dataset, Dataset.dataset_id == WSISlide.dataset_id)
            .where(external_filter())
            .group_by(WSISlide.dataset_id, Dataset.name)
        )
    ).all()
    data = [
        {
            "dataset_id": identity,
            "dataset_name": name or "Uncategorized",
            "total_files": count,
        }
        for identity, name, count in rows
    ]
    return {"datasets": data, "total": sum(item["total_files"] for item in data)}


def check_batch(items, progress, processed, total):
    """Bounded daemon workers; NAS timeouts never spawn a thread per file."""
    work = queue.Queue()
    done = queue.Queue()
    for index, item in enumerate(items):
        work.put((index, item))

    def check(item):
        path = Path(item["wsi_path"])
        associated = item["associated_files"] or {}
        kind = associated.get("format_type", path.suffix.lower().lstrip("."))
        if not path.is_file():
            return False, "File not found"
        if (
            kind == "mrxs"
            and not Path(associated.get("data_folder") or path.with_suffix("")).is_dir()
        ):
            return False, "Missing required data folder"
        if kind == "tmap" and any(
            not Path(value).is_file() for value in associated.get("dt_files", [])
        ):
            return False, "Missing associated DT file"
        return True, "Available"

    def worker():
        try:
            while True:
                try:
                    index, item = work.get_nowait()
                except queue.Empty:
                    return
                try:
                    result = check(item)
                except OSError as exc:
                    result = (False, str(exc))
                done.put((index, result))
        finally:
            _health_slots.release()

    for _ in range(min(8, len(items))):
        if not _health_slots.acquire(blocking=False):
            break
        threading.Thread(target=worker, daemon=True).start()
    results = {}
    while len(results) < len(items):
        try:
            index, result = done.get(timeout=5)
        except queue.Empty:
            # Stop dispatching to a stalled mount. Bounded workers may still be in stat().
            while True:
                try:
                    work.get_nowait()
                except queue.Empty:
                    break
            raise TimeoutError(
                "Storage did not respond within 5 seconds; partial results were not marked missing"
            )
        results[index] = result
        progress.update(processed + len(results), total, "external-health")
    available = []
    unavailable = []
    for index, item in enumerate(items):
        ok, reason = results[index]
        entry = {key: value for key, value in item.items() if key != "associated_files"}
        entry.update(status="available" if ok else "unavailable", reason=reason)
        (available if ok else unavailable).append(entry)
    return available, unavailable


async def health(progress, dataset_id):
    condition = external_filter()
    if dataset_id:
        condition = and_(condition, WSISlide.dataset_id == dataset_id)
    async with safe_session() as db:
        total = await db.scalar(
            select(func.count()).select_from(WSISlide).where(condition)
        )
    progress.update(0, total, "external-health", force=True)
    last = 0
    processed = 0
    available = []
    unavailable = []
    while True:
        async with safe_session() as db:
            rows = (
                (
                    await db.execute(
                        select(
                            WSISlide.id,
                            WSISlide.wsi_id,
                            WSISlide.original_filename,
                            WSISlide.wsi_path,
                            WSISlide.dataset_id,
                            Dataset.name.label("dataset_name"),
                            WSISlide.label,
                            WSISlide.associated_files,
                        )
                        .outerjoin(Dataset, Dataset.dataset_id == WSISlide.dataset_id)
                        .where(condition, WSISlide.id > last)
                        .order_by(WSISlide.id)
                        .limit(256)
                    )
                )
                .mappings()
                .all()
            )
        if not rows:
            break
        last = rows[-1]["id"]
        batch = [{k: v for k, v in row.items() if k != "id"} for row in rows]
        ok, bad = await jobs.thread_work(check_batch, batch, progress, processed, total)
        available.extend(ok)
        unavailable.extend(bad)
        processed += len(rows)
        progress.update(processed, total, "external-health", force=True)
    result = {
        "total_external": processed,
        "available_count": len(available),
        "unavailable_count": len(unavailable),
        "available": available,
        "unavailable": unavailable,
    }
    from backend.storage.external_availability import record_many_from_scan

    await jobs.thread_work(record_many_from_scan, result)
    result[
        "available"
    ] = []  # The UI uses counts; avoid serializing thousands of successful rows.
    return result


async def begin(kind, scope=""):
    return await jobs.start(kind, scope, lambda progress: health(progress, scope))


@router.post("/inspections/{kind}")
async def start(
    kind: Kind, dataset_id: str = Query("", max_length=255), user=Depends(require_admin)
):
    return await begin(kind, dataset_id if kind == "external-health" else "")


@router.get("/inspections/{kind}")
async def status(
    kind: Kind,
    dataset_id: str = Query("", max_length=255),
    result: bool = False,
    user=Depends(require_admin),
):
    return await asyncio.to_thread(
        jobs.status,
        kind,
        dataset_id if kind == "external-health" else "",
        result=result,
    )


@router.delete("/inspections/{kind}")
async def cancel(
    kind: Kind, dataset_id: str = Query("", max_length=255), user=Depends(require_admin)
):
    return jobs.cancel(kind, dataset_id if kind == "external-health" else "")
