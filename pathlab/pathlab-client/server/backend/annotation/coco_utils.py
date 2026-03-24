"""
COCO annotation utilities for segmentation tasks.

Provides:
- ROI→COCO conversion: convert viewer annotation regions to COCO format
- Materialization: write COCO JSON from DB to disk for training consumption
"""

import copy
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Set

logger = logging.getLogger(__name__)


IMPORT_LABEL_COLORS = [
    "#ef4444",
    "#f97316",
    "#eab308",
    "#22c55e",
    "#06b6d4",
    "#3b82f6",
    "#8b5cf6",
    "#ec4899",
    "#14b8a6",
    "#a855f7",
    "#6366f1",
    "#0ea5e9",
    "#84cc16",
    "#d946ef",
    "#f43f5e",
]


def _normalize_file_key(file_name: Any) -> Optional[str]:
    if not file_name:
        return None
    normalized = Path(str(file_name)).name.strip().lower()
    return normalized or None


def _normalize_categories(categories: Any) -> Dict[int, str]:
    """Normalize COCO categories from either list or legacy dict format."""
    category_map: Dict[int, str] = {}

    if isinstance(categories, list):
        for item in categories:
            if not isinstance(item, dict):
                continue
            try:
                category_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            category_map[category_id] = str(item.get("name") or category_id)
        return category_map

    if isinstance(categories, dict):
        for key, value in categories.items():
            try:
                category_id = int(key)
            except (TypeError, ValueError):
                continue
            category_map[category_id] = str(value)

    return category_map


def _get_color_for_label(
    label: str,
    label_to_color: Dict[str, str],
    default_color: str,
) -> str:
    if label in label_to_color:
        return label_to_color[label]

    preferred_colors = [default_color] + [
        color for color in IMPORT_LABEL_COLORS if color != default_color
    ]
    used_colors = set(label_to_color.values())

    for color in preferred_colors:
        if color not in used_colors:
            label_to_color[label] = color
            return color

    fallback_colors = preferred_colors or [default_color]
    color = fallback_colors[len(label_to_color) % len(fallback_colors)]
    label_to_color[label] = color
    return color


