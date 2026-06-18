from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import torch.nn as nn

WSI_EXTS = {".svs", ".ndpi", ".tiff", ".tif", ".mrxs", ".scn", ".bif"}
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

SEG_PARAMS = {
    "seg_level": -1,
    "sthresh": 8,
    "mthresh": 7,
    "close": 4,
    "use_otsu": True,
}

FILTER_PARAMS = {
    "a_t": 16,
    "a_h": 4,
    "max_n_holes": 8,
}

PATCH_SIZE = 256
CONTOUR_FN = "four_pt"
USE_PADDING = True
MIN_PATCHES = 10


def compute_pathlab_params_hash(
    *,
    level: int = 0,
    seg_params: dict | None = None,
    filter_params: dict | None = None,
    contour_fn: str = CONTOUR_FN,
    use_padding: bool = USE_PADDING,
    seg_level: int = SEG_PARAMS["seg_level"],
) -> str:
    """Match PathLab's feature_cache.compute_params_hash convention."""
    seg_params = seg_params or SEG_PARAMS
    filter_params = filter_params or FILTER_PARAMS
    params = {
        "level": level,
        "contour_fn": contour_fn,
        "use_padding": use_padding,
        "seg_level": seg_level,
        "sthresh": seg_params.get("sthresh", 8),
        "mthresh": seg_params.get("mthresh", 7),
        "close": seg_params.get("close", 4),
        "use_otsu": seg_params.get("use_otsu", True),
        "a_t": filter_params.get("a_t", 16),
        "a_h": filter_params.get("a_h", 4),
        "max_n_holes": filter_params.get("max_n_holes", 8),
    }
    params_str = json.dumps(params, sort_keys=True)
    return hashlib.md5(params_str.encode()).hexdigest()[:8]


def _uses_pathlab_uploads_layout(data_output: Path, wsi_dir: Path) -> bool:
    if os.getenv("PATHSCIENTIST_PATHLAB_UPLOADS_LAYOUT", "").lower() in {"1", "true", "yes"}:
        return True
    if (data_output / "wsi_files").is_dir():
        return True
    return wsi_dir.name == "wsi_files" and wsi_dir.parent == data_output


def _artifact_dirs(data_output: Path, wsi_dir: Path, extractor_name: str) -> tuple[Path, Path]:
    if _uses_pathlab_uploads_layout(data_output, wsi_dir):
        params_hash = compute_pathlab_params_hash()
        return (
            data_output / "features" / extractor_name / params_hash,
            data_output / "coordinates" / params_hash,
        )
    return data_output / "pt_files" / extractor_name, data_output / "patches"


def _pathlab_task_features_dir(data_output: Path, wsi_dir: Path) -> Path | None:
    if not _uses_pathlab_uploads_layout(data_output, wsi_dir):
        return None
    task_id = (
        os.getenv("PATHSCIENTIST_PATHLAB_TRAINING_TASK_ID", "").strip()
        or os.getenv("PATHSCIENTIST_TRAINING_TASK_ID", "").strip()
        or os.getenv("PATHLAB_TRAINING_TASK_ID", "").strip()
    )
    if not task_id or "/" in task_id or "\\" in task_id or task_id in {".", ".."}:
        return None
    return data_output / "training" / task_id / "features"


def _link_task_feature(
    task_features_dir: Path | None,
    wsi_id: str,
    cached_features_path: Path,
) -> Path | None:
    if task_features_dir is None:
        return None
    if not cached_features_path.exists():
        return None
    task_features_dir.mkdir(parents=True, exist_ok=True)
    link_path = task_features_dir / f"{wsi_id}.pt"
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    try:
        rel_path = os.path.relpath(cached_features_path, task_features_dir)
        link_path.symlink_to(rel_path)
    except OSError:
        link_path.symlink_to(cached_features_path)
    return link_path


def _is_quick_check() -> bool:
    keys = ("QUICK_CHECK", "PATHSCIENTIST_QUICK_CHECK", "PATHLAB_QUICK_CHECK")
    return any(os.getenv(key, "").lower() in {"1", "true", "yes"} for key in keys)


