"""
PathLab Feature Extraction Script
===================================

Extracts patch-level features from WSIs using PathLab's real pipeline:
  1. TissueSegmenter: CLAM-style HSV + Otsu + morphology → tissue contours
  2. WSITiler: Contour-based tiling with MPP-aware patch sizing → coords.h5
  3. WSIPatchDataset: Load patches by coordinates → DataLoader
  4. Extractor: Batch forward pass → features.pt

Code Agent can modify ANY part of this script.
Constraints (from skill definition):
  - Output convention: {output_dir}/pt_files/{extractor_name}/{wsi_id}.pt
  - Coordinates: {output_dir}/patches/{wsi_id}_coords.h5
  - Each feature tensor shape: (N_patches, D)
  - Save extraction_meta.json and metrics.json in output_dir

Reference:
  - common/preprocessing/tiling.py (TissueSegmenter + WSITiler)
  - common/preprocessing/coords_utils.py (coordinate caching)
  - common/dataset.py (WSIPatchDataset + build_dataloader)
  - common/extractors/ (20 pretrained extractors)
"""
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

# Disable cuDNN if driver version is incompatible (e.g., driver 570 + cu124)
try:
    torch.backends.cudnn.enabled = True
    # Quick test
    _ = torch.nn.functional.conv2d(
        torch.randn(1, 1, 3, 3, device="cuda"),
        torch.randn(1, 1, 2, 2, device="cuda"),
    )
except RuntimeError:
    torch.backends.cudnn.enabled = False

# ── Logging ──────────────────────────────────────────────────────
logger = logging.getLogger("extraction")
_log_handlers = [logging.StreamHandler(sys.stdout)]
_log_dir = os.getenv("OUTPUT_DIR", "/results")
try:
    Path(_log_dir).mkdir(parents=True, exist_ok=True)
    _log_handlers.append(logging.FileHandler(f"{_log_dir}/extraction.log"))
except OSError:
    pass
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", handlers=_log_handlers)


# ============================================================================
# Extractor — Code Agent can replace backbone, add multi-scale, etc.
# ============================================================================

DEFAULT_EXTRACTOR_NAME = "uni2"

_EXTRACTOR_ALIASES = {
    "UNI2": "uni2",
    "UNI": "uni",
    "CONCH": "conch",
    "CONCH15": "conch15",
    "CONCH 1.5": "conch15",
    "Virchow2": "virchow2",
    "Virchow": "virchow",
    "ResNet50": "resnet50",
}


