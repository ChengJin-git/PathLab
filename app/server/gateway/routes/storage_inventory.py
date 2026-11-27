"""Small, indexed storage responses and durable admin operations."""

import asyncio
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, text
from backend.auth.dependencies import require_admin
from backend.common.config import Config
from backend.database.database import get_db
from backend.database.models import StorageTask
from backend.storage.deletion import enqueue
from backend.storage.inventory import CATEGORIES, Inventory

router = APIRouter()


def operation(row):
    return (
        None
        if row is None
        else {
            "id": row.task_id,
            "kind": row.task_type,
            "status": row.status,
            "processed": row.processed_items,
            "total": row.total_items,
            "result": row.results,
            "error": row.error_message,
        }
    )


async def latest(db):
    return await db.scalar(
        select(StorageTask)
        .where(
            StorageTask.task_type.in_(["storage_scan", "storage_cleanup"]),
            StorageTask.params["root"].as_string()
            == str(Config.get_uploads_dir().absolute()),
        )
        .order_by(StorageTask.created_at.desc())
        .limit(1)
    )


@router.get("/inventory")
async def overview(user=Depends(require_admin), db=Depends(get_db)):
    summary = await asyncio.to_thread(
        lambda: Inventory(Config.get_uploads_dir()).summary()
    )
    return {**summary, "operation": operation(await latest(db))}


@router.get("/inventory/items")
async def items(
    category: str | None = None,
    state: Literal["orphaned", "cached", "referenced", "recent", "managed"]
    | None = None,
    cursor: str | None = Query(None, max_length=120),
    limit: int = Query(50, ge=1, le=100),
    user=Depends(require_admin),
):
    if category and category not in CATEGORIES:
        raise HTTPException(422, "Invalid storage category")
    try:
        return await asyncio.to_thread(
            lambda: Inventory(Config.get_uploads_dir()).page(
                category, state, cursor, limit
            )
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class Selection(BaseModel):
    generation: str = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]+$")
    scope: Literal["selected", "all"]
    ids: list[str] = Field(default_factory=list, max_length=1000)
    excluded_ids: list[str] = Field(default_factory=list, max_length=1000)
    category: str | None = None
    state: Literal["orphaned", "cached"] = "orphaned"

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope == "selected" and (not self.ids or self.excluded_ids):
            raise ValueError("Select files before cleaning up")
        if self.scope == "all" and self.ids:
            raise ValueError("All-filtered selection cannot include explicit IDs")
        return self


async def admit(db, user, kind, selection=None):
    # PostgreSQL transaction lock closes the double-click/cross-Gateway race.
    await db.execute(text("SELECT pg_advisory_xact_lock(72419834)"))
    current = await latest(db)
    if current and current.status in {"pending", "processing", "failed"}:
        await db.commit()
        return operation(current)
    task = await enqueue(db, user.id, task_type=kind, selection=selection)
    await db.commit()
    return operation(task)


@router.post("/inventory/scan", status_code=202)
async def scan(user=Depends(require_admin), db=Depends(get_db)):
    return await admit(db, user, "storage_scan")


@router.post("/inventory/cleanup", status_code=202)
async def cleanup(body: Selection, user=Depends(require_admin), db=Depends(get_db)):
    if body.category and body.category not in CATEGORIES:
        raise HTTPException(422, "Invalid storage category")
    summary = await asyncio.to_thread(
        lambda: Inventory(Config.get_uploads_dir()).summary()
    )
    if body.generation != summary["generation"]:
        raise HTTPException(409, "Storage inventory changed; refresh the selection")
    # Scope is validated at admission; the durable job stores the resulting
    # predicate (explicit IDs or all-filtered with exclusions), not UI state.
    return await admit(db, user, "storage_cleanup", body.model_dump(exclude={"scope"}))


@router.delete("/inventory/operations/{task_id}")
async def cancel(task_id: str, user=Depends(require_admin), db=Depends(get_db)):
    row = await db.scalar(
        select(StorageTask)
        .where(
            StorageTask.task_id == task_id,
            StorageTask.task_type.in_(["storage_scan", "storage_cleanup"]),
        )
        .with_for_update()
    )
    if not row:
        raise HTTPException(404, "Storage operation not found")
    if row.status in {"pending", "processing", "failed"}:
        row.status = "cancelled"
        await db.commit()
    return operation(row)
