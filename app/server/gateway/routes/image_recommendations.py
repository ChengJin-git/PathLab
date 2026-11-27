"""Bounded image-card queries: filter in SQL instead of downloading whole inventories."""

from pathlib import Path
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import and_, case, cast, exists, func, or_, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import User, current_active_user
from backend.database import get_db
from backend.database.models import (
    AIResult,
    AITask,
    DataGroup,
    Dataset,
    TrainingTask,
    TrainedModel,
    WSISlide,
)
from backend.services.workspaces import resolve_scope

router = APIRouter(tags=["WSI Management"])


def recommendation_query(
    user,
    scope,
    *,
    dataset_id=None,
    data_type=None,
    label=None,
    pred=None,
    has_predictions=False,
    correct_prediction=None,
    event_status=None,
    segmentation_class=None,
    task_id=None,
    feature_extractor=None,
    aggregator=None,
    result_task_type=None,
    query="",
    limit=3
):
    image_type = func.coalesce(WSISlide.data_type, Dataset.data_type)
    statement = (
        select(
            WSISlide.wsi_id,
            WSISlide.original_filename,
            WSISlide.dataset_id,
            Dataset.name.label("dataset_name"),
            WSISlide.case_id,
            WSISlide.label,
            WSISlide.age,
            WSISlide.gender,
            WSISlide.source,
            WSISlide.event_time,
            WSISlide.event_status,
            WSISlide.split,
            WSISlide.file_size,
            image_type.label("data_type"),
            WSISlide.created_at,
        )
        .outerjoin(Dataset, Dataset.dataset_id == WSISlide.dataset_id)
    )
    filters = []
    if scope.dataset_ids is not None or scope.workspace_id or not user.is_admin():
        visible = WSISlide.dataset_id.in_(scope.datasets(user))
        if scope.dataset_ids is None and not scope.workspace_id:
            visible = or_(
                visible,
                and_(WSISlide.dataset_id.is_(None), WSISlide.user_id == str(user.id)),
            )
        filters.append(visible)
    if dataset_id:
        filters.append(WSISlide.dataset_id == dataset_id)
    if data_type:
        filters.append(image_type == data_type)
    if label:
        filters.append(func.lower(WSISlide.label) == label.lower())
    if event_status is not None:
        filters.append(WSISlide.event_status == event_status)
    statement = statement.where(*filters)

    needs_results = (
        has_predictions
        or pred is not None
        or correct_prediction is not None
        or segmentation_class is not None
        or task_id is not None
        or feature_extractor is not None
        or aggregator is not None
        or result_task_type is not None
    )
    if needs_results:
        # Indexed per-slide lookup avoids sorting/materializing every result's
        # metadata before LIMIT. Filter the latest visible result, not an older match.
        latest = select(AIResult.pred, AIResult.task_id, AIResult.extra_metadata).where(
            AIResult.wsi_id == WSISlide.wsi_id
        )
        if not user.is_admin():
            from backend.services.result_access import owned_result_clause
            latest = latest.where(owned_result_clause(user))
        if task_id:
            latest = latest.where(AIResult.task_id == task_id)
        if feature_extractor or aggregator:
            model = select(1).where(TrainedModel.task_id == AIResult.task_id)
            if feature_extractor:
                model = model.where(
                    func.lower(TrainedModel.feature_extractor)
                    == feature_extractor.lower()
                )
            if aggregator:
                model = model.where(
                    or_(
                        image_type == "patch",
                        func.lower(TrainedModel.aggregator) == aggregator.lower(),
                    )
                )
            latest = latest.where(
                exists(model.correlate(AIResult, WSISlide, DataGroup))
            )
        if result_task_type:
            task = (
                select(1)
                .select_from(TrainingTask)
                .join(DataGroup, DataGroup.group_id == TrainingTask.group_id)
                .where(
                    TrainingTask.task_id == AIResult.task_id,
                    DataGroup.task_type == result_task_type,
                )
            )
            latest = latest.where(exists(task.correlate(AIResult)))
        latest = (
            latest.order_by(AIResult.created_at.desc(), AIResult.id.desc())
            .limit(1)
            .correlate(WSISlide)
            .lateral()
        )
        statement = statement.join(latest, true()).add_columns(
            latest.c.pred.label("result_prediction")
        )
        if pred:
            statement = statement.where(func.lower(latest.c.pred) == pred.lower())
        if correct_prediction is not None:
            # Unlabeled predictions are neither correct nor incorrect.
            statement = statement.where(
                WSISlide.label.isnot(None), latest.c.pred.isnot(None)
            )
            matches = func.lower(WSISlide.label) == func.lower(latest.c.pred)
            statement = statement.where(matches if correct_prediction else ~matches)
        if segmentation_class:
            class_names = cast(latest.c.extra_metadata["class_names"], JSONB)
            classes = func.jsonb_array_elements_text(
                case(
                    (func.jsonb_typeof(class_names) == "array", class_names),
                    else_=func.jsonb_build_array(),
                )
            ).table_valued("value")
            statement = statement.where(
                exists(
                    select(1)
                    .select_from(classes)
                    .where(func.lower(classes.c.value) == segmentation_class.lower())
                )
            )

    # Keep filename ranking server-side; generic requests use the indexed recent order.
    if query:
        normalized = query.strip().lower()
        query_base = re.sub(r"\.[^/.]+$", "", normalized)
        filename = func.lower(WSISlide.original_filename)
        basename = func.regexp_replace(filename, r"\.[^/.]+$", "")
        rank = case(
            (filename == normalized, 1000),
            (basename == query_base, 900),
            (filename.startswith(normalized, autoescape=True), 700),
            (basename.startswith(query_base, autoescape=True), 650),
            (filename.contains(normalized, autoescape=True), 500),
            (basename.contains(query_base, autoescape=True), 400),
            (
                and_(
                    *(
                        filename.contains(word, autoescape=True)
                        for word in normalized.split()
                    )
                ),
                200,
            ),
            else_=0,
        )
        statement = statement.order_by(rank.desc(), WSISlide.original_filename)
    return statement.order_by(WSISlide.id.desc()).limit(limit)


@router.get("/recommendations")
async def image_recommendations(
    dataset_id: str | None = None,
    data_type: Literal["wsi", "patch"] | None = None,
    label: str | None = None,
    pred: str | None = None,
    has_predictions: bool = False,
    correct_prediction: bool | None = None,
    event_status: int | None = Query(None, ge=0, le=1),
    segmentation_class: str | None = None,
    task_id: str | None = None,
    feature_extractor: str | None = None,
    aggregator: str | None = None,
    result_task_type: Literal["patch_segmentation"] | None = None,
    query: str = Query("", max_length=200),
    limit: int = Query(3, ge=1, le=100),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
    workspace_id: Annotated[str | None, Header(alias="X-Workspace-ID")] = None,
):
    scope = await resolve_scope(db, user, workspace_id)
    statement = recommendation_query(
        user,
        scope,
        dataset_id=dataset_id,
        data_type=data_type,
        label=label,
        pred=pred,
        has_predictions=has_predictions,
        correct_prediction=correct_prediction,
        event_status=event_status,
        segmentation_class=segmentation_class,
        task_id=task_id,
        feature_extractor=feature_extractor,
        aggregator=aggregator,
        result_task_type=result_task_type,
        query=query,
        limit=limit,
    )
    rows = (await db.execute(statement)).mappings().all()
    items = []
    for row in rows:
        item = dict(row)
        item["file_extension"] = Path(item["original_filename"] or "").suffix.lower()
        items.append(item)
    return {"items": items}
