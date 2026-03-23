"""
Patch Classification Inference

Handles GPU inference for patch-level classification tasks.
Extracted from results.py — no logic changes.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, cast as type_cast

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.config import Config
from backend.database.repositories import WSIRepository

from .analysis_helpers import (
    _coerce_str,
    _coerce_str_list,
)
from .inference_base import resolve_device, report_progress

logger = logging.getLogger(__name__)


async def _run_inference_patch_classification(
    task,
    wsi_ids: List[str],
    resources: dict[str, Any],
    db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None,
    assigned_device: Optional[str] = None,
):
    """
    Run GPU inference to generate AI results for patch classification task.

    This is called automatically by the analysis pipeline when AI results are missing.
    Uses feature extractor + linear probe on images directly.
    Generates CAM heatmaps for visualization.

    Args:
        progress_callback: Optional async callback for progress updates (0.0 to 1.0)
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
    from backend.database.repositories import AIResultRepository

    task_id = task.task_id
    uploads_dir = Config.get_uploads_dir()

    # Load model
    model_dir = uploads_dir / "models" / resources["model_id"]
    ckpt_path = model_dir / "linear_probe.pth"
    config_path = model_dir / "config.json"

    if not ckpt_path.exists():
        raise HTTPException(
            status_code=500, detail="Model checkpoint (linear_probe.pth) not found"
        )

    # Load config
    config = {}
    if config_path.exists():
        with open(config_path, "r") as f:
            config = json.load(f)

    # Determine classes from WSI labels or config
    classes = _coerce_str_list(config.get("classes", []))
    if not classes:
        for wsi_id in wsi_ids:
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if (
                wsi is not None
                and isinstance(wsi.label, str)
                and wsi.label not in classes
            ):
                classes.append(wsi.label)
        classes = sorted(classes)

    if len(classes) == 0:
        raise HTTPException(status_code=400, detail="Could not determine classes")

    # Build labels dict and image paths
    labels: Dict[str, int] = {}
    image_paths: Dict[str, str] = {}
    for wsi_id in wsi_ids:
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if wsi is not None:
            if isinstance(wsi.label, str) and wsi.label in classes:
                labels[wsi_id] = classes.index(wsi.label)
            image_paths[wsi_id] = _coerce_str(wsi.wsi_path)

    if not image_paths:
        raise HTTPException(status_code=400, detail="No image paths found")

    device = resolve_device(assigned_device)
    checkpoint = torch.load(ckpt_path, map_location=device)

    extractor_name = checkpoint.get(
        "extractor_name", config.get("extractor", "resnet50")
    )
    extractor_dim = checkpoint["extractor_dim"]
    num_classes = checkpoint["num_classes"]

    # Build model: extractor + linear probe
    try:
        extractor = get_extractor(extractor_name, pretrained=True)
    except (FileNotFoundError, OSError, Exception) as exc:
        raise RuntimeError(
            f"Failed to load feature extractor '{extractor_name}'. "
            f"Please ensure the model weights are downloaded locally. "
            f"Original error: {exc}"
        ) from exc
    extractor = extractor.to(device)
    extractor.eval()

    linear_probe = nn.Linear(extractor_dim, num_classes).to(device)
    linear_probe.load_state_dict(checkpoint["state_dict"])
    linear_probe.eval()

    # Match patch-classification training preprocessing.
    target_size = resolve_patch_resize_size(extractor_name)
    fm_transform = build_patch_classification_transform(
        extractor, target_size, mode="eval"
    )

    # Get CAM extractor
    cam_extractor = get_cam_extractor(extractor_name)
    cam_size = get_cam_spatial_size(extractor_name)
    use_gradients = is_cnn_extractor(extractor_name)

    # Combined model for CAM extraction
    class CombinedModel(nn.Module):
        def __init__(self, extractor, linear_probe):
            super().__init__()
            self.extractor = extractor
            self.linear_probe = linear_probe

        def forward(self, x):
            features = self.extractor(x)
            return self.linear_probe(features)

    combined_model = CombinedModel(extractor, linear_probe).to(device)
    combined_model.eval()

    # Delete old AIResult records before regenerating to avoid duplicates
    deleted_count = await AIResultRepository.delete_by_task_id(db, task_id)
    if deleted_count > 0:
        logger.info(f"Deleted {deleted_count} old AIResult records for task {task_id}")

    # Run inference
    ai_results_root = uploads_dir / "ai_results"
    results_saved = 0
    total_items = len(image_paths)

    with torch.set_grad_enabled(use_gradients):
        for idx, (wsi_id, img_path) in enumerate(image_paths.items()):
            # Update progress (0.1 to 0.9 range, leaving room for setup/cleanup)
            await report_progress(progress_callback, idx, total_items)

            try:
                img = Image.open(img_path).convert("RGB")
                transformed = type_cast("Any", fm_transform(img))
                img_tensor = transformed.unsqueeze(0).to(device)

                # Forward pass
                with torch.inference_mode():
                    logits = combined_model(img_tensor)
                    probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                    pred_idx = int(probs.argmax())
                    pred_label = classes[pred_idx]

                # Extract CAM
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

                probs_dict = {cls: float(probs[i]) for i, cls in enumerate(classes)}
                gt_label = classes[labels[wsi_id]] if wsi_id in labels else "unknown"

                wsi_result_dir = ai_results_root / wsi_id
                wsi_result_dir.mkdir(parents=True, exist_ok=True)

                # Save CAM
                cam_file = wsi_result_dir / f"train_{task_id}_cam.npy"
                np.save(cam_file, cam_map)

                # Save result JSON
                result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "pred": pred_label,
                    "probs": probs_dict,
                    "ground_truth": gt_label,
                    "correct": pred_label == gt_label,
                    "classes": classes,
                    "cam_file": str(cam_file),
                    "cam_size": list(cam_size),
                }

                result_file = wsi_result_dir / f"train_{task_id}_result.json"
                with open(result_file, "w", encoding="utf-8") as f:
                    json.dump(result_data, f, ensure_ascii=False, indent=2)

                # Save to database
                db_result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "pred": pred_label,
                    "probs": probs_dict,
                    "extra_metadata": {
                        "ground_truth": gt_label,
                        "correct": pred_label == gt_label,
                        "classes": classes,
                        "task_type": "patch_classification",
                        "cam_file": str(cam_file),
                        "cam_size": list(cam_size),
                        "result_file": str(result_file),
                    },
                }
                await AIResultRepository.create(db, db_result_data)
                results_saved += 1

            except Exception as e:
                logger.warning(f"Failed to process {wsi_id}: {e}")
                continue

    await db.commit()
    logger.info(
        f"Generated AI results for patch classification task {task_id}: {results_saved} images"
    )

    return {
        "message": "AI results generated successfully",
        "task_id": task_id,
        "task_type": "patch_classification",
        "wsi_count": results_saved,
        "classes": classes,
    }
