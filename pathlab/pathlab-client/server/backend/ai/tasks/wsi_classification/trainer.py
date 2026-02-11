"""WSI Classification Trainer - integrates feature extraction and MIL training."""
from __future__ import annotations

import json
import asyncio
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional, Union

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from sklearn.metrics import (
    roc_auc_score, accuracy_score, precision_score, recall_score, f1_score,
    confusion_matrix as sklearn_confusion_matrix
)

from backend.ai.tasks.base import BaseTrainer
from backend.ai.extractors import get_extractor
from backend.ai.aggregators import get_aggregator
from backend.ai.utils.dataset import build_dataloader
from backend.ai.utils.feature_dataset import WSIFeatureDataset, CaseFeatureDataset
from backend.ai.utils.vram_guard import (
    check_vram_before_model_load,
    check_vram_before_batch_processing,
    VRAMInsufficientError,
    VRAMExceededError,
)
from backend.ai.schemas import TaskType, TaskStatus, TrainResponse, FeatureExtractionResponse
from backend.ai.tasks.feature_cache import (
    compute_params_hash,
    find_cached_features,
    get_cache_save_path,
    create_symlink_to_cache,
    read_params_from_coords_h5,
    acquire_feature_lock,
    safe_load_features,
    save_features,
    FeatureLockTimeoutError,
)
from backend.ai.tasks.patch_cache import find_any_cached_coords_for_wsi
from backend.database.repositories import WSIRepository, TrainingTaskRepository, AIResultRepository
from backend.ai.cancellation import is_task_cancelled, TrainingCancelledException
from backend.ai.permission_revocation import is_permission_revoked, PermissionRevokedException
from backend.common.config import Config
from contextlib import asynccontextmanager
import anyio
import logging

_scoped_db_logger = logging.getLogger("ai.scoped_db")


async def _safe_update_progress(session_maker, task_id: str, status: str, progress: int):
    """Write progress to shared file. Gateway reads the file directly — no DB, no HTTP.

    File: {uploads_dir}/progress/{task_id}  (atomic write via tmpfile + rename)
    Crash recovery: file persists on disk, Gateway reads last written value.
    Non-fatal: if file write fails, training continues.
    """
    from backend.common.progress_store import set_progress

    set_progress(task_id, progress)


@asynccontextmanager
async def scoped_db(session_maker):
    """Create a short-lived database session for a single operation.

    Follows the same pattern as safe_session() in database.py:
    - The main operation is NOT shielded (allows timeout/cancellation to work)
    - Only cleanup (rollback/close) is shielded to ensure proper resource release

    Includes timeout protection to prevent indefinite blocking on
    long-running database operations.
    """
    timeout = Config.DB_OPERATION_TIMEOUT
    session = session_maker()
    try:
        async with asyncio.timeout(timeout):
            yield session
            await session.commit()
    except TimeoutError:
        with anyio.CancelScope(shield=True):
            await session.rollback()
        _scoped_db_logger.error(
            f"Database operation timed out after {timeout}s."
        )
        raise
    except Exception:
        with anyio.CancelScope(shield=True):
            await session.rollback()
        raise
    finally:
        with anyio.CancelScope(shield=True):
            await session.close()


