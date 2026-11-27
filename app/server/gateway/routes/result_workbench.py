"""Result workbench API: bounded catalog, immutable runs, recipes and scoped assistant."""

from __future__ import annotations

import asyncio
import csv
import io
import json
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import Field
from sqlalchemy import case, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import User, current_active_user
from backend.database import get_db
from backend.database.models import (
    AutoResearchSession,
    Dataset,
    DataGroup,
    ResultAnalysis,
    ResultConversation,
    ResultRecipe,
    ResultSource,
    TrainingTask,
    TrainingTaskWSI,
    TrainedModel,
    WSISlide,
    utc_now,
)
from backend.services.result_analysis.contracts import (
    AnalysisConfig,
    StrictModel,
    catalog,
)
from backend.services.result_analysis.sources import (
    authorized_sources,
    public_source,
    visibility,
)
from backend.services.result_analysis.runs import (
    owned_run,
    public_run,
    run_directory,
    submit,
)
from backend.services.workspaces import resolve_scope

router = APIRouter(prefix="/results/workbench", tags=["Result workbench"])
Workspace = Annotated[str | None, Header(alias="X-Workspace-ID")]


@router.get("/catalog")
async def get_catalog(user: User = Depends(current_active_user)):
    return catalog()


@router.get("/sources")
async def list_sources(
    query: str = Query("", max_length=200),
    kind: str = "",
    task_family: str = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await resolve_scope(db, user, workspace_id)
    statement = select(ResultSource).where(*visibility(user, scope))
    if query:
        statement = statement.where(
            or_(
                ResultSource.title.ilike(f"%{query}%"),
                ResultSource.task_type.ilike(f"%{query}%"),
            )
        )
    if kind:
        statement = statement.where(ResultSource.kind == kind)
    if task_family:
        from sqlalchemy import String, cast

        if task_family == "multitask":
            statement = statement.where(func.json_array_length(ResultSource.details['task_families']) > 1)
        else:
            statement = statement.where(
                cast(ResultSource.details["task_families"], String).contains(
                    json.dumps(task_family)
                )
            )
    rows = (
        (
            await db.execute(
                statement.order_by(
                    ResultSource.created_at.desc(), ResultSource.source_id
                )
                .offset(offset)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [public_source(row) for row in rows[:limit]],
        "has_more": len(rows) > limit,
    }


@router.get("/source")
async def get_source(
    source_id: str,
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return public_source(
        (await authorized_sources(db, user, [source_id], workspace_id))[0]
    )


@router.get("/source/artifact")
async def source_artifact(
    source_id: str,
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    source = (await authorized_sources(db, user, [source_id], workspace_id))[0]
    if source.kind != "analysis":
        raise HTTPException(404, "This source has no published analysis document")
    session = (
        await db.execute(
            select(AutoResearchSession).where(
                AutoResearchSession.session_id == source.session_id
            )
        )
    ).scalar_one()
    from backend.autoresearch.engine.analysis_results import read_result

    try:
        return await asyncio.to_thread(
            read_result, Path(session.workspace_path), source.details["path"]
        )
    except (OSError, ValueError):
        raise HTTPException(404, "Published analysis file unavailable") from None


@router.get("/source/figure")
async def source_figure(
    source_id: str,
    path: str,
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    source = (await authorized_sources(db, user, [source_id], workspace_id))[0]
    if source.kind != "analysis":
        raise HTTPException(404, "Figure not found")
    session = (
        await db.execute(
            select(AutoResearchSession).where(
                AutoResearchSession.session_id == source.session_id
            )
        )
    ).scalar_one()
    from backend.autoresearch.engine.analysis_results import read_result
    from backend.autoresearch.engine.jobs import contained

    result = await asyncio.to_thread(
        read_result, Path(session.workspace_path), source.details["path"]
    )
    if path not in {f["path"] for f in result["figures"]} | {result["code_path"]}:
        raise HTTPException(404, "Figure not found")
    return FileResponse(
        contained(Path(session.workspace_path), path),
        headers={
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


class RunRequest(StrictModel):
    config: AnalysisConfig
    title: str = Field("", max_length=200)


@router.post("/runs")
async def create_run(
    body: RunRequest,
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return public_run(
        await submit(db, user, body.config, workspace_id, body.title), True
    )


@router.get("/runs")
async def list_runs(
    source_id: str = "",
    status: str = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if source_id:
        await authorized_sources(db, user, [source_id], workspace_id)
    statement = select(
        ResultAnalysis.analysis_id,
        ResultAnalysis.title,
        ResultAnalysis.status,
        ResultAnalysis.progress,
        ResultAnalysis.phase,
        ResultAnalysis.error,
        ResultAnalysis.created_at,
        ResultAnalysis.finished_at,
        ResultAnalysis.sources,
    )
    if not user.is_admin():
        statement = statement.where(ResultAnalysis.user_id == str(user.id))
    if status == "background":
        statement = statement.where(ResultAnalysis.user_id == str(user.id))
    if workspace_id:
        statement = statement.where(ResultAnalysis.workspace_id == workspace_id)
    # JSON containment isn't portable to SQLite; use an exact source ID JSON text match,
    # followed by authoritative source checks when opening the record.
    if source_id:
        from sqlalchemy import String, cast

        statement = statement.where(
            cast(ResultAnalysis.sources, String).contains(json.dumps(source_id))
        )
    if status == "active":
        statement = statement.where(
            ResultAnalysis.status.in_(["queued", "running", "cancelling"])
        )
    rows = (
        await db.execute(
            statement.order_by(
                case((ResultAnalysis.status.in_(["queued", "running", "cancelling"]), 0), else_=1)
                if status == "background" else ResultAnalysis.created_at.desc(),
                ResultAnalysis.created_at.desc(), ResultAnalysis.analysis_id
            )
            .offset(offset)
            .limit(limit + 1)
        )
    ).all()
    accessible = []
    scope = await resolve_scope(db, user, workspace_id)
    source_ids = {item["source_id"] for row in rows[:limit] for item in row.sources}
    allowed = set(
        (
            await db.execute(
                select(ResultSource.source_id).where(
                    ResultSource.source_id.in_(source_ids), *visibility(user, scope)
                )
            )
        ).scalars()
    )
    for row in rows[:limit]:
        if {item["source_id"] for item in row.sources} <= allowed:
            accessible.append(public_run(row))
    return {"items": accessible, "has_more": len(rows) > limit}


@router.get("/runs/{analysis_id}")
async def get_run(
    analysis_id: str,
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return public_run(await owned_run(db, user, analysis_id, workspace_id), True)


@router.delete("/runs/{analysis_id}")
async def delete_run(
    analysis_id: str,
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    row = await owned_run(db, user, analysis_id, workspace_id)
    if row.status in {"running", "queued", "cancelling"}:
        raise HTTPException(409, "Cancel the analysis before deleting it")
    from backend.storage.deletion import enqueue
    await enqueue(db, user.id, paths=[f'analysis-workbench/{analysis_id}'])
    await db.delete(row)
    await db.commit()
    return {"deleted": True}


@router.get("/runs/{analysis_id}/preview")
async def sample_preview(
    analysis_id: str, source_id: str, wsi_id: str,
    layer: str = Query("pred", pattern="^(pred|gt)$"),
    class_index: int = Query(0, ge=0, le=1023),
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user), db: AsyncSession = Depends(get_db),
):
    row = await owned_run(db, user, analysis_id, workspace_id)
    if row.status != "completed":
        raise HTTPException(409, "Analysis is not complete")
    saved = next((s for s in row.sources if s["source_id"] == source_id), None)
    if not saved or saved["task_type"] != "patch_segmentation":
        raise HTTPException(404, "Segmentation sample not found")
    source = (await authorized_sources(db, user, [source_id], workspace_id))[0]
    if source.revision != saved["revision"]:
        raise HTTPException(409, "Predictions changed since this analysis; run a new analysis to view matching masks")
    from backend.services.result_analysis.inputs import prediction_query
    config = AnalysisConfig.model_validate(row.config)
    sample = (await db.execute(prediction_query(source.task_id, config).where(WSISlide.wsi_id == wsi_id).limit(1))).first()
    if sample is None:
        raise HTTPException(404, "Sample is outside this analysis")
    from backend.services.result_analysis.previews import render_mask
    from backend.common.config import Config
    try:
        image = await asyncio.to_thread(render_mask, Config.get_uploads_dir(), source.task_id, wsi_id, layer, class_index, config.threshold)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(image, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})


@router.get("/runs/{analysis_id}/samples")
async def run_samples(
    analysis_id: str,
    offset: int = Query(0, ge=0),
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    row = await owned_run(db, user, analysis_id, workspace_id)
    if row.status != "completed":
        raise HTTPException(409, "Analysis is not complete")
    if offset % 50:
        raise HTTPException(422, "Sample pages contain 50 records")
    directory = run_directory(analysis_id)

    def read_page():
        index_path = directory / "sample-index.json"
        if not index_path.is_file():
            samples = [
                {**sample, "source_title": source["title"]}
                for source in (row.result or {}).get("results", [])
                for sample in source.get("samples", [])
            ]
            return {
                "items": samples[offset : offset + 50],
                "has_more": offset + 50 < len(samples),
            }
        index = json.loads(index_path.read_text())
        if offset >= index["count"]:
            return {"items": [], "has_more": False}
        with (directory / "samples.jsonl").open("rb") as file:
            file.seek(index["offsets"][offset // 50])
            items = []
            for _ in range(50):
                line = file.readline()
                if not line:
                    break
                items.append(json.loads(line))
        return {"items": items, "has_more": offset + 50 < index["count"]}

    return await asyncio.to_thread(read_page)


@router.post("/runs/{analysis_id}/cancel")
async def cancel_run(
    analysis_id: str,
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    row = await owned_run(db, user, analysis_id, workspace_id)
    row = (
        await db.execute(
            select(ResultAnalysis)
            .where(ResultAnalysis.analysis_id == analysis_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if row.status in {"running", "queued"}:
        from backend.common.task_dispatch import publish_task_cancellation

        queued = row.status == "queued"
        row.status = "cancelled" if queued else "cancelling"
        row.finished_at = utc_now() if queued else None
        await db.commit()
        await publish_task_cancellation(analysis_id)
    return public_run(row)


@router.get("/runs/{analysis_id}/export")
async def export_run(
    analysis_id: str,
    format: str = "json",
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    row = await owned_run(db, user, analysis_id, workspace_id)
    if row.status != "completed":
        raise HTTPException(409, "Analysis is not complete")
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["source", "metric", "value", "unit", "ci_lower", "ci_upper"])
        for result in (row.result or {}).get("results", []):
            for metric, value in result["metrics"].items():
                writer.writerow(
                    [
                        result["title"],
                        metric,
                        value.get("value"),
                        value.get("unit"),
                        value.get("ci_lower"),
                        value.get("ci_upper"),
                    ]
                )
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{analysis_id}.csv"'
            },
        )
    if format == "inputs":
        path = run_directory(analysis_id) / "input.json"
        if not path.is_file():
            raise HTTPException(404, "This analysis has no frozen input snapshot")
        return FileResponse(path, filename=f"{analysis_id}_inputs.json")
    if format == "original":
        native = (row.result or {}).get("native_artifact")
        if not native:
            raise HTTPException(404, "Original evaluation artifact unavailable")
        from backend.common.config import Config

        path = (
            Config.get_uploads_dir()
            / "logs"
            / "analysis"
            / native["task_id"]
            / native["analysis_id"]
            / "results.json"
        )
        if not path.is_file():
            raise HTTPException(404, "Original evaluation artifact unavailable")
        return FileResponse(path, filename=f"{analysis_id}_original.json")
    if format != "json":
        raise HTTPException(422, "Unknown export format")
    return Response(
        json.dumps(public_run(row, True), ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{analysis_id}.json"'},
    )


class RecipeRequest(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    config: AnalysisConfig
    version: int | None = None


def recipe_item(row):
    return {
        "recipe_id": row.recipe_id,
        "name": row.name,
        "config": row.config,
        "version": row.version,
    }


@router.get("/recipes")
async def list_recipes(
    offset: int = Query(0, ge=0),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        (
            await db.execute(
                select(ResultRecipe)
                .where(ResultRecipe.user_id == str(user.id))
                .order_by(ResultRecipe.updated_at.desc())
                .offset(offset)
                .limit(21)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [recipe_item(row) for row in rows[:20]],
        "has_more": len(rows) > 20,
    }


@router.post("/recipes")
async def create_recipe(
    body: RecipeRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    config = body.config.model_copy(update={"source_ids": []})
    row = ResultRecipe(
        recipe_id=uuid4().hex,
        user_id=str(user.id),
        name=body.name,
        config=config.model_dump(),
    )
    db.add(row)
    await db.flush()
    return recipe_item(row)


@router.put("/recipes/{recipe_id}")
async def update_recipe(
    recipe_id: str,
    body: RecipeRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(ResultRecipe)
            .where(
                ResultRecipe.recipe_id == recipe_id,
                ResultRecipe.user_id == str(user.id),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Recipe not found")
    if body.version != row.version:
        raise HTTPException(409, "Recipe changed; reload before saving")
    row.name, row.config, row.version = (
        body.name,
        body.config.model_copy(update={"source_ids": []}).model_dump(),
        row.version + 1,
    )
    return recipe_item(row)


@router.delete("/recipes/{recipe_id}")
async def delete_recipe(
    recipe_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        delete(ResultRecipe).where(
            ResultRecipe.recipe_id == recipe_id, ResultRecipe.user_id == str(user.id)
        )
    )
    if not result.rowcount:
        raise HTTPException(404, "Recipe not found")
    return {"deleted": True}


@router.get("/models")
async def model_options(
    query: str = Query("", max_length=200),
    offset: int = Query(0, ge=0),
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await resolve_scope(db, user, workspace_id)
    statement = (
        select(
            TrainedModel.model_id,
            TrainedModel.model_name,
            TrainedModel.task_id,
            TrainedModel.classes,
            DataGroup.task_type,
        )
        .join(TrainingTask, TrainingTask.task_id == TrainedModel.task_id)
        .join(DataGroup, DataGroup.group_id == TrainingTask.group_id)
        .where(TrainedModel.is_active.is_(True))
    )
    if not user.is_admin():
        statement = statement.where(TrainedModel.user_id == str(user.id), TrainingTask.user_id == str(user.id))
    if workspace_id:
        statement = statement.where(scope.task_filter(TrainedModel.task_id, user))
    if query:
        statement = statement.where(TrainedModel.model_name.ilike(f"%{query}%"))
    rows = (
        (
            await db.execute(
                statement.order_by(TrainedModel.created_at.desc())
                .offset(offset)
                .limit(21)
            )
        )
        .mappings()
        .all()
    )
    return {"items": [dict(row) for row in rows[:20]], "has_more": len(rows) > 20}


@router.get("/model")
async def model_option(
    model_id: str,
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await resolve_scope(db, user, workspace_id)
    statement = (
        select(
            TrainedModel.model_id,
            TrainedModel.model_name,
            TrainedModel.task_id,
            TrainedModel.classes,
            DataGroup.task_type,
        )
        .join(TrainingTask, TrainingTask.task_id == TrainedModel.task_id)
        .join(DataGroup, DataGroup.group_id == TrainingTask.group_id)
        .where(TrainedModel.model_id == model_id, TrainedModel.is_active.is_(True))
    )
    if not user.is_admin():
        statement = statement.where(TrainedModel.user_id == str(user.id), TrainingTask.user_id == str(user.id))
    if workspace_id:
        statement = statement.where(scope.task_filter(TrainedModel.task_id, user))
    row = (await db.execute(statement)).mappings().one_or_none()
    if not row:
        raise HTTPException(404, "Model unavailable")
    return dict(row)


@router.get("/datasets")
async def dataset_options(
    model_id: str,
    query: str = Query("", max_length=200),
    offset: int = Query(0, ge=0),
    mode: str = "external",
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await resolve_scope(db, user, workspace_id)
    await model_option(model_id, workspace_id, user, db)
    model = (
        await db.execute(select(TrainedModel).where(TrainedModel.model_id == model_id))
    ).scalar_one_or_none()
    if not model or (not user.is_admin() and model.user_id != str(user.id)):
        raise HTTPException(404, "Model not found")
    task = (
        await db.execute(
            select(TrainingTask).where(TrainingTask.task_id == model.task_id)
        )
    ).scalar_one()
    group = await db.scalar(
        select(DataGroup).where(DataGroup.group_id == task.group_id)
    )
    statement = (
        select(Dataset.dataset_id, Dataset.name)
        .where(
            Dataset.dataset_id.in_(scope.datasets(user)),
            Dataset.tasks.any(task_type=group.task_type),
        )
    )
    if query:
        statement = statement.where(Dataset.name.ilike(f"%{query}%"))
    datasets = (
        await db.execute(statement.order_by(Dataset.name).offset(offset).limit(21))
    ).all()
    items = []
    for ds in datasets[:20]:
        count = await db.scalar(
            select(func.count())
            .select_from(WSISlide)
            .where(WSISlide.dataset_id == ds.dataset_id)
        )
        overlap = await db.scalar(
            select(
                exists(
                    select(TrainingTaskWSI.id)
                    .join(WSISlide, WSISlide.wsi_id == TrainingTaskWSI.wsi_id)
                    .where(
                        TrainingTaskWSI.task_id == model.task_id,
                        WSISlide.dataset_id == ds.dataset_id,
                    )
                )
            )
        )
        reason = (
            "Training dataset overlap"
            if overlap and mode == "external"
            else "Dataset is empty"
            if not count
            else None
        )
        if mode == "inference":
            from .results import _is_dataset_unlabeled_for_batch_inference

            if not await _is_dataset_unlabeled_for_batch_inference(
                db, ds.dataset_id, group.task_type
            ):
                reason = (
                    reason
                    or "Dataset already has ground truth; use external validation"
                )
        elif "classification" in group.task_type:
            labels = set(
                (
                    await db.execute(
                        select(WSISlide.label)
                        .where(
                            WSISlide.dataset_id == ds.dataset_id,
                            WSISlide.label.isnot(None),
                        )
                        .distinct()
                    )
                ).scalars()
            )
            normalize = lambda values: {v.strip().lower() for v in values if v}
            if normalize(labels) != normalize(model.classes):
                reason = reason or "Ground-truth classes do not match the model"
        elif group.task_type in {"patch_segmentation", "patch_detection"}:
            from backend.database.repositories import WSIRepository

            categories = await WSIRepository._get_coco_categories_for_dataset(
                db, ds.dataset_id, group.task_type
            )
            target_labels = {
                str(category.get("name", "")).strip().lower() for category in categories
            }
            if target_labels != {str(label).strip().lower() for label in model.classes}:
                reason = (
                    reason or "Segmentation ground-truth classes do not match the model"
                )
        items.append(
            {
                "dataset_id": ds.dataset_id,
                "name": ds.name,
                "count": count,
                "compatible": reason is None,
                "reason": reason,
            }
        )
    return {"items": items, "has_more": len(datasets) > 20}


@router.get("/images")
async def image_options(
    model_id: str,
    query: str = Query("", max_length=200),
    offset: int = Query(0, ge=0),
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    model = await model_option(model_id, workspace_id, user, db)
    scope = await resolve_scope(db, user, workspace_id)
    from backend.database.models import SegmentationAnnotation
    from backend.storage import external_availability

    statement = (
        select(WSISlide.wsi_id, WSISlide.original_filename, WSISlide.wsi_path)
        .join(Dataset, Dataset.dataset_id == WSISlide.dataset_id)
        .where(
            WSISlide.dataset_id.in_(scope.datasets(user)),
            Dataset.tasks.any(task_type=model["task_type"]),
        )
    )
    if "classification" in model["task_type"]:
        statement = statement.where(
            or_(WSISlide.label.is_(None), func.trim(WSISlide.label) == "")
        )
    elif "survival" in model["task_type"]:
        statement = statement.where(
            WSISlide.event_time.is_(None), WSISlide.event_status.is_(None)
        )
    else:
        statement = statement.where(
            ~exists(
                select(SegmentationAnnotation.id).where(
                    SegmentationAnnotation.annotation_id == "label_" + WSISlide.wsi_id,
                    SegmentationAnnotation.source != "viewer",
                    SegmentationAnnotation.status == "finalized",
                )
            )
        )
    if query:
        statement = statement.where(WSISlide.original_filename.ilike(f"%{query}%"))
    rows = (
        await db.execute(
            statement.order_by(WSISlide.created_at.desc(), WSISlide.wsi_id)
            .offset(offset)
            .limit(51)
        )
    ).all()
    return {
        "items": [
            {
                "wsi_id": row.wsi_id,
                "original_filename": row.original_filename,
                "availability": external_availability.get_wsi_availability(row.wsi_id)
                if external_availability.is_external_path(row.wsi_path)
                else {"status": "available"},
            }
            for row in rows[:50]
        ],
        "has_more": len(rows) > 50,
    }


class AssistantRequest(StrictModel):
    message: str = Field(min_length=1, max_length=6000)
    config: AnalysisConfig
    analysis_id: str | None = None
    conversation_id: str | None = None
    version: int | None = None
    language: str = Field("zh-CN", max_length=20)


@router.get("/assistant/{conversation_id}")
async def assistant_history(
    conversation_id: str,
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(ResultConversation, conversation_id)
    if row is None or row.user_id != str(user.id) or row.workspace_id != workspace_id:
        raise HTTPException(404, "Conversation not found")
    ids = {
        identity
        for message in row.messages
        for identity in message.get("source_ids", [])
    }
    await authorized_sources(db, user, list(ids), workspace_id)
    return {
        "conversation_id": row.conversation_id,
        "version": row.version,
        "messages": row.messages,
    }


@router.post("/assistant")
async def assistant(
    body: AssistantRequest,
    request: Request,
    workspace_id: Workspace = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    from backend.services.result_analysis.assistant import decide
    from backend.services.result_analysis.contracts import validate_selection

    scope = await resolve_scope(db, user, workspace_id)
    sources = await authorized_sources(db, user, body.config.source_ids, workspace_id)
    context = {
        "config": body.config.model_dump(),
        "sources": [public_source(source) for source in sources],
    }
    if body.analysis_id:
        measured = await owned_run(db, user, body.analysis_id, workspace_id)
        context["measured_result"] = {
            "analysis_id": measured.analysis_id,
            "status": measured.status,
            "config": measured.config,
            "results": [
                {
                    key: value
                    for key, value in item.items()
                    if key
                    in {"title", "source_id", "count", "metrics", "notes", "groups"}
                }
                for item in (measured.result or {}).get("results", [])
            ],
        }
    conversation = None
    if body.conversation_id:
        conversation = await db.get(ResultConversation, body.conversation_id)
        if (
            not conversation
            or conversation.user_id != str(user.id)
            or conversation.workspace_id != workspace_id
        ):
            raise HTTPException(404, "Conversation not found")
        if body.version != conversation.version:
            raise HTTPException(409, "Conversation changed; reload before continuing")
        await authorized_sources(
            db,
            user,
            list(
                {
                    identity
                    for item in conversation.messages
                    for identity in item.get("source_ids", [])
                }
            ),
            workspace_id,
        )
    history = list(conversation.messages) if conversation else []
    readonly = (
        scope.execution_mode == "read_only"
        or request.headers.get("X-Workspace-Mode") == "read_only"
        or not user.can_use_gpu()
    )
    if "analysis" not in scope.enabled_skills:
        readonly = True
    selected_skills = request.headers.get("X-Chat-Skills")
    if selected_skills is not None:
        try:
            parsed_skills = json.loads(selected_skills)
            if not isinstance(parsed_skills, list) or not all(
                isinstance(item, str) for item in parsed_skills
            ):
                raise ValueError()
            readonly = readonly or "analysis" not in parsed_skills
        except (ValueError, TypeError):
            raise HTTPException(422, "Invalid selected skills") from None
    # Release the read transaction while waiting on the model.
    await db.commit()
    try:
        import httpx

        decision = await decide(context, history, body.message, body.language, readonly)
    except (ValueError, KeyError, IndexError, TypeError, httpx.HTTPError):
        raise HTTPException(
            502,
            "Analysis assistant is unavailable or returned an invalid response. Your configuration is unchanged.",
        ) from None
    if await request.is_disconnected():
        raise HTTPException(499, "Request cancelled")
    await authorized_sources(db, user, body.config.source_ids, workspace_id)
    # The response must stay within the explicitly selected sources.
    if decision.config:
        if set(decision.config.source_ids) != set(body.config.source_ids):
            raise HTTPException(422, "Assistant changed the selected result sources")
        sources = await authorized_sources(
            db, user, decision.config.source_ids, workspace_id
        )
        try:
            validate_selection(decision.config, sources)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    if body.conversation_id:
        conversation = (
            await db.execute(
                select(ResultConversation)
                .where(ResultConversation.conversation_id == body.conversation_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        if body.version != conversation.version:
            raise HTTPException(409, "Conversation changed; reload before continuing")
    else:
        conversation = ResultConversation(
            conversation_id=uuid4().hex,
            user_id=str(user.id),
            workspace_id=workspace_id,
            messages=[],
            version=0,
        )
        db.add(conversation)
    conversation.version += 1
    conversation.messages = history + [
        {"role": "user", "content": body.message, "source_ids": body.config.source_ids}
    ]
    await db.flush()
    run = None
    if decision.action == "run":
        # The same endpoint and validation used by the manual Run button.
        run = public_run(await submit(db, user, decision.config, workspace_id), True)
    history.extend(
        [
            {
                "role": "user",
                "content": body.message,
                "source_ids": body.config.source_ids,
            },
            {
                "role": "assistant",
                "content": decision.message,
                "source_ids": body.config.source_ids,
                "action": decision.action,
                "config": decision.config.model_dump() if decision.config else None,
                "analysis_id": run["analysis_id"] if run else None,
                "handoff": decision.handoff,
            },
        ]
    )
    conversation.messages, conversation.updated_at = history[-40:], utc_now()
    await db.commit()
    return {
        "conversation_id": conversation.conversation_id,
        "version": conversation.version,
        "messages": conversation.messages,
        **decision.model_dump(),
        "run": run,
    }
