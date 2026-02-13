"""
Heatmap utility functions shared across heatmap endpoints.

Extracted from heatmap_routes.py to reduce duplication.
"""
import json
import logging
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

import numpy as np

logger = logging.getLogger(__name__)


def load_result_meta(attention_or_cam_file: Path, suffix: str = "_attention.npy") -> Dict[str, Any]:
    """
    Load result metadata JSON for an attention/CAM file.
    
    Args:
        attention_or_cam_file: Path to _attention.npy or _cam.npy file
        suffix: Suffix to replace (default "_attention.npy")
    
    Returns:
        Dict with result metadata, or empty dict if file doesn't exist
    """
    result_json_file = attention_or_cam_file.with_name(
        attention_or_cam_file.name.replace(suffix, "_result.json")
    )
    if result_json_file.exists():
        try:
            with open(result_json_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load result meta from {result_json_file}: {e}")
    return {}


def find_best_fold(task_id: str, uploads_dir: Path, model_prefixes: Optional[List[str]] = None) -> Optional[str]:
    """
    Find the best fold for a task by reading metrics.json from model directories.
    
    Args:
        task_id: The training task ID
        uploads_dir: Base uploads directory
        model_prefixes: List of model prefixes to check (default: common aggregators)
    
    Returns:
        Best fold key (e.g., 'fold_0') or None if not found
    """
    if model_prefixes is None:
        model_prefixes = [
            "patch_cls",  # Patch classification
            "abmil", "meanmil", "maxmil", "dsmil", "dtfdmil",  # WSI aggregators
            "clam_sb", "clam_mb", "transmil",
        ]
    
    for model_prefix in model_prefixes:
        model_id = f"{model_prefix}_{task_id}"
        metrics_file = uploads_dir / "models" / model_id / "metrics.json"
        if metrics_file.exists():
            try:
                with open(metrics_file, 'r') as f:
                    metrics_data = json.load(f)
                    best_fold = metrics_data.get("best_fold")
                    if best_fold:
                        return best_fold
            except Exception as e:
                logger.warning(f"Failed to read metrics.json for {model_id}: {e}")
    
    return None


def select_attention_file(
    attention_files: List[Path],
    task_id: Optional[str],
    fold_key: Optional[str],
    uploads_dir: Optional[Path] = None
) -> Optional[Path]:
    """
    Select the appropriate attention file based on task_id and fold_key.
    
    Args:
        attention_files: List of attention file paths
        task_id: Optional task ID filter
        fold_key: Optional fold key filter (e.g., 'fold_0')
        uploads_dir: Base uploads directory (needed for best_fold lookup)
    
    Returns:
        Selected attention file path, or None if no match
    """
    if not attention_files:
        return None
    
    if task_id:
        if fold_key:
            # Explicit fold_key specified
            matching = [f for f in attention_files if task_id in f.name and fold_key in f.name]
        else:
            # No fold_key - prefer non-fold files, or find best fold
            matching = [f for f in attention_files if task_id in f.name]
            non_fold = [f for f in matching if "fold_" not in f.name]
            
            if non_fold:
                matching = non_fold
            elif matching and uploads_dir:
                # All files are k-fold - try to find best fold
                best_fold = find_best_fold(task_id, uploads_dir)
                if best_fold:
                    best_matching = [f for f in matching if best_fold in f.name]
                    if best_matching:
                        matching = best_matching
                        logger.info(f"Using best fold {best_fold} for task {task_id}")
        
        return matching[0] if matching else None
    else:
        # No task_id - use most recent
        return sorted(attention_files, key=lambda f: f.stat().st_mtime, reverse=True)[0]


def handle_multi_class_attention(
    attention: np.ndarray,
    result_meta: Dict[str, Any],
    class_idx: Optional[int] = None
) -> Tuple[np.ndarray, Optional[int]]:
    """
    Handle multi-class attention arrays (e.g., from CLAM_MB).
    
    Args:
        attention: Attention array, shape (N,) for single-class or (num_classes, N) for multi-class
        result_meta: Result metadata dict with 'classes' and 'pred' keys
        class_idx: Optional class index to select (defaults to predicted class)
    
    Returns:
        Tuple of (1D attention array, selected_class_idx or None for single-class)
    """
    if attention.ndim != 2:
        return attention, None
    
    # Multi-class attention: shape (num_classes, N)
    num_attention_classes = attention.shape[0]
    classes = result_meta.get("classes", [])
    selected_class_idx = class_idx
    
    if selected_class_idx is None:
        # Default to predicted class
        pred_label = result_meta.get("pred")
        if pred_label and pred_label in classes:
            selected_class_idx = classes.index(pred_label)
        else:
            selected_class_idx = 0
    
    # Validate class_idx
    if selected_class_idx < 0 or selected_class_idx >= num_attention_classes:
        selected_class_idx = 0
    
    logger.info(f"Multi-class attention: using class {selected_class_idx}")
    return attention[selected_class_idx], selected_class_idx


def normalize_attention(attention: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Normalize attention weights for visualization.

    Handles both softmax-normalized and raw logit attention:
    - If already softmax (sums to ~1): apply percentile clipping for contrast
    - If raw logits: apply softmax first, then percentile clipping

    Args:
        attention: 1D attention array

    Returns:
        Tuple of (normalized_attention for visualization [0-1],
                  processed_attention for raw_weight display)
    """
    attention_sum = attention.sum()

    if abs(attention_sum - 1.0) < 0.01:
        # Already softmax normalized - use percentile clipping for visualization
        p_low, p_high = np.percentile(attention, [5, 95])
        attention_clipped = np.clip(attention, p_low, p_high)
        attention_normalized = (attention_clipped - p_low) / (p_high - p_low + 1e-8)
        logger.debug(f"Percentile normalization: p5={p_low:.6f}, p95={p_high:.6f}")
        return attention_normalized, attention
    else:
        # Raw logits - apply softmax first
        attention_shifted = attention - attention.max()
        exp_attention = np.exp(attention_shifted)
        attention_softmax = exp_attention / exp_attention.sum()
        # Then percentile normalization for visualization
        p_low, p_high = np.percentile(attention_softmax, [5, 95])
        attention_clipped = np.clip(attention_softmax, p_low, p_high)
        attention_normalized = (attention_clipped - p_low) / (p_high - p_low + 1e-8)
        logger.debug(f"Softmax + percentile normalization: p5={p_low:.6f}, p95={p_high:.6f}")
        return attention_normalized, attention_softmax

