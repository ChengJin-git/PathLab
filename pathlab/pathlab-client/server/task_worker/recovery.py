from __future__ import annotations

import logging
from typing import Any

from backend.ai.schemas.base import TaskStatus
from backend.common.config import Config
from backend.database import get_db
from backend.database.repositories import (
    DatasetRepository,
    TrainingTaskRepository,
)
from gateway.task_dispatch import (
    build_task_descriptor,
    enqueue_task_descriptor,
    TaskDescriptor,
)

logger = logging.getLogger("task_worker.recovery")


def _is_external_validation_task_id(task_id: object) -> bool:
    return isinstance(task_id, str) and task_id.startswith("extval_")


def _is_batch_inference_task_id(task_id: object) -> bool:
    return isinstance(task_id, str) and task_id.startswith("binfer_")


def _build_batch_inference_descriptor(task: Any) -> TaskDescriptor:
    cfg = task.model_config or {}
    payload: dict[str, Any] = {
        "task_id": task.task_id,
        "model_task_id": cfg.get("model_task_id", ""),
        "model_id": cfg.get("model_id", ""),
        "dataset_id": cfg.get("dataset_id", ""),
    }
    wsi_ids = cfg.get("wsi_ids")
    if wsi_ids is not None:
        payload["wsi_ids"] = wsi_ids
    return build_task_descriptor(
        job_id=task.task_id,
        job_kind="inference",
        handler="inference.batch",
        payload=payload,
    )


def _build_external_validation_descriptor(task: Any, wsi_ids: list[str]) -> TaskDescriptor:
    model_config = task.model_config or {}
    resolved_model_task_type = model_config.get("model_task_type")
    resolved_model_data_type = model_config.get("model_data_type")

    if not resolved_model_task_type or not resolved_model_data_type:
        source_task_id = model_config.get("model_task_id", "")
        if source_task_id:
            resolved_model_task_type = resolved_model_task_type or "wsi_classification"
            resolved_model_data_type = resolved_model_data_type or "wsi"

    resolved_model_task_type = resolved_model_task_type or "wsi_classification"
    resolved_model_data_type = resolved_model_data_type or "wsi"

    payload: dict[str, Any] = {
        "task_id": task.task_id,
        "model_task_id": model_config.get("model_task_id", ""),
        "model_id": model_config.get("model_id", ""),
        "model_classes": task.classes,
        "model_task_type": resolved_model_task_type,
        "model_data_type": resolved_model_data_type,
        "dataset_id": model_config.get("dataset_id", ""),
        "wsi_ids": wsi_ids,
    }
    return build_task_descriptor(
        job_id=task.task_id,
        job_kind="external_validation",
        handler="external_validation.run",
        payload=payload,
    )


def _build_training_descriptor(task: Any, wsi_count: int) -> TaskDescriptor:
    data_type = task.data_group.data_type if task.data_group else "wsi"
    task_type = task.data_group.task_type if task.data_group else "wsi_classification"

    pipeline_kwargs: dict[str, Any] = {
        "task_id": task.task_id,
        "data_type": data_type,
        "input_ref": {
            "kind": "training_task_selection",
            "task_id": task.task_id,
        },
        "wsi_count": wsi_count,
        "preprocessing_config": task.preprocessing_config or {},
        "model_config": task.model_config or {},
        "huggingface_token": None,
        "training_task_type": task_type,
    }

    if data_type == "wsi" and task.status in (
        TaskStatus.EXTRACTING,
        TaskStatus.TRAINING,
    ):
        pipeline_kwargs["patching_complete"] = True

    payload = {
        "task_id": task.task_id,
        "paths_to_check": [],
        "uploads_dir": str(Config.get_uploads_dir()),
        "pipeline_kwargs": pipeline_kwargs,
    }

    return build_task_descriptor(
        job_id=task.task_id,
        job_kind="training",
        handler="training.preflight",
        payload=payload,
    )


async def _enqueue_recovery_descriptor(descriptor: TaskDescriptor) -> None:
    await enqueue_task_descriptor(descriptor)
    logger.info(f"Enqueued recovery descriptor for {descriptor.job_id} ({descriptor.handler})")


