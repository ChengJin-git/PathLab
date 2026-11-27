"""Helpers for cached WSI recommendation heatmap previews."""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from backend.common.file_types import is_patch_file
from backend.common.slide_utils import load_slide as _load_slide

from .coords_utils import safe_load_h5_coords, safe_load_h5_coords_attrs
from .heatmap_utils import handle_multi_class_attention, load_result_meta, normalize_attention

logger = logging.getLogger(__name__)

RECOMMENDATION_PREVIEW_MAX_SIZE = 256
RECOMMENDATION_OPACITY = 0.68
RECOMMENDATION_BLUR_SCALE = 0.6
RECOMMENDATION_CONTRAST_BOOST = 1.18
RECOMMENDATION_SATURATION_BOOST = 1.25


def _delete_preview_if_possible(preview_path: Path) -> None:
    try:
        preview_path.unlink()
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("Failed to delete recommendation preview cache %s: %s", preview_path, exc)


def _is_preview_cache_readable(preview_path: Path) -> bool:
    try:
        with Image.open(preview_path) as preview:
            preview.load()
        return True
    except Exception as exc:
        logger.warning("Unreadable recommendation preview cache %s, will regenerate: %s", preview_path, exc)
        _delete_preview_if_possible(preview_path)
        return False


def _save_preview_image(preview_image: Image.Image, preview_path: Path) -> None:
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    temp_preview_path = preview_path.with_name(f"{preview_path.name}.tmp")
    _delete_preview_if_possible(temp_preview_path)

    image_to_save = preview_image.copy()
    image_to_save.info.pop("icc_profile", None)

    try:
        image_to_save.save(temp_preview_path, format="PNG")
        temp_preview_path.replace(preview_path)
    except Exception:
        _delete_preview_if_possible(temp_preview_path)
        raise


def build_recommendation_preview_path(attention_file: Path, class_idx: Optional[int] = None) -> Path:
    class_suffix = f"_class_{class_idx}" if class_idx is not None else ""
    base_name = attention_file.stem.replace("_attention", "")
    return attention_file.with_name(f"{base_name}{class_suffix}_recommendation_preview.png")


def build_segmentation_recommendation_preview_path(mask_file: Path) -> Path:
    base_name = mask_file.stem.replace("_pred_mask", "")
    return mask_file.with_name(f"{base_name}_seg_recommendation_preview.png")


def build_patch_cam_recommendation_preview_path(cam_file: Path) -> Path:
    base_name = cam_file.stem.replace("_cam", "")
    return cam_file.with_name(f"{base_name}_cam_recommendation_preview.png")


def build_resized_recommendation_preview_path(preview_path: Path, size: int) -> Path:
    return preview_path.with_name(f"{preview_path.stem}_s{size}.png")


def ensure_resized_recommendation_preview_cache(
    preview_path: Path,
    size: Optional[int],
    *,
    overwrite: bool = False,
) -> Optional[Path]:
    if not preview_path.exists() or not _is_preview_cache_readable(preview_path):
        return None

    if size is None or size <= 0:
        return preview_path

    with Image.open(preview_path) as preview:
        source_width, source_height = preview.size

    if max(source_width, source_height) <= size:
        return preview_path

    resized_preview_path = build_resized_recommendation_preview_path(preview_path, size)
    if (
        resized_preview_path.exists()
        and not overwrite
        and resized_preview_path.stat().st_mtime >= preview_path.stat().st_mtime
    ):
        if _is_preview_cache_readable(resized_preview_path):
            return resized_preview_path

    try:
        with Image.open(preview_path) as preview:
            resized_preview = preview.copy()

        resized_preview.thumbnail((size, size), Image.Resampling.LANCZOS)
        _save_preview_image(resized_preview, resized_preview_path)
        return resized_preview_path
    except Exception as exc:
        logger.warning(
            "Failed to cache resized recommendation preview %s at size %s: %s",
            preview_path,
            size,
            exc,
        )
        return preview_path if preview_path.exists() else None


