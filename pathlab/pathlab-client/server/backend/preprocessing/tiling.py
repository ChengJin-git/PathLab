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

# PrePATH-style resolution configuration
# Different magnifications use different patch sizes to maintain consistent physical coverage (~128μm)
# 20x (mpp≈0.5): 256px × 0.5μm = 128μm
# 40x (mpp≈0.25): 512px × 0.25μm = 128μm
# 80x (mpp≈0.125): 1024px × 0.125μm = 128μm
PREPATH_SIZES = {"20x": 256, "40x": 512, "80x": 1024}
PREPATH_STEPS = {"20x": 256, "40x": 512, "80x": 1024}


def get_magnification_from_mpp(mpp: float) -> str:
    """
    Determine magnification category from MPP value.

    Uses the same logic as PrePATH:
    object_power = int(round(10.0 / mpp))

    Args:
        mpp: Microns per pixel

    Returns:
        Magnification string: "20x", "40x", or "80x"
    """
    object_power = int(round(10.0 / mpp))
    if object_power <= 30:
        return "20x"
    elif object_power <= 60:
        return "40x"
    else:
        return "80x"


def adjust_size_by_magnification(mpp: float) -> tuple[int, int]:
    """
    Adjust patch size and step size based on WSI magnification (PrePATH-style).

    This ensures different resolution WSIs cut patches covering the same physical area (~128μm).

    Args:
        mpp: Microns per pixel at level 0

    Returns:
        Tuple of (patch_size, step_size)
    """
    mag = get_magnification_from_mpp(mpp)
    patch_size = PREPATH_SIZES[mag]
    step_size = PREPATH_STEPS[mag]
    return patch_size, step_size


def get_native_mpp(slide) -> Optional[float]:
    """
    Extract native MPP from slide object.

    Args:
        slide: ASlide Slide object

    Returns:
        MPP value as float, or None if not available
    """
    try:
        mpp_value = slide.mpp
        if isinstance(mpp_value, (int, float)) and mpp_value > 0:
            return float(mpp_value)
        elif isinstance(mpp_value, tuple) and len(mpp_value) >= 2:
            # If mpp is a tuple (mpp_x, mpp_y), take average
            avg_mpp = (float(mpp_value[0]) + float(mpp_value[1])) / 2
            if avg_mpp > 0:
                return avg_mpp
    except Exception as e:
        logger.warning(f"Failed to get MPP from slide: {e}")
    return None


