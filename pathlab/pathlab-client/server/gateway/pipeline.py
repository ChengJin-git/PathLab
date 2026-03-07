"""
Training pipeline implementation
Handles the background training workflow

Synchronous HTTP Architecture:
- Gateway sends HTTP request to AI service and waits for completion
- Timeout is configurable via Settings (default: 3 days)
- AI service runs training synchronously and returns result
- On timeout, Gateway calls AI service to cancel training and release GPU
"""
import asyncio
import httpx
import os
import traceback
from pathlib import Path
from typing import List, Dict, Set, Tuple
from contextlib import asynccontextmanager

from backend.ai.schemas.base import TaskStatus
from backend.common.coco_utils import (
    extract_coco_wsi_label_sets,
    materialize_coco_to_disk,
    merge_coco_datasets,
)
from backend.database.repositories import TrainingTaskRepository, SegmentationAnnotationRepository, WSIRepository
from backend.database.utils.training_logger import TrainingLogger
from backend.common.config import Config
from .dependencies import logger, PREPROCESSING_SERVICE_URL, AI_SERVICE_URL
from .utils import cancel_ai_service_training


_UNSUPPORTED_PATCH_SEGMENTATION_LOSS_TOKENS = frozenset({
    "ce",
    "softcrossentropyloss",
    "crossentropy",
    "crossentropyloss",
})


def _normalize_patch_segmentation_loss_name(loss_name: str) -> str:
    return "".join(ch for ch in str(loss_name).lower() if ch.isalnum())


def _validate_patch_segmentation_loss_names(loss_names: List[str]) -> None:
    unsupported_losses = [
        loss_name for loss_name in loss_names
        if _normalize_patch_segmentation_loss_name(loss_name) in _UNSUPPORTED_PATCH_SEGMENTATION_LOSS_TOKENS
    ]
    if unsupported_losses:
        unsupported_display = ", ".join(sorted(set(unsupported_losses)))
        raise ValueError(
            "Patch segmentation does not support Cross Entropy losses "
            f"({unsupported_display}). This training path uses multi-channel float masks; "
            "please use Dice/Jaccard/Tversky/Focal/Lovasz/BCE/MCC losses instead."
        )


def get_training_timeout() -> int:
    """Get the configured training task timeout in seconds."""
    return Config.get_task_timeout()


def _build_segmentation_wsi_lookups(wsis) -> Tuple[Dict[str, str], Dict[str, str]]:
    exact_lookup: Dict[str, str] = {}
    stem_candidates: Dict[str, Set[str]] = {}

    for wsi in wsis:
        candidate_names = []
        if getattr(wsi, "original_filename", None):
            candidate_names.append(str(wsi.original_filename))
        if getattr(wsi, "wsi_path", None):
            candidate_names.append(Path(str(wsi.wsi_path)).name)

        for candidate in candidate_names:
            normalized = Path(candidate).name.strip().lower()
            if not normalized:
                continue
            exact_lookup.setdefault(normalized, wsi.wsi_id)
            stem_candidates.setdefault(Path(normalized).stem, set()).add(wsi.wsi_id)

    stem_lookup = {
        stem: next(iter(wsi_ids))
        for stem, wsi_ids in stem_candidates.items()
        if len(wsi_ids) == 1
    }
    return exact_lookup, stem_lookup


async def _load_segmentation_coco_payload(db, dataset_id: str) -> dict:
    dataset_level_record = await SegmentationAnnotationRepository.get_dataset_level_by_dataset(
        db,
        dataset_id,
        include_drafts=False,
    )
    if dataset_level_record and isinstance(dataset_level_record.annotations, dict):
        return dataset_level_record.annotations

    records = await SegmentationAnnotationRepository.get_all_by_dataset(
        db,
        dataset_id,
        include_drafts=False,
    )
    if not records:
        return {}

    dataset_level_record = next(
        (record for record in records if record.annotation_id == f"annot_{dataset_id}"),
        None,
    )
    payloads = [dataset_level_record.annotations] if dataset_level_record else [
        record.annotations for record in records if isinstance(record.annotations, dict)
    ]
    return merge_coco_datasets(payloads)


