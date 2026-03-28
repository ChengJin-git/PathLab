"""
Batch Inference on Unlabeled Datasets

Orchestrator (_run_batch_inference) + 4 unlabeled inference handlers.
Called by the GPU task queue with TaskType.BATCH_INFERENCE.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from backend.ai.permission_revocation import clear_revocation, is_permission_revoked
from backend.ai.schemas.base import TaskStatus
from backend.common.progress_store import clear_progress, set_progress
from backend.database.database import safe_session
from backend.database.models import TrainingTask, utc_now
from backend.database.repositories import (
    AIResultRepository,
    DatasetRepository,
    TrainedModelRepository,
    TrainingTaskRepository,
)
from sqlalchemy import update as sql_update

logger = logging.getLogger(__name__)

CHUNK_SIZE = 50


class PermissionRevokedException(Exception):
    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(f"Permission revoked for task {task_id}")


async def _run_batch_inference(
    task_id: str,
    model_task_id: str,
    model_id: str,
    dataset_id: str,
    assigned_device: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """
    Entry point called by the GPU task queue for BATCH_INFERENCE tasks.

    Fetches all WSI ids for the target dataset, processes them in
    CHUNK_SIZE=50 chunks, checks permission revocation between chunks,
    and bulk-writes AIResult rows atomically per chunk.

    Args:
        task_id: The batch inference TrainingTask id (binfer_*)
        model_task_id: The original training task id the model came from
        model_id: The active trained model id
        dataset_id: The target unlabeled dataset id
        assigned_device: CUDA device string (injected by queue, e.g. "cuda:0")
    """

    async def _update_status(
        status: str, progress: int = 0, error: Optional[str] = None
    ):
        values: dict = {"status": status, "progress": progress}
        if error:
            values["error_message"] = error
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            values["finished_at"] = utc_now()
        async with safe_session() as db:
            await db.execute(
                sql_update(TrainingTask)
                .where(TrainingTask.task_id == task_id)
                .values(**values)
            )
            await db.commit()

    try:
        async with safe_session() as db:
            model_task = await TrainingTaskRepository.get_by_id(db, model_task_id)
            if not model_task:
                raise ValueError(f"Model task not found: {model_task_id}")
            trained_model = await TrainedModelRepository.get_by_id(db, model_id)
            if not trained_model:
                raise ValueError(f"Trained model not found: {model_id}")
            dg = model_task.data_group
            task_type = dg.task_type if dg else ""
            dataset_wsi_ids: List[str] = await DatasetRepository.get_wsi_ids(
                db, dataset_id
            )

        if is_permission_revoked(task_id):
            raise PermissionRevokedException(task_id)

        total = len(dataset_wsi_ids)
        logger.info(
            "Batch inference task=%s type=%s slides=%d device=%s",
            task_id,
            task_type,
            total,
            assigned_device,
        )

        await _update_status(TaskStatus.TRAINING, 0)

        for chunk_start in range(0, total, CHUNK_SIZE):
            chunk_ids = dataset_wsi_ids[chunk_start : chunk_start + CHUNK_SIZE]

            if task_type in ("wsi_classification", "classification"):
                chunk_results = await _run_batch_wsi_classification(
                    task_id=task_id,
                    trained_model=trained_model,
                    wsi_ids=chunk_ids,
                    assigned_device=assigned_device,
                    offset=chunk_start,
                    total=total,
                )
            elif task_type == "patch_classification":
                chunk_results = await _run_batch_patch_classification(
                    task_id=task_id,
                    trained_model=trained_model,
                    wsi_ids=chunk_ids,
                    assigned_device=assigned_device,
                    offset=chunk_start,
                    total=total,
                )
            elif task_type in ("wsi_survival", "survival"):
                chunk_results = await _run_batch_wsi_survival(
                    task_id=task_id,
                    trained_model=trained_model,
                    wsi_ids=chunk_ids,
                    assigned_device=assigned_device,
                    offset=chunk_start,
                    total=total,
                )
            elif task_type in ("patch_segmentation", "segmentation"):
                chunk_results = await _run_batch_patch_segmentation(
                    task_id=task_id,
                    trained_model=trained_model,
                    wsi_ids=chunk_ids,
                    assigned_device=assigned_device,
                    offset=chunk_start,
                    total=total,
                )
            else:
                raise ValueError(
                    f"Unsupported task_type for batch inference: {task_type}"
                )

            if is_permission_revoked(task_id):
                if chunk_results:
                    async with safe_session() as db:
                        await AIResultRepository.bulk_create(db, chunk_results)
                        await db.commit()
                raise PermissionRevokedException(task_id)

            if chunk_results:
                async with safe_session() as db:
                    await AIResultRepository.bulk_create(db, chunk_results)
                    await db.commit()

            done = min(chunk_start + CHUNK_SIZE, total)
            progress_pct = int(done / total * 90) if total > 0 else 0
            await set_progress(task_id, progress_pct)

        await clear_progress(task_id)
        await _update_status(TaskStatus.COMPLETED, 100)
        logger.info("Batch inference task=%s completed (%d slides)", task_id, total)

    except PermissionRevokedException:
        logger.warning("Batch inference task=%s: permission revoked", task_id)
        try:
            await _update_status(TaskStatus.FAILED, 0, "Permission revoked")
        except Exception:
            pass
        raise
    except Exception as exc:
        logger.error("Batch inference task=%s failed: %s", task_id, exc, exc_info=True)
        try:
            await _update_status(TaskStatus.FAILED, 0, str(exc))
        except Exception:
            pass
        raise
    finally:
        clear_revocation(task_id)


async def _run_batch_wsi_classification(
    task_id: str,
    trained_model: Any,
    wsi_ids: List[str],
    assigned_device: Optional[str],
    offset: int = 0,
    total: int = 0,
) -> List[dict]:
    """
    WSI-level classification inference on a chunk of unlabeled slides.
    Mirrors _run_external_validation (WSI classification path) without metric computation.
    Returns list of AIResult dicts — caller handles DB write.
    GPU implementation: Task 5, Step 5.6.
    """
    raise NotImplementedError(
        "_run_batch_wsi_classification: GPU implementation pending (Task 5 step 5.6). "
        "See inference_external_validation.py _run_external_validation for the pattern."
    )


async def _run_batch_patch_classification(
    task_id: str,
    trained_model: Any,
    wsi_ids: List[str],
    assigned_device: Optional[str],
    offset: int = 0,
    total: int = 0,
) -> List[dict]:
    """
    Patch-level classification inference on a chunk of unlabeled patches.
    Mirrors _run_external_validation_patch_classification without metric computation.
    Returns list of AIResult dicts — caller handles DB write.
    GPU implementation: Task 5, Step 5.6.
    """
    raise NotImplementedError(
        "_run_batch_patch_classification: GPU implementation pending (Task 5 step 5.6). "
        "See inference_external_validation.py _run_external_validation_patch_classification."
    )


async def _run_batch_wsi_survival(
    task_id: str,
    trained_model: Any,
    wsi_ids: List[str],
    assigned_device: Optional[str],
    offset: int = 0,
    total: int = 0,
) -> List[dict]:
    """
    WSI-level survival risk scoring on a chunk of unlabeled slides.
    No labels required — computes risk score from pre-extracted features.
    Output: AIResult with extra_metadata={"risk_score": float, "risk_group": "high"|"low"}.
    GPU implementation: Task 5, Step 5.6.
    """
    raise NotImplementedError(
        "_run_batch_wsi_survival: GPU implementation pending (Task 5 step 5.6). "
        "See inference_external_validation.py _run_external_validation for survival path."
    )


async def _run_batch_patch_segmentation(
    task_id: str,
    trained_model: Any,
    wsi_ids: List[str],
    assigned_device: Optional[str],
    offset: int = 0,
    total: int = 0,
) -> List[dict]:
    """
    Patch-level segmentation inference on a chunk of unlabeled patches.
    Generates mask files and stores pred_mask_path in metadata.
    Output: AIResult with extra_metadata={"pred_mask_path": str}.
    GPU implementation: Task 5, Step 5.6.
    """
    raise NotImplementedError(
        "_run_batch_patch_segmentation: GPU implementation pending (Task 5 step 5.6). "
        "See inference_external_validation.py _run_external_validation_patch_segmentation."
    )
