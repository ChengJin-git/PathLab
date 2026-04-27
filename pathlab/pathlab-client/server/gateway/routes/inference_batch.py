"""
Batch Inference on Unlabeled Datasets

Orchestrator (_run_batch_inference) + 4 unlabeled inference handlers.
Called by the GPU task queue with TaskType.BATCH_INFERENCE.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from backend.ai.permission_revocation import (
    PermissionRevokedException,
    clear_revocation,
    is_permission_revoked,
)
from backend.ai.schemas.base import TaskStatus
from backend.database.database import safe_session
from backend.database.models import TrainingTask, utc_now
from backend.database.repositories import (
    AIResultRepository,
    DatasetRepository,
    TrainedModelRepository,
    TrainingTaskRepository,
)
from sqlalchemy import update as sql_update

from gateway.pipeline import ScopedLogger

from .inference_external_validation import (
    _run_external_validation,
    _run_external_validation_patch_classification,
    _run_external_validation_patch_segmentation,
)

logger = logging.getLogger(__name__)


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

    Delegates to the existing external-validation inference implementations,
    but runs them in batch-inference mode so they skip metric analysis and
    write results under the batch task.

    Args:
        task_id: The batch inference TrainingTask id (binfer_*)
        model_task_id: The original training task id the model came from
        model_id: The active trained model id
        dataset_id: The target unlabeled dataset id
        assigned_device: CUDA device string (injected by queue, e.g. "cuda:0")
    """

    async def _update_task_progress(
        status: str,
        progress: int,
        processed_wsi: int = 0,
        results_count: int = 0,
        error: Optional[str] = None,
        total_wsi: int = 0,
    ):
        values: dict[str, Any] = {"status": status, "progress": progress}
        if error:
            values["error_message"] = error
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            values["finished_at"] = utc_now()
        async with safe_session() as db:
            task = await TrainingTaskRepository.get_by_id(db, task_id)
            model_config = dict(task.model_config or {}) if task else {}
            model_config.update(
                {
                    "total_wsi": total_wsi,
                    "processed_wsi": processed_wsi,
                    "results_count": results_count,
                }
            )
            values["model_config"] = model_config
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
            model_data_type = dg.data_type if dg else ""
            dataset_wsi_ids: List[str] = await DatasetRepository.get_wsi_ids(
                db, dataset_id
            )
            await AIResultRepository.delete_by_task_id(db, task_id)
            await db.commit()

        if is_permission_revoked(task_id):
            raise PermissionRevokedException(f"Permission revoked for task {task_id}")

        total = len(dataset_wsi_ids)
        logger.info(
            "Batch inference task=%s type=%s slides=%d device=%s",
            task_id,
            task_type,
            total,
            assigned_device,
        )

        await _update_task_progress(TaskStatus.TRAINING, 0, 0, 0, total_wsi=total)

        if not dataset_wsi_ids:
            await _update_task_progress(
                TaskStatus.COMPLETED, 100, 0, 0, total_wsi=0
            )
            return

        if task_type in ("wsi_classification", "wsi_survival"):
            await _run_external_validation(
                task_id=task_id,
                model_task_id=model_task_id,
                model_id=model_id,
                model_classes=getattr(trained_model, "classes", None),
                model_task_type=task_type,
                model_data_type=model_data_type or "wsi",
                dataset_id=dataset_id,
                wsi_ids=dataset_wsi_ids,
                assigned_device=assigned_device,
                execution_mode="batch_inference",
                auto_trigger_analysis=False,
            )
        elif task_type == "patch_classification":
            await _run_batch_patch_classification(
                task_id=task_id,
                model_task_id=model_task_id,
                model_id=model_id,
                trained_model=trained_model,
                dataset_id=dataset_id,
                wsi_ids=dataset_wsi_ids,
                assigned_device=assigned_device,
                total=total,
                update_task_progress=_update_task_progress,
            )
        elif task_type == "patch_segmentation":
            await _run_batch_patch_segmentation(
                task_id=task_id,
                model_task_id=model_task_id,
                model_id=model_id,
                dataset_id=dataset_id,
                wsi_ids=dataset_wsi_ids,
                assigned_device=assigned_device,
                total=total,
                update_task_progress=_update_task_progress,
            )
        else:
            raise ValueError(f"Unsupported task_type for batch inference: {task_type}")

        logger.info("Batch inference task=%s completed (%d slides)", task_id, total)

    except PermissionRevokedException:
        logger.warning("Batch inference task=%s: permission revoked", task_id)
        try:
            await _update_task_progress(
                TaskStatus.FAILED, 0, error="Permission revoked"
            )
        except Exception:
            pass
        raise
    except Exception as exc:
        logger.error("Batch inference task=%s failed: %s", task_id, exc, exc_info=True)
        try:
            await _update_task_progress(TaskStatus.FAILED, 0, error=str(exc))
        except Exception:
            pass
        raise
    finally:
        clear_revocation(task_id)