async def resume_interrupted_tasks() -> None:
    async for db in get_db():
        try:
            interrupted_tasks = await TrainingTaskRepository.get_interrupted_tasks(db)

            if not interrupted_tasks:
                logger.info("No interrupted tasks to resume")
                return

            logger.info(f"Found {len(interrupted_tasks)} interrupted task(s) to resume")

            from gateway.startup import wait_for_services_ready

            services_ready = await wait_for_services_ready(timeout=60.0)
            if not services_ready:
                logger.error(
                    "Cannot resume interrupted tasks: dependent services are not ready"
                )
                for task in interrupted_tasks:
                    try:
                        await TrainingTaskRepository.update_status(
                            db,
                            task.task_id,
                            TaskStatus.FAILED,
                            error_message="Failed to resume: dependent services not available after system restart",
                        )
                    except Exception as exc:
                        logger.error(
                            f"Failed to mark task {task.task_id} as failed: {exc}"
                        )
                await db.commit()
                return

            for task in interrupted_tasks:
                try:
                    already_resuming = task.status == TaskStatus.RESUMING

                    if already_resuming:
                        logger.info(
                            f"Task {task.task_id} is already in 'resuming' state "
                            f"(claimed by a previous restart but never started), re-submitting to queue"
                        )
                    else:
                        claimed = await TrainingTaskRepository.try_claim_for_resume(
                            db, task.task_id
                        )
                        await db.commit()

                        if not claimed:
                            logger.info(
                                f"Task {task.task_id} already claimed by another instance, skipping"
                            )
                            continue

                    if _is_batch_inference_task_id(task.task_id):
                        descriptor = _build_batch_inference_descriptor(task)
                        await _enqueue_recovery_descriptor(descriptor)
                        logger.info(
                            f"Resumed batch inference task {task.task_id} (claimed by this instance)"
                        )
                        continue

                    if _is_external_validation_task_id(task.task_id):
                        external_validation_dataset_id = (task.model_config or {}).get(
                            "dataset_id", ""
                        )
                        wsi_ids = (
                            await DatasetRepository.get_wsi_ids(
                                db, external_validation_dataset_id
                            )
                            if external_validation_dataset_id
                            else []
                        )
                    else:
                        task_counts = await TrainingTaskRepository.get_wsi_counts_batch(
                            db, [task.task_id]
                        )
                        wsi_count = int(task_counts.get(task.task_id, 0))
                        wsi_ids = []

                    if _is_external_validation_task_id(task.task_id):
                        has_training_inputs = bool(wsi_ids)
                    else:
                        has_training_inputs = wsi_count > 0

                    if not has_training_inputs:
                        logger.warning(
                            f"Task {task.task_id} has no associated WSI IDs, marking as failed"
                        )
                        await TrainingTaskRepository.update_status(
                            db,
                            task.task_id,
                            TaskStatus.FAILED,
                            error_message="No associated WSI IDs found during resume",
                        )
                        await db.commit()
                        continue

                    logger.info(f"Resuming task: {task.task_id} ({task.task_name})")
                    logger.info(f"  - Status before interruption: {task.status}")
                    logger.info(f"  - Progress before interruption: {task.progress}%")
                    logger.info(
                        f"  - WSI count: {len(wsi_ids) if _is_external_validation_task_id(task.task_id) else wsi_count}"
                    )

                    if _is_external_validation_task_id(task.task_id):
                        descriptor = _build_external_validation_descriptor(task, wsi_ids)
                    else:
                        descriptor = _build_training_descriptor(task, wsi_count)

                    await _enqueue_recovery_descriptor(descriptor)

                    logger.info(
                        f"Task {task.task_id} queued for resume (claimed by this instance)"
                    )
                except Exception as exc:
                    logger.error(f"Failed to resume task {task.task_id}: {exc}")
                    try:
                        await TrainingTaskRepository.update_status(
                            db,
                            task.task_id,
                            TaskStatus.FAILED,
                            error_message=f"Failed to resume after system restart: {str(exc)}",
                        )
                        await db.commit()
                    except Exception as update_error:
                        logger.error(f"Failed to update task status: {update_error}")

        except Exception as exc:
            logger.error(f"Failed to check for interrupted tasks: {exc}")
