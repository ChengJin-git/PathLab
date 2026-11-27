"""Add selected viewer objects to reference labels without discarding existing labels."""

from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import select
from backend.annotation.coco_utils import roi_annotations_to_coco, merge_coco_datasets
from backend.database.models import Dataset, DatasetTask, ViewerRegion
from backend.database.repositories import (
    SegmentationAnnotationRepository,
    AnnotationAuditLogRepository,
)
from . import viewer_annotations as annotations
from .dataset_access import can_manage_dataset


async def publish(db, user, wsi_id, body):
    from .viewer_labels import resolve_labels

    slide = await annotations.slide_access(db, user, wsi_id, body.layer)
    if not slide.dataset or not await can_manage_dataset(db, user, slide.dataset):
        raise HTTPException(403, "Management access required")
    if slide.data_type != "patch":
        raise HTTPException(
            422, "Extract regions as patches before publishing spatial labels"
        )
    dataset = await db.scalar(
        select(Dataset).where(Dataset.dataset_id == slide.dataset_id).with_for_update()
    )
    rows = (
        await db.scalars(
            select(ViewerRegion)
            .where(
                *annotations.region_scope(user, wsi_id, body.layer),
                ViewerRegion.region_id.in_([r.id for r in body.regions]),
                ViewerRegion.deleted.is_(False),
            )
            .order_by(ViewerRegion.region_id)
            .with_for_update()
        )
    ).all()
    revisions = {r.id: r.revision for r in body.regions}
    if len(rows) != len(revisions) or any(
        r.revision != revisions[r.region_id] for r in rows
    ):
        raise HTTPException(409, "Selected regions changed")
    _, existing, _ = await resolve_labels(wsi_id, user, db, body.task_type)
    name = slide.original_filename or Path(slide.wsi_path).name
    coco = roi_annotations_to_coco(
        {wsi_id: [annotations.serialize(r) for r in rows]},
        {wsi_id: {"width": slide.width, "height": slide.height, "file_name": name}},
    )
    coco["images"][0]["wsi_id"] = wsi_id
    for value, row in zip(coco["annotations"], rows):
        value["viewer_region_id"] = row.region_id
    if existing:
        previous = existing.annotations
        images = [
            image
            for image in previous.get("images", [])
            if image.get("wsi_id") == wsi_id
            or Path(image.get("file_name") or "").name
            in {name, Path(slide.wsi_path).name}
        ]
        image_ids = {image["id"] for image in images}
        retained = {
            "images": images,
            "categories": previous.get("categories", []),
            "annotations": [
                item
                for item in previous.get("annotations", [])
                if item["image_id"] in image_ids
                and item.get("viewer_region_id") not in revisions
            ],
        }
        merged = merge_coco_datasets([retained, coco])
        for item in merged["annotations"]:
            item["image_id"] = 1
        coco = {**merged, "images": [{**coco["images"][0], "id": 1}]}
    if not any(task.task_type == body.task_type for task in dataset.tasks):
        dataset.tasks.append(DatasetTask(task_type=body.task_type))
    await db.flush()
    await SegmentationAnnotationRepository.upsert(
        db,
        annotation_id=f"{body.task_type}_{wsi_id}",
        user_id=dataset.user_id,
        annotations=coco,
        source_dataset_id=dataset.dataset_id,
        source="viewer",
        task_type=body.task_type,
    )
    await AnnotationAuditLogRepository.log(
        db,
        dataset.dataset_id,
        str(user.id),
        "promoted_to_training_reference",
        {"wsi_id": wsi_id, "region_ids": list(revisions), "task_type": body.task_type},
    )
    dataset.revision += 1
    await db.commit()
    return {"count": len(rows)}
