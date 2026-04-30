"""
WSI Classification Inference

Handles GPU inference for WSI-level classification tasks.
Extracted from results.py — no logic changes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, cast as type_cast

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.config import Config
from backend.ai.result_store import (
    AIResultStore,
    ATTENTION_ARTIFACT,
    ATTENTION_RAW_ARTIFACT,
)
from backend.database.repositories import (
    AIResultRepository,
    TrainingTaskRepository,
    WSIRepository,
)
from .analysis_utils import (
    _split_case_attention_to_slides_static,
)
from .inference_base import resolve_checkpoint_paths, resolve_device, report_progress

logger = logging.getLogger(__name__)


async def _run_inference_wsi_classification(
    task,
    wsi_ids: List[str],
    resources: dict[str, Any],
    db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None,
    assigned_device: Optional[str] = None,
):
    """
    Run GPU inference to generate AI results for WSI classification task.

    This is called automatically by the analysis pipeline when AI results are missing.
    Uses pre-extracted features and aggregator model to run inference.
    Saves classification results with attention weights.

    For case-level datasets, features are concatenated by case before inference,
    then attention is split back to per-slide for saving.

    Uses WSIFeatureDataset/CaseFeatureDataset for memory-efficient on-demand loading.

    Args:
        progress_callback: Optional async callback for progress updates (0.0 to 1.0)
    """
    import torch
    import torch.nn.functional as F
    import numpy as np
    from torch.utils.data import DataLoader
    from backend.ai.aggregators import get_aggregator
    from backend.ai.utils.feature_dataset import WSIFeatureDataset, CaseFeatureDataset
    from backend.database.repositories import AIResultRepository

    task_id = task.task_id
    uploads_dir = Config.get_uploads_dir()

    # Check features requirement for WSI tasks
    if not resources["has_features"]:
        raise HTTPException(status_code=400, detail="No features found for this task")

    # Load model
    ckpt_path, config_path = resolve_checkpoint_paths(
        resources, uploads_dir, "aggregator.pth"
    )

    if not ckpt_path.exists():
        raise HTTPException(status_code=500, detail="Model checkpoint not found")

    # Load config
    config = {}
    if config_path.exists():
        with open(config_path, "r") as f:
            config = json.load(f)

    # Check if case-level from config
    aggregation_level = config.get("aggregation_level", "file")
    is_case_level = aggregation_level == "case"

    # Determine classes from WSI labels
    classes: List[str] = []
    for wsi_id in wsi_ids:
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if wsi is not None and isinstance(wsi.label, str) and wsi.label not in classes:
            classes.append(wsi.label)
    classes = sorted(classes)

    if len(classes) == 0:
        raise HTTPException(
            status_code=400, detail="Could not determine classes from WSI labels"
        )

    # Build labels dict
    labels: Dict[str, int] = {}
    for wsi_id in wsi_ids:
        wsi = await WSIRepository.get_by_id(db, wsi_id)
        if wsi is not None and isinstance(wsi.label, str):
            labels[wsi_id] = classes.index(wsi.label)

    # Features directory
    features_dir = uploads_dir / "training" / task_id / "features"

    # Filter wsi_ids to only those with existing features
    valid_wsi_ids = [
        wsi_id for wsi_id in wsi_ids if (features_dir / f"{wsi_id}.pt").exists()
    ]
    if not valid_wsi_ids:
        raise HTTPException(status_code=400, detail="Could not find any feature files")

    device = resolve_device(assigned_device)
    checkpoint = torch.load(ckpt_path, map_location=device)

    # Get aggregator
    aggregator_name = config.get("model", "abmil")
    model = type_cast(
        "Any",
        get_aggregator(
            aggregator_name,
            in_dim=checkpoint["in_dim"],
            num_classes=checkpoint["num_classes"],
        ).to(device),
    )
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()

    has_raw_attention = hasattr(model, "forward_with_raw_attention")

    # Delete old AIResult records before regenerating to avoid duplicates
    deleted_count = await AIResultRepository.delete_by_task_id(db, task_id)
    if deleted_count > 0:
        logger.info(f"Deleted {deleted_count} old AIResult records for task {task_id}")

    # Run inference and save results
    result_store = AIResultStore(uploads_dir)
    results_saved = 0

    feature_extractor = None
    if isinstance(task.preprocessing_config, dict):
        feature_extractor = task.preprocessing_config.get("feature_extractor")

    # Prepare case-level structures if needed
    case_to_wsi: Dict[str, List[str]] = {}
    case_wsi_patch_counts: Dict[str, List[int]] = {}

    with torch.inference_mode():
        if is_case_level:
            # Get case_id mapping and build case-level structures
            wsi_case_map = await TrainingTaskRepository.get_wsi_case_ids(db, task_id)

            # Group WSIs by case_id (only valid ones)
            for wsi_id in valid_wsi_ids:
                case_id = wsi_case_map.get(wsi_id, wsi_id)
                if case_id not in case_to_wsi:
                    case_to_wsi[case_id] = []
                case_to_wsi[case_id].append(wsi_id)

            # Build case_labels
            case_labels: Dict[str, int] = {}
            for case_id, case_wsi_ids in case_to_wsi.items():
                if case_wsi_ids[0] in labels:
                    case_labels[case_id] = labels[case_wsi_ids[0]]

            # Create CaseFeatureDataset for on-demand loading
            case_ids = list(case_to_wsi.keys())
            dataset = CaseFeatureDataset(
                features_dir=features_dir,
                case_ids=case_ids,
                case_to_wsi=case_to_wsi,
                labels=case_labels,
                task_family="classification",
            )
            dataloader = DataLoader(dataset, batch_size=1, shuffle=False)

            logger.info(
                f"Case-level inference: {len(case_ids)} cases from {len(valid_wsi_ids)} slides"
            )
            total_items = len(case_ids)

            # Run inference per case using DataLoader
            for idx, (
                features,
                label,
                case_id,
                batch_wsi_ids,
                batch_patch_counts,
            ) in enumerate(dataloader):
                # Update progress (0.1 to 0.9 range, leaving room for setup/cleanup)
                await report_progress(progress_callback, idx, total_items)
                # Unpack batch (batch_size=1)
                h_features = features.squeeze(0).to(device)
                case_id = case_id[0]
                wsi_ids_in_case = (
                    list(batch_wsi_ids[0])
                    if isinstance(batch_wsi_ids[0], (list, tuple))
                    else [batch_wsi_ids[0]]
                )
                patch_counts = [int(c) for c in batch_patch_counts[0]]
                case_wsi_patch_counts[case_id] = patch_counts

                if has_raw_attention:
                    logits, attention, raw_attention = model.forward_with_raw_attention(
                        h_features
                    )
                else:
                    logits, attention = type_cast("Any", model(h_features))
                    raw_attention = None

                # Forward pass
                probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                pred_idx = int(probs.argmax())
                pred_label = classes[pred_idx]
                probs_dict = {cls: float(probs[i]) for i, cls in enumerate(classes)}

                # Split attention back to per-slide
                attention_np = (
                    attention.cpu().numpy() if attention is not None else None
                )
                raw_attention_np = (
                    raw_attention.cpu().numpy() if raw_attention is not None else None
                )

                slide_attentions = _split_case_attention_to_slides_static(
                    attention_np, case_id, case_wsi_patch_counts, case_to_wsi
                )
                slide_raw_attentions = _split_case_attention_to_slides_static(
                    raw_attention_np, case_id, case_wsi_patch_counts, case_to_wsi
                )

                # Save result for each slide in the case
                for wsi_id in case_to_wsi[case_id]:
                    gt_label = (
                        classes[labels.get(wsi_id, 0)]
                        if wsi_id in labels
                        else "unknown"
                    )

                    slide_att = slide_attentions.get(wsi_id)
                    slide_raw_att = slide_raw_attentions.get(wsi_id)

                    attention_shape = (
                        list(slide_att.shape) if slide_att is not None else None
                    )
                    attention_type = "none"
                    if slide_att is not None:
                        attention_type = (
                            "multi_class" if slide_att.ndim == 2 else "single"
                        )

                    result_data = {
                        "wsi_id": wsi_id,
                        "task_id": task_id,
                        "task_name": task.task_name or task_id,
                        "pred": pred_label,
                        "probs": probs_dict,
                        "ground_truth": gt_label,
                        "correct": pred_label == gt_label,
                        "classes": classes,
                        "feature_extractor": feature_extractor,
                        "aggregator": aggregator_name,
                        "attention_type": attention_type,
                        "attention_shape": attention_shape,
                        "case_id": case_id,
                        "aggregation_level": "case",
                    }

                    arrays = {}
                    if slide_raw_att is not None:
                        arrays[ATTENTION_RAW_ARTIFACT] = slide_raw_att
                    if slide_att is not None:
                        arrays[ATTENTION_ARTIFACT] = slide_att
                    result_store.write_wsi_result(
                        task_id=task_id,
                        wsi_id=wsi_id,
                        result=result_data,
                        arrays=arrays,
                    )
                    attention_file_path = None

                    db_result_data = {
                        "wsi_id": wsi_id,
                        "task_id": task_id,
                        "pred": pred_label,
                        "probs": probs_dict,
                        "extra_metadata": {
                            "ground_truth": gt_label,
                            "correct": pred_label == gt_label,
                            "classes": classes,
                            "task_type": "wsi_classification",
                            "aggregator": aggregator_name,
                            "attention_type": attention_type,
                            "attention_shape": attention_shape,
                            "result_file": None,
                            "attention_file": attention_file_path,
                            "case_id": case_id,
                            "aggregation_level": "case",
                        },
                    }
                    await AIResultRepository.create(db, db_result_data)
                    results_saved += 1
        else:
            # Slide-level inference using WSIFeatureDataset
            dataset = WSIFeatureDataset(
                features_dir=features_dir,
                wsi_ids=valid_wsi_ids,
                labels=labels,
                task_family="classification",
            )
            dataloader = DataLoader(dataset, batch_size=1, shuffle=False)
            total_items = len(valid_wsi_ids)

            for idx, (features, label, wsi_id) in enumerate(dataloader):
                # Update progress (0.1 to 0.9 range, leaving room for setup/cleanup)
                await report_progress(progress_callback, idx, total_items)

                # Unpack batch (batch_size=1)
                h_features = features.squeeze(0).to(device)
                wsi_id = wsi_id[0]

                if has_raw_attention:
                    logits, attention, raw_attention = model.forward_with_raw_attention(
                        h_features
                    )
                else:
                    logits, attention = type_cast("Any", model(h_features))
                    raw_attention = None

                probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                pred_idx = int(probs.argmax())
                pred_label = classes[pred_idx]

                probs_dict = {cls: float(probs[i]) for i, cls in enumerate(classes)}
                gt_label = (
                    classes[labels.get(wsi_id, 0)] if wsi_id in labels else "unknown"
                )

                attention_shape = None
                attention_type = "none"
                attention_file_path = None
                attention_np = None
                if attention is not None:
                    attention_np = attention.cpu().numpy()
                    attention_shape = list(attention_np.shape)
                    attention_type = (
                        "multi_class" if attention_np.ndim == 2 else "single"
                    )

                result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "task_name": task.task_name or task_id,
                    "pred": pred_label,
                    "probs": probs_dict,
                    "ground_truth": gt_label,
                    "correct": pred_label == gt_label,
                    "classes": classes,
                    "feature_extractor": feature_extractor,
                    "aggregator": aggregator_name,
                    "attention_type": attention_type,
                    "attention_shape": attention_shape,
                }

                arrays = {}
                if raw_attention is not None:
                    arrays[ATTENTION_RAW_ARTIFACT] = raw_attention.cpu().numpy()
                if attention_np is not None:
                    arrays[ATTENTION_ARTIFACT] = attention_np
                result_store.write_wsi_result(
                    task_id=task_id,
                    wsi_id=wsi_id,
                    result=result_data,
                    arrays=arrays,
                )

                db_result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "pred": pred_label,
                    "probs": probs_dict,
                    "extra_metadata": {
                        "ground_truth": gt_label,
                        "correct": pred_label == gt_label,
                        "classes": classes,
                        "task_type": "wsi_classification",
                        "aggregator": aggregator_name,
                        "attention_type": attention_type,
                        "attention_shape": attention_shape,
                        "result_file": None,
                        "attention_file": attention_file_path,
                    },
                }
                await AIResultRepository.create(db, db_result_data)
                results_saved += 1

    await db.commit()
    logger.info(
        f"Generated AI results for WSI classification task {task_id}: {results_saved} WSIs"
    )

    return {
        "message": "AI results generated successfully",
        "task_id": task_id,
        "task_type": "wsi_classification",
        "wsi_count": results_saved,
        "classes": classes,
    }
