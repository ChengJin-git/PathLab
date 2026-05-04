"""Small JSON-safety helpers for collector payloads."""

from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    return str(value)


def as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return jsonable(value)
    return {}


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return jsonable(value)
    if isinstance(value, tuple):
        return jsonable(list(value))
    return []
