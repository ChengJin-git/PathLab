"""
Training pipeline implementation
Handles the background training workflow

Synchronous HTTP Architecture:
- Gateway sends HTTP request to AI service and waits for completion
- Timeout is set to 3 days to allow long-running training
- AI service runs training synchronously and returns result
- On timeout, Gateway calls AI service to cancel training and release GPU
"""
import asyncio
import httpx
from typing import List, Dict

from backend.database import get_db
from backend.database.repositories import TrainingTaskRepository
from backend.database.utils.training_logger import TrainingLogger
from .dependencies import logger, PREPROCESSING_SERVICE_URL, AI_SERVICE_URL

# HTTP timeout for long-running training tasks: 3 days
TRAINING_HTTP_TIMEOUT = 86400 * 3  # 3 days in seconds


async def _cancel_ai_service_training(task_id: str) -> None:
    """
    Request AI service to cancel a training task and release GPU.

    Called when Gateway HTTP request times out or user cancels.
    Uses fire-and-forget pattern: sends the request and returns immediately
    without waiting for response, since AI service may be blocked by GPU training.

    The cancellation flag is set immediately when the request is received,
    so we don't need to wait for the response.
    """
    try:
        # Fire-and-forget: very short timeout, we don't care about the response
        # The cancellation flag is set immediately when request is received
        async with httpx.AsyncClient(timeout=1.0) as client:
            await client.delete(f"{AI_SERVICE_URL}/api/ai/training/{task_id}")
            logger.info(f"Sent cancellation request to AI service for task {task_id}")
    except httpx.TimeoutException:
        # Expected - AI service is blocked by GPU training, but flag is already set
        logger.info(f"Cancellation request sent to AI service for task {task_id} (fire-and-forget)")
    except Exception as e:
        # Best effort - don't fail the main flow if cancellation fails
        logger.warning(f"Failed to send cancellation to AI service for task {task_id}: {e}")


