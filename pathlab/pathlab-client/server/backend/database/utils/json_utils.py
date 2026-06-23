"""
JSON Utilities - Helpers for JSON-safe data serialization

Provides functions to sanitize float values (nan, inf, -inf) and other
non-JSON-compliant values before serialization.

This is critical for training metrics which may contain nan/inf values
that would cause JSON serialization errors:
    ValueError: Out of range float values are not JSON compliant: nan

Usage:
    from backend.database.utils.json_utils import sanitize_for_json

    # Sanitize metadata before logging/storing
    metadata = {"loss": float('nan'), "lr": 0.001}
    safe_metadata = sanitize_for_json(metadata)
    # Result: {"loss": None, "lr": 0.001}
"""

import math
from typing import Any, Dict, List, Optional, Union


def sanitize_float(value: float, replace_with: Optional[float] = None) -> Optional[float]:
    """
    Sanitize a float value, replacing nan/inf/-inf with a safe value.

    Args:
        value: Float value to sanitize
        replace_with: Value to use for invalid floats (default: None)

    Returns:
        The original value if valid, or replace_with if nan/inf/-inf
    """
    if math.isnan(value) or math.isinf(value):
        return replace_with
    return value


def sanitize_for_json(data: Any, replace_with: Optional[float] = None) -> Any:
    """
    Recursively sanitize a data structure to be JSON-safe.

    Handles:
    - float nan, inf, -inf -> None (or replace_with)
    - numpy arrays -> lists (if numpy is available)
    - Nested dicts and lists

    Args:
        data: Any data structure (dict, list, scalar, etc.)
        replace_with: Value to use for invalid floats (default: None)

    Returns:
        JSON-safe version of the data
    """
    if data is None:
        return None

    # Handle numpy types if numpy is available
    try:
        import numpy as np
        if isinstance(data, np.ndarray):
            return sanitize_for_json(data.tolist(), replace_with)
        if isinstance(data, (np.floating, np.float16, np.float32, np.float64)):
            data = float(data)
        if isinstance(data, (np.integer, np.int8, np.int16, np.int32, np.int64, np.uint8, np.uint16, np.uint32, np.uint64)):
            return int(data)
        if isinstance(data, np.bool_):
            return bool(data)
    except ImportError:
        pass

    # Handle torch tensors if torch is available
    try:
        import torch
        if isinstance(data, torch.Tensor):
            return sanitize_for_json(data.detach().cpu().numpy().tolist(), replace_with)
    except ImportError:
        pass

    # Handle Python floats
    if isinstance(data, float):
        return sanitize_float(data, replace_with)

    # Handle dicts recursively
    if isinstance(data, dict):
        return {k: sanitize_for_json(v, replace_with) for k, v in data.items()}

    # Handle lists/tuples recursively
    if isinstance(data, (list, tuple)):
        sanitized = [sanitize_for_json(item, replace_with) for item in data]
        return sanitized if isinstance(data, list) else tuple(sanitized)

    # Other types (str, int, bool, None) are JSON-safe
    return data


def is_json_safe(data: Any) -> bool:
    """
    Check if data is safe for JSON serialization.

    Args:
        data: Any data structure

    Returns:
        True if data can be safely serialized to JSON
    """
    if data is None:
        return True

    if isinstance(data, float):
        return not (math.isnan(data) or math.isinf(data))

    if isinstance(data, (str, int, bool)):
        return True

    if isinstance(data, dict):
        return all(is_json_safe(v) for v in data.values())

    if isinstance(data, (list, tuple)):
        return all(is_json_safe(item) for item in data)

    # Check numpy types
    try:
        import numpy as np
        if isinstance(data, (np.floating, np.float16, np.float32, np.float64)):
            return not (np.isnan(data) or np.isinf(data))
        if isinstance(data, (np.integer, np.bool_)):
            return True
        if isinstance(data, np.ndarray):
            return not (np.any(np.isnan(data)) or np.any(np.isinf(data)))
    except ImportError:
        pass

    # Unknown types may not be safe
    return False