def atomic_torch_save(tensor, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    torch.save(tensor, tmp)
    os.replace(tmp, path)


def atomic_json_dump(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def atomic_bytes_write(payload: bytes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rank", type=int, required=True)
    parser.add_argument("--world-size", type=int, required=True)
    parser.add_argument("--wsi-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--data-output-dir", required=True)
    parser.add_argument(
        "--extractor",
        default=os.getenv("PATHSCIENTIST_FEATURE_EXTRACTOR", DEFAULT_EXTRACTOR_NAME),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("PATHSCIENTIST_FEATURE_BATCH_SIZE", "64")),
    )
    return parser.parse_args()


def _normalize_extractor_name(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        return DEFAULT_EXTRACTOR_NAME
    return _EXTRACTOR_ALIASES.get(name, _EXTRACTOR_ALIASES.get(name.upper(), name))


def build_extractor(extractor_name=DEFAULT_EXTRACTOR_NAME, device="cuda"):
    try:
        from common.extractors import get_extractor, get_extractor_transforms
        model = get_extractor(extractor_name, pretrained=True)
        transforms = get_extractor_transforms(extractor_name, mode="eval")
        output_dim = model.output_dim
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load feature extractor '{extractor_name}': {exc}. "
            "Refusing to fall back to ImageNet ResNet50 because that would "
            "produce mislabeled features. Configure the requested pathology "
            "foundation model checkpoint or set PATHSCIENTIST_FEATURE_EXTRACTOR explicitly."
        ) from exc
    model = model.to(device).eval()
    return model, transforms, output_dim


def _pil_open(path: str):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    return Image.open(path).convert("RGB")


def _write_coords_h5(coords: np.ndarray, path: Path, *, source: str) -> None:
    import h5py

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.stem}.tmp{path.suffix}")
    with h5py.File(tmp, "w") as f:
        dset = f.create_dataset("coords", data=coords.astype(np.int64))
        dset.attrs["patch_size"] = PATCH_SIZE
        dset.attrs["read_size"] = PATCH_SIZE
        dset.attrs["source"] = source
        f.attrs["patch_size"] = PATCH_SIZE
        f.attrs["read_size"] = PATCH_SIZE
    os.replace(tmp, path)


def _tile_wsi_with_pil(wsi_path: str, coords_path: Path) -> Optional[str]:
    img = _pil_open(wsi_path)
    width, height = img.size
    thumb_w = max(1, min(1024, width // PATCH_SIZE))
    thumb_h = max(1, int(round(height * thumb_w / width)))
    thumb = img.resize((thumb_w, thumb_h))
    arr = np.asarray(thumb)
    tissue = (arr.mean(axis=2) < 230) & (arr.mean(axis=2) > 20)
    coords = []
    for y in range(0, max(1, height - PATCH_SIZE + 1), PATCH_SIZE):
        y0 = int(y * thumb_h / height)
        y1 = max(y0 + 1, int((y + PATCH_SIZE) * thumb_h / height))
        for x in range(0, max(1, width - PATCH_SIZE + 1), PATCH_SIZE):
            x0 = int(x * thumb_w / width)
            x1 = max(x0 + 1, int((x + PATCH_SIZE) * thumb_w / width))
            if tissue[y0:y1, x0:x1].mean() >= 0.15:
                coords.append((x, y))
    img.close()
    if len(coords) < MIN_PATCHES:
        return None
    _write_coords_h5(np.asarray(coords), coords_path, source="pil_thumbnail_fallback")
    return str(coords_path)


def tile_wsi(wsi_path: str, coords_dir: str, wsi_id: str) -> Optional[str]:
    from common.preprocessing.tiling import TissueSegmenter, WSITiler

    coords_path = Path(coords_dir) / f"{wsi_id}_coords.h5"
    tmp_coords_path = coords_path.with_name(f"{coords_path.stem}.tmp{coords_path.suffix}")
    coords_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        try:
            from aslide import ASlide
            slide = ASlide(str(wsi_path))
            mpp = getattr(slide, "mpp", None)
        except ImportError:
            import openslide
            slide = openslide.OpenSlide(str(wsi_path))
            mpp_str = slide.properties.get("openslide.mpp-x")
            mpp = float(mpp_str) if mpp_str else None
    except Exception:
        try:
            return _tile_wsi_with_pil(wsi_path, coords_path)
        except Exception:
            return None

    segmenter = TissueSegmenter(
        seg_level=SEG_PARAMS["seg_level"],
        sthresh=SEG_PARAMS["sthresh"],
        mthresh=SEG_PARAMS["mthresh"],
        close=SEG_PARAMS["close"],
        use_otsu=SEG_PARAMS["use_otsu"],
        filter_params=FILTER_PARAMS,
    )
    tiler = WSITiler(
        patch_size=PATCH_SIZE,
        segmenter=segmenter,
        contour_fn=CONTOUR_FN,
        use_padding=USE_PADDING,
        native_mpp=mpp,
    )

    try:
        coords = tiler.compute_coordinates(
            slide,
            str(tmp_coords_path),
            seg_params=SEG_PARAMS,
            filter_params=FILTER_PARAMS,
        )
        if hasattr(slide, "close"):
            slide.close()
        if len(coords) < MIN_PATCHES:
            tmp_coords_path.unlink(missing_ok=True)
            return None
        os.replace(tmp_coords_path, coords_path)
        return str(coords_path)
    except Exception:
        if hasattr(slide, "close"):
            slide.close()
        tmp_coords_path.unlink(missing_ok=True)
        try:
            return _tile_wsi_with_pil(wsi_path, coords_path)
        except Exception:
            return None


@torch.no_grad()
def extract_wsi_features(
    wsi_path: str,
    coords_h5: str,
    extractor: nn.Module,
    transforms,
    output_dim: int,
    device: str = "cuda",
    batch_size: int = 64,
    patch_errors: list[str] | None = None,
) -> Optional[torch.Tensor]:
    loader = _manual_patch_loader(
        wsi_path, coords_h5, transforms, batch_size, patch_errors=patch_errors
    )
    if loader is None:
        return None

    all_features = []
    for batch in loader:
        imgs = batch[0] if isinstance(batch, tuple) else batch
        if imgs is None or len(imgs) == 0:
            continue
        imgs = imgs.to(device)
        features = extractor(imgs)
        all_features.append(features.cpu())
    if not all_features:
        return None
    return torch.cat(all_features, dim=0)


def _manual_patch_loader(wsi_path, coords_h5, transforms, batch_size, patch_errors=None):
    import h5py

    patch_errors = patch_errors if patch_errors is not None else []
    try:
        with h5py.File(coords_h5, "r") as f:
            coords = f["coords"][:]
            attrs = dict(f["coords"].attrs) if "coords" in f else dict(f.attrs)
    except Exception as exc:
        patch_errors.append(f"coords_read_failed: {type(exc).__name__}: {exc}")
        return None

    read_size = int(attrs.get("read_size", attrs.get("patch_size", PATCH_SIZE)))
    try:
        try:
            from aslide import ASlide
            slide = ASlide(str(wsi_path))
        except ImportError:
            import openslide
            slide = openslide.OpenSlide(str(wsi_path))
        use_pil = False
    except Exception:
        try:
            slide = _pil_open(wsi_path)
            use_pil = True
        except Exception as exc:
            patch_errors.append(f"manual_loader_failed: {type(exc).__name__}: {exc}")
            return None

    patches = []
    for x, y in coords:
        try:
            if use_pil:
                region = slide.crop((int(x), int(y), int(x) + read_size, int(y) + read_size))
            else:
                region = slide.read_region((int(x), int(y)), 0, (read_size, read_size))
            patches.append(transforms(region.convert("RGB")))
        except Exception as exc:
            if len(patch_errors) < 5:
                patch_errors.append(
                    f"patch_failed@{int(x)},{int(y)}: {type(exc).__name__}: {exc}"
                )
            continue
    if hasattr(slide, "close"):
        slide.close()
    if not patches:
        return None
    return torch.split(torch.stack(patches), batch_size)


def _write_worker_payload(
    *,
    args,
    extractor_name: str,
    device: str,
    assigned: list[Path],
    features_dir: Path,
    coords_dir: Path,
    task_features_dir: Path | None,
    meta_dir: Path,
    results: dict,
    total_patches: int,
    start: float,
) -> None:
    payload = {
        "rank": args.rank,
        "world_size": args.world_size,
        "extractor": extractor_name,
        "device": device,
        "total_assigned": len(assigned),
        "successful": sum(1 for r in results.values() if r.get("status") in {"success", "cached"}),
        "patches_extracted": total_patches,
        "duration": round(time.time() - start, 1),
        "features_dir": str(features_dir),
        "coords_dir": str(coords_dir),
        "results": results,
    }
    if task_features_dir is not None:
        payload["task_features_dir"] = str(task_features_dir)
    atomic_json_dump(payload, meta_dir / f"worker_{args.rank}.json")


def main() -> None:
    args = parse_args()
    start = time.time()
    wsi_dir = Path(args.wsi_dir)
    data_output = Path(args.data_output_dir)
    output_dir = Path(args.output_dir)
    extractor_name = _normalize_extractor_name(args.extractor)
    features_dir, coords_dir = _artifact_dirs(data_output, wsi_dir, extractor_name)
    task_features_dir = _pathlab_task_features_dir(data_output, wsi_dir)
    meta_dir = output_dir / "worker_meta"
    device = "cuda" if torch.cuda.is_available() else "cpu"

    features_dir.mkdir(parents=True, exist_ok=True)
    coords_dir.mkdir(parents=True, exist_ok=True)
    if task_features_dir is not None:
        task_features_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    wsi_files = sorted(p for p in wsi_dir.iterdir() if p.suffix.lower() in WSI_EXTS)
    if _is_quick_check():
        limit = int(os.getenv("PATHSCIENTIST_QUICK_CHECK_WSI_LIMIT", "2"))
        wsi_files = wsi_files[: max(1, limit)]
    assigned = wsi_files[args.rank::args.world_size]
    results = {}
    total_patches = 0

    if os.getenv("PATHSCIENTIST_FAKE_FEATURE_EXTRACTION", "") == "1":
        for wsi_path in assigned:
            wsi_id = wsi_path.stem
            coords_path = coords_dir / f"{wsi_id}_coords.h5"
            atomic_bytes_write(b"fake h5", coords_path)
            feature = torch.zeros((3, 8), dtype=torch.float32)
            out_path = features_dir / f"{wsi_id}.pt"
            atomic_torch_save(feature, out_path)
            _link_task_feature(task_features_dir, wsi_id, out_path)
            total_patches += 3
            results[wsi_id] = {"status": "success", "n_patches": 3, "feature_dim": 8}
        _write_worker_payload(
            args=args,
            extractor_name=extractor_name,
            device=device,
            assigned=assigned,
            features_dir=features_dir,
            coords_dir=coords_dir,
            task_features_dir=task_features_dir,
            meta_dir=meta_dir,
            results=results,
            total_patches=total_patches,
            start=start,
        )
        return

    if not assigned:
        _write_worker_payload(
            args=args,
            extractor_name=extractor_name,
            device=device,
            assigned=assigned,
            features_dir=features_dir,
            coords_dir=coords_dir,
            task_features_dir=task_features_dir,
            meta_dir=meta_dir,
            results=results,
            total_patches=total_patches,
            start=start,
        )
        return

    extractor, transforms, output_dim = build_extractor(extractor_name, device)

    for wsi_path in assigned:
        wsi_id = wsi_path.stem
        out_path = features_dir / f"{wsi_id}.pt"
        if out_path.exists():
            _link_task_feature(task_features_dir, wsi_id, out_path)
            try:
                feat = torch.load(out_path, map_location="cpu", weights_only=True)
                total_patches += int(feat.shape[0])
                results[wsi_id] = {
                    "status": "cached",
                    "n_patches": int(feat.shape[0]),
                    "feature_dim": int(feat.shape[1]),
                }
            except Exception:
                results[wsi_id] = {"status": "cached"}
            continue

        coords_h5 = str(coords_dir / f"{wsi_id}_coords.h5")
        if not Path(coords_h5).exists():
            coords_h5 = tile_wsi(str(wsi_path), str(coords_dir), wsi_id) or ""
        if not coords_h5:
            results[wsi_id] = {"status": "no_tissue"}
            continue

        patch_errors: list[str] = []
        try:
            features = extract_wsi_features(
                str(wsi_path),
                coords_h5,
                extractor,
                transforms,
                output_dim,
                device,
                args.batch_size,
                patch_errors=patch_errors,
            )
        except Exception as exc:
            results[wsi_id] = {
                "status": "extraction_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "patch_errors": patch_errors[:5],
            }
            continue
        if features is None or features.shape[0] == 0:
            results[wsi_id] = {
                "status": "extraction_failed",
                "error": "no_features",
                "patch_errors": patch_errors[:5],
            }
            continue

        atomic_torch_save(features, out_path)
        _link_task_feature(task_features_dir, wsi_id, out_path)
        total_patches += int(features.shape[0])
        results[wsi_id] = {
            "status": "success",
            "n_patches": int(features.shape[0]),
            "feature_dim": int(features.shape[1]),
        }

    _write_worker_payload(
        args=args,
        extractor_name=extractor_name,
        device=device,
        assigned=assigned,
        features_dir=features_dir,
        coords_dir=coords_dir,
        task_features_dir=task_features_dir,
        meta_dir=meta_dir,
        results=results,
        total_patches=total_patches,
        start=start,
    )


if __name__ == "__main__":
    main()