class TissueSegmenter:
    """
    Tissue segmentation using CLAM-style approach

    Uses HSV color space + Otsu/Binary thresholding + morphological operations
    to detect tissue regions and filter out background/artifacts
    """

    def __init__(
        self,
        seg_level: int = -1,
        sthresh: int = 8,
        mthresh: int = 7,
        close: int = 4,
        use_otsu: bool = False,
        filter_params: Optional[Dict] = None
    ):
        """
        Args:
            seg_level: Pyramid level for segmentation (-1 = auto select ~96x downsample)
            sthresh: Binary threshold value (default: 8, low threshold for maximum tissue detection)
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
        # import time as _time

        # Auto-select segmentation level if needed
        seg_level = self._get_seg_level(slide)
        logger.info(f"Segmenting at level {seg_level}")

        # Read slide at segmentation level
        level_dims = slide.level_dimensions[seg_level]
        # _t0 = _time.monotonic()
        img = slide.read_region((0, 0), seg_level, level_dims)
        # _t1 = _time.monotonic()
        # logger.info(f"[Timing] read_region level={seg_level} dims={level_dims} took {_t1 - _t0:.1f}s")
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

        # _t2 = _time.monotonic()
        # logger.info(f"[Timing] segment_tissue total {_t2 - _t0:.1f}s (read={_t1 - _t0:.1f}s, process={_t2 - _t1:.1f}s), found {len(tissue_contours)} tissue regions")

        return tissue_contours, hole_contours

    def _get_seg_level(self, slide) -> int:
        """Get appropriate segmentation level (~96x downsample)"""
        if self.seg_level >= 0:
            return min(self.seg_level, len(slide.level_dimensions) - 1)

        # Auto-select level closest to 96x downsample
        target_downsample = 96
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

    Supports MPP-aware tiling for resolution normalization:
    - Patches are extracted at target MPP (default 0.25, i.e., 40x)
    - Physical size is preserved across different scanners
    - Automatic scaling when native MPP differs from target MPP

    More efficient than grid-based approach:
    - Only processes tissue regions (not entire slide)
    - Uses contour checking instead of per-patch tissue detection
    - Supports parallel coordinate generation
    """

    def __init__(
        self,
        patch_size: int = 256,
        stride: int = 0,
        level: int = 0,
        segmenter: Optional[TissueSegmenter] = None,
        contour_fn: str = 'four_pt',
        use_padding: bool = True,
        native_mpp: Optional[float] = None,
        level_downsample: float = 1.0
    ):
        """
        PrePATH-style tiling: automatically adjusts patch_size based on magnification
        to ensure different resolution WSIs cut patches covering the same physical area (~128μm).

        Args:
            patch_size: Ignored when native_mpp is available (auto-adjusted by magnification)
            stride: Stride between patches (0 = non-overlapping, auto-set to patch_size)
            level: Pyramid level to extract from (always 0 for PrePATH-style)
            segmenter: Tissue segmentation instance
            contour_fn: Contour checking function ('four_pt', 'center', 'basic')
            use_padding: Allow patches at slide edges
            native_mpp: Native MPP of the slide at level 0. If None, falls back to pixel-based tiling
            level_downsample: Downsample factor for the specified level (slide.level_downsamples[level])
        """
        self.level = level
        self.segmenter = segmenter or TissueSegmenter()
        self.contour_fn = contour_fn
        self.use_padding = use_padding
        self.native_mpp = native_mpp
        self.level_downsample = level_downsample

        # PrePATH-style: auto-adjust patch_size and step_size based on magnification
        # This ensures patches from different resolution WSIs cover the same physical area (~128μm)
        if native_mpp is not None and native_mpp > 0:
            # Determine patch_size and step_size based on magnification
            auto_patch_size, auto_step_size = adjust_size_by_magnification(native_mpp)
            self.patch_size = auto_patch_size

            # For stride: if 0 (non-overlapping), use auto_step_size; otherwise use provided stride
            if stride == 0:
                self.stride = auto_step_size
            else:
                self.stride = stride

            # read_size == patch_size (no resize needed in PrePATH-style)
            self.read_size = self.patch_size
            # step_size is the stride at level 0 (in native pixels)
            self.step_size = self.stride

            mag = get_magnification_from_mpp(native_mpp)
            logger.info(f"PrePATH-style tiling: native_mpp={native_mpp:.4f}, magnification={mag}, "
                       f"patch_size={self.patch_size}, step_size={self.step_size}")
        else:
            # Fallback: no MPP info, use provided patch_size and stride
            self.patch_size = patch_size
            self.stride = stride if stride > 0 else patch_size
            self.read_size = self.patch_size
            self.step_size = self.stride
            logger.warning("No MPP info available, falling back to pixel-based tiling with "
                          f"patch_size={self.patch_size}, step_size={self.step_size}")

    def compute_coordinates(
        self,
        slide,
        save_path: Optional[Path] = None,
        tissue_contours: Optional[List] = None,
        hole_contours: Optional[List] = None,
        seg_params: Optional[Dict] = None,
        filter_params: Optional[Dict] = None
    ) -> List[Tuple[int, int]]:
        """
        Compute patch coordinates within tissue contours

        Args:
            slide: ASlide Slide object
            save_path: Optional path to save coordinates
            tissue_contours: Pre-computed tissue contours (optional)
            hole_contours: Pre-computed hole contours (optional)
            seg_params: Segmentation parameters (for cache metadata)
            filter_params: Filter parameters (for cache metadata)

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
            self._save_coordinates(
                all_coordinates, save_path, tissue_contours, hole_contours,
                seg_params=seg_params, filter_params=filter_params
            )

        return all_coordinates

    def _process_contour(
        self,
        slide,
        contour,
        holes: List,
        cont_idx: int
    ) -> List[Tuple[int, int]]:
        """
        Process a single tissue contour to extract patch coordinates.

        Uses vectorized mask-based filtering: draws filled contour/hole masks
        with cv2.drawContours, then checks all candidate points via numpy
        array indexing instead of per-point cv2.pointPolygonTest calls.

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
        ref_patch_size = int(self.read_size * downsample)
        step_size_x = int(self.step_size * downsample)
        step_size_y = int(self.step_size * downsample)

        # Determine iteration bounds
        img_w, img_h = slide.level_dimensions[0]
        if self.use_padding:
            stop_x = x + w
            stop_y = y + h
        else:
            stop_x = min(x + w, img_w - ref_patch_size + 1)
            stop_y = min(y + h, img_h - ref_patch_size + 1)

        # Generate candidate coordinates
        x_range = np.arange(x, stop_x, step=step_size_x)
        y_range = np.arange(y, stop_y, step=step_size_y)

        if len(x_range) == 0 or len(y_range) == 0:
            logger.info(f"Contour {cont_idx}: no candidate coordinates")
            return []

        x_coords, y_coords = np.meshgrid(x_range, y_range, indexing='ij')
        coord_candidates = np.array([x_coords.flatten(), y_coords.flatten()]).T
        num_candidates = len(coord_candidates)
        logger.info(f"Contour {cont_idx}: checking {num_candidates} candidate coordinates")

        if num_candidates == 0:
            return []

        # --- Vectorized mask-based filtering ---
        # Choose mask resolution: ref_patch_size // 4 matches four_pt offset granularity
        mask_scale = max(ref_patch_size // 4, 1)

        # Extend bounding box to cover all test points (center ± offset)
        extend = ref_patch_size
        mask_x0 = x - extend
        mask_y0 = y - extend
        mask_w = int(np.ceil((w + 2 * extend) / mask_scale)) + 1
        mask_h = int(np.ceil((h + 2 * extend) / mask_scale)) + 1

        # Build filled tissue mask
        tissue_mask = np.zeros((mask_h, mask_w), dtype=np.uint8)
        sc = ((contour.squeeze().astype(np.float64) - [mask_x0, mask_y0]) / mask_scale).astype(np.int32)
        cv2.drawContours(tissue_mask, [sc.reshape(-1, 1, 2)], -1, 255, -1)

        # Build filled holes mask
        holes_mask = np.zeros((mask_h, mask_w), dtype=np.uint8) if holes else None
        for hole in holes:
            sh = ((hole.squeeze().astype(np.float64) - [mask_x0, mask_y0]) / mask_scale).astype(np.int32)
            cv2.drawContours(holes_mask, [sh.reshape(-1, 1, 2)], -1, 255, -1)

        half = ref_patch_size // 2
        quarter = ref_patch_size // 4
        cx = coord_candidates[:, 0] + half   # center x
        cy = coord_candidates[:, 1] + half   # center y

        # Determine tissue test points based on contour_fn mode
        if self.contour_fn == 'four_pt':
            tpx = np.stack([cx - quarter, cx + quarter, cx - quarter, cx + quarter], axis=1)
            tpy = np.stack([cy - quarter, cy - quarter, cy + quarter, cy + quarter], axis=1)
        elif self.contour_fn == 'center':
            tpx = cx.reshape(-1, 1)
            tpy = cy.reshape(-1, 1)
        else:  # basic – top-left corner
            tpx = coord_candidates[:, 0].astype(np.float64).reshape(-1, 1)
            tpy = coord_candidates[:, 1].astype(np.float64).reshape(-1, 1)

        # Convert test points to mask indices
        mpx = ((tpx - mask_x0) / mask_scale).astype(np.int32)
        mpy = ((tpy - mask_y0) / mask_scale).astype(np.int32)

        # Vectorised tissue check: ALL test points must be inside
        in_tissue = np.ones(num_candidates, dtype=bool)
        for i in range(tpx.shape[1]):
            mx = mpx[:, i]
            my = mpy[:, i]
            ib = (mx >= 0) & (mx < mask_w) & (my >= 0) & (my < mask_h)
            ok = np.zeros(num_candidates, dtype=bool)
            idx = np.where(ib)[0]
            if len(idx) > 0:
                ok[idx] = tissue_mask[my[idx], mx[idx]] > 0
            in_tissue &= ok

        # Vectorised hole check: center must NOT be in any hole
        if holes_mask is not None and np.any(in_tissue):
            hx = ((cx - mask_x0) / mask_scale).astype(np.int32)
            hy = ((cy - mask_y0) / mask_scale).astype(np.int32)
            ib = (hx >= 0) & (hx < mask_w) & (hy >= 0) & (hy < mask_h)
            in_hole = np.zeros(num_candidates, dtype=bool)
            idx = np.where(ib & in_tissue)[0]
            if len(idx) > 0:
                in_hole[idx] = holes_mask[hy[idx], hx[idx]] > 0
            in_tissue &= ~in_hole

        valid_coords = [tuple(c) for c in coord_candidates[in_tissue]]
        logger.info(f"Contour {cont_idx}: extracted {len(valid_coords)} patches from {num_candidates} candidates")
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
        hole_contours: Optional[List] = None,
        seg_params: Optional[Dict] = None,
        filter_params: Optional[Dict] = None
    ):
        """
        Save coordinates and metadata to HDF5 file using atomic write pattern.

        Writes to a .h5.partial temporary file first, then renames to .h5.
        This ensures that if the process is interrupted during saving,
        the incomplete file is clearly identifiable and won't be mistaken
        for a valid cache entry.

        All parameters are always saved to ensure cache consistency.
        Default values are used when seg_params or filter_params are None.
        """
        import h5py

        # Convert to Path if string
        if isinstance(save_path, str):
            save_path = Path(save_path)

        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert coordinates to numpy array
        coords_array = np.array(coordinates, dtype=np.int32)

        # Use defaults for seg_params and filter_params if None
        seg_params = seg_params or {}
        filter_params = filter_params or {}

        # Write to .partial file first, then atomically rename
        partial_path = save_path.parent / f"{save_path.stem}.h5.partial"

        with h5py.File(partial_path, 'w') as f:
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

            # MPP-related parameters for cache validation
            dset.attrs['native_mpp'] = self.native_mpp if self.native_mpp is not None else -1.0
            dset.attrs['level_downsample'] = self.level_downsample
            dset.attrs['read_size'] = self.read_size
            dset.attrs['step_size'] = self.step_size

            # Save seg_level from segmenter (always save for cache consistency)
            dset.attrs['seg_level'] = self.segmenter.seg_level

            # Save segmentation parameters (always save with defaults for cache consistency)
            dset.attrs['sthresh'] = seg_params.get('sthresh', 5)
            dset.attrs['mthresh'] = seg_params.get('mthresh', 7)
            dset.attrs['close'] = seg_params.get('close', 4)
            dset.attrs['use_otsu'] = seg_params.get('use_otsu', False)

            # Save filter parameters (always save with defaults for cache consistency)
            dset.attrs['a_t'] = filter_params.get('a_t', 100)
            dset.attrs['a_h'] = filter_params.get('a_h', 16)
            dset.attrs['max_n_holes'] = filter_params.get('max_n_holes', 8)

        # Atomically rename to final path
        partial_path.rename(save_path)

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

        Patches are read at read_size (MPP-adjusted) and resized to patch_size.

        Args:
            slide: ASlide Slide object
            coordinates: List of (x, y) coordinates at level 0
            max_patches: Maximum number of patches to extract (optional)

        Returns:
            List of PIL Image patches (all at patch_size x patch_size)
        """
        # Limit number of patches if specified
        if max_patches is not None and max_patches < len(coordinates):
            # Sample uniformly
            indices = np.linspace(0, len(coordinates) - 1, max_patches, dtype=int)
            coordinates = [coordinates[i] for i in indices]
            logger.info(f"Sampling {max_patches} patches from {len(coordinates)} total")

        patches = []
        needs_resize = self.read_size != self.patch_size

        for x, y in coordinates:
            try:
                # read_region expects level 0 coordinates
                # Read at read_size (MPP-adjusted size)
                patch = slide.read_region(
                    (x, y),
                    self.level,
                    (self.read_size, self.read_size)
                )

                # Convert RGBA to RGB if needed
                if patch.mode == 'RGBA':
                    patch = patch.convert('RGB')

                # Resize to output patch_size if needed
                if needs_resize:
                    patch = patch.resize((self.patch_size, self.patch_size), Image.Resampling.LANCZOS)

                patches.append(patch)

            except Exception as e:
                logger.warning(f"Failed to extract patch at ({x}, {y}): {e}")
                continue

        logger.info(f"Extracted {len(patches)} patches (read_size={self.read_size}, output_size={self.patch_size})")
        return patches


# Required attributes that must exist in coords.h5 for valid cache
# Note: patch_size and stride are recorded but NOT used for cache validation
# because they are auto-determined by each WSI's magnification/MPP (PrePATH-style)
REQUIRED_COORDS_ATTRS = [
    'patch_size', 'stride', 'patch_level', 'contour_fn', 'use_padding',
    'seg_level', 'sthresh', 'mthresh', 'close', 'use_otsu',
    'a_t', 'a_h', 'max_n_holes',
    'native_mpp', 'read_size', 'step_size',
]


def _check_coords_params_match(
    attrs: Dict,
    level: int,
    seg_params: Optional[Dict],
    filter_params: Optional[Dict],
    contour_fn: str,
    use_padding: bool,
    seg_level: int = -1,
    **kwargs,  # Ignore legacy patch_size, stride parameters
) -> bool:
    """
    Check if cached coordinates parameters match the requested parameters.

    Returns True if all parameters match, False otherwise.

    PrePATH-style: patch_size and stride are NOT validated because they are
    automatically determined by each WSI's magnification/MPP.

    NOTE: All required attributes must exist in the cached file. Old cache files
    without complete attributes will return False, forcing recomputation.
    """
    # Check all required attributes exist first
    missing_attrs = [attr for attr in REQUIRED_COORDS_ATTRS if attr not in attrs]
    if missing_attrs:
        logger.warning(
            f"Missing required attributes in cache: {missing_attrs}. "
            "This is likely an old cache file that needs recomputation."
        )
        return False

    # Use defaults for seg_params and filter_params if None
    seg_params = seg_params or {}
    filter_params = filter_params or {}

    # Check basic tiling parameters (NOT patch_size/stride - they're auto-determined by MPP)
    if attrs['patch_level'] != level:
        logger.warning(f"patch_level mismatch: cached={attrs['patch_level']}, requested={level}")
        return False

    # Handle bytes vs string for contour_fn
    cached_contour_fn = attrs['contour_fn']
    if isinstance(cached_contour_fn, bytes):
        cached_contour_fn = cached_contour_fn.decode('utf-8')

    if cached_contour_fn != contour_fn:
        logger.warning(f"contour_fn mismatch: cached={cached_contour_fn}, requested={contour_fn}")
        return False
    if attrs['use_padding'] != use_padding:
        logger.warning(f"use_padding mismatch: cached={attrs['use_padding']}, requested={use_padding}")
        return False

    # Check seg_level
    if attrs['seg_level'] != seg_level:
        logger.warning(f"seg_level mismatch: cached={attrs['seg_level']}, requested={seg_level}")
        return False

    # Check segmentation parameters (always check, use defaults if not provided)
    requested_sthresh = seg_params.get('sthresh', 5)
    if attrs['sthresh'] != requested_sthresh:
        logger.warning(f"sthresh mismatch: cached={attrs['sthresh']}, requested={requested_sthresh}")
        return False

    requested_mthresh = seg_params.get('mthresh', 7)
    if attrs['mthresh'] != requested_mthresh:
        logger.warning(f"mthresh mismatch: cached={attrs['mthresh']}, requested={requested_mthresh}")
        return False

    requested_close = seg_params.get('close', 4)
    if attrs['close'] != requested_close:
        logger.warning(f"close mismatch: cached={attrs['close']}, requested={requested_close}")
        return False

    requested_use_otsu = seg_params.get('use_otsu', False)
    if attrs['use_otsu'] != requested_use_otsu:
        logger.warning(f"use_otsu mismatch: cached={attrs['use_otsu']}, requested={requested_use_otsu}")
        return False

    # Check filter parameters (always check, use defaults if not provided)
    requested_a_t = filter_params.get('a_t', 100)
    if attrs['a_t'] != requested_a_t:
        logger.warning(f"a_t mismatch: cached={attrs['a_t']}, requested={requested_a_t}")
        return False

    requested_a_h = filter_params.get('a_h', 16)
    if attrs['a_h'] != requested_a_h:
        logger.warning(f"a_h mismatch: cached={attrs['a_h']}, requested={requested_a_h}")
        return False

    requested_max_n_holes = filter_params.get('max_n_holes', 8)
    if attrs['max_n_holes'] != requested_max_n_holes:
        logger.warning(f"max_n_holes mismatch: cached={attrs['max_n_holes']}, requested={requested_max_n_holes}")
        return False

    # NOTE: native_mpp is NOT validated - same slide always has same MPP
    # patch_size and stride are also NOT validated - they're auto-determined by MPP

    return True


def check_coords_cache_valid(
    wsi_id: str,
    coords_dir: Path,
    level: int = 0,
    seg_params: Optional[Dict] = None,
    filter_params: Optional[Dict] = None,
    contour_fn: str = 'four_pt',
    use_padding: bool = True,
    seg_level: int = -1,
    **kwargs,  # Ignore legacy patch_size, stride parameters
) -> Optional[Tuple[List[Tuple[int, int]], Path]]:
    """
    Check if valid cached coordinates exist for the given parameters.

    Uses params_hash-based directory structure:
        coords_dir/{params_hash}/{wsi_id}_coords.h5

    PrePATH-style: patch_size and stride are NOT used for cache key.

    Returns:
        Tuple of (coordinates, coords_file_path) if valid cache exists, None otherwise.
        If a .h5.partial file is found, it indicates a previous extraction was
        interrupted — the partial file is deleted and None is returned.
    """
    from backend.ai.tasks.feature_cache import compute_params_hash

    # Compute params_hash for cache lookup (PrePATH-style: no patch_size/stride)
    params_hash = compute_params_hash(
        level=level,
        seg_params=seg_params,
        filter_params=filter_params,
        contour_fn=contour_fn,
        use_padding=use_padding,
        seg_level=seg_level,
    )

    coords_file = coords_dir / params_hash / f"{wsi_id}_coords.h5"

    # Check for incomplete extraction artifact
    partial_path = coords_file.parent / f"{wsi_id}_coords.h5.partial"
    if partial_path.exists():
        logger.warning(f"Found incomplete coordinates file: {partial_path}, deleting")
        try:
            partial_path.unlink()
        except OSError as e:
            logger.warning(f"Failed to delete partial file {partial_path}: {e}")

    if not coords_file.exists():
        return None

    # Use safe loading to handle corrupted files
    coords_array, attrs, load_error = safe_load_h5_coords(coords_file, delete_if_corrupted=True)

    if coords_array is None:
        logger.warning(f"Failed to load cached coordinates: {load_error}")
        return None

    # With params_hash directory structure, we trust the hash matches
    # But still validate to catch any edge cases (e.g., hash collision)
    if _check_coords_params_match(
        attrs, level,
        seg_params, filter_params, contour_fn, use_padding,
        seg_level=seg_level,
    ):
        if len(coords_array) > 0:
            logger.info(f"[Coords cache hit] {len(coords_array)} coordinates from {coords_file}")
            return [tuple(coord) for coord in coords_array], coords_file
        else:
            # Cached file has 0 coordinates - treat as cache miss so adaptive fallback can try
            logger.warning(
                f"[Coords cache] Cached file has 0 coordinates for {wsi_id}, "
                f"treating as cache miss for adaptive seg_level fallback"
            )
            return None

    logger.info("Cached coordinates have different parameters (hash collision?)")
    return None


def get_or_compute_coordinates(
    wsi_id: str,
    slide,
    coords_dir: Path,
    level: int = 0,
    force_recompute: bool = False,
    seg_params: Optional[Dict] = None,
    filter_params: Optional[Dict] = None,
    contour_fn: str = 'four_pt',
    use_padding: bool = True,
    seg_level: int = -1,
    tissue_contours: Optional[List] = None,
    hole_contours: Optional[List] = None,
    **kwargs,  # Ignore legacy patch_size, stride parameters
) -> Tuple[List[Tuple[int, int]], Path]:
    """
    Get patch coordinates from cache or compute if not exists.

    Uses params_hash-based directory structure for caching:
        coords_dir/{params_hash}/{wsi_id}_coords.h5

    PrePATH-style tiling: patch_size and stride are automatically determined
    by each WSI's magnification/MPP, NOT passed as parameters.

    Cache validation checks parameters including:
    - level (pyramid level)
    - contour_fn, use_padding (tiling options)
    - seg_level: pyramid level for tissue segmentation
    - seg_params: sthresh, mthresh, close, use_otsu (segmentation params)
    - filter_params: a_t, a_h, max_n_holes (contour filter params)

    native_mpp is automatically extracted from the slide object.

    Args:
        wsi_id: WSI identifier
        slide: ASlide Slide object
        coords_dir: Root directory to store coordinates (e.g., uploads/coordinates)
        level: Pyramid level (always 0 for PrePATH-style)
        force_recompute: Force recomputation even if cache exists
        seg_params: Segmentation parameters (optional)
        filter_params: Contour filtering parameters (optional)
        contour_fn: Contour checking function
        use_padding: Allow patches at tissue boundary
        seg_level: Pyramid level for tissue segmentation (-1 = auto)

    Returns:
        Tuple of (coordinates, coords_file_path):
        - coordinates: List of (x, y) coordinates at level 0
        - coords_file_path: Path to the saved/cached coords h5 file
    """
    from backend.ai.tasks.feature_cache import compute_params_hash

    # Compute params_hash for cache directory (PrePATH-style: no patch_size/stride)
    params_hash = compute_params_hash(
        level=level,
        seg_params=seg_params,
        filter_params=filter_params,
        contour_fn=contour_fn,
        use_padding=use_padding,
        seg_level=seg_level,
    )

    # Create cache directory with params_hash
    cache_dir = coords_dir / params_hash
    cache_dir.mkdir(parents=True, exist_ok=True)
    coords_file = cache_dir / f"{wsi_id}_coords.h5"

    # Check for incomplete extraction artifact
    partial_path = coords_file.parent / f"{wsi_id}_coords.h5.partial"
    if partial_path.exists():
        logger.warning(f"Found incomplete coordinates file: {partial_path}, deleting")
        try:
            partial_path.unlink()
        except OSError as e:
            logger.warning(f"Failed to delete partial file {partial_path}: {e}")

    # Get native MPP from slide for MPP-aware tiling
    native_mpp = get_native_mpp(slide)
    logger.info(f"Slide native MPP: {native_mpp}, params_hash: {params_hash}")

    # Load from cache if exists
    if coords_file.exists() and not force_recompute:
        logger.info(f"Checking cached coordinates: {coords_file}")

        # Use safe loading to handle corrupted files
        coords_array, attrs, load_error = safe_load_h5_coords(coords_file, delete_if_corrupted=True)

        if coords_array is not None:
            # With params_hash directory, we trust the hash matches
            # But still validate to catch edge cases
            if _check_coords_params_match(
                attrs, level,
                seg_params, filter_params, contour_fn, use_padding,
                seg_level=seg_level,
            ):
                if len(coords_array) > 0:
                    logger.info(f"[Coords cache hit] {len(coords_array)} coordinates from {coords_file}")
                    return [tuple(coord) for coord in coords_array], coords_file
                else:
                    # Cached file has 0 coordinates - recompute with adaptive fallback
                    logger.warning(
                        f"[Coords cache hit] Cached file has 0 coordinates for {wsi_id}, "
                        f"recomputing with adaptive seg_level fallback"
                    )
            else:
                logger.warning("Cached coordinates have different parameters (hash collision?), recomputing")
        else:
            logger.warning(f"Failed to load cached coordinates: {load_error}, recomputing")

    # Compute new coordinates
    logger.info(f"Computing new coordinates for {wsi_id}")

    # Merge seg_level into seg_params for TissueSegmenter
    effective_seg_params = dict(seg_params or {})
    effective_seg_params['seg_level'] = seg_level

    # Create segmenter with custom parameters
    segmenter = TissueSegmenter(
        **effective_seg_params,
        filter_params=filter_params
    )

    # Resolve the actual segmentation level (auto-selection resolves -1 to a concrete level)
    initial_seg_level = segmenter._get_seg_level(slide)

    # Get level downsample factor for MPP calculation
    level_downsample = slide.level_downsamples[level] if level < len(slide.level_downsamples) else 1.0

    # Create tiler with PrePATH-style settings (patch_size/stride auto-determined by MPP)
    tiler = WSITiler(
        level=level,
        segmenter=segmenter,
        contour_fn=contour_fn,
        use_padding=use_padding,
        native_mpp=native_mpp,
        level_downsample=level_downsample,
    )

    # Don't save yet - may need adaptive fallback to lower seg_levels
    coordinates = tiler.compute_coordinates(
        slide, save_path=None,
        tissue_contours=tissue_contours,
        hole_contours=hole_contours,
        seg_params=seg_params, filter_params=filter_params
    )

    # Adaptive seg_level fallback: if no coordinates found, try lower seg_levels
    # Lower levels have higher resolution, making it easier to detect small tissue regions
    if len(coordinates) == 0 and initial_seg_level > 0:
        logger.warning(
            f"No coordinates found at seg_level={initial_seg_level} for {wsi_id}, "
            f"trying lower levels adaptively..."
        )
        for fallback_level in range(initial_seg_level - 1, -1, -1):
            logger.info(f"[Adaptive fallback] Trying seg_level={fallback_level} for {wsi_id}")

            fallback_seg_params = dict(seg_params or {})
            fallback_seg_params['seg_level'] = fallback_level

            fallback_segmenter = TissueSegmenter(
                **fallback_seg_params,
                filter_params=filter_params
            )

            fallback_tiler = WSITiler(
                level=level,
                segmenter=fallback_segmenter,
                contour_fn=contour_fn,
                use_padding=use_padding,
                native_mpp=native_mpp,
                level_downsample=level_downsample,
            )

            coordinates = fallback_tiler.compute_coordinates(
                slide, save_path=None,
                seg_params=seg_params, filter_params=filter_params
            )

            if len(coordinates) > 0:
                logger.info(
                    f"[Adaptive fallback] Found {len(coordinates)} coordinates at "
                    f"seg_level={fallback_level} for {wsi_id} "
                    f"(original auto-selected level={initial_seg_level})"
                )
                break

        if len(coordinates) == 0:
            logger.error(
                f"No tissue coordinates found at any seg_level (0 to {initial_seg_level}) "
                f"for {wsi_id}. The slide may not contain detectable tissue."
            )

    # Save coordinates using original tiler (preserves original seg_level for cache consistency)
    tiler._save_coordinates(
        coordinates, coords_file,
        seg_params=seg_params, filter_params=filter_params
    )

    return coordinates, coords_file


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
        vis_level: Visualization level (-1 = auto select ~96x)
        line_thickness: Line thickness for drawing contours
        color: Color for tissue contours (RGB)
        hole_color: Color for hole contours (RGB)

    Returns:
        PIL Image with segmentation overlay
    """
    # Auto-select visualization level
    if vis_level < 0:
        target_downsample = 96
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


