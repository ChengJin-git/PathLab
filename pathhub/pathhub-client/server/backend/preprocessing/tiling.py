"""
WSI Tiling Module

Implements CLAM-style tiling strategy:
1. Tissue segmentation using HSV color space and morphological operations
2. Contour detection and filtering
3. Pre-compute patch coordinates within tissue contours
4. Save coordinates to disk for reuse
5. Extract patches on-demand from saved coordinates

Reference: CLAM (mahmoodlab/CLAM)
"""
import json
import numpy as np
import cv2
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class TissueSegmenter:
    """
    Tissue segmentation using CLAM-style approach

    Uses HSV color space + Otsu/Binary thresholding + morphological operations
    to detect tissue regions and filter out background/artifacts
    """

    def __init__(
        self,
        seg_level: int = -1,
        sthresh: int = 5,
        mthresh: int = 7,
        close: int = 4,
        use_otsu: bool = False,
        filter_params: Optional[Dict] = None
    ):
        """
        Args:
            seg_level: Pyramid level for segmentation (-1 = auto select ~64x downsample)
            sthresh: Binary threshold value (default: 5, low threshold for maximum tissue detection)
            mthresh: Median filter kernel size (default: 7)
            close: Morphological closing kernel size (default: 4)
            use_otsu: Use Otsu's method instead of binary threshold
            filter_params: Contour filtering parameters
                - a_t: Minimum tissue area (relative to 512x512 patch)
                - a_h: Minimum hole area
                - max_n_holes: Maximum number of holes per contour
        """
        self.seg_level = seg_level
        self.sthresh = sthresh
        self.mthresh = mthresh
        self.close = close
        self.use_otsu = use_otsu

        # Default filter parameters (CLAM defaults)
        self.filter_params = filter_params or {
            'a_t': 100,      # Min tissue area (in 512x512 patches)
            'a_h': 16,       # Min hole area
            'max_n_holes': 8 # Max holes per contour
        }

    def segment_tissue(self, slide) -> Tuple[List, List]:
        """
        Segment tissue regions from WSI

        Args:
            slide: ASlide Slide object

        Returns:
            Tuple of (tissue_contours, hole_contours)
        """
        # Auto-select segmentation level if needed
        seg_level = self._get_seg_level(slide)
        logger.info(f"Segmenting at level {seg_level}")

        # Read slide at segmentation level
        level_dims = slide.level_dimensions[seg_level]
        img = slide.read_region((0, 0), seg_level, level_dims)
        img_np = np.array(img.convert('RGB'))

        # Convert to HSV and extract saturation channel
        img_hsv = cv2.cvtColor(img_np, cv2.COLOR_RGB2HSV)
        img_med = cv2.medianBlur(img_hsv[:, :, 1], self.mthresh)

        # Thresholding
        if self.use_otsu:
            _, img_thresh = cv2.threshold(
                img_med, 0, 255, cv2.THRESH_OTSU + cv2.THRESH_BINARY
            )
        else:
            _, img_thresh = cv2.threshold(
                img_med, self.sthresh, 255, cv2.THRESH_BINARY
            )

        # Morphological closing
        if self.close > 0:
            kernel = np.ones((self.close, self.close), np.uint8)
            img_thresh = cv2.morphologyEx(img_thresh, cv2.MORPH_CLOSE, kernel)

        # Find contours
        contours, hierarchy = cv2.findContours(
            img_thresh, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE
        )

        # Filter contours (hierarchy processing is done in _filter_contours)
        tissue_contours, hole_contours = self._filter_contours(
            contours, hierarchy, seg_level, slide
        )

        # Scale contours back to level 0
        scale = self._get_scale(slide, seg_level)
        tissue_contours = self._scale_contours(tissue_contours, scale)
        hole_contours = self._scale_holes(hole_contours, scale)

        logger.info(f"Found {len(tissue_contours)} tissue regions")

        return tissue_contours, hole_contours

    def _get_seg_level(self, slide) -> int:
        """Get appropriate segmentation level (~64x downsample)"""
        if self.seg_level >= 0:
            return min(self.seg_level, len(slide.level_dimensions) - 1)

        # Auto-select level closest to 64x downsample
        target_downsample = 64
        level_downsamples = slide.level_downsamples

        best_level = 0
        min_diff = abs(level_downsamples[0] - target_downsample)

        for i, ds in enumerate(level_downsamples):
            diff = abs(ds - target_downsample)
            if diff < min_diff:
                min_diff = diff
                best_level = i

        return best_level

    def _get_scale(self, slide, level: int) -> Tuple[float, float]:
        """Get scale factor from level to level 0

        To scale coordinates from a downsampled level to level 0,
        we need to multiply by the downsample factor.
        """
        downsample = slide.level_downsamples[level]
        return (downsample, downsample)

    def _filter_contours(
        self,
        contours,
        hierarchy,
        seg_level: int,
        slide
    ) -> Tuple[List, List]:
        """Filter contours by area and extract holes"""
        # Calculate scaled reference patch area
        scale = slide.level_downsamples[seg_level]
        ref_patch_size = 512
        scaled_ref_patch_area = int(ref_patch_size**2 / (scale * scale))

        # Scale filter parameters
        a_t = self.filter_params['a_t'] * scaled_ref_patch_area
        a_h = self.filter_params['a_h'] * scaled_ref_patch_area
        max_n_holes = self.filter_params['max_n_holes']

        filtered_tissue = []
        filtered_holes = []

        # Check if hierarchy is valid
        if hierarchy is None or len(hierarchy) == 0:
            logger.warning("No contours found in hierarchy")
            return filtered_tissue, filtered_holes

        # Flatten hierarchy if needed (OpenCV returns shape (1, N, 4))
        if hierarchy.ndim == 3:
            hierarchy = hierarchy[0]

        # Keep only [First_Child, Parent] columns (like PrePATH/CLAM)
        # OpenCV hierarchy format: [Next, Previous, First_Child, Parent]
        hierarchy = hierarchy[:, 2:]

        # Find foreground contours (parent == -1)
        # Now hierarchy[:, 1] is the Parent column
        hierarchy_1 = np.flatnonzero(hierarchy[:, 1] == -1)

        logger.info(f"Found {len(hierarchy_1)} foreground contours before filtering")

        for cont_idx in hierarchy_1:
            cont = contours[cont_idx]

            # Find holes in this contour
            holes = np.flatnonzero(hierarchy[:, 1] == cont_idx)

            # Calculate contour area (excluding holes)
            area = cv2.contourArea(cont)
            hole_areas = [cv2.contourArea(contours[h]) for h in holes]
            area = area - np.sum(hole_areas)

            x, y, w, h = cv2.boundingRect(cont)
            logger.debug(f"  Contour {cont_idx}: area={area:.0f}, bbox=({x},{y},{w},{h}), a_t={a_t:.0f}")

            if area == 0:
                continue

            # Filter by minimum area
            if area >= a_t:
                filtered_tissue.append(cont)

                # Filter holes
                hole_contours = [contours[h] for h in holes]
                hole_contours = sorted(hole_contours, key=cv2.contourArea, reverse=True)
                hole_contours = hole_contours[:max_n_holes]
                hole_contours = [h for h in hole_contours if cv2.contourArea(h) > a_h]

                filtered_holes.append(hole_contours)

        return filtered_tissue, filtered_holes

    @staticmethod
    def _scale_contours(contours, scale):
        """Scale contours by scale factor"""
        return [np.array(cont * scale, dtype='int32') for cont in contours]

    @staticmethod
    def _scale_holes(holes, scale):
        """Scale hole contours by scale factor"""
        return [[np.array(h * scale, dtype='int32') for h in hole_list]
                for hole_list in holes]


