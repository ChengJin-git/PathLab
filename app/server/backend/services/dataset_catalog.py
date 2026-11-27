"""Dataset descriptions, supported tasks and task-scoped ground truth."""

from sqlalchemy import select, func
from fastapi import HTTPException
from backend.ai.task_taxonomy import normalize_task_type
from backend.database.models import DatasetTask, WSISlide, SegmentationAnnotation


def validate_metadata(value):
    import json

    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        raise HTTPException(422, "Metadata must contain finite JSON values") from None
    if len(encoded) > 65536:
        raise HTTPException(422, "Metadata exceeds 64 KiB")
    if any(not key.strip() or len(key) > 100 for key in value):
        raise HTTPException(422, "Metadata field names must be 1–100 characters")
    return value


def validate_dataset_tasks(data_type, aggregation_level, task_types):
    if not task_types or len(task_types) != len(set(task_types)):
        raise ValueError("Select one or more distinct tasks")
    for task in task_types:
        canonical = normalize_task_type(
            task_type=task, data_type=data_type, aggregation_level=aggregation_level
        )
        if task != canonical:
            raise ValueError("Use canonical task IDs")
    return task_types


def require_dataset_task(dataset, task_type):
    try:
        validate_dataset_tasks(
            dataset.data_type, dataset.aggregation_level, [task_type]
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if task_type not in {task.task_type for task in dataset.tasks}:
        raise HTTPException(400, "Add this task to the dataset before using its labels")
    return dataset


async def task_summaries(db, dataset_ids):
    if not dataset_ids:
        return {}
    tasks = (
        (
            await db.execute(
                select(DatasetTask).where(DatasetTask.dataset_id.in_(dataset_ids))
            )
        )
        .scalars()
        .all()
    )
    counts = (
        await db.execute(
            select(
                WSISlide.dataset_id,
                func.count(),
                func.count().filter(
                    WSISlide.label.isnot(None), func.trim(WSISlide.label) != ""
                ),
                func.count().filter(
                    WSISlide.event_time.isnot(None), WSISlide.event_status.isnot(None)
                ),
            )
            .where(WSISlide.dataset_id.in_(dataset_ids))
            .group_by(WSISlide.dataset_id)
        )
    ).all()
    count_map = {row[0]: row[1:] for row in counts}
    label_rows = (
        await db.execute(
            select(WSISlide.dataset_id, WSISlide.label)
            .where(
                WSISlide.dataset_id.in_(dataset_ids),
                WSISlide.label.isnot(None),
                func.trim(WSISlide.label) != "",
            )
            .distinct()
        )
    ).all()
    class_map = {}
    for dataset_id, label in label_rows:
        class_map.setdefault(dataset_id, []).append(label)
    output = {}
    for task in tasks:
        total, classification, survival = count_map.get(task.dataset_id, (0, 0, 0))
        labelled = (
            classification
            if "classification" in task.task_type
            else survival
            if "survival" in task.task_type
            else min(total, task.labelled_count)
        )
        output.setdefault(task.dataset_id, []).append(
            {
                "task_type": task.task_type,
                "description": task.description,
                "labelled_count": labelled,
                "sample_count": total,
                "classes": sorted(class_map.get(task.dataset_id, []))
                if "classification" in task.task_type
                else task.classes,
                "status": "unlabelled"
                if not labelled
                else "complete"
                if labelled == total
                else "partial",
            }
        )
    return output


def merge_task_annotations(records):
    """Newest finalized annotation wins per image; other images/classes survive."""
    from pathlib import Path
    from backend.annotation.coco_utils import merge_coco_datasets

    selected, seen = [], set()
    for record in records:
        payload = record.annotations
        if not isinstance(payload, dict):
            continue
        images = []
        for image in payload.get("images", []):
            identity = image.get('wsi_id') or Path(image.get("file_name") or "").name
            if not identity or identity in seen:
                continue
            seen.add(identity)
            images.append(image)
        ids = {image["id"] for image in images}
        if images:
            selected.append(
                {
                    "images": images,
                    "categories": payload.get("categories", []),
                    "annotations": [
                        annotation
                        for annotation in payload.get("annotations", [])
                        if annotation["image_id"] in ids
                    ],
                }
            )
    return merge_coco_datasets(selected)


async def load_task_annotations(db, dataset_id, task_type):
    records = (
        await db.scalars(
            select(SegmentationAnnotation)
            .where(
                SegmentationAnnotation.source_dataset_id == dataset_id,
                SegmentationAnnotation.task_type == task_type,
                SegmentationAnnotation.status == "finalized",
            )
            .order_by(
                SegmentationAnnotation.updated_at.desc(),
                SegmentationAnnotation.id.desc(),
            )
        )
    ).all()
    import asyncio

    return await asyncio.to_thread(merge_task_annotations, records)


async def refresh_spatial_summary(db, dataset_id, task_type):
    """Refresh task counters from effective annotations on images still present."""
    from pathlib import Path
    from sqlalchemy import update

    payload = await load_task_annotations(db, dataset_id, task_type)
    rows=(await db.execute(select(WSISlide.wsi_id,WSISlide.original_filename,WSISlide.wsi_path).where(WSISlide.dataset_id==dataset_id))).all()
    ids={row.wsi_id for row in rows}
    names={Path(name).name for row in rows for name in (row.original_filename,row.wsi_path) if name}
    images = [
        image
        for image in payload["images"]
        if image.get('wsi_id') in ids or Path(image.get("file_name") or "").name in names
    ]
    await db.execute(
        update(DatasetTask)
        .where(DatasetTask.dataset_id == dataset_id, DatasetTask.task_type == task_type)
        .values(
            labelled_count=len(images),
            classes=sorted({category["name"] for category in payload["categories"]}),
        )
    )
