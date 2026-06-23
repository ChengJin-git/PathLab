"""Shared coordinate/feature cache key helpers."""

import hashlib
import json
from typing import Any, Optional


def compute_params_hash(
    level: int = 0,
    seg_params: Optional[dict[str, Any]] = None,
    filter_params: Optional[dict[str, Any]] = None,
    contour_fn: str = "four_pt",
    use_padding: bool = True,
    seg_level: int = -1,
) -> str:
    """Compute the stable cache key for preprocessing parameters.

    Patch geometry is intentionally absent because PathLab derives it from each
    slide's magnification/MPP instead of accepting caller-supplied dimensions.
    """
    seg_params = seg_params or {}
    filter_params = filter_params or {}

    params = {
        "level": level,
        "contour_fn": contour_fn,
        "use_padding": use_padding,
        "seg_level": seg_level,
        "sthresh": seg_params.get("sthresh", 5),
        "mthresh": seg_params.get("mthresh", 7),
        "close": seg_params.get("close", 4),
        "use_otsu": seg_params.get("use_otsu", False),
        "a_t": filter_params.get("a_t", 100),
        "a_h": filter_params.get("a_h", 16),
        "max_n_holes": filter_params.get("max_n_holes", 8),
    }

    params_str = json.dumps(params, sort_keys=True)
    return hashlib.md5(params_str.encode()).hexdigest()[:8]