def _persist_wsi_metadata(metadata_file: Path, metadata: dict[str, Any]) -> None:
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    metadata_with_timestamp = {
        **metadata,
        "saved_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
    }
    metadata_file.write_text(
        json.dumps(metadata_with_timestamp, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_wsi_metadata(
    uploads_dir: Path,
    wsi_id: str,
    wsi_path: Optional[str | Path] = None,
    file_size: Optional[int] = None,
) -> dict[str, Any]:
    metadata_file = uploads_dir / "metadata" / f"{wsi_id}.json"
    metadata: dict[str, Any] = {}
    if metadata_file.exists():
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))

    resolved_wsi_path = str(wsi_path) if wsi_path else metadata.get("wsi_path")
    if not resolved_wsi_path:
        raise FileNotFoundError(f"WSI metadata not found: {metadata_file}")

    resolved_file_size = file_size if file_size is not None else metadata.get("file_size")
    resolved_path_obj = Path(resolved_wsi_path)
    if (resolved_file_size is None or int(resolved_file_size) <= 0) and resolved_path_obj.exists():
        resolved_file_size = resolved_path_obj.stat().st_size

    merged_metadata = {
        **metadata,
        "wsi_id": wsi_id,
        "wsi_path": resolved_wsi_path,
        "file_size": int(resolved_file_size or 0),
    }

    needs_persist = (
        not metadata_file.exists()
        or metadata.get("wsi_path") != merged_metadata["wsi_path"]
        or int(metadata.get("file_size") or 0) != merged_metadata["file_size"]
    )
    if needs_persist:
        try:
            _persist_wsi_metadata(metadata_file, merged_metadata)
        except Exception as exc:
            logger.warning("Failed to persist fallback metadata for %s: %s", wsi_id, exc)

    return merged_metadata


def _resolve_patch_size(uploads_dir: Path, wsi_id: str, preferred_patch_size: Optional[int]) -> int:
    from backend.ai.tasks.patch_cache import find_any_cached_coords_for_wsi

    if preferred_patch_size is not None:
        try:
            return max(1, int(preferred_patch_size))
        except (TypeError, ValueError):
            logger.warning("Invalid preferred patch_size for %s: %s", wsi_id, preferred_patch_size)

    coords_file = find_any_cached_coords_for_wsi(uploads_dir, wsi_id)
    if coords_file is None:
        return 512

    attrs, load_error = safe_load_h5_coords_attrs(coords_file, delete_if_corrupted=False)
    if attrs is None:
        logger.warning("Failed to load coords attrs for %s: %s", wsi_id, load_error)
        return 512

    raw_patch_size = attrs.get("patch_size")
    try:
        return max(1, int(raw_patch_size)) if raw_patch_size is not None else 512
    except (TypeError, ValueError):
        logger.warning("Invalid coords patch_size for %s: %s", wsi_id, raw_patch_size)
        return 512


def _load_patch_thumbnail(wsi_path: Path, size: int) -> tuple[Image.Image, int, int]:
    with Image.open(wsi_path) as img:
        slide_width, slide_height = img.size
        try:
            img.draft("RGB", (size, size))
        except Exception:
            pass

        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        return img.convert("RGB"), slide_width, slide_height


def _load_thumbnail_and_dims(wsi_path: Path, file_size: Optional[int], size: int) -> tuple[Image.Image, int, int]:
    if is_patch_file(str(wsi_path), file_size or wsi_path.stat().st_size):
        return _load_patch_thumbnail(wsi_path, size)

    slide = _load_slide(str(wsi_path))
    try:
        slide_width, slide_height = slide.level_dimensions[0]
        lowest_level = len(slide.level_dimensions) - 1
        region = slide.read_region((0, 0), lowest_level, slide.level_dimensions[lowest_level])
        thumbnail = region.convert("RGB")
        thumbnail.thumbnail((size, size), Image.Resampling.LANCZOS)
        return thumbnail, slide_width, slide_height
    finally:
        try:
            slide.close()
        except Exception:
            pass


