"""
Feature Service

Handles feature extraction for training.
Extracts features from WSI patches using built-in feature extractors.
"""

import os
import json
import torch
import numpy as np
from typing import Dict, List, Optional
from pathlib import Path
from torch.utils.data import Dataset

# Get uploads directory (same as preprocessing service)
# feature_service.py -> services -> ai -> backend -> services -> smartresearch (ROOT)
ROOT = Path(__file__).resolve().parents[4]  # Go up 4 levels to smartresearch/
UPLOADS_DIR = str(ROOT / "uploads")

print(f"[FeatureService] ROOT: {ROOT}")
print(f"[FeatureService] UPLOADS_DIR: {UPLOADS_DIR}")


class WSIPatchDataset(Dataset):
    """Dataset for reading patches from WSI on-the-fly"""

    def __init__(self, slide, coordinates, patch_size, patch_level, transform):
        self.slide = slide
        self.coordinates = coordinates
        self.patch_size = patch_size
        self.patch_level = patch_level
        self.transform = transform

    def __len__(self):
        return len(self.coordinates)

    def __getitem__(self, idx):
        coord = self.coordinates[idx]
        x, y = int(coord[0]), int(coord[1])

        # Read patch
        patch = self.slide.read_region((x, y), self.patch_level, (self.patch_size, self.patch_size))

        # Convert RGBA to RGB if needed
        if patch.mode == 'RGBA':
            patch = patch.convert('RGB')

        # Apply transform
        return self.transform(patch)


