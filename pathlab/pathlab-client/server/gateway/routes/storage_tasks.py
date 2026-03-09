"""
Storage batch task routes — background tasks, task management, and SSE streaming.

Extracted from storage.py for maintainability.
Includes:
- Cancellation mechanism for storage tasks
- Background task functions (batch import, reset derived data, delete external, batch update metadata)
- Task start endpoints (POST /tasks/batch-import, /tasks/delete-external, /tasks/batch-update-metadata)
- Reset derived data endpoint (POST /reset-derived-data)
- Task management endpoints (GET /tasks/stream, GET /tasks/{task_id}, DELETE /tasks/{task_id})
"""
import asyncio
import json
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import delete as sql_delete
from backend.database import get_db, async_session, safe_session
from backend.database.repositories import (
    WSIRepository,
    DatasetRepository,
    DataGroupRepository,
    TrainingTaskRepository,
    StorageTaskRepository,
    SegmentationAnnotationRepository,
)
from backend.database.models import TrainingTaskWSI, AIResult, AITask
from backend.auth import current_active_user, User, get_user_from_token_param
from backend.auth.dependencies import require_admin
from ..dependencies import logger, storage_manager
from ..models import StartBatchImportRequest, StartDeleteExternalRequest, StartBatchUpdateMetadataRequest
from ..utils import (
    ensure_segmentation_contract,
    ensure_dataset_segmentation_contract,
    find_matching_segmentation_annotation_path,
    load_coco_annotation_file,
    SEGMENTATION_TASK_TYPE,
)
from backend.ai.schemas.base import TaskStatus
from backend.common.annotation_summary_cache import rebuild_dataset_annotation_summary_cache
from backend.common.config import Config
from backend.common.file_types import is_patch_file

router = APIRouter()

# ==============================================================================
# Storage Task Cancellation Mechanism
# ==============================================================================
# Thread-safe set to track cancelled storage tasks
_storage_cancellation_requests: set[str] = set()


def request_storage_task_cancellation(task_id: str) -> bool:
    """
    Request cancellation of a storage task (batch_import or delete_external).

    Returns:
        True if cancellation was requested (task will stop at next iteration)
    """
    _storage_cancellation_requests.add(task_id)
    logger.info(f"Cancellation requested for storage task {task_id}")
    return True


def is_storage_task_cancelled(task_id: str) -> bool:
    """
    Check if a storage task has been requested to cancel.

    Background tasks should call this in their processing loops.
    """
    return task_id in _storage_cancellation_requests


def clear_storage_task_cancellation(task_id: str) -> None:
    """
    Clear the cancellation flag for a storage task after it has been processed.
    """
    _storage_cancellation_requests.discard(task_id)


# ==============================================================================
# Reset Derived Data Endpoint
# ==============================================================================