def _weight_to_rgb(weight: float) -> tuple[int, int, int]:
    weight = max(0.0, min(1.0, float(weight)))
    if weight < 0.5:
        t = weight / 0.5
        return (
            int(59 + (255 - 59) * t),
            int(76 + (255 - 76) * t),
            int(192 + (255 - 192) * t),
        )
    t = (weight - 0.5) / 0.5
    return (255, int(255 * (1 - t)), int(255 * (1 - t * 0.8)))


def _get_blur_radius(patch_w: float, patch_h: float) -> float:
    patch_extent = max(1.0, min(float(patch_w), float(patch_h)))
    base_radius = (patch_extent / 2.0) * RECOMMENDATION_BLUR_SCALE
    if patch_extent <= 1.0:
        return 0.0
    if patch_extent <= 2.0:
        return min(0.35, base_radius)
    return max(0.45, base_radius * 0.7)


def _enhance_overlay(overlay: Image.Image) -> Image.Image:
    alpha_channel = overlay.getchannel("A")
    rgb_image = overlay.convert("RGB")
    rgb_image = ImageEnhance.Color(rgb_image).enhance(RECOMMENDATION_SATURATION_BOOST)
    rgb_image = ImageEnhance.Contrast(rgb_image).enhance(RECOMMENDATION_CONTRAST_BOOST)
    enhanced = rgb_image.convert("RGBA")
    enhanced.putalpha(alpha_channel)
    return enhanced


def render_recommendation_preview(
    wsi_id: str,
    attention_file: Path,
    uploads_dir: Path,
    patch_size: Optional[int] = None,
    class_idx: Optional[int] = None,
    size: int = RECOMMENDATION_PREVIEW_MAX_SIZE,
    wsi_path: Optional[str | Path] = None,
    file_size: Optional[int] = None,
) -> Image.Image:
    from backend.ai.tasks.patch_cache import find_any_cached_coords_for_wsi

    metadata = _load_wsi_metadata(uploads_dir, wsi_id, wsi_path=wsi_path, file_size=file_size)
    wsi_path = Path(metadata["wsi_path"])
    thumbnail, slide_width, slide_height = _load_thumbnail_and_dims(
        wsi_path,
        metadata.get("file_size"),
        size,
    )

    coords_file = find_any_cached_coords_for_wsi(uploads_dir, wsi_id)
    if coords_file is None:
        raise FileNotFoundError(f"Coordinates not found for {wsi_id}")

    coords, _, load_error = safe_load_h5_coords(coords_file, delete_if_corrupted=False)
    if coords is None:
        raise RuntimeError(f"Failed to load coordinates for {wsi_id}: {load_error}")

    attention = np.load(str(attention_file), allow_pickle=True)
    result_meta = load_result_meta(attention_file, "_attention.npy")
    attention, _ = handle_multi_class_attention(attention, result_meta, class_idx)

    if len(attention) != len(coords):
        min_len = min(len(attention), len(coords))
        attention = attention[:min_len]
        coords = coords[:min_len]

    attention_normalized, _ = normalize_attention(attention)
    resolved_patch_size = _resolve_patch_size(uploads_dir, wsi_id, patch_size)
    thumb_width, thumb_height = thumbnail.size
    scale_x = thumb_width / slide_width
    scale_y = thumb_height / slide_height
    patch_w = max(1e-6, resolved_patch_size * scale_x)
    patch_h = max(1e-6, resolved_patch_size * scale_y)

    heatmap_rgba = np.zeros((thumb_height, thumb_width, 4), dtype=np.uint8)
    for coord, weight in zip(coords, attention_normalized):
        x = max(0, int(math.floor(coord[0] * scale_x)))
        y = max(0, int(math.floor(coord[1] * scale_y)))
        x_end = min(thumb_width, int(math.ceil((coord[0] + resolved_patch_size) * scale_x)))
        y_end = min(thumb_height, int(math.ceil((coord[1] + resolved_patch_size) * scale_y)))
        if x_end <= x:
            x_end = min(thumb_width, x + 1)
        if y_end <= y:
            y_end = min(thumb_height, y + 1)
        if x < x_end and y < y_end:
            rgb = _weight_to_rgb(weight)
            heatmap_rgba[y:y_end, x:x_end, 0] = rgb[0]
            heatmap_rgba[y:y_end, x:x_end, 1] = rgb[1]
            heatmap_rgba[y:y_end, x:x_end, 2] = rgb[2]
            heatmap_rgba[y:y_end, x:x_end, 3] = 255

    overlay = Image.fromarray(heatmap_rgba, mode="RGBA")
    blur_radius = _get_blur_radius(patch_w, patch_h)
    if blur_radius > 0:
        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    overlay = _enhance_overlay(overlay)
    alpha_channel = overlay.getchannel("A").point(lambda value: int(value * RECOMMENDATION_OPACITY))
    overlay.putalpha(alpha_channel)
    return Image.alpha_composite(thumbnail.convert("RGBA"), overlay).convert("RGB")


