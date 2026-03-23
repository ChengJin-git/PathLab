"""
WSI Survival Inference

Handles GPU inference for WSI-level survival analysis tasks.
Extracted from results.py — no logic changes.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, cast as type_cast

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.config import Config
from backend.database.repositories import (
    TrainingTaskRepository,
    WSIRepository,
)
from backend.preprocessing.heatmap_preview_cache import (
    ensure_recommendation_preview_cache,
)

from .analysis_helpers import (
    _split_case_attention_to_slides_static,
)
from .inference_base import resolve_device, report_progress

logger = logging.getLogger(__name__)


async def _run_inference_wsi_survival(
    task,
    wsi_ids: List[str],
    resources: dict[str, Any],
    db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None,
    assigned_device: Optional[str] = None,
):
    """
    Run GPU inference to generate AI results for WSI survival prediction task.

    This is called automatically by the analysis pipeline when AI results are missing.
    Uses pre-extracted features and aggregator model to compute risk scores,
    hazards, and survival probabilities.

    For case-level datasets, features are concatenated by case before inference,
    then attention is split back to per-slide for saving.

    Uses WSIFeatureDataset/CaseFeatureDataset for memory-efficient on-demand loading.

    Args:
        progress_callback: Optional async callback for progress updates (0.0 to 1.0)
    """
    import torch
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
    model_dir = uploads_dir / "models" / resources["model_id"]
    ckpt_path = model_dir / "aggregator.pth"
    config_path = model_dir / "config.json"

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

    # Features directory
    features_dir = uploads_dir / "training" / task_id / "features"

    # Filter wsi_ids to only those with existing features
    valid_wsi_ids = [
        wsi_id for wsi_id in wsi_ids if (features_dir / f"{wsi_id}.pt").exists()
    ]
    if not valid_wsi_ids:
        raise HTTPException(status_code=400, detail="Could not find any feature files")

    # Get survival metadata (event_time, event_status) for each WSI
    # Batch fetch all WSIs to avoid N+1 query problem
    times_map: Dict[str, float] = {}
    statuses_map: Dict[str, int] = {}

    wsi_map = await WSIRepository.get_by_ids(db, valid_wsi_ids)
    for wsi_id in valid_wsi_ids:
        wsi = wsi_map.get(wsi_id)
        if wsi is not None:
            event_time_value = type_cast("Any", getattr(wsi, "event_time", None))
            event_status_value = type_cast("Any", getattr(wsi, "event_status", None))
            times_map[wsi_id] = (
                float(event_time_value) if event_time_value is not None else 0.0
            )
            statuses_map[wsi_id] = (
                int(event_status_value) if event_status_value is not None else 0
            )
        else:
            times_map[wsi_id] = 0.0
            statuses_map[wsi_id] = 0

    device = resolve_device(assigned_device)
    checkpoint = torch.load(ckpt_path, map_location=device)

    # Get bin_edges from checkpoint (required for survival)
    bin_edges = checkpoint.get("bin_edges", None)
    if bin_edges is None:
        raise HTTPException(
            status_code=500, detail="Checkpoint missing bin_edges for survival task"
        )
    if isinstance(bin_edges, torch.Tensor):
        bin_edges = bin_edges.cpu().numpy()

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

    # Run inference and collect results
    ai_results_root = uploads_dir / "ai_results"

    bin_edges_list = (
        bin_edges.tolist() if hasattr(bin_edges, "tolist") else list(bin_edges)
    )

    # Collect all risk scores first (for median calculation)
    all_risks: List[float] = []
    # Store inference results for later saving
    case_results: List[Dict[str, Any]] = []

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

            # Build case_times and case_statuses
            case_times: Dict[str, float] = {}
            case_statuses: Dict[str, int] = {}
            for case_id, case_wsi_ids in case_to_wsi.items():
                first_wsi = case_wsi_ids[0]
                case_times[case_id] = times_map.get(first_wsi, 0.0)
                case_statuses[case_id] = statuses_map.get(first_wsi, 0)

            # Create CaseFeatureDataset for on-demand loading
            case_ids = list(case_to_wsi.keys())
            dataset = CaseFeatureDataset(
                features_dir=features_dir,
                case_ids=case_ids,
                case_to_wsi=case_to_wsi,
                times=case_times,
                statuses=case_statuses,
                task_type="survival",
            )
            dataloader = DataLoader(dataset, batch_size=1, shuffle=False)

            logger.info(
                f"Case-level inference: {len(case_ids)} cases from {len(valid_wsi_ids)} slides"
            )
            total_items = len(case_ids)

            # Case-level inference using DataLoader
            for idx, (
                features,
                time_val,
                status_val,
                case_id,
                batch_wsi_ids,
                batch_patch_counts,
            ) in enumerate(dataloader):
                # Update progress (0.1 to 0.9 range, leaving room for setup/cleanup)
                await report_progress(progress_callback, idx, total_items)
                # Unpack batch (batch_size=1)
                h_features = features.squeeze(0).to(device)
                case_id = case_id[0]
                patch_counts = [int(c) for c in batch_patch_counts[0]]
                case_wsi_patch_counts[case_id] = patch_counts

                if has_raw_attention:
                    logits, attention, raw_attention = model.forward_with_raw_attention(
                        h_features
                    )
                else:
                    logits, attention = type_cast("Any", model(h_features))
                    raw_attention = None

                hazards = torch.sigmoid(logits).cpu().numpy().flatten()
                surv = np.cumprod(1 - hazards)
                risk_score = float(np.sum(hazards))
                all_risks.append(risk_score)

                attention_np = (
                    attention.cpu().numpy() if attention is not None else None
                )
                raw_attention_np = (
                    raw_attention.cpu().numpy() if raw_attention is not None else None
                )

                case_results.append(
                    {
                        "case_id": case_id,
                        "risk_score": risk_score,
                        "hazards": hazards.tolist(),
                        "surv_probs": surv.tolist(),
                        "event_time": float(time_val.item()),
                        "event_status": int(status_val.item()),
                        "attention_np": attention_np,
                        "raw_attention_np": raw_attention_np,
                    }
                )
        else:
            # Slide-level inference using WSIFeatureDataset
            dataset = WSIFeatureDataset(
                features_dir=features_dir,
                wsi_ids=valid_wsi_ids,
                times=times_map,
                statuses=statuses_map,
                task_type="survival",
            )
            dataloader = DataLoader(dataset, batch_size=1, shuffle=False)
            total_items = len(valid_wsi_ids)

            for idx, (features, time_val, status_val, wsi_id) in enumerate(dataloader):
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

                hazards = torch.sigmoid(logits).cpu().numpy().flatten()
                surv = np.cumprod(1 - hazards)
                risk_score = float(np.sum(hazards))
                all_risks.append(risk_score)

                attention_np = (
                    attention.cpu().numpy() if attention is not None else None
                )
                raw_attention_np = (
                    raw_attention.cpu().numpy() if raw_attention is not None else None
                )

                case_results.append(
                    {
                        "wsi_id": wsi_id,
                        "risk_score": risk_score,
                        "hazards": hazards.tolist(),
                        "surv_probs": surv.tolist(),
                        "event_time": float(time_val.item()),
                        "event_status": int(status_val.item()),
                        "attention_np": attention_np,
                        "raw_attention_np": raw_attention_np,
                    }
                )

    # Calculate median risk score for stratification
    median_risk_score = float(np.median(all_risks)) if all_risks else 0.0

    # Save results
    results_saved = 0

    if is_case_level:
        # Save per-slide results for case-level
        for case_result in case_results:
            case_id = case_result["case_id"]
            risk_score = case_result["risk_score"]
            risk_group = "High Risk" if risk_score >= median_risk_score else "Low Risk"

            # Split attention back to per-slide
            slide_attentions = _split_case_attention_to_slides_static(
                case_result["attention_np"], case_id, case_wsi_patch_counts, case_to_wsi
            )
            slide_raw_attentions = _split_case_attention_to_slides_static(
                case_result["raw_attention_np"],
                case_id,
                case_wsi_patch_counts,
                case_to_wsi,
            )

            for wsi_id in case_to_wsi[case_id]:
                result_dir = ai_results_root / wsi_id
                result_dir.mkdir(parents=True, exist_ok=True)

                slide_att = slide_attentions.get(wsi_id)
                slide_raw_att = slide_raw_attentions.get(wsi_id)

                attention_shape = (
                    list(slide_att.shape) if slide_att is not None else None
                )
                attention_type = "none"
                if slide_att is not None:
                    attention_type = "multi_class" if slide_att.ndim == 2 else "single"

                result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "risk_score": risk_score,
                    "hazards": case_result["hazards"],
                    "surv_probs": case_result["surv_probs"],
                    "event_time": times_map.get(wsi_id, case_result["event_time"]),
                    "event_status": statuses_map.get(
                        wsi_id, case_result["event_status"]
                    ),
                    "bin_edges": bin_edges_list,
                    "aggregator": aggregator_name,
                    "median_risk_score": median_risk_score,
                    "risk_group": risk_group,
                    "attention_type": attention_type,
                    "attention_shape": attention_shape,
                    "case_id": case_id,
                    "aggregation_level": "case",
                }

                result_file = result_dir / f"train_{task_id}_result.json"
                with open(result_file, "w") as f:
                    json.dump(result_data, f, indent=2)

                attention_file_path = None
                if slide_att is not None:
                    att_file = result_dir / f"train_{task_id}_attention.npy"
                    np.save(att_file, slide_att)
                    ensure_recommendation_preview_cache(
                        wsi_id, att_file, Config.get_uploads_dir()
                    )
                    attention_file_path = str(att_file)

                if slide_raw_att is not None:
                    raw_att_file = result_dir / f"train_{task_id}_attention_raw.npy"
                    np.save(raw_att_file, slide_raw_att)

                db_result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "pred": risk_group,
                    "probs": None,
                    "extra_metadata": {
                        "task_type": "survival",
                        "risk_score": risk_score,
                        "risk_group": risk_group,
                        "median_risk_score": median_risk_score,
                        "hazards": case_result["hazards"],
                        "surv_probs": case_result["surv_probs"],
                        "event_time": result_data["event_time"],
                        "event_status": result_data["event_status"],
                        "bin_edges": bin_edges_list,
                        "aggregator": aggregator_name,
                        "attention_type": attention_type,
                        "attention_shape": attention_shape,
                        "result_file": str(result_file),
                        "attention_file": attention_file_path,
                        "case_id": case_id,
                        "aggregation_level": "case",
                    },
                }
                await AIResultRepository.create(db, db_result_data)
                results_saved += 1
    else:
        # Slide-level saving (original logic)
        for slide_result in case_results:
            wsi_id = slide_result["wsi_id"]
            risk_score = slide_result["risk_score"]
            risk_group = "High Risk" if risk_score >= median_risk_score else "Low Risk"

            result_dir = ai_results_root / wsi_id
            result_dir.mkdir(parents=True, exist_ok=True)

            attention_np = slide_result["attention_np"]
            raw_attention_np = slide_result["raw_attention_np"]

            attention_shape = (
                list(attention_np.shape) if attention_np is not None else None
            )
            attention_type = "none"
            if attention_np is not None:
                attention_type = "multi_class" if attention_np.ndim == 2 else "single"

            result_data = {
                "wsi_id": wsi_id,
                "task_id": task_id,
                "risk_score": risk_score,
                "hazards": slide_result["hazards"],
                "surv_probs": slide_result["surv_probs"],
                "event_time": slide_result["event_time"],
                "event_status": slide_result["event_status"],
                "bin_edges": bin_edges_list,
                "aggregator": aggregator_name,
                "median_risk_score": median_risk_score,
                "risk_group": risk_group,
                "attention_type": attention_type,
                "attention_shape": attention_shape,
            }

            result_file = result_dir / f"train_{task_id}_result.json"
            with open(result_file, "w") as f:
                json.dump(result_data, f, indent=2)

            attention_file_path = None
            if attention_np is not None:
                att_file = result_dir / f"train_{task_id}_attention.npy"
                np.save(att_file, attention_np)
                ensure_recommendation_preview_cache(
                    wsi_id, att_file, Config.get_uploads_dir()
                )
                attention_file_path = str(att_file)

            if raw_attention_np is not None:
                raw_att_file = result_dir / f"train_{task_id}_attention_raw.npy"
                np.save(raw_att_file, raw_attention_np)

            db_result_data = {
                "wsi_id": wsi_id,
                "task_id": task_id,
                "pred": risk_group,
                "probs": None,
                "extra_metadata": {
                    "task_type": "survival",
                    "risk_score": risk_score,
                    "risk_group": risk_group,
                    "median_risk_score": median_risk_score,
                    "hazards": slide_result["hazards"],
                    "surv_probs": slide_result["surv_probs"],
                    "event_time": slide_result["event_time"],
                    "event_status": slide_result["event_status"],
                    "bin_edges": bin_edges_list,
                    "aggregator": aggregator_name,
                    "attention_type": attention_type,
                    "attention_shape": attention_shape,
                    "result_file": str(result_file),
                    "attention_file": attention_file_path,
                },
            }
            await AIResultRepository.create(db, db_result_data)
            results_saved += 1

    await db.commit()
    logger.info(
        f"Generated AI results for WSI survival task {task_id}: {results_saved} WSIs"
    )

    return {
        "message": "AI results generated successfully",
        "task_id": task_id,
        "task_type": "wsi_survival",
        "wsi_count": results_saved,
        "median_risk_score": median_risk_score,
    }
