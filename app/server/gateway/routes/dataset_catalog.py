"""Dataset creation and additive multi-task label imports shared by UI and Chat."""

from uuid import uuid4
from typing import Any, Literal
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from backend.auth import User, current_active_user
from backend.auth.dependencies import get_dataset_with_access
from backend.database import get_db
from backend.database.models import Dataset, DatasetTask, DatasetStats, WSISlide
from backend.database.repositories import (
    SegmentationAnnotationRepository,
    DatasetStatsRepository,
)
from backend.services.dataset_catalog import (
    validate_dataset_tasks,
    validate_metadata,
    task_summaries,
)
from backend.common.chat_context_cache import invalidate_chat_context
from gateway.models import DatasetPropertiesRequest

router = APIRouter(prefix="/wsi/datasets", tags=["Dataset catalog"])


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    data_type: Literal["wsi", "patch"]
    aggregation_level: Literal["file", "case"] = "file"
    task_types: list[str] = Field(min_length=1, max_length=5)
    description: str = Field("", max_length=5000)
    source_organ: str = Field("", max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_public: bool = False

    @model_validator(mode="after")
    def validate(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Dataset name is required")
        validate_dataset_tasks(self.data_type, self.aggregation_level, self.task_types)
        validate_metadata(self.metadata)
        return self


class LabelRow(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    filename: str = Field(min_length=1, max_length=500)
    label: str | None = Field(None, max_length=100)
    event_time: float | None = Field(None, ge=0)
    event_status: Literal[0, 1] | None = None
    case_id: str | None = Field(None, max_length=255)
    age: int | None = Field(None, ge=0, le=150)
    gender: str | None = Field(None, max_length=20)
    split: Literal["train", "val", "test"] | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def clean(self):
        self.filename = self.filename.strip()
        if not self.filename:
            raise ValueError("filename is required")
        if self.label is not None:
            self.label = self.label.strip() or None
        if (self.event_time is None) != (self.event_status is None):
            raise ValueError(
                "Follow-up time and event status must both be present or both be empty"
            )
        return self


class LabelImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    task_types: list[str] = Field(default_factory=list, max_length=5)
    rows: list[LabelRow] = Field(default_factory=list, max_length=10000)
    annotations: dict[str, dict[str, Any]] = Field(default_factory=dict)
    properties: DatasetPropertiesRequest | None = None


def validate_image_labels(dataset, fields):
    """Validate optional image-level targets independently of the upload task."""
    row = LabelRow(
        filename=fields["original_filename"],
        **{
            key: fields[key]
            for key in (
                "label",
                "case_id",
                "age",
                "gender",
                "event_time",
                "event_status",
                "split",
            )
            if fields.get(key) is not None
        },
    )
    if dataset is not None:
        tasks = {task.task_type for task in dataset.tasks}
        if row.label is not None and not any(
            "classification" in task for task in tasks
        ):
            raise HTTPException(422, "Add classification before importing class labels")
        if row.event_time is not None and "wsi_survival" not in tasks:
            raise HTTPException(422, "Add survival analysis before importing outcomes")
        if dataset.aggregation_level == "case" and not (row.case_id or "").strip():
            raise HTTPException(422, "Case-level data requires the original case ID")
    fields["label"] = row.label
    return fields


async def apply_properties(
    db, dataset, properties, user=None, *, defer_visibility=False
):
    """Apply catalog edits inside the caller's locked transaction."""
    from sqlalchemy import update
    from .dataset_visibility import apply_dataset_visibility

    tasks = (
        properties.task_types
        if properties.task_types is not None
        else [task.task_type for task in dataset.tasks]
    )
    level = properties.aggregation_level or dataset.aggregation_level
    data_type = properties.data_type or dataset.data_type
    try:
        validate_dataset_tasks(data_type, level, tasks)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if properties.name is not None:
        conflict = await db.scalar(
            select(Dataset.dataset_id).where(
                Dataset.user_id == dataset.user_id,
                Dataset.name == properties.name,
                Dataset.dataset_id != dataset.dataset_id,
            )
        )
        if conflict:
            raise HTTPException(409, "A dataset with this name already exists")
        dataset.name = properties.name
    if properties.task_types is not None:
        existing = {task.task_type: task for task in dataset.tasks}
        # Tasks with labels remain available; additions never discard another task's targets.
        removed = set(existing) - set(tasks)
        if removed:
            summaries = (await task_summaries(db, [dataset.dataset_id])).get(
                dataset.dataset_id, []
            )
            if any(
                task["task_type"] in removed and task["labelled_count"]
                for task in summaries
            ):
                raise HTTPException(409, "Tasks with labels cannot be removed")
        dataset.tasks = [
            existing.get(task) or DatasetTask(task_type=task) for task in tasks
        ]
    if properties.description is not None:
        dataset.description = properties.description.strip()
    if data_type != dataset.data_type:
        incompatible = await db.scalar(
            select(WSISlide.wsi_id)
            .where(
                WSISlide.dataset_id == dataset.dataset_id,
                WSISlide.data_type.is_distinct_from(data_type),
            )
            .limit(1)
        )
        if incompatible:
            raise HTTPException(
                422,
                "Image type must match the images already registered in this dataset",
            )
        dataset.data_type = data_type
    if properties.task_descriptions is not None:
        if set(properties.task_descriptions) - set(tasks):
            raise HTTPException(
                422, "Task descriptions must refer to selected dataset tasks"
            )
        for task in dataset.tasks:
            if task.task_type in properties.task_descriptions:
                description = properties.task_descriptions[task.task_type]
                if len(description) > 5000:
                    raise HTTPException(422, "Task description exceeds 5000 characters")
                task.description = description.strip()
    if "acquisition_metadata" in properties.model_fields_set:
        dataset.acquisition_metadata = (
            validate_metadata(properties.acquisition_metadata)
            if properties.acquisition_metadata is not None
            else None
        )
    if "parent_dataset_id" in properties.model_fields_set:
        parent = properties.parent_dataset_id
        if db.bind.dialect.name == "postgresql":
            from sqlalchemy import text

            await db.execute(text("SELECT pg_advisory_xact_lock(2026110506)"))
        if parent:
            if user is None:
                raise HTTPException(403, "Parent dataset access must be verified")
            await get_dataset_with_access(parent, user, db)
            ancestors = (
                select(Dataset.dataset_id, Dataset.parent_dataset_id)
                .where(Dataset.dataset_id == parent)
                .cte("ancestors", recursive=True)
            )
            ancestors = ancestors.union(
                select(Dataset.dataset_id, Dataset.parent_dataset_id).join(
                    ancestors, Dataset.dataset_id == ancestors.c.parent_dataset_id
                )
            )
            if await db.scalar(
                select(ancestors.c.dataset_id).where(
                    ancestors.c.dataset_id == dataset.dataset_id
                )
            ):
                raise HTTPException(422, "Dataset ancestry cannot contain a cycle")
        dataset.parent_dataset_id = parent
    if properties.metadata is not None:
        dataset.metadata_fields = validate_metadata(
            {**(dataset.metadata_fields or {}), **properties.metadata}
        )
    if properties.remove_metadata:
        dataset.metadata_fields = {
            key: value
            for key, value in (dataset.metadata_fields or {}).items()
            if key not in properties.remove_metadata
        }
    if "source" in properties.model_fields_set:
        dataset.source_organ = (properties.source or "").strip() or None
        await db.execute(
            update(WSISlide)
            .where(
                WSISlide.dataset_id == dataset.dataset_id,
                WSISlide.source.is_distinct_from(dataset.source_organ),
            )
            .values(source=dataset.source_organ)
        )
    old_level = dataset.aggregation_level
    dataset.aggregation_level = level
    visibility = (
        await apply_dataset_visibility(db, dataset, properties.is_public)
        if properties.is_public is not None and not defer_visibility
        else {}
    )
    await db.flush()
    if level != old_level:
        await DatasetStatsRepository.recompute(db, dataset.dataset_id)
    return visibility


async def validate_case_labels(db, dataset):
    if dataset.aggregation_level != "case":
        return
    from sqlalchemy import func, or_

    missing = await db.scalar(
        select(WSISlide.wsi_id)
        .where(
            WSISlide.dataset_id == dataset.dataset_id,
            or_(WSISlide.case_id.is_(None), func.trim(WSISlide.case_id) == ""),
        )
        .limit(1)
    )
    if missing:
        raise HTTPException(422, "Case-level data requires a case ID for every image")
    conflict = await db.scalar(
        select(WSISlide.case_id)
        .where(WSISlide.dataset_id == dataset.dataset_id)
        .group_by(WSISlide.case_id)
        .having(
            (func.count(func.distinct(WSISlide.split)) > 1)
            | (func.count(func.distinct(WSISlide.label)) > 1)
            | (func.count(func.distinct(WSISlide.event_time)) > 1)
            | (func.count(func.distinct(WSISlide.event_status)) > 1)
        )
        .limit(1)
    )
    if conflict:
        raise HTTPException(
            422, f"Conflicting labels, outcomes or splits within case {conflict}"
        )


async def require_write_scope(db, user, dataset_id, workspace_id):
    await get_dataset_with_access(dataset_id, user, db, require_owner=True)
    from backend.services.workspaces import resolve_scope

    scope = await resolve_scope(db, user, workspace_id)
    if scope.execution_mode == "read_only" or "data" not in scope.enabled_skills:
        raise HTTPException(403, "Workspace does not permit dataset edits")
    if scope.dataset_ids is not None and dataset_id not in scope.dataset_ids:
        raise HTTPException(403, "Dataset is outside the workspace")
    # Serialize concurrent append/metadata edits; re-read revision after locking.
    return (
        await db.execute(
            select(Dataset)
            .where(Dataset.dataset_id == dataset_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


@router.post("")
async def create_dataset(
    body: DatasetCreate,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
    workspace_id: str | None = Header(None, alias="X-Workspace-ID"),
):
    from backend.services.workspaces import resolve_scope

    scope = await resolve_scope(db, user, workspace_id)
    if scope.execution_mode == "read_only" or "data" not in scope.enabled_skills:
        raise HTTPException(403, "Workspace does not permit dataset creation")
    if await db.scalar(
        select(Dataset.id).where(
            Dataset.user_id == str(user.id), Dataset.name == body.name
        )
    ):
        raise HTTPException(409, "A dataset with this name already exists")
    dataset = Dataset(
        dataset_id=str(uuid4()),
        name=body.name,
        description=body.description,
        data_type=body.data_type,
        aggregation_level=body.aggregation_level,
        source_organ=body.source_organ or None,
        metadata_fields=body.metadata,
        user_id=str(user.id),
        is_public=body.is_public,
        tasks=[DatasetTask(task_type=task) for task in body.task_types],
    )
    db.add(dataset)
    await db.flush()
    db.add(DatasetStats(dataset_id=dataset.dataset_id))
    if scope.workspace_id:
        from backend.database.models import Workspace

        workspace = await db.scalar(
            select(Workspace)
            .where(Workspace.workspace_id == scope.workspace_id)
            .with_for_update()
        )
        workspace.dataset_ids = list(
            dict.fromkeys([*workspace.dataset_ids, dataset.dataset_id])
        )
        workspace.version += 1
    await db.commit()
    await invalidate_chat_context(str(user.id))
    return dataset.to_dict()


@router.post("/{dataset_id}/labels")
async def import_labels(
    dataset_id: str,
    body: LabelImport,
    user: User = Depends(current_active_user),
    db=Depends(get_db),
    workspace_id: str | None = Header(None, alias="X-Workspace-ID"),
):
    dataset = await require_write_scope(db, user, dataset_id, workspace_id)
    if dataset.revision != body.revision:
        raise HTTPException(409, "Dataset changed; reload before importing labels")
    if body.properties is not None:
        if (
            body.properties.revision is not None
            and body.properties.revision != body.revision
        ):
            raise HTTPException(409, "Dataset revision does not match the edit")
        await apply_properties(
            db, dataset, body.properties, user=user, defer_visibility=True
        )
    tasks = set(task.task_type for task in dataset.tasks) | set(body.task_types)
    try:
        validate_dataset_tasks(
            dataset.data_type, dataset.aggregation_level, sorted(tasks)
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    names = [row.filename for row in body.rows]
    if len(names) != len(set(names)):
        raise HTTPException(422, "Duplicate filenames in metadata")
    all_names = set(names)
    for task_type, coco in body.annotations.items():
        if task_type not in tasks or task_type not in {
            "patch_segmentation",
            "patch_detection",
        }:
            raise HTTPException(
                422, "Select the matching spatial task before importing annotations"
            )
        if not all(
            isinstance(coco.get(key), list)
            for key in ("images", "annotations", "categories")
        ):
            raise HTTPException(
                422, "Annotations require COCO images, annotations and categories"
            )
        if len(coco["images"]) > 10000 or len(coco["annotations"]) > 1000000:
            raise HTTPException(
                422, "Import at most 10,000 images / 1,000,000 objects per request"
            )
        from backend.ai.utils.detection_dataset import coco_targets

        try:
            coco_targets(coco, [category["name"] for category in coco["categories"]])
            filenames = [image["file_name"] for image in coco["images"]]
            if any(not isinstance(name, str) or not name for name in filenames) or len(
                filenames
            ) != len(set(filenames)):
                raise ValueError("COCO image filenames must be unique and nonempty")
            if task_type == "patch_segmentation" and any(
                not ann.get("segmentation") for ann in coco["annotations"]
            ):
                raise ValueError("Segmentation annotations need polygons or masks")
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        all_names.update(filenames)
    slides = (
        await db.scalars(
            select(WSISlide).where(
                WSISlide.dataset_id == dataset_id,
                WSISlide.original_filename.in_(all_names),
            )
        )
    ).all()
    by_name = {slide.original_filename: slide for slide in slides}
    if len(by_name) != len(slides):
        raise HTTPException(422, "Image filenames are ambiguous in this dataset")
    missing = all_names - by_name.keys()
    if missing:
        raise HTTPException(
            422,
            f"Images not found: {', '.join(sorted(missing)[:10])}. Upload the images first.",
        )
    for row in body.rows:
        slide = by_name[row.filename]
        values = row.model_dump(exclude_unset=True, exclude={"filename"})
        if "label" in values and not any("classification" in task for task in tasks):
            raise HTTPException(422, "Add classification before importing class labels")
        if {
            "event_time",
            "event_status",
        } & values.keys() and "wsi_survival" not in tasks:
            raise HTTPException(422, "Add survival analysis before importing outcomes")
        if ("event_time" in values) != ("event_status" in values):
            raise HTTPException(422, "Import follow-up time and event status together")
        if "metadata" in values:
            metadata = values.pop("metadata")
            if metadata is not None:
                slide.metadata_fields = {
                    **(slide.metadata_fields or {}),
                    **validate_metadata(metadata),
                }
        for key, value in values.items():
            setattr(slide, key, value)
    # All validation and writes are one transaction; other task labels are retained.
    existing = {task.task_type for task in dataset.tasks}
    dataset.tasks.extend(
        DatasetTask(task_type=task) for task in sorted(tasks - existing)
    )
    await db.flush()
    for task_type, coco in body.annotations.items():
        from collections import defaultdict

        by_image = defaultdict(list)
        for annotation in coco["annotations"]:
            by_image[annotation["image_id"]].append(annotation)
        for index, image in enumerate(coco["images"]):
            slide = by_name[image["file_name"]]
            image["wsi_id"] = slide.wsi_id
            if (
                slide.width
                and slide.height
                and (image["width"], image["height"]) != (slide.width, slide.height)
            ):
                raise HTTPException(
                    422, f"Annotation dimensions do not match {slide.original_filename}"
                )
            payload = {
                "images": [image],
                "categories": coco["categories"],
                "annotations": by_image[image["id"]],
            }
            await SegmentationAnnotationRepository.upsert(
                db,
                annotation_id=f"{task_type}_{slide.wsi_id}",
                user_id=str(user.id),
                source_dataset_id=dataset_id,
                task_type=task_type,
                annotations=payload,
                status="finalized",
                source="import",
                refresh_summary=index == len(coco["images"]) - 1,
            )
    dataset.revision += 1
    await db.flush()
    await validate_case_labels(db, dataset)
    await DatasetStatsRepository.recompute(db, dataset_id)
    if body.properties is not None and body.properties.is_public is not None:
        from .dataset_visibility import apply_dataset_visibility

        await apply_dataset_visibility(db, dataset, body.properties.is_public)
    await db.commit()
    await invalidate_chat_context(str(dataset.user_id))
    return {
        "dataset": dataset.to_dict(),
        "updated_images": len(all_names),
        "tasks": (await task_summaries(db, [dataset_id])).get(dataset_id, []),
    }