def _normalize_extractor_name(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        return DEFAULT_EXTRACTOR_NAME
    return _EXTRACTOR_ALIASES.get(name, _EXTRACTOR_ALIASES.get(name.upper(), name))


def build_extractor(extractor_name=DEFAULT_EXTRACTOR_NAME, device="cuda"):
    """
    Build a feature extractor by name from PathLab's registry.

    Available: resnet50, vit_l_16, uni, uni2, conch, conch15, virchow, virchow2,
    plip, phikon, phikon2, patho_clip, openmidnight, H-Optimus-0/1, mSTAR, GPFM, etc.
    """
    try:
        from common.extractors import get_extractor, get_extractor_transforms
        model = get_extractor(extractor_name, pretrained=True)
        transforms = get_extractor_transforms(extractor_name, mode="eval")
        output_dim = model.output_dim
    except Exception as e:
        raise RuntimeError(
            f"Failed to load feature extractor '{extractor_name}': {e}. "
            "Refusing to fall back to ImageNet ResNet50 because that would "
            "produce mislabeled features. Configure the requested pathology "
            "foundation model checkpoint or set PATHSCIENTIST_FEATURE_EXTRACTOR "
            "explicitly."
        ) from e

    model = model.to(device).eval()
    return model, transforms, output_dim


# ============================================================================
# Hyperparameters — Code Agent can change any of these
# ============================================================================

EXTRACTOR_NAME = _normalize_extractor_name(
    os.getenv("PATHSCIENTIST_FEATURE_EXTRACTOR")
    or os.getenv("PATHLAB_EXTRACTOR")
    or DEFAULT_EXTRACTOR_NAME
)

# Segmentation parameters (PrePATH/CLAM TCGA preset)
SEG_PARAMS = {
    "seg_level": -1,       # Auto-select segmentation level
    "sthresh": 8,          # Binary threshold for tissue detection
    "mthresh": 7,          # Median blur kernel size
    "close": 4,            # Morphological closing kernel
    "use_otsu": True,      # Use Otsu threshold instead of binary
}

# Filter parameters (PrePATH/CLAM TCGA preset)
FILTER_PARAMS = {
    "a_t": 16,             # Min tissue area (in 512px² patch units)
    "a_h": 4,              # Min hole area
    "max_n_holes": 8,      # Max holes per contour
}

# Tiling parameters
PATCH_SIZE = 256           # Base patch size (auto-adjusted by MPP)
CONTOUR_FN = "four_pt"    # Tissue check: 'four_pt', 'center', 'basic'
USE_PADDING = True         # Allow edge patches

# Extraction parameters
BATCH_SIZE = 64            # Patches per GPU batch
NUM_WORKERS = 0            # DataLoader workers (0 = main process, avoids CUDA fork issues)
MIN_PATCHES = 10           # Skip WSIs with fewer patches
LEGACY_COORDS_SUBDIR = "h5_files"


def _coords_file(coords_dir: Path, wsi_id: str) -> Path:
    return Path(coords_dir) / f"{wsi_id}_coords.h5"


def _find_existing_coords(
    wsi_id: str,
    coords_dir: Path,
    legacy_coords_dir: Path,
) -> Optional[Path]:
    current = _coords_file(coords_dir, wsi_id)
    if current.exists():
        return current
    legacy = _coords_file(legacy_coords_dir, wsi_id)
    if legacy.exists():
        return legacy
    return None


def _copy_legacy_coords_if_needed(
    wsi_id: str,
    coords_dir: Path,
    legacy_coords_dir: Path,
) -> None:
    current = _coords_file(coords_dir, wsi_id)
    if current.exists():
        return
    legacy = _coords_file(legacy_coords_dir, wsi_id)
    if not legacy.exists():
        return
    try:
        current.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, current)
        logger.info(f"  Migrated legacy coordinates to {current}")
    except OSError as e:
        logger.warning(f"  Could not migrate legacy coordinates for {wsi_id}: {e}")


# ============================================================================
# Pipeline: WSI → coords.h5 → patches → features.pt
# ============================================================================

def tile_wsi(wsi_path: str, coords_dir: str, wsi_id: str) -> Optional[str]:
    """
    Step 1 & 2: Tissue segmentation + coordinate tiling.

    Uses PathLab's real TissueSegmenter (CLAM-style) and WSITiler.
    Returns path to coords.h5, or None if no tissue found.
    """
    from common.preprocessing.tiling import TissueSegmenter, WSITiler

    # Open slide
    try:
        from aslide import ASlide
        slide = ASlide(str(wsi_path))
        mpp = getattr(slide, "mpp", None)
    except ImportError:
        import openslide
        slide = openslide.OpenSlide(str(wsi_path))
        mpp_str = slide.properties.get("openslide.mpp-x")
        mpp = float(mpp_str) if mpp_str else None

    # Segment tissue
    segmenter = TissueSegmenter(
        seg_level=SEG_PARAMS["seg_level"],
        sthresh=SEG_PARAMS["sthresh"],
        mthresh=SEG_PARAMS["mthresh"],
        close=SEG_PARAMS["close"],
        use_otsu=SEG_PARAMS["use_otsu"],
        filter_params=FILTER_PARAMS,
    )

    # Tile
    tiler = WSITiler(
        patch_size=PATCH_SIZE,
        segmenter=segmenter,
        contour_fn=CONTOUR_FN,
        use_padding=USE_PADDING,
        native_mpp=mpp,
    )

    coords_path = Path(coords_dir) / f"{wsi_id}_coords.h5"
    Path(coords_dir).mkdir(parents=True, exist_ok=True)

    try:
        coords = tiler.compute_coordinates(
            slide,
            str(coords_path),
            seg_params=SEG_PARAMS,
            filter_params=FILTER_PARAMS,
        )
        if hasattr(slide, "close"):
            slide.close()

        if len(coords) < MIN_PATCHES:
            logger.warning(f"  Only {len(coords)} patches (min={MIN_PATCHES}), skipping")
            return None

        logger.info(f"  Tiled: {len(coords)} patches (mpp={mpp})")
        return str(coords_path)

    except Exception as e:
        logger.error(f"  Tiling failed: {e}")
        if hasattr(slide, "close"):
            slide.close()
        return None