def roi_annotations_to_coco(
    annotations_map: Dict[str, List[dict[str, Any]]],
    wsi_dimensions: Dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Convert viewer ROI annotations to COCO format.

    Args:
        annotations_map: { wsi_id: [{ type, x, y, width, height, label, color, points? }, ...] }
        wsi_dimensions: { wsi_id: { "width": int, "height": int, "file_name": str } }

    Returns:
        COCO-format dict: { "images": [...], "annotations": [...], "categories": [...] }
    """
    coco_images: List[dict[str, Any]] = []
    coco_annotations: List[dict[str, Any]] = []
    label_to_category_id: Dict[str, int] = {}
    image_id_counter = 0
    annotation_id_counter = 0

    for wsi_id, roi_list in annotations_map.items():
        dims = wsi_dimensions.get(wsi_id)
        if not dims:
            logger.warning(f"No dimensions found for WSI {wsi_id}, skipping")
            continue

        image_id_counter += 1
        coco_images.append(
            {
                "id": image_id_counter,
                "width": dims["width"],
                "height": dims["height"],
                "file_name": dims.get("file_name", f"{wsi_id}"),
            }
        )

        for roi in roi_list:
            label = roi.get("label", "unlabeled")
            if label not in label_to_category_id:
                label_to_category_id[label] = len(label_to_category_id)
            cat_id = label_to_category_id[label]

            annotation_id_counter += 1

            # Build segmentation polygon
            roi_type = roi.get("type", "rect")
            if roi_type == "polygon" and roi.get("points"):
                flat_points = []
                for pt in roi["points"]:
                    flat_points.extend(pt)
                segmentation = [flat_points]
            else:
                x = roi.get("x", 0)
                y = roi.get("y", 0)
                w = roi.get("width", 0)
                h = roi.get("height", 0)
                segmentation = [[x, y, x + w, y, x + w, y + h, x, y + h]]

            x = roi.get("x", 0)
            y = roi.get("y", 0)
            w = roi.get("width", 0)
            h = roi.get("height", 0)

            coco_annotations.append(
                {
                    "id": annotation_id_counter,
                    "image_id": image_id_counter,
                    "category_id": cat_id,
                    "segmentation": segmentation,
                    "bbox": [x, y, w, h],
                    "area": w * h,
                    "iscrowd": 0,
                }
            )

    # Build categories list (COCO standard format)
    categories = [
        {"id": cat_id, "name": label}
        for label, cat_id in sorted(label_to_category_id.items(), key=lambda x: x[1])
    ]

    return {
        "images": coco_images,
        "annotations": coco_annotations,
        "categories": categories,
    }


def merge_coco_datasets(coco_payloads: List[dict[str, Any]]) -> dict[str, Any]:
    """
    Merge one or more COCO payloads into a single normalized dataset.

    The merge is resilient to per-file imports where image/category IDs restart from 1.
    Categories are unified by category name and re-indexed to a stable global list.
    """
    merged_images: List[dict[str, Any]] = []
    merged_annotations: List[dict[str, Any]] = []
    category_name_to_id: Dict[str, int] = {}
    next_image_id = 1
    next_annotation_id = 1

    for payload in coco_payloads or []:
        if not isinstance(payload, dict):
            continue

        categories_map = _normalize_categories(payload.get("categories", []))
        for category_name in categories_map.values():
            if category_name not in category_name_to_id:
                category_name_to_id[category_name] = len(category_name_to_id)

        image_id_map: Dict[Any, int] = {}
        for image in payload.get("images") or []:
            if not isinstance(image, dict):
                continue

            old_image_id = image.get("id")
            if old_image_id is None:
                continue

            merged_image = copy.deepcopy(image)
            merged_image["id"] = next_image_id
            merged_images.append(merged_image)
            image_id_map[old_image_id] = next_image_id
            next_image_id += 1

        for annotation in payload.get("annotations") or []:
            if not isinstance(annotation, dict):
                continue

            mapped_image_id = image_id_map.get(annotation.get("image_id"))
            if mapped_image_id is None:
                continue

            category_id = annotation.get("category_id")
            try:
                category_id = int(category_id)
            except (TypeError, ValueError):
                pass

            category_name = categories_map.get(category_id, str(category_id))
            if category_name not in category_name_to_id:
                category_name_to_id[category_name] = len(category_name_to_id)

            merged_annotation = copy.deepcopy(annotation)
            merged_annotation["id"] = next_annotation_id
            merged_annotation["image_id"] = mapped_image_id
            merged_annotation["category_id"] = category_name_to_id[category_name]
            merged_annotations.append(merged_annotation)
            next_annotation_id += 1

    categories = [
        {"id": category_id, "name": category_name}
        for category_name, category_id in category_name_to_id.items()
    ]

    return {
        "images": merged_images,
        "annotations": merged_annotations,
        "categories": categories,
    }


def extract_coco_wsi_label_sets(
    coco_data: dict[str, Any],
    file_name_to_wsi_id: Dict[str, str],
    file_stem_to_wsi_id: Optional[Dict[str, str]] = None,
) -> Dict[str, Set[str]]:
    """
    Extract per-WSI multi-label category names from a COCO dataset.

    Returns a mapping of ``wsi_id -> {category_name, ...}``. Images with no
    annotations are intentionally omitted so callers can treat them as negatives.
    """
    if not isinstance(coco_data, dict):
        return {}

    categories = _normalize_categories(coco_data.get("categories", []))
    image_id_to_wsi_id: Dict[Any, str] = {}
    label_sets: Dict[str, Set[str]] = {}

    for image in coco_data.get("images") or []:
        if not isinstance(image, dict):
            continue

        normalized_name = _normalize_file_key(image.get("file_name"))
        if not normalized_name:
            continue

        wsi_id = file_name_to_wsi_id.get(normalized_name)
        if not wsi_id and file_stem_to_wsi_id:
            wsi_id = file_stem_to_wsi_id.get(Path(normalized_name).stem)
        if wsi_id:
            image_id_to_wsi_id[image.get("id")] = wsi_id

    for annotation in coco_data.get("annotations") or []:
        if not isinstance(annotation, dict):
            continue

        wsi_id = image_id_to_wsi_id.get(annotation.get("image_id"))
        if not wsi_id:
            continue

        category_id = annotation.get("category_id")
        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            pass

        label_name = categories.get(category_id, str(category_id))
        label_sets.setdefault(wsi_id, set()).add(label_name)

    return label_sets


def materialize_coco_to_disk(
    coco_data: dict[str, Any],
    output_path: Path,
) -> Path:
    """
    Write COCO JSON data from DB to disk for training consumption.

    Args:
        coco_data: COCO-format dict (from SegmentationAnnotation.annotations)
        output_path: Target file path (e.g., uploads/annotations/{dataset_id}_coco.json)

    Returns:
        The output_path written to.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(coco_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Materialized COCO JSON to {output_path}")
    return output_path


def coco_to_roi_annotations(
    coco_data: dict[str, Any],
    file_name_to_wsi_id: Dict[str, str],
    file_stem_to_wsi_id: Optional[Dict[str, str]] = None,
    default_color: str = "#3b82f6",
) -> Dict[str, List[dict[str, Any]]]:
    """
    Convert COCO annotations for a dataset into viewer ROI annotations.

    Args:
        coco_data: COCO dict with images / annotations / categories.
        file_name_to_wsi_id: Exact file-name lookup (normalized basename -> wsi_id).
        file_stem_to_wsi_id: Optional unique stem lookup for fallback matching.
        default_color: Default viewer color for imported GT labels.
    """
    if not isinstance(coco_data, dict):
        return {}

    categories = _normalize_categories(coco_data.get("categories", []))
    image_id_to_wsi_id: Dict[Any, str] = {}
    roi_map: Dict[str, List[dict[str, Any]]] = {}
    label_to_color: Dict[str, str] = {}

    for image in coco_data.get("images") or []:
        if not isinstance(image, dict):
            continue

        normalized_name = _normalize_file_key(image.get("file_name"))
        if not normalized_name:
            continue

        wsi_id = file_name_to_wsi_id.get(normalized_name)
        if not wsi_id and file_stem_to_wsi_id:
            wsi_id = file_stem_to_wsi_id.get(Path(normalized_name).stem)
        if wsi_id:
            image_id_to_wsi_id[image.get("id")] = wsi_id

    for annotation in coco_data.get("annotations") or []:
        if not isinstance(annotation, dict):
            continue

        wsi_id = image_id_to_wsi_id.get(annotation.get("image_id"))
        if not wsi_id:
            continue

        bbox = annotation.get("bbox") or []
        x = float(bbox[0]) if len(bbox) > 0 else 0.0
        y = float(bbox[1]) if len(bbox) > 1 else 0.0
        width = float(bbox[2]) if len(bbox) > 2 else 0.0
        height = float(bbox[3]) if len(bbox) > 3 else 0.0

        points: Optional[List[List[float]]] = None
        segmentation = annotation.get("segmentation") or []
        if isinstance(segmentation, list) and segmentation:
            polygon = segmentation[0]
            if isinstance(polygon, list) and len(polygon) >= 6:
                candidate_points: List[List[float]] = []
                for idx in range(0, len(polygon) - 1, 2):
                    candidate_points.append(
                        [float(polygon[idx]), float(polygon[idx + 1])]
                    )
                if len(candidate_points) >= 3:
                    points = candidate_points

        if points and (width <= 0 or height <= 0):
            xs = [pt[0] for pt in points]
            ys = [pt[1] for pt in points]
            x = min(xs)
            y = min(ys)
            width = max(xs) - x
            height = max(ys) - y

        category_id = annotation.get("category_id")
        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            pass
        fallback_label = category_id if category_id is not None else "unlabeled"
        label = categories.get(category_id, str(fallback_label))

        roi = {
            "id": f"{wsi_id}:{annotation.get('image_id')}:{annotation.get('id')}",
            "type": "polygon" if points else "rect",
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "label": label,
            "color": _get_color_for_label(label, label_to_color, default_color),
        }
        if points:
            roi["points"] = points

        roi_map.setdefault(wsi_id, []).append(roi)

    return roi_map