def render_segmentation_recommendation_preview(
    wsi_id: str,
    mask_file: Path,
    uploads_dir: Path,
    seg_colors: list[tuple[int, int, int, int]],
    size: int = RECOMMENDATION_PREVIEW_MAX_SIZE,
    wsi_path: Optional[str | Path] = None,
    file_size: Optional[int] = None,
) -> Image.Image:
    metadata = _load_wsi_metadata(uploads_dir, wsi_id, wsi_path=wsi_path, file_size=file_size)
    resolved_wsi_path = Path(metadata["wsi_path"])
    thumbnail, _, _ = _load_thumbnail_and_dims(
        resolved_wsi_path,
        metadata.get("file_size"),
        size,
    )

    mask = np.load(str(mask_file), allow_pickle=True)
    mask = (mask > 0).astype(np.uint8, copy=False)

    target_w, target_h = thumbnail.size
    overlay = np.zeros((target_h, target_w, 4), dtype=np.uint8)

    if mask.ndim == 3:
        for class_idx in range(mask.shape[0]):
            color = seg_colors[class_idx % len(seg_colors)]
            class_mask = Image.fromarray((mask[class_idx] * 255).astype(np.uint8), mode="L")
            class_mask = class_mask.resize((target_w, target_h), Image.Resampling.NEAREST)
            class_arr = np.array(class_mask) > 127
            for channel_idx in range(4):
                overlay[:, :, channel_idx][class_arr] = color[channel_idx]
    elif mask.ndim == 2:
        color = seg_colors[0]
        class_mask = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
        class_mask = class_mask.resize((target_w, target_h), Image.Resampling.NEAREST)
        class_arr = np.array(class_mask) > 127
        for channel_idx in range(4):
            overlay[:, :, channel_idx][class_arr] = color[channel_idx]
    else:
        raise ValueError(f"Unexpected segmentation mask ndim: {mask.ndim}")

    overlay_img = Image.fromarray(overlay, mode="RGBA")
    return Image.alpha_composite(thumbnail.convert("RGBA"), overlay_img).convert("RGB")


def render_patch_cam_recommendation_preview(
    wsi_id: str,
    cam_file: Path,
    uploads_dir: Path,
    size: int = RECOMMENDATION_PREVIEW_MAX_SIZE,
    wsi_path: Optional[str | Path] = None,
    file_size: Optional[int] = None,
) -> Image.Image:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import colormaps

    metadata = _load_wsi_metadata(uploads_dir, wsi_id, wsi_path=wsi_path, file_size=file_size)
    resolved_wsi_path = Path(metadata["wsi_path"])
    thumbnail, _, _ = _load_thumbnail_and_dims(
        resolved_wsi_path,
        metadata.get("file_size"),
        size,
    )

    cam = np.load(str(cam_file), allow_pickle=True)
    if cam.max() > cam.min():
        cam_normalized = (cam - cam.min()) / (cam.max() - cam.min())
    else:
        cam_normalized = np.zeros_like(cam)

    colormap = colormaps["jet"]
    colored_cam = colormap(cam_normalized)
    colored_cam_uint8 = (colored_cam * 255).astype(np.uint8)
    colored_cam_uint8[:, :, 3] = int(round(255 * RECOMMENDATION_OPACITY))

    target_w, target_h = thumbnail.size
    cam_image = Image.fromarray(colored_cam_uint8, mode="RGBA")
    cam_image = cam_image.resize((target_w, target_h), Image.Resampling.BILINEAR)

    blur_radius = max(1.0, (target_w / 50.0) * RECOMMENDATION_BLUR_SCALE)
    cam_image = cam_image.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    cam_image = _enhance_overlay(cam_image)

    return Image.alpha_composite(thumbnail.convert("RGBA"), cam_image).convert("RGB")