@torch.no_grad()
def extract_wsi_features(
    wsi_path: str,
    coords_h5: str,
    extractor: nn.Module,
    transforms,
    output_dim: int,
    device: str = "cuda",
) -> Optional[torch.Tensor]:
    """
    Step 3 & 4: Load patches by coordinates → extract features.

    Uses PathLab's WSIPatchDataset for coordinate-based patch loading.
    """
    try:
        from common.dataset import WSIPatchDataset, build_dataloader
        loader, dataset = build_dataloader(
            wsi_path, coords_h5, extractor=extractor,
            batch_size=BATCH_SIZE, num_workers=NUM_WORKERS,
        )
    except Exception:
        # Fallback: manual loading
        loader = _manual_patch_loader(wsi_path, coords_h5, transforms, BATCH_SIZE)
        if loader is None:
            return None

    all_features = []
    for batch in loader:
        if isinstance(batch, tuple):
            imgs = batch[0]  # (imgs, coords) from WSIPatchDataset
        else:
            imgs = batch
        if imgs is None or len(imgs) == 0:
            continue
        imgs = imgs.to(device)
        features = extractor(imgs)  # (B, D)
        all_features.append(features.cpu())

    if not all_features:
        return None

    return torch.cat(all_features, dim=0)  # (N, D)


def _manual_patch_loader(wsi_path, coords_h5, transforms, batch_size):
    """Fallback patch loader if WSIPatchDataset is unavailable."""
    import h5py

    try:
        with h5py.File(coords_h5, "r") as f:
            coords = f["coords"][:]
            attrs = dict(f["coords"].attrs) if "coords" in f else dict(f.attrs)
    except Exception as e:
        logger.error(f"  Cannot read coords: {e}")
        return None

    read_size = int(attrs.get("read_size", attrs.get("patch_size", PATCH_SIZE)))

    try:
        from aslide import ASlide
        slide = ASlide(str(wsi_path))
    except ImportError:
        import openslide
        slide = openslide.OpenSlide(str(wsi_path))

    patches = []
    for x, y in coords:
        try:
            region = slide.read_region((int(x), int(y)), 0, (read_size, read_size))
            img = np.array(region)[:, :, :3]
            tensor = transforms(img)
            patches.append(tensor)
        except Exception:
            continue

    if hasattr(slide, "close"):
        slide.close()

    if not patches:
        return None

    # Simple batched iterator
    all_tensors = torch.stack(patches)
    return torch.split(all_tensors, batch_size)


# ============================================================================
# Main Pipeline
# ============================================================================

