"""
Training pipeline implementation
Handles the background training workflow
"""
import httpx
from typing import List, Dict

from backend.database import get_db
from backend.database.repositories import TrainingTaskRepository
from backend.database.utils.training_logger import TrainingLogger
from .dependencies import logger, PREPROCESSING_SERVICE_URL, AI_SERVICE_URL


async def run_training_pipeline(
    task_id: str,
    data_level: str,
    wsi_ids: List[str],
    preprocessing_config: Dict,
    model_config: Dict
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

            # For patch-level tasks, skip patch extraction
            if data_level == 'patch':
                await training_logger.info("Patch-level task detected - skipping patch extraction")
                await training_logger.info("Note: Training for patch-level is not implemented yet")
                await TrainingTaskRepository.update_status(
                    db, task_id, "completed", progress=100
                )
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
                    async with httpx.AsyncClient(timeout=300.0) as client:
                        response = await client.post(
                            f"{PREPROCESSING_SERVICE_URL}/wsi/{wsi_id}/compute_patches",
                            params={
                                "patch_size": patch_size,
                                "stride": stride,
                                "level": level,
                                "force_recompute": True,
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
            feature_batch_size = preprocessing_config.get('feature_batch_size', 256)
            await training_logger.info("Calling AI service for feature extraction")
            await db.commit()

            try:
                async with httpx.AsyncClient(timeout=3600.0) as client:
                    resp = await client.post(
                        f"{AI_SERVICE_URL}/api/ai/training/extract_features",
                        json={
                            "task_id": task_id,
                            "wsi_ids": wsi_ids,
                            "feature_extractor": "resnet50",
                            "batch_size": feature_batch_size,
                            "force_recompute": True,
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

            await training_logger.info("Feature extraction completed for all WSI")
            await db.commit()

            # Step 3: ABMIL training via AI service
            epochs = int(model_config.get('epochs', 10))
            lr = float(model_config.get('learning_rate', 1e-4))

            await training_logger.info("Calling AI service to train ABMIL model")
            await db.commit()

            try:
                async with httpx.AsyncClient(timeout=3600.0) as client:
                    resp = await client.post(
                        f"{AI_SERVICE_URL}/api/ai/training/train_abmil",
                        json={
                            "task_id": task_id,
                            "epochs": epochs,
                            "lr": lr,
                        },
                    )
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

            await training_logger.info("Training pipeline completed successfully")
            # Do not overwrite status here; AI service sets progress to 100 and status to completed
            await db.commit()

        except Exception as e:
            if training_logger:
                await training_logger.error(f"Training pipeline failed: {e}", metadata={"error": str(e)})
            await TrainingTaskRepository.update_status(
                db, task_id, "failed", progress=0, error_message=str(e)
            )
            await db.commit()

        finally:
            # Close logger
            if training_logger:
                await training_logger.close()
            # Note: db session is automatically closed by get_db() context manager

