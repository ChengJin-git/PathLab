"""Bounded CPU-only region assistance; existing geometry is never changed implicitly."""

from collections import OrderedDict
import math
import threading
import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from backend.services.viewer_annotations import RegionGeometry


class AssistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    region: RegionGeometry
    method: Literal["wand", "grabcut", "scribble", "nuclei", "model"] = "grabcut"
    points: list[tuple[float, float, int]] = Field(default_factory=list, max_length=256)
    tolerance: int = Field(24, ge=1, le=100)
    model_id: str | None = None


_crops = OrderedDict()
_lock = threading.RLock()


def crop(slide, region):
    from pathlib import Path

    path = Path(slide.wsi_path)
    key = (
        str(path),
        path.stat().st_mtime_ns,
        region.x,
        region.y,
        region.width,
        region.height,
    )
    with _lock:
        if key in _crops:
            _crops.move_to_end(key)
            return _crops[key]
    if region.width > 16384 or region.height > 16384:
        raise ValueError("region_too_large")
    scale = min(1, 768 / max(region.width, region.height))
    width, height = (
        max(1, round(region.width * scale)),
        max(1, round(region.height * scale)),
    )
    if slide.data_type == "patch":
        with Image.open(path) as image:
            image = image.convert("RGB").crop(
                (region.x, region.y, region.x + region.width, region.y + region.height)
            )
            image = image.resize((width, height))
    else:
        from backend.common.slide_utils import load_slide

        source = load_slide(str(path))
        try:
            downsample = 1 / scale
            level = source.get_best_level_for_downsample(downsample)
            factor = source.level_downsamples[level]
            image = (
                source.read_region(
                    (int(region.x), int(region.y)),
                    level,
                    (
                        max(1, math.ceil(region.width / factor)),
                        max(1, math.ceil(region.height / factor)),
                    ),
                )
                .convert("RGB")
                .resize((width, height))
            )
        finally:
            source.close()
    result = np.asarray(image).copy(), region.width / width, region.height / height
    with _lock:
        _crops[key] = result
        while len(_crops) > 8:
            _crops.popitem(last=False)
    return result


def contours(mask, region, sx, sy):
    import cv2
    from shapely.geometry import Polygon

    found, hierarchy = cv2.findContours(
        mask.astype("uint8"), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )
    output = []
    if hierarchy is None:
        return output
    for index, contour in enumerate(found):
        if hierarchy[0, index, 3] != -1 or cv2.contourArea(contour) < 12:
            continue

        def points(shape):
            shape = cv2.approxPolyDP(shape, 1.2, True).reshape(-1, 2)
            return [
                [float(x * sx + region.x), float(y * sy + region.y)] for x, y in shape
            ]

        shell = points(contour)
        if len(shell) < 3:
            continue
        holes = []
        child = hierarchy[0, index, 2]
        while child != -1:
            hole = points(found[child])
            if len(hole) >= 3:
                holes.append(hole)
            child = hierarchy[0, child, 0]
        shape = Polygon(shell, holes)
        if not shape.is_valid:
            shape = shape.buffer(0)
        if shape.geom_type != "Polygon" or shape.is_empty:
            continue
        x, y, right, bottom = shape.bounds
        output.append(
            {
                "type": "polygon",
                "x": x,
                "y": y,
                "width": right - x,
                "height": bottom - y,
                "points": list(map(list, shape.exterior.coords))[:-1],
                "holes": [
                    list(map(list, ring.coords))[:-1] for ring in shape.interiors
                ],
            }
        )
    return sorted(output, key=lambda r: r["width"] * r["height"], reverse=True)[:100]


def assist(slide, body):
    import cv2

    image, sx, sy = crop(slide, body.region)
    height, width = image.shape[:2]
    if min(width, height) < 8:
        raise ValueError("region_too_small")
    points = [
        (
            min(width - 1, max(0, int((x - body.region.x) / sx))),
            min(height - 1, max(0, int((y - body.region.y) / sy))),
            int(label),
        )
        for x, y, label in body.points
    ]
    if any(label not in (0, 1) for _, _, label in points):
        raise ValueError("invalid_prompt")
    if body.method == "wand":
        seed = next(
            ((x, y) for x, y, label in points if label == 1), (width // 2, height // 2)
        )
        mask = np.zeros((height + 2, width + 2), np.uint8)
        cv2.floodFill(
            image.copy(),
            mask,
            seed,
            (0, 0, 0),
            (body.tolerance,) * 3,
            (body.tolerance,) * 3,
            cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE | (255 << 8),
        )
        mask = mask[1:-1, 1:-1] > 0
    elif body.method == "grabcut":
        mask = np.full((height, width), cv2.GC_PR_BGD, np.uint8)
        margin = max(1, min(width, height) // 12)
        mask[margin:-margin, margin:-margin] = cv2.GC_PR_FGD
        mask[[0, -1], :] = 0
        mask[:, [0, -1]] = 0
        for x, y, label in points:
            cv2.circle(mask, (x, y), 3, int(cv2.GC_FGD if label else cv2.GC_BGD), -1)
        cv2.grabCut(
            image,
            mask,
            None,
            np.zeros((1, 65)),
            np.zeros((1, 65)),
            3,
            cv2.GC_INIT_WITH_MASK,
        )
        mask = np.isin(mask, [cv2.GC_FGD, cv2.GC_PR_FGD])
    elif body.method == "scribble":
        if {p[2] for p in points} != {0, 1}:
            raise ValueError("need_positive_negative")
        from sklearn.ensemble import RandomForestClassifier

        colors = cv2.cvtColor(image, cv2.COLOR_RGB2LAB).astype("float32") / 255
        features = np.concatenate(
            [
                colors,
                cv2.GaussianBlur(colors, (0, 0), 2),
                cv2.GaussianBlur(colors, (0, 0), 5),
            ],
            axis=2,
        )
        labels = np.full((height, width), -1, np.int8)
        for x, y, label in points:
            cv2.circle(labels, (x, y), 4, label, -1)
        selected = labels >= 0
        classifier = RandomForestClassifier(
            n_estimators=24, max_depth=8, n_jobs=2, random_state=0
        )
        classifier.fit(features[selected], labels[selected])
        mask = classifier.predict(features.reshape(-1, 9)).reshape(height, width) > 0
    elif body.method == "nuclei":
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        _, mask = cv2.threshold(
            cv2.GaussianBlur(gray, (3, 3), 0),
            0,
            255,
            cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
        )
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    else:
        from .viewer_prompt_models import segment

        mask = segment(body.model_id, image, points)
    return {
        "regions": contours(mask, body.region, sx, sy),
        "method": body.method,
        "preview": True,
    }