def extract():
    """
    Full extraction pipeline matching PathLab's real flow:
      WSI → TissueSegmenter → WSITiler → coords.h5 → WSIPatchDataset → Extractor → features.pt

    Output directory convention:
      {data_output}/pt_files/{extractor_name}/{wsi_id}.pt
      {data_output}/patches/{wsi_id}_coords.h5

    DATA_OUTPUT_DIR: stable user-visible path for feature/coord files.
    OUTPUT_DIR: per-run directory for metrics.json (used by the agent).
    """
    wsi_dir = os.getenv("WSI_DIR", "/data/WSIs")
    output_dir = os.getenv("OUTPUT_DIR", "/results")
    # DATA_OUTPUT_DIR is the stable path for actual data artifacts;
    # falls back to OUTPUT_DIR for backward compatibility.
    data_output = os.getenv("DATA_OUTPUT_DIR", output_dir)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Data artifacts go to DATA_OUTPUT_DIR (stable, user-visible)
    features_dir = Path(data_output) / "pt_files" / EXTRACTOR_NAME
    coords_dir = Path(data_output) / "patches"
    legacy_coords_dir = Path(data_output) / LEGACY_COORDS_SUBDIR

    features_dir.mkdir(parents=True, exist_ok=True)
    coords_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Extractor: {EXTRACTOR_NAME}")
    logger.info(f"Device: {device}")
    logger.info(f"Seg params: {SEG_PARAMS}")
    logger.info(f"Filter params: {FILTER_PARAMS}")

    # Find WSI files
    wsi_exts = {".svs", ".ndpi", ".tiff", ".tif", ".mrxs", ".scn", ".bif"}
    wsi_files = [f for f in Path(wsi_dir).iterdir() if f.suffix.lower() in wsi_exts]

    if not wsi_files:
        logger.warning(f"No WSI files found in {wsi_dir}")
        meta_dir = Path(output_dir).parent
        meta_dir.mkdir(parents=True, exist_ok=True)
        json.dump({"status": "no_files"}, open(str(meta_dir / "extraction_meta.json"), "w"))
        return

    logger.info(f"Found {len(wsi_files)} WSI files")

    # --- Early skip: check if all features and coordinates already exist ---
    wsi_ids = [f.stem for f in wsi_files]
    existing_features = [wid for wid in wsi_ids if (features_dir / f"{wid}.pt").exists()]
    existing_coords = [
        wid for wid in wsi_ids
        if _find_existing_coords(wid, coords_dir, legacy_coords_dir) is not None
    ]

    if len(existing_features) == len(wsi_files) and len(existing_coords) == len(wsi_files):
        logger.info(
            f"All {len(wsi_files)} WSIs already have features and coordinates — skipping extraction"
        )
        for wid in wsi_ids:
            _copy_legacy_coords_if_needed(wid, coords_dir, legacy_coords_dir)
        # Load patch counts from existing features for metrics
        total_patches = 0
        results = {}
        for wid in wsi_ids:
            feat = torch.load(features_dir / f"{wid}.pt", map_location="cpu", weights_only=True)
            n_patches = feat.shape[0]
            feat_dim = feat.shape[1]
            total_patches += n_patches
            results[wid] = {"status": "cached", "n_patches": n_patches, "feature_dim": feat_dim}

        meta = {
            "status": "completed",
            "extractor": EXTRACTOR_NAME,
            "output_dim": feat_dim,
            "total_wsi": len(wsi_files),
            "successful": len(wsi_files),
            "total_time": 0.0,
            "patches_extracted": total_patches,
            "features_dir": str(features_dir),
            "coords_dir": str(coords_dir),
            "legacy_coords_dir": str(legacy_coords_dir),
            "skipped": True,
            "results": results,
        }
        meta_path = str(Path(output_dir) / "extraction_meta.json")
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
        if data_output != output_dir:
            with open(str(Path(data_output) / "extraction_meta.json"), "w") as f:
                json.dump(meta, f, indent=2)
        metrics_path = str(Path(output_dir) / "metrics.json")
        with open(metrics_path, "w") as f:
            json.dump({"patches_extracted": float(total_patches), "status": "completed", "skipped": True}, f, indent=2)

        logger.info(f"Done (cached): {len(wsi_files)} WSIs, {total_patches} patches total")
        return

    if existing_features:
        logger.info(
            f"Partial cache: {len(existing_features)}/{len(wsi_files)} features, "
            f"{len(existing_coords)}/{len(wsi_files)} coords — extracting remaining"
        )

    # Build extractor
    extractor, transforms, output_dim = build_extractor(EXTRACTOR_NAME, device)
    params = sum(p.numel() for p in extractor.parameters())
    logger.info(f"Extractor: {params:,} params, dim={output_dim}")

    # Quick check mode: process only 1 WSI to validate pipeline works
    quick_check = os.getenv("PATHLAB_QUICK_CHECK", "") == "1"
    if quick_check:
        wsi_files = wsi_files[:1]
        logger.info("[QUICK CHECK] Processing only 1 WSI for validation")

    # Process each WSI
    results = {}
    start_time = time.time()

    for i, wsi_path in enumerate(wsi_files, 1):
        wsi_id = wsi_path.stem
        out_path = features_dir / f"{wsi_id}.pt"

        if out_path.exists():
            _copy_legacy_coords_if_needed(wsi_id, coords_dir, legacy_coords_dir)
            logger.info(f"[{i}/{len(wsi_files)}] {wsi_id} — cached")
            results[wsi_id] = {"status": "cached"}
            continue

        logger.info(f"[{i}/{len(wsi_files)}] {wsi_id}")
        t0 = time.time()

        # Step 1-2: Tile
        coords_h5 = tile_wsi(str(wsi_path), coords_dir, wsi_id)
        if not coords_h5:
            results[wsi_id] = {"status": "no_tissue"}
            continue

        # Step 3-4: Extract features
        features = extract_wsi_features(
            str(wsi_path), coords_h5, extractor, transforms, output_dim, device
        )

        dt = time.time() - t0

        if features is not None and features.shape[0] > 0:
            torch.save(features, out_path)
            results[wsi_id] = {
                "status": "success",
                "n_patches": features.shape[0],
                "feature_dim": features.shape[1],
                "duration": round(dt, 1),
            }
            logger.info(f"  → {features.shape[0]} patches, dim={features.shape[1]}, {dt:.1f}s")
        else:
            results[wsi_id] = {"status": "extraction_failed"}

    total_time = time.time() - start_time
    n_success = sum(1 for r in results.values() if r.get("status") == "success")

    total_patches = sum(
        r.get("n_patches", 0) for r in results.values() if r.get("status") == "success"
    )

    # Save metadata
    meta = {
        "status": "completed",
        "extractor": EXTRACTOR_NAME,
        "output_dim": output_dim,
        "total_wsi": len(wsi_files),
        "successful": n_success,
        "total_time": round(total_time, 1),
        "patches_extracted": total_patches,
        "features_dir": str(features_dir),
        "coords_dir": str(coords_dir),
        "legacy_coords_dir": str(legacy_coords_dir),
        "config": {
            "seg_params": SEG_PARAMS,
            "filter_params": FILTER_PARAMS,
            "patch_size": PATCH_SIZE,
            "contour_fn": CONTOUR_FN,
            "batch_size": BATCH_SIZE,
            "min_patches": MIN_PATCHES,
        },
        "results": results,
    }

    meta_path = str(Path(output_dir) / "extraction_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    # Also save extraction_meta to data output dir for user inspection
    if data_output != output_dir:
        data_meta_path = str(Path(data_output) / "extraction_meta.json")
        with open(data_meta_path, "w") as f:
            json.dump(meta, f, indent=2)

    # Also save metrics.json for code_agent to pick up
    metrics_path = str(Path(output_dir) / "metrics.json")
    with open(metrics_path, "w") as f:
        json.dump({"patches_extracted": float(total_patches), "status": "completed"}, f, indent=2)

    logger.info(f"Done: {n_success}/{len(wsi_files)} WSIs, {total_patches} patches, {total_time:.1f}s")
    logger.info(f"Features saved to: {features_dir}")


if __name__ == "__main__":
    extract()
