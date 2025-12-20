"""
WSI Patch Dataset for feature extraction (single-GPU optimized)

- Reads patch coordinates from uploads/coordinates/{wsi_id}_coords.h5
- Loads WSI via Aslide and reads patches at given level
- Applies extractor-specific or default torchvision transforms
- Supports both train and eval modes for data augmentation

Usage:
    # Method 1: Use extractor's built-in transforms (recommended)
    from smartresearch.services.backend.ai.extractors import get_extractor
    extractor = get_extractor("resnet50", pretrained=True)
    dataset = WSIPatchDataset(wsi_path, coords_h5, extractor=extractor, mode="eval")

    # Method 2: Use default transforms
    dataset = WSIPatchDataset(wsi_path, coords_h5)  # uses default ImageNet transforms

    # Method 3: Use custom transforms
    dataset = WSIPatchDataset(wsi_path, coords_h5, transform=my_transform)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple, List, Optional, Callable, TYPE_CHECKING

import h5py
import numpy as np
from PIL import Image

import torch
from torch.utils.data import Dataset, DataLoader

if TYPE_CHECKING:
    from smartresearch.services.backend.ai.extractors.base import BaseExtractor

# Import default transforms from extractors module
from smartresearch.services.backend.ai.extractors.transforms import get_default_transforms


def get_torchvision_transforms(image_size: int = 224, mode: str = "eval") -> Callable:
    """
    Get default torchvision transforms.

    This is a convenience function that wraps get_default_transforms.
    For extractor-specific preprocessing, use extractor.get_transforms() instead.

    Args:
        image_size: Target image size
        mode: "train" for augmentation, "eval" for inference

    Returns:
        Composed transform callable
    """
    return get_default_transforms(image_size=image_size, mode=mode)


def _load_slide(wsi_path: str):
    from Aslide.aslide import Slide
    return Slide(str(wsi_path))


class WSIPatchDataset(Dataset):
    """
    Dataset backed by HDF5 coordinates and ASlide slide reading.

    Returns image tensor and (x, y) coordinate per item.

    Supports three ways to specify transforms (in order of priority):
    1. Explicit `transform` parameter - use custom transforms
    2. `extractor` parameter - use extractor's get_transforms() method
    3. Default - use ImageNet transforms with image_size=224

    Args:
        wsi_path: Path to the WSI file
        coords_h5: Path to HDF5 file containing patch coordinates
        transform: Custom transform callable (highest priority)
        extractor: Feature extractor instance to get transforms from
        mode: "train" or "eval" - controls data augmentation
        fast_read: Use fast read mode for ASlide
    """
    def __init__(
        self,
        wsi_path: str,
        coords_h5: str,
        transform: Optional[Callable] = None,
        extractor: Optional["BaseExtractor"] = None,
        mode: str = "eval",
        fast_read: bool = True,
    ) -> None:
        self.wsi_path = wsi_path
        self.coords_h5 = coords_h5
        self.mode = mode
        self.fast_read = fast_read

        # Determine transform: explicit > extractor > default
        if transform is not None:
            self.transform = transform
        elif extractor is not None:
            self.transform = extractor.get_transforms(mode=mode)
        else:
            self.transform = get_torchvision_transforms(image_size=224, mode=mode)

        # Load slide lazily to allow multiprocessing DataLoader workers to open independently
        self._slide = None

        # Load coordinates and metadata
        with h5py.File(self.coords_h5, "r") as f:
            self._coords = f["coords"][:].astype(np.int32)  # copy to memory, avoids file locks
            attrs = dict(f["coords"].attrs)
            self.patch_size = int(attrs.get("patch_size", 256))
            self.level = int(attrs.get("patch_level", 0))

    def __len__(self) -> int:
        return len(self._coords)

    def _ensure_slide(self):
        if self._slide is None:
            self._slide = _load_slide(self.wsi_path)
        return self._slide

    def __getitem__(self, idx: int):
        x, y = self._coords[idx]
        slide = self._ensure_slide()
        patch = slide.read_region((int(x), int(y)), self.level, (self.patch_size, self.patch_size))
        if patch.mode == "RGBA":
            patch = patch.convert("RGB")
        img = self.transform(patch)
        return img, torch.tensor([int(x), int(y)], dtype=torch.int32)


def build_dataloader(
    wsi_path: str,
    coords_h5: str,
    batch_size: int = 256,
    num_workers: int = 8,
    prefetch_factor: int = 16,
    pin_memory: bool = True,
    extractor: Optional["BaseExtractor"] = None,
    mode: str = "eval",
    transform: Optional[Callable] = None,
):
    """
    Build a DataLoader for WSI patch extraction.

    Args:
        wsi_path: Path to the WSI file
        coords_h5: Path to HDF5 file containing patch coordinates
        batch_size: Batch size for DataLoader
        num_workers: Number of worker processes
        prefetch_factor: Number of batches to prefetch per worker
        pin_memory: Pin memory for faster GPU transfer
        extractor: Feature extractor instance to get transforms from
        mode: "train" or "eval" - controls data augmentation
        transform: Custom transform callable (overrides extractor)

    Returns:
        Tuple of (DataLoader, WSIPatchDataset)
    """
    dataset = WSIPatchDataset(
        wsi_path=wsi_path,
        coords_h5=coords_h5,
        transform=transform,
        extractor=extractor,
        mode=mode,
    )
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        prefetch_factor=prefetch_factor if num_workers > 0 else None,
        pin_memory=pin_memory,
        drop_last=False,
    )
    return loader, dataset

