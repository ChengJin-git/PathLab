"""
Patch Segmentation Inference

Handles GPU inference for patch-level segmentation tasks, including
Grad-CAM target layer resolution and per-image metric computation.
Extracted from results.py — no logic changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, cast as type_cast

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.config import Config
from backend.database.repositories import WSIRepository

from .analysis_utils import (
    _coerce_str,
    _coerce_str_list,
    _normalize_label_names,
)
from .inference_base import resolve_device

logger = logging.getLogger(__name__)


def _get_seg_grad_cam_target_layers(model):
    """Determine the target layer for Grad-CAM in a segmentation model.

    Supports:
    - FMSegmentationModel: uses last decoder block (before head)
    - SMP models (UNet, etc.): uses last decoder block
    """
    import torch.nn as nn
    from backend.ai.segmentors.fm_segmentation_model import FMSegmentationModel

    if isinstance(model, FMSegmentationModel):
        # FM model: decoder is nn.Sequential of _DecoderBlock
        return [model.decoder[-1]]

    # SMP models: try common decoder structures
    if hasattr(model, "decoder"):
        dec = model.decoder
        if hasattr(dec, "blocks") and len(dec.blocks) > 0:
            return [dec.blocks[-1]]
        # Fallback: last child of decoder
        children = list(dec.children())
        if children:
            return [children[-1]]

    # Last resort: find the last Conv2d layer before segmentation_head
    if hasattr(model, "segmentation_head"):
        return [model.segmentation_head[0]]

    raise ValueError("Cannot determine Grad-CAM target layer for segmentation model")


def _build_segmentation_per_image_metrics(
    iou_per_class,
    dice_per_class,
    precision_per_class,
    recall_per_class,
    accuracy,
    precision,
    recall,
) -> Dict[str, Any]:
    iou_flat = (
        iou_per_class.squeeze(0)
        if getattr(iou_per_class, "dim", lambda: 0)() > 1
        else iou_per_class
    )
    dice_flat = (
        dice_per_class.squeeze(0)
        if getattr(dice_per_class, "dim", lambda: 0)() > 1
        else dice_per_class
    )
    precision_flat = (
        precision_per_class.squeeze(0)
        if getattr(precision_per_class, "dim", lambda: 0)() > 1
        else precision_per_class
    )
    recall_flat = (
        recall_per_class.squeeze(0)
        if getattr(recall_per_class, "dim", lambda: 0)() > 1
        else recall_per_class
    )
    num_classes = int(iou_flat.numel()) if hasattr(iou_flat, "numel") else len(iou_flat)
    primary_iou_key = "miou" if num_classes > 1 else "iou"

    precision_value = precision.item()
    recall_value = recall.item()
    f1_value = (
        (2 * precision_value * recall_value / (precision_value + recall_value))
        if (precision_value + recall_value) > 0
        else 0.0
    )

    return {
        primary_iou_key: iou_flat.mean().item(),
        "iou_per_class": iou_flat.tolist() if iou_flat.dim() > 0 else [iou_flat.item()],
        "dice": dice_flat.mean().item(),
        "dice_per_class": dice_flat.tolist()
        if dice_flat.dim() > 0
        else [dice_flat.item()],
        "f1": f1_value,
        "f1_per_class": dice_flat.tolist()
        if dice_flat.dim() > 0
        else [dice_flat.item()],
        "accuracy": accuracy.item(),
        "precision": precision_value,
        "precision_per_class": precision_flat.tolist()
        if precision_flat.dim() > 0
        else [precision_flat.item()],
        "recall": recall_value,
        "recall_per_class": recall_flat.tolist()
        if recall_flat.dim() > 0
        else [recall_flat.item()],
    }


async def _run_inference_patch_segmentation(
    task,
    wsi_ids: List[str],
    resources: dict[str, Any],
    db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None,
    assigned_device: Optional[str] = None,
):
    """
    Run GPU inference to generate per-WSI AI results for patch segmentation task.

    Loads the segmentation model from TrainedModel checkpoint, runs inference on
    each image, computes per-image segmentation metrics (IoU, Dice, etc.) when
    ground truth annotations are available, and saves AIResult records to the
    database — achieving parity with patch classification tasks.

    Args:
        progress_callback: Optional async callback for progress updates (0.0 to 1.0)
    """
    import torch
    import numpy as np
    import segmentation_models_pytorch as smp
    from backend.ai.segmentors import Segmentor
    from backend.ai.utils.patch_resize import resolve_patch_resize_size
    from backend.ai.utils.segmentation_dataset import (
        SegmentationDataset,
        get_transforms,
    )
    from backend.database.repositories import AIResultRepository, TrainedModelRepository
    from PIL import Image
    from torchvision.transforms import v2

    task_id = task.task_id
    uploads_dir = Config.get_uploads_dir()

    # Load model from TrainedModel table
    trained_models = await TrainedModelRepository.get_by_task_id(db, task_id)
    if not trained_models:
        raise ValueError(f"No trained model found for segmentation task {task_id}")
    trained_model = trained_models[0]  # Most recent
    checkpoint_path = _coerce_str(trained_model.model_path)
    class_names = _normalize_label_names(
        _coerce_str_list(task.classes or trained_model.classes or [])
    )

    device = resolve_device(assigned_device)

    logger.info(f"Loading segmentation model from {checkpoint_path}")

    def _load_model():
        checkpoint = torch.load(
            checkpoint_path, map_location=device, weights_only=False
        )
        config = checkpoint.get("config", {})
        architecture = config.get("architecture", "unet")
        backbone = config.get("backbone", "resnet50")
        dataset_cfg = config.get("dataset", {})
        in_channels = dataset_cfg.get("channels", 3)
        num_classes = dataset_cfg.get("classes", 1)

        segmentor = Segmentor(
            architecture=architecture,
            encoder_name=backbone,
            in_channels=in_channels,
            classes=num_classes,
        )
        model = type_cast("Any", segmentor.build_model())
        if checkpoint.get("is_fm", False):
            model.load_decoder_state_dict(checkpoint["model_state_dict"])
        else:
            model.load_state_dict(checkpoint["model_state_dict"])
        model = model.to(device)
        model.eval()

        norm_mean, norm_std = segmentor.get_normalization_params()
        resize_size = resolve_patch_resize_size(backbone, is_segmentation_backbone=True)
        return model, config, norm_mean, norm_std, num_classes, resize_size

    (
        model,
        model_config,
        norm_mean,
        norm_std,
        num_classes,
        resize_size,
    ) = await asyncio.to_thread(_load_model)
    if not class_names:
        class_names = _normalize_label_names(
            (model_config.get("dataset") or {}).get("class_names", [])
        )

    if progress_callback:
        await progress_callback(0.1)

    # Build image paths and labels from WSI records
    image_paths: Dict[str, str] = {}
    for wsi_id in wsi_ids:
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if wsi is not None:
            wsi_path = _coerce_str(wsi.wsi_path)
            if wsi_path:
                image_paths[wsi_id] = wsi_path

    if not image_paths:
        raise ValueError(f"No image paths found for segmentation task {task_id}")

    # Delete old AIResult records to avoid duplicates
    deleted_count = await AIResultRepository.delete_by_task_id(db, task_id)
    if deleted_count > 0:
        logger.info(f"Deleted {deleted_count} old AIResult records for task {task_id}")

    def _resolve_annotations_from_config() -> tuple[Optional[str], Optional[str]]:
        test_cfg = (model_config.get("dataset") or {}).get("test", {})
        ann_path = test_cfg.get("annotations_path")
        img_dir = test_cfg.get("image_dir")
        if ann_path and Path(ann_path).exists():
            return ann_path, img_dir
        return None, None

    def _discover_annotations() -> tuple[Optional[str], Optional[str]]:
        from pathlib import Path as _Path

        image_dirs = set()
        for img_path in image_paths.values():
            image_dirs.add(str(_Path(img_path).parent))
        for img_dir in image_dirs:
            dir_path = _Path(img_dir)
            for search_dir in [dir_path, dir_path.parent]:
                if not search_dir.exists():
                    continue
                for json_file in search_dir.glob("*.json"):
                    try:
                        with open(json_file, "r") as f:
                            data = json.load(f)
                        if (
                            "images" in data
                            and "annotations" in data
                            and "categories" in data
                        ):
                            return str(json_file), img_dir
                    except Exception:
                        continue
        return None, None

    annotations_path, annotations_img_dir = _resolve_annotations_from_config()
    if annotations_path:
        logger.info(
            f"Using test-split annotations from model config: {annotations_path}"
        )
    else:
        annotations_path, annotations_img_dir = await asyncio.to_thread(
            _discover_annotations
        )
        if annotations_path:
            logger.info(
                f"Found COCO annotations via filesystem scan: {annotations_path}"
            )
        else:
            logger.info(
                "No COCO annotations found — running inference only (no per-image metrics)"
            )
    has_annotations = annotations_path is not None

    # Run inference
    val_transform = get_transforms(
        "val",
        size=(resize_size, resize_size),
        normalization_mean=norm_mean,
        normalization_std=norm_std,
    )
    ai_results_root = uploads_dir / "ai_results"
    results_saved = 0
    total_items = len(image_paths)

    def _run_inference():
        nonlocal results_saved
        from pathlib import Path as _Path

        all_results = []

        # Build ground truth dataset if annotations available
        gt_dataset = None
        gt_filename_map = {}
        if has_annotations:
            try:
                gt_dataset = SegmentationDataset(
                    img_dir=annotations_img_dir,
                    annotations_path=annotations_path,
                    transform=val_transform,
                )
                for idx, item in enumerate(gt_dataset.image_items):
                    fname = _Path(item["image"]).name
                    gt_filename_map[fname] = idx
            except Exception as e:
                logger.warning(f"Failed to load annotation dataset: {e}")
                gt_dataset = None

        with torch.no_grad():
            for idx, (wsi_id, img_path) in enumerate(image_paths.items()):
                try:
                    img = Image.open(img_path).convert("RGB")
                    original_size = img.size  # (W, H)
                    img_filename = _Path(img_path).name

                    # Prepare image tensor
                    img_tensor = v2.ToImage()(img)
                    img_tensor = val_transform(img_tensor)
                    img_tensor = type_cast("Any", img_tensor).unsqueeze(0).to(device)

                    # Run inference
                    outputs = model(img_tensor)
                    preds_prob = torch.sigmoid(outputs)
                    preds_binary = (preds_prob > 0.5).float()

                    # Compute per-image metrics if ground truth is available
                    per_image_metrics = {}
                    has_gt = False
                    if gt_dataset is not None and img_filename in gt_filename_map:
                        gt_idx = gt_filename_map[img_filename]
                        _, gt_mask = gt_dataset[gt_idx]
                        gt_mask = type_cast("Any", gt_mask).unsqueeze(0).to(device)
                        has_gt = True

                        tp, fp, fn, tn = smp.metrics.get_stats(
                            type_cast("Any", preds_binary.long().cpu()),
                            type_cast("Any", gt_mask.long().cpu()),
                            mode="multilabel",
                            threshold=None,
                        )
                        iou_per_class = smp.metrics.iou_score(
                            tp, fp, fn, tn, reduction="none"
                        )
                        dice_per_class = smp.metrics.f1_score(
                            tp, fp, fn, tn, reduction="none"
                        )
                        precision_per_class = smp.metrics.precision(
                            tp, fp, fn, tn, reduction="none"
                        )
                        recall_per_class = smp.metrics.recall(
                            tp, fp, fn, tn, reduction="none"
                        )
                        accuracy = smp.metrics.accuracy(
                            tp, fp, fn, tn, reduction="micro"
                        )
                        precision_val = smp.metrics.precision(
                            tp, fp, fn, tn, reduction="micro"
                        )
                        recall_val = smp.metrics.recall(
                            tp, fp, fn, tn, reduction="micro"
                        )

                        per_image_metrics = _build_segmentation_per_image_metrics(
                            iou_per_class,
                            dice_per_class,
                            precision_per_class,
                            recall_per_class,
                            accuracy,
                            precision_val,
                            recall_val,
                        )

                    # Save prediction mask
                    wsi_result_dir = ai_results_root / wsi_id
                    wsi_result_dir.mkdir(parents=True, exist_ok=True)

                    # Keep segmentation artifacts streamed to disk during inference to avoid
                    # retaining many large masks/CAMs in memory. Store binary masks as uint8
                    # to reduce write volume without changing viewer semantics.
                    pred_mask = (
                        preds_binary.squeeze(0).to(dtype=torch.uint8).cpu().numpy()
                    )
                    mask_file = wsi_result_dir / f"train_{task_id}_pred_mask.npy"
                    np.save(mask_file, pred_mask)

                    # Extract Grad-CAM for segmentation model
                    try:
                        from pytorch_grad_cam import GradCAM
                        from pytorch_grad_cam.utils.model_targets import (
                            SemanticSegmentationTarget,
                        )

                        # Determine target layer based on model type
                        target_layers = _get_seg_grad_cam_target_layers(model)

                        # Use dominant predicted class for Grad-CAM target
                        pred_mask_for_cam = pred_mask.astype(
                            np.float32, copy=False
                        )  # (C, H, W)
                        if (
                            pred_mask_for_cam.ndim == 3
                            and pred_mask_for_cam.shape[0] > 1
                        ):
                            dominant_class = int(
                                pred_mask_for_cam.sum(axis=(1, 2)).argmax()
                            )
                        else:
                            dominant_class = 0
                        sem_mask = pred_mask_for_cam[dominant_class]  # (H, W) binary

                        targets = [
                            type_cast(
                                "Any",
                                SemanticSegmentationTarget(dominant_class, sem_mask),
                            )
                        ]
                        cam_input = img_tensor.clone().detach().requires_grad_(True)

                        with torch.enable_grad():
                            with GradCAM(
                                model=model, target_layers=target_layers
                            ) as grad_cam:
                                cam_map = grad_cam(
                                    input_tensor=cam_input, targets=targets
                                )
                        cam_map = cam_map[0]  # (H, W)
                    except Exception as cam_err:
                        logger.warning(
                            f"Grad-CAM extraction failed for {wsi_id}: {cam_err}"
                        )
                        cam_map = np.zeros(
                            (img_tensor.shape[2], img_tensor.shape[3]), dtype=np.float32
                        )

                    cam_file = wsi_result_dir / f"train_{task_id}_cam.npy"
                    np.save(cam_file, cam_map)

                    # Save result JSON
                    result_data = {
                        "wsi_id": wsi_id,
                        "task_id": task_id,
                        "task_type": "patch_segmentation",
                        "aggregation_level": "file",
                        "num_classes": num_classes,
                        "class_names": class_names,
                        "image_size": list(original_size),
                        "pred_mask_file": str(mask_file),
                        "cam_file": str(cam_file),
                        "cam_size": list(cam_map.shape),
                        "has_ground_truth": has_gt,
                        "metrics": per_image_metrics,
                    }
                    result_file = wsi_result_dir / f"train_{task_id}_result.json"
                    with open(result_file, "w", encoding="utf-8") as f:
                        json.dump(result_data, f, ensure_ascii=False, indent=2)

                    all_results.append(
                        {
                            "wsi_id": wsi_id,
                            "metrics": per_image_metrics,
                            "has_ground_truth": has_gt,
                            "class_names": class_names,
                            "num_classes": num_classes,
                            "image_size": list(original_size),
                            "pred_mask_file": str(mask_file),
                            "result_file": str(result_file),
                        }
                    )
                    results_saved += 1

                except Exception as e:
                    logger.warning(f"Failed to process {wsi_id}: {e}")
                    continue

        return all_results

    all_results = await asyncio.to_thread(_run_inference)

    if progress_callback:
        await progress_callback(0.8)

    # Save to database in batches to reduce write-transaction churn.
    db_records = []
    for r in all_results:
        db_records.append(
            {
                "wsi_id": r["wsi_id"],
                "task_id": task_id,
                "pred": "segmentation",
                "probs": r["metrics"] if r["metrics"] else {},
                "extra_metadata": {
                    "task_type": "patch_segmentation",
                    "aggregation_level": "file",
                    "has_ground_truth": r["has_ground_truth"],
                    "class_names": r.get("class_names", []),
                    "num_classes": r.get("num_classes"),
                    "image_size": r.get("image_size"),
                    "metrics": r["metrics"],
                    "pred_mask_file": r["pred_mask_file"],
                    "result_file": r["result_file"],
                },
            }
        )

    if db_records:
        await AIResultRepository.bulk_create(db, db_records, batch_size=100)

    await db.commit()

    logger.info(
        f"Generated AI results for patch segmentation task {task_id}: {results_saved}/{total_items} images"
    )

    if progress_callback:
        await progress_callback(1.0)

    return {
        "message": "AI results generated successfully",
        "task_id": task_id,
        "task_type": "patch_segmentation",
        "wsi_count": results_saved,
    }
