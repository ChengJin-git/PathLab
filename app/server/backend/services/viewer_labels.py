"""Resolve the current reference-label record for a single image and task."""

from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import select, text
from backend.auth.dependencies import get_wsi_with_access
from backend.database.models import SegmentationAnnotation
from backend.annotation.coco_utils import coco_to_roi_annotations


async def resolve_labels(wsi_id, user, db, task_type=None):
    slide = await get_wsi_with_access(wsi_id, user, db, with_dataset=True)
    tasks = (
        [
            task.task_type
            for task in slide.dataset.tasks
            if task.task_type in {"patch_segmentation", "patch_detection"}
        ]
        if slide.dataset
        else []
    )
    task_type = task_type or (tasks[0] if len(tasks) == 1 else "patch_segmentation")
    if task_type not in {"patch_segmentation", "patch_detection"}:
        raise HTTPException(422, "Invalid spatial task")
    payload = {
        "dataset_id": slide.dataset_id,
        "task_type": task_type,
        "annotations": {},
        "record_count": 0,
        "source": "ground_truth",
        "annotation_source": None,
        "width": slide.width,
        "height": slide.height,
    }
    if not slide.dataset_id:
        return slide, None, payload
    names = {Path(slide.original_filename or "").name, Path(slide.wsi_path).name}
    query = select(SegmentationAnnotation).where(
        SegmentationAnnotation.source_dataset_id == slide.dataset_id,
        SegmentationAnnotation.status == "finalized",
        SegmentationAnnotation.task_type == task_type,
    )
    if db.bind.dialect.name == "postgresql":
        query = query.where(
            text(
                "EXISTS (SELECT 1 FROM json_array_elements(segmentation_annotations.annotations->'images') image WHERE image->>'wsi_id'=:sid OR image->>'file_name' IN (:name1,:name2))"
            )
        ).params(
            sid=wsi_id,
            name1=slide.original_filename or "",
            name2=Path(slide.wsi_path).name,
        )
    records = (
        await db.scalars(
            query.order_by(SegmentationAnnotation.updated_at.desc()).limit(20)
        )
    ).all()
    for record in records:
        matching = [
            image
            for image in record.annotations.get("images", [])
            if image.get("wsi_id") == wsi_id
            or Path(image.get("file_name") or "").name in names
        ]
        if not matching:
            continue
        ids = {image["id"] for image in matching}
        filtered = {
            **record.annotations,
            "images": matching,
            "annotations": [
                a
                for a in record.annotations.get("annotations", [])
                if a.get("image_id") in ids
            ],
        }
        lookup = {Path(image["file_name"]).name.lower(): wsi_id for image in matching}
        payload.update(
            annotations=coco_to_roi_annotations(filtered, lookup),
            record_count=1,
            annotation_source="imported_gt"
            if record.source in {"import", "upload"}
            else "user_label",
            width=matching[0].get("width") or slide.width,
            height=matching[0].get("height") or slide.height,
        )
        return slide, record, payload
    return slide, None, payload