class WSIClassificationTrainer(BaseTrainer):
    """
    Trainer for WSI-level classification tasks.

    Pipeline:
    1. Extract features from WSI patches using a feature extractor (e.g., ResNet50)
    2. Train an aggregator model (e.g., ABMIL) on extracted features
    3. Save checkpoint and metrics
    """

    task_type = TaskType.WSI_CLASSIFICATION

    async def extract_features(
        self,
        wsi_ids: List[str],
        extractor_name: str,
        batch_size: int,
        force_recompute: bool,
        logger: Any,
        session_maker: Any,
        hf_token: str = "",
        preprocessing_config: Optional[Dict] = None,
    ) -> FeatureExtractionResponse:
        """
        Extract features for all WSI slides sequentially (single-GPU optimized).

        Uses global feature cache to avoid redundant extraction:
        - Cache location: uploads/features/{extractor_name}/{params_hash}/{wsi_id}.pt
        - Task directory: uploads/training/{task_id}/features/{wsi_id}.pt (symlink)

        The params_hash ensures features are only reused when preprocessing config matches.

        Args:
            session_maker: Factory to create short-lived DB sessions (replaces db parameter)
        """
        # VRAM Protection: Check if GPU has enough memory BEFORE loading the model
        # This prevents system crashes from loading models that are too large
        device = torch.device(self.device)
        if device.type == "cuda":
            try:
                await asyncio.to_thread(
                    check_vram_before_model_load,
                    model_name=extractor_name,
                    device=device,
                    batch_size=batch_size,
                )
            except VRAMInsufficientError as e:
                raise RuntimeError(
                    f"VRAM protection triggered: {e.message}"
                ) from e

        # Build extractor once and reuse (blocking: model download + GPU transfer)
        def _load_extractor():
            return get_extractor(extractor_name, pretrained=True, hf_token=hf_token).to(self.device).eval()
        extractor = await asyncio.to_thread(_load_extractor)

        results = []
        total = len(wsi_ids)
        task_features_dir = self.uploads_root / "training" / self.task_id / "features"
        task_features_dir.mkdir(parents=True, exist_ok=True)

        for i, wsi_id in enumerate(wsi_ids, 1):
            # Check for cancellation at each iteration (important for cache hit scenarios)
            if is_task_cancelled(self.task_id):
                raise TrainingCancelledException("Feature extraction cancelled during cache check")

            task_feat_path = task_features_dir / f"{wsi_id}.pt"
            # Find coords_h5 from new cache structure: coordinates/{params_hash}/{wsi_id}_coords.h5
            coords_h5 = find_any_cached_coords_for_wsi(self.uploads_root, wsi_id)
            if not coords_h5:
                raise FileNotFoundError(f"Coordinates not found for {wsi_id}. Please run preprocessing first.")

            # Compute params_hash from coords.h5 to ensure consistency
            # The coords.h5 file contains the actual preprocessing parameters used
            params_hash = read_params_from_coords_h5(coords_h5)
            if not params_hash:
                # Fallback to preprocessing_config if coords.h5 doesn't have params
                preprocessing_config = preprocessing_config or {}
                params_hash = compute_params_hash(
                    patch_size=preprocessing_config.get('tile_size', 512),
                    stride=preprocessing_config.get('stride', 512),
                    level=preprocessing_config.get('level', 0),
                    seg_params={
                        'sthresh': preprocessing_config.get('sthresh', 5),
                        'mthresh': preprocessing_config.get('mthresh', 7),
                        'close': preprocessing_config.get('close', 4),
                        'use_otsu': preprocessing_config.get('use_otsu', False),
                    },
                    filter_params={
                        'a_t': preprocessing_config.get('a_t', 100),
                        'a_h': preprocessing_config.get('a_h', 16),
                        'max_n_holes': preprocessing_config.get('max_n_holes', 8),
                    },
                    contour_fn=preprocessing_config.get('contour_fn', 'four_pt'),
                    use_padding=preprocessing_config.get('use_padding', True),
                    seg_level=preprocessing_config.get('seg_level', -1),
                )

            # Step 1: Check if task-specific features already exist (file or symlink)
            # Just check existence, don't load the file - loading is too slow for many WSIs
            if task_feat_path.exists() and not force_recompute:
                results.append({"wsi_id": wsi_id, "path": str(task_feat_path)})
                # Only update DB every 100 items or at the end to avoid slow commits
                if i % 100 == 0 or i == total:
                    progress = 33 + int(i / total * 33)
                    await _safe_update_progress(session_maker, self.task_id, TaskStatus.EXTRACTING, progress)
                    await logger.info(f"[{i}/{total}] Feature check progress (all cached so far)")
                continue

            # Step 2: Check global feature cache
            cached_path = find_cached_features(
                self.uploads_root, extractor_name, params_hash, wsi_id
            )

            if cached_path and not force_recompute:
                # Cache hit: create symlink directly without loading the file
                # Loading large feature files just for validation is too slow for many WSIs
                create_symlink_to_cache(task_features_dir, wsi_id, cached_path)
                results.append({"wsi_id": wsi_id, "path": str(task_feat_path)})
                # Only update DB every 100 items or at the end to avoid slow commits
                if i % 100 == 0 or i == total:
                    progress = 33 + int(i / total * 33)
                    await _safe_update_progress(session_maker, self.task_id, TaskStatus.EXTRACTING, progress)
                    await logger.info(f"[{i}/{total}] Feature check progress (creating symlinks)")
                continue

            # Step 3: Extract features (cache miss) - use file lock to prevent race conditions
            # When multiple tasks try to extract features for the same WSI simultaneously,
            # only one will actually extract, others will wait and then use the cached result

            # Define cancellation/revocation check for lock waiting
            def check_cancelled_or_revoked():
                return is_task_cancelled(self.task_id) or is_permission_revoked(self.task_id)

            # Track if we logged waiting message (to avoid spam)
            wait_logged = [False]  # Use list to allow modification in closure

            # Define callback for lock wait progress
            def on_lock_wait(wait_seconds: float):
                if not wait_logged[0]:
                    # Log only once when we start waiting
                    import logging
                    lock_logger = logging.getLogger("feature_cache")
                    lock_logger.info(
                        f"[{i}/{total}] Waiting for another task to finish extracting {wsi_id} "
                        f"(waited {wait_seconds:.0f}s, will reuse cached result)"
                    )
                    wait_logged[0] = True

            try:
                async with acquire_feature_lock(
                    self.uploads_root, extractor_name, params_hash, wsi_id,
                    cancellation_check=check_cancelled_or_revoked,
                    wait_callback=on_lock_wait,
                ):
                    # Log if we were waiting
                    if wait_logged[0]:
                        await logger.info(
                            f"[{i}/{total}] Lock acquired for {wsi_id} after waiting",
                            metadata={"wsi_id": wsi_id}
                        )

                    # Re-check cache after acquiring lock - another process may have just finished
                    cached_path = find_cached_features(
                        self.uploads_root, extractor_name, params_hash, wsi_id
                    )
                    if cached_path and not force_recompute:
                        # Another process just finished extracting - try to use their result
                        feats, load_error = await asyncio.to_thread(
                            safe_load_features, cached_path, delete_if_corrupted=True
                        )
                        if feats is not None:
                            create_symlink_to_cache(task_features_dir, wsi_id, cached_path)
                            shape = tuple(feats.shape)
                            await logger.info(
                                f"[{i}/{total}] Cache hit after lock for {wsi_id} (reusing result from another task)",
                                metadata={"wsi_id": wsi_id, "shape": list(shape), "cached_path": str(cached_path)}
                            )
                            results.append({"wsi_id": wsi_id, "shape": shape, "path": str(task_feat_path)})
                            progress = 33 + int(i / total * 33)
                            await _safe_update_progress(session_maker, self.task_id, TaskStatus.EXTRACTING, progress)
                            continue
                        else:
                            # Cached file was corrupted, log and proceed to extract
                            await logger.warning(
                                f"[{i}/{total}] Corrupted cached file after lock for {wsi_id}, will re-extract",
                                metadata={"wsi_id": wsi_id, "cached_path": str(cached_path), "error": load_error}
                            )

                    # Actually extract features - get WSI path with short-lived session
                    async with scoped_db(session_maker) as db:
                        wsi = await WSIRepository.get_by_id(db, wsi_id)
                        if not wsi:
                            raise ValueError(f"WSI not found: {wsi_id}")
                        wsi_path = wsi.wsi_path

                    if not coords_h5.exists():
                        raise FileNotFoundError(f"Coordinates not found for {wsi_id}: {coords_h5}")

                    await logger.info(
                        f"[{i}/{total}] Extracting features for {wsi_id} (cache miss)",
                        metadata={"wsi_id": wsi_id, "wsi_index": i, "total_wsi": total}
                    )

                    feats = await asyncio.to_thread(
                        self._extract_wsi_features,
                        extractor=extractor,
                        wsi_path=str(wsi_path),
                        coords_h5=str(coords_h5),
                        batch_size=batch_size,
                    )

                    # Save to global cache (blocking disk I/O → thread)
                    cache_feat_path = get_cache_save_path(
                        self.uploads_root, extractor_name, params_hash, wsi_id
                    )
                    feats_contiguous = feats.contiguous()
                    await asyncio.to_thread(save_features, cache_feat_path, feats_contiguous)

                    # Create symlink in task directory
                    create_symlink_to_cache(task_features_dir, wsi_id, cache_feat_path)
                    shape = tuple(feats.shape)

                    await logger.info(
                        f"[{i}/{total}] Features saved to cache for {wsi_id}",
                        metadata={"wsi_id": wsi_id, "shape": list(shape), "cache_path": str(cache_feat_path)}
                    )

            except FeatureLockTimeoutError as e:
                # Lock timeout - check if features were completed by another process
                cached_path = find_cached_features(
                    self.uploads_root, extractor_name, params_hash, wsi_id
                )
                if cached_path:
                    feats, load_error = await asyncio.to_thread(
                        safe_load_features, cached_path, delete_if_corrupted=True
                    )
                    if feats is not None:
                        create_symlink_to_cache(task_features_dir, wsi_id, cached_path)
                        shape = tuple(feats.shape)
                        await logger.info(
                            f"[{i}/{total}] Lock timeout but cache found for {wsi_id} (using cached result)",
                            metadata={"wsi_id": wsi_id, "shape": list(shape), "cached_path": str(cached_path)}
                        )
                        results.append({"wsi_id": wsi_id, "shape": shape, "path": str(task_feat_path)})
                        progress = 33 + int(i / total * 33)
                        await _safe_update_progress(session_maker, self.task_id, TaskStatus.EXTRACTING, progress)
                        continue

                # No cache available after timeout - this is a real error
                await logger.error(
                    f"[{i}/{total}] Feature lock timeout for {wsi_id} and no cache available",
                    metadata={"wsi_id": wsi_id, "timeout": e.timeout}
                )
                raise

            progress = 33 + int(i / total * 33)
            await _safe_update_progress(session_maker, self.task_id, TaskStatus.EXTRACTING, progress)

            results.append({"wsi_id": wsi_id, "shape": shape, "path": str(task_feat_path)})

        # Bulk update feature_extracted flag for all processed WSIs
        processed_wsi_ids = [r["wsi_id"] for r in results]
        if processed_wsi_ids:
            try:
                async with scoped_db(session_maker) as db:
                    await WSIRepository.bulk_update_feature_extracted(db, processed_wsi_ids)
            except Exception as e:
                await logger.warning(
                    f"Failed to update feature_extracted flags (non-fatal): {e}",
                    metadata={"count": len(processed_wsi_ids)}
                )

        return self._build_feature_response(results)

    def _extract_wsi_features(
        self,
        extractor: nn.Module,
        wsi_path: str,
        coords_h5: str,
        batch_size: int,
    ) -> torch.Tensor:
        """
        Extract features for a single WSI (synchronous, runs in thread pool).

        Uses the extractor's preprocessing transforms to ensure correct
        normalization and image size for the model.

        This method is intentionally synchronous because all GPU operations
        (model forward pass, tensor transfers) are blocking. It should be
        called via asyncio.to_thread() to avoid blocking the event loop.

        VRAM Protection:
        Before batch processing, this method performs a VRAM check by running
        a single sample through the extractor. If the requested batch_size would
        exceed available VRAM (85% threshold), a VRAMExceededError is raised
        with a suggested safe batch_size.
        """
        # VRAM Protection: Check BEFORE creating the large-batch DataLoader
        # to prevent OOM when loading the first batch
        _log = logging.getLogger(__name__)
        device = torch.device(self.device)

        _log.info(f"[FeatureExtract] START wsi_path={wsi_path}, coords_h5={coords_h5}, "
                  f"batch_size={batch_size}, device={device}")

        if device.type == "cuda":
            # Create a small DataLoader with batch_size=1 for VRAM measurement
            _log.info("[FeatureExtract] Creating VRAM probe DataLoader (num_workers=0, batch_size=1)...")
            probe_loader, probe_dataset = build_dataloader(
                wsi_path=wsi_path,
                coords_h5=coords_h5,
                batch_size=1,  # Use batch_size=1 for safe probing
                num_workers=0,  # No multiprocessing for quick probe
                prefetch_factor=2,  # Ignored when num_workers=0
                pin_memory=False,
                extractor=extractor,
                mode="eval",
            )
            _log.info(f"[FeatureExtract] Probe dataset created, len={len(probe_dataset)}")

            if len(probe_dataset) > 0:
                # Get a single sample for VRAM measurement
                _log.info("[FeatureExtract] Reading first patch for VRAM probe...")
                sample_batch, _ = next(iter(probe_loader))
                _log.info(f"[FeatureExtract] First patch read OK, shape={sample_batch.shape}, numel={sample_batch.numel()}")

                # Guard: collate may return empty tensor if all patches failed to load
                if sample_batch.numel() == 0:
                    _log.warning(
                        f"All patches failed to load for VRAM probe (coords exist but patches unreadable). "
                        f"Returning empty features for {wsi_path}"
                    )
                    del probe_loader, probe_dataset
                    torch.cuda.empty_cache()
                    return torch.empty(0, extractor.output_dim)

                try:
                    _log.info("[FeatureExtract] Running VRAM check (forward pass with batch_size=1)...")
                    check_vram_before_batch_processing(
                        extractor=extractor,
                        sample_input=sample_batch,
                        requested_batch_size=batch_size,
                        device=device,
                        safety_threshold=0.85,  # Use at most 85% of VRAM
                    )
                    _log.info("[FeatureExtract] VRAM check passed")
                except VRAMExceededError as e:
                    # Re-raise with clear message for upstream handling
                    raise RuntimeError(
                        f"VRAM protection triggered: {e.message}. "
                        f"Please reduce batch_size to {e.suggested_batch_size} or lower."
                    ) from e
                # Clean up probe loader
                del probe_loader, probe_dataset
                torch.cuda.empty_cache()
                _log.info("[FeatureExtract] Probe cleanup done")

        # Now create the actual DataLoader with user-specified batch_size
        # Note: Disable pin_memory to avoid CUDA errors in multiprocess DataLoader
        # "RuntimeError: Caught RuntimeError in pin memory thread for device 0"
        _log.info(f"[FeatureExtract] Creating actual DataLoader (num_workers=4, batch_size={batch_size})...")
        loader, dataset = build_dataloader(
            wsi_path=wsi_path,
            coords_h5=coords_h5,
            batch_size=batch_size,
            num_workers=4,
            prefetch_factor=2,
            pin_memory=False,  # Disabled to avoid CUDA pin memory errors
            extractor=extractor,
            mode="eval",
        )
        _log.info(f"[FeatureExtract] DataLoader created, dataset len={len(dataset)}, "
                  f"num_batches≈{(len(dataset) + batch_size - 1) // batch_size}")

        feats_all = []
        batch_count = 0
        total_batches = (len(dataset) + batch_size - 1) // batch_size
        _log.info(f"[FeatureExtract] Starting batch iteration (total_batches≈{total_batches})...")
        # Process batches with inference mode applied per-batch.
        # This method runs in a thread pool (via asyncio.to_thread), so
        # inference_mode won't affect other coroutines on the event loop.
        for imgs, _coords in loader:
            batch_count += 1
            if batch_count <= 3 or batch_count % 50 == 0:
                _log.info(f"[FeatureExtract] Batch {batch_count}/{total_batches}, imgs.shape={imgs.shape}")

            # Check for cancellation or permission revocation at each batch
            if is_task_cancelled(self.task_id):
                raise TrainingCancelledException("Feature extraction cancelled during batch processing")
            if is_permission_revoked(self.task_id):
                raise PermissionRevokedException("Feature extraction stopped: permission revoked by admin")

            # Apply inference_mode only during the actual computation
            with torch.inference_mode():
                imgs = imgs.to(self.device, non_blocking=True)
                feats = extractor(imgs)
                feats_all.append(feats.cpu())  # Keep on CPU to save VRAM

        _log.info(f"[FeatureExtract] Batch iteration complete, total batches processed={batch_count}")

        if len(feats_all) == 0:
            _log.warning(f"[FeatureExtract] No features extracted (0 batches), returning empty tensor")
            return torch.empty(0, extractor.output_dim)

        result = torch.cat(feats_all, dim=0)  # (N, D)
        _log.info(f"[FeatureExtract] DONE, result shape={result.shape}")
        return result

    def _is_kfold_splits(self, splits_map: Dict[str, List[str]]) -> bool:
        """Check if splits_map represents k-fold configuration."""
        return any(key.startswith("fold_") for key in splits_map.keys())

    def _get_num_folds(self, splits_map: Dict[str, List[str]]) -> int:
        """Get number of folds from k-fold splits_map."""
        fold_keys = [k for k in splits_map.keys() if k.startswith("fold_")]
        return len(fold_keys)

    # ==========================================================================
    # Case-Level Support Methods
    # ==========================================================================

    def _convert_splits_to_case_level(
        self,
        splits_map: Dict[str, List[str]],
        wsi_case_map: Dict[str, str],
    ) -> Dict[str, List[str]]:
        """
        Convert slide-level splits to case-level splits.

        This is a pure format conversion: transforms wsi_id-based splits_map to case_id-based.
        All slides in the same case are guaranteed to be in the same split (ensured by
        split_case_dataset() in TrainingTaskRepository.create()).

        Args:
            splits_map: Original splits with wsi_ids {'train': [wsi_ids...], 'val': [...], ...}
            wsi_case_map: Dict mapping wsi_id -> case_id

        Returns:
            case_splits: Dict with case_ids {'train': [case_ids...], 'val': [...], ...}
        """
        # Build case_splits by collecting unique case_ids for each split
        case_splits: Dict[str, List[str]] = {split_name: [] for split_name in splits_map.keys()}
        seen_cases: set = set()

        for split_name, wsi_ids in splits_map.items():
            for wsi_id in wsi_ids:
                case_id = wsi_case_map.get(wsi_id, wsi_id)  # fallback to wsi_id
                if case_id not in seen_cases:
                    seen_cases.add(case_id)
                    case_splits[split_name].append(case_id)

        return case_splits

    def _split_case_attention_to_slides(
        self,
        attention: Optional[np.ndarray],
        case_id: str,
        case_wsi_patch_counts: Dict[str, List[int]],
        case_to_wsi: Dict[str, List[str]],
    ) -> Dict[str, Optional[np.ndarray]]:
        """
        Split case-level attention weights back to individual slides.

        When training with case-level features, the attention is computed over all patches
        from all slides in the case. This method splits the attention back to per-slide
        arrays based on the original patch counts.

        Args:
            attention: Case-level attention array (total_patches,) or (num_classes, total_patches)
            case_id: The case ID to split attention for
            case_wsi_patch_counts: Dict mapping case_id -> list of patch counts per WSI
            case_to_wsi: Dict mapping case_id -> list of wsi_ids

        Returns:
            Dict mapping wsi_id -> attention array for that slide
        """
        if attention is None:
            wsi_ids = case_to_wsi.get(case_id, [])
            return {wsi_id: None for wsi_id in wsi_ids}

        wsi_ids = case_to_wsi.get(case_id, [])
        patch_counts = case_wsi_patch_counts.get(case_id, [])

        if len(wsi_ids) != len(patch_counts):
            # Fallback: return None for all slides
            return {wsi_id: None for wsi_id in wsi_ids}

        slide_attentions: Dict[str, Optional[np.ndarray]] = {}
        start_idx = 0

        for wsi_id, count in zip(wsi_ids, patch_counts):
            end_idx = start_idx + count
            if attention.ndim == 1:
                # Single attention vector: (total_patches,)
                slide_attentions[wsi_id] = attention[start_idx:end_idx]
            elif attention.ndim == 2:
                # Multi-class attention: (num_classes, total_patches)
                slide_attentions[wsi_id] = attention[:, start_idx:end_idx]
            else:
                slide_attentions[wsi_id] = None
            start_idx = end_idx

        return slide_attentions

    def _evaluate_split(
        self,
        model: nn.Module,
        dataset: WSIFeatureDataset,
        classes: List[str],
        criterion: Optional[nn.Module] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate model on a dataset, return metrics.

        Uses DataLoader for memory-efficient evaluation - features are loaded
        on-demand from disk.

        Args:
            model: The model to evaluate
            dataset: WSIFeatureDataset or CaseFeatureDataset to evaluate on
            classes: List of class names
            criterion: Loss function to use (optional). If None, uses unweighted CrossEntropyLoss.

        Returns:
            Dict with loss, accuracy, and auc metrics
        """
        from torch.utils.data import DataLoader

        model.eval()
        all_probs = []
        all_preds = []
        all_labels = []
        total_loss = 0.0
        if criterion is None:
            criterion = nn.CrossEntropyLoss()
        num_classes = len(classes)

        # num_workers=0 for single-process loading - avoids IPC overhead for batch_size=1
        # Features are loaded directly to GPU via Dataset, so no need for pin_memory
        eval_loader = DataLoader(
            dataset,
            batch_size=1,
            shuffle=False,
            num_workers=0,
        )

        with torch.inference_mode():
            for batch in eval_loader:
                # Unpack batch - features shape is (1, num_patches, feature_dim)
                # Features are already on GPU if Dataset was created with device parameter
                features, label, *_ = batch
                H = features.squeeze(0)  # Already on GPU
                y = label.to(self.device)  # Label is still on CPU

                loss, logits = model.run_one_step(H, y, criterion=criterion)
                total_loss += float(loss.item())

                probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                pred_idx = int(probs.argmax())

                all_probs.append(probs)
                all_preds.append(pred_idx)
                all_labels.append(label.item())

        avg_loss = total_loss / max(1, len(dataset))
        all_probs = np.array(all_probs)
        all_preds = np.array(all_preds)
        all_labels = np.array(all_labels)

        accuracy = accuracy_score(all_labels, all_preds)

        # AUC calculation
        try:
            if num_classes == 2:
                auc = roc_auc_score(all_labels, all_probs[:, 1])
            else:
                auc = roc_auc_score(all_labels, all_probs, multi_class='ovr', average='macro')
        except ValueError:
            auc = None

        model.train()
        # Round all metrics to 4 decimal places
        return {
            "loss": round(float(avg_loss), 4),
            "accuracy": round(float(accuracy), 4),
            "auc": round(float(auc), 4) if auc is not None else None
        }

    def _calculate_kfold_comprehensive_metrics(
        self,
        task_id: str,
        fold_keys: List[str],
        classes: List[str],
        splits_map: Optional[Dict[str, List[str]]] = None,
    ) -> tuple:
        """
        Calculate comprehensive metrics for K-Fold training by reading saved JSON files.

        This reads the per-WSI result JSON files saved during K-Fold training and
        calculates metrics using sklearn, similar to how non-K-Fold analysis does it.

        Args:
            task_id: Training task ID
            fold_keys: List of fold keys (e.g., ["fold_0", "fold_1"])
            classes: List of class names
            splits_map: Optional dict mapping fold_key to list of WSI IDs.
                       If provided, directly reads files for known WSI IDs (fast).
                       If None, falls back to scanning directory (slow, for backward compatibility).

        Returns:
            Tuple of:
            - Dict with metric names as keys and {"mean": float, "std": float} as values (aggregated)
            - Dict with fold_key as keys and {metric_name: value} as values (per-fold)
            Metrics include: precision, sensitivity (recall), specificity, f1, auc
        """
        ai_results_root = self.uploads_root / "ai_results"
        n_classes = len(classes)

        # Per-fold metrics (for aggregated calculation)
        fold_metrics = {
            "precision": [],
            "sensitivity": [],
            "specificity": [],
            "f1": [],
            "auc": [],
        }
        # Per-fold detailed values
        per_fold_metrics = {}

        for fold_idx, fold_key in enumerate(fold_keys):
            # Collect predictions for this fold from saved JSON files
            all_preds = []
            all_labels = []
            all_probs = []  # For AUC calculation

            # Fast path: directly read files for known WSI IDs
            if splits_map and fold_key in splits_map:
                wsi_ids = splits_map[fold_key]
                for wsi_id in wsi_ids:
                    result_file = ai_results_root / wsi_id / f"train_{task_id}_{fold_key}_result.json"
                    if result_file.exists():
                        try:
                            with open(result_file, 'r') as f:
                                data = json.load(f)
                                pred = data.get("pred")
                                gt = data.get("ground_truth")
                                probs = data.get("probs", {})
                                if pred and gt:
                                    pred_idx = classes.index(pred) if pred in classes else -1
                                    gt_idx = classes.index(gt) if gt in classes else -1
                                    if pred_idx >= 0 and gt_idx >= 0:
                                        all_preds.append(pred_idx)
                                        all_labels.append(gt_idx)
                                        probs_arr = [probs.get(cls, 0.0) for cls in classes]
                                        all_probs.append(probs_arr)
                        except Exception:
                            continue
            # Slow path: scan directory (fallback for backward compatibility)
            elif ai_results_root.exists():
                for wsi_dir in ai_results_root.iterdir():
                    if wsi_dir.is_dir():
                        result_file = wsi_dir / f"train_{task_id}_{fold_key}_result.json"
                        if result_file.exists():
                            try:
                                with open(result_file, 'r') as f:
                                    data = json.load(f)
                                    if data.get("task_id") == task_id and data.get("fold_key") == fold_key:
                                        pred = data.get("pred")
                                        gt = data.get("ground_truth")
                                        probs = data.get("probs", {})
                                        if pred and gt:
                                            pred_idx = classes.index(pred) if pred in classes else -1
                                            gt_idx = classes.index(gt) if gt in classes else -1
                                            if pred_idx >= 0 and gt_idx >= 0:
                                                all_preds.append(pred_idx)
                                                all_labels.append(gt_idx)
                                                probs_arr = [probs.get(cls, 0.0) for cls in classes]
                                                all_probs.append(probs_arr)
                            except Exception:
                                continue

            if not all_preds:
                continue

            all_preds = np.array(all_preds)
            all_labels = np.array(all_labels)
            all_probs = np.array(all_probs)

            # Calculate metrics using sklearn
            precision = precision_score(all_labels, all_preds, average='macro', zero_division=0)
            recall = recall_score(all_labels, all_preds, average='macro', zero_division=0)
            f1 = f1_score(all_labels, all_preds, average='macro', zero_division=0)

            # Specificity calculation (macro average)
            cm = sklearn_confusion_matrix(all_labels, all_preds, labels=list(range(n_classes)))
            specificities = []
            for i in range(n_classes):
                tp = cm[i, i]
                fp = cm[:, i].sum() - tp
                fn = cm[i, :].sum() - tp
                tn = cm.sum() - tp - fp - fn
                spec = tn / (tn + fp) if (tn + fp) > 0 else 0
                specificities.append(spec)
            specificity = np.mean(specificities) if specificities else 0.0

            # AUC calculation
            try:
                if n_classes == 2:
                    auc_val = roc_auc_score(all_labels, all_probs[:, 1])
                else:
                    auc_val = roc_auc_score(all_labels, all_probs, multi_class='ovr', average='macro')
            except ValueError:
                auc_val = None

            # Filter out nan values before appending
            if not np.isnan(precision):
                fold_metrics["precision"].append(precision)
            if not np.isnan(recall):
                fold_metrics["sensitivity"].append(recall)
            if not np.isnan(specificity):
                fold_metrics["specificity"].append(specificity)
            if not np.isnan(f1):
                fold_metrics["f1"].append(f1)
            if auc_val is not None and not np.isnan(auc_val):
                fold_metrics["auc"].append(auc_val)

            # Store per-fold values (rounded to 4 decimal places), skip nan values
            per_fold_metrics[fold_key] = {}
            if not np.isnan(precision):
                per_fold_metrics[fold_key]["precision"] = round(float(precision), 4)
            if not np.isnan(recall):
                per_fold_metrics[fold_key]["sensitivity"] = round(float(recall), 4)
            if not np.isnan(specificity):
                per_fold_metrics[fold_key]["specificity"] = round(float(specificity), 4)
            if not np.isnan(f1):
                per_fold_metrics[fold_key]["f1"] = round(float(f1), 4)
            if auc_val is not None and not np.isnan(auc_val):
                per_fold_metrics[fold_key]["auc"] = round(float(auc_val), 4)

        # Calculate mean and std for each metric (rounded to 4 decimal places)
        aggregated = {}
        for metric_name, values in fold_metrics.items():
            if values:
                mean_val = float(np.mean(values))
                std_val = float(np.std(values))
                if not np.isnan(mean_val) and not np.isnan(std_val):
                    aggregated[metric_name] = {
                        "mean": round(mean_val, 4),
                        "std": round(std_val, 4),
                    }

        return aggregated, per_fold_metrics

    def _run_one_epoch(
        self,
        train_loader,
        model: nn.Module,
        criterion: nn.Module,
        optimizer,
        device: str,
        task_id: str,
    ):
        """
        Run one training epoch synchronously.

        Must be called via asyncio.to_thread() to avoid blocking the event loop.
        DataLoader iteration triggers torch.load() in __getitem__(), and GPU
        operations (forward/backward pass) are also blocking.

        Returns:
            Tuple of (running_loss, stop_reason).
            stop_reason is None if completed normally, 'cancelled' or 'permission_revoked' otherwise.
        """
        running_loss = 0.0
        batch_count = 0
        for batch in train_loader:
            batch_count += 1
            features, label, *_ = batch
            H = features.squeeze(0)
            y = label.to(device)

            loss, logits = model.run_one_step(H, y, criterion=criterion)

            # Check for cancellation/permission every 50 batches
            if batch_count % 50 == 0:
                if is_task_cancelled(task_id):
                    return None, "cancelled"
                if is_permission_revoked(task_id):
                    return None, "permission_revoked"

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            running_loss += float(loss.item())

        return running_loss, None


    async def _train_single_run(
        self,
        train_dataset: WSIFeatureDataset,
        val_dataset: Optional[WSIFeatureDataset],
        classes: List[str],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        session_maker: Any,
        run_name: str = "",
        progress_base: int = 66,
        progress_range: int = 24,  # 66-90%, leaving 90-100% for saving results
        optimizer_type: str = "adam",
        auto_balance: bool = False,
        early_stopping_patience: int = 10,
    ) -> Dict[str, Any]:
        """
        Train a single model run (used for both regular training and k-fold).

        Uses PyTorch DataLoader for memory-efficient training - features are loaded
        on-demand from disk instead of being pre-loaded into memory.

        Args:
            train_dataset: WSIFeatureDataset or CaseFeatureDataset for training
            val_dataset: Optional dataset for validation
            classes: List of class names
            aggregator_name: Name of aggregator model
            num_classes: Number of classes
            epochs: Number of training epochs
            lr: Learning rate
            logger: Logger instance
            db: Database session
            run_name: Name for logging
            progress_base: Starting progress percentage
            progress_range: Progress range for this run
            optimizer_type: Optimizer type ('adam', 'sgd', 'adamw')
            auto_balance: Whether to apply class weights for imbalanced datasets
            early_stopping_patience: Number of epochs to wait before early stopping

        Returns dict with model, history, and metrics.
        """
        from torch.utils.data import DataLoader

        # Blocking: torch.load() inside get_feature_dim()
        in_dim = await asyncio.to_thread(train_dataset.get_feature_dim)

        # Blocking: GPU model creation
        model = await asyncio.to_thread(
            lambda: get_aggregator(aggregator_name, in_dim=in_dim, num_classes=num_classes).to(self.device)
        )

        # Calculate class weights for auto-balancing
        class_weights = None
        if auto_balance:
            # Blocking: iterates dataset calling torch.load() for each sample
            def _compute_class_counts():
                counts = [0] * num_classes
                for idx in range(len(train_dataset)):
                    _, label, *_ = train_dataset[idx]
                    counts[label] += 1
                return counts

            class_counts = await asyncio.to_thread(_compute_class_counts)
            # Formula: weight[i] = n_total / (n_classes * n_samples[i])
            n_total = len(train_dataset)
            class_weights = torch.tensor([
                n_total / (num_classes * max(1, count)) for count in class_counts
            ], dtype=torch.float32, device=self.device)
            await logger.info(
                f"Auto-balance enabled: class_weights={[f'{w:.2f}' for w in class_weights.tolist()]}",
                metadata={"class_counts": class_counts, "class_weights": class_weights.tolist()}
            )

        criterion = nn.CrossEntropyLoss(weight=class_weights)

        # Dynamic optimizer selection
        optimizer_type_lower = optimizer_type.lower()
        if optimizer_type_lower == "sgd":
            optimizer = optim.SGD(model.parameters(), lr=lr, momentum=0.9, weight_decay=0.0)
        elif optimizer_type_lower == "adamw":
            optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
        else:  # Default to adam
            optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=0.0)

        # Learning rate scheduler
        scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

        history = {"train_loss": [], "val_loss": [], "val_accuracy": [], "val_auc": []}
        best_val_loss = float('inf')
        best_val_auc = None
        best_state_dict = None
        epochs_without_improvement = 0

        # Create DataLoader for training - batch_size=1 since each WSI has variable number of patches
        # shuffle=True for training randomization
        # num_workers=0 for single-process loading - avoids IPC overhead for batch_size=1
        # Features are loaded directly to GPU via Dataset, so no need for pin_memory
        train_loader = DataLoader(
            train_dataset,
            batch_size=1,
            shuffle=True,
            num_workers=0,
        )

        model.train()



        for epoch in range(1, epochs + 1):
            # Check for cancellation or permission revocation at each epoch start
            if is_task_cancelled(self.task_id):
                await logger.info(f"{run_name} Training cancelled by user/timeout at epoch {epoch}")
                # Clean up CUDA tensors before raising exception to ensure GPU memory is freed
                del model, optimizer, criterion
                if class_weights is not None:
                    del class_weights
                torch.cuda.empty_cache()  # Release cached GPU memory
                raise TrainingCancelledException(f"Training cancelled at epoch {epoch}")
            if is_permission_revoked(self.task_id):
                await logger.info(f"{run_name} Training stopped: permission revoked at epoch {epoch}")
                del model, optimizer, criterion
                if class_weights is not None:
                    del class_weights
                torch.cuda.empty_cache()  # Release cached GPU memory
                raise PermissionRevokedException(f"Training stopped at epoch {epoch}: permission revoked by admin")

            # Run training epoch in thread pool to avoid blocking the event loop.
            # DataLoader iteration triggers torch.load() and GPU ops are blocking.
            running_loss, stop_reason = await asyncio.to_thread(
                self._run_one_epoch, train_loader, model, criterion, optimizer, self.device, self.task_id
            )

            if stop_reason == "cancelled":
                del model, optimizer, criterion
                if class_weights is not None:
                    del class_weights
                torch.cuda.empty_cache()
                raise TrainingCancelledException(f"Training cancelled during epoch {epoch} loop")
            if stop_reason == "permission_revoked":
                del model, optimizer, criterion
                if class_weights is not None:
                    del class_weights
                torch.cuda.empty_cache()
                raise PermissionRevokedException(f"Training stopped during epoch {epoch}: permission revoked by admin")

            epoch_loss = running_loss / max(1, len(train_dataset))
            history["train_loss"].append(epoch_loss)

            # Validation - run in thread pool (DataLoader + GPU inference are blocking)
            val_metrics = {"loss": None, "accuracy": None, "auc": None}
            if val_dataset is not None and len(val_dataset) > 0:
                val_metrics = await asyncio.to_thread(self._evaluate_split, model, val_dataset, classes, criterion)
                history["val_loss"].append(val_metrics["loss"])
                history["val_accuracy"].append(val_metrics["accuracy"])
                history["val_auc"].append(val_metrics["auc"])

                # Track best model
                # Use AUC for model selection if available (higher is better)
                # Fallbck to Loss (lower is better) if AUC is None
                is_improvement = False
                if val_metrics["auc"] is not None:
                     if best_val_auc is None or val_metrics["auc"] > best_val_auc:
                        best_val_auc = val_metrics["auc"]
                        is_improvement = True
                else:
                    if val_metrics["loss"] < best_val_loss:
                        best_val_loss = val_metrics["loss"]
                        is_improvement = True

                if is_improvement:
                    best_val_loss = val_metrics["loss"]
                    best_state_dict = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                    epochs_without_improvement = 0
                else:
                    epochs_without_improvement += 1

            # Log progress
            log_msg = f"{run_name} Epoch {epoch}/{epochs} - train_loss: {epoch_loss:.4f}"
            if val_dataset is not None and len(val_dataset) > 0:
                log_msg += f", val_loss: {val_metrics['loss']:.4f}, val_acc: {val_metrics['accuracy']:.4f}"

            # Prepare metadata with val_ prefix for validation metrics
            metadata = {"epoch": epoch, "train_loss": epoch_loss}
            if val_dataset is not None and len(val_dataset) > 0:
                metadata.update({f"val_{k}": v for k, v in val_metrics.items()})
            await logger.info(log_msg, metadata=metadata)

            # Calculate progress using (epoch-1) to ensure we never reach progress_base + progress_range
            # This keeps training progress smoothly increasing but always < 90%
            progress = progress_base + int((epoch - 1) / epochs * progress_range)
            await _safe_update_progress(session_maker, self.task_id, TaskStatus.TRAINING, progress)

            # Update learning rate
            scheduler.step()

            # Early stopping check
            if val_dataset is not None and len(val_dataset) > 0 and epochs_without_improvement >= early_stopping_patience:
                stopped_metric = f"auc={best_val_auc:.4f}" if best_val_auc is not None else f"loss={best_val_loss:.4f}"
                await logger.info(
                    f"{run_name} Early stopping triggered at epoch {epoch} (no improvement for {early_stopping_patience} epochs)",
                    metadata={"epoch": epoch, "best_val_metric": stopped_metric}
                )
                break

        # Restore best model if we have validation
        if best_state_dict is not None:
            model.load_state_dict(best_state_dict)

        return {"model": model, "in_dim": in_dim, "history": history, "criterion": criterion}

    async def _validate_and_repair_features(
        self,
        features_dir: Path,
        all_wsi_ids: List[str],
        feature_extractor: str,
        logger: Any,
        session_maker: Any,
    ) -> None:
        """
        Validate all feature files and re-extract any corrupted or missing ones.

        This prevents training from crashing due to corrupted .pt files
        (e.g., from incomplete writes before the atomic .partial mechanism was added).
        """
        corrupted_ids = []
        for wsi_id in all_wsi_ids:
            feat_path = features_dir / f"{wsi_id}.pt"
            if not feat_path.exists():
                corrupted_ids.append(wsi_id)
                continue
            loaded_feats, load_error = safe_load_features(
                feat_path, delete_if_corrupted=True
            )
            if loaded_feats is None:
                await logger.warning(
                    f"Corrupted feature file detected for {wsi_id}: {load_error}"
                )
                corrupted_ids.append(wsi_id)

        if not corrupted_ids:
            return

        await logger.info(
            f"Re-extracting features for {len(corrupted_ids)} corrupted/missing WSIs",
            metadata={"count": len(corrupted_ids), "wsi_ids": corrupted_ids[:10]}
        )

        # Get hf_token from global settings
        hf_token = Config.get_global_settings().get("huggingface_token", "")

        # Get preprocessing_config from task
        async with scoped_db(session_maker) as db:
            task = await TrainingTaskRepository.get_by_id(db, self.task_id)
        preprocessing_config = task.preprocessing_config if task else None

        # Re-extract features for corrupted WSIs
        await self.extract_features(
            wsi_ids=corrupted_ids,
            extractor_name=feature_extractor,
            batch_size=32,
            force_recompute=True,
            logger=logger,
            session_maker=session_maker,
            hf_token=hf_token,
            preprocessing_config=preprocessing_config,
        )

    async def train_model(
        self,
        splits_map: Dict[str, List[str]],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        session_maker: Any,
        optimizer: str = "adam",
        auto_balance: bool = False,
        early_stopping_patience: int = 10,
        feature_extractor: str = "",
        seed: Optional[int] = 42,
    ) -> TrainResponse:
        """
        Train aggregator with proper data splits.

        Uses PyTorch DataLoader for memory-efficient training - features are loaded
        on-demand from disk instead of being pre-loaded into memory.

        Supports:
        - Regular splits: {'train': [...], 'val': [...], 'test': [...]}
        - K-Fold CV: {'fold_0': [...], 'fold_1': [...], ...}
        - Case-level training: features from slides in same case are concatenated on-demand

        Args:
            session_maker: Factory to create short-lived DB sessions (replaces db parameter)
            optimizer: Optimizer type ('adam', 'sgd', 'adamw')
            auto_balance: Whether to apply class weights for imbalanced datasets
            early_stopping_patience: Number of epochs to wait before early stopping
            seed: Random seed for reproducibility (default: 42)
        """
        # Set global random seeds for reproducibility
        if seed is not None:
            self._set_seed(seed)
            await logger.info(f"Random seed set to {seed} for reproducibility")

        # Collect all WSI IDs
        all_wsi_ids = []
        for ids in splits_map.values():
            all_wsi_ids.extend(ids)
        all_wsi_ids = list(set(all_wsi_ids))

        # Features directory - features are loaded on-demand via Dataset
        features_dir = self.uploads_root / "training" / self.task_id / "features"

        # Validate feature files and re-extract any corrupted ones
        if feature_extractor:
            await self._validate_and_repair_features(
                features_dir, all_wsi_ids, feature_extractor, logger, session_maker
            )

        # Get labels from database using batch query (avoid N+1 problem)
        async with scoped_db(session_maker) as db:
            wsi_map = await WSIRepository.get_by_ids(db, all_wsi_ids)

        labels = {}
        classes = []
        for wsi_id in all_wsi_ids:
            wsi = wsi_map.get(wsi_id)
            if not wsi or not wsi.label:
                raise ValueError(f"WSI {wsi_id} has invalid/missing label")
            if wsi.label not in classes:
                classes.append(wsi.label)

        classes = sorted(classes)
        for wsi_id in all_wsi_ids:
            wsi = wsi_map[wsi_id]
            labels[wsi_id] = classes.index(wsi.label)

        # Check for case-level training
        async with scoped_db(session_maker) as db:
            aggregation_level = await TrainingTaskRepository.get_dataset_aggregation_level(db, self.task_id)
        is_case_level = aggregation_level == 'case'

        # Prepare case-level data structures if needed
        case_to_wsi: Optional[Dict[str, List[str]]] = None
        case_labels: Optional[Dict[str, int]] = None
        case_splits: Optional[Dict[str, List[str]]] = None
        wsi_case_map: Optional[Dict[str, str]] = None

        if is_case_level:
            # Get case_id mapping for all WSIs
            async with scoped_db(session_maker) as db:
                wsi_case_map = await TrainingTaskRepository.get_wsi_case_ids(db, self.task_id)

            # Build case_to_wsi mapping and case_labels
            case_to_wsi = {}
            for wsi_id, case_id in wsi_case_map.items():
                if case_id not in case_to_wsi:
                    case_to_wsi[case_id] = []
                case_to_wsi[case_id].append(wsi_id)

            # case_labels: use label from first WSI in each case
            case_labels = {}
            for case_id, wsi_ids_in_case in case_to_wsi.items():
                if wsi_ids_in_case:
                    case_labels[case_id] = labels[wsi_ids_in_case[0]]

            # Convert splits to case-level
            case_splits = self._convert_splits_to_case_level(splits_map, wsi_case_map)

            await logger.info(
                f"[Case-Level] Training with {len(case_to_wsi)} cases from {len(all_wsi_ids)} slides",
                metadata={"num_cases": len(case_to_wsi), "num_slides": len(all_wsi_ids), "aggregation_level": "case"}
            )

        model_id = f"{aggregator_name}_{self.task_id}"
        model_dir = self.uploads_root / "models" / model_id
        model_dir.mkdir(parents=True, exist_ok=True)

        is_kfold = self._is_kfold_splits(splits_map)

        # Build case-level context dict to pass to training methods
        case_level_ctx = None
        if is_case_level:
            case_level_ctx = {
                "case_to_wsi": case_to_wsi,
                "case_labels": case_labels,
                "case_splits": case_splits,
                "wsi_case_map": wsi_case_map,
                "original_labels": labels,
            }

        if is_kfold:
            return await self._train_kfold(
                splits_map, features_dir, labels, classes, aggregator_name, num_classes,
                epochs, lr, logger, session_maker, model_id, model_dir,
                optimizer, auto_balance, early_stopping_patience,
                case_level_ctx=case_level_ctx,
            )
        else:
            return await self._train_regular(
                splits_map, features_dir, labels, classes, aggregator_name, num_classes,
                epochs, lr, logger, session_maker, model_id, model_dir,
                optimizer, auto_balance, early_stopping_patience,
                case_level_ctx=case_level_ctx,
            )

    async def _train_regular(
        self,
        splits_map: Dict[str, List[str]],
        features_dir: Path,
        labels: Dict[str, int],
        classes: List[str],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        session_maker: Any,
        model_id: str,
        model_dir: Path,
        optimizer: str = "adam",
        auto_balance: bool = False,
        early_stopping_patience: int = 10,
        case_level_ctx: Optional[Dict[str, Any]] = None,
    ) -> TrainResponse:
        """
        Train with regular train/val/test splits.

        Uses PyTorch DataLoader for memory-efficient training.
        """
        is_case_level = case_level_ctx is not None

        # Use case-level splits and data if applicable
        if is_case_level:
            case_splits = case_level_ctx["case_splits"]
            train_ids = list(case_splits.get("train", []))
            val_ids = list(case_splits.get("val", []))
            test_ids = case_splits.get("test", [])
            case_to_wsi = case_level_ctx["case_to_wsi"]
            case_labels = case_level_ctx["case_labels"]
        else:
            train_ids = list(splits_map.get("train", []))
            val_ids = list(splits_map.get("val", []))
            test_ids = splits_map.get("test", [])

        if not train_ids:
            raise ValueError("No training samples in splits_map")

        # Auto-create val split from train if val is empty (10% of train)
        auto_val_created = False
        if not val_ids and len(train_ids) > 1:
            import random
            n_val = max(1, int(len(train_ids) * 0.1))
            random.shuffle(train_ids)
            val_ids = train_ids[:n_val]
            train_ids = train_ids[n_val:]
            auto_val_created = True

        unit_name = "cases" if is_case_level else "slides"
        if auto_val_created:
            await logger.info(
                f"Auto-created val split: moved {len(val_ids)} {unit_name} from train to val (10%)",
                metadata={"train": len(train_ids), "val": len(val_ids), "test": len(test_ids), "auto_val": True}
            )

        await logger.info(
            f"Training with splits: train={len(train_ids)}, val={len(val_ids)}, test={len(test_ids)} {unit_name}",
            metadata={"train": len(train_ids), "val": len(val_ids), "test": len(test_ids)}
        )

        # Create datasets for training
        # Pass device to Dataset for direct GPU loading - avoids CPU->GPU transfer overhead
        if is_case_level:
            train_dataset = CaseFeatureDataset(
                features_dir=features_dir,
                case_ids=train_ids,
                case_to_wsi=case_to_wsi,
                labels=case_labels,
                task_type="classification",
                device=self.device,
            )
            val_dataset = CaseFeatureDataset(
                features_dir=features_dir,
                case_ids=val_ids,
                case_to_wsi=case_to_wsi,
                labels=case_labels,
                task_type="classification",
                device=self.device,
            ) if val_ids else None
            test_dataset = CaseFeatureDataset(
                features_dir=features_dir,
                case_ids=test_ids,
                case_to_wsi=case_to_wsi,
                labels=case_labels,
                task_type="classification",
                device=self.device,
            ) if test_ids else None
        else:
            train_dataset = WSIFeatureDataset(
                features_dir=features_dir,
                wsi_ids=train_ids,
                labels=labels,
                task_type="classification",
                device=self.device,
            )
            val_dataset = WSIFeatureDataset(
                features_dir=features_dir,
                wsi_ids=val_ids,
                labels=labels,
                task_type="classification",
                device=self.device,
            ) if val_ids else None
            test_dataset = WSIFeatureDataset(
                features_dir=features_dir,
                wsi_ids=test_ids,
                labels=labels,
                task_type="classification",
                device=self.device,
            ) if test_ids else None

        result = await self._train_single_run(
            train_dataset=train_dataset,
            val_dataset=val_dataset,
            classes=classes,
            aggregator_name=aggregator_name,
            num_classes=num_classes,
            epochs=epochs,
            lr=lr,
            logger=logger,
            session_maker=session_maker,
            optimizer_type=optimizer,
            auto_balance=auto_balance,
            early_stopping_patience=early_stopping_patience
        )

        model = result["model"]
        in_dim = result["in_dim"]
        history = result["history"]
        train_criterion = result.get("criterion")

        # Evaluate on test set
        test_metrics = None
        if test_dataset is not None and len(test_dataset) > 0:
            test_metrics = await asyncio.to_thread(self._evaluate_split, model, test_dataset, classes, train_criterion)
            await logger.info(
                f"Test metrics: loss={test_metrics['loss']:.4f}, acc={test_metrics['accuracy']:.4f}",
                metadata=test_metrics
            )

        # Save checkpoint - blocking disk I/O
        ckpt_path = model_dir / "aggregator.pth"
        await asyncio.to_thread(torch.save, {
            "state_dict": model.state_dict(),
            "in_dim": in_dim,
            "num_classes": num_classes,
        }, ckpt_path)

        # Save config
        # Note: aggregation_level uses 'file' instead of 'slide' for clarity
        (model_dir / "config.json").write_text(json.dumps({
            "task_id": self.task_id,
            "model": aggregator_name,
            "in_dim": in_dim,
            "num_classes": num_classes,
            "epochs": epochs,
            "lr": lr,
            "split_type": "regular",
            "aggregation_level": "case" if is_case_level else "file",
        }, ensure_ascii=False, indent=2))

        # Save metrics
        metrics_data = {
            "is_kfold": False,
            "history": history,
            "val_metrics": {
                "accuracy": history["val_accuracy"][-1] if history["val_accuracy"] else None,
                "auc": history["val_auc"][-1] if history["val_auc"] else None,
            } if val_ids else None,
            "test_metrics": test_metrics,
        }
        (model_dir / "metrics.json").write_text(json.dumps(metrics_data, ensure_ascii=False, indent=2))

        # Save per-WSI inference results
        # For case-level, create a dataset with all cases for inference
        # Pass device for direct GPU loading
        all_sample_ids = train_ids + val_ids + test_ids
        if is_case_level:
            all_dataset = CaseFeatureDataset(
                features_dir=features_dir,
                case_ids=all_sample_ids,
                case_to_wsi=case_to_wsi,
                labels=case_labels,
                task_type="classification",
                device=self.device,
            )
        else:
            all_dataset = WSIFeatureDataset(
                features_dir=features_dir,
                wsi_ids=all_sample_ids,
                labels=labels,
                task_type="classification",
                device=self.device,
            )

        await self._save_training_inference_results(
            model=model,
            dataset=all_dataset,
            classes=classes,
            task_id=self.task_id,
            logger=logger,
            session_maker=session_maker,
            aggregator_name=aggregator_name,
            case_level_ctx=case_level_ctx,
            test_sample_ids=test_ids if test_ids else None,
        )

        return self._build_train_response(
            model_id=model_id,
            checkpoint_path=str(ckpt_path),
            loss_history=history["train_loss"],
            val_metrics=test_metrics or (metrics_data.get("val_metrics") if val_ids else None),
        )

    async def _train_kfold(
        self,
        splits_map: Dict[str, List[str]],
        features_dir: Path,
        labels: Dict[str, int],
        classes: List[str],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        session_maker: Any,
        model_id: str,
        model_dir: Path,
        optimizer: str = "adam",
        auto_balance: bool = False,
        early_stopping_patience: int = 10,
        case_level_ctx: Optional[Dict[str, Any]] = None,
    ) -> TrainResponse:
        """
        Train with K-Fold cross-validation.

        Uses PyTorch DataLoader for memory-efficient training.
        """
        is_case_level = case_level_ctx is not None

        # Use case-level splits and data if applicable
        if is_case_level:
            case_splits = case_level_ctx["case_splits"]
            case_to_wsi = case_level_ctx["case_to_wsi"]
            case_labels = case_level_ctx["case_labels"]
            working_splits = case_splits
        else:
            working_splits = splits_map

        num_folds = self._get_num_folds(working_splits)
        fold_keys = sorted([k for k in working_splits.keys() if k.startswith("fold_")])

        unit_name = "cases" if is_case_level else "slides"
        await logger.info(
            f"Starting {num_folds}-fold cross-validation ({unit_name})",
            metadata={"num_folds": num_folds, "epochs_per_fold": epochs, "aggregation_level": "case" if is_case_level else "file"}
        )

        fold_results = {}
        all_val_metrics = {"accuracy": [], "auc": [], "loss": []}

        for fold_idx, val_fold_key in enumerate(fold_keys):
            # Current fold is validation, all others are training
            val_ids = working_splits[val_fold_key]
            train_ids = []
            for key in fold_keys:
                if key != val_fold_key:
                    train_ids.extend(working_splits[key])

            await logger.info(
                f"Fold {fold_idx + 1}/{num_folds}: train={len(train_ids)}, val={len(val_ids)} {unit_name}",
                metadata={"fold": fold_idx + 1, "train": len(train_ids), "val": len(val_ids)}
            )

            # Create datasets for this fold
            # Pass device for direct GPU loading
            if is_case_level:
                train_dataset = CaseFeatureDataset(
                    features_dir=features_dir,
                    case_ids=train_ids,
                    case_to_wsi=case_to_wsi,
                    labels=case_labels,
                    task_type="classification",
                    device=self.device,
                )
                val_dataset = CaseFeatureDataset(
                    features_dir=features_dir,
                    case_ids=val_ids,
                    case_to_wsi=case_to_wsi,
                    labels=case_labels,
                    task_type="classification",
                    device=self.device,
                )
            else:
                train_dataset = WSIFeatureDataset(
                    features_dir=features_dir,
                    wsi_ids=train_ids,
                    labels=labels,
                    task_type="classification",
                    device=self.device,
                )
                val_dataset = WSIFeatureDataset(
                    features_dir=features_dir,
                    wsi_ids=val_ids,
                    labels=labels,
                    task_type="classification",
                    device=self.device,
                )

            # Calculate progress for this fold (66-100% total for all folds including saving)
            # Each fold gets (100-66)/num_folds = 34/num_folds percent
            # Within each fold: 70% for training, 30% for saving
            fold_total_range = 34 / num_folds
            fold_progress_base = 66 + int(fold_idx * fold_total_range)
            fold_training_range = int(fold_total_range * 0.7)  # 70% for training
            fold_saving_base = fold_progress_base + fold_training_range
            fold_saving_range = max(1, int(fold_total_range * 0.3))  # 30% for saving, min 1%

            result = await self._train_single_run(
                train_dataset=train_dataset,
                val_dataset=val_dataset,
                classes=classes,
                aggregator_name=aggregator_name,
                num_classes=num_classes,
                epochs=epochs,
                lr=lr,
                logger=logger,
                session_maker=session_maker,
                run_name=f"[Fold {fold_idx + 1}/{num_folds}]",
                progress_base=fold_progress_base,
                progress_range=fold_training_range,
                optimizer_type=optimizer,
                auto_balance=auto_balance,
                early_stopping_patience=early_stopping_patience,
            )

            model = result["model"]
            in_dim = result["in_dim"]
            history = result["history"]
            fold_criterion = result.get("criterion")

            # Final validation metrics - run in thread pool (DataLoader + GPU inference are blocking)
            val_metrics = await asyncio.to_thread(self._evaluate_split, model, val_dataset, classes, fold_criterion)

            fold_results[val_fold_key] = {
                "history": history,
                "val_metrics": val_metrics,
            }

            all_val_metrics["accuracy"].append(val_metrics["accuracy"])
            if val_metrics["auc"] is not None:
                all_val_metrics["auc"].append(val_metrics["auc"])
            all_val_metrics["loss"].append(val_metrics["loss"])

            # Save fold checkpoint - blocking disk I/O
            fold_dir = model_dir / val_fold_key
            fold_dir.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(torch.save, {
                "state_dict": model.state_dict(),
                "in_dim": in_dim,
                "num_classes": num_classes,
            }, fold_dir / "aggregator.pth")

            # Save per-WSI inference results for this fold's VALIDATION set only
            # In K-Fold, each sample should be predicted by the model that didn't see it during training
            # This ensures the saved predictions are truly out-of-sample predictions
            await self._save_training_inference_results(
                model=model,
                dataset=val_dataset,
                classes=classes,
                task_id=self.task_id,
                logger=logger,
                session_maker=session_maker,
                aggregator_name=aggregator_name,
                fold_key=val_fold_key,
                progress_base=fold_saving_base,
                progress_range=fold_saving_range,
                case_level_ctx=case_level_ctx,
            )

            auc_str = f"{val_metrics['auc']:.4f}" if val_metrics['auc'] is not None else 'N/A'
            await logger.info(
                f"Fold {fold_idx + 1} complete: acc={val_metrics['accuracy']:.4f}, auc={auc_str}",
                metadata={"fold": fold_idx + 1, **val_metrics}
            )

        # Calculate aggregated statistics (basic metrics from training, rounded to 4 decimal places)
        aggregated = {
            "accuracy": {
                "mean": round(float(np.mean(all_val_metrics["accuracy"])), 4),
                "std": round(float(np.std(all_val_metrics["accuracy"])), 4),
            },
            "loss": {
                "mean": round(float(np.mean(all_val_metrics["loss"])), 4),
                "std": round(float(np.std(all_val_metrics["loss"])), 4),
            },
        }
        if all_val_metrics["auc"]:
            aggregated["auc"] = {
                "mean": round(float(np.mean(all_val_metrics["auc"])), 4),
                "std": round(float(np.std(all_val_metrics["auc"])), 4),
            }

        # Calculate comprehensive metrics by reading saved JSON files
        # This provides precision, sensitivity, specificity, f1, etc. - similar to Analysis
        # Pass splits_map to enable fast direct file access instead of slow directory scanning
        comprehensive_metrics, per_fold_comprehensive = self._calculate_kfold_comprehensive_metrics(
            task_id=self.task_id,
            fold_keys=fold_keys,
            classes=classes,
            splits_map=splits_map,
        )
        # Merge comprehensive metrics into aggregated (don't overwrite accuracy/auc already calculated)
        for metric_name, metric_stats in comprehensive_metrics.items():
            if metric_name not in aggregated:
                aggregated[metric_name] = metric_stats

        # Add per-fold comprehensive metrics to fold_results
        for fold_key, metrics in per_fold_comprehensive.items():
            if fold_key in fold_results:
                fold_results[fold_key]["val_metrics"].update(metrics)

        # Find best fold based on accuracy
        best_fold_idx = int(np.argmax(all_val_metrics["accuracy"]))
        best_fold_key = fold_keys[best_fold_idx]
        best_fold_accuracy = round(float(all_val_metrics["accuracy"][best_fold_idx]), 4)

        await logger.info(
            f"K-Fold complete: accuracy={aggregated['accuracy']['mean']:.4f}±{aggregated['accuracy']['std']:.4f}, "
            f"best={best_fold_key} (acc={best_fold_accuracy:.4f})",
            metadata={"aggregated": aggregated, "best_fold": best_fold_key, "best_fold_accuracy": best_fold_accuracy}
        )

        # Save config
        # Note: aggregation_level uses 'file' instead of 'slide' for clarity
        (model_dir / "config.json").write_text(json.dumps({
            "task_id": self.task_id,
            "model": aggregator_name,
            "in_dim": in_dim,
            "num_classes": num_classes,
            "epochs": epochs,
            "lr": lr,
            "split_type": "kfold",
            "num_folds": num_folds,
            "best_fold": best_fold_key,
            "aggregation_level": "case" if is_case_level else "file",
        }, ensure_ascii=False, indent=2))

        # Save aggregated metrics
        metrics_data = {
            "is_kfold": True,
            "num_folds": num_folds,
            "best_fold": best_fold_key,
            "folds": {k: v for k, v in fold_results.items()},
            "aggregated": aggregated,
        }
        (model_dir / "metrics.json").write_text(json.dumps(metrics_data, ensure_ascii=False, indent=2))

        # Use best fold's checkpoint as default
        ckpt_path = model_dir / best_fold_key / "aggregator.pth"

        # Build val_metrics with only float values
        val_metrics_dict: Dict[str, float] = {
            "accuracy": aggregated["accuracy"]["mean"],
        }
        if aggregated.get("auc", {}).get("mean") is not None:
            val_metrics_dict["auc"] = aggregated["auc"]["mean"]

        return self._build_train_response(
            model_id=model_id,
            checkpoint_path=str(ckpt_path),
            loss_history=fold_results[best_fold_key]["history"]["train_loss"],
            val_metrics=val_metrics_dict,
            kfold_aggregated=aggregated,
        )

    async def _save_training_inference_results(
        self,
        model: nn.Module,
        dataset: Union[WSIFeatureDataset, CaseFeatureDataset],
        classes: List[str],
        task_id: str,
        logger: Any,
        session_maker: Any,
        aggregator_name: str = "unknown",
        fold_key: Optional[str] = None,
        progress_base: int = 90,
        progress_range: int = 10,
        case_level_ctx: Optional[Dict[str, Any]] = None,
        test_sample_ids: Optional[List[str]] = None,
    ) -> None:
        """
        Save per-WSI inference results after training.

        Uses PyTorch DataLoader for memory-efficient inference - features are loaded
        on-demand from disk.

        For case-level training, runs inference on case features and splits
        attention back to per-slide for saving.

        Optimized with:
        - Dynamic progress updates with per-file granularity
        - Parallel file I/O using asyncio
        - Batch database inserts for performance

        Progress allocation within the given range:
        - 0-20%: Inference
        - 20-80%: File I/O (per-file progress)
        - 80-90%: Database insert
        - 90-100%: Metrics calculation

        Args:
            model: Trained model for inference
            dataset: WSIFeatureDataset or CaseFeatureDataset
            classes: List of class names
            task_id: Training task ID
            logger: Logger instance
            session_maker: Factory to create short-lived DB sessions
            aggregator_name: Name of aggregator model
            fold_key: Optional fold identifier (e.g., "fold_0") for k-fold training
            progress_base: Starting progress percentage (default 90 for regular training)
            progress_range: Total progress range for saving (default 10 for regular training)
            case_level_ctx: Case-level context dict with case_to_wsi, original_labels, etc.
            test_sample_ids: Optional list of test set sample IDs for metrics calculation

        For each WSI, saves:
        - Prediction (pred): predicted class label
        - Probabilities (probs): probability distribution over classes
        - Attention weights: per-patch attention scores

        Results are saved to:
        - uploads/ai_results/{wsi_id}/train_{task_id}_result.json
        - uploads/ai_results/{wsi_id}/train_{task_id}_attention.npy (if attention available)
        """
        import concurrent.futures
        from functools import partial
        from torch.utils.data import DataLoader

        is_case_level = isinstance(dataset, CaseFeatureDataset)
        fold_suffix = f"_{fold_key}" if fold_key else ""
        fold_desc = f" ({fold_key})" if fold_key else ""

        # For case-level, count actual WSI slides for progress
        if is_case_level:
            case_to_wsi = case_level_ctx["case_to_wsi"] if case_level_ctx else dataset.case_to_wsi
            original_labels = case_level_ctx.get("original_labels", {}) if case_level_ctx else {}
            # Count total slides
            total_slides = sum(len(case_to_wsi.get(case_id, [])) for case_id in dataset.case_ids)
            total_wsi = total_slides
        else:
            total_wsi = len(dataset)

        # Calculate progress points based on progress_base and progress_range
        # Allocation: 20% inference, 60% file I/O, 10% DB, 10% metrics
        progress_inference = progress_base
        progress_file_io_start = progress_base + int(progress_range * 0.2)
        progress_file_io_end = progress_base + int(progress_range * 0.8)
        progress_db = progress_base + int(progress_range * 0.8)
        progress_metrics = progress_base + int(progress_range * 0.9)

        await _safe_update_progress(session_maker, self.task_id, TaskStatus.TRAINING, progress_inference)
        unit_name = "slides" if is_case_level else "WSI slides"
        await logger.info(
            f"[Saving] Starting to save inference results{fold_desc} for {total_wsi} {unit_name}...",
            metadata={"task_id": task_id, "num_wsi": total_wsi, "fold_key": fold_key, "phase": "saving_results", "is_case_level": is_case_level}
        )

        model.eval()
        ai_results_root = self.uploads_root / "ai_results"
        has_raw_attention = hasattr(model, 'forward_with_raw_attention')
        num_classes = len(classes)

        # Create DataLoader for inference (batch_size=1 since variable length)
        # num_workers=0 for single-process loading - avoids IPC overhead for batch_size=1
        # Features are loaded directly to GPU via Dataset, so no need for pin_memory
        inference_loader = DataLoader(
            dataset,
            batch_size=1,
            shuffle=False,
            num_workers=0,
        )

        # Phase 1: Run inference and collect results in thread pool.
        # DataLoader triggers torch.load() in __getitem__(), and GPU inference is blocking.
        def _run_inference():
            """Synchronous inference loop - runs in thread pool to avoid blocking event loop."""
            all_probs = []
            all_preds = []
            all_labels_list = []
            all_sample_ids = []
            inference_results = []
            db_records = []

            with torch.inference_mode():
                for batch in inference_loader:
                    # Unpack batch based on dataset type
                    if is_case_level:
                        # CaseFeatureDataset: (features, label, case_id, wsi_ids, patch_counts)
                        features, label, case_id, wsi_ids_tuple, patch_counts_tuple = batch
                        case_id = case_id[0]  # Remove batch dimension
                        # wsi_ids and patch_counts are tuples of tuples due to batching
                        slide_wsi_ids = [w[0] for w in wsi_ids_tuple] if wsi_ids_tuple else []
                        patch_counts = [int(p[0]) for p in patch_counts_tuple] if patch_counts_tuple else []
                        sample_id = case_id
                        sample_label = label.item()
                    else:
                        # WSIFeatureDataset: (features, label, wsi_id)
                        features, label, wsi_id = batch
                        wsi_id = wsi_id[0]  # Remove batch dimension
                        sample_id = wsi_id
                        sample_label = label.item()

                    # Features are already on GPU if Dataset was created with device parameter
                    H = features.squeeze(0)  # Already on GPU

                    if has_raw_attention:
                        logits, attention, raw_attention = model.forward_with_raw_attention(H)
                    else:
                        logits, attention = model(H)
                        raw_attention = None

                    probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
                    pred_idx = int(probs.argmax())
                    pred_label = classes[pred_idx]

                    all_probs.append(probs)
                    all_preds.append(pred_idx)
                    all_labels_list.append(sample_label)
                    all_sample_ids.append(sample_id)

                    probs_dict = {cls: float(probs[i]) for i, cls in enumerate(classes)}
                    gt_label = classes[sample_label]

                    attention_np = attention.cpu().numpy() if attention is not None else None
                    raw_attention_np = raw_attention.cpu().numpy() if raw_attention is not None else None

                    if is_case_level:
                        # Case-level: split attention back to per-slide and save per WSI
                        # Build case_wsi_patch_counts from current batch data
                        case_wsi_patch_counts = {case_id: patch_counts}

                        slide_attentions = self._split_case_attention_to_slides(
                            attention_np, case_id, case_wsi_patch_counts, case_to_wsi
                        )
                        slide_raw_attentions = self._split_case_attention_to_slides(
                            raw_attention_np, case_id, case_wsi_patch_counts, case_to_wsi
                        ) if raw_attention_np is not None else {wid: None for wid in slide_wsi_ids}

                        for wid in slide_wsi_ids:
                            wsi_result_dir = ai_results_root / wid
                            slide_attn = slide_attentions.get(wid)
                            slide_raw_attn = slide_raw_attentions.get(wid)

                            attention_shape = list(slide_attn.shape) if slide_attn is not None else None
                            attention_type = "none"
                            if slide_attn is not None:
                                attention_type = "multi_class" if slide_attn.ndim == 2 else "single"

                            # Use the slide's own ground truth label (should be same as case for case-level)
                            slide_gt_label = classes[original_labels.get(wid, sample_label)]

                            result_data = {
                                "wsi_id": wid,
                                "case_id": case_id,
                                "task_id": task_id,
                                "pred": pred_label,
                                "probs": probs_dict,
                                "ground_truth": slide_gt_label,
                                "correct": pred_label == slide_gt_label,
                                "classes": classes,
                                "aggregator": aggregator_name,
                                "attention_type": attention_type,
                                "attention_shape": attention_shape,
                                "aggregation_level": "case",
                            }
                            if fold_key:
                                result_data["fold_key"] = fold_key

                            inference_results.append((wid, result_data, slide_attn, slide_raw_attn, wsi_result_dir))

                            # Prepare database record
                            result_file = wsi_result_dir / f"train_{task_id}{fold_suffix}_result.json"
                            attention_file_path = str(wsi_result_dir / f"train_{task_id}{fold_suffix}_attention.npy") if slide_attn is not None else None
                            db_records.append({
                                "wsi_id": wid,
                                "task_id": task_id,
                                "pred": pred_label,
                                "probs": probs_dict,
                                "extra_metadata": {
                                    "case_id": case_id,
                                    "ground_truth": slide_gt_label,
                                    "correct": pred_label == slide_gt_label,
                                    "classes": classes,
                                    "aggregator": aggregator_name,
                                    "attention_type": attention_type,
                                    "attention_shape": attention_shape,
                                    "fold_key": fold_key,
                                    "result_file": str(result_file),
                                    "attention_file": attention_file_path,
                                    "aggregation_level": "case",
                                }
                            })
                    else:
                        # Slide-level: original behavior
                        wsi_id = sample_id
                        wsi_result_dir = ai_results_root / wsi_id

                        attention_shape = list(attention_np.shape) if attention_np is not None else None
                        attention_type = "none"
                        if attention_np is not None:
                            attention_type = "multi_class" if attention_np.ndim == 2 else "single"

                        result_data = {
                            "wsi_id": wsi_id,
                            "task_id": task_id,
                            "pred": pred_label,
                            "probs": probs_dict,
                            "ground_truth": gt_label,
                            "correct": pred_label == gt_label,
                            "classes": classes,
                            "aggregator": aggregator_name,
                            "attention_type": attention_type,
                            "attention_shape": attention_shape,
                        }
                        if fold_key:
                            result_data["fold_key"] = fold_key

                        inference_results.append((wsi_id, result_data, attention_np, raw_attention_np, wsi_result_dir))

                        # Prepare database record
                        result_file = wsi_result_dir / f"train_{task_id}{fold_suffix}_result.json"
                        attention_file_path = str(wsi_result_dir / f"train_{task_id}{fold_suffix}_attention.npy") if attention_np is not None else None
                        db_records.append({
                            "wsi_id": wsi_id,
                            "task_id": task_id,
                            "pred": pred_label,
                            "probs": probs_dict,
                            "extra_metadata": {
                                "ground_truth": gt_label,
                                "correct": pred_label == gt_label,
                                "classes": classes,
                                "aggregator": aggregator_name,
                                "attention_type": attention_type,
                                "attention_shape": attention_shape,
                                "fold_key": fold_key,
                                "result_file": str(result_file),
                                "attention_file": attention_file_path,
                            }
                        })

            return all_probs, all_preds, all_labels_list, all_sample_ids, inference_results, db_records

        all_probs, all_preds, all_labels_list, all_sample_ids, inference_results, db_records = await asyncio.to_thread(_run_inference)

        # Phase 2: Parallel file I/O with progress updates
        await _safe_update_progress(session_maker, self.task_id, TaskStatus.TRAINING, progress_file_io_start)
        await logger.info(
            f"[Saving] Writing {total_wsi} result files to disk...",
            metadata={"phase": "writing_files", "num_files": total_wsi}
        )

        # Track completed files for progress updates
        completed_count = [0]  # Use list for mutable reference in closure
        progress_lock = asyncio.Lock()
        # Calculate file I/O progress range (60% of total range)
        file_io_progress_range = progress_file_io_end - progress_file_io_start

        def save_single_wsi_files(item, fold_suffix: str, task_id: str):
            """Synchronous function to save files for a single WSI."""
            wsi_id, result_data, attention_np, raw_attention_np, wsi_result_dir = item
            wsi_result_dir.mkdir(parents=True, exist_ok=True)

            result_file = wsi_result_dir / f"train_{task_id}{fold_suffix}_result.json"
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, ensure_ascii=False)

            if attention_np is not None:
                attention_file = wsi_result_dir / f"train_{task_id}{fold_suffix}_attention.npy"
                np.save(attention_file, attention_np)

            if raw_attention_np is not None:
                raw_attention_file = wsi_result_dir / f"train_{task_id}{fold_suffix}_attention_raw.npy"
                np.save(raw_attention_file, raw_attention_np)

            return wsi_id

        async def save_with_progress(executor, item, fold_suffix, task_id, total, session_maker_ref, task_id_for_update,
                                      file_io_start, file_io_range):
            """Save files and update progress."""
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                executor,
                partial(save_single_wsi_files, fold_suffix=fold_suffix, task_id=task_id),
                item
            )
            async with progress_lock:
                completed_count[0] += 1
                # Update progress every 10% of files or at least every 500 files (reduced frequency for performance)
                update_interval = max(1, min(total // 10, 500))
                if completed_count[0] % update_interval == 0 or completed_count[0] == total:
                    # Progress based on file completion within the file I/O range
                    file_progress = file_io_start + int(completed_count[0] / total * file_io_range)
                    await _safe_update_progress(session_maker_ref, task_id_for_update, TaskStatus.TRAINING, file_progress)
            return result

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            tasks = [
                save_with_progress(executor, item, fold_suffix, task_id, total_wsi, session_maker, self.task_id,
                                   progress_file_io_start, file_io_progress_range)
                for item in inference_results
            ]
            await asyncio.gather(*tasks)

        # Phase 3: Batch database insert
        await _safe_update_progress(session_maker, self.task_id, TaskStatus.TRAINING, progress_db)
        await logger.info(
            f"[Saving] Inserting {len(db_records)} records to database...",
            metadata={"phase": "database_insert", "num_records": len(db_records)}
        )

        async with scoped_db(session_maker) as db:
            await AIResultRepository.bulk_create(db, db_records, batch_size=100)

        # Phase 4: Calculate and log final metrics
        await _safe_update_progress(session_maker, self.task_id, TaskStatus.TRAINING, progress_metrics)

        all_probs = np.array(all_probs)
        all_preds = np.array(all_preds)
        all_labels_arr = np.array(all_labels_list)

        # Filter to test set only if test_sample_ids is provided
        if test_sample_ids is not None and len(test_sample_ids) > 0:
            # Create mask for test samples
            test_mask = np.array([sid in test_sample_ids for sid in all_sample_ids])
            test_probs = all_probs[test_mask]
            test_preds = all_preds[test_mask]
            test_labels = all_labels_arr[test_mask]

            if len(test_labels) > 0:
                accuracy = round(float(accuracy_score(test_labels, test_preds)), 4)

                try:
                    if num_classes == 2:
                        auc = round(float(roc_auc_score(test_labels, test_probs[:, 1])), 4)
                        auc_display = f"AUC: {auc:.4f}"
                    else:
                        auc = round(float(roc_auc_score(test_labels, test_probs, multi_class='ovr', average='macro')), 4)
                        auc_display = f"AUC (macro-OVR): {auc:.4f}"
                except ValueError:
                    auc = None
                    auc_display = "AUC: N/A (insufficient samples per class)"

                metrics_metadata = {
                    "task_id": task_id,
                    "accuracy": accuracy,
                    "num_classes": num_classes,
                    "classes": classes,
                    "test_samples": len(test_labels),
                }
                if auc is not None:
                    metrics_metadata["auc"] = auc

                await logger.info(
                    f"[Saving] Complete - Test Set Accuracy: {accuracy:.4f}, {auc_display} (n={len(test_labels)})",
                    metadata=metrics_metadata
                )
            else:
                await logger.info(
                    f"[Saving] Complete - No test samples found for metrics calculation",
                    metadata={"task_id": task_id}
                )
        else:
            # No test set specified - log without metrics (for k-fold or when no test set)
            await logger.info(
                f"[Saving] Complete - Inference results saved for {len(all_sample_ids)} samples",
                metadata={"task_id": task_id, "num_samples": len(all_sample_ids)}
            )

        await db.commit()

        model.train()

