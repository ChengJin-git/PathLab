"""WSI Classification Trainer - integrates feature extraction and ABMIL training."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Any, Optional

import torch
import torch.nn as nn
import torch.optim as optim

from backend.ai.tasks.base import BaseTrainer
from backend.ai.extractors import get_extractor
from backend.ai.aggregators import get_aggregator
from backend.ai.utils.dataset import build_dataloader
from backend.ai.schemas import TaskType, TrainResponse, FeatureExtractionResponse
from backend.ai.tasks.feature_cache import (
    compute_params_hash,
    find_cached_features,
    get_cache_save_path,
    create_symlink_to_cache,
)
from backend.database.repositories import WSIRepository, TrainingTaskRepository


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
        db: Any,
        hf_token: str = "",
        preprocessing_config: Optional[Dict] = None,
    ) -> FeatureExtractionResponse:
        """
        Extract features for all WSI slides sequentially (single-GPU optimized).

        Uses global feature cache to avoid redundant extraction:
        - Cache location: uploads/features/{extractor_name}/{params_hash}/{wsi_id}.pt
        - Task directory: uploads/training/{task_id}/features/{wsi_id}.pt (symlink)

        The params_hash ensures features are only reused when preprocessing config matches.
        """
        # Build extractor once and reuse
        extractor = get_extractor(extractor_name, pretrained=True, hf_token=hf_token).to(self.device).eval()

        results = []
        total = len(wsi_ids)
        task_features_dir = self.uploads_root / "training" / self.task_id / "features"
        task_features_dir.mkdir(parents=True, exist_ok=True)

        # Compute params hash for cache lookup
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
        )

        for i, wsi_id in enumerate(wsi_ids, 1):
            task_feat_path = task_features_dir / f"{wsi_id}.pt"

            # Step 1: Check if task-specific features already exist (file or symlink)
            if task_feat_path.exists() and not force_recompute:
                feats = torch.load(task_feat_path, map_location="cpu")
                shape = tuple(feats.shape)
                await logger.info(
                    f"[{i}/{total}] Features already exist for {wsi_id}, skipping",
                    metadata={"wsi_id": wsi_id, "shape": list(shape), "path": str(task_feat_path)}
                )
                results.append({"wsi_id": wsi_id, "shape": shape, "path": str(task_feat_path)})
                progress = 33 + int(i / total * 33)
                await TrainingTaskRepository.update_status(db, self.task_id, "extracting", progress=progress)
                await db.commit()
                continue

            # Step 2: Check global feature cache
            cached_path = find_cached_features(
                self.uploads_root, extractor_name, params_hash, wsi_id
            )

            if cached_path and not force_recompute:
                # Cache hit: create symlink to cached features
                create_symlink_to_cache(task_features_dir, wsi_id, cached_path)
                feats = torch.load(cached_path, map_location="cpu")
                shape = tuple(feats.shape)
                await logger.info(
                    f"[{i}/{total}] Cache hit for {wsi_id}, created symlink",
                    metadata={"wsi_id": wsi_id, "shape": list(shape), "cached_path": str(cached_path)}
                )
                results.append({"wsi_id": wsi_id, "shape": shape, "path": str(task_feat_path)})
                progress = 33 + int(i / total * 33)
                await TrainingTaskRepository.update_status(db, self.task_id, "extracting", progress=progress)
                await db.commit()
                continue

            # Step 3: Extract features (cache miss)
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if not wsi:
                raise ValueError(f"WSI not found: {wsi_id}")

            wsi_path = wsi.wsi_path
            coords_h5 = self.uploads_root / "coordinates" / f"{wsi_id}_coords.h5"

            if not coords_h5.exists():
                raise FileNotFoundError(f"Coordinates not found for {wsi_id}: {coords_h5}")

            await logger.info(
                f"[{i}/{total}] Extracting features for {wsi_id} (cache miss)",
                metadata={"wsi_id": wsi_id, "wsi_index": i, "total_wsi": total}
            )
            await db.commit()

            feats = await self._extract_wsi_features(
                extractor=extractor,
                wsi_path=str(wsi_path),
                coords_h5=str(coords_h5),
                batch_size=batch_size,
            )

            # Save to global cache
            cache_feat_path = get_cache_save_path(
                self.uploads_root, extractor_name, params_hash, wsi_id
            )
            torch.save(feats.contiguous(), cache_feat_path)

            # Create symlink in task directory
            create_symlink_to_cache(task_features_dir, wsi_id, cache_feat_path)
            shape = tuple(feats.shape)

            await logger.info(
                f"[{i}/{total}] Features saved to cache for {wsi_id}",
                metadata={"wsi_id": wsi_id, "shape": list(shape), "cache_path": str(cache_feat_path)}
            )

            progress = 33 + int(i / total * 33)
            await TrainingTaskRepository.update_status(db, self.task_id, "extracting", progress=progress)
            await db.commit()

            results.append({"wsi_id": wsi_id, "shape": shape, "path": str(task_feat_path)})

        return self._build_feature_response(results)
    
    async def _extract_wsi_features(
        self,
        extractor: nn.Module,
        wsi_path: str,
        coords_h5: str,
        batch_size: int,
    ) -> torch.Tensor:
        """
        Extract features for a single WSI.

        Uses the extractor's preprocessing transforms to ensure correct
        normalization and image size for the model.

        NOTE: @torch.inference_mode() decorator does NOT work with async functions.
        We must use the context manager inside the function instead.
        """
        # Use extractor's transforms for correct preprocessing
        # Note: Disable pin_memory to avoid CUDA errors in multiprocess DataLoader
        # "RuntimeError: Caught RuntimeError in pin memory thread for device 0"
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

        feats_all = []
        # Use context manager for async function (decorator doesn't work with async)
        with torch.inference_mode():
            for imgs, _coords in loader:
                imgs = imgs.to(self.device, non_blocking=True)
                feats = extractor(imgs)
                feats_all.append(feats.cpu())  # Keep on CPU to save VRAM

        if len(feats_all) == 0:
            return torch.empty(0, extractor.output_dim)

        return torch.cat(feats_all, dim=0)  # (N, D)
    
    async def train_model(
        self,
        wsi_ids: List[str],
        aggregator_name: str,
        num_classes: int,
        epochs: int,
        lr: float,
        logger: Any,
        db: Any,
    ) -> TrainResponse:
        """Train ABMIL aggregator on extracted features."""
        # Load all features
        features_dir = self.uploads_root / "training" / self.task_id / "features"
        feats = self._load_features(features_dir, wsi_ids)
        
        # Get labels from database
        labels = {}
        classes = []
        for wsi_id in wsi_ids:
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if not wsi or not wsi.label:
                raise ValueError(f"WSI {wsi_id} has invalid/missing label")
            if wsi.label not in classes:
                classes.append(wsi.label)
        
        classes = sorted(classes)
        for wsi_id in wsi_ids:
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if not wsi or not wsi.label or wsi.label not in classes:
                raise ValueError(f"WSI {wsi_id} has invalid/missing label")
            labels[wsi_id] = classes.index(wsi.label)
        
        # Determine feature dimension
        any_tensor = next(iter(feats.values()))
        in_dim = int(any_tensor.shape[1])
        
        # Build aggregator
        model = get_aggregator(aggregator_name, in_dim=in_dim, num_classes=num_classes).to(self.device)
        criterion = nn.CrossEntropyLoss()
        optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=0.0)
        
        # Training loop
        history = {"loss": []}
        model.train()
        
        for epoch in range(1, epochs + 1):
            running_loss = 0.0
            for wsi_id in wsi_ids:
                H = feats[wsi_id].to(self.device)
                logits, attn = model(H)
                y = torch.tensor([labels[wsi_id]], dtype=torch.long, device=self.device)
                loss = criterion(logits, y)
                
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                
                running_loss += float(loss.item())
            
            epoch_loss = running_loss / max(1, len(wsi_ids))
            history["loss"].append(epoch_loss)
            
            # Log epoch progress
            await logger.info(
                f"Epoch {epoch}/{epochs} - loss: {epoch_loss:.4f}",
                metadata={"epoch": epoch, "loss": epoch_loss}
            )
            
            # Update progress: training from 66% to 100%
            progress = 66 + int(epoch / epochs * 34)
            await TrainingTaskRepository.update_status(db, self.task_id, "training", progress=progress)
            await db.commit()
        
        # Save checkpoint
        model_id = f"{aggregator_name}_{self.task_id}"
        model_dir = self.uploads_root / "models" / model_id
        model_dir.mkdir(parents=True, exist_ok=True)
        ckpt_path = model_dir / "aggregator.pth"
        
        torch.save({
            "state_dict": model.state_dict(),
            "in_dim": in_dim,
            "num_classes": num_classes,
        }, ckpt_path)
        
        # Save config
        (model_dir / "config.json").write_text(json.dumps({
            "task_id": self.task_id,
            "model": aggregator_name,
            "in_dim": in_dim,
            "num_classes": num_classes,
            "epochs": epochs,
            "lr": lr,
        }, ensure_ascii=False, indent=2))
        
        # Save metrics
        (model_dir / "metrics.json").write_text(json.dumps({
            "history": history
        }, ensure_ascii=False, indent=2))

        # 返回统一格式
        return self._build_train_response(
            model_id=model_id,
            checkpoint_path=str(ckpt_path),
            loss_history=history["loss"],
        )
    
    def _load_features(self, features_dir: Path, wsi_ids: List[str]) -> Dict[str, torch.Tensor]:
        """Load pre-extracted features for all WSI."""
        feats = {}
        for wsi_id in wsi_ids:
            feat_path = features_dir / f"{wsi_id}.pt"
            if not feat_path.exists():
                raise FileNotFoundError(f"Features not found for {wsi_id}: {feat_path}")
            feats[wsi_id] = torch.load(feat_path, map_location="cpu")
        return feats

