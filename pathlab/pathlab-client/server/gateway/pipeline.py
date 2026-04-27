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
import time
import traceback
from importlib import import_module
from pathlib import Path
from typing import Any, List, Dict, Set, Tuple, cast
from contextlib import asynccontextmanager

TaskStatus = import_module("backend.ai.schemas.base").TaskStatus
_coco_utils = import_module("backend.annotation.coco_utils")
extract_coco_wsi_label_sets = _coco_utils.extract_coco_wsi_label_sets
materialize_coco_to_disk = _coco_utils.materialize_coco_to_disk
merge_coco_datasets = _coco_utils.merge_coco_datasets
safe_session = import_module("backend.database").safe_session
_repositories = import_module("backend.database.repositories")
TrainingTaskRepository = _repositories.TrainingTaskRepository
SegmentationAnnotationRepository = _repositories.SegmentationAnnotationRepository
WSIRepository = _repositories.WSIRepository
TrainingLogger = import_module("backend.database.utils.training_logger").TrainingLogger
Config = import_module("backend.common.config").Config
_task_taxonomy = import_module("backend.ai.task_taxonomy")
from .dependencies import logger, AI_SERVICE_URL
from .utils import cancel_ai_service_training, ensure_coords_ready


_GPU_VRAM_REPROBE_TIMEOUT_SECS = float(
    os.getenv("GPU_VRAM_REPROBE_TIMEOUT_SECS", "1800")
)
_GPU_VRAM_REPROBE_POLL_SECS = 10.0


def _get_gpu_utils_module():
    return import_module("backend.common.gpu_utils")


def _get_results_route_module():
    return import_module("gateway.routes.results")


def _training_task_family(training_task_type: str) -> str:
    normalized = str(training_task_type or "wsi_classification").strip().lower()
    return _task_taxonomy.get_task_metadata(normalized).task_family


async def _ensure_gpu_vram_for_step(
    assigned_device: str | None,
    step_name: str,
    logger_manager: "ScopedLogger",
    min_vram_mb: float | None = None,
) -> None:
    if not assigned_device or not assigned_device.startswith("cuda"):
        return

    try:
        check_gpu_vram_available = _get_gpu_utils_module().check_gpu_vram_available
    except ImportError:
        return

    try:
        gpu_index = int(assigned_device.split(":")[-1]) if ":" in assigned_device else 0
    except (ValueError, IndexError):
        return

    if min_vram_mb is None:
        min_vram_mb = Config.DEFAULT_MIN_VRAM_MB

    deadline = time.monotonic() + _GPU_VRAM_REPROBE_TIMEOUT_SECS
    warned = False

    while True:
        is_available, current_free_mb, message = check_gpu_vram_available(
            gpu_index, min_vram_mb
        )
        if is_available:
            if warned:
                async with logger_manager.session() as (log, _db):
                    await log.info(
                        f"[{step_name}] {assigned_device} VRAM recovered — {current_free_mb:.0f} MB free"
                    )
            return

        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"{assigned_device} still has insufficient VRAM after "
                f"{_GPU_VRAM_REPROBE_TIMEOUT_SECS:.0f}s wait before {step_name}. "
                f"Required: {min_vram_mb:.0f} MB, available: {current_free_mb:.0f} MB. "
                "Another process may be occupying the GPU."
            )

        if not warned:
            async with logger_manager.session() as (log, _db):
                await log.warning(
                    f"[{step_name}] {assigned_device} VRAM insufficient — waiting. {message}",
                    metadata={"required_mb": min_vram_mb, "free_mb": current_free_mb},
                )
            warned = True

        await asyncio.sleep(_GPU_VRAM_REPROBE_POLL_SECS)


_UNSUPPORTED_PATCH_SEGMENTATION_LOSS_TOKENS = frozenset(
    {
        "ce",
        "softcrossentropyloss",
        "crossentropy",
        "crossentropyloss",
    }
)

_PATCH_SEGMENTATION_EXPECTED_SPLITS = ("train", "val", "test")


def _normalize_patch_segmentation_loss_name(loss_name: str) -> str:
    return "".join(ch for ch in str(loss_name).lower() if ch.isalnum())


