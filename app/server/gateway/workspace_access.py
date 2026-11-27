"""Enforce explicit workspace headers on API actions, independently of prompts."""

from __future__ import annotations

import json

from fastapi import HTTPException, Request
from starlette.requests import HTTPConnection
from typing import cast
from sqlalchemy import select

from backend.database import safe_session
from backend.database.models import (
    Dataset,
    WSISlide,
    TrainingTask,
    TrainedModel,
    AITask,
)
from backend.services.workspaces import resolve_scope


async def enforce_workspace_request(connection: HTTPConnection):
    # Presence WebSockets retain their own authenticated access checks.
    if connection.scope["type"] != "http":
        return
    request = cast(Request, connection)
    workspace_id = request.headers.get("X-Workspace-ID")
    mode = request.headers.get("X-Workspace-Mode")
    selected_skills = request.headers.get("X-Chat-Skills")
    if not workspace_id and not mode and selected_skills is None:
        return
    if mode not in (None, "standard", "read_only"):
        raise HTTPException(422, "Invalid workspace execution mode")
    path = request.url.path.removeprefix("/api")
    # Scope configuration must remain reachable even if an old binding was archived.
    if path.startswith(("/workspaces", "/conversations", "/auth", "/capabilities")) or path == "/chat":
        return
    # These POST endpoints are read queries with bounded structured parameters.
    if path in {"/workbench/resolve", "/workbench/research-statuses", "/results/workbench/assistant"}:
        return
    # History file browsing is authorized against the requested conversation's
    # saved workspace, independently from the currently open conversation.
    if request.method == 'GET' and path.startswith('/workbench/conversations/'):
        return
    # Authenticate using the shared JWT validation, including session revocation.
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    from backend.auth.dependencies import _get_user_from_jwt

    credentials: HTTPAuthorizationCredentials = await HTTPBearer()(request)
    async with safe_session() as db:
        user = await _get_user_from_jwt(credentials.credentials, db)
        scope = await resolve_scope(db, user, workspace_id)
        request.state.workspace_scope = scope
        file_lookup = path.startswith('/workbench/research/') and path.endswith(('/index', '/file-reference'))
        viewer_query = path.startswith('/viewer/slides/') and path.endswith(('/assistant','/search','/geometry','/assist','/regions/selection'))
        mutating = request.method not in ("GET", "HEAD", "OPTIONS") and not file_lookup and not viewer_query
        if mutating and (mode == "read_only" or scope.execution_mode == "read_only"):
            raise HTTPException(403, "Workspace is read-only")
        skill = next(
            (
                value
                for prefix, value in (
                    ("/tasks/training", "training"),
                    ("/ai", "inference"),
                    ("/patch-inference", "inference"),
                    ("/research", "training"),
                    ("/results/external-validation", "inference"),
                    ("/results/batch-inference", "inference"),
                    ("/results/independent-inference", "inference"),
                    ("/results", "analysis"),
                    ("/reports", "analysis"),
                    ("/annotation", "annotation"),
                    ("/viewer", "annotation"),
                    ("/wsi", "data"),
                    ("/storage", "data"),
                )
                if path.startswith(prefix)
            ),
            None,
        )
        enabled_skills = set(scope.enabled_skills)
        if selected_skills is not None:
            try:
                parsed = json.loads(selected_skills)
                if not isinstance(parsed, list) or not all(
                    isinstance(item, str) for item in parsed
                ):
                    raise ValueError()
                enabled_skills.intersection_update(parsed)
            except ValueError:
                raise HTTPException(422, "Invalid selected skills")
        if mutating and skill and skill not in enabled_skills:
            raise HTTPException(403, "This skill is disabled in the workspace")
        if not workspace_id:
            return
        payload = dict(request.query_params)
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                body = await request.json()
                if isinstance(body, dict):
                    payload.update(body)
            except ValueError:
                raise HTTPException(422, "Invalid JSON")
        elif "multipart/form-data" in request.headers.get("content-type", ""):
            form = await request.form()
            payload.update(
                {key: value for key, value in form.items() if isinstance(value, str)}
            )
        payload.update(request.path_params)
        if path in {'/wsi/upload/file','/wsi/upload/path'}:
            # This ID identifies the new/idempotent upload, not an existing input.
            payload.pop('wsi_id',None)
        requested_workspace = payload.get("workspace_id")
        if requested_workspace and requested_workspace != workspace_id:
            raise HTTPException(409, "Workspace header and resource query differ")
        if "task_id" in request.path_params:
            task_id = request.path_params["task_id"]
            task = (
                await db.execute(
                    select(TrainingTask.task_id).where(TrainingTask.task_id == task_id)
                )
            ).scalar_one_or_none()
            if task:
                payload["training_task_id"] = task_id
            else:
                ai_task = (
                    await db.execute(select(AITask).where(AITask.task_id == task_id))
                ).scalar_one_or_none()
                if ai_task:
                    payload["wsi_id"] = ai_task.wsi_id
        # Request path parameters are populated before router dependencies run.
        ids = scope.datasets(user)
        checks = (
            (
                (
                    "dataset_id",
                    "dataset_ids",
                    "source_dataset_id",
                    "data_task_id",
                    "target_dataset_id",
                ),
                Dataset.dataset_id,
                Dataset.dataset_id.in_(ids),
            ),
            (("wsi_id", "wsi_ids"), WSISlide.wsi_id, WSISlide.dataset_id.in_(ids)),
            (
                ("model_id",),
                TrainedModel.model_id,
                scope.task_filter(TrainedModel.task_id, user),
            ),
            (
                ("model_task_id", "training_task_id", "rerun_from_task_id"),
                TrainingTask.task_id,
                scope.task_filter(TrainingTask.task_id, user),
            ),
        )
        for keys, column, condition in checks:
            selected = []
            for key in keys:
                value = payload.get(key)
                if isinstance(value, str) and value:
                    selected.append(value)
                elif isinstance(value, list):
                    selected.extend(str(item) for item in value)
            if selected:
                found = set(
                    (
                        await db.execute(
                            select(column).where(column.in_(selected), condition)
                        )
                    )
                    .scalars()
                    .all()
                )
                if set(selected) - found:
                    raise HTTPException(
                        403, "Resource is outside the accessible workspace"
                    )
        if payload.get("directory_path"):
            scope.validate_scan_path(str(payload["directory_path"]))