async def _run_batch_wsi_classification(
    task_id: str,
    model_task_id: str,
    model_id: str,
    trained_model: Any,
    dataset_id: str,
    wsi_ids: List[str],
    assigned_device: Optional[str],
    total: int = 0,
) -> None:
    await _run_external_validation(
        task_id=task_id,
        model_task_id=model_task_id,
        model_id=model_id,
        model_classes=getattr(trained_model, "classes", None),
        model_task_type="wsi_classification",
        model_data_type="wsi",
        dataset_id=dataset_id,
        wsi_ids=wsi_ids,
        assigned_device=assigned_device,
        execution_mode="batch_inference",
        auto_trigger_analysis=False,
    )


async def _run_batch_patch_classification(
    task_id: str,
    model_task_id: str,
    model_id: str,
    trained_model: Any,
    dataset_id: str,
    wsi_ids: List[str],
    assigned_device: Optional[str],
    total: int = 0,
    update_task_progress=None,
) -> None:
    logger_manager = ScopedLogger(task_id)
    await _run_external_validation_patch_classification(
        task_id=task_id,
        model_task_id=model_task_id,
        model_id=model_id,
        model_classes=getattr(trained_model, "classes", []) or [],
        dataset_id=dataset_id,
        wsi_ids=wsi_ids,
        assigned_device=assigned_device or "",
        logger_manager=logger_manager,
        update_task_progress=update_task_progress,
        execution_mode="batch_inference",
        auto_trigger_analysis=False,
    )


async def _run_batch_wsi_survival(
    task_id: str,
    model_task_id: str,
    model_id: str,
    trained_model: Any,
    dataset_id: str,
    wsi_ids: List[str],
    assigned_device: Optional[str],
    total: int = 0,
    update_task_progress=None,
) -> None:
    await _run_external_validation(
        task_id=task_id,
        model_task_id=model_task_id,
        model_id=model_id,
        model_classes=getattr(trained_model, "classes", None),
        model_task_type="wsi_survival",
        model_data_type="wsi",
        dataset_id=dataset_id,
        wsi_ids=wsi_ids,
        assigned_device=assigned_device,
        execution_mode="batch_inference",
        auto_trigger_analysis=False,
    )


async def _run_batch_patch_segmentation(
    task_id: str,
    model_task_id: str,
    model_id: str,
    dataset_id: str,
    wsi_ids: List[str],
    assigned_device: Optional[str],
    total: int = 0,
    update_task_progress=None,
) -> None:
    logger_manager = ScopedLogger(task_id)
    await _run_external_validation_patch_segmentation(
        task_id=task_id,
        model_task_id=model_task_id,
        model_id=model_id,
        dataset_id=dataset_id,
        wsi_ids=wsi_ids,
        assigned_device=assigned_device or "",
        logger_manager=logger_manager,
        update_task_progress=update_task_progress,
        execution_mode="batch_inference",
        auto_trigger_analysis=False,
    )
