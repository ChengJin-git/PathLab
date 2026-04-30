import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np


def build_legacy_ai_result_fixtures(
    uploads_dir: Path, task_id: str = "task-101"
) -> dict[str, object]:
    """Create deterministic legacy AI result fixtures under uploads_dir/ai_results."""
    legacy_dir = uploads_dir / "ai_results"
    legacy_dir.mkdir(parents=True, exist_ok=True)

    wsi_ids = ["wsi-a", "wsi-b", "case/with/slash"]

    classification_result_a = {
        "wsi_id": "wsi-a",
        "task_id": task_id,
        "pred": "A",
        "ground_truth": "B",
        "probs": {"A": 0.8, "B": 0.2},
        "correct": False,
        "classes": ["A", "B"],
    }

    fold_result_a = {
        "wsi_id": "wsi-a",
        "task_id": task_id,
        "fold_key": "fold_0",
        "pred": "A",
        "probs": {"A": 0.75, "B": 0.25},
    }

    survival_result_b = {
        "wsi_id": "wsi-b",
        "task_id": task_id,
        "risk_score": 1.23,
        "event_time": 456.0,
        "event_status": 1,
        "surv_probs": [0.9, 0.7, 0.3],
        "bin_edges": [0.0, 12.0, 24.0],
    }

    classification_result_c = {
        "wsi_id": "case/with/slash",
        "task_id": task_id,
        "pred": "C",
        "ground_truth": "D",
        "probs": {"C": 0.6, "D": 0.4},
        "correct": True,
        "classes": ["C", "D"],
    }

    def _write_result(wsi_id: str, payload: Mapping[str, object], suffix: str = "") -> Path:
        wsi_dir = legacy_dir / wsi_id
        wsi_dir.mkdir(parents=True, exist_ok=True)
        filename = f"train_{task_id}{suffix}_result.json"
        path = wsi_dir / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return path

    def _write_npy(wsi_id: str, artifact: str, array: np.ndarray[Any, Any]) -> Path:
        wsi_dir = legacy_dir / wsi_id
        wsi_dir.mkdir(parents=True, exist_ok=True)
        path = wsi_dir / f"train_{task_id}_{artifact}.npy"
        np.save(path, array)
        return path

    _write_result("wsi-a", classification_result_a)
    _write_result("wsi-a", fold_result_a, suffix="_fold_0")
    _write_npy("wsi-a", "attention", np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32))
    _write_npy("wsi-a", "attention_raw", np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32))
    _write_npy("wsi-a", "cam", np.array([[0.5, 0.6], [0.7, 0.8]], dtype=np.float32))

    _write_result("wsi-b", survival_result_b)
    _write_npy("wsi-b", "attention", np.array([0.5, 0.4, 0.3, 0.2], dtype=np.float32))
    _write_npy("wsi-b", "attention_raw", np.array([[5.0, 6.0], [7.0, 8.0]], dtype=np.float32))
    _write_npy("wsi-b", "cam", np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32))

    malformed_path = legacy_dir / "wsi-b" / f"train_{task_id}_malformed.json"
    malformed_path.write_text('{"pred": "A", "probs": }', encoding="utf-8")

    _write_result("case/with/slash", classification_result_c)
    _write_npy("case/with/slash", "attention", np.array([0.7, 0.8, 0.9, 1.0], dtype=np.float32))
    _write_npy("case/with/slash", "attention_raw", np.array([[9.0, 10.0], [11.0, 12.0]], dtype=np.float32))

    corrupt_path = legacy_dir / "case/with/slash" / f"train_{task_id}_corrupt.npy"
    corrupt_path.write_bytes(b"NOT_A_VALID_NPY_HEADER")

    duplicate_path = legacy_dir / "wsi-a" / f"train_{task_id}_attention.npy.duplicate"
    real_npy = legacy_dir / "wsi-a" / f"train_{task_id}_attention.npy"
    duplicate_path.write_bytes(real_npy.read_bytes())

    valid_count = 12

    return {
        "task_id": task_id,
        "wsi_ids": wsi_ids,
        "legacy_dir": legacy_dir,
        "valid_count": valid_count,
    }
