"""Native patch detection inference for training, batch and external evaluation."""

import asyncio
from pathlib import Path

from backend.common.config import Config
from backend.database import safe_session
from backend.database.repositories import (
    WSIRepository,
    TrainedModelRepository,
    AIResultRepository,
    SegmentationAnnotationRepository,
)
from backend.annotation.coco_utils import merge_coco_datasets
from .inference_base import resolve_device


async def run_detection_inference(
    task_id, model_id, wsi_ids, *, assigned_device=None, progress_callback=None
):
    from backend.ai.detectors.models import load_detector
    from backend.ai.utils.detection_dataset import coco_targets
    from backend.ai.result_store import AIResultStore
    from backend.common.task_dispatch import is_task_cancelled
    from backend.services.result_analysis.sources import index_task
    import torch
    from PIL import Image
    from torchvision.transforms.functional import pil_to_tensor

    async with safe_session() as db:
        trained = await TrainedModelRepository.get_by_id(db, model_id)
        if trained is None:
            raise ValueError("Detection model not found")
        checkpoint = trained.model_path
        from backend.database.repositories import TrainingTaskRepository

        task = await TrainingTaskRepository.get_by_id(db, task_id)
        user_id = task.user_id
        slides = await WSIRepository.get_by_ids(db, wsi_ids)
        inputs = [
            (
                identity,
                slides[identity].wsi_path,
                slides[identity].original_filename,
                slides[identity].dataset_id,
            )
            for identity in wsi_ids
        ]
        payloads = {}
        for dataset_id in {item[3] for item in inputs}:
            records = await SegmentationAnnotationRepository.get_all_by_dataset(
                db, dataset_id, task_type="patch_detection"
            )
            from backend.services.dataset_catalog import merge_task_annotations
            finalized = [merge_task_annotations(records)] if records else []
            payloads[dataset_id] = finalized
    from backend.services.research_prediction import read_manifest

    if read_manifest(Path(checkpoint).parent):
        from .inference_research_images import run_research_images

        if len(payloads) != 1:
            raise ValueError("Research detection inference requires one dataset")
        await run_research_images(
            task_id=task_id,
            model_task_id=trained.task_id,
            model_id=model_id,
            dataset_id=next(iter(payloads)),
            wsi_ids=wsi_ids,
            execution_mode="batch_inference",
            auto_trigger_analysis=False,
            assigned_device=assigned_device,
        )
        return
    device = resolve_device(assigned_device)

    async def gpu_thread(function, *args):
        # Keep the queue lease until a CUDA thread has really stopped, even when
        # the surrounding worker coroutine is cancelled.
        work = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            await asyncio.shield(work)
            raise

    model, classes = await gpu_thread(load_detector, checkpoint, device)
    store = AIResultStore(Config.get_uploads_dir())
    targets_by_dataset = {}
    try:
        for identity, payload in payloads.items():
            if not payload:
                targets_by_dataset[identity] = {}
                continue
            for raw in payload:
                coco_targets(raw, classes)
            payload = merge_coco_datasets(payload)
            targets = coco_targets(payload, classes)
            mapping = {}
            for image in payload["images"]:
                name = Path(image["file_name"]).name
                if name in mapping:
                    raise ValueError(f"Ambiguous COCO image filename: {name}")
                mapping[name] = targets[image["id"]]
            targets_by_dataset[identity] = mapping
        async with safe_session() as db:
            await AIResultRepository.delete_by_task_id(db, task_id)
            await db.commit()
        for index, (identity, path, original_name, dataset_id) in enumerate(inputs):
            from backend.ai.permission_revocation import (
                is_permission_revoked,
                PermissionRevokedException,
            )

            if is_permission_revoked(task_id):
                raise PermissionRevokedException(f"Permission revoked: {task_id}")
            if await is_task_cancelled(task_id):
                raise asyncio.CancelledError("Detection inference cancelled")

            def predict():
                with Image.open(path) as image:
                    tensor = pil_to_tensor(image.convert("RGB")).float() / 255
                    size = list(image.size)
                with torch.inference_mode():
                    output = model([tensor.to(device)])[0]
                keep = output["labels"] > 0
                return {
                    key: output[key][keep].cpu().tolist()
                    for key in ("boxes", "labels", "scores")
                }, size

            prediction, size = await gpu_thread(predict)
            mapping = targets_by_dataset[dataset_id]
            target = mapping.get(original_name, mapping.get(Path(path).name))
            metadata = {
                "task_type": "patch_detection",
                "class_names": classes,
                "aggregation_level": "file",
                "image_size": size,
                "has_ground_truth": target is not None,
                "detection": {"prediction": prediction, "target": target},
            }
            if task_id.startswith("extval_"):
                metadata.update(
                    model_task_id=trained.task_id,
                    validation_task_id=task_id,
                    validation_source=dataset_id,
                )
            await asyncio.to_thread(
                store.write_wsi_result,
                task_id=task_id,
                wsi_id=identity,
                result={"wsi_id": identity, "task_id": task_id, **metadata},
                arrays={},
                finalize=False,
                update_index=False,
            )
            async with safe_session() as db:
                await AIResultRepository.bulk_create(
                    db,
                    [
                        {
                            "task_id": task_id,
                            "wsi_id": identity,
                            "user_id": user_id,
                            "pred": "detection",
                            "probs": None,
                            "extra_metadata": metadata,
                        }
                    ],
                )
                await db.commit()
            if progress_callback:
                await progress_callback((index + 1) / len(inputs))
        await asyncio.to_thread(store.write_task_bundle, task_id=task_id)
        async with safe_session() as db:
            await index_task(db, task_id)
            await db.commit()
    finally:
        model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
