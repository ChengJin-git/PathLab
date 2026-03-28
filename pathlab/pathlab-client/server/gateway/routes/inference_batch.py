"""
Batch Inference Orchestrator

Handles GPU inference over unlabeled datasets for all supported task types:
  - WSI Classification
  - Patch Classification
  - WSI Survival (risk scoring)
  - Patch Segmentation

This module is invoked by the task queue when a BATCH_INFERENCE task is submitted.
It dispatches to the appropriate per-task-type handler based on model_config stored
in the TrainingTask record.

NOTE: This is a stub implementation. Full handler logic will be added in Task 5.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _run_batch_inference(
    task,
    db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None,
    assigned_device: Optional[str] = None,
    **kwargs,
):
    """
    Entry point called by the task queue for BATCH_INFERENCE tasks.

    Reads model_config from the task record to determine:
      - model_task_type (wsi_classification / patch_classification /
                         wsi_survival / patch_segmentation)
      - model_data_type (wsi / patch)
      - model_task_id, model_id, dataset_id

    Then dispatches to the appropriate handler.

    Args:
        task: TrainingTask ORM instance with task_type=BATCH_INFERENCE
        db: Async SQLAlchemy session
        progress_callback: Optional async callback (0.0 → 1.0)
        assigned_device: Optional CUDA device string (e.g. "cuda:0")
        **kwargs: model_task_id, model_id, dataset_id forwarded from submit()
    """
    model_config = task.model_config or {}
    model_task_type = model_config.get("model_task_type", "")

    logger.info(
        "Starting batch inference task=%s type=%s dataset=%s model=%s",
        task.task_id,
        model_task_type,
        model_config.get("dataset_id"),
        model_config.get("model_id"),
    )

    if model_task_type == "wsi_classification":
        await _run_batch_wsi_classification(
            task, db, progress_callback, assigned_device, **kwargs
        )
    elif model_task_type == "patch_classification":
        await _run_batch_patch_classification(
            task, db, progress_callback, assigned_device, **kwargs
        )
    elif model_task_type == "wsi_survival":
        await _run_batch_wsi_survival(
            task, db, progress_callback, assigned_device, **kwargs
        )
    elif model_task_type == "patch_segmentation":
        await _run_batch_patch_segmentation(
            task, db, progress_callback, assigned_device, **kwargs
        )
    else:
        raise ValueError(
            f"Unsupported model_task_type for batch inference: {model_task_type}"
        )


async def _run_batch_wsi_classification(
    task,
    db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None,
    assigned_device: Optional[str] = None,
    **kwargs,
):
    """Run batch inference for WSI-level classification tasks. (Task 5)"""
    raise NotImplementedError(
        "_run_batch_wsi_classification: full implementation pending (Task 5)"
    )


async def _run_batch_patch_classification(
    task,
    db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None,
    assigned_device: Optional[str] = None,
    **kwargs,
):
    """Run batch inference for patch-level classification tasks. (Task 5)"""
    raise NotImplementedError(
        "_run_batch_patch_classification: full implementation pending (Task 5)"
    )


async def _run_batch_wsi_survival(
    task,
    db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None,
    assigned_device: Optional[str] = None,
    **kwargs,
):
    """Run batch inference for WSI-level survival analysis (risk scoring). (Task 5)"""
    raise NotImplementedError(
        "_run_batch_wsi_survival: full implementation pending (Task 5)"
    )


async def _run_batch_patch_segmentation(
    task,
    db: AsyncSession,
    progress_callback: Optional[Callable[[float], Any]] = None,
    assigned_device: Optional[str] = None,
    **kwargs,
):
    """Run batch inference for patch-level segmentation tasks. (Task 5)"""
    raise NotImplementedError(
        "_run_batch_patch_segmentation: full implementation pending (Task 5)"
    )
