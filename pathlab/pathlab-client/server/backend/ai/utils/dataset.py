"""
WSI Patch Dataset for feature extraction (single-GPU optimized)

- Reads patch coordinates from uploads/coordinates/{wsi_id}_coords.h5
- Loads WSI via Aslide and reads patches at given level
- Applies extractor-specific or default torchvision transforms
- Supports both train and eval modes for data augmentation
- Gracefully handles corrupted patches by skipping them with warnings

Usage:
    # Method 1: Use extractor's built-in transforms (recommended)
    from backend.ai.extractors import get_extractor
    extractor = get_extractor("resnet50", pretrained=True)
    dataset = WSIPatchDataset(wsi_path, coords_h5, extractor=extractor, mode="eval")

    # Method 2: Use default transforms
    dataset = WSIPatchDataset(wsi_path, coords_h5)  # uses default ImageNet transforms

    # Method 3: Use custom transforms
    dataset = WSIPatchDataset(wsi_path, coords_h5, transform=my_transform)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Callable, TYPE_CHECKING, Any

import numpy as np
from PIL import Image

import torch
from torch.utils.data import Dataset, DataLoader

if TYPE_CHECKING:
    from backend.ai.extractors.base import BaseExtractor

# Import default transforms from extractors module
from backend.ai.extractors.transforms import get_default_transforms
from backend.preprocessing.tiling import safe_load_h5_coords

logger = logging.getLogger(__name__)


def get_torchvision_transforms(image_size: int = 224, mode: str = "eval") -> Callable[..., Any]:
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
    """Load WSI file using Aslide (delegates to shared slide_utils)"""
    from backend.common.slide_utils import load_slide
    return load_slide(wsi_path)


class WSIPatchDataset(Dataset[Any]):
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
        transform: Optional[Callable[..., Any]] = None,
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

        # Load coordinates and metadata using safe loading
        coords_array, attrs, load_error = safe_load_h5_coords(
            Path(self.coords_h5), delete_if_corrupted=False
        )
        if coords_array is None:
            raise RuntimeError(
                f"Failed to load coordinates from {self.coords_h5}: {load_error}. "
                "The file may be corrupted. Please rerun preprocessing."
            )

        self._coords = coords_array.astype(np.int32)
        self.patch_size = int(attrs.get("patch_size", 256))
        self.level = int(attrs.get("patch_level", 0))

        # MPP-aware reading: read at read_size and resize to patch_size
        # For old cache files without read_size, fall back to patch_size (no resize)
        self.read_size = int(attrs.get("read_size", self.patch_size))
        self._needs_resize = self.read_size != self.patch_size

    def __len__(self) -> int:
        return len(self._coords)

    def _ensure_slide(self):
        if self._slide is None:
            import os
            pid = os.getpid()
            logger.info(f"[WSIPatchDataset] Opening slide in pid={pid}: {self.wsi_path}")
            self._slide = _load_slide(self.wsi_path)
            logger.info(f"[WSIPatchDataset] Slide opened OK in pid={pid}: {self.wsi_path}")
        return self._slide

    def __getitem__(self, idx: int):
        x, y = self._coords[idx]
        slide = self._ensure_slide()

        try:
            # Read at read_size (MPP-adjusted) and resize to patch_size if needed
            patch = slide.read_region((int(x), int(y)), self.level, (self.read_size, self.read_size))
            if patch.mode == "RGBA":
                patch = patch.convert("RGB")

            # Resize to output patch_size for MPP normalization
            if self._needs_resize:
                patch = patch.resize((self.patch_size, self.patch_size), Image.Resampling.LANCZOS)

            img = self.transform(patch)
            return img, torch.tensor([int(x), int(y)], dtype=torch.int32)
        except Exception as e:
            # Return None to indicate this patch failed to load
            # The collate function will filter these out
            logger.warning(
                f"Failed to read patch at coordinates ({int(x)}, {int(y)}) from {self.wsi_path}: {type(e).__name__}: {str(e)}"
            )
            return None


def _collate_skip_failed_patches(batch):
    """
    Custom collate function that skips failed patches (None values).

    When a patch fails to load, __getitem__ returns None. This collate function
    filters out those None values and returns only valid patches.

    Args:
        batch: List of items from dataset (may contain None for failed patches)

    Returns:
        Tuple of (images, coordinates) tensors, with failed patches removed
    """
    # Filter out None values (failed patches)
    valid_items = [item for item in batch if item is not None]

    if len(valid_items) == 0:
        # All patches in this batch failed - return empty tensors
        return torch.empty(0, 3, 224, 224), torch.empty(0, 2, dtype=torch.int32)

    # Unzip valid items
    imgs, coords = zip(*valid_items)

    # Stack into tensors
    imgs_tensor = torch.stack(imgs)
    coords_tensor = torch.stack(coords)

    return imgs_tensor, coords_tensor


def build_dataloader(
    wsi_path: str,
    coords_h5: str,
    batch_size: int = 128,
    num_workers: int = 4,
    prefetch_factor: int = 2,
    pin_memory: bool = False,  # Disabled by default to avoid CUDA pin memory errors
    extractor: Optional["BaseExtractor"] = None,
    mode: str = "eval",
    transform: Optional[Callable[..., Any]] = None,
):
    """
    Build a DataLoader for WSI patch extraction.

    Args:
        wsi_path: Path to the WSI file
        coords_h5: Path to HDF5 file containing patch coordinates
        batch_size: Batch size for DataLoader
        num_workers: Number of worker processes (auto-set to 0 if in daemon process)
        prefetch_factor: Number of batches to prefetch per worker
        pin_memory: Pin memory for faster GPU transfer
        extractor: Feature extractor instance to get transforms from
        mode: "train" or "eval" - controls data augmentation
        transform: Custom transform callable (overrides extractor)

    Returns:
        Tuple of (DataLoader, WSIPatchDataset)
    """
    import multiprocessing

    # Daemon processes cannot have child processes (multiprocessing restriction)
    # When running as a daemon subprocess (e.g., AI service via main.py),
    # we must use num_workers=0 to avoid the error:
    # "AssertionError: daemonic processes are not allowed to have children"
    current_process = multiprocessing.current_process()
    if current_process.daemon:
        num_workers = 0
        pin_memory = False  # pin_memory also requires spawning threads

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
        collate_fn=_collate_skip_failed_patches,  # Use custom collate to skip failed patches
        multiprocessing_context='spawn' if num_workers > 0 else None,  # Avoid fork deadlock in multithreaded env
    )
    return loader, dataset