async def _load_segmentation_training_inputs(
    db,
    task_id: str,
    wsi_ids: List[str],
) -> Tuple[List, dict, Dict[str, List[str]]]:
    wsi_map = await WSIRepository.get_by_ids(db, wsi_ids)
    wsis = [wsi_map[wsi_id] for wsi_id in wsi_ids if wsi_id in wsi_map]
    if not wsis:
        raise ValueError("No patch images found for segmentation training task")

    dataset_ids = {wsi.dataset_id for wsi in wsis if wsi.dataset_id}
    if len(dataset_ids) != 1:
        raise ValueError("Segmentation training requires all selected images to belong to the same dataset")

    dataset_id = next(iter(dataset_ids))
    coco_data = await _load_segmentation_coco_payload(db, dataset_id)
    if not coco_data.get("images"):
        raise ValueError(f"No finalized COCO annotations found for segmentation dataset {dataset_id}")

    splits_map = await TrainingTaskRepository.get_wsi_ids_by_split(db, task_id)
    return wsis, coco_data, splits_map


def _build_split_coco_payload(
    coco_data: dict,
    allowed_wsi_ids: Set[str],
    exact_lookup: Dict[str, str],
    stem_lookup: Dict[str, str],
    wsi_to_relative_path: Dict[str, str],
) -> dict:
    allowed_image_ids: Set[int] = set()
    images = []

    for image in coco_data.get("images") or []:
        if not isinstance(image, dict):
            continue
        normalized_name = Path(str(image.get("file_name") or "")).name.strip().lower()
        if not normalized_name:
            continue
        wsi_id = exact_lookup.get(normalized_name) or stem_lookup.get(Path(normalized_name).stem)
        if wsi_id not in allowed_wsi_ids:
            continue

        image_copy = dict(image)
        image_copy["file_name"] = wsi_to_relative_path.get(wsi_id, image_copy.get("file_name"))
        images.append(image_copy)
        allowed_image_ids.add(image_copy.get("id"))

    annotations = [
        dict(annotation)
        for annotation in (coco_data.get("annotations") or [])
        if isinstance(annotation, dict) and annotation.get("image_id") in allowed_image_ids
    ]

    payload = {
        "images": images,
        "annotations": annotations,
        "categories": coco_data.get("categories", []),
    }
    if coco_data.get("info") is not None:
        payload["info"] = coco_data.get("info")
    if coco_data.get("licenses") is not None:
        payload["licenses"] = coco_data.get("licenses")
    return payload


def _prepare_segmentation_training_dataset(
    task_id: str,
    wsis: List,
    coco_data: dict,
    splits_map: Dict[str, List[str]],
    preprocessing_config: Dict,
) -> Tuple[Dict, int]:
    exact_lookup, stem_lookup = _build_segmentation_wsi_lookups(wsis)
    label_sets = extract_coco_wsi_label_sets(coco_data, exact_lookup, stem_lookup)
    classes = sorted({label for labels in label_sets.values() for label in labels})
    if not classes:
        raise ValueError("Segmentation dataset has no COCO categories available for training")

    split_config = preprocessing_config.get("split_config") or {}
    strategy = split_config.get("strategy", "random")
    if strategy == "k_fold":
        raise ValueError("Patch segmentation training does not support k-fold splits yet")

    expected_splits = ["train", "val", "test"]
    if not all(split_name in splits_map for split_name in expected_splits):
        raise ValueError("Segmentation training requires train/val/test split assignments")

    image_parents = [str(Path(str(wsi.wsi_path)).resolve().parent) for wsi in wsis if wsi.wsi_path]
    image_root = Path(os.path.commonpath(image_parents)) if image_parents else Config.get_uploads_dir()
    wsi_to_relative_path = {
        wsi.wsi_id: os.path.relpath(str(Path(str(wsi.wsi_path)).resolve()), str(image_root))
        for wsi in wsis
        if wsi.wsi_path
    }

    split_dir = Config.get_uploads_dir() / task_id / "segmentation_splits"
    split_dir.mkdir(parents=True, exist_ok=True)
    dataset_config: Dict[str, Dict[str, str]] = {"classes": len(classes), "channels": 3}

    for split_name in expected_splits:
        split_payload = _build_split_coco_payload(
            coco_data,
            set(splits_map.get(split_name, [])),
            exact_lookup,
            stem_lookup,
            wsi_to_relative_path,
        )
        split_path = split_dir / f"{split_name}.json"
        materialize_coco_to_disk(split_payload, split_path)
        dataset_config[split_name] = {
            "image_dir": str(image_root),
            "annotations_path": str(split_path),
        }

    return dataset_config, len(classes)


