"""
Analysis Helper Functions

Shared helper utilities used across classification, survival, and external
validation analysis modules.
"""

import logging
from typing import Any, Optional, Dict, List

from fastapi import HTTPException

from backend.auth.dependencies import (
    check_dataset_gpu_permission,
    check_task_access_permission,
)
from backend.database.repositories import TrainingTaskRepository, WSIRepository

logger = logging.getLogger(__name__)


def _get_random_seed_from_task(task) -> Optional[int]:
    """Extract random seed from task's preprocessing_config.

    The seed is stored in preprocessing_config.split_config.seed and serves
    as both a reproducibility parameter and an invisible watermark for model provenance.
    """
    if not task or not task.preprocessing_config:
        return None
    split_config = task.preprocessing_config.get("split_config", {})
    return split_config.get("seed")


async def _resolve_task_dataset_id(task, db) -> Optional[str]:
    """Resolve dataset_id for a training task.

    For external validation tasks, dataset_id is stored in model_config.
    For regular training tasks, dataset_id must be derived from the task's WSIs
    through the TrainingTaskWSI junction table.

    Args:
        task: TrainingTask object
        db: Database session

    Returns:
        dataset_id string or None
    """
    mc = task.model_config or {}
    # External validation tasks have dataset_id in model_config
    dataset_id = mc.get("dataset_id")
    if dataset_id:
        return dataset_id

    # For regular training tasks, derive from WSIs
    wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task.task_id)
    if wsi_ids:
        first_wsi = await WSIRepository.get_by_id(db, wsi_ids[0])
        if first_wsi and first_wsi.dataset_id:
            return first_wsi.dataset_id

    return None


async def _require_task_access(
    user,
    task,
    db,
    *,
    owner_user_id: Optional[str] = None,
    forbidden_detail: str = "You don't have permission to access this task",
) -> Optional[str]:
    """Require read access to a training task and return its resolved dataset_id."""
    task_dataset_id = await _resolve_task_dataset_id(task, db)
    if not await check_task_access_permission(
        user,
        owner_user_id or task.user_id,
        task_dataset_id,
        db,
    ):
        raise HTTPException(status_code=403, detail=forbidden_detail)
    return task_dataset_id


async def _get_task_with_access(
    task_id: str,
    user,
    db,
    *,
    not_found_detail: Optional[str] = None,
    forbidden_detail: str = "You don't have permission to access this task",
) -> tuple[Any, Optional[str]]:
    """Load a task, require access, and return ``(task, dataset_id)``."""
    task = await TrainingTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(
            status_code=404, detail=not_found_detail or f"Task not found: {task_id}"
        )

    task_dataset_id = await _require_task_access(
        user,
        task,
        db,
        forbidden_detail=forbidden_detail,
    )
    return task, task_dataset_id


async def _require_task_gpu_permission(
    user,
    task,
    db,
    *,
    forbidden_detail: str,
    fallback_role_detail: Optional[str] = None,
) -> Optional[str]:
    """Require GPU permission for a task's dataset, with role fallback when no dataset exists."""
    task_dataset_id = await _resolve_task_dataset_id(task, db)
    if task_dataset_id:
        has_permission = await check_dataset_gpu_permission(user, task_dataset_id, db)
        if not has_permission:
            raise HTTPException(status_code=403, detail=forbidden_detail)
        return task_dataset_id

    if not user.can_use_gpu():
        raise HTTPException(
            status_code=403, detail=fallback_role_detail or forbidden_detail
        )

    return None


def _normalize_label_names(labels: List[str]) -> List[str]:
    return sorted({str(label).strip() for label in labels if str(label).strip()})


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else str(value)


def _coerce_str_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    return [str(v) for v in values if isinstance(v, (str, int, float)) or v is not None]


def _split_case_attention_to_slides_static(
    attention: Optional[Any],
    case_id: str,
    case_wsi_patch_counts: Dict[str, List[int]],
    case_to_wsi: Dict[str, List[str]],
) -> Dict[str, Optional[Any]]:
    """
    Split case-level attention weights back to individual slides.
    Static version for use in results.py inference.
    """
    import numpy as np

    if attention is None:
        wsi_ids = case_to_wsi.get(case_id, [])
        return {wsi_id: None for wsi_id in wsi_ids}

    wsi_ids = case_to_wsi.get(case_id, [])
    patch_counts = case_wsi_patch_counts.get(case_id, [])

    if len(wsi_ids) != len(patch_counts):
        return {wsi_id: None for wsi_id in wsi_ids}

    slide_attentions: Dict[str, Optional["np.ndarray[Any, Any]"]] = {}
    start_idx = 0

    for wsi_id, count in zip(wsi_ids, patch_counts):
        end_idx = start_idx + count
        if attention.ndim == 1:
            slide_attentions[wsi_id] = attention[start_idx:end_idx]
        elif attention.ndim == 2:
            slide_attentions[wsi_id] = attention[:, start_idx:end_idx]
        else:
            slide_attentions[wsi_id] = None
        start_idx = end_idx

    return slide_attentions
