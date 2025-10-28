"""
WSI Tiling Module

Implements PrePATH-style tiling strategy:
1. Pre-compute patch coordinates with tissue detection
2. Save coordinates to disk for reuse
3. Extract patches on-demand from saved coordinates
"""
import os
import json
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class TissueDetector:
    """Detect tissue regions in WSI using Otsu thresholding"""
    
    def __init__(
        self,
        tissue_threshold: float = 0.5,
        min_tissue_ratio: float = 0.1
    ):
        """
        Args:
            tissue_threshold: Threshold for tissue detection (0-1)
            min_tissue_ratio: Minimum ratio of tissue pixels in a patch
        """
        self.tissue_threshold = tissue_threshold
        self.min_tissue_ratio = min_tissue_ratio
    
    def is_tissue(self, patch: Image.Image) -> bool:
        """
        Check if a patch contains enough tissue
        
        Args:
            patch: PIL Image patch
            
        Returns:
            True if patch contains tissue
        """
        # Convert to grayscale
        gray = patch.convert('L')
        gray_np = np.array(gray)
        
        # Simple Otsu-like thresholding
        # Tissue is typically darker than background
        threshold = np.mean(gray_np) * self.tissue_threshold
        tissue_mask = gray_np < threshold
        
        tissue_ratio = np.sum(tissue_mask) / tissue_mask.size
        return tissue_ratio >= self.min_tissue_ratio


class WSITiler:
    """
    WSI Tiling with PrePATH-style coordinate pre-computation
    """
    
    def __init__(
        self,
        patch_size: int = 256,
        stride: int = 256,
        level: int = 0,
        tissue_detector: Optional[TissueDetector] = None
    ):
        """
        Args:
            patch_size: Size of patches to extract
            stride: Stride between patches
            level: Pyramid level to extract from
            tissue_detector: Tissue detection instance
        """
        self.patch_size = patch_size
        self.stride = stride
        self.level = level
        self.tissue_detector = tissue_detector or TissueDetector()
    
    def compute_coordinates(
        self,
        slide,
        save_path: Optional[Path] = None
    ) -> List[Tuple[int, int]]:
        """
        Compute patch coordinates with tissue detection
        
        Args:
            slide: ASlide Slide object
            save_path: Optional path to save coordinates
            
        Returns:
            List of (x, y) coordinates
        """
        logger.info(f"Computing patch coordinates for slide")
        
        # Get slide dimensions at target level
        level_dims = slide.level_dimensions[self.level]
        width, height = level_dims
        
        logger.info(f"Slide dimensions at level {self.level}: {width}x{height}")
        
        coordinates = []
        
        # Grid sampling
        for y in range(0, height - self.patch_size + 1, self.stride):
            for x in range(0, width - self.patch_size + 1, self.stride):
                # Extract patch for tissue detection
                try:
                    patch = slide.read_region(
                        (x, y),
                        self.level,
                        (self.patch_size, self.patch_size)
                    )
                    
                    # Check if patch contains tissue
                    if self.tissue_detector.is_tissue(patch):
                        coordinates.append((x, y))
                
                except Exception as e:
                    logger.warning(f"Failed to read patch at ({x}, {y}): {e}")
                    continue
        
        logger.info(f"Found {len(coordinates)} tissue patches")
        
        # Save coordinates if path provided
        if save_path:
            self._save_coordinates(coordinates, save_path)
        
        return coordinates
    
    def _save_coordinates(
        self,
        coordinates: List[Tuple[int, int]],
        save_path: Path
    ):
        """Save coordinates to JSON file"""
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "patch_size": self.patch_size,
            "stride": self.stride,
            "level": self.level,
            "num_patches": len(coordinates),
            "coordinates": coordinates
        }
        
        with open(save_path, 'w') as f:
            json.dump(data, f)
        
        logger.info(f"Saved {len(coordinates)} coordinates to {save_path}")
    
    @staticmethod
    def load_coordinates(load_path: Path) -> Dict:
        """Load coordinates from JSON file"""
        with open(load_path, 'r') as f:
            data = json.load(f)
        
        logger.info(f"Loaded {data['num_patches']} coordinates from {load_path}")
        return data
    
    def extract_patches(
        self,
        slide,
        coordinates: List[Tuple[int, int]]
    ) -> List[Image.Image]:
        """
        Extract patches from slide using pre-computed coordinates
        
        Args:
            slide: ASlide Slide object
            coordinates: List of (x, y) coordinates
            
        Returns:
            List of PIL Image patches
        """
        patches = []
        
        for x, y in coordinates:
            try:
                patch = slide.read_region(
                    (x, y),
                    self.level,
                    (self.patch_size, self.patch_size)
                )
                patches.append(patch)
            except Exception as e:
                logger.warning(f"Failed to extract patch at ({x}, {y}): {e}")
                continue
        
        logger.info(f"Extracted {len(patches)} patches")
        return patches


def get_or_compute_coordinates(
    wsi_id: str,
    slide,
    coords_dir: Path,
    patch_size: int = 256,
    stride: int = 256,
    level: int = 0,
    force_recompute: bool = False
) -> List[Tuple[int, int]]:
    """
    Get patch coordinates from cache or compute if not exists
    
    Args:
        wsi_id: WSI identifier
        slide: ASlide Slide object
        coords_dir: Directory to store coordinates
        patch_size: Patch size
        stride: Stride
        level: Pyramid level
        force_recompute: Force recomputation even if cache exists
        
    Returns:
        List of (x, y) coordinates
    """
    coords_file = coords_dir / f"{wsi_id}_coords.json"
    
    # Load from cache if exists
    if coords_file.exists() and not force_recompute:
        logger.info(f"Loading coordinates from cache: {coords_file}")
        data = WSITiler.load_coordinates(coords_file)
        
        # Verify parameters match
        if (data['patch_size'] == patch_size and
            data['stride'] == stride and
            data['level'] == level):
            return data['coordinates']
        else:
            logger.warning("Cached coordinates have different parameters, recomputing")
    
    # Compute new coordinates
    logger.info(f"Computing new coordinates for {wsi_id}")
    tiler = WSITiler(
        patch_size=patch_size,
        stride=stride,
        level=level
    )
    
    coordinates = tiler.compute_coordinates(slide, save_path=coords_file)
    return coordinates