def safe_load_h5_coords(
    h5_path: Path,
    delete_if_corrupted: bool = True,
) -> Tuple[Optional[np.ndarray], Optional[Dict], Optional[str]]:
    """
    Safely load coordinates and attributes from an HDF5 file.

    This handles corrupted h5 files that may result from power loss or crashes
    during file writing.

    Args:
        h5_path: Path to the .h5 coordinates file
        delete_if_corrupted: If True, delete corrupted files automatically

    Returns:
        Tuple of (coords_array, attrs_dict, error_message)
        - On success: (coords_array, attrs_dict, None)
        - On failure: (None, None, error_message)

    The caller should handle the None case by recomputing coordinates.
    """
    import h5py

    if not h5_path.exists():
        return None, None, f"File does not exist: {h5_path}"

    try:
        with h5py.File(h5_path, 'r') as f:
            if 'coords' not in f:
                error_msg = f"No 'coords' dataset in {h5_path}"
                logger.warning(error_msg)
                if delete_if_corrupted:
                    _delete_corrupted_h5(h5_path)
                return None, None, error_msg

            coords_array = f['coords'][:]
            attrs = dict(f['coords'].attrs)
            return coords_array, attrs, None

    except OSError as e:
        # OSError covers HDF5 file corruption errors like:
        # - "Unable to open file" (truncated file)
        # - "file signature not found" (incomplete write)
        # - "Unable to read data" (corrupted data)
        error_msg = str(e)
        logger.warning(
            f"Detected corrupted H5 file (likely from power loss): {h5_path}. "
            f"Error: {error_msg}"
        )
        if delete_if_corrupted:
            _delete_corrupted_h5(h5_path)
        return None, None, f"Corrupted file (will recompute): {error_msg}"

    except Exception as e:
        # Other unexpected errors
        error_msg = str(e)
        logger.error(f"Failed to load H5 file {h5_path}: {error_msg}")
        return None, None, error_msg


def _delete_corrupted_h5(h5_path: Path) -> None:
    """Delete a corrupted H5 file and log the action."""
    try:
        h5_path.unlink()
        logger.info(f"Deleted corrupted H5 file: {h5_path}")
    except Exception as del_e:
        logger.error(f"Failed to delete corrupted H5 file {h5_path}: {del_e}")