async def _call_ai_service(
    logger_manager: 'ScopedLogger',
    task_id: str,
    endpoint: str,
    payload: dict,
    operation_name: str,
    timeout: int = None,
) -> dict:
    """
    Unified AI service HTTP call with standardized error handling.

    Args:
        logger_manager: ScopedLogger instance for database logging
        task_id: Training task ID
        endpoint: Full URL endpoint to call
        payload: JSON payload to send
        operation_name: Human-readable operation name for error messages
        timeout: Optional timeout in seconds (defaults to configured training timeout)

    Returns:
        Response JSON data

    Raises:
        Exception: On HTTP errors, timeouts, or connection failures
    """
    timeout = timeout or get_training_timeout()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(endpoint, json=payload)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        body = e.response.text if e.response is not None else str(e)
        async with logger_manager.session() as (logger, db):
            await logger.error(
                f"AI service {operation_name} failed: {e}",
                metadata={"status_code": e.response.status_code if e.response else None, "body": body}
            )
        raise
    except httpx.TimeoutException as e:
        async with logger_manager.session() as (logger, db):
            await logger.error(
                f"{operation_name} timeout after {timeout} seconds. Requesting AI service to cancel and release GPU.",
                metadata={"timeout_seconds": timeout, "error": str(e)}
            )
        await cancel_ai_service_training(task_id)
        raise Exception(f"{operation_name} timeout after {timeout // 3600} hours. Task cancelled.") from e
    except httpx.RequestError as e:
        async with logger_manager.session() as (logger, db):
            await logger.error(
                f"Failed to connect to AI service for {operation_name}: {e}",
                metadata={"ai_service_url": AI_SERVICE_URL, "error": str(e)}
            )
        raise Exception(f"AI service unavailable at {AI_SERVICE_URL}. Please ensure the AI service is running.") from e


class ScopedLogger:
    """
    Helper to create short-lived DB sessions for logging and status updates.
    Ensures that we don't hold a DB connection open during long-running HTTP calls.

    Includes timeout protection to prevent indefinite blocking on database operations.
    """

    def __init__(self, task_id: str):
        self.task_id = task_id
        from backend.database import async_session_maker
        self.session_maker = async_session_maker

    @asynccontextmanager
    async def session(self):
        """Yields (logger, db_session) and handles commit/close.

        Includes timeout protection to prevent indefinite blocking on
        long-running database operations.
        """
        timeout = Config.DB_OPERATION_TIMEOUT
        try:
            # Wrap the entire session operation with a timeout
            async with asyncio.timeout(timeout):
                async with self.session_maker() as db:
                    training_logger = TrainingLogger(self.task_id, db)
                    try:
                        yield training_logger, db
                        await db.commit()
                    except Exception:
                        await db.rollback()
                        raise
                    finally:
                        await training_logger.close()
        except asyncio.TimeoutError:
            # Log to console since we can't use the database
            logger.error(
                f"[{self.task_id}] Database operation timed out after {timeout}s."
            )
            raise Exception(
                f"Database operation timed out after {timeout}s. Please retry the operation."
            )