class FeatureService:
    """Service for feature extraction"""

    @staticmethod
    async def extract_features_for_training(
        task_id: str,
        wsi_ids: List[str],
        feature_extractor: str = "resnet50",
        batch_size: int = 64,
        device: str = "cuda"
    ) -> Dict[str, str]:
        """
        Extract features for all WSIs in a training task

        Args:
            task_id: Training task ID
            wsi_ids: List of WSI IDs to extract features from
            feature_extractor: Name of built-in feature extractor
            batch_size: Batch size for feature extraction
            device: Device to use (cuda/cpu)

        Returns:
            Dictionary mapping wsi_id to feature file path
            {
                "wsi_001": "training/task_123/features/wsi_001_features.pt",
                "wsi_002": "training/task_123/features/wsi_002_features.pt",
                ...
            }
        """
        # Create feature directory
        feature_dir = os.path.join(UPLOADS_DIR, "training", task_id, "features")
        os.makedirs(feature_dir, exist_ok=True)
        
        feature_paths = {}
        
        for wsi_id in wsi_ids:
            try:
                print(f"[FeatureService] Processing WSI: {wsi_id}")

                # Extract features for this WSI
                features = await FeatureService._extract_features_for_wsi(
                    wsi_id=wsi_id,
                    feature_extractor=feature_extractor,
                    batch_size=batch_size,
                    device=device
                )

                # Save features
                feature_filename = f"{wsi_id}_features.pt"
                feature_path = os.path.join(feature_dir, feature_filename)
                torch.save(features, feature_path)

                print(f"[FeatureService] ✓ Saved features to: {feature_path}")

                # Store relative path
                relative_path = f"training/{task_id}/features/{feature_filename}"
                feature_paths[wsi_id] = relative_path

            except Exception as e:
                import traceback
                print(f"[FeatureService] ✗ Failed to extract features for {wsi_id}: {e}")
                print(traceback.format_exc())
                raise
        
        return feature_paths

    @staticmethod
    async def _extract_features_for_wsi(
        wsi_id: str,
        feature_extractor: str,
        batch_size: int,
        device: str
    ) -> torch.Tensor:
        """
        Extract features for a single WSI

        Args:
            wsi_id: WSI ID
            feature_extractor: Name of built-in feature extractor
            batch_size: Batch size
            device: Device to use

        Returns:
            Feature tensor [N, D]
        """
        import h5py
        from tqdm import tqdm
        from torchvision import transforms

        print(f"[FeatureService] UPLOADS_DIR: {UPLOADS_DIR}")
        print(f"[FeatureService] Extracting features for WSI: {wsi_id}")

        # 1. Load coordinates from H5 file
        coords_path = os.path.join(UPLOADS_DIR, "coordinates", f"{wsi_id}_coords.h5")
        coordinates, patch_size, patch_level = FeatureService._load_coordinates_from_h5(coords_path)

        print(f"[FeatureService] Loaded {len(coordinates)} patches for {wsi_id}")

        # 2. Load WSI slide
        wsi_path = await FeatureService._get_wsi_path(wsi_id)
        print(f"[FeatureService] WSI path from database: {wsi_path}")
        print(f"[FeatureService] File exists: {wsi_path.exists()}")
        print(f"[FeatureService] File size: {wsi_path.stat().st_size / (1024**3):.2f} GB")

        from Aslide.aslide import Slide
        try:
            slide = Slide(str(wsi_path))

            if slide is None:
                raise ValueError(f"Aslide returned None - unsupported format or corrupted file: {wsi_path}")

            print(f"[FeatureService] ✓ Loaded WSI: {wsi_path}")
            print(f"[FeatureService] Slide dimensions: {slide.level_dimensions[0]}")
            print(f"[FeatureService] Slide levels: {len(slide.level_dimensions)}")
        except Exception as e:
            print(f"[FeatureService] ✗ Failed to load WSI: {e}")
            import traceback
            print(traceback.format_exc())
            raise

        # 3. Load feature extractor
        from smartresearch.services.backend.ai.models.lib import create_extractor
        extractor = create_extractor(feature_extractor, pretrained=True, device=device)
        extractor.eval()

        print(f"[FeatureService] Loaded feature extractor: {feature_extractor}")

        # 4. Prepare image transforms
        transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])

        # 5. Extract features in batches with DataLoader for efficient parallel loading
        from torch.utils.data import DataLoader

        # Create dataset and dataloader (using module-level WSIPatchDataset class)
        dataset = WSIPatchDataset(slide, coordinates, patch_size, patch_level, transform)
        dataloader = DataLoader(
            dataset,
            batch_size=batch_size,
            shuffle=False,
            num_workers=0,  # Use 0 to avoid pickling issues with Aslide Slide object
            pin_memory=True if device == 'cuda' else False
        )

        print(f"[FeatureService] Processing {len(dataloader)} batches with batch_size={batch_size}")

        all_features = []
        for batch_tensors in tqdm(dataloader, desc=f"Extracting features for {wsi_id}"):
            batch_tensors = batch_tensors.to(device)

            # Extract features
            with torch.no_grad():
                batch_features = extractor.extract_batch(batch_tensors)

            all_features.append(batch_features.cpu())

        # Concatenate all features
        features = torch.cat(all_features, dim=0)

        # Close slide
        try:
            slide.close()
        except:
            pass

        print(f"[FeatureService] Extracted features: {features.shape}")

        return features

    @staticmethod
    def _load_coordinates_from_h5(coords_path: str):
        """Load patch coordinates from H5 file"""
        import h5py

        print(f"[FeatureService] Loading coordinates from: {coords_path}")

        if not os.path.exists(coords_path):
            raise FileNotFoundError(f"Coordinates file not found: {coords_path}")

        with h5py.File(coords_path, 'r') as f:
            coordinates = f['coords'][:]
            patch_size = f['coords'].attrs.get('patch_size', 256)
            patch_level = f['coords'].attrs.get('patch_level', 0)

        print(f"[FeatureService] Loaded {len(coordinates)} coordinates (patch_size={patch_size}, level={patch_level})")
        return coordinates, patch_size, patch_level

    @staticmethod
    async def _get_wsi_path(wsi_id: str) -> Path:
        """Get WSI file path from database"""
        import sys
        sys.path.insert(0, str(ROOT))

        print(f"[FeatureService] Getting WSI path for: {wsi_id}")

        from smartresearch.services.backend.database import get_db
        from smartresearch.services.backend.database.repositories import WSIRepository

        # Use async database access
        wsi_path = None
        async for db in get_db():
            try:
                print(f"[FeatureService] Querying database for WSI: {wsi_id}")
                wsi = await WSIRepository.get_by_id(db, wsi_id)

                if not wsi:
                    print(f"[FeatureService] ✗ WSI not found in database: {wsi_id}")
                    raise FileNotFoundError(f"WSI not found in database: {wsi_id}")

                print(f"[FeatureService] ✓ Found WSI in database: {wsi.wsi_path}")
                wsi_path = Path(wsi.wsi_path)

                if not wsi_path.exists():
                    print(f"[FeatureService] ✗ WSI file does not exist: {wsi_path}")
                    raise FileNotFoundError(f"WSI file not found: {wsi_path}")

                print(f"[FeatureService] ✓ WSI file exists: {wsi_path}")
                break  # Exit the async for loop

            except Exception as e:
                print(f"[FeatureService] ✗ Error getting WSI path: {e}")
                raise
            finally:
                await db.close()

        if wsi_path is None:
            raise FileNotFoundError(f"Failed to get WSI path for: {wsi_id}")

        return wsi_path

    @staticmethod
    def _read_patches_from_slide(slide, coordinates, patch_size, patch_level):
        """Read patches from WSI slide (sequential)"""
        patches = []
        for coord in coordinates:
            x, y = int(coord[0]), int(coord[1])

            # Read region from slide
            patch = slide.read_region((x, y), patch_level, (patch_size, patch_size))

            # Convert RGBA to RGB if needed
            if patch.mode == 'RGBA':
                patch = patch.convert('RGB')

            patches.append(patch)

        return patches

    @staticmethod
    def _read_patches_from_slide_parallel(slide, coordinates, patch_size, patch_level, num_workers=4):
        """Read patches from WSI slide with parallel reading using ThreadPoolExecutor"""
        from concurrent.futures import ThreadPoolExecutor

        def read_single_patch(coord):
            x, y = int(coord[0]), int(coord[1])
            patch = slide.read_region((x, y), patch_level, (patch_size, patch_size))

            # Convert RGBA to RGB if needed
            if patch.mode == 'RGBA':
                patch = patch.convert('RGB')

            return patch

        # Use ThreadPoolExecutor for parallel I/O
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            patches = list(executor.map(read_single_patch, coordinates))

        return patches

    @staticmethod
    async def load_features(feature_path: str) -> torch.Tensor:
        """
        Load features from file

        Args:
            feature_path: Path to feature file (relative to uploads/)

        Returns:
            Feature tensor
        """
        full_path = os.path.join(UPLOADS_DIR, feature_path)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"Feature file not found: {full_path}")

        features = torch.load(full_path)
        return features

    @staticmethod
    def get_feature_dim(feature_extractor: str) -> int:
        """Get feature dimension for a given extractor"""
        feature_dims = {
            "resnet50": 2048,
            "vit_large": 1024,
            "ctranspath": 768,
            "uni": 1024,
        }
        return feature_dims.get(feature_extractor, 2048)

