"""Workspace scopes narrow existing access; all-area is a search scope, not a dump."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select

from backend.database.models import (
    Dataset,
    TrainingTaskWSI,
    WSISlide,
    Workspace,
)

SKILLS = {
    "data": {"name": "数据管理", "name_en": "Data management"},
    "training": {"name": "模型训练", "name_en": "Training"},
    "inference": {"name": "推理验证", "name_en": "Inference"},
    "analysis": {"name": "结果分析", "name_en": "Analysis"},
    "annotation": {"name": "协作标注", "name_en": "Annotation"},
    "literature": {"name": "文献研究", "name_en": "Literature"},
    "tasks": {"name": "任务管理", "name_en": "Task management"},
}
CONNECTORS = {
    "web_search": {"name": "网页搜索 / Exa", "name_en": "Web search / Exa"},
    "articles": {"name": "网页与论文阅读", "name_en": "Article reader"},
}
EXPERT_SKILLS = {
    "training-advisor": ("data", "training", "tasks"),
    "validation-operator": ("data", "inference", "analysis"),
    "slide-analyst": ("data", "annotation", "inference", "analysis"),
    "literature-scout": ("literature",),
}


def visible_dataset_ids(user):
    from .dataset_access import accessible_dataset_ids

    return accessible_dataset_ids(user)


@dataclass(frozen=True)
class WorkspaceScope:
    workspace_id: str | None = None
    name: str = "All accessible resources"
    dataset_ids: tuple[str, ...] | None = None
    root_paths: tuple[str, ...] = ()
    enabled_skills: tuple[str, ...] = tuple(SKILLS)
    enabled_connectors: tuple[str, ...] = tuple(CONNECTORS)
    execution_mode: str = "standard"
    version: int = 0

    def datasets(self, user):
        query = visible_dataset_ids(user)
        if self.dataset_ids is not None:
            query = query.where(Dataset.dataset_id.in_(self.dataset_ids))
        return query

    def task_filter(self, task_column, user):
        # A multi-dataset task must have all its inputs inside the effective scope.
        inputs = (
            select(TrainingTaskWSI.id)
            .join(WSISlide, WSISlide.wsi_id == TrainingTaskWSI.wsi_id)
            .where(TrainingTaskWSI.task_id == task_column)
        )
        return and_(
            exists(inputs),
            ~exists(
                inputs.where(
                    or_(
                        WSISlide.dataset_id.is_(None),
                        WSISlide.dataset_id.not_in(self.datasets(user)),
                    )
                )
            ),
        )

    def validate_scan_path(self, directory: str) -> str:
        path = Path(directory).expanduser().resolve()
        if self.workspace_id and not any(
            path.is_relative_to(Path(root).resolve()) for root in self.root_paths
        ):
            raise HTTPException(403, "Directory is outside the workspace scan roots")
        return str(path)


async def resolve_scope(db, user, workspace_id: str | None) -> WorkspaceScope:
    if not workspace_id:
        return WorkspaceScope()
    workspace = (
        await db.execute(
            select(Workspace).where(
                Workspace.workspace_id == workspace_id, Workspace.archived.is_(False)
            )
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise HTTPException(404, "Workspace not found or archived")
    if not user.is_admin() and workspace.user_id != str(user.id):
        raise HTTPException(403, "Workspace access denied")
    return WorkspaceScope(
        workspace_id=workspace.workspace_id,
        name=workspace.name,
        dataset_ids=tuple(workspace.dataset_ids or []),
        root_paths=tuple(workspace.root_paths or []),
        enabled_skills=tuple(workspace.enabled_skills or []),
        enabled_connectors=tuple(workspace.enabled_connectors or []),
        execution_mode=workspace.execution_mode,
        version=workspace.version,
    )


async def dataset_capabilities(db, user, dataset):
    from backend.auth.dependencies import (
        check_dataset_access_permission,
        check_dataset_write_permission,
        check_dataset_gpu_permission,
    )

    readable = await check_dataset_access_permission(
        user,
        dataset.dataset_id,
        dataset.user_id,
        db,
        is_public=dataset.is_public,
        parent_dataset_id=dataset.parent_dataset_id,
    )
    return {
        "read": readable,
        "write": readable
        and await check_dataset_write_permission(
            user,
            dataset.dataset_id,
            dataset.user_id,
            db,
            parent_dataset_id=dataset.parent_dataset_id,
        ),
        "run_gpu": readable
        and await check_dataset_gpu_permission(user, dataset.dataset_id, db),
        "autoresearch": readable and user.can_use_gpu(),
    }