def ensure_recommendation_preview_cache(
    wsi_id: str,
    attention_file: Path,
    uploads_dir: Path,
    patch_size: Optional[int] = None,
    class_idx: Optional[int] = None,
    overwrite: bool = False,
    wsi_path: Optional[str | Path] = None,
    file_size: Optional[int] = None,
) -> Optional[Path]:
    preview_path = build_recommendation_preview_path(attention_file, class_idx)
    if (
        preview_path.exists()
        and not overwrite
        and preview_path.stat().st_mtime >= attention_file.stat().st_mtime
    ):
        if _is_preview_cache_readable(preview_path):
            return preview_path

    try:
        preview_image = render_recommendation_preview(
            wsi_id,
            attention_file,
            uploads_dir,
            patch_size=patch_size,
            class_idx=class_idx,
            wsi_path=wsi_path,
            file_size=file_size,
        )
        _save_preview_image(preview_image, preview_path)
        return preview_path
    except Exception as exc:
        logger.warning("Failed to cache recommendation preview for %s from %s: %s", wsi_id, attention_file, exc)
        return None


def ensure_segmentation_recommendation_preview_cache(
    wsi_id: str,
    mask_file: Path,
    uploads_dir: Path,
    seg_colors: list[tuple[int, int, int, int]],
    overwrite: bool = False,
    wsi_path: Optional[str | Path] = None,
    file_size: Optional[int] = None,
) -> Optional[Path]:
    preview_path = build_segmentation_recommendation_preview_path(mask_file)
    if (
        preview_path.exists()
        and not overwrite
        and preview_path.stat().st_mtime >= mask_file.stat().st_mtime
    ):
        if _is_preview_cache_readable(preview_path):
            return preview_path

    try:
        preview_image = render_segmentation_recommendation_preview(
            wsi_id,
            mask_file,
            uploads_dir,
            seg_colors=seg_colors,
            wsi_path=wsi_path,
            file_size=file_size,
        )
        _save_preview_image(preview_image, preview_path)
        return preview_path
    except Exception as exc:
        logger.warning(
            "Failed to cache segmentation recommendation preview for %s from %s: %s",
            wsi_id,
            mask_file,
            exc,
        )
        return None


def ensure_patch_cam_recommendation_preview_cache(
    wsi_id: str,
    cam_file: Path,
    uploads_dir: Path,
    overwrite: bool = False,
    wsi_path: Optional[str | Path] = None,
    file_size: Optional[int] = None,
) -> Optional[Path]:
    preview_path = build_patch_cam_recommendation_preview_path(cam_file)
    if (
        preview_path.exists()
        and not overwrite
        and preview_path.stat().st_mtime >= cam_file.stat().st_mtime
    ):
        if _is_preview_cache_readable(preview_path):
            return preview_path

    try:
        preview_image = render_patch_cam_recommendation_preview(
            wsi_id,
            cam_file,
            uploads_dir,
            wsi_path=wsi_path,
            file_size=file_size,
        )
        _save_preview_image(preview_image, preview_path)
        return preview_path
    except Exception as exc:
        logger.warning(
            "Failed to cache patch CAM recommendation preview for %s from %s: %s",
            wsi_id,
            cam_file,
            exc,
        )
        return None
