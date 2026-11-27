"""Image-task adapter shared by batch inference and external validation."""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
from PIL import Image

from backend.ai.permission_revocation import is_permission_revoked
from backend.ai.result_store import PRED_MASK_ARTIFACT, AIResultStore
from backend.common.config import Config
from backend.database.database import safe_session
from backend.database.repositories import (
    AIResultRepository,
    SegmentationAnnotationRepository,
    TrainingTaskRepository,
    WSIRepository,
)
from backend.services.research_prediction import ResearchPredictor


def ground_truth_mask(slide, annotations: list[dict], classes: list[str], size):
    from PIL import ImageDraw

    width, height = size
    for coco in annotations:
        category_names = {c["id"]: c["name"] for c in coco.get("categories", [])}
        matches = [
            image
            for image in coco.get("images", [])
            if image.get("wsi_id") == slide.wsi_id
            or (
                not image.get("wsi_id")
                and Path(image.get("file_name", "")).name
                in {slide.original_filename, Path(slide.wsi_path).name}
            )
        ]
        if len(matches) != 1:
            continue
        image = matches[0]
        if (image.get("width", width), image.get("height", height)) != (width, height):
            raise ValueError("Annotation and input image dimensions differ")
        channels = [Image.new("1", (width, height)) for _ in classes]
        for annotation in coco.get("annotations", []):
            if annotation.get("image_id") != image["id"]:
                continue
            name = category_names.get(annotation["category_id"])
            if name not in classes:
                raise ValueError(
                    "Ground-truth category is not in the predictor contract"
                )
            segmentation = annotation["segmentation"]
            if isinstance(segmentation, dict):
                from pycocotools import mask as mask_utils

                if isinstance(segmentation.get("counts"), list):
                    segmentation = mask_utils.frPyObjects(segmentation, height, width)
                decoded = mask_utils.decode(segmentation)
                previous = np.asarray(channels[classes.index(name)], dtype=bool)
                channels[classes.index(name)] = Image.fromarray(
                    (previous | decoded.astype(bool)).astype(np.uint8) * 255
                ).convert("1")
            else:
                for polygon in segmentation:
                    ImageDraw.Draw(channels[classes.index(name)]).polygon(
                        list(zip(polygon[::2], polygon[1::2])), fill=1
                    )
        return np.stack([np.asarray(channel, dtype=np.uint8) for channel in channels])
    return None


def segmentation_metrics(prediction, truth):
    intersection = (prediction.astype(bool) & truth.astype(bool)).sum(axis=(1, 2))
    union = (prediction.astype(bool) | truth.astype(bool)).sum(axis=(1, 2))
    denominator = prediction.sum(axis=(1, 2)) + truth.sum(axis=(1, 2))
    iou = np.divide(intersection, union, out=np.ones(len(union)), where=union > 0)
    dice = np.divide(
        2 * intersection, denominator, out=np.ones(len(union)), where=denominator > 0
    )
    return {
        "iou": float(iou.mean()),
        "miou": float(iou.mean()),
        "dice": float(dice.mean()),
        "iou_per_class": iou.tolist(),
        "dice_per_class": dice.tolist(),
    }