@router.post("/reset-derived-data")
async def reset_derived_data(
    background_tasks: BackgroundTasks,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Start a reset derived data background task.
    This is a DESTRUCTIVE operation used for forcing a complete data reset.
    Admin only operation.

    Deletes:
    - All coordinates, masks, features, AI results, training data, models, logs, metadata

    Preserves:
    - Original WSI files in wsi_files/

    Returns the task ID immediately while processing continues in the background.
    Progress can be monitored via SSE at /storage/tasks/stream
    """
    try:
        # Generate task ID
        task_id = f"reset_{uuid.uuid4().hex[:16]}"

        # Create task record (8 directories to delete)
        task = await StorageTaskRepository.create(
            db,
            task_id=task_id,
            user_id=str(user.id),
            task_type='reset_derived_data',
            total_items=8,  # 8 directories to delete
            params={}
        )
        await db.commit()

        # Start background task
        background_tasks.add_task(
            _run_reset_derived_data_task,
            task_id,
            str(user.id)
        )

        return {
            "task_id": task_id,
            "message": "Reset derived data task started",
            "total_items": 8
        }

    except Exception as e:
        logger.error(f"Failed to start reset derived data task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start reset derived data task: {str(e)}")


# ==============================================================================
# Background Task Functions for Batch Operations
# ==============================================================================

async def _run_batch_import_task(task_id: str, user_id: str, request_params: dict):
    """
    Background task for batch importing WSI files.
    Updates progress in database as it processes files.
    """
    from ..utils import extract_wsi_properties
    import uuid as uuid_module

    async with async_session() as db:
        try:
            # Update task status to processing
            await StorageTaskRepository.update_status(db, task_id, 'processing', progress=0)
            await db.commit()

            files = request_params.get('files', [])
            dataset_id = request_params.get('dataset_id')
            dataset_name = request_params.get('dataset_name')
            aggregation_level = request_params.get('aggregation_level', 'file')
            task_type = request_params.get('task_type', 'classification')
            default_label = request_params.get('default_label')
            default_event_time = request_params.get('default_event_time')
            default_event_status = request_params.get('default_event_status')

            total_files = len(files)
            results = []
            success_count = 0
            failed_count = 0
            skipped_count = 0

            # Resolve or create dataset
            resolved_dataset_id = None
            resolved_dataset_name = None

            if task_type == 'segmentation' and aggregation_level != 'file':
                await StorageTaskRepository.update_status(
                    db, task_id, 'failed',
                    error_message="Segmentation batch import must use aggregation_level='file'"
                )
                await db.commit()
                return

            if dataset_id:
                existing_dataset = await DatasetRepository.get_by_id(db, dataset_id)
                if not existing_dataset:
                    await StorageTaskRepository.update_status(
                        db, task_id, 'failed',
                        error_message=f"Dataset not found: {dataset_id}"
                    )
                    await db.commit()
                    return
                try:
                    data_group = ensure_dataset_segmentation_contract(
                        existing_dataset,
                        context='Batch import',
                        expected_task_type=task_type,
                    )
                except HTTPException as exc:
                    await StorageTaskRepository.update_status(db, task_id, 'failed', error_message=str(exc.detail))
                    await db.commit()
                    return
                resolved_dataset_id = dataset_id
                resolved_dataset_name = existing_dataset.name
            elif dataset_name:
                # Determine data_type from files (default to 'wsi')
                # Check first file to determine if patch or wsi
                data_type = 'wsi'
                if task_type == 'segmentation':
                    if any(not is_patch_file((f.get('path', '') if isinstance(f, dict) else f.path)) for f in files):
                        await StorageTaskRepository.update_status(
                            db, task_id, 'failed',
                            error_message='Segmentation batch import only supports patch/image files with same-name COCO JSON annotations'
                        )
                        await db.commit()
                        return
                    data_type = 'patch'
                    aggregation_level = 'file'
                elif files:
                    first_file_path = files[0].get('path', '') if isinstance(files[0], dict) else files[0].path
                    if is_patch_file(first_file_path):
                        data_type = 'patch'

                try:
                    ensure_segmentation_contract(task_type, data_type, aggregation_level, context='Batch import')
                except HTTPException as exc:
                    await StorageTaskRepository.update_status(db, task_id, 'failed', error_message=str(exc.detail))
                    await db.commit()
                    return

                # Get or create DataGroup first
                data_group = await DataGroupRepository.get_or_create(
                    db,
                    data_type=data_type,
                    aggregation_level=aggregation_level,
                    task_type=task_type
                )

                # Create dataset with group_id
                dataset = await DatasetRepository.get_or_create(db, dataset_name, group_id=data_group.group_id, user_id=user_id)
                if dataset.user_id != user_id:
                    dataset.user_id = user_id
                    await db.flush()
                resolved_dataset_id = dataset.dataset_id
                resolved_dataset_name = dataset.name
            else:
                await StorageTaskRepository.update_status(
                    db, task_id, 'failed',
                    error_message="Either dataset_id or dataset_name is required"
                )
                await db.commit()
                return

            # Get existing files in dataset to check for duplicates
            existing_wsi = await WSIRepository.get_by_dataset(db, resolved_dataset_id, limit=10000, skip=0)
            existing_set = {wsi.original_filename for wsi in existing_wsi}

            # Process each file
            for i, file_info in enumerate(files):
                # Check for cancellation at the start of each iteration
                if is_storage_task_cancelled(task_id):
                    logger.info(f"Batch import task {task_id} cancelled by user at file {i + 1}/{total_files}")
                    clear_storage_task_cancellation(task_id)
                    # Status already updated by cancel endpoint, just exit
                    return

                try:
                    file_path = file_info.get('path') if isinstance(file_info, dict) else file_info.path
                    format_type = file_info.get('format_type', 'standard') if isinstance(file_info, dict) else getattr(file_info, 'format_type', 'standard')
                    associated_data = file_info.get('associated_data') if isinstance(file_info, dict) else getattr(file_info, 'associated_data', None)

                    path_obj = Path(file_path)

                    # Skip if file doesn't exist
                    if not path_obj.exists():
                        results.append({
                            "path": file_path,
                            "wsi_id": None,
                            "status": "failed",
                            "message": "File not found"
                        })
                        failed_count += 1
                        continue

                    # Check for duplicates
                    original_filename = path_obj.name
                    if original_filename in existing_set:
                        results.append({
                            "path": file_path,
                            "wsi_id": None,
                            "status": "skipped",
                            "message": "File already exists in dataset"
                        })
                        skipped_count += 1
                        continue

                    # Extract properties first to get file_size for type detection
                    props = extract_wsi_properties(file_path)
                    file_size = props.get("file_size", 0)

                    # Generate ID based on file type (wsi_xxx or patch_xxx)
                    if is_patch_file(file_path, file_size):
                        wsi_id = f"patch_{uuid_module.uuid4().hex[:16]}"
                    else:
                        wsi_id = f"wsi_{uuid_module.uuid4().hex[:16]}"

                    # Build associated_files JSON
                    associated_files_json = None
                    if format_type in ('mrxs', 'tmap'):
                        associated_files_json = {"format_type": format_type}
                        if format_type == 'mrxs' and associated_data:
                            associated_files_json["data_folder"] = associated_data
                        elif format_type == 'tmap' and associated_data:
                            associated_files_json["dt_files"] = associated_data if isinstance(associated_data, list) else []

                    # Create WSI record
                    wsi_data = {
                        "wsi_id": wsi_id,
                        "original_filename": original_filename,
                        "wsi_path": file_path,
                        "dataset_id": resolved_dataset_id,
                        "file_size": props.get("file_size", 0),
                        "width": props.get("width"),
                        "height": props.get("height"),
                        "mpp": props.get("mpp"),
                        "magnification": props.get("magnification"),
                        "vendor": props.get("vendor"),
                        "user_id": user_id,
                        "associated_files": associated_files_json,
                        "case_id": uuid.uuid4().hex[:12],  # Random unique case_id; users override via CSV registration later
                    }

                    # Set label or survival data based on task type
                    if task_type == "survival":
                        wsi_data["event_time"] = default_event_time
                        wsi_data["event_status"] = default_event_status
                    elif task_type == 'segmentation':
                        if not is_patch_file(file_path, file_size):
                            results.append({
                                "path": file_path,
                                "wsi_id": None,
                                "status": "failed",
                                "message": "Segmentation batch import only supports patch/image files"
                            })
                            failed_count += 1
                            continue
                        matched_json_path = find_matching_segmentation_annotation_path(file_path)
                        if matched_json_path is None:
                            results.append({
                                "path": file_path,
                                "wsi_id": None,
                                "status": "failed",
                                "message": "Missing same-name COCO JSON annotation"
                            })
                            failed_count += 1
                            continue
                        try:
                            coco_data = load_coco_annotation_file(matched_json_path)
                        except HTTPException as json_err:
                            results.append({
                                "path": file_path,
                                "wsi_id": None,
                                "status": "failed",
                                "message": str(json_err.detail)
                            })
                            failed_count += 1
                            continue
                        wsi_data["label"] = None
                    else:
                        wsi_data["label"] = default_label

                    await WSIRepository.create(db, wsi_data)

                    # For segmentation tasks: import matched COCO JSON annotation file
                    if task_type == 'segmentation':
                        annotation_id = f"annot_{wsi_id}"
                        await SegmentationAnnotationRepository.upsert(
                            db,
                            annotation_id=annotation_id,
                            user_id=user_id,
                            annotations=coco_data,
                            source_dataset_id=resolved_dataset_id,
                            status="finalized",
                            source="import",
                        )
                        logger.info(f"Imported COCO annotation for {wsi_id} from {matched_json_path.name}")

                    results.append({
                        "path": file_path,
                        "wsi_id": wsi_id,
                        "status": "success",
                        "message": "Registered successfully"
                    })
                    success_count += 1
                    existing_set.add(original_filename)

                except Exception as e:
                    results.append({
                        "path": file_path if 'file_path' in dir() else str(file_info),
                        "wsi_id": None,
                        "status": "failed",
                        "message": str(e)
                    })
                    failed_count += 1
                    logger.error(f"Failed to register WSI in batch import task {task_id}: {e}")

                # Update progress
                progress = int(((i + 1) / total_files) * 100)
                await StorageTaskRepository.update_status(
                    db, task_id, 'processing',
                    progress=progress,
                    processed_items=i + 1,
                    success_count=success_count,
                    failed_count=failed_count,
                    skipped_count=skipped_count
                )
                await db.commit()

            # Update task with final results
            await StorageTaskRepository.update_status(
                db, task_id, 'completed',
                progress=100,
                processed_items=total_files,
                success_count=success_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                results=results
            )
            await db.commit()

            if task_type == 'segmentation' and resolved_dataset_id and success_count > 0:
                try:
                    await rebuild_dataset_annotation_summary_cache(db, resolved_dataset_id)
                except Exception as cache_err:
                    logger.warning(f"Failed to refresh annotation summary cache for {resolved_dataset_id}: {cache_err}")

            logger.info(f"Batch import task {task_id} completed: {success_count} success, {failed_count} failed, {skipped_count} skipped")

        except Exception as e:
            logger.error(f"Batch import task {task_id} failed: {e}")
            await StorageTaskRepository.update_status(
                db, task_id, 'failed',
                error_message=str(e)
            )
            await db.commit()


async def _run_reset_derived_data_task(task_id: str, user_id: str):
    """
    Background task for resetting all derived data.
    Updates progress in database as it processes directories.
    """
    async with async_session() as db:
        try:
            # Update task status to processing
            await StorageTaskRepository.update_status(db, task_id, 'processing', progress=0)
            await db.commit()

            # Define progress callback to update database
            def progress_callback(progress: int):
                """Synchronous callback to update progress - will be called from sync context"""
                # We can't use async here since it's called from sync code
                # Instead, we'll update progress after the operation completes
                pass

            # Run the reset operation in thread pool
            result = await asyncio.to_thread(
                storage_manager.reset_derived_data,
                progress_callback=None  # We'll update progress manually
            )

            # Update task with final results
            await StorageTaskRepository.update_status(
                db, task_id, 'completed',
                progress=100,
                processed_items=8,
                success_count=len(result.get('deleted_dirs', [])),
                failed_count=len(result.get('failed', [])),
                results=[{
                    "deleted_dirs": result.get('deleted_dirs', []),
                    "failed": result.get('failed', []),
                    "total_size": result.get('total_size', 0),
                    "summary": result.get('summary', '')
                }]
            )
            await db.commit()

            logger.info(f"Reset derived data task {task_id} completed: {result.get('summary', '')}")

        except Exception as e:
            logger.error(f"Reset derived data task {task_id} failed: {e}")
            await StorageTaskRepository.update_status(
                db, task_id, 'failed',
                error_message=str(e)
            )
            await db.commit()


async def _run_delete_external_task(task_id: str, user_id: str, wsi_ids: list):
    """
    Background task for deleting external WSI records.
    Updates progress in database as it processes files.
    """
    async with async_session() as db:
        try:
            # Update task status to processing
            await StorageTaskRepository.update_status(db, task_id, 'processing', progress=0)
            await db.commit()

            total_items = len(wsi_ids)
            results = []
            deleted_count = 0
            failed_count = 0
            affected_dataset_ids = set()  # Track datasets that may become empty

            for i, wsi_id in enumerate(wsi_ids):
                # Check for cancellation at the start of each iteration
                if is_storage_task_cancelled(task_id):
                    logger.info(f"Delete external task {task_id} cancelled by user at item {i + 1}/{total_items}")
                    clear_storage_task_cancellation(task_id)
                    # Status already updated by cancel endpoint, just exit
                    return

                try:
                    # Get WSI to verify it exists and get wsi_path for cache cleanup
                    wsi = await WSIRepository.get_by_id(db, wsi_id)
                    if not wsi:
                        results.append({
                            "wsi_id": wsi_id,
                            "status": "failed",
                            "message": "WSI not found"
                        })
                        failed_count += 1
                        continue

                    wsi_path = wsi.wsi_path
                    affected_dataset_id = wsi.dataset_id  # Track for post-delete cleanup

                    # Delete all associated data before deleting the WSI record
                    # This mirrors the behavior of delete_wsi API in wsi.py
                    try:
                        # Delete training task associations first (foreign key constraint)
                        await db.execute(
                            sql_delete(TrainingTaskWSI).where(TrainingTaskWSI.wsi_id == wsi_id)
                        )
                        # Delete AI results
                        await db.execute(
                            sql_delete(AIResult).where(AIResult.wsi_id == wsi_id)
                        )
                        # Delete AI tasks
                        await db.execute(
                            sql_delete(AITask).where(AITask.wsi_id == wsi_id)
                        )
                    except Exception as assoc_error:
                        logger.warning(f"Failed to delete associated data for {wsi_id}: {assoc_error}")

                    # Delete the WSI record
                    success = await WSIRepository.delete(db, wsi_id)
                    if success:
                        await db.commit()

                        # Delete all cache files (coordinates, masks, thumbnails, ai_results, features)
                        # Use "complete" mode to delete everything including training features
                        # Pass wsi_path=None to skip deleting the actual WSI file (it's external)
                        try:
                            storage_cleanup = await asyncio.to_thread(
                                storage_manager.delete_wsi_files,
                                wsi_id,
                                None,  # Don't delete the actual WSI file (it's external)
                                "complete"
                            )
                            logger.info(f"Cleaned up cache files for {wsi_id}: {storage_cleanup.get('summary', '')}")
                        except Exception as cleanup_error:
                            logger.warning(f"Failed to cleanup cache files for {wsi_id}: {cleanup_error}")

                        results.append({
                            "wsi_id": wsi_id,
                            "status": "deleted",
                            "message": "Record and cache files deleted successfully"
                        })
                        deleted_count += 1
                        if affected_dataset_id:
                            affected_dataset_ids.add(affected_dataset_id)
                    else:
                        results.append({
                            "wsi_id": wsi_id,
                            "status": "failed",
                            "message": "Failed to delete record"
                        })
                        failed_count += 1

                except Exception as e:
                    results.append({
                        "wsi_id": wsi_id,
                        "status": "failed",
                        "message": str(e)
                    })
                    failed_count += 1
                    logger.error(f"Failed to delete WSI {wsi_id} in task {task_id}: {e}")

                # Update progress
                progress = int(((i + 1) / total_items) * 100)
                await StorageTaskRepository.update_status(
                    db, task_id, 'processing',
                    progress=progress,
                    processed_items=i + 1,
                    success_count=deleted_count,
                    failed_count=failed_count
                )
                await db.commit()

            # Clean up empty datasets after all deletions
            if affected_dataset_ids and deleted_count > 0:
                for ds_id in affected_dataset_ids:
                    try:
                        remaining = await WSIRepository.count_by_dataset(db, ds_id)
                        if remaining == 0:
                            await DatasetRepository.delete(db, ds_id)
                            await db.commit()
                            logger.info(f"Cleaned up empty dataset {ds_id} after external delete")
                    except Exception as ds_err:
                        logger.warning(f"Failed to cleanup empty dataset {ds_id}: {ds_err}")
            # Update task with final results
            await StorageTaskRepository.update_status(
                db, task_id, 'completed',
                progress=100,
                processed_items=total_items,
                success_count=deleted_count,
                failed_count=failed_count,
                results=results
            )
            await db.commit()

            logger.info(f"Delete external task {task_id} completed: {deleted_count} deleted, {failed_count} failed")

        except Exception as e:
            logger.error(f"Delete external task {task_id} failed: {e}")
            await StorageTaskRepository.update_status(
                db, task_id, 'failed',
                error_message=str(e)
            )
            await db.commit()


async def _run_batch_update_metadata_task(task_id: str, user_id: str, request_params: dict):
    """
    Background task for batch updating WSI metadata.
    Updates progress in database as it processes files.
    Skips updates when the new value matches the existing value.
    """
    async with async_session() as db:
        try:
            # Update task status to processing
            await StorageTaskRepository.update_status(db, task_id, 'processing', progress=0)
            await db.commit()

            wsi_ids = request_params.get('wsi_ids', [])
            # Metadata fields to update
            new_label = request_params.get('label')
            new_case_id = request_params.get('case_id')
            new_age = request_params.get('age')
            new_gender = request_params.get('gender')
            new_source = request_params.get('source')
            new_event_time = request_params.get('event_time')
            new_event_status = request_params.get('event_status')

            total_items = len(wsi_ids)
            results = []
            updated_count = 0
            skipped_count = 0
            failed_count = 0
            dataset_task_type_map = {}

            if new_label is not None and wsi_ids:
                wsi_map = await WSIRepository.get_by_ids(db, wsi_ids)
                dataset_ids = sorted({wsi.dataset_id for wsi in wsi_map.values() if wsi.dataset_id})
                datasets = await DatasetRepository.get_by_ids(db, dataset_ids) if dataset_ids else []
                dataset_task_type_map = {
                    dataset.dataset_id: (dataset.data_group.task_type if dataset.data_group else None)
                    for dataset in datasets
                }

            for i, wsi_id in enumerate(wsi_ids):
                # Check for cancellation at the start of each iteration
                if is_storage_task_cancelled(task_id):
                    logger.info(f"Batch update metadata task {task_id} cancelled by user at item {i + 1}/{total_items}")
                    clear_storage_task_cancellation(task_id)
                    return

                try:
                    # Get WSI to check existing values
                    wsi = await WSIRepository.get_by_id(db, wsi_id)
                    if not wsi:
                        results.append({
                            "wsi_id": wsi_id,
                            "status": "failed",
                            "message": "WSI not found"
                        })
                        failed_count += 1
                        continue

                    if new_label is not None and dataset_task_type_map.get(wsi.dataset_id) == SEGMENTATION_TASK_TYPE:
                        results.append({
                            "wsi_id": wsi_id,
                            "status": "failed",
                            "message": "Segmentation WSIs do not support image-level label updates"
                        })
                        failed_count += 1
                        continue

                    # Build update dict, only include fields that are different
                    update_data = {}
                    if new_label is not None and wsi.label != new_label:
                        update_data['label'] = new_label
                    if new_case_id is not None and wsi.case_id != new_case_id:
                        update_data['case_id'] = new_case_id
                    if new_age is not None and wsi.age != new_age:
                        update_data['age'] = new_age
                    if new_gender is not None and wsi.gender != new_gender:
                        update_data['gender'] = new_gender
                    if new_source is not None and wsi.source != new_source:
                        update_data['source'] = new_source
                    if new_event_time is not None and wsi.event_time != new_event_time:
                        update_data['event_time'] = new_event_time
                    if new_event_status is not None and wsi.event_status != new_event_status:
                        update_data['event_status'] = new_event_status

                    # Skip if no changes needed
                    if not update_data:
                        results.append({
                            "wsi_id": wsi_id,
                            "status": "skipped",
                            "message": "No changes needed"
                        })
                        skipped_count += 1
                    else:
                        # Perform update
                        await WSIRepository.update(db, wsi_id, update_data)
                        await db.commit()
                        results.append({
                            "wsi_id": wsi_id,
                            "status": "updated",
                            "message": f"Updated {len(update_data)} field(s)"
                        })
                        updated_count += 1

                except Exception as e:
                    results.append({
                        "wsi_id": wsi_id,
                        "status": "failed",
                        "message": str(e)
                    })
                    failed_count += 1
                    logger.error(f"Failed to update WSI {wsi_id} in task {task_id}: {e}")

                # Update progress
                progress = int(((i + 1) / total_items) * 100)
                await StorageTaskRepository.update_status(
                    db, task_id, 'processing',
                    progress=progress,
                    processed_items=i + 1,
                    success_count=updated_count,
                    failed_count=failed_count,
                    skipped_count=skipped_count
                )
                await db.commit()

            # Update task with final results
            await StorageTaskRepository.update_status(
                db, task_id, 'completed',
                progress=100,
                processed_items=total_items,
                success_count=updated_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                results=results
            )
            await db.commit()

            logger.info(f"Batch update metadata task {task_id} completed: {updated_count} updated, {skipped_count} skipped, {failed_count} failed")

        except Exception as e:
            logger.error(f"Batch update metadata task {task_id} failed: {e}")
            await StorageTaskRepository.update_status(
                db, task_id, 'failed',
                error_message=str(e)
            )
            await db.commit()


# ==============================================================================
# Background Task API Endpoints
# ==============================================================================

@router.post("/tasks/batch-import")
async def start_batch_import_task(
    request: StartBatchImportRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Start a batch import background task.
    Admin only operation.

    Returns the task ID immediately while processing continues in the background.
    Progress can be monitored via SSE at /storage/tasks/stream
    """
    try:
        if request.task_type == 'segmentation' and request.aggregation_level != 'file':
            raise HTTPException(status_code=400, detail="Segmentation batch import must use aggregation_level='file'")

        # Generate task ID
        task_id = f"import_{uuid.uuid4().hex[:16]}"

        default_label = request.default_label if request.task_type == 'classification' else None

        # Prepare params for storage
        params = {
            "files": [f.model_dump() if hasattr(f, 'model_dump') else f.dict() for f in request.files],
            "dataset_id": request.dataset_id,
            "dataset_name": request.dataset_name,
            "aggregation_level": request.aggregation_level,
            "task_type": request.task_type,
            "default_label": default_label,
            "default_event_time": request.default_event_time,
            "default_event_status": request.default_event_status,
        }

        # Create task record
        task = await StorageTaskRepository.create(
            db,
            task_id=task_id,
            user_id=str(user.id),
            task_type='batch_import',
            total_items=len(request.files),
            params=params
        )
        await db.commit()

        # Start background task
        background_tasks.add_task(
            _run_batch_import_task,
            task_id,
            str(user.id),
            params
        )

        return {
            "task_id": task_id,
            "message": "Batch import task started",
            "total_files": len(request.files)
        }

    except Exception as e:
        logger.error(f"Failed to start batch import task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start batch import: {str(e)}")


@router.post("/tasks/delete-external")
async def start_delete_external_task(
    request: StartDeleteExternalRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Start a delete external files background task.
    Admin only operation.

    Returns the task ID immediately while processing continues in the background.
    Progress can be monitored via SSE at /storage/tasks/stream
    """
    try:
        # Generate task ID
        task_id = f"delete_{uuid.uuid4().hex[:16]}"

        # Create task record
        task = await StorageTaskRepository.create(
            db,
            task_id=task_id,
            user_id=str(user.id),
            task_type='delete_external',
            total_items=len(request.wsi_ids),
            params={"wsi_ids": request.wsi_ids}
        )
        await db.commit()

        # Start background task
        background_tasks.add_task(
            _run_delete_external_task,
            task_id,
            str(user.id),
            request.wsi_ids
        )

        return {
            "task_id": task_id,
            "message": "Delete external files task started",
            "total_files": len(request.wsi_ids)
        }

    except Exception as e:
        logger.error(f"Failed to start delete external task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start delete external task: {str(e)}")


@router.post("/tasks/batch-update-metadata")
async def start_batch_update_metadata_task(
    request: StartBatchUpdateMetadataRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Start a batch update metadata background task.
    All authenticated users can update their own WSI metadata.

    Returns the task ID immediately while processing continues in the background.
    Progress can be monitored via SSE at /storage/tasks/stream

    Optimization: Skips updates when the new value matches the existing value.
    """
    try:
        if not request.wsi_ids:
            raise HTTPException(status_code=400, detail="No WSI IDs provided")

        if request.label is not None:
            wsis = await WSIRepository.get_by_ids(db, request.wsi_ids)
            dataset_ids = sorted({wsi.dataset_id for wsi in wsis.values() if wsi.dataset_id})
            datasets = await DatasetRepository.get_by_ids(db, dataset_ids) if dataset_ids else []
            segmentation_dataset_ids = {
                dataset.dataset_id
                for dataset in datasets
                if dataset.data_group and dataset.data_group.task_type == SEGMENTATION_TASK_TYPE
            }
            if any(wsi.dataset_id in segmentation_dataset_ids for wsi in wsis.values()):
                raise HTTPException(
                    status_code=400,
                    detail="Segmentation WSIs do not support image-level label updates",
                )

        # Check if at least one field is provided
        has_update = any([
            request.label is not None,
            request.case_id is not None,
            request.age is not None,
            request.gender is not None,
            request.source is not None,
            request.event_time is not None,
            request.event_status is not None,
        ])
        if not has_update:
            return {
                "task_id": "no-op",
                "message": "No metadata fields provided to update, nothing to do",
                "total_items": 0
            }

        # Generate task ID
        task_id = f"update_{uuid.uuid4().hex[:16]}"

        # Prepare params for storage
        params = {
            "wsi_ids": request.wsi_ids,
            "label": request.label,
            "case_id": request.case_id,
            "age": request.age,
            "gender": request.gender,
            "source": request.source,
            "event_time": request.event_time,
            "event_status": request.event_status,
        }

        # Create task record
        task = await StorageTaskRepository.create(
            db,
            task_id=task_id,
            user_id=str(user.id),
            task_type='batch_update_metadata',
            total_items=len(request.wsi_ids),
            params=params
        )
        await db.commit()

        # Start background task
        background_tasks.add_task(
            _run_batch_update_metadata_task,
            task_id,
            str(user.id),
            params
        )

        return {
            "task_id": task_id,
            "message": "Batch update metadata task started",
            "total_items": len(request.wsi_ids)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start batch update metadata task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start batch update metadata task: {str(e)}")


# ==============================================================================
# Task Management Endpoints (SSE streaming, get, cancel)
# ==============================================================================

@router.get("/tasks/stream")
async def stream_storage_tasks(user: User = Depends(get_user_from_token_param)):
    """
    Server-Sent Events endpoint for real-time storage task updates.
    Streams task status and progress updates to connected clients.

    Admin users see all admin tasks, regular users see nothing (storage tasks are admin-only).

    Note: Uses token query parameter for authentication since EventSource API
    doesn't support custom headers. Token is passed via URL: ?token=<jwt>
    """
    # Only admin users can see storage tasks (they are admin-only operations)
    if not user.is_admin():
        # Non-admin users get empty stream
        async def empty_generator():
            while True:
                yield f"data: {json.dumps({'items': []})}\n\n"
                await asyncio.sleep(5)

        return StreamingResponse(
            empty_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    # For admin users, filter by their user_id to implement targeted push
    # Admin notifications only visible to the admin who created them
    user_id_filter = str(user.id)

    async def event_generator():
        """Generate SSE events with storage task updates"""
        consecutive_errors = 0
        last_data_hash = None
        BASE_INTERVAL = 5  # seconds between polls (increased from 2s)

        try:
            while True:
                # Use safe_session to ensure proper connection cleanup on cancel
                async with safe_session() as db:
                    try:
                        # Fetch storage tasks for this admin user
                        tasks = await StorageTaskRepository.get_user_tasks(
                            db, user_id=user_id_filter, limit=50
                        )

                        result_tasks = [task.to_dict() for task in tasks]

                        # Change detection: only send if data changed
                        data = json.dumps({"items": result_tasks})
                        import hashlib
                        data_hash = hashlib.md5(data.encode()).hexdigest()
                        if data_hash != last_data_hash:
                            yield f"data: {data}\n\n"
                            last_data_hash = data_hash

                        consecutive_errors = 0  # Reset on success
                    except Exception as e:
                        consecutive_errors += 1
                        logger.error(f"Error fetching storage tasks in SSE (consecutive={consecutive_errors}): {e}")
                        yield f"data: {json.dumps({'error': str(e)})}\n\n"

                # Exponential backoff on consecutive errors: 5s → 10s → 20s → 30s (cap)
                if consecutive_errors > 0:
                    backoff = min(BASE_INTERVAL * (2 ** consecutive_errors), 30)
                    await asyncio.sleep(backoff)
                else:
                    await asyncio.sleep(BASE_INTERVAL)

        except asyncio.CancelledError:
            # Client disconnected
            logger.info("SSE storage tasks client disconnected")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/tasks/{task_id}")
async def get_storage_task(
    task_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get storage task status by ID.
    Admin only operation.
    """
    task = await StorageTaskRepository.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Check ownership - admin can only see their own tasks
    if task.user_id != str(user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    return task.to_dict()


@router.delete("/tasks/{task_id}")
async def cancel_storage_task(
    task_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel a running storage task (batch_import or delete_external).
    Admin only operation.

    - If the task is running, it will be cancelled at the next iteration
    - If the task is pending, it will be marked as cancelled
    - Already completed/failed/cancelled tasks cannot be cancelled

    Returns:
        {"cancelled": bool, "message": str}
    """
    task = await StorageTaskRepository.get_by_id(db, task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Check ownership
    if task.user_id != str(user.id):
        raise HTTPException(status_code=403, detail="You don't have permission to cancel this task")

    # Check if task can be cancelled
    if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
        return {
            "cancelled": False,
            "message": f"Task {task_id} is already {task.status}"
        }

    # Request cancellation (background task will check this flag)
    request_storage_task_cancellation(task_id)

    # Update database status to cancelled
    await StorageTaskRepository.update_status(
        db,
        task_id,
        status=TaskStatus.CANCELLED,
        error_message="Task cancelled by user"
    )
    await db.commit()

    logger.info(f"Storage task {task_id} cancelled by user {user.id}")

    return {
        "cancelled": True,
        "message": f"Task {task_id} cancelled successfully"
    }