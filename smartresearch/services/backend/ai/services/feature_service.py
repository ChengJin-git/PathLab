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

# Get uploads directory (same as AI service main.py)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
UPLOADS_DIR = os.path.join(ROOT, "uploads")


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
                
                # Store relative path
                relative_path = f"training/{task_id}/features/{feature_filename}"
                feature_paths[wsi_id] = relative_path
                
            except Exception as e:
                print(f"Failed to extract features for {wsi_id}: {e}")
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
        
        This is a placeholder implementation.
        The actual implementation should:
        1. Load patches from coordinates file
        2. Load built-in feature extractor
        3. Extract features in batches
        4. Return feature tensor [N, D] where N=num_patches, D=feature_dim
        
        Args:
            wsi_id: WSI ID
            feature_extractor: Name of built-in feature extractor
            batch_size: Batch size
            device: Device to use
        
        Returns:
            Feature tensor [N, D]
        """
        # TODO: Implement actual feature extraction
        # For now, return dummy features

        # Load coordinates to get number of patches
        coords_path = os.path.join(UPLOADS_DIR, "coordinates", f"{wsi_id}_coords.h5")
        if os.path.exists(coords_path):
            # TODO: Load from H5 file
            # For now, use default
            num_patches = 100
        else:
            # Default to 100 patches if coordinates not found
            num_patches = 100
        
        # Get feature dimension based on extractor
        feature_dims = {
            "resnet50": 2048,
            "vit_large": 1024,
            "ctranspath": 768,
            "uni": 1024,
        }
        feature_dim = feature_dims.get(feature_extractor, 2048)
        
        # Return dummy features for now
        # TODO: Replace with actual feature extraction
        print(f"[FeatureService] Extracting features for {wsi_id} using {feature_extractor}")
        print(f"[FeatureService] TODO: Implement actual feature extraction")
        print(f"[FeatureService] Returning dummy features: [{num_patches}, {feature_dim}]")
        
        features = torch.randn(num_patches, feature_dim)
        return features

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

