from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from autoresearch.dataset.readiness import DataReadinessResult, assess_data_readiness
from autoresearch.dataset.types import TaskProfile
from autoresearch.orchestrator.execution_plan import build_execution_plan


def _valid_splits(*slide_ids: str) -> dict:
    ids = list(slide_ids)
    return {
        "train": ids[:1],
        "val": ids[1:2],
        "test": ids[2:3],
        "labels": {slide_id: idx % 2 for idx, slide_id in enumerate(ids)},
    }


def _write_pathlab_uploads(root: Path) -> None:
    features = root / "features" / "virchow2"
    features.mkdir(parents=True, exist_ok=True)
    for slide_id in ("slide_001", "slide_002", "slide_003"):
        (features / f"{slide_id}.pt").write_bytes(b"pt")
    (root / "splits.json").write_text(
        json.dumps(_valid_splits("slide_001", "slide_002", "slide_003"))
    )


def _canonical_wsi_profile() -> TaskProfile:
    return TaskProfile(
        task_type="wsi_classification",
        asset_level="slide",
        input_modality="wsi",
        label_granularity="slide",
    )


def test_readiness_maps_canonical_wsi_task_to_slide_feature_consumer(tmp_path):
    uploads = tmp_path / "uploads"
    _write_pathlab_uploads(uploads)

    readiness = assess_data_readiness(
        _canonical_wsi_profile(),
        data_mounts={str(uploads): "/data/pathlab"},
    )

    assert readiness.status == "features_ready"


def test_execution_plan_maps_canonical_wsi_task_to_private_execution_skill():
    readiness = DataReadinessResult(
        status="features_ready",
        features_dir="/data/internal/features/virchow2",
        splits_file="/data/internal/splits.json",
    )

    plan = build_execution_plan(
        profile=_canonical_wsi_profile(),
        selected_skill="",
        readiness=readiness,
    )

    assert plan.primary_skill == "mil_classification"
    assert plan.steps[0].skill == "mil_classification"