def _validate_patch_segmentation_loss_names(loss_names: List[str]) -> None:
    unsupported_losses = [
        loss_name
        for loss_name in loss_names
        if _normalize_patch_segmentation_loss_name(loss_name)
        in _UNSUPPORTED_PATCH_SEGMENTATION_LOSS_TOKENS
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


def _serialize_segmentation_wsi(wsi) -> Dict[str, Any]:
    return {
        "wsi_id": str(wsi.wsi_id),
        "dataset_id": str(wsi.dataset_id) if getattr(wsi, "dataset_id", None) else None,
        "wsi_path": str(wsi.wsi_path) if getattr(wsi, "wsi_path", None) else None,
        "original_filename": str(wsi.original_filename)
        if getattr(wsi, "original_filename", None)
        else None,
    }


def _build_segmentation_wsi_lookups(
    wsis: List[Dict[str, Any]],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    exact_lookup: Dict[str, str] = {}
    stem_candidates: Dict[str, Set[str]] = {}

    for wsi in wsis:
        candidate_names = []
        if wsi.get("original_filename"):
            candidate_names.append(str(wsi["original_filename"]))
        if wsi.get("wsi_path"):
            candidate_names.append(Path(str(wsi["wsi_path"])).name)

        for candidate in candidate_names:
            normalized = Path(candidate).name.strip().lower()
            if not normalized:
                continue
            wsi_id = str(wsi["wsi_id"])
            exact_lookup.setdefault(normalized, wsi_id)
            stem_candidates.setdefault(Path(normalized).stem, set()).add(wsi_id)

    stem_lookup = {
        stem: next(iter(wsi_ids))
        for stem, wsi_ids in stem_candidates.items()
        if len(wsi_ids) == 1
    }
    return exact_lookup, stem_lookup


async def _load_segmentation_coco_payloads(db, dataset_id: str) -> List[dict[str, Any]]:
    records = await SegmentationAnnotationRepository.get_all_by_dataset(
        db,
        dataset_id,
        include_drafts=False,
    )
    if not records:
        return []

    dataset_level_record = next(
        (record for record in records if record.annotation_id == f"label_{dataset_id}"),
        None,
    )
    payloads = (
        [cast(dict[str, Any], dataset_level_record.annotations)]
        if dataset_level_record and isinstance(dataset_level_record.annotations, dict)
        else [
            cast(dict[str, Any], record.annotations)
            for record in records
            if isinstance(record.annotations, dict)
        ]
    )
    return payloads


def _build_split_coco_payload(
    coco_data: dict[str, Any],
    allowed_wsi_ids: Set[str],
    exact_lookup: Dict[str, str],
    stem_lookup: Dict[str, str],
    wsi_to_relative_path: Dict[str, str],
) -> dict[str, Any]:
    allowed_image_ids: Set[int] = set()
    images = []

    for image in coco_data.get("images") or []:
        if not isinstance(image, dict):
            continue
        normalized_name = Path(str(image.get("file_name") or "")).name.strip().lower()
        if not normalized_name:
            continue
        wsi_id = exact_lookup.get(normalized_name) or stem_lookup.get(
            Path(normalized_name).stem
        )
        if wsi_id not in allowed_wsi_ids:
            continue

        image_copy = dict(image)
        image_copy["file_name"] = wsi_to_relative_path.get(
            wsi_id, image_copy.get("file_name")
        )
        image_id = image_copy.get("id")
        if not isinstance(image_id, int):
            continue
        images.append(image_copy)
        allowed_image_ids.add(image_id)

    annotations = [
        dict(annotation)
        for annotation in (coco_data.get("annotations") or [])
        if isinstance(annotation, dict)
        and annotation.get("image_id") in allowed_image_ids
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


async def _load_segmentation_training_dataset_inputs(
    db,
    task_id: str,
    wsi_ids: List[str],
    preprocessing_config: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[dict[str, Any]], Dict[str, List[str]]]:
    wsi_map = await WSIRepository.get_by_ids(db, wsi_ids)
    wsis = [
        _serialize_segmentation_wsi(wsi_map[wsi_id])
        for wsi_id in wsi_ids
        if wsi_id in wsi_map
    ]
    if not wsis:
        raise ValueError("No patch images found for segmentation training task")

    dataset_ids = {wsi["dataset_id"] for wsi in wsis if wsi.get("dataset_id")}
    if len(dataset_ids) != 1:
        raise ValueError(
            "Segmentation training requires all selected images to belong to the same dataset"
        )

    dataset_id = next(iter(dataset_ids), None)
    if dataset_id is None:
        raise ValueError("Segmentation training dataset id could not be resolved")
    coco_payloads = await _load_segmentation_coco_payloads(db, dataset_id)
    if not coco_payloads:
        raise ValueError(
            f"No finalized COCO annotations found for segmentation dataset {dataset_id}"
        )

    split_config = preprocessing_config.get("split_config") or {}
    strategy = split_config.get("strategy", "random")
    if strategy == "k_fold":
        raise ValueError(
            "Patch segmentation training does not support k-fold splits yet"
        )

    splits_map = await TrainingTaskRepository.get_wsi_ids_by_split(db, task_id)
    if not all(
        split_name in splits_map for split_name in _PATCH_SEGMENTATION_EXPECTED_SPLITS
    ):
        raise ValueError(
            "Segmentation training requires train/val/test split assignments"
        )

    return wsis, coco_payloads, splits_map


def _prepare_segmentation_training_dataset(
    task_id: str,
    wsis: List[Dict[str, Any]],
    coco_payloads: List[dict[str, Any]],
    splits_map: Dict[str, List[str]],
) -> Tuple[Dict[str, Any], int]:
    coco_data = merge_coco_datasets(coco_payloads)
    if not coco_data.get("images"):
        raise ValueError(
            "Segmentation dataset has no COCO images available for training"
        )

    exact_lookup, stem_lookup = _build_segmentation_wsi_lookups(wsis)
    label_sets = extract_coco_wsi_label_sets(coco_data, exact_lookup, stem_lookup)
    classes = sorted({label for labels in label_sets.values() for label in labels})
    if not classes:
        raise ValueError(
            "Segmentation dataset has no COCO categories available for training"
        )

    image_parents = [
        str(Path(str(wsi["wsi_path"])).resolve().parent)
        for wsi in wsis
        if wsi.get("wsi_path")
    ]
    image_root = (
        Path(os.path.commonpath(image_parents))
        if image_parents
        else Config.get_uploads_dir()
    )
    wsi_to_relative_path = {
        str(wsi["wsi_id"]): os.path.relpath(
            str(Path(str(wsi["wsi_path"])).resolve()), str(image_root)
        )
        for wsi in wsis
        if wsi.get("wsi_path")
    }

    split_dir = Config.get_uploads_dir() / "training" / task_id / "segmentation_splits"
    split_dir.mkdir(parents=True, exist_ok=True)
    dataset_config: Dict[str, Any] = {"classes": len(classes), "channels": 3}

    for split_name in _PATCH_SEGMENTATION_EXPECTED_SPLITS:
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
    logger_manager: "ScopedLogger",
    task_id: str,
    endpoint: str,
    payload: dict[str, Any],
    operation_name: str,
    timeout: int | None = None,
) -> dict[str, Any]:
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
                metadata={
                    "status_code": e.response.status_code if e.response else None,
                    "body": body,
                },
            )
        raise
    except httpx.TimeoutException as e:
        async with logger_manager.session() as (logger, db):
            await logger.error(
                f"{operation_name} timeout after {timeout} seconds. Requesting AI service to cancel and release GPU.",
                metadata={"timeout_seconds": timeout, "error": str(e)},
            )
        await cancel_ai_service_training(task_id)
        raise Exception(
            f"{operation_name} timeout after {timeout // 3600} hours. Task cancelled."
        ) from e
    except httpx.RequestError as e:
        async with logger_manager.session() as (logger, db):
            await logger.error(
                f"Failed to connect to AI service for {operation_name}: {e}",
                metadata={"ai_service_url": AI_SERVICE_URL, "error": str(e)},
            )
        raise Exception(
            f"AI service unavailable at {AI_SERVICE_URL}. Please ensure the AI service is running."
        ) from e


class ScopedLogger:
    """
    Helper to create short-lived DB sessions for logging and status updates.
    Ensures that we don't hold a DB connection open during long-running HTTP calls.

    Includes timeout protection to prevent indefinite blocking on database operations.
    """

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.session_maker = import_module("backend.database").async_session_maker

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


async def _generate_patch_segmentation_visualizations(
    logger_manager: "ScopedLogger",
    task_id: str,
    assigned_device: str | None = None,
) -> None:
    results_routes = _get_results_route_module()
    _check_task_resources = results_routes._check_task_resources
    _run_inference_patch_segmentation = results_routes._run_inference_patch_segmentation

    async def _update_visualization_progress(progress_ratio: float) -> None:
        bounded_ratio = max(0.0, min(progress_ratio, 1.0))
        progress = 92 + int(round(bounded_ratio * 7))
        async with safe_session() as db:
            await TrainingTaskRepository.update_status(
                db,
                task_id,
                TaskStatus.TRAINING,
                progress=max(92, min(progress, 99)),
            )

    async with safe_session() as db:
        task = await TrainingTaskRepository.get_by_id(db, task_id)
        if not task:
            raise ValueError(f"Training task not found: {task_id}")

        resources = await _check_task_resources(task_id, db)
        if resources["has_ai_results"]:
            async with logger_manager.session() as (logger, db_for_log):
                await logger.info(
                    "Visualization artifacts already exist. Skipping post-training generation."
                )
                await TrainingTaskRepository.update_status(
                    db_for_log, task_id, TaskStatus.TRAINING, progress=99
                )
            return

        wsi_ids = await TrainingTaskRepository.get_wsi_ids(db, task_id)
        if not wsi_ids:
            raise ValueError(f"No WSI IDs found for task {task_id}")

        async with logger_manager.session() as (logger, db_for_log):
            await logger.info(
                "[Post-processing] Generating visualization artifacts...",
                metadata={"artifacts": ["pred_mask.npy", "cam.npy"]},
            )
            await TrainingTaskRepository.update_status(
                db_for_log, task_id, TaskStatus.TRAINING, progress=92
            )

        await _run_inference_patch_segmentation(
            task,
            wsi_ids,
            resources,
            db,
            progress_callback=_update_visualization_progress,
            assigned_device=assigned_device,
        )

    async with logger_manager.session() as (logger, db):
        await logger.info(
            "Visualization artifacts generated successfully.",
            metadata={"artifacts": ["pred_mask.npy", "cam.npy"]},
        )
        await TrainingTaskRepository.update_status(
            db, task_id, TaskStatus.TRAINING, progress=99
        )


async def run_patching_stage(
    task_id: str,
    wsi_ids: List[str],
    preprocessing_config: Dict[str, Any],
) -> None:
    """
    Run the CPU-only patch coordinate extraction stage for WSI tasks.

    Runs OUTSIDE the GPU task queue — does not consume a GPU concurrency slot.
    Called as a pre-queue step by run_patching_then_submit() before GPU stages.

    Cancellation:
      - asyncio.Task.cancel() raises CancelledError at each await asyncio.sleep(0) point
      - DB status poll per WSI also stops early if status == TaskStatus.CANCELLED (belt-and-suspenders)

    Progress: updates DB from 0% to 33% across WSIs. GPU stages (EXTRACTING, TRAINING) use 33%-100%.
    """
    logger_manager = ScopedLogger(task_id)

    total_wsi = len(wsi_ids)
    if total_wsi == 0:
        logger.warning(
            f"[{task_id}] run_patching_stage called with empty wsi_ids — nothing to do"
        )
        return
    level = preprocessing_config.get("level", 0)
    sthresh = preprocessing_config.get("sthresh", 8)
    mthresh = preprocessing_config.get("mthresh", 7)
    close = preprocessing_config.get("close", 4)
    use_otsu = preprocessing_config.get("use_otsu", False)
    contour_fn = preprocessing_config.get("contour_fn", "four_pt")
    use_padding = preprocessing_config.get("use_padding", True)
    a_t = preprocessing_config.get("a_t", 1)
    a_h = preprocessing_config.get("a_h", 256)
    max_n_holes = preprocessing_config.get("max_n_holes", 100)
    coords_request_params = {
        "level": level,
        "force_recompute": False,
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
    }

    async with logger_manager.session() as (log, db):
        await TrainingTaskRepository.update_status(
            db, task_id, TaskStatus.PATCHING, progress=0
        )
        await log.info(f"Extracting patches from {total_wsi} WSI slides")
        await log.info(f"Level: {level}", metadata={"level": level})

    for idx, wsi_id in enumerate(wsi_ids, 1):
        await asyncio.sleep(0)

        async with logger_manager.session() as (_, db):
            task_record = await TrainingTaskRepository.get_by_id(db, task_id)
            task_status = task_record.status if task_record is not None else None
            if task_record is None or task_status == TaskStatus.CANCELLED:
                logger.info(
                    f"[{task_id}] Task cancelled during patch extraction at WSI {idx}/{total_wsi}, stopping"
                )
                raise asyncio.CancelledError()

        try:
            async with logger_manager.session() as (log, db):
                await log.info(
                    f"Processing WSI {idx}/{total_wsi}: {wsi_id}",
                    metadata={
                        "wsi_index": idx,
                        "total_wsi": total_wsi,
                        "wsi_id": wsi_id,
                    },
                )

            async def _log_retry(
                attempt: int, max_retries: int, retry_err: Exception, wait_secs: int
            ):
                async with logger_manager.session() as (log, db):
                    await log.warning(
                        f"[{idx}/{total_wsi}] compute_patches attempt {attempt}/{max_retries} "
                        f"failed for {wsi_id}: {type(retry_err).__name__}. "
                        f"Retrying in {wait_secs}s (cached coords will be used on retry)...",
                        metadata={
                            "wsi_id": wsi_id,
                            "attempt": attempt,
                            "error": str(retry_err),
                        },
                    )

            async def _log_lock_wait(wait_seconds: float):
                async with logger_manager.session() as (log, db):
                    await log.info(
                        f"[{idx}/{total_wsi}] Waiting {wait_seconds:.0f}s for shared coords extraction lock on {wsi_id}",
                        metadata={"wsi_id": wsi_id, "wait_seconds": wait_seconds},
                    )

            result = await ensure_coords_ready(
                wsi_id,
                params=coords_request_params,
                timeout=600.0,
                uploads_root=Config.get_uploads_dir(),
                on_retry=_log_retry,
                on_lock_wait=_log_lock_wait,
            )

            num_patches = result.get("num_patches", 0)
            cached = result.get("cached", False)

            async with logger_manager.session() as (log, db):
                if num_patches == 0:
                    await log.warning(
                        f"[{idx}/{total_wsi}] No tissue patches found for {wsi_id} — "
                        f"the slide may be blank or contain no detectable tissue. "
                        f"It will be skipped during feature extraction.",
                        metadata={"wsi_id": wsi_id, "num_patches": 0, "cached": cached},
                    )
                elif cached:
                    await log.info(
                        f"[{idx}/{total_wsi}] Coords cache hit for {wsi_id}",
                        metadata={
                            "wsi_id": wsi_id,
                            "num_patches": num_patches,
                            "cached": True,
                        },
                    )
                else:
                    await log.info(
                        f"[{idx}/{total_wsi}] Extracted {num_patches} patches from {wsi_id}",
                        metadata={
                            "wsi_id": wsi_id,
                            "num_patches": num_patches,
                            "cached": False,
                        },
                    )

                progress = int((idx / total_wsi) * 33)
                await TrainingTaskRepository.update_status(
                    db, task_id, TaskStatus.PATCHING, progress=progress
                )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            import traceback as _tb

            err_type = type(e).__name__
            err_msg = str(e) or repr(e)
            err_tb = _tb.format_exc()
            resp_body = ""
            if isinstance(e, httpx.HTTPStatusError):
                try:
                    resp_body = e.response.text[:1000]
                except Exception:
                    resp_body = "(unable to read response body)"
            async with logger_manager.session() as (log, db):
                await log.error(
                    f"Failed to extract patches from {wsi_id}: [{err_type}] {err_msg}",
                    metadata={
                        "wsi_id": wsi_id,
                        "error": err_msg,
                        "error_type": err_type,
                        "response_body": resp_body,
                        "traceback": err_tb,
                    },
                )
            raise

    async with logger_manager.session() as (log, db):
        await log.info(f"Patch extraction completed for all {total_wsi} WSI slides")


async def run_patching_then_submit(
    task_id: str, pipeline_kwargs: dict[str, Any]
) -> None:
    """
    Coordinator for WSI tasks: run CPU-only patching outside the GPU gate, then
    submit the GPU pipeline (feature extraction + training) to the task queue.

    Lifecycle:
      PENDING → PATCHING (set by run_patching_stage) → QUEUED (submitted to GPU queue)

    Called as a background asyncio.Task registered with TaskQueueManager._patching_tasks.
    Cancellation via asyncio.Task.cancel() propagates as CancelledError; the handler
    updates DB status to CANCELLED and deregisters from the queue manager.
    """
    from .task_queue import get_task_queue, TaskType

    try:
        await run_patching_stage(
            task_id=task_id,
            wsi_ids=pipeline_kwargs["wsi_ids"],
            preprocessing_config=pipeline_kwargs.get("preprocessing_config", {}),
        )

        async with safe_session() as db:
            task_record = await TrainingTaskRepository.get_by_id(db, task_id)
            if not task_record or task_record.status == TaskStatus.CANCELLED:
                logger.info(
                    f"[{task_id}] Task cancelled after patching completion, not submitting to GPU queue"
                )
                return

        gpu_kwargs = {**pipeline_kwargs, "patching_complete": True}
        task_queue = get_task_queue()
        await task_queue.submit(
            task_id=task_id,
            task_type=TaskType.TRAINING,
            coro_func=run_training_pipeline,
            **gpu_kwargs,
        )

        async with safe_session() as db:
            await TrainingTaskRepository.update_status(
                db, task_id, TaskStatus.QUEUED, progress=33
            )
            await db.commit()

        logger.info(
            f"[{task_id}] Patching complete, submitted to GPU queue (progress=33%)"
        )

    except asyncio.CancelledError:
        logger.info(f"[{task_id}] Pre-queue patching cancelled")
        try:
            async with safe_session() as db:
                task_record = await TrainingTaskRepository.get_by_id(db, task_id)
                if task_record and task_record.status not in (
                    TaskStatus.CANCELLED,
                    TaskStatus.FAILED,
                    TaskStatus.COMPLETED,
                ):
                    await TrainingTaskRepository.update_status(
                        db, task_id, TaskStatus.CANCELLED
                    )
                    await db.commit()
        except Exception as db_err:
            logger.error(
                f"[{task_id}] Failed to update cancelled status after patching cancellation: {db_err}"
            )
        raise

    except Exception as e:
        err_msg = str(e) or repr(e)
        logger.error(
            f"[{task_id}] Pre-queue patching failed: [{type(e).__name__}] {err_msg}"
        )
        try:
            async with safe_session() as db:
                task_record = await TrainingTaskRepository.get_by_id(db, task_id)
                if task_record and task_record.status not in (
                    TaskStatus.CANCELLED,
                    TaskStatus.FAILED,
                    TaskStatus.COMPLETED,
                ):
                    await TrainingTaskRepository.update_status(
                        db,
                        task_id,
                        TaskStatus.FAILED,
                        error_message=f"Patch extraction failed: [{type(e).__name__}] {err_msg}",
                    )
                    await db.commit()
        except Exception as db_err:
            logger.error(
                f"[{task_id}] Failed to update failed status after patching error: {db_err}"
            )

    finally:
        try:
            from .task_queue import get_task_queue

            get_task_queue().deregister_patching_task(task_id)
        except Exception:
            pass


async def run_training_pipeline(
    task_id: str,
    data_type: str,
    wsi_ids: List[str],
    preprocessing_config: Dict[str, Any],
    model_config: Dict[str, Any],
    huggingface_token: str | None = None,
    training_task_type: str = "classification",  # "classification", "survival", or "segmentation"
    assigned_device: str
    | None = None,  # GPU device assigned by task queue (e.g., "cuda:0")
    user_id: str | None = None,  # User who submitted the task (for permission checks)
    user_is_admin: bool = False,  # Whether the submitting user is admin
    patching_complete: bool = False,  # True when patching was run pre-queue (WSI tasks only)
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
            await logger.info(
                f"Starting training pipeline for task: {task_id} (data_type: {data_type})"
            )

        task_family = _training_task_family(training_task_type)

        # For patch-level tasks, route based on training_task_type
        if data_type == "patch":
            if task_family == "segmentation":
                preprocessing_config = dict(preprocessing_config or {})
                async with logger_manager.session() as (logger, db):
                    await logger.info("Patch-level segmentation task detected")

                    (
                        wsis,
                        coco_payloads,
                        splits_map,
                    ) = await _load_segmentation_training_dataset_inputs(
                        db=db,
                        task_id=task_id,
                        wsi_ids=wsi_ids,
                        preprocessing_config=preprocessing_config,
                    )

                segmentation_dataset, num_classes = (
                    _prepare_segmentation_training_dataset(
                        task_id=task_id,
                        wsis=wsis,
                        coco_payloads=coco_payloads,
                        splits_map=splits_map,
                    )
                )
                preprocessing_config["segmentation_dataset"] = segmentation_dataset

                # Patch Segmentation: uses architecture + backbone (not feature extractor)
                architecture = model_config.get("architecture", "unet")
                backbone = model_config.get("backbone", "resnet50")
                loss_names = model_config.get("loss_names", ["DiceLoss", "JaccardLoss"])
                loss_weights = model_config.get("loss_weights", [0.5, 0.5])
                _validate_patch_segmentation_loss_names(loss_names)
                epochs = int(model_config.get("epochs", 100))
                lr = float(model_config.get("learning_rate", 0.0001))
                batch_size = int(model_config.get("batch_size", 16))
                optimizer = model_config.get("optimizer", "adamw")
                early_stopping_patience = int(
                    model_config.get("early_stopping_patience", 15)
                )
                seed = preprocessing_config.get("split_config", {}).get("seed", 42)

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
                            "train_annotations_path": segmentation_dataset["train"][
                                "annotations_path"
                            ],
                            "val_annotations_path": segmentation_dataset["val"][
                                "annotations_path"
                            ],
                            "test_annotations_path": segmentation_dataset["test"][
                                "annotations_path"
                            ],
                        },
                    )

                    await logger.info(
                        f"Training {architecture} with {backbone} backbone",
                        metadata={
                            "architecture": architecture,
                            "backbone": backbone,
                            "loss_names": loss_names,
                            "epochs": epochs,
                            "lr": lr,
                        },
                    )

                    # Update status to training; preserve progress if resuming from checkpoint
                    _seg_task = await TrainingTaskRepository.get_by_id(db, task_id)
                    _seg_start_progress = (
                        int(_seg_task.progress)
                        if _seg_task is not None
                        and _seg_task.status == TaskStatus.RESUMING
                        and _seg_task.progress is not None
                        else 50
                    )
                    await TrainingTaskRepository.update_status(
                        db, task_id, TaskStatus.TRAINING, progress=_seg_start_progress
                    )

                await _ensure_gpu_vram_for_step(
                    assigned_device, "patch_segmentation", logger_manager
                )
                _decoder_type = (
                    architecture.replace("_decoder", "")
                    if architecture.endswith("_decoder")
                    else None
                )
                _seg_payload: dict[str, Any] = {
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
                }
                if _decoder_type is not None:
                    _seg_payload["decoder_type"] = _decoder_type
                await _call_ai_service(
                    logger_manager=logger_manager,
                    task_id=task_id,
                    endpoint=f"{AI_SERVICE_URL}/api/ai/training/patch_segmentation",
                    payload=_seg_payload,
                    operation_name="patch segmentation training",
                )

                await _generate_patch_segmentation_visualizations(
                    logger_manager=logger_manager,
                    task_id=task_id,
                    assigned_device=assigned_device,
                )

                async with logger_manager.session() as (logger, db):
                    await logger.info(
                        "Patch segmentation training completed successfully"
                    )
                    await TrainingTaskRepository.update_status(
                        db, task_id, TaskStatus.COMPLETED, progress=100
                    )
                return

            # Patch Classification: use Feature Extractor + Linear Probe training
            async with logger_manager.session() as (logger, db):
                await logger.info(
                    "Patch-level task detected - using Feature Extractor + Classifier Head"
                )

                # Get training parameters
                feature_extractor = preprocessing_config.get(
                    "feature_extractor", "resnet50"
                )
                classifier = model_config.get("classifier", "linear")
                epochs = int(model_config.get("epochs", 50))
                lr = float(model_config.get("learning_rate", 0.0002))
                batch_size = int(model_config.get("batch_size", 64))
                optimizer = model_config.get("optimizer", "adam")
                auto_balance = bool(model_config.get("auto_balance", False))
                early_stopping_patience = int(
                    model_config.get("early_stopping_patience", 10)
                )
                seed = preprocessing_config.get("split_config", {}).get("seed", 42)

                await logger.info(
                    f"Training {classifier} classifier with {feature_extractor} backbone",
                    metadata={
                        "feature_extractor": feature_extractor,
                        "classifier": classifier,
                        "epochs": epochs,
                        "lr": lr,
                        "optimizer": optimizer,
                        "auto_balance": auto_balance,
                    },
                )

                # Update status to training; preserve progress if resuming from checkpoint
                _patch_task = await TrainingTaskRepository.get_by_id(db, task_id)
                _patch_start_progress = (
                    int(_patch_task.progress)
                    if _patch_task is not None
                    and _patch_task.status == TaskStatus.RESUMING
                    and _patch_task.progress is not None
                    else 50
                )
                await TrainingTaskRepository.update_status(
                    db, task_id, TaskStatus.TRAINING, progress=_patch_start_progress
                )

            await _ensure_gpu_vram_for_step(
                assigned_device, "patch_classification", logger_manager
            )
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
                operation_name="patch classification training",
            )

            async with logger_manager.session() as (logger, db):
                await logger.info(
                    "Patch classification training completed successfully"
                )
                await TrainingTaskRepository.update_status(
                    db, task_id, TaskStatus.COMPLETED, progress=100
                )
            return

        # Step 1: Patch extraction for WSI-level tasks
        if patching_complete:
            async with logger_manager.session() as (log, db):
                await log.info(
                    f"Patch extraction already complete (pre-queue), "
                    f"skipping patching stage for {len(wsi_ids)} WSI slides"
                )
        else:
            await run_patching_stage(
                task_id=task_id,
                wsi_ids=wsi_ids,
                preprocessing_config=preprocessing_config,
            )

        # Step 2: Feature extraction via AI service
        feature_extractor = preprocessing_config.get("feature_extractor", "resnet50")
        feature_batch_size = preprocessing_config.get(
            "feature_batch_size", 64
        )  # Match constants/training.ts

        async with logger_manager.session() as (logger, db):
            await logger.info(
                f"Calling AI service for feature extraction (using {feature_extractor})"
            )

        await _ensure_gpu_vram_for_step(
            assigned_device, "feature_extraction", logger_manager
        )
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
            operation_name="feature extraction",
        )

        async with logger_manager.session() as (logger, db):
            await logger.info("Feature extraction completed for all WSI")

        # Step 3: WSI classification training via AI service (supports multiple aggregators)
        epochs = int(model_config.get("epochs", 50))
        lr = float(model_config.get("learning_rate", 0.0002))
        weight_decay = float(model_config.get("weight_decay", 1e-5))
        aggregator = model_config.get("aggregator", "abmil")
        optimizer = model_config.get("optimizer", "adam")
        auto_balance = bool(model_config.get("auto_balance", False))
        early_stopping_patience = int(model_config.get("early_stopping_patience", 20))
        seed = preprocessing_config.get("split_config", {}).get("seed", 42)

        async with logger_manager.session() as (logger, db):
            await logger.info(f"Calling AI service to train {aggregator.upper()} model")

        # Use correct endpoint based on training_task_type
        if task_family == "survival":
            endpoint = f"{AI_SERVICE_URL}/api/ai/training/wsi_survival"
            payload = {
                "task_id": task_id,
                "epochs": epochs,
                "lr": lr,
                "weight_decay": weight_decay,
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

        await _ensure_gpu_vram_for_step(assigned_device, "wsi_training", logger_manager)
        await _call_ai_service(
            logger_manager=logger_manager,
            task_id=task_id,
            endpoint=endpoint,
            payload=payload,
            operation_name="WSI training",
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

        if (
            "CUDA error" in err_msg
            and assigned_device
            and assigned_device.startswith("cuda:")
        ):
            try:
                from .task_queue import get_task_queue as _get_tq

                _gpu_idx = int(assigned_device.split(":")[-1])
                _get_tq().mark_gpu_bad(_gpu_idx)
            except Exception:
                pass

        async with logger_manager.session() as (logger, db):
            await logger.error(
                f"Training pipeline failed: [{err_type}] {err_msg}",
                metadata={
                    "error": err_msg,
                    "error_type": err_type,
                    "traceback": err_tb,
                },
            )
            task = await TrainingTaskRepository.get_by_id(db, task_id)
            if task is not None and task.status != TaskStatus.CANCELLED:
                await TrainingTaskRepository.update_status(
                    db,
                    task_id,
                    TaskStatus.FAILED,
                    error_message=f"[{err_type}] {err_msg}",
                )