async def run_training_pipeline(
    task_id: str,
    data_level: str,
    wsi_ids: List[str],
    preprocessing_config: Dict,
    model_config: Dict,
    huggingface_token: str = None,
    training_task_type: str = "classification"  # "classification" or "survival_prediction"
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
    # Create new database session for background task
    async for db in get_db():
        training_logger = None
        try:
            # Initialize training logger
            training_logger = TrainingLogger(task_id, db)

            # Update task status to running
            await TrainingTaskRepository.update_status(db, task_id, "running", progress=0)
            await db.commit()

            await training_logger.info(f"Starting training pipeline for task: {task_id} (data_level: {data_level})")
            await db.commit()  # Commit log entry

            # For patch-level tasks, use Feature Extractor + Linear Probe training
            if data_level == 'patch':
                await training_logger.info("Patch-level task detected - using Feature Extractor + Linear Probe")
                await db.commit()

                # Get training parameters
                feature_extractor = preprocessing_config.get('feature_extractor', 'resnet50')
                epochs = int(model_config.get('epochs', 10))
                lr = float(model_config.get('learning_rate', 1e-4))
                batch_size = int(model_config.get('batch_size', 64))
                optimizer = model_config.get('optimizer', 'adam')
                auto_balance = bool(model_config.get('auto_balance', False))
                early_stopping_patience = int(model_config.get('early_stopping_patience', 10))

                await training_logger.info(
                    f"Training Linear Probe with {feature_extractor} backbone",
                    metadata={"feature_extractor": feature_extractor, "epochs": epochs, "lr": lr, "optimizer": optimizer, "auto_balance": auto_balance}
                )
                await db.commit()

                # Update status to training
                await TrainingTaskRepository.update_status(db, task_id, "training", progress=50)
                await db.commit()

                # Call AI service for patch classification training (synchronous, waits for completion)
                try:
                    async with httpx.AsyncClient(timeout=TRAINING_HTTP_TIMEOUT) as client:
                        resp = await client.post(
                            f"{AI_SERVICE_URL}/api/ai/training/patch_classification",
                            json={
                                "task_id": task_id,
                                "epochs": epochs,
                                "lr": lr,
                                "feature_extractor": feature_extractor,
                                "batch_size": batch_size,
                                "huggingface_token": huggingface_token or "",
                                "optimizer": optimizer,
                                "auto_balance": auto_balance,
                                "early_stopping_patience": early_stopping_patience,
                            },
                        )
                        resp.raise_for_status()
                        _ = resp.json()
                except httpx.HTTPStatusError as e:
                    body = e.response.text if e.response is not None else str(e)
                    await training_logger.error(
                        f"AI service patch classification training failed: {e}",
                        metadata={"status_code": e.response.status_code if e.response else None, "body": body}
                    )
                    await db.commit()
                    raise
                except httpx.TimeoutException as e:
                    # Timeout - request AI service to cancel training and release GPU
                    await training_logger.error(
                        f"Training timeout after {TRAINING_HTTP_TIMEOUT} seconds. Requesting AI service to cancel and release GPU.",
                        metadata={"timeout_seconds": TRAINING_HTTP_TIMEOUT, "error": str(e)}
                    )
                    await db.commit()
                    await _cancel_ai_service_training(task_id)
                    raise Exception(f"Training timeout after {TRAINING_HTTP_TIMEOUT // 86400} days. Task cancelled.") from e
                except httpx.RequestError as e:
                    await training_logger.error(
                        f"Failed to connect to AI service for patch training: {e}",
                        metadata={"ai_service_url": AI_SERVICE_URL, "error": str(e)}
                    )
                    await db.commit()
                    raise Exception(f"AI service unavailable at {AI_SERVICE_URL}. Please ensure the AI service is running.") from e

                await training_logger.info("Patch classification training completed successfully")
                await TrainingTaskRepository.update_status(db, task_id, "completed", progress=100)
                await db.commit()
                return

            # Step 1: Patch extraction for WSI-level tasks
            total_wsi = len(wsi_ids)
            patch_size = preprocessing_config.get('tile_size', 512)
            stride = preprocessing_config.get('stride', 512)
            level = preprocessing_config.get('level', 0)
            # If stride is 0, use patch_size (no overlap)
            if stride == 0:
                stride = patch_size

            # Tissue segmentation parameters
            sthresh = preprocessing_config.get('sthresh', 5)
            mthresh = preprocessing_config.get('mthresh', 7)
            close = preprocessing_config.get('close', 4)
            use_otsu = preprocessing_config.get('use_otsu', False)
            contour_fn = preprocessing_config.get('contour_fn', 'four_pt')
            use_padding = preprocessing_config.get('use_padding', True)

            # Filter parameters
            a_t = preprocessing_config.get('a_t', 1)
            a_h = preprocessing_config.get('a_h', 256)
            max_n_holes = preprocessing_config.get('max_n_holes', 100)

            await training_logger.info(f"Extracting patches from {total_wsi} WSI slides")
            await training_logger.info(
                f"Patch size: {patch_size}x{patch_size}, Stride: {stride}, Level: {level}",
                metadata={"patch_size": patch_size, "stride": stride, "level": level}
            )
            await db.commit()

            for idx, wsi_id in enumerate(wsi_ids, 1):
                try:
                    await training_logger.info(
                        f"Processing WSI {idx}/{total_wsi}: {wsi_id}",
                        metadata={"wsi_index": idx, "total_wsi": total_wsi, "wsi_id": wsi_id}
                    )
                    await db.commit()

                    # Call preprocessing service to compute patches
                    # Note: force_recompute=False allows reusing cached coordinates
                    # if ALL parameters match (including seg_params and filter_params)
                    async with httpx.AsyncClient(timeout=300.0) as client:
                        response = await client.post(
                            f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/compute_patches",
                            params={
                                "patch_size": patch_size,
                                "stride": stride,
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

                        num_patches = result.get('num_patches', 0)
                        await training_logger.info(
                            f"Extracted {num_patches} patches from {wsi_id}",
                            metadata={"wsi_id": wsi_id, "num_patches": num_patches}
                        )
                        await db.commit()

                    # Update progress (0-33%)
                    progress = int((idx / total_wsi) * 33)
                    await TrainingTaskRepository.update_status(db, task_id, "running", progress=progress)
                    await db.commit()

                except Exception as e:
                    await training_logger.error(
                        f"Failed to extract patches from {wsi_id}: {e}",
                        metadata={"wsi_id": wsi_id, "error": str(e)}
                    )
                    await db.commit()
                    raise

            await training_logger.info(f"Patch extraction completed for all {total_wsi} WSI slides")
            await db.commit()

            # Step 2: Feature extraction via AI service
            feature_extractor = preprocessing_config.get('feature_extractor', 'resnet50')
            feature_batch_size = preprocessing_config.get('feature_batch_size', 256)
            await training_logger.info(f"Calling AI service for feature extraction (using {feature_extractor})")
            await db.commit()

            try:
                async with httpx.AsyncClient(timeout=TRAINING_HTTP_TIMEOUT) as client:
                    resp = await client.post(
                        f"{AI_SERVICE_URL}/api/ai/training/extract_features",
                        json={
                            "task_id": task_id,
                            "wsi_ids": wsi_ids,
                            "feature_extractor": feature_extractor,
                            "batch_size": feature_batch_size,
                            "force_recompute": False,  # Use cached features if available
                            "huggingface_token": huggingface_token or "",
                            "preprocessing_config": preprocessing_config,  # For cache key computation
                        },
                    )
                    resp.raise_for_status()
                    _ = resp.json()
            except httpx.HTTPStatusError as e:
                body = e.response.text if e.response is not None else str(e)
                await training_logger.error(
                    f"AI service feature extraction failed: {e}",
                    metadata={"status_code": e.response.status_code if e.response else None, "body": body}
                )
                await db.commit()
                raise
            except httpx.TimeoutException as e:
                # Timeout - request AI service to cancel and release GPU
                await training_logger.error(
                    f"Feature extraction timeout after {TRAINING_HTTP_TIMEOUT} seconds. Requesting AI service to cancel and release GPU.",
                    metadata={"timeout_seconds": TRAINING_HTTP_TIMEOUT, "error": str(e)}
                )
                await db.commit()
                await _cancel_ai_service_training(task_id)
                raise Exception(f"Feature extraction timeout after {TRAINING_HTTP_TIMEOUT // 86400} days. Task cancelled.") from e
            except httpx.RequestError as e:
                await training_logger.error(
                    f"Failed to connect to AI service for feature extraction: {e}",
                    metadata={"ai_service_url": AI_SERVICE_URL, "error": str(e)}
                )
                await db.commit()
                raise Exception(f"AI service unavailable at {AI_SERVICE_URL}. Please ensure the AI service is running.") from e

            await training_logger.info("Feature extraction completed for all WSI")
            await db.commit()

            # Step 3: WSI classification training via AI service (supports multiple aggregators)
            epochs = int(model_config.get('epochs', 10))
            lr = float(model_config.get('learning_rate', 1e-4))
            aggregator = model_config.get('aggregator', 'abmil')
            optimizer = model_config.get('optimizer', 'adam')
            auto_balance = bool(model_config.get('auto_balance', False))
            early_stopping_patience = int(model_config.get('early_stopping_patience', 10))

            await training_logger.info(f"Calling AI service to train {aggregator.upper()} model")
            await db.commit()

            try:
                # Use correct endpoint based on training_task_type
                if training_task_type == "survival_prediction":
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
                    }

                # Send training request (synchronous, waits for completion)
                async with httpx.AsyncClient(timeout=TRAINING_HTTP_TIMEOUT) as client:
                    resp = await client.post(endpoint, json=payload)
                    resp.raise_for_status()
                    _ = resp.json()

            except httpx.HTTPStatusError as e:
                body = e.response.text if e.response is not None else str(e)
                await training_logger.error(
                    f"AI service training failed: {e}",
                    metadata={"status_code": e.response.status_code if e.response else None, "body": body}
                )
                await db.commit()
                raise
            except httpx.TimeoutException as e:
                # Timeout - request AI service to cancel training and release GPU
                await training_logger.error(
                    f"WSI training timeout after {TRAINING_HTTP_TIMEOUT} seconds. Requesting AI service to cancel and release GPU.",
                    metadata={"timeout_seconds": TRAINING_HTTP_TIMEOUT, "error": str(e)}
                )
                await db.commit()
                await _cancel_ai_service_training(task_id)
                raise Exception(f"WSI training timeout after {TRAINING_HTTP_TIMEOUT // 86400} days. Task cancelled.") from e
            except httpx.RequestError as e:
                await training_logger.error(
                    f"Failed to connect to AI service for training: {e}",
                    metadata={"ai_service_url": AI_SERVICE_URL, "error": str(e)}
                )
                await db.commit()
                raise Exception(f"AI service unavailable at {AI_SERVICE_URL}. Please ensure the AI service is running.") from e

            await training_logger.info("Training pipeline completed successfully")
            # Do not overwrite status here; AI service sets progress to 100 and status to completed
            await db.commit()

        except asyncio.CancelledError:
            # Task was cancelled via TaskQueueManager.cancel_task()
            # Status should already be set to 'cancelled' in queue.py
            if training_logger:
                await training_logger.info("Training pipeline cancelled")
                await db.commit()
            # Re-raise to let asyncio handle the cancellation properly
            raise

        except Exception as e:
            if training_logger:
                await training_logger.error(f"Training pipeline failed: {e}", metadata={"error": str(e)})
            # Don't reset progress on failure - keep the progress at the point of failure
            # Only update to 'failed' if not already cancelled
            task = await TrainingTaskRepository.get_by_id(db, task_id)
            if task and task.status != "cancelled":
                await TrainingTaskRepository.update_status(
                    db, task_id, "failed", error_message=str(e)
                )
            await db.commit()

        finally:
            # Close logger
            if training_logger:
                await training_logger.close()
            # Note: db session is automatically closed by get_db() context manager

