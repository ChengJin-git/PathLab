"""Persisted research scopes and the public Chat capability catalog."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import func, select

from backend.auth import User, current_active_user
from backend.database import get_db
from backend.database.models import Dataset, DatasetStats, Workspace
from backend.common.config import Config
from backend.services.workspaces import (
    CONNECTORS,
    SKILLS,
    dataset_capabilities,
    resolve_scope,
    visible_dataset_ids,
)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


class WorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    dataset_ids: list[str] = Field(default_factory=list, max_length=200)
    root_paths: list[str] = Field(default_factory=list, max_length=10)
    enabled_skills: list[str] = Field(default_factory=lambda: list(SKILLS))
    enabled_connectors: list[str] = Field(default_factory=lambda: list(CONNECTORS))
    execution_mode: Literal["standard", "read_only"] = "standard"


def serialize(workspace):
    return {
        key: getattr(workspace, key)
        for key in (
            "workspace_id",
            "user_id",
            "name",
            "dataset_ids",
            "root_paths",
            "enabled_skills",
            "enabled_connectors",
            "execution_mode",
            "version",
        )
    }


@router.get("/capabilities")
async def capabilities(user: User = Depends(current_active_user)):
    settings = Config.get_global_settings()
    return {
        "role": user.role,
        "can_use_gpu": user.can_use_gpu(),
        "can_scan_server": user.is_admin(),
        "can_manage_users": user.is_admin(),
        "skills": [{"id": key, **value} for key, value in SKILLS.items()],
        "connectors": [
            {
                "id": key,
                **value,
                "available": (
                    bool(settings.get("exa_api_key")) if key == "web_search" else True
                ),
            }
            for key, value in CONNECTORS.items()
        ],
    }


@router.get("/datasets")
async def selectable_datasets(
    search: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    query = (
        select(
            Dataset.dataset_id,
            Dataset.name,
            Dataset.data_type,
            DatasetStats.file_count,
        )
        .outerjoin(DatasetStats, DatasetStats.dataset_id == Dataset.dataset_id)
        .where(Dataset.dataset_id.in_(visible_dataset_ids(user)))
    )
    if search.strip():
        query = query.where(Dataset.name.icontains(search.strip(), autoescape=True))
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0
    rows = (
        await db.execute(
            query.order_by(Dataset.name, Dataset.dataset_id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    from backend.services.dataset_catalog import task_summaries
    tasks = await task_summaries(db, [row.dataset_id for row in rows])
    return {"items": [{**dict(row._mapping), "task_types": [task['task_type'] for task in tasks.get(row.dataset_id, [])]} for row in rows], "total": total, "page": page}


@router.get("/datasets/{dataset_id}/capabilities")
async def get_dataset_capabilities(
    dataset_id: str, user: User = Depends(current_active_user), db=Depends(get_db)
):
    dataset = (
        await db.execute(select(Dataset).where(Dataset.dataset_id == dataset_id))
    ).scalar_one_or_none()
    if dataset is None:
        raise HTTPException(404, "Dataset not found")
    result = await dataset_capabilities(db, user, dataset)
    if not result["read"]:
        raise HTTPException(403, "Dataset access denied")
    return result


@router.get("")
async def list_workspaces(
    user: User = Depends(current_active_user), db=Depends(get_db)
):
    rows = (
        (
            await db.execute(
                select(Workspace)
                .where(Workspace.user_id == str(user.id), Workspace.archived.is_(False))
                .order_by(Workspace.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {"items": [serialize(row) for row in rows]}


async def validate_request(req, db, user):
    name = req.name.strip()
    if not name:
        raise HTTPException(422, "Workspace name cannot be blank")
    if (
        set(req.enabled_skills) - SKILLS.keys()
        or set(req.enabled_connectors) - CONNECTORS.keys()
    ):
        raise HTTPException(422, "Unknown skill or connector")
    selected = list(dict.fromkeys(req.dataset_ids))
    if selected:
        allowed = set(
            (
                await db.execute(
                    visible_dataset_ids(user).where(Dataset.dataset_id.in_(selected))
                )
            )
            .scalars()
            .all()
        )
        if set(selected) - allowed:
            raise HTTPException(403, "One or more datasets are unavailable")
    if req.root_paths and not user.is_admin():
        raise HTTPException(
            403, "Only administrators can configure server scan directories"
        )
    roots = [
        str(Path(root).expanduser().resolve())
        for root in req.root_paths
        if root.strip()
    ]
    return {
        **req.model_dump(),
        "name": name,
        "dataset_ids": selected,
        "root_paths": list(dict.fromkeys(roots)),
        "enabled_skills": list(dict.fromkeys(req.enabled_skills)),
        "enabled_connectors": list(dict.fromkeys(req.enabled_connectors)),
    }


@router.post("")
async def create_workspace(
    req: WorkspaceRequest, user: User = Depends(current_active_user), db=Depends(get_db)
):
    workspace = Workspace(
        workspace_id=f"ws_{uuid.uuid4().hex}",
        user_id=str(user.id),
        **await validate_request(req, db, user),
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return serialize(workspace)


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str, user: User = Depends(current_active_user), db=Depends(get_db)
):
    await resolve_scope(db, user, workspace_id)
    return serialize(
        (
            await db.execute(
                select(Workspace).where(Workspace.workspace_id == workspace_id)
            )
        ).scalar_one()
    )


@router.put("/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    req: WorkspaceRequest,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
):
    await resolve_scope(db, user, workspace_id)
    values = await validate_request(req, db, user)
    workspace = (
        await db.execute(
            select(Workspace)
            .where(Workspace.workspace_id == workspace_id)
            .with_for_update()
        )
    ).scalar_one()
    for key, value in values.items():
        setattr(workspace, key, value)
    workspace.version += 1
    await db.commit()
    return serialize(workspace)


@router.delete("/{workspace_id}")
async def archive_workspace(
    workspace_id: str, user: User = Depends(current_active_user), db=Depends(get_db)
):
    await resolve_scope(db, user, workspace_id)
    workspace = (
        await db.execute(
            select(Workspace).where(Workspace.workspace_id == workspace_id)
        )
    ).scalar_one()
    workspace.archived = True
    await db.commit()
    return {"archived": True}