async def run_research_images(
    *,
    task_id,
    model_task_id,
    model_id,
    dataset_id,
    wsi_ids,
    execution_mode,
    auto_trigger_analysis,
    assigned_device,
):
    root = Config.get_uploads_dir()
    if not wsi_ids:
        raise ValueError("Select at least one input image")
    predictor = await asyncio.to_thread(
        ResearchPredictor, root / "models" / model_id, assigned_device or "cpu"
    )
    manifest = predictor.manifest
    if manifest["input_kind"] != "image" or manifest["task_type"] not in {
        "patch_classification",
        "patch_segmentation",
        "patch_detection",
    }:
        predictor.close()
        raise ValueError("This model does not accept patch images")
    segmentation = manifest["task_type"] == "patch_segmentation"
    detection = manifest["task_type"] == "patch_detection"
    try:
        async with safe_session() as db:
            slides = await WSIRepository.get_by_ids(db, wsi_ids)
            task = await TrainingTaskRepository.get_by_id(db, task_id)
            user_id = task.user_id
            annotations = (
                await SegmentationAnnotationRepository.get_all_by_dataset(
                    db, dataset_id, task_type=manifest['task_type']
                )
                if segmentation or detection
                else []
            )
            from backend.services.dataset_catalog import merge_task_annotations
            coco = [merge_task_annotations(annotations)] if annotations else []
            await AIResultRepository.delete_by_task_id(db, task_id)
            await TrainingTaskRepository.update_status(
                db, task_id, "training", progress=1
            )
            await db.commit()
        records = []

        def predict_slide(slide):
            with Image.open(slide.wsi_path) as image:
                rgb = np.asarray(image.convert("RGB"))
            output = predictor.predict_image(rgb)
            result = {
                "wsi_id": slide.wsi_id,
                "task_id": task_id
                if execution_mode == "batch_inference"
                else model_task_id,
                "task_type": manifest["task_type"],
                "aggregation_level": "file",
                "classes": manifest["classes"],
            }
            arrays = {}
            if detection:
                from backend.ai.utils.detection_dataset import coco_targets
                target = None
                for payload in coco:
                    matches = [image for image in payload["images"] if Path(image["file_name"]).name in {slide.original_filename, Path(slide.wsi_path).name}]
                    if len(matches) > 1:
                        raise ValueError("Ambiguous detection annotation filename")
                    if matches:
                        if target is not None:
                            raise ValueError("Multiple ground-truth records for detection image")
                        target = coco_targets(payload, manifest["classes"])[matches[0]["id"]]
                result.update(class_names=manifest["classes"], image_size=[rgb.shape[1], rgb.shape[0]],
                              has_ground_truth=target is not None,
                              detection={"prediction": {k: v.tolist() for k, v in output.items()}, "target": target})
                pred, probs = "detection", None
            elif segmentation:
                mask = output["mask"]
                truth = ground_truth_mask(
                    slide, coco, manifest["classes"], (rgb.shape[1], rgb.shape[0])
                )
                result.update(
                    {
                        "num_classes": len(manifest["classes"]),
                        "class_names": manifest["classes"],
                        "image_size": [rgb.shape[1], rgb.shape[0]],
                        "has_ground_truth": truth is not None,
                        "metrics": segmentation_metrics(mask, truth)
                        if truth is not None
                        else {},
                        "pred_mask_file": None,
                    }
                )
                arrays[PRED_MASK_ARTIFACT] = mask
                if truth is not None:
                    arrays["gt_mask"] = truth
                if "probabilities" in output:
                    from backend.services.result_analysis.segmentation_thresholds import probability_bins, threshold_counts
                    arrays["pred_bins"] = probability_bins(output["probabilities"])
                    result["segmentation_preview"] = True
                    if truth is not None:
                        result["threshold_counts"] = threshold_counts(output["probabilities"], truth)
                pred, probs = "segmentation", result["metrics"]
            else:
                values = output["probabilities"][0]
                pred = manifest["classes"][int(values.argmax())]
                probs = dict(zip(manifest["classes"], values.tolist()))
                result.update(
                    {
                        "pred": pred,
                        "probs": probs,
                        "ground_truth": slide.label,
                        "correct": pred == slide.label if slide.label else None,
                    }
                )
            if execution_mode != "batch_inference":
                result.update(
                    {"validation_source": dataset_id, "validation_task_id": task_id}
                )
            AIResultStore(root).write_wsi_result(
                task_id, slide.wsi_id, result=result, arrays=arrays, finalize=False
            )
            return {
                "wsi_id": slide.wsi_id,
                "task_id": task_id,
                "user_id": user_id,
                "pred": pred,
                "probs": probs,
                "extra_metadata": {
                    **result,
                    "execution_mode": execution_mode,
                    "model_task_id": model_task_id,
                    "dataset_id": dataset_id,
                },
            }

        for index, slide_id in enumerate(wsi_ids):
            if is_permission_revoked(task_id):
                raise PermissionError("Inference permission was revoked")
            if slide_id not in slides:
                raise ValueError("Selected image no longer exists")
            records.append(await asyncio.to_thread(predict_slide, slides[slide_id]))
            async with safe_session() as db:
                await TrainingTaskRepository.update_status(
                    db,
                    task_id,
                    "training",
                    progress=5 + int((index + 1) / len(wsi_ids) * 90),
                )
                await db.commit()
        await asyncio.to_thread(AIResultStore(root).write_task_bundle, task_id=task_id)
        async with safe_session() as db:
            await AIResultRepository.bulk_create(db, records)
            await TrainingTaskRepository.update_status(
                db, task_id, "completed", progress=100
            )
            await db.commit()
        if auto_trigger_analysis and not detection:
            from .inference_external_validation import (
                _auto_trigger_external_validation_analysis,
            )

            await _auto_trigger_external_validation_analysis(
                task_id,
                model_task_id,
                model_id,
                dataset_id,
                metrics=["iou", "dice"] if segmentation else None,
                charts=["per_class_iou", "per_class_dice"] if segmentation else None,
            )
    finally:
        predictor.close()
