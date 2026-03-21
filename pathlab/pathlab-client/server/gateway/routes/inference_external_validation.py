"""
External Validation Inference

Handles GPU inference for external validation tasks across all task types
(patch classification, patch segmentation, WSI classification, WSI survival).
Also contains _auto_trigger_external_validation_analysis which chains inference
with the analysis pipeline.
Extracted from results.py — no logic changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, cast as type_cast

from sqlalchemy import update as sql_update

from backend.ai.schemas.base import TaskStatus
from backend.common.config import Config
from backend.database.models import TrainingTask
from backend.database.repositories import (
    AIResultRepository,
    DatasetRepository,
    TrainedModelRepository,
    TrainingTaskRepository,
    WSIRepository,
)
from backend.preprocessing.heatmap_preview_cache import (
    ensure_recommendation_preview_cache,
)

from .analysis_helpers import (
    _coerce_str,
    _coerce_str_list,
    _normalize_label_names,
    _split_case_attention_to_slides_static,
)
from .analysis_state import get_analysis_state
from .inference_patch_segmentation import (
    _build_segmentation_per_image_metrics,
    _get_seg_grad_cam_target_layers,
)

logger = logging.getLogger(__name__)


async def _run_external_validation_patch_segmentation(
    task_id: str,
    model_task_id: str,
    model_id: str,
    dataset_id: str,
    wsi_ids: List[str],
    assigned_device: str,
    logger_manager,
    update_task_progress,
):
    """Run external validation for patch segmentation models.

    Loads the segmentation model from checkpoint, discovers COCO annotations
    for the target dataset, runs inference, computes segmentation metrics
    (IoU, Dice, Accuracy, etc.), and saves per-image results.
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
    from backend.database.repositories import WSIRepository, TrainedModelRepository
    from backend.database.database import safe_session
    from backend.common.progress_store import clear_progress
    from backend.ai.permission_revocation import (
        is_permission_revoked,
        clear_revocation,
        PermissionRevokedException,
    )

    uploads_dir = Config.get_uploads_dir()
    device = (
        assigned_device
        if assigned_device
        else ("cuda" if torch.cuda.is_available() else "cpu")
    )

    try:
        # 1. Load model checkpoint and rebuild model
        async with safe_session() as db:
            trained_model = await TrainedModelRepository.get_by_id(db, model_id)
            if not trained_model:
                raise ValueError(f"Trained model not found: {model_id}")
            checkpoint_path = trained_model.model_path
            source_task = (
                await TrainingTaskRepository.get_by_id(db, model_task_id)
                if model_task_id
                else None
            )

        async with logger_manager.session() as (tl, _db):
            await tl.info(f"Patch segmentation: loading model from {checkpoint_path}")

        def _load_model():
            checkpoint = torch.load(
                _coerce_str(checkpoint_path), map_location=device, weights_only=False
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
            # FM-based checkpoints contain only decoder+head weights;
            # the frozen backbone is already loaded by build_model().
            if checkpoint.get("is_fm", False):
                model.load_decoder_state_dict(checkpoint["model_state_dict"])
            else:
                model.load_state_dict(checkpoint["model_state_dict"])
            model = model.to(device)
            model.eval()

            norm_mean, norm_std = segmentor.get_normalization_params()
            resize_size = resolve_patch_resize_size(
                backbone, is_segmentation_backbone=True
            )
            return model, config, norm_mean, norm_std, num_classes, resize_size

        (
            model,
            model_config,
            norm_mean,
            norm_std,
            num_classes,
            resize_size,
        ) = await asyncio.to_thread(_load_model)
        class_names = _normalize_label_names(
            _coerce_str_list(
                (source_task.classes if source_task else None)
                or trained_model.classes
                or (model_config.get("dataset") or {}).get("class_names", [])
            )
        )

        await update_task_progress(TaskStatus.PATCHING, 10)
        if is_permission_revoked(task_id):
            raise PermissionRevokedException(f"Permission revoked for task {task_id}")

        # 2. Get image paths and discover annotations from target dataset
        image_paths: Dict[str, str] = {}
        task_user_id = None
        async with safe_session() as db:
            for wsi_id in wsi_ids:
                wsi = await WSIRepository.get_by_id(db, wsi_id)
                if wsi is not None:
                    wsi_path = _coerce_str(wsi.wsi_path)
                    if wsi_path:
                        image_paths[wsi_id] = wsi_path

            task_record = await TrainingTaskRepository.get_by_id(db, task_id)
            task_user_id = (
                str(task_record.user_id)
                if isinstance(task_record, TrainingTask)
                and isinstance(task_record.user_id, str)
                else None
            )

            survival_data: Dict[str, Dict[str, Any]] = {}
            labels: Dict[str, int] = {}

        if not image_paths:
            raise ValueError("No image paths found for target WSIs")

        # Discover COCO annotation files by scanning image directories
        def _discover_annotations():
            """Search for COCO-format JSON annotation files near image directories."""
            from pathlib import Path as _Path

            image_dirs = set()
            for img_path in image_paths.values():
                image_dirs.add(str(_Path(img_path).parent))

            for img_dir in image_dirs:
                dir_path = _Path(img_dir)
                # Search in the image directory and its parent
                search_dirs = [dir_path, dir_path.parent]
                for search_dir in search_dirs:
                    if not search_dir.exists():
                        continue
                    for json_file in search_dir.glob("*.json"):
                        try:
                            with open(json_file, "r") as f:
                                data = json.load(f)
                            # Validate it's a COCO-format annotation file
                            if (
                                "images" in data
                                and "annotations" in data
                                and "categories" in data
                            ):
                                return str(json_file), img_dir
                        except Exception:
                            continue
            return None, None

        annotations_path, annotations_img_dir = await asyncio.to_thread(
            _discover_annotations
        )

        has_annotations = annotations_path is not None

        async with logger_manager.session() as (tl, _db):
            if has_annotations:
                await tl.info(f"Found COCO annotations: {annotations_path}")
            else:
                await tl.info(
                    "No COCO annotations found for target dataset — running inference only (no metrics)"
                )
            await tl.info(f"Running inference on {len(image_paths)} images")

        await update_task_progress(TaskStatus.PATCHING, 20)

        # 3. Build dataset and run inference
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
            from torch.cuda.amp import autocast
            from PIL import Image
            from torchvision.transforms import v2
            from torchvision import tv_tensors

            all_results = []

            # If we have annotations, build a SegmentationDataset for ground truth
            gt_dataset = None
            gt_filename_map = {}  # filename -> dataset index
            if has_annotations:
                try:
                    gt_dataset = SegmentationDataset(
                        img_dir=annotations_img_dir,
                        annotations_path=annotations_path,
                        transform=val_transform,
                    )
                    # Build filename -> index map
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
                        img_tensor = (
                            type_cast("Any", img_tensor).unsqueeze(0).to(device)
                        )

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

                            # Compute metrics using SMP
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
                            precision = smp.metrics.precision(
                                tp, fp, fn, tn, reduction="micro"
                            )
                            recall = smp.metrics.recall(
                                tp, fp, fn, tn, reduction="micro"
                            )

                            per_image_metrics = _build_segmentation_per_image_metrics(
                                iou_per_class,
                                dice_per_class,
                                precision_per_class,
                                recall_per_class,
                                accuracy,
                                precision,
                                recall,
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
                        mask_file = wsi_result_dir / f"extval_{task_id}_pred_mask.npy"
                        np.save(mask_file, pred_mask)

                        # Extract Grad-CAM for segmentation model
                        try:
                            from pytorch_grad_cam import GradCAM
                            from pytorch_grad_cam.utils.model_targets import (
                                SemanticSegmentationTarget,
                            )

                            target_layers = _get_seg_grad_cam_target_layers(model)

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
                            sem_mask = pred_mask_for_cam[
                                dominant_class
                            ]  # (H, W) binary

                            targets = [
                                type_cast(
                                    "Any",
                                    SemanticSegmentationTarget(
                                        dominant_class, sem_mask
                                    ),
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
                                (img_tensor.shape[2], img_tensor.shape[3]),
                                dtype=np.float32,
                            )

                        cam_file = wsi_result_dir / f"extval_{task_id}_cam.npy"
                        np.save(cam_file, cam_map)

                        # Save result JSON
                        result_data = {
                            "wsi_id": wsi_id,
                            "task_id": model_task_id,
                            "validation_source": dataset_id,
                            "validation_task_id": task_id,
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

                        result_file = wsi_result_dir / f"extval_{task_id}_result.json"
                        with open(result_file, "w", encoding="utf-8") as f:
                            json.dump(result_data, f, ensure_ascii=False, indent=2)

                        all_results.append(
                            {
                                "wsi_id": wsi_id,
                                "metrics": per_image_metrics,
                                "has_ground_truth": has_gt,
                                "class_names": class_names,
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
        if is_permission_revoked(task_id):
            raise PermissionRevokedException(f"Permission revoked for task {task_id}")

        # 4. Save to database
        async with safe_session() as db:
            from backend.database.repositories import AIResultRepository

            db_records = []
            for r in all_results:
                db_records.append(
                    {
                        "wsi_id": r["wsi_id"],
                        "task_id": task_id,
                        "user_id": task_user_id,
                        "pred": "segmentation",
                        "probs": r["metrics"] if r["metrics"] else {},
                        "extra_metadata": {
                            "validation_type": "external",
                            "model_task_id": model_task_id,
                            "dataset_id": dataset_id,
                            "aggregation_level": "file",
                            "task_type": "patch_segmentation",
                            "has_ground_truth": r["has_ground_truth"],
                            "class_names": r.get("class_names", []),
                            "metrics": r["metrics"],
                            "pred_mask_file": r["pred_mask_file"],
                            "result_file": r["result_file"],
                        },
                    }
                )

            if db_records:
                await AIResultRepository.bulk_create(db, db_records, batch_size=100)
            await db.commit()

        await clear_progress(task_id)
        await update_task_progress(
            TaskStatus.COMPLETED, 100, results_saved, results_saved
        )

        async with logger_manager.session() as (tl, _db):
            await tl.info(
                f"Patch segmentation external validation completed: {results_saved}/{total_items} images processed"
            )

        # Auto-trigger analysis
        await _auto_trigger_external_validation_analysis(
            task_id=task_id,
            model_task_id=model_task_id,
            model_id=model_id,
            dataset_id=dataset_id,
            metrics=["iou", "dice", "accuracy", "precision", "recall"],
            charts=["per_class_iou", "per_class_dice"],
        )

    except Exception as e:
        import traceback

        logger.error(
            f"Patch segmentation external validation {task_id} failed: {e}\n{traceback.format_exc()}"
        )
        try:
            await clear_progress(task_id)
            async with logger_manager.session() as (tl, _db):
                await tl.error(f"Patch segmentation external validation failed: {e}")
        except Exception:
            pass
        await update_task_progress(TaskStatus.FAILED, 0, error_msg=str(e))
    finally:
        clear_revocation(task_id)
        try:
            import gc

            gc.collect()
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception as cleanup_err:
            logger.warning(
                f"Patch seg ext-val {task_id}: VRAM cleanup failed: {cleanup_err}"
            )


async def _run_external_validation_patch_classification(
    task_id: str,
    model_task_id: str,
    model_id: str,
    model_classes: List[str],
    dataset_id: str,
    wsi_ids: List[str],
    assigned_device: str,
    logger_manager,
    update_task_progress,
):
    """Run external validation for patch classification models.

    Loads the feature extractor + linear probe, runs inference on each image,
    generates CAM heatmaps, and saves results. Pattern follows
    _run_inference_patch_classification but adapted for external validation context.
    """
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import numpy as np
    from PIL import Image
    from backend.ai.extractors import get_extractor
    from backend.ai.utils.patch_resize import (
        build_patch_classification_transform,
        resolve_patch_resize_size,
    )
    from backend.ai.utils.cam_utils import (
        get_cam_extractor,
        get_cam_spatial_size,
        is_cnn_extractor,
    )
    from backend.database.repositories import AIResultRepository, WSIRepository
    from backend.database.database import safe_session
    from backend.common.progress_store import clear_progress
    from backend.ai.permission_revocation import (
        is_permission_revoked,
        clear_revocation,
        PermissionRevokedException,
    )

    uploads_dir = Config.get_uploads_dir()
    device = (
        assigned_device
        if assigned_device
        else ("cuda" if torch.cuda.is_available() else "cpu")
    )

    try:
        # Load model checkpoint(s)
        model_dir = uploads_dir / "models" / model_id
        config_path = model_dir / "config.json"

        config = {}
        if config_path.exists():
            with open(config_path, "r") as f:
                config = json.load(f)

        classes = model_classes or config.get("classes", [])
        if not classes:
            raise ValueError("Could not determine model classes")

        is_kfold = config.get("split_type") == "kfold"
        num_folds = config.get("num_folds", 5) if is_kfold else 1

        async with logger_manager.session() as (tl, _db):
            kfold_msg = f" (k-fold: {num_folds} folds)" if is_kfold else ""
            await tl.info(
                f"Patch classification: loading model {model_id} with {len(classes)} classes{kfold_msg}"
            )

        # Load checkpoint(s) and build model(s) (in thread to avoid blocking event loop)
        def _load_models():
            _extractor_name = config.get("extractor", "resnet50")
            _models = []

            if is_kfold:
                # K-fold: load each fold's linear_probe and build a combined model
                for fold_idx in range(num_folds):
                    fold_ckpt_path = model_dir / f"fold_{fold_idx}" / "linear_probe.pth"
                    if not fold_ckpt_path.exists():
                        raise FileNotFoundError(
                            f"Fold {fold_idx} checkpoint not found: {fold_ckpt_path}"
                        )

                    checkpoint = torch.load(fold_ckpt_path, map_location=device)
                    # K-fold checkpoints use "feature_dim" instead of "extractor_dim"
                    extractor_dim = checkpoint.get("feature_dim") or checkpoint.get(
                        "extractor_dim"
                    )
                    _num_classes = checkpoint["num_classes"]

                    fold_probe = nn.Linear(extractor_dim, _num_classes).to(device)
                    fold_probe.load_state_dict(checkpoint["state_dict"])
                    fold_probe.eval()
                    _models.append(fold_probe)
            else:
                # Regular: single checkpoint at root
                ckpt_path = model_dir / "linear_probe.pth"
                if not ckpt_path.exists():
                    raise FileNotFoundError(
                        f"Model checkpoint (linear_probe.pth) not found at {ckpt_path}"
                    )

                checkpoint = torch.load(ckpt_path, map_location=device)
                _extractor_name = checkpoint.get("extractor_name", _extractor_name)
                extractor_dim = checkpoint.get("extractor_dim") or checkpoint.get(
                    "feature_dim"
                )
                _num_classes = checkpoint["num_classes"]

                probe = nn.Linear(extractor_dim, _num_classes).to(device)
                probe.load_state_dict(checkpoint["state_dict"])
                probe.eval()
                _models.append(probe)

            # Build shared extractor (frozen, shared across all folds)
            try:
                _extractor = get_extractor(_extractor_name, pretrained=True)
            except (FileNotFoundError, OSError, Exception) as exc:
                raise RuntimeError(
                    f"Failed to load feature extractor '{_extractor_name}'. "
                    f"Please ensure the model weights are downloaded locally. "
                    f"Original error: {exc}"
                ) from exc
            _extractor = _extractor.to(device)
            _extractor.eval()

            return _extractor, _models, _extractor_name

        extractor, linear_probes, extractor_name = await asyncio.to_thread(_load_models)

        # Match patch-classification training preprocessing.
        target_size = resolve_patch_resize_size(extractor_name)
        fm_transform = build_patch_classification_transform(
            extractor, target_size, mode="eval"
        )
        cam_extractor = get_cam_extractor(extractor_name)
        cam_size = get_cam_spatial_size(extractor_name)
        use_gradients = is_cnn_extractor(extractor_name)

        # Combined model for CAM extraction (uses first probe for CAM; ensemble for prediction)
        class CombinedModel(nn.Module):
            def __init__(self, ext, probe):
                super().__init__()
                self.extractor = ext
                self.linear_probe = probe

            def forward(self, x):
                features = self.extractor(x)
                return self.linear_probe(features)

        # For CAM, use the first linear probe (all folds share the same extractor)
        combined_model = CombinedModel(extractor, linear_probes[0]).to(device)
        combined_model.eval()

        # Build labels dict and image paths from target dataset WSIs
        labels: Dict[str, int] = {}
        image_paths: Dict[str, str] = {}
        task_user_id = None
        async with safe_session() as db:
            for wsi_id in wsi_ids:
                wsi = await WSIRepository.get_by_id(db, wsi_id)
                if wsi is not None:
                    if isinstance(wsi.label, str) and wsi.label in classes:
                        labels[wsi_id] = classes.index(wsi.label)
                    image_paths[wsi_id] = _coerce_str(wsi.wsi_path)

            # Get user_id from the task for saving results later
            task_record = await TrainingTaskRepository.get_by_id(db, task_id)
            task_user_id = (
                str(task_record.user_id)
                if isinstance(task_record, TrainingTask)
                and isinstance(task_record.user_id, str)
                else None
            )

        if not image_paths:
            raise ValueError("No image paths found for target WSIs")

        async with logger_manager.session() as (tl, _db):
            await tl.info(
                f"Running inference on {len(image_paths)} images (extractor: {extractor_name})"
            )

        await update_task_progress(TaskStatus.PATCHING, 10)
        if is_permission_revoked(task_id):
            raise PermissionRevokedException(f"Permission revoked for task {task_id}")

        # Delete old AIResult records for this task
        async with safe_session() as db:
            deleted_count = await AIResultRepository.delete_by_task_id(db, task_id)
            await db.commit()
            if deleted_count > 0:
                logger.info(
                    f"Deleted {deleted_count} old AIResult records for task {task_id}"
                )

        # Run inference (in thread to avoid blocking event loop)
        ai_results_root = uploads_dir / "ai_results"
        results_saved = 0
        total_items = len(image_paths)

        def _run_inference():
            nonlocal results_saved
            all_results = []
            with torch.set_grad_enabled(use_gradients):
                for idx, (wsi_id, img_path) in enumerate(image_paths.items()):
                    try:
                        img = Image.open(img_path).convert("RGB")
                        transformed = type_cast("Any", fm_transform(img))
                        img_tensor = transformed.unsqueeze(0).to(device)

                        # K-fold ensemble: average logits across all folds
                        if is_kfold:
                            with torch.inference_mode():
                                features = extractor(img_tensor)
                                all_logits = []
                                for fold_probe in linear_probes:
                                    fold_logits = fold_probe(features)
                                    all_logits.append(fold_logits)
                                avg_logits = torch.mean(torch.stack(all_logits), dim=0)
                                probs = (
                                    F.softmax(avg_logits, dim=-1)
                                    .squeeze(0)
                                    .cpu()
                                    .numpy()
                                )
                                pred_idx = int(probs.argmax())
                                pred_label = classes[pred_idx]
                        else:
                            with torch.inference_mode():
                                logits = combined_model(img_tensor)
                                probs = (
                                    F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                                )
                                pred_idx = int(probs.argmax())
                                pred_label = classes[pred_idx]

                        # Extract CAM (uses combined_model with first probe)
                        try:
                            cam_map = cam_extractor.extract_cam(
                                model=combined_model,
                                input_tensor=img_tensor,
                                target_class=pred_idx,
                            )
                            cam_map = cam_map.squeeze(0)
                        except Exception:
                            cam_map = np.ones(cam_size, dtype=np.float32) / (
                                cam_size[0] * cam_size[1]
                            )

                        probs_dict = {
                            cls: float(probs[i]) for i, cls in enumerate(classes)
                        }
                        gt_label = (
                            classes[labels[wsi_id]] if wsi_id in labels else "unknown"
                        )

                        wsi_result_dir = ai_results_root / wsi_id
                        wsi_result_dir.mkdir(parents=True, exist_ok=True)

                        # Save CAM
                        cam_file = wsi_result_dir / f"extval_{task_id}_cam.npy"
                        np.save(cam_file, cam_map)

                        # Save result JSON (aligned with WSI branch fields)
                        result_data = {
                            "wsi_id": wsi_id,
                            "task_id": model_task_id,
                            "validation_source": dataset_id,
                            "validation_task_id": task_id,
                            "task_type": "patch_classification",
                            "aggregation_level": "file",
                            "pred": pred_label,
                            "probs": probs_dict,
                            "ground_truth": gt_label,
                            "correct": pred_label == gt_label
                            if gt_label != "unknown"
                            else None,
                            "classes": classes,
                            "cam_file": str(cam_file),
                            "cam_size": list(cam_size),
                            "is_kfold": is_kfold,
                            "num_folds": num_folds if is_kfold else None,
                        }

                        result_file = wsi_result_dir / f"extval_{task_id}_result.json"
                        with open(result_file, "w", encoding="utf-8") as f:
                            json.dump(result_data, f, ensure_ascii=False, indent=2)

                        all_results.append(
                            {
                                "wsi_id": wsi_id,
                                "pred": pred_label,
                                "probs": probs_dict,
                                "gt_label": gt_label,
                                "correct": pred_label == gt_label
                                if gt_label != "unknown"
                                else None,
                                "cam_file": str(cam_file),
                                "cam_size": list(cam_size),
                                "result_file": str(result_file),
                            }
                        )
                        results_saved += 1
                    except Exception as e:
                        logger.warning(f"Failed to process {wsi_id}: {e}")
                        continue
            return all_results

        all_results = await asyncio.to_thread(_run_inference)
        if is_permission_revoked(task_id):
            raise PermissionRevokedException(f"Permission revoked for task {task_id}")

        # Save to database (aligned with WSI branch fields)
        async with safe_session() as db:
            for r in all_results:
                db_result_data = {
                    "wsi_id": r["wsi_id"],
                    "task_id": task_id,
                    "user_id": task_user_id,
                    "pred": r["pred"],
                    "probs": r["probs"],
                    "extra_metadata": {
                        "validation_type": "external",
                        "model_task_id": model_task_id,
                        "dataset_id": dataset_id,
                        "aggregation_level": "file",
                        "ground_truth": r["gt_label"],
                        "correct": r["correct"],
                        "classes": classes,
                        "task_type": "patch_classification",
                        "cam_file": r["cam_file"],
                        "cam_size": r["cam_size"],
                        "result_file": r["result_file"],
                    },
                }
                await AIResultRepository.create(db, db_result_data)
            await db.commit()

        await clear_progress(task_id)
        await update_task_progress(
            TaskStatus.COMPLETED, 100, results_saved, results_saved
        )

        async with logger_manager.session() as (tl, _db):
            await tl.info(
                f"Patch classification external validation completed: {results_saved}/{total_items} images processed"
            )

        # Auto-trigger analysis
        await _auto_trigger_external_validation_analysis(
            task_id=task_id,
            model_task_id=model_task_id,
            model_id=model_id,
            dataset_id=dataset_id,
        )

    except Exception as e:
        import traceback

        logger.error(
            f"Patch classification external validation {task_id} failed: {e}\n{traceback.format_exc()}"
        )
        try:
            await clear_progress(task_id)
            async with logger_manager.session() as (tl, _db):
                await tl.error(f"Patch classification external validation failed: {e}")
        except Exception:
            pass
        await update_task_progress(TaskStatus.FAILED, 0, error_msg=str(e))
    finally:
        clear_revocation(task_id)
        try:
            import gc

            gc.collect()
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception as cleanup_err:
            logger.warning(
                f"Patch ext-val {task_id}: VRAM cleanup failed: {cleanup_err}"
            )


async def _run_external_validation(
    task_id: str,
    model_task_id: str,
    model_id: str,
    model_classes: Optional[List[str]],
    model_task_type: str,  # "classification", "wsi_classification", "survival", "wsi_survival", "patch_classification"
    model_data_type: str = "wsi",  # "wsi" or "patch"
    dataset_id: str = "",
    wsi_ids: Optional[List[str]] = None,
    assigned_device: Optional[
        str
    ] = None,  # GPU device assigned by task queue (e.g., "cuda:0")
):
    """Background task to run external validation.

    This function is called by the task queue and updates progress in the database.
    Supports WSI classification, WSI survival, and patch classification models.
    Supports case-level inference based on the target dataset's aggregation_level.

    Architecture:
    - Pre-inference DB queries run in async context (fast, short-lived sessions)
    - Synchronous DataLoader + model inference runs in a thread via asyncio.to_thread()
      to avoid blocking the event loop (which would cause DB lock + frontend freeze)
    - Progress updates during inference use file-based progress_store (no DB needed)
    - Post-inference: results are batch-inserted into ai_results table
    """
    import torch
    import torch.nn.functional as F
    import numpy as np
    import httpx
    from sqlalchemy import update as sql_update
    from backend.database.models import TrainingTask
    from backend.database.database import safe_session
    from backend.common.progress_store import set_progress, clear_progress
    from gateway.pipeline import ScopedLogger
    from gateway.dependencies import AI_SERVICE_URL
    from backend.ai.tasks.feature_cache import (
        compute_params_hash,
        find_cached_features,
        create_symlink_to_cache,
    )
    from gateway.utils import ensure_coords_ready
    from backend.ai.permission_revocation import (
        is_permission_revoked,
        clear_revocation,
        PermissionRevokedException,
    )

    wsi_ids = wsi_ids or []

    # Minimum patches threshold for valid WSI (same as trainer.py)
    MIN_PATCHES_THRESHOLD = 100

    # ScopedLogger writes to training_logs table so SSE log stream works
    logger_manager = ScopedLogger(task_id)

    # Determine if this is a survival task
    is_survival = model_task_type in ("survival", "wsi_survival")

    async def update_task_progress(
        status: str,
        progress: int,
        processed_wsi: int = 0,
        results_count: int = 0,
        error_msg: Optional[str] = None,
    ):
        """Helper to update task status in database. Uses safe_session for background tasks."""
        async with safe_session() as db:
            # Update status and progress
            await TrainingTaskRepository.update_status(
                db, task_id, status, progress, error_msg
            )

            # Update model_config with processed_wsi and results_count
            task = await TrainingTaskRepository.get_by_id(db, task_id)
            if isinstance(task, TrainingTask):
                model_config = (
                    task.model_config if isinstance(task.model_config, dict) else {}
                )
                model_config["processed_wsi"] = processed_wsi
                model_config["results_count"] = results_count
                await db.execute(
                    sql_update(TrainingTask)
                    .where(TrainingTask.task_id == task_id)
                    .values(model_config=model_config)
                )
            await db.commit()

    try:
        # Mark as running and log start
        await update_task_progress(TaskStatus.PATCHING, 0)
        if is_permission_revoked(task_id):
            raise PermissionRevokedException(f"Permission revoked for task {task_id}")
        async with logger_manager.session() as (tl, _db):
            await tl.info(f"Starting external validation for task: {task_id}")
            await tl.info(
                f"Model: {model_id} | Dataset: {dataset_id} | WSIs: {len(wsi_ids)} | Data type: {model_data_type} | Task type: {model_task_type}"
            )

        uploads_dir = Config.get_uploads_dir()

        # ================================================================
        # Patch-level tasks: branch to dedicated handlers
        # ================================================================
        if model_data_type == "patch":
            is_patch_segmentation = model_task_type in (
                "patch_segmentation",
                "segmentation",
            )
            if is_patch_segmentation:
                await _run_external_validation_patch_segmentation(
                    task_id=task_id,
                    model_task_id=model_task_id,
                    model_id=model_id,
                    dataset_id=dataset_id,
                    wsi_ids=wsi_ids,
                    assigned_device=assigned_device or "",
                    logger_manager=logger_manager,
                    update_task_progress=update_task_progress,
                )
                return

            # Patch classification external validation
            await _run_external_validation_patch_classification(
                task_id=task_id,
                model_task_id=model_task_id,
                model_id=model_id,
                model_classes=model_classes or [],
                dataset_id=dataset_id,
                wsi_ids=wsi_ids,
                assigned_device=assigned_device or "",
                logger_manager=logger_manager,
                update_task_progress=update_task_progress,
            )
            return

        # Load model - wrapped in asyncio.to_thread because torch.load() is
        # CPU-intensive (pickle deserialization) and would block the event loop.
        model_dir = uploads_dir / "models" / model_id
        config_path = model_dir / "config.json"
        device = (
            assigned_device
            if assigned_device
            else ("cuda" if torch.cuda.is_available() else "cpu")
        )

        def _sync_load_models():
            """Load model config and checkpoint(s). Runs in thread to avoid blocking event loop."""
            from backend.ai.aggregators import get_aggregator

            _config = {}
            if config_path.exists():
                with open(config_path, "r") as f:
                    _config = json.load(f)

            _is_kfold = _config.get("split_type") == "kfold"
            _num_folds = _config.get("num_folds", 5) if _is_kfold else 1
            _aggregator_name = _config.get("model", "abmil")

            _models = []
            _bin_edges = None

            if _is_kfold:
                logger.info(
                    f"K-fold model detected with {_num_folds} folds, loading all checkpoints"
                )
                _all_fold_bin_edges = []
                for fold_idx in range(_num_folds):
                    fold_ckpt_path = model_dir / f"fold_{fold_idx}" / "aggregator.pth"
                    if not fold_ckpt_path.exists():
                        raise FileNotFoundError(
                            f"Fold {fold_idx} checkpoint not found: {fold_ckpt_path}"
                        )

                    checkpoint = torch.load(fold_ckpt_path, map_location=device)
                    fold_model = type_cast(
                        "Any",
                        get_aggregator(
                            _aggregator_name,
                            in_dim=checkpoint["in_dim"],
                            num_classes=checkpoint["num_classes"],
                        ).to(device),
                    )
                    fold_model.load_state_dict(checkpoint["state_dict"])
                    fold_model.eval()
                    _models.append(fold_model)

                    if is_survival:
                        fold_be = checkpoint.get("bin_edges")
                        if fold_be is not None:
                            fold_be = (
                                np.array(fold_be)
                                if not isinstance(fold_be, np.ndarray)
                                else fold_be
                            )
                            _all_fold_bin_edges.append(fold_be)

                # Average bin_edges across all folds for ensemble survival model
                if is_survival and _all_fold_bin_edges:
                    if len(_all_fold_bin_edges) == 1:
                        _bin_edges = _all_fold_bin_edges[0]
                    else:
                        # All folds should have same number of bins; average the edges
                        min_len = min(len(be) for be in _all_fold_bin_edges)
                        trimmed = [be[:min_len] for be in _all_fold_bin_edges]
                        _bin_edges = np.mean(trimmed, axis=0)
            else:
                ckpt_path = model_dir / "aggregator.pth"
                if not ckpt_path.exists():
                    raise FileNotFoundError(f"Model checkpoint not found: {ckpt_path}")

                checkpoint = torch.load(ckpt_path, map_location=device)
                _model = type_cast(
                    "Any",
                    get_aggregator(
                        _aggregator_name,
                        in_dim=checkpoint["in_dim"],
                        num_classes=checkpoint["num_classes"],
                    ).to(device),
                )
                _model.load_state_dict(checkpoint["state_dict"])
                _model.eval()
                _models.append(_model)

                if is_survival:
                    _bin_edges = checkpoint.get("bin_edges")
                    if _bin_edges is not None:
                        _bin_edges = (
                            np.array(_bin_edges)
                            if not isinstance(_bin_edges, np.ndarray)
                            else _bin_edges
                        )

            _has_raw_attention = hasattr(_models[0], "forward_with_raw_attention")
            return (
                _models,
                _bin_edges,
                _has_raw_attention,
                _config,
                _is_kfold,
                _num_folds,
                _aggregator_name,
            )

        (
            models,
            bin_edges,
            has_raw_attention,
            config,
            is_kfold,
            num_folds,
            aggregator_name,
        ) = await asyncio.to_thread(_sync_load_models)

        async with logger_manager.session() as (tl, _db):
            if is_kfold:
                await tl.info(
                    f"Loaded k-fold model ({num_folds} folds) on device: {device}, aggregator: {aggregator_name}"
                )
            else:
                await tl.info(
                    f"Loaded model on device: {device}, aggregator: {aggregator_name}"
                )

        # Use classes from TrainedModel directly (for classification)
        classes = model_classes or []

        # Get test dataset's data_level and ground truth data
        is_case_level = False
        wsi_case_map: Dict[str, str] = {}
        survival_data: Dict[str, Dict[str, Any]] = {}
        labels: Dict[str, int] = {}

        async with safe_session() as db:
            # Get aggregation_level from target dataset
            aggregation_level = await DatasetRepository.get_aggregation_level(
                db, dataset_id
            )
            is_case_level = aggregation_level == "case"
            logger.info(
                f"External validation: target dataset aggregation_level = {aggregation_level}, is_case_level = {is_case_level}"
            )

            if is_case_level:
                # Get case_id mapping for case-level inference
                wsi_case_map = await DatasetRepository.get_wsi_case_ids(db, dataset_id)
                logger.info(
                    f"External validation: loaded case_id mapping for {len(wsi_case_map)} WSIs"
                )

            # Batch-fetch all WSI metadata in one query (avoids N+1 query problem)
            wsi_map = await WSIRepository.get_by_ids(db, wsi_ids)

            # Get user_id from the task for saving results later
            task_record = await TrainingTaskRepository.get_by_id(db, task_id)
            task_user_id = (
                str(task_record.user_id)
                if isinstance(task_record, TrainingTask)
                and isinstance(task_record.user_id, str)
                else None
            )

            if is_survival:
                # For survival: get event_time and event_status from WSI metadata
                for wsi_id in wsi_ids:
                    wsi = wsi_map.get(wsi_id)
                    if wsi:
                        event_time = getattr(wsi, "event_time", None) or (
                            wsi.extra_metadata or {}
                        ).get("event_time")
                        event_status = getattr(wsi, "event_status", None) or (
                            wsi.extra_metadata or {}
                        ).get("event_status")
                        if event_time is not None:
                            survival_data[wsi_id] = {
                                "event_time": float(event_time),
                                "event_status": int(event_status or 0),
                            }
            else:
                # For classification: get class labels
                for wsi_id in wsi_ids:
                    wsi = wsi_map.get(wsi_id)
                    if (
                        wsi is not None
                        and isinstance(wsi.label, str)
                        and wsi.label in classes
                    ):
                        labels[wsi_id] = classes.index(wsi.label)

        # ================================================================
        # Build features directory using global cache (params_hash based).
        # If features are missing, automatically extract them via
        # preprocessing + AI services (same pattern as pipeline.py).
        # ================================================================
        features_dir = uploads_dir / "training" / task_id / "features"
        features_dir.mkdir(parents=True, exist_ok=True)

        # Get preprocessing_config from the validation task record
        async with safe_session() as db:
            val_task = await TrainingTaskRepository.get_by_id(db, task_id)
            preprocessing_config = (
                val_task.preprocessing_config if val_task else {}
            ) or {}

        feature_extractor = preprocessing_config.get("feature_extractor", "resnet50")

        # Compute params_hash from preprocessing config
        seg_params = {
            "sthresh": preprocessing_config.get("sthresh", 8),
            "mthresh": preprocessing_config.get("mthresh", 7),
            "close": preprocessing_config.get("close", 4),
            "use_otsu": preprocessing_config.get("use_otsu", False),
        }
        filter_params = {
            "a_t": preprocessing_config.get("a_t", 1),
            "a_h": preprocessing_config.get("a_h", 256),
            "max_n_holes": preprocessing_config.get("max_n_holes", 100),
        }
        level = preprocessing_config.get("level", 0)
        contour_fn = preprocessing_config.get("contour_fn", "four_pt")
        use_padding = preprocessing_config.get("use_padding", True)
        coords_request_params = {
            "level": level,
            "force_recompute": False,
            "sthresh": seg_params["sthresh"],
            "mthresh": seg_params["mthresh"],
            "close": seg_params["close"],
            "use_otsu": seg_params["use_otsu"],
            "contour_fn": contour_fn,
            "use_padding": use_padding,
            "a_t": filter_params["a_t"],
            "a_h": filter_params["a_h"],
            "max_n_holes": filter_params["max_n_holes"],
            "save_mask": True,
        }

        params_hash = compute_params_hash(
            level=level,
            seg_params=seg_params,
            filter_params=filter_params,
            contour_fn=contour_fn,
            use_padding=use_padding,
        )

        # Step 1: Check global feature cache for each WSI
        cached_wsi_ids = []
        missing_wsi_ids = []

        def _check_feature_cache():
            for wsi_id in wsi_ids:
                cached_path = find_cached_features(
                    uploads_dir, feature_extractor, params_hash, wsi_id
                )
                if cached_path is not None:
                    create_symlink_to_cache(features_dir, wsi_id, cached_path)
                    cached_wsi_ids.append(wsi_id)
                else:
                    missing_wsi_ids.append(wsi_id)

        await asyncio.to_thread(_check_feature_cache)

        async with logger_manager.session() as (tl, _db):
            await tl.info(
                f"Feature cache: {len(cached_wsi_ids)}/{len(wsi_ids)} WSIs found in global cache (hash={params_hash})"
            )

        # Step 2: If features are missing, extract them via preprocessing + AI services
        # with resilient fallback: skip problematic WSIs instead of failing the entire task
        failed_wsi_ids = []  # Track WSIs that failed extraction
        failed_reasons = {}  # Track reasons for failure

        if missing_wsi_ids:
            async with logger_manager.session() as (tl, _db):
                await tl.info(
                    f"Extracting features for {len(missing_wsi_ids)} WSIs missing from cache..."
                )

            await update_task_progress(TaskStatus.PATCHING, 5)
            await set_progress(task_id, 5)

            # Step 2a: Patch extraction via preprocessing service (with fallback logic)
            # This mirrors the training pipeline pattern from pipeline.py
            total_missing = len(missing_wsi_ids)
            coords_success_wsi_ids = []  # WSIs where coords extraction succeeded

            for idx, wsi_id in enumerate(missing_wsi_ids, 1):
                await asyncio.sleep(0)  # Yield to event loop

                coords_result = None
                coords_error = None

                async def _log_retry(
                    attempt: int, max_retries: int, retry_err: Exception, wait_secs: int
                ):
                    async with logger_manager.session() as (tl, _db):
                        await tl.warning(
                            f"[{idx}/{total_missing}] compute_patches attempt {attempt}/{max_retries} "
                            f"failed for {wsi_id}: {type(retry_err).__name__}. "
                            f"Retrying in {wait_secs}s (cached coords will be used on retry)...",
                            metadata={
                                "wsi_id": wsi_id,
                                "attempt": attempt,
                                "error": str(retry_err),
                            },
                        )

                async def _log_lock_wait(wait_seconds: float):
                    async with logger_manager.session() as (tl, _db):
                        await tl.info(
                            f"[{idx}/{total_missing}] Waiting {wait_seconds:.0f}s for shared coords extraction lock on {wsi_id}",
                            metadata={"wsi_id": wsi_id, "wait_seconds": wait_seconds},
                        )

                try:
                    coords_result = await ensure_coords_ready(
                        wsi_id,
                        params=coords_request_params,
                        timeout=600.0,
                        uploads_root=uploads_dir,
                        on_retry=_log_retry,
                        on_lock_wait=_log_lock_wait,
                    )
                except httpx.HTTPStatusError as http_err:
                    coords_error = http_err
                    try:
                        resp_body = (
                            http_err.response.text[:500] if http_err.response else ""
                        )
                    except Exception:
                        resp_body = "(unable to read response body)"
                    async with logger_manager.session() as (tl, _db):
                        await tl.warning(
                            f"[{idx}/{total_missing}] Patch extraction failed for {wsi_id}: "
                            f"HTTP {http_err.response.status_code if http_err.response else 'N/A'} - {resp_body}",
                            metadata={
                                "wsi_id": wsi_id,
                                "error": str(http_err),
                                "response_body": resp_body,
                            },
                        )
                except Exception as e:
                    coords_error = e

                # Handle result
                if coords_result is not None:
                    num_patches = coords_result.get("num_patches", 0)
                    cached = coords_result.get("cached", False)

                    if num_patches == 0:
                        # 0 patches = no detectable tissue (even after adaptive seg_level fallback)
                        async with logger_manager.session() as (tl, _db):
                            await tl.warning(
                                f"[{idx}/{total_missing}] Skipping {wsi_id}: 0 patches extracted "
                                f"(no detectable tissue after adaptive seg_level fallback)",
                                metadata={"wsi_id": wsi_id, "num_patches": 0},
                            )
                        failed_wsi_ids.append(wsi_id)
                        failed_reasons[wsi_id] = "0 patches (no detectable tissue)"
                    elif num_patches < MIN_PATCHES_THRESHOLD:
                        # Too few patches for reliable inference
                        async with logger_manager.session() as (tl, _db):
                            await tl.warning(
                                f"[{idx}/{total_missing}] Skipping {wsi_id}: only {num_patches} patches "
                                f"(minimum {MIN_PATCHES_THRESHOLD} required for reliable inference)",
                                metadata={
                                    "wsi_id": wsi_id,
                                    "num_patches": num_patches,
                                    "threshold": MIN_PATCHES_THRESHOLD,
                                },
                            )
                        failed_wsi_ids.append(wsi_id)
                        failed_reasons[wsi_id] = (
                            f"low patches ({num_patches} < {MIN_PATCHES_THRESHOLD})"
                        )
                    else:
                        coords_success_wsi_ids.append(wsi_id)
                        async with logger_manager.session() as (tl, _db):
                            if cached:
                                await tl.info(
                                    f"[{idx}/{total_missing}] Coords cache hit for {wsi_id} ({num_patches} patches)",
                                    metadata={
                                        "wsi_id": wsi_id,
                                        "num_patches": num_patches,
                                        "cached": True,
                                    },
                                )
                            else:
                                await tl.info(
                                    f"[{idx}/{total_missing}] Extracted {num_patches} patches from {wsi_id}",
                                    metadata={
                                        "wsi_id": wsi_id,
                                        "num_patches": num_patches,
                                        "cached": False,
                                    },
                                )
                else:
                    # Coords extraction failed after retries
                    err_type = (
                        type(coords_error).__name__ if coords_error else "Unknown"
                    )
                    err_msg = str(coords_error) if coords_error else "Unknown error"
                    async with logger_manager.session() as (tl, _db):
                        await tl.error(
                            f"[{idx}/{total_missing}] Skipping {wsi_id}: coords extraction failed - [{err_type}] {err_msg}",
                            metadata={
                                "wsi_id": wsi_id,
                                "error": err_msg,
                                "error_type": err_type,
                            },
                        )
                    failed_wsi_ids.append(wsi_id)
                    failed_reasons[wsi_id] = f"coords failed: {err_type}"

                # Update progress (5-30% for patch extraction)
                progress = 5 + int((idx / total_missing) * 25)
                await update_task_progress(TaskStatus.PATCHING, progress)
                await set_progress(task_id, progress)

            # Log summary of coords extraction
            async with logger_manager.session() as (tl, _db):
                await tl.info(
                    f"Patch extraction phase complete: {len(coords_success_wsi_ids)}/{total_missing} WSIs succeeded, "
                    f"{len(failed_wsi_ids)} failed/skipped",
                    metadata={
                        "success_count": len(coords_success_wsi_ids),
                        "failed_count": len(failed_wsi_ids),
                        "failed_wsi_ids": failed_wsi_ids[:20],  # Cap at 20 for log size
                    },
                )

            # Step 2b: Feature extraction via AI service (only for WSIs with valid coords)
            if coords_success_wsi_ids:
                feature_batch_size = preprocessing_config.get("feature_batch_size", 64)
                from gateway.pipeline import get_training_timeout

                timeout = get_training_timeout()

                async with logger_manager.session() as (tl, _db):
                    await tl.info(
                        f"Calling AI service for feature extraction (using {feature_extractor}) on {len(coords_success_wsi_ids)} WSIs"
                    )

                await update_task_progress(TaskStatus.EXTRACTING, 30)
                await set_progress(task_id, 30)

                try:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        resp = await client.post(
                            f"{AI_SERVICE_URL}/api/ai/training/extract_features",
                            json={
                                "task_id": task_id,
                                "wsi_ids": coords_success_wsi_ids,
                                "feature_extractor": feature_extractor,
                                "batch_size": feature_batch_size,
                                "force_recompute": False,
                                "huggingface_token": "",
                                "preprocessing_config": preprocessing_config,
                                "device": assigned_device or "",
                            },
                        )
                        resp.raise_for_status()
                        feat_result = resp.json()
                        # Check for skipped WSIs from feature extraction
                        feat_skipped = (
                            feat_result.get("skipped_wsi_ids", [])
                            if feat_result
                            else []
                        )
                        if feat_skipped:
                            for skip_wsi in feat_skipped:
                                if skip_wsi not in failed_wsi_ids:
                                    failed_wsi_ids.append(skip_wsi)
                                    failed_reasons[skip_wsi] = (
                                        "feature extraction skipped (low patches)"
                                    )
                            async with logger_manager.session() as (tl, _db):
                                await tl.warning(
                                    f"AI service skipped {len(feat_skipped)} WSIs during feature extraction: {feat_skipped[:10]}",
                                    metadata={
                                        "skipped_count": len(feat_skipped),
                                        "skipped_wsi_ids": feat_skipped[:20],
                                    },
                                )
                except httpx.HTTPStatusError as e:
                    body = e.response.text if e.response is not None else str(e)
                    async with logger_manager.session() as (tl, _db):
                        await tl.error(
                            f"Feature extraction failed: {e}", metadata={"body": body}
                        )
                    raise
                except httpx.TimeoutException as e:
                    async with logger_manager.session() as (tl, _db):
                        await tl.error(f"Feature extraction timeout: {e}")
                    raise

                async with logger_manager.session() as (tl, _db):
                    await tl.info(
                        f"Feature extraction completed for {len(coords_success_wsi_ids)} WSIs"
                    )

                await update_task_progress(TaskStatus.EXTRACTING, 33)
                await set_progress(task_id, 33)

                # Step 2c: Validate extracted features and symlink to task directory
                from backend.ai.tasks.feature_cache import safe_load_features

                def _validate_and_symlink_features():
                    valid_wsi_ids = []
                    invalid_wsi_ids = []
                    for wsi_id in coords_success_wsi_ids:
                        cached_path = find_cached_features(
                            uploads_dir, feature_extractor, params_hash, wsi_id
                        )
                        if cached_path is None:
                            invalid_wsi_ids.append((wsi_id, "no cached features found"))
                            continue

                        # Validate the feature file is not corrupted/empty
                        feats, load_error = safe_load_features(
                            cached_path, delete_if_corrupted=True
                        )
                        if feats is None:
                            invalid_wsi_ids.append((wsi_id, f"corrupted: {load_error}"))
                            continue

                        if feats.shape[0] == 0:
                            invalid_wsi_ids.append((wsi_id, "empty [0, feat_dim]"))
                            continue

                        if feats.shape[0] < MIN_PATCHES_THRESHOLD:
                            invalid_wsi_ids.append(
                                (
                                    wsi_id,
                                    f"low patches ({feats.shape[0]} < {MIN_PATCHES_THRESHOLD})",
                                )
                            )
                            continue

                        # Feature is valid - create symlink
                        create_symlink_to_cache(features_dir, wsi_id, cached_path)
                        valid_wsi_ids.append(wsi_id)

                    return valid_wsi_ids, invalid_wsi_ids

                valid_wsi_ids, invalid_wsi_ids = await asyncio.to_thread(
                    _validate_and_symlink_features
                )

                # Update tracking for invalid features
                for wsi_id, reason in invalid_wsi_ids:
                    if wsi_id not in failed_wsi_ids:
                        failed_wsi_ids.append(wsi_id)
                        failed_reasons[wsi_id] = f"feature validation failed: {reason}"

                if invalid_wsi_ids:
                    async with logger_manager.session() as (tl, _db):
                        await tl.warning(
                            f"Feature validation: {len(invalid_wsi_ids)} WSIs have invalid features",
                            metadata={
                                "invalid_count": len(invalid_wsi_ids),
                                "invalid_details": {
                                    w: r for w, r in invalid_wsi_ids[:20]
                                },
                            },
                        )

                # Move valid WSIs to cached list
                for wsi_id in valid_wsi_ids:
                    if wsi_id not in cached_wsi_ids:
                        cached_wsi_ids.append(wsi_id)

            # Log final fallback summary if any WSIs were skipped
            if failed_wsi_ids:
                async with logger_manager.session() as (tl, _db):
                    await tl.warning(
                        f"[Fallback Summary] {len(failed_wsi_ids)}/{len(wsi_ids)} WSIs skipped during extraction",
                        metadata={
                            "total_wsi": len(wsi_ids),
                            "skipped_count": len(failed_wsi_ids),
                            "skipped_wsi_ids": failed_wsi_ids[:50],
                            "reasons": {
                                k: v for k, v in list(failed_reasons.items())[:50]
                            },
                        },
                    )
        else:
            # No missing WSIs - all features cached
            await update_task_progress(TaskStatus.TRAINING, 35)
            await set_progress(task_id, 35)

        # Update status to TRAINING for inference phase
        await update_task_progress(TaskStatus.TRAINING, 35)
        if is_permission_revoked(task_id):
            raise PermissionRevokedException(f"Permission revoked for task {task_id}")
        await set_progress(task_id, 35)
        async with logger_manager.session() as (tl, _db):
            valid_count = len(cached_wsi_ids)
            await tl.info(
                f"Features ready for {valid_count}/{len(wsi_ids)} WSIs. Starting inference..."
            )

        ai_results_root = uploads_dir / "ai_results"

        # Import Dataset classes for memory-efficient loading
        from backend.ai.utils.feature_dataset import (
            WSIFeatureDataset,
            CaseFeatureDataset,
        )

        # ================================================================
        # Data preparation: build Dataset objects (fast, pure Python)
        # Moved OUTSIDE the sync function so dataset is created in async context.
        # ================================================================
        case_to_wsi: Dict[str, List[str]] = {}
        case_wsi_patch_counts: Dict[str, List[int]] = {}
        case_labels_map: Dict[str, int] = {}
        case_survival_data: Dict[str, Dict[str, Any]] = {}

        if is_case_level:
            # Group WSIs by case_id and validate feature existence
            valid_wsi_ids = []
            for wsi_id in wsi_ids:
                feat_path = features_dir / f"{wsi_id}.pt"
                if not feat_path.exists():
                    logger.warning(f"Features not found for {wsi_id}, skipping")
                    continue
                valid_wsi_ids.append(wsi_id)
                case_id = wsi_case_map.get(wsi_id, wsi_id)
                if case_id not in case_to_wsi:
                    case_to_wsi[case_id] = []
                case_to_wsi[case_id].append(wsi_id)

            if not is_survival:
                for case_id, case_wsi_ids in case_to_wsi.items():
                    first_wsi = case_wsi_ids[0]
                    if first_wsi in labels:
                        case_labels_map[case_id] = labels[first_wsi]

            case_ids = list(case_to_wsi.keys())
            case_times: Dict[str, float] = {}
            case_statuses: Dict[str, int] = {}
            if is_survival:
                for case_id, case_wsi_ids in case_to_wsi.items():
                    first_wsi = case_wsi_ids[0]
                    if first_wsi in survival_data:
                        case_gt = survival_data[first_wsi]
                        case_times[case_id] = case_gt["event_time"]
                        case_statuses[case_id] = case_gt["event_status"]
                        case_survival_data[case_id] = case_gt
                    else:
                        case_times[case_id] = 0.0
                        case_statuses[case_id] = 0
                        case_survival_data[case_id] = {
                            "event_time": 0.0,
                            "event_status": 0,
                        }
            if is_survival:
                dataset = CaseFeatureDataset(
                    features_dir=features_dir,
                    case_ids=case_ids,
                    case_to_wsi=case_to_wsi,
                    times=case_times,
                    statuses=case_statuses,
                    task_type="survival",
                    device=device,
                )
            else:
                dataset = CaseFeatureDataset(
                    features_dir=features_dir,
                    case_ids=case_ids,
                    case_to_wsi=case_to_wsi,
                    labels=case_labels_map,
                    task_type="classification",
                    device=device,
                )
            total = len(case_ids)
            logger.info(
                f"External validation case-level: {total} cases from {len(valid_wsi_ids)} WSIs"
            )

        else:
            # Slide-level: validate feature existence and create dataset
            valid_wsi_ids = [
                wsi_id for wsi_id in wsi_ids if (features_dir / f"{wsi_id}.pt").exists()
            ]
            if not valid_wsi_ids:
                raise FileNotFoundError("No feature files found for any WSI")

            if is_survival:
                times_map: Dict[str, float] = {}
                statuses_map: Dict[str, int] = {}
                for wsi_id in valid_wsi_ids:
                    if wsi_id in survival_data:
                        times_map[wsi_id] = survival_data[wsi_id]["event_time"]
                        statuses_map[wsi_id] = survival_data[wsi_id]["event_status"]
                    else:
                        times_map[wsi_id] = 0.0
                        statuses_map[wsi_id] = 0
                dataset = WSIFeatureDataset(
                    features_dir=features_dir,
                    wsi_ids=valid_wsi_ids,
                    times=times_map,
                    statuses=statuses_map,
                    task_type="survival",
                    device=device,
                )
            else:
                dataset = WSIFeatureDataset(
                    features_dir=features_dir,
                    wsi_ids=valid_wsi_ids,
                    labels=labels,
                    task_type="classification",
                    device=device,
                )
            total = len(valid_wsi_ids)
            logger.info(f"External validation slide-level: {total} WSIs")

        if total == 0:
            raise FileNotFoundError("No valid items to process after filtering")

        # ================================================================
        # Define chunk-based inference function.
        # Instead of processing ALL items in one giant asyncio.to_thread call
        # (which holds the GIL for minutes and blocks the event loop),
        # we process CHUNK_SIZE items at a time, yielding to the event loop
        # between chunks. This follows the same pattern as trainer.py which
        # calls asyncio.to_thread per-epoch.
        # ================================================================
        CHUNK_SIZE = 30

        def _sync_run_chunk(start_idx: int, end_idx: int):
            """Process dataset[start_idx:end_idx]. Returns partial results."""
            _chunk_saved = 0
            _chunk_risk_scores = []
            _chunk_result_files = []
            _chunk_db_records = []

            with torch.inference_mode():
                for idx in range(start_idx, end_idx):
                    # Load item from dataset (triggers torch.load for features)
                    item = dataset[idx]

                    hazards = np.array([], dtype=np.float32)
                    risk_score = 0.0
                    surv_probs: List[float] = []
                    probs = np.array([], dtype=np.float32)
                    slide_attentions: Dict[str, Any] = {}
                    slide_raw_attentions: Dict[str, Any] = {}

                    if is_case_level:
                        # CaseFeatureDataset returns:
                        #   survival: (features, time, status, case_id, wsi_ids, patch_counts)
                        #   classification: (features, label, case_id, wsi_ids, patch_counts)
                        if is_survival:
                            (
                                features,
                                _time,
                                _status,
                                item_id,
                                item_wsi_ids,
                                patch_counts,
                            ) = item
                        else:
                            features, _label, item_id, item_wsi_ids, patch_counts = item
                        case_wsi_patch_counts[item_id] = patch_counts
                        agg_level = "case"
                    else:
                        # WSIFeatureDataset returns:
                        #   survival: (features, time, status, wsi_id)
                        #   classification: (features, label, wsi_id)
                        if is_survival:
                            features, _time, _status, item_id = item
                        else:
                            features, _label, item_id = item
                        item_wsi_ids = [item_id]
                        agg_level = "file"

                    h_features = features.to(device)

                    # --- Model inference ---
                    if is_kfold:
                        if is_survival:
                            hazards = np.array([], dtype=np.float32)
                            risk_score = 0.0
                            surv_probs = []
                            all_hazards = []
                            all_attentions = []
                            for fold_model in models:
                                if has_raw_attention:
                                    logits_f, attn_f, _ = (
                                        fold_model.forward_with_raw_attention(
                                            h_features
                                        )
                                    )
                                else:
                                    logits_f, attn_f = fold_model(h_features)
                                hazards_f = (
                                    torch.sigmoid(logits_f).cpu().numpy().flatten()
                                )
                                all_hazards.append(hazards_f)
                                if attn_f is not None:
                                    all_attentions.append(attn_f.cpu().numpy())
                            hazards = np.mean(all_hazards, axis=0)
                            surv_probs = np.cumprod(1 - hazards).tolist()
                            risk_score = float(np.sum(hazards))
                            attention = (
                                np.mean(all_attentions, axis=0)
                                if all_attentions
                                else None
                            )
                            raw_attention = None
                        else:
                            probs = np.array([], dtype=np.float32)
                            all_logits = []
                            all_attentions = []
                            for fold_model in models:
                                if has_raw_attention:
                                    logits_f, attn_f, _ = (
                                        fold_model.forward_with_raw_attention(
                                            h_features
                                        )
                                    )
                                else:
                                    logits_f, attn_f = fold_model(h_features)
                                all_logits.append(logits_f)
                                if attn_f is not None:
                                    all_attentions.append(attn_f.cpu().numpy())
                            avg_logits = torch.mean(torch.stack(all_logits), dim=0)
                            probs = (
                                F.softmax(avg_logits, dim=-1).squeeze(0).cpu().numpy()
                            )
                            attention = (
                                np.mean(all_attentions, axis=0)
                                if all_attentions
                                else None
                            )
                            raw_attention = None
                    else:
                        _model = models[0]
                        if has_raw_attention:
                            logits, attention_t, raw_attention_t = (
                                _model.forward_with_raw_attention(h_features)
                            )
                        else:
                            logits, attention_t = _model(h_features)
                            raw_attention_t = None

                        if is_survival:
                            hazards = torch.sigmoid(logits).cpu().numpy().flatten()
                            surv_probs = np.cumprod(1 - hazards).tolist()
                            risk_score = float(np.sum(hazards))
                            attention = (
                                attention_t.cpu().numpy()
                                if attention_t is not None
                                else None
                            )
                            raw_attention = (
                                raw_attention_t.cpu().numpy()
                                if raw_attention_t is not None
                                else None
                            )
                        else:
                            probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                            attention = (
                                attention_t.cpu().numpy()
                                if attention_t is not None
                                else None
                            )
                            raw_attention = (
                                raw_attention_t.cpu().numpy()
                                if raw_attention_t is not None
                                else None
                            )

                    # --- Split attention for case-level ---
                    if is_case_level:
                        slide_attentions = _split_case_attention_to_slides_static(
                            attention, item_id, case_wsi_patch_counts, case_to_wsi
                        )
                        slide_raw_attentions = _split_case_attention_to_slides_static(
                            raw_attention, item_id, case_wsi_patch_counts, case_to_wsi
                        )

                    # --- Build prediction data ---
                    gt_data: Dict[str, Any] = {}
                    if is_survival:
                        if is_case_level:
                            gt_data = case_survival_data.get(item_id, {})
                        else:
                            gt_data = survival_data.get(item_id, {})
                        _chunk_risk_scores.append(
                            float(np.sum(hazards))
                            if isinstance(hazards, np.ndarray)
                            else risk_score
                        )
                        pred_label = None
                        probs_dict = None
                        gt_label = None
                    else:
                        pred_idx = int(probs.argmax())
                        pred_label = (
                            classes[pred_idx] if pred_idx < len(classes) else "unknown"
                        )
                        probs_dict = {
                            cls: float(probs[i]) for i, cls in enumerate(classes)
                        }
                        if is_case_level:
                            gt_label = (
                                classes[case_labels_map[item_id]]
                                if item_id in case_labels_map
                                else "unknown"
                            )
                        else:
                            gt_label = (
                                classes[labels[item_id]]
                                if item_id in labels
                                else "unknown"
                            )

                    # --- Save per-WSI results ---
                    for wsi_id in item_wsi_ids:
                        wsi_result_dir = ai_results_root / wsi_id
                        wsi_result_dir.mkdir(parents=True, exist_ok=True)

                        if is_case_level:
                            slide_attn = slide_attentions.get(wsi_id)
                            slide_raw_attn = slide_raw_attentions.get(wsi_id)
                        else:
                            slide_attn = attention
                            slide_raw_attn = raw_attention

                        attention_shape = (
                            list(slide_attn.shape)
                            if slide_attn is not None and hasattr(slide_attn, "shape")
                            else None
                        )
                        if slide_attn is None:
                            attention_type = "none"
                        elif getattr(slide_attn, "ndim", None) == 1:
                            attention_type = "1d"
                        else:
                            attention_type = "2d"

                        if is_survival:
                            result_data = {
                                "wsi_id": wsi_id,
                                "case_id": item_id if is_case_level else None,
                                "task_id": model_task_id,
                                "validation_source": dataset_id,
                                "validation_task_id": task_id,
                                "task_type": "survival",
                                "aggregation_level": agg_level,
                                "risk_score": risk_score,
                                "hazards": hazards.tolist()
                                if isinstance(hazards, np.ndarray)
                                else hazards,
                                "surv_probs": surv_probs,
                                "event_time": gt_data.get("event_time"),
                                "event_status": gt_data.get("event_status"),
                                "bin_edges": bin_edges.tolist()
                                if bin_edges is not None
                                else None,
                                "attention_type": attention_type,
                                "attention_shape": attention_shape,
                                "is_kfold": is_kfold,
                                "num_folds": num_folds if is_kfold else None,
                            }
                        else:
                            result_data = {
                                "wsi_id": wsi_id,
                                "case_id": item_id if is_case_level else None,
                                "task_id": model_task_id,
                                "validation_source": dataset_id,
                                "validation_task_id": task_id,
                                "task_type": "classification",
                                "aggregation_level": agg_level,
                                "pred": pred_label,
                                "probs": probs_dict,
                                "ground_truth": gt_label,
                                "correct": pred_label == gt_label
                                if gt_label != "unknown"
                                else None,
                                "classes": classes,
                                "aggregator": aggregator_name,
                                "attention_type": attention_type,
                                "attention_shape": attention_shape,
                                "is_kfold": is_kfold,
                                "num_folds": num_folds if is_kfold else None,
                            }

                        result_file = wsi_result_dir / f"extval_{task_id}_result.json"
                        attention_file = None

                        if slide_raw_attn is not None:
                            np.save(
                                wsi_result_dir / f"extval_{task_id}_attention_raw.npy",
                                slide_raw_attn,
                            )
                        if slide_attn is not None:
                            attention_file = (
                                wsi_result_dir / f"extval_{task_id}_attention.npy"
                            )
                            np.save(attention_file, slide_attn)
                            ensure_recommendation_preview_cache(
                                wsi_id, attention_file, Config.get_uploads_dir()
                            )

                        if attention_file is not None:
                            result_data["attention_file"] = str(attention_file)

                        with open(result_file, "w", encoding="utf-8") as f:
                            json.dump(result_data, f, ensure_ascii=False, indent=2)

                        if is_survival:
                            _chunk_result_files.append((str(result_file), wsi_id))

                        _chunk_saved += 1

                        # Collect DB record
                        _chunk_db_records.append(
                            {
                                "wsi_id": wsi_id,
                                "task_id": task_id,
                                "user_id": task_user_id,
                                "pred": pred_label,
                                "probs": probs_dict,
                                "extra_metadata": {
                                    "validation_type": "external",
                                    "model_task_id": model_task_id,
                                    "dataset_id": dataset_id,
                                    "aggregation_level": agg_level,
                                    "case_id": item_id if is_case_level else None,
                                    "task_type": "survival"
                                    if is_survival
                                    else "classification",
                                    "attention_type": attention_type,
                                    "attention_shape": attention_shape,
                                    "attention_file": str(attention_file)
                                    if attention_file is not None
                                    else None,
                                    "result_file": str(result_file),
                                },
                            }
                        )

            return (
                _chunk_saved,
                _chunk_risk_scores,
                _chunk_result_files,
                _chunk_db_records,
            )

        # ================================================================
        # Run inference in CHUNKS to avoid blocking the event loop.
        # Between each chunk, we yield to the event loop via await asyncio.sleep(0)
        # so SSE streams, DB queries, and other tasks can proceed.
        # ================================================================
        async with logger_manager.session() as (tl, _db):
            level_msg = "case-level" if is_case_level else "slide-level"
            await tl.info(f"Running {level_msg} inference in chunks of {CHUNK_SIZE}...")

        results_saved = 0
        all_risk_scores = []
        saved_result_files = []
        db_records = []

        for chunk_start in range(0, total, CHUNK_SIZE):
            chunk_end = min(chunk_start + CHUNK_SIZE, total)
            (
                chunk_saved,
                chunk_risk_scores,
                chunk_result_files,
                chunk_db_records,
            ) = await asyncio.to_thread(_sync_run_chunk, chunk_start, chunk_end)
            results_saved += chunk_saved
            db_records.extend(chunk_db_records)
            if is_survival:
                all_risk_scores.extend(chunk_risk_scores)
                saved_result_files.extend(chunk_result_files)

            # Update progress via file-based store (35% to 95% for inference phase)
            progress = 35 + int(chunk_end / total * 60)
            await set_progress(task_id, progress)

            # Yield to event loop - this is the KEY fix that prevents blocking
            await asyncio.sleep(0)

        # For survival: compute median risk score and update all result files with risk_group
        # NOTE: This loop reads+writes potentially thousands of JSON files.
        # Run in thread to avoid blocking the event loop.
        if is_survival and all_risk_scores:
            median_risk_score = float(np.median(all_risk_scores))
            logger.info(
                f"Survival external validation: median risk score = {median_risk_score:.4f}"
            )

            def _sync_update_survival_result_files():
                for result_file, wsi_id in saved_result_files:
                    with open(result_file, "r") as f:
                        result_data = json.load(f)

                    risk_group = (
                        "High Risk"
                        if result_data["risk_score"] >= median_risk_score
                        else "Low Risk"
                    )
                    result_data["median_risk_score"] = median_risk_score
                    result_data["risk_group"] = risk_group

                    with open(result_file, "w", encoding="utf-8") as f:
                        json.dump(result_data, f, ensure_ascii=False, indent=2)

            await asyncio.to_thread(_sync_update_survival_result_files)

        # Batch-insert results into database so Results page can display them
        if db_records:
            logger.info(f"Saving {len(db_records)} results to database...")
            async with safe_session() as db:
                await AIResultRepository.bulk_create(db, db_records, batch_size=100)
                await db.commit()
            logger.info(f"Saved {len(db_records)} results to database")

        await update_task_progress(
            TaskStatus.TRAINING, 95, results_saved, results_saved
        )

        # Clear file-based progress (task is finishing)
        await clear_progress(task_id)

        # Mark as completed
        await update_task_progress(
            TaskStatus.COMPLETED, 100, results_saved, results_saved
        )
        case_level_msg = " (case-level)" if is_case_level else ""
        kfold_msg = f" (k-fold: {num_folds} folds averaged)" if is_kfold else ""
        logger.info(
            f"External validation {task_id} completed: {results_saved} results (type: {'survival' if is_survival else 'classification'}){case_level_msg}{kfold_msg}"
        )

        async with logger_manager.session() as (tl, _db):
            await tl.info(
                f"External validation completed: {results_saved} results saved{case_level_msg}{kfold_msg}"
            )

        # Auto-trigger analysis after inference completes
        await _auto_trigger_external_validation_analysis(
            task_id=task_id,
            model_task_id=model_task_id,
            model_id=model_id,
            dataset_id=dataset_id,
        )

    except Exception as e:
        import traceback

        logger.error(
            f"External validation {task_id} failed: {e}\n{traceback.format_exc()}"
        )

        # For HTTPStatusError, extract the actual error detail from the response body
        # instead of the generic "Server error '500 Internal Server Error' for url ..." message
        err_msg = str(e)
        if isinstance(e, httpx.HTTPStatusError) and e.response is not None:
            try:
                body = json.loads(e.response.text)
                if isinstance(body, dict) and "detail" in body:
                    err_msg = body["detail"]
            except Exception:
                try:
                    err_msg = e.response.text[:2000] or err_msg
                except Exception:
                    pass

        try:
            await clear_progress(task_id)
            async with logger_manager.session() as (tl, _db):
                await tl.error(f"External validation failed: {err_msg}")
        except Exception:
            pass  # Don't let logging failure mask the original error
        await update_task_progress(TaskStatus.FAILED, 0, error_msg=err_msg)
    finally:
        clear_revocation(task_id)
        try:
            import gc
            from backend.ai.utils.feature_dataset import clear_feature_cache

            clear_feature_cache()
            gc.collect()
            gc.collect()  # Second pass for cyclic references
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                logger.info(f"External validation {task_id}: GPU memory cleaned up")
            else:
                logger.info(
                    f"External validation {task_id}: gc.collect() done (no GPU)"
                )
        except Exception as cleanup_err:
            logger.warning(
                f"External validation {task_id}: VRAM cleanup failed: {cleanup_err}"
            )


async def _auto_trigger_external_validation_analysis(
    task_id: str,
    model_task_id: str,
    model_id: str,
    dataset_id: str,
    metrics: Optional[List[str]] = None,
    charts: Optional[List[str]] = None,
    bootstrap_ci_metrics: Optional[List[str]] = None,
    submitted_by: Optional[str] = None,
):
    """
    Auto-trigger analysis after external validation inference completes.

    This makes External Validation a one-click complete operation:
    1. GPU inference runs first (via _run_external_validation)
    2. Then CPU analysis runs automatically (via this function)

    The analysis task will appear in the Background Task Panel and be merged
    with the External Validation task in the frontend display.

    Args:
        task_id: The external validation task ID
        model_task_id: The original training task ID of the model
        model_id: The trained model ID
        dataset_id: The target dataset ID
        metrics: Optional list of metrics to compute (default: accuracy, precision, recall, f1, auc)
        charts: Optional list of charts to generate (default: confusion_matrix, roc_curve)
        bootstrap_ci_metrics: Optional list of metrics to compute 95% CI for
    """
    from backend.database.database import safe_session
    from .results import _iter_complete_analysis_runs, run_analysis_pipeline

    # Check if analysis already exists for this task
    analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id
    if analysis_dir.exists():
        for item in _iter_complete_analysis_runs(analysis_dir):
            logger.info(
                f"Analysis already exists for external validation {task_id}, skipping auto-trigger"
            )
            return

    state = get_analysis_state()

    # Generate analysis ID
    analysis_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_auto"

    try:
        # Use safe_session for proper cleanup in background task
        async with safe_session() as db:
            # Get the external validation task to get user_id and other info
            task = await TrainingTaskRepository.get_by_id(db, task_id)
            if not task:
                logger.error(f"Auto-trigger analysis failed: task {task_id} not found")
                return

            user_id = str(task.user_id)
            # Use provided submitted_by, or fall back to task owner
            effective_submitted_by = submitted_by or user_id

            # Build title for the analysis
            model_config = task.model_config or {}
            source_name = model_id
            target_name = dataset_id

            try:
                model = await TrainedModelRepository.get_by_id(db, model_id)
                if model:
                    source_name = model.model_name or model_id
                target_ds = await DatasetRepository.get_by_id(db, dataset_id)
                if target_ds:
                    target_name = target_ds.name or dataset_id
            except Exception:
                pass

            title = f"{source_name} → {target_name}"

            # Use provided options or get from model_config or use defaults
            analysis_metrics = (
                metrics
                or model_config.get("analysis_metrics")
                or ["accuracy", "precision", "recall", "f1", "auc", "weighted_kappa"]
            )
            analysis_charts = (
                charts
                or model_config.get("analysis_charts")
                or ["confusion_matrix", "roc_curve"]
            )
            analysis_bootstrap_ci = (
                bootstrap_ci_metrics
                if bootstrap_ci_metrics is not None
                else (model_config.get("bootstrap_ci_metrics") or [])
            )

            # Create analysis state entry
            await state.create(
                analysis_id=analysis_id,
                task_id=task_id,
                user_id=user_id,
                title=title,
                analysis_type="external",
            )

            # Start analysis pipeline as asyncio task (CPU-only)
            analysis_task = asyncio.create_task(
                run_analysis_pipeline(
                    task_id=analysis_id,
                    analysis_id=analysis_id,
                    training_task_id=task_id,
                    task_type_str="external_validation",
                    metrics=analysis_metrics,
                    charts=analysis_charts,
                    description="Auto-triggered after external validation inference",
                    bootstrap_ci_metrics=analysis_bootstrap_ci,
                    submitted_by=effective_submitted_by,
                )
            )
            # Register task for potential cancellation
            state.register_task(analysis_id, analysis_task)
            logger.info(
                f"Auto-triggered analysis for external validation: task_id={task_id}, analysis_id={analysis_id}, bootstrap_ci={len(analysis_bootstrap_ci) > 0}"
            )

    except Exception as e:
        logger.error(
            f"Failed to auto-trigger analysis for external validation {task_id}: {e}"
        )
