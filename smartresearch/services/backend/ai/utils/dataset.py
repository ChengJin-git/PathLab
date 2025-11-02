"""
WSI Patch Dataset for feature extraction (single-GPU optimized)

- Reads patch coordinates from uploads/coordinates/{wsi_id}_coords.h5
- Loads WSI via Aslide and reads patches at given level
- Applies torchvision transforms and returns tensor batches
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple, List, Optional

import h5py
import numpy as np
from PIL import Image

import torch
from torch.utils.data import Dataset, DataLoader

# Lazy import torchvision to avoid import overhead if not needed
_transforms = None

def get_torchvision_transforms(image_size: int = 224):
    global _transforms
    if _transforms is None:
        import torchvision.transforms as T
        _transforms = T
    return _transforms.Compose([
        _transforms.Resize((image_size, image_size)),
        _transforms.ToTensor(),
        _transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])


def _load_slide(wsi_path: str):
    from Aslide.aslide import Slide
    return Slide(str(wsi_path))


class WSIPatchDataset(Dataset):
    """
    Dataset backed by HDF5 coordinates and ASlide slide reading.

    Returns image tensor and (x, y) coordinate per item.
    """
    def __init__(
        self,
        wsi_path: str,
        coords_h5: str,
        transform=None,
        fast_read: bool = True,
    ) -> None:
        self.wsi_path = wsi_path
        self.coords_h5 = coords_h5
        self.transform = transform or get_torchvision_transforms(224)
        self.fast_read = fast_read

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
):
    dataset = WSIPatchDataset(wsi_path=wsi_path, coords_h5=coords_h5)
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