class WSITiler:
    """
    WSI Tiling with CLAM-style contour-based coordinate computation

    More efficient than grid-based approach:
    - Only processes tissue regions (not entire slide)
    - Uses contour checking instead of per-patch tissue detection
    - Supports parallel coordinate generation
    """

    def __init__(
        self,
        patch_size: int = 256,
        stride: int = 256,
        level: int = 0,
        segmenter: Optional[TissueSegmenter] = None,
        contour_fn: str = 'four_pt',
        use_padding: bool = True
    ):
        """
        Args:
            patch_size: Size of patches to extract
            stride: Stride between patches (step_size)
            level: Pyramid level to extract from
            segmenter: Tissue segmentation instance
            contour_fn: Contour checking function ('four_pt', 'center', 'basic')
            use_padding: Allow patches at slide edges
        """
        self.patch_size = patch_size
        self.stride = stride
        self.level = level
        self.segmenter = segmenter or TissueSegmenter()
        self.contour_fn = contour_fn
        self.use_padding = use_padding

    def compute_coordinates(
        self,
        slide,
        save_path: Optional[Path] = None,
        tissue_contours: Optional[List] = None,
        hole_contours: Optional[List] = None
    ) -> List[Tuple[int, int]]:
        """
        Compute patch coordinates within tissue contours

        Args:
            slide: ASlide Slide object
            save_path: Optional path to save coordinates
            tissue_contours: Pre-computed tissue contours (optional)
            hole_contours: Pre-computed hole contours (optional)

        Returns:
            List of (x, y) coordinates at level 0
        """
        logger.info(f"Computing patch coordinates for slide")

        # Segment tissue if contours not provided
        if tissue_contours is None or hole_contours is None:
            logger.info("Segmenting tissue...")
            tissue_contours, hole_contours = self.segmenter.segment_tissue(slide)

        logger.info(f"Processing {len(tissue_contours)} tissue regions")

        # Process each tissue contour
        all_coordinates = []
        for idx, (tissue_cont, holes) in enumerate(zip(tissue_contours, hole_contours)):
            coords = self._process_contour(
                slide, tissue_cont, holes, idx
            )
            all_coordinates.extend(coords)

        logger.info(f"Found {len(all_coordinates)} tissue patches")

        # Save coordinates if path provided
        if save_path:
            self._save_coordinates(all_coordinates, save_path, tissue_contours, hole_contours)

        return all_coordinates

    def _process_contour(
        self,
        slide,
        contour,
        holes: List,
        cont_idx: int
    ) -> List[Tuple[int, int]]:
        """
        Process a single tissue contour to extract patch coordinates

        Args:
            slide: ASlide Slide object
            contour: Tissue contour (at level 0)
            holes: List of hole contours within this tissue region
            cont_idx: Contour index

        Returns:
            List of (x, y) coordinates at level 0
        """
        # Get bounding box
        x, y, w, h = cv2.boundingRect(contour)
        logger.info(f"Contour {cont_idx}: bbox=({x},{y},{w},{h}), area={cv2.contourArea(contour):.0f}")

        # Calculate patch parameters at level 0
        downsample = slide.level_downsamples[self.level]
        ref_patch_size = int(self.patch_size * downsample)
        step_size_x = int(self.stride * downsample)
        step_size_y = int(self.stride * downsample)

        # Determine iteration bounds
        img_w, img_h = slide.level_dimensions[0]
        if self.use_padding:
            stop_x = x + w
            stop_y = y + h
        else:
            stop_x = min(x + w, img_w - ref_patch_size + 1)
            stop_y = min(y + h, img_h - ref_patch_size + 1)

        # Create contour checking function
        cont_check_fn = self._get_contour_check_fn(contour, ref_patch_size)

        # Generate candidate coordinates
        x_range = np.arange(x, stop_x, step=step_size_x)
        y_range = np.arange(y, stop_y, step=step_size_y)
        x_coords, y_coords = np.meshgrid(x_range, y_range, indexing='ij')
        coord_candidates = np.array([x_coords.flatten(), y_coords.flatten()]).transpose()

        # Filter coordinates by contour and holes
        logger.info(f"Contour {cont_idx}: checking {len(coord_candidates)} candidate coordinates")
        valid_coords = []
        for coord in coord_candidates:
            if self._is_in_contour(cont_check_fn, coord, holes, ref_patch_size):
                valid_coords.append(tuple(coord))

        logger.info(f"Contour {cont_idx}: extracted {len(valid_coords)} patches from {len(coord_candidates)} candidates")

        return valid_coords

    def _get_contour_check_fn(self, contour, patch_size: int):
        """Create contour checking function based on contour_fn type"""
        if self.contour_fn == 'four_pt':
            # Check 4 points around center
            def check_fn(pt):
                center = (float(pt[0] + patch_size // 2), float(pt[1] + patch_size // 2))
                offset = patch_size // 4
                points = [
                    (float(center[0] - offset), float(center[1] - offset)),
                    (float(center[0] + offset), float(center[1] - offset)),
                    (float(center[0] - offset), float(center[1] + offset)),
                    (float(center[0] + offset), float(center[1] + offset)),
                ]
                return all(cv2.pointPolygonTest(contour, p, False) >= 0 for p in points)
            return check_fn

        elif self.contour_fn == 'center':
            # Check center point only
            def check_fn(pt):
                center = (float(pt[0] + patch_size // 2), float(pt[1] + patch_size // 2))
                return cv2.pointPolygonTest(contour, center, False) >= 0
            return check_fn

        else:  # 'basic'
            # Check top-left corner only
            def check_fn(pt):
                return cv2.pointPolygonTest(contour, (float(pt[0]), float(pt[1])), False) >= 0
            return check_fn

    @staticmethod
    def _is_in_contour(cont_check_fn, pt, holes: List, patch_size: int) -> bool:
        """Check if point is in contour and not in any holes"""
        if not cont_check_fn(pt):
            return False

        # Check if in any hole
        center = (float(pt[0] + patch_size // 2), float(pt[1] + patch_size // 2))
        for hole in holes:
            if cv2.pointPolygonTest(hole, center, False) > 0:
                return False

        return True

    def _save_coordinates(
        self,
        coordinates: List[Tuple[int, int]],
        save_path,  # Can be str or Path
        tissue_contours: Optional[List] = None,
        hole_contours: Optional[List] = None
    ):
        """Save coordinates and metadata to HDF5 file in PrePATH-compatible format"""
        import h5py

        # Convert to Path if string
        if isinstance(save_path, str):
            save_path = Path(save_path)

        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert coordinates to numpy array
        coords_array = np.array(coordinates, dtype=np.int32)

        with h5py.File(save_path, 'w') as f:
            # Create coords dataset
            dset = f.create_dataset('coords', data=coords_array)

            # Save metadata as attributes on the coords dataset (PrePATH-compatible)
            dset.attrs['patch_size'] = self.patch_size
            dset.attrs['patch_level'] = self.level
            dset.attrs['name'] = save_path.stem  # Slide name from filename

            # Additional metadata (not in PrePATH but useful)
            dset.attrs['stride'] = self.stride
            dset.attrs['contour_fn'] = self.contour_fn
            dset.attrs['use_padding'] = self.use_padding

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
        coordinates: List[Tuple[int, int]],
        max_patches: Optional[int] = None
    ) -> List[Image.Image]:
        """
        Extract patches from slide using pre-computed coordinates

        Args:
            slide: ASlide Slide object
            coordinates: List of (x, y) coordinates at level 0
            max_patches: Maximum number of patches to extract (optional)

        Returns:
            List of PIL Image patches
        """
        # Limit number of patches if specified
        if max_patches is not None and max_patches < len(coordinates):
            # Sample uniformly
            indices = np.linspace(0, len(coordinates) - 1, max_patches, dtype=int)
            coordinates = [coordinates[i] for i in indices]
            logger.info(f"Sampling {max_patches} patches from {len(coordinates)} total")

        patches = []

        for x, y in coordinates:
            try:
                # read_region expects level 0 coordinates
                patch = slide.read_region(
                    (x, y),
                    self.level,
                    (self.patch_size, self.patch_size)
                )

                # Convert RGBA to RGB if needed
                if patch.mode == 'RGBA':
                    patch = patch.convert('RGB')

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
    force_recompute: bool = False,
    seg_params: Optional[Dict] = None,
    filter_params: Optional[Dict] = None,
    contour_fn: str = 'four_pt',
    use_padding: bool = True
) -> List[Tuple[int, int]]:
    """
    Get patch coordinates from cache or compute if not exists

    Args:
        wsi_id: WSI identifier
        slide: ASlide Slide object
        coords_dir: Directory to store coordinates
        patch_size: Patch size
        stride: Stride (step_size)
        level: Pyramid level
        force_recompute: Force recomputation even if cache exists
        seg_params: Segmentation parameters (optional)
        filter_params: Contour filtering parameters (optional)
        contour_fn: Contour checking function
        use_padding: Allow patches at tissue boundary

    Returns:
        List of (x, y) coordinates at level 0
    """
    coords_file = coords_dir / f"{wsi_id}_coords.h5"

    # Load from cache if exists
    if coords_file.exists() and not force_recompute:
        logger.info(f"Loading coordinates from cache: {coords_file}")
        try:
            import h5py
            with h5py.File(coords_file, 'r') as f:
                coords_array = f['coords'][:]
                attrs = dict(f['coords'].attrs)

                # Verify parameters match
                if (attrs.get('patch_size') == patch_size and
                    attrs.get('stride') == stride and
                    attrs.get('patch_level') == level):
                    return [tuple(coord) for coord in coords_array]
                else:
                    logger.warning("Cached coordinates have different parameters, recomputing")
        except Exception as e:
            logger.warning(f"Failed to load cached coordinates: {e}, recomputing")

    # Compute new coordinates
    logger.info(f"Computing new coordinates for {wsi_id}")

    # Create segmenter with custom parameters
    segmenter = TissueSegmenter(
        **(seg_params or {}),
        filter_params=filter_params
    )

    # Create tiler
    tiler = WSITiler(
        patch_size=patch_size,
        stride=stride,
        level=level,
        segmenter=segmenter,
        contour_fn=contour_fn,
        use_padding=use_padding
    )

    coordinates = tiler.compute_coordinates(slide, save_path=coords_file)
    return coordinates


def visualize_segmentation(
    slide,
    tissue_contours: List,
    hole_contours: List,
    vis_level: int = -1,
    line_thickness: int = 5,
    color: Tuple[int, int, int] = (0, 255, 0),
    hole_color: Tuple[int, int, int] = (0, 0, 255)
) -> Image.Image:
    """
    Visualize tissue segmentation results

    Args:
        slide: ASlide Slide object
        tissue_contours: List of tissue contours (at level 0)
        hole_contours: List of hole contours (at level 0)
        vis_level: Visualization level (-1 = auto select ~64x)
        line_thickness: Line thickness for drawing contours
        color: Color for tissue contours (RGB)
        hole_color: Color for hole contours (RGB)

    Returns:
        PIL Image with segmentation overlay
    """
    # Auto-select visualization level
    if vis_level < 0:
        target_downsample = 64
        level_downsamples = slide.level_downsamples
        vis_level = 0
        min_diff = abs(level_downsamples[0] - target_downsample)
        for i, ds in enumerate(level_downsamples):
            diff = abs(ds - target_downsample)
            if diff < min_diff:
                min_diff = diff
                vis_level = i

    # Read slide at visualization level
    level_dims = slide.level_dimensions[vis_level]
    img = slide.read_region((0, 0), vis_level, level_dims)
    img_np = np.array(img.convert('RGB'))

    # Scale contours to visualization level
    downsample = slide.level_downsamples[vis_level]
    scale = (1.0 / downsample, 1.0 / downsample)

    scaled_tissue = [np.array(cont * scale, dtype='int32') for cont in tissue_contours]
    scaled_holes = [[np.array(h * scale, dtype='int32') for h in holes]
                    for holes in hole_contours]

    # Draw tissue contours
    cv2.drawContours(img_np, scaled_tissue, -1, color, line_thickness, lineType=cv2.LINE_8)

    # Draw holes
    for holes in scaled_holes:
        cv2.drawContours(img_np, holes, -1, hole_color, line_thickness, lineType=cv2.LINE_8)

    return Image.fromarray(img_np)