async def run_training_pipeline(
    task_id: str,
    data_type: str,
    wsi_ids: List[str],
    preprocessing_config: Dict,
    model_config: Dict,
    huggingface_token: str = None,
    training_task_type: str = "classification",  # "classification", "survival", or "segmentation"
    assigned_device: str = None,  # GPU device assigned by task queue (e.g., "cuda:0")
    user_id: str = None,  # User who submitted the task (for permission checks)
    user_is_admin: bool = False,  # Whether the submitting user is admin
):
    """
    Run the training pipeline based on data level:

    WSI-level:
    1. Patch extraction for all WSI slides
    2. Feature extraction via AI service
    3. ABMIL model training via AI service

    Patch-level:
    1. Skip patch extraction (images are already patches)
    2. Skip feature extraction (model processes images directly)
    3. Model training (TODO)
    """
    # Use ScopedLogger to manage granular sessions
    logger_manager = ScopedLogger(task_id)

    try:
        # Initialize training and log start
        async with logger_manager.session() as (logger, db):
            await logger.info(f"Starting training pipeline for task: {task_id} (data_type: {data_type})")

        # For patch-level tasks, route based on training_task_type
        if data_type == 'patch':
            if training_task_type == "segmentation":
                preprocessing_config = dict(preprocessing_config or {})

                # Get segmentation-specific training parameters
                architecture = model_config.get('architecture', 'unet')
                backbone = model_config.get('backbone', 'resnet50')
                loss_names = model_config.get('loss_names', ['DiceLoss', 'JaccardLoss'])
                loss_weights = model_config.get('loss_weights', [0.5, 0.5])
                _validate_patch_segmentation_loss_names(loss_names)
                epochs = int(model_config.get('epochs', 100))
                lr = float(model_config.get('learning_rate', 0.0001))
                batch_size = int(model_config.get('batch_size', 16))
                optimizer = model_config.get('optimizer', 'adamw')
                early_stopping_patience = int(model_config.get('early_stopping_patience', 15))
                seed = preprocessing_config.get('split_config', {}).get('seed', 42)

                # Keep DB work short: fetch DB-backed inputs in one scoped session,
                # then build split JSON on disk outside the timed DB session.
                async with logger_manager.session() as (logger, db):
                    await logger.info("Patch-level segmentation task detected")
                    wsis, coco_data, splits_map = await _load_segmentation_training_inputs(
                        db=db,
                        task_id=task_id,
                        wsi_ids=wsi_ids,
                    )

                segmentation_dataset, num_classes = _prepare_segmentation_training_dataset(
                    task_id=task_id,
                    wsis=wsis,
                    coco_data=coco_data,
                    splits_map=splits_map,
                    preprocessing_config=preprocessing_config,
                )
                preprocessing_config["segmentation_dataset"] = segmentation_dataset

                async with logger_manager.session() as (logger, db):
                    await TrainingTaskRepository.update_preprocessing_config(
                        db,
                        task_id,
                        preprocessing_config,
                    )

                    await logger.info(
                        "Prepared segmentation dataset splits for training",
                        metadata={
                            "num_classes": num_classes,
                            "train_annotations_path": segmentation_dataset["train"]["annotations_path"],
                            "val_annotations_path": segmentation_dataset["val"]["annotations_path"],
                            "test_annotations_path": segmentation_dataset["test"]["annotations_path"],
                        }
                    )

                    await logger.info(
                        f"Training {architecture} with {backbone} backbone",
                        metadata={"architecture": architecture, "backbone": backbone,
                                  "loss_names": loss_names, "epochs": epochs, "lr": lr}
                    )

                    # Update status to training
                    await TrainingTaskRepository.update_status(db, task_id, TaskStatus.TRAINING, progress=50)

                # Call AI service for patch segmentation training
                await _call_ai_service(
                    logger_manager=logger_manager,
                    task_id=task_id,
                    endpoint=f"{AI_SERVICE_URL}/api/ai/training/patch_segmentation",
                    payload={
                        "task_id": task_id,
                        "architecture": architecture,
                        "backbone": backbone,
                        "loss_names": loss_names,
                        "loss_weights": loss_weights,
                        "epochs": epochs,
                        "lr": lr,
                        "batch_size": batch_size,
                        "optimizer": optimizer,
                        "early_stopping_patience": early_stopping_patience,
                        "device": assigned_device,
                        "seed": seed,
                        "num_classes": num_classes,
                    },
                    operation_name="patch segmentation training"
                )

                async with logger_manager.session() as (logger, db):
                    await logger.info("Patch segmentation training completed successfully")
                    await TrainingTaskRepository.update_status(db, task_id, TaskStatus.COMPLETED, progress=100)
                return

            # Patch Classification: use Feature Extractor + Linear Probe training
            async with logger_manager.session() as (logger, db):
                await logger.info("Patch-level task detected - using Feature Extractor + Classifier Head")

                # Get training parameters
                feature_extractor = preprocessing_config.get('feature_extractor', 'resnet50')
                classifier = model_config.get('classifier', 'linear')
                epochs = int(model_config.get('epochs', 50))
                lr = float(model_config.get('learning_rate', 0.0002))
                batch_size = int(model_config.get('batch_size', 64))
                optimizer = model_config.get('optimizer', 'adam')
                auto_balance = bool(model_config.get('auto_balance', False))
                early_stopping_patience = int(model_config.get('early_stopping_patience', 10))
                seed = preprocessing_config.get('split_config', {}).get('seed', 42)

                await logger.info(
                    f"Training {classifier} classifier with {feature_extractor} backbone",
                    metadata={"feature_extractor": feature_extractor, "classifier": classifier, "epochs": epochs, "lr": lr, "optimizer": optimizer, "auto_balance": auto_balance}
                )

                # Update status to training
                await TrainingTaskRepository.update_status(db, task_id, TaskStatus.TRAINING, progress=50)

            # Call AI service for patch classification training (synchronous, waits for completion)
            await _call_ai_service(
                logger_manager=logger_manager,
                task_id=task_id,
                endpoint=f"{AI_SERVICE_URL}/api/ai/training/patch_classification",
                payload={
                    "task_id": task_id,
                    "epochs": epochs,
                    "lr": lr,
                    "feature_extractor": feature_extractor,
                    "classifier": classifier,
                    "batch_size": batch_size,
                    "huggingface_token": huggingface_token or "",
                    "optimizer": optimizer,
                    "auto_balance": auto_balance,
                    "early_stopping_patience": early_stopping_patience,
                    "device": assigned_device,
                    "seed": seed,
                },
                operation_name="patch classification training"
            )

            async with logger_manager.session() as (logger, db):
                await logger.info("Patch classification training completed successfully")
                await TrainingTaskRepository.update_status(db, task_id, TaskStatus.COMPLETED, progress=100)
            return

        # Step 1: Patch extraction for WSI-level tasks
        # Note: patch_size and stride are now auto-determined by PrePATH-style tiling
        # based on WSI magnification to ensure consistent physical coverage (~128μm)
        total_wsi = len(wsi_ids)
        level = preprocessing_config.get('level', 0)

        # Tissue segmentation parameters (defaults match constants/training.ts)
        sthresh = preprocessing_config.get('sthresh', 8)
        mthresh = preprocessing_config.get('mthresh', 7)
        close = preprocessing_config.get('close', 4)
        use_otsu = preprocessing_config.get('use_otsu', False)
        contour_fn = preprocessing_config.get('contour_fn', 'four_pt')
        use_padding = preprocessing_config.get('use_padding', True)

        # Filter parameters
        a_t = preprocessing_config.get('a_t', 1)
        a_h = preprocessing_config.get('a_h', 256)
        max_n_holes = preprocessing_config.get('max_n_holes', 100)

        async with logger_manager.session() as (logger, db):
            await TrainingTaskRepository.update_status(db, task_id, TaskStatus.PATCHING, progress=0)
            await logger.info(f"Extracting patches from {total_wsi} WSI slides")
            await logger.info(
                f"Level: {level}",
                metadata={"level": level}
            )

        for idx, wsi_id in enumerate(wsi_ids, 1):
            # Yield control to allow cancellation signals to be processed
            # This is important when cache hits cause fast iterations
            await asyncio.sleep(0)

            try:
                async with logger_manager.session() as (logger, db):
                    await logger.info(
                        f"Processing WSI {idx}/{total_wsi}: {wsi_id}",
                        metadata={"wsi_index": idx, "total_wsi": total_wsi, "wsi_id": wsi_id}
                    )

                # Call preprocessing service to compute patches (NO DB SESSION HELD)
                # Note: patch_size and stride are auto-determined by backend based on WSI MPP
                # force_recompute=False allows reusing cached coordinates
                # if ALL parameters match (including seg_params and filter_params)
                #
                # Retry logic: If the preprocessing worker crashes (e.g., C library segfault
                # during mask visualization), the HTTP connection is severed, causing
                # RemoteProtocolError. On retry, cached coordinates are returned instantly.
                max_retries = 3
                result = None
                for attempt in range(1, max_retries + 1):
                    try:
                        async with httpx.AsyncClient(timeout=600.0) as client:
                            response = await client.post(
                                f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/compute_patches",
                                params={
                                    "level": level,
                                    "force_recompute": False,  # Allow cache reuse
                                    "sthresh": sthresh,
                                    "mthresh": mthresh,
                                    "close": close,
                                    "use_otsu": use_otsu,
                                    "contour_fn": contour_fn,
                                    "use_padding": use_padding,
                                    "a_t": a_t,
                                    "a_h": a_h,
                                    "max_n_holes": max_n_holes,
                                    "save_mask": True,
                                },
                            )
                            response.raise_for_status()
                            result = response.json()
                        break  # Success, exit retry loop
                    except (httpx.RemoteProtocolError, httpx.ConnectError) as retry_err:
                        # Worker crash (segfault) or connection refused (worker restarting)
                        if attempt < max_retries:
                            wait_secs = attempt * 3  # 3s, 6s backoff
                            async with logger_manager.session() as (logger, db):
                                await logger.warning(
                                    f"[{idx}/{total_wsi}] compute_patches attempt {attempt}/{max_retries} "
                                    f"failed for {wsi_id}: {type(retry_err).__name__}. "
                                    f"Retrying in {wait_secs}s (cached coords will be used on retry)...",
                                    metadata={"wsi_id": wsi_id, "attempt": attempt, "error": str(retry_err)}
                                )
                            await asyncio.sleep(wait_secs)
                        else:
                            raise  # Final attempt failed, propagate to outer except

                num_patches = result.get('num_patches', 0)
                cached = result.get('cached', False)

                async with logger_manager.session() as (logger, db):
                    if cached:
                        await logger.info(
                            f"[{idx}/{total_wsi}] Coords cache hit for {wsi_id}",
                            metadata={"wsi_id": wsi_id, "num_patches": num_patches, "cached": True}
                        )
                    else:
                        await logger.info(
                            f"[{idx}/{total_wsi}] Extracted {num_patches} patches from {wsi_id}",
                            metadata={"wsi_id": wsi_id, "num_patches": num_patches, "cached": False}
                        )

                    # Update progress (0-33%)
                    progress = int((idx / total_wsi) * 33)
                    await TrainingTaskRepository.update_status(db, task_id, TaskStatus.PATCHING, progress=progress)

            except Exception as e:
                err_type = type(e).__name__
                err_msg = str(e) or repr(e)
                err_tb = traceback.format_exc()
                # For HTTP errors, include the response body for debugging
                resp_body = ""
                if isinstance(e, httpx.HTTPStatusError):
                    try:
                        resp_body = e.response.text[:1000]
                    except Exception:
                        resp_body = "(unable to read response body)"
                async with logger_manager.session() as (logger, db):
                    await logger.error(
                        f"Failed to extract patches from {wsi_id}: [{err_type}] {err_msg}",
                        metadata={
                            "wsi_id": wsi_id,
                            "error": err_msg,
                            "error_type": err_type,
                            "response_body": resp_body,
                            "traceback": err_tb,
                        }
                    )
                raise

        async with logger_manager.session() as (logger, db):
            await logger.info(f"Patch extraction completed for all {total_wsi} WSI slides")

        # Step 2: Feature extraction via AI service
        feature_extractor = preprocessing_config.get('feature_extractor', 'resnet50')
        feature_batch_size = preprocessing_config.get('feature_batch_size', 64)  # Match constants/training.ts

        async with logger_manager.session() as (logger, db):
            await logger.info(f"Calling AI service for feature extraction (using {feature_extractor})")

        # Call AI Service (NO DB SESSION HELD)
        await _call_ai_service(
            logger_manager=logger_manager,
            task_id=task_id,
            endpoint=f"{AI_SERVICE_URL}/api/ai/training/extract_features",
            payload={
                "task_id": task_id,
                "wsi_ids": wsi_ids,
                "feature_extractor": feature_extractor,
                "batch_size": feature_batch_size,
                "force_recompute": False,
                "huggingface_token": huggingface_token or "",
                "preprocessing_config": preprocessing_config,
                "device": assigned_device,
            },
            operation_name="feature extraction"
        )

        async with logger_manager.session() as (logger, db):
            await logger.info("Feature extraction completed for all WSI")

        # Step 3: WSI classification training via AI service (supports multiple aggregators)
        epochs = int(model_config.get('epochs', 50))
        lr = float(model_config.get('learning_rate', 0.0002))
        aggregator = model_config.get('aggregator', 'abmil')
        optimizer = model_config.get('optimizer', 'adam')
        auto_balance = bool(model_config.get('auto_balance', False))
        early_stopping_patience = int(model_config.get('early_stopping_patience', 20))
        seed = preprocessing_config.get('split_config', {}).get('seed', 42)

        async with logger_manager.session() as (logger, db):
            await logger.info(f"Calling AI service to train {aggregator.upper()} model")

        # Use correct endpoint based on training_task_type
        if training_task_type == "survival":
            endpoint = f"{AI_SERVICE_URL}/api/ai/training/wsi_survival"
            payload = {
                "task_id": task_id,
                "epochs": epochs,
                "lr": lr,
                "aggregator": aggregator,
                "feature_extractor": feature_extractor,
                "num_bins": 4,  # Standard for manual NLLLoss
                "optimizer": optimizer,
                "early_stopping_patience": early_stopping_patience,
                "device": assigned_device,
                "seed": seed,
                # Note: auto_balance not applicable for survival (no class weights)
            }
        else:
            endpoint = f"{AI_SERVICE_URL}/api/ai/training/wsi_classification"
            payload = {
                "task_id": task_id,
                "epochs": epochs,
                "lr": lr,
                "aggregator": aggregator,
                "feature_extractor": feature_extractor,
                "optimizer": optimizer,
                "auto_balance": auto_balance,
                "early_stopping_patience": early_stopping_patience,
                "device": assigned_device,
                "seed": seed,
            }

        # Send training request (synchronous, waits for completion) (NO DB SESSION HELD)
        await _call_ai_service(
            logger_manager=logger_manager,
            task_id=task_id,
            endpoint=endpoint,
            payload=payload,
            operation_name="WSI training"
        )

        async with logger_manager.session() as (logger, db):
            await logger.info("Training pipeline completed successfully")
            # Do not overwrite status here; AI service sets progress to 100 and status to completed

    except asyncio.CancelledError:
        # Task was cancelled via TaskQueueManager.cancel_task()
        # Status should already be set to 'cancelled' in queue.py
        async with logger_manager.session() as (logger, db):
            await logger.info("Training pipeline cancelled")
        # Re-raise to let asyncio handle the cancellation properly
        raise

    except Exception as e:
        # Don't reset progress on failure - keep the progress at the point of failure
        # Only update to 'failed' if not already cancelled
        err_type = type(e).__name__
        err_msg = str(e) or repr(e)
        err_tb = traceback.format_exc()

        # For HTTPStatusError, extract the actual error detail from the response body
        # instead of the generic "Server error '500 Internal Server Error' for url ..." message
        if isinstance(e, httpx.HTTPStatusError) and e.response is not None:
            try:
                import json
                body = json.loads(e.response.text)
                if isinstance(body, dict) and "detail" in body:
                    err_msg = body["detail"]
            except Exception:
                # Fallback: use raw response text if JSON parsing fails
                try:
                    err_msg = e.response.text[:2000] or err_msg
                except Exception:
                    pass

        async with logger_manager.session() as (logger, db):
            await logger.error(
                f"Training pipeline failed: [{err_type}] {err_msg}",
                metadata={"error": err_msg, "error_type": err_type, "traceback": err_tb}
            )
            task = await TrainingTaskRepository.get_by_id(db, task_id)
            if task and task.status != TaskStatus.CANCELLED:
                await TrainingTaskRepository.update_status(
                    db, task_id, TaskStatus.FAILED, error_message=f"[{err_type}] {err_msg}"
                )

