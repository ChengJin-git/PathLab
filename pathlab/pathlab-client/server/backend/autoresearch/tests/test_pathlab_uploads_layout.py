from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

import yaml
import numpy as np
import torch
from PIL import Image

from autoresearch.dataset.readiness import DataReadinessResult, assess_data_readiness
from autoresearch.dataset.types import TaskProfile
from autoresearch.domain.skills.base_skill import Skill
from autoresearch.orchestrator.execution_plan import build_execution_plan
from autoresearch.orchestrator.external_request import infer_external_request
from autoresearch.orchestrator.prompts import build_execution_brief
from autoresearch.tools.run_experiment import (
    _external_test_env,
    _feature_output_contract_violation_for_test,
)
from autoresearch.orchestrator.types import ResearchObjective, ResearchSessionState


_SKILLS_DIR = Path(__file__).parent.parent / "domain" / "skills"


def _valid_splits(*slide_ids: str) -> dict:
    ids = list(slide_ids)
    return {
        "train": ids[:1],
        "val": ids[1:2],
        "test": ids[2:3],
        "labels": {slide_id: idx % 2 for idx, slide_id in enumerate(ids)},
    }


def _write_pathlab_uploads(root: Path) -> dict[str, Path]:
    paths = {
        "wsi_files": root / "wsi_files",
        "features": root / "features" / "virchow2",
        "task_features": root / "training" / "task-001" / "features",
        "coordinates": root / "coordinates",
        "metadata": root / "metadata",
        "ai_results": root / "ai_results",
        "models": root / "models",
        "masks": root / "masks",
        "progress": root / "progress",
        "logs": root / "logs",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)

    for slide_id in ("slide_001", "slide_002", "slide_003"):
        (paths["wsi_files"] / f"{slide_id}.svs").write_text("wsi")
        (paths["features"] / f"{slide_id}.pt").write_bytes(b"pt")
        (paths["task_features"] / f"{slide_id}.pt").write_bytes(b"pt")
        (paths["coordinates"] / f"{slide_id}_coords.h5").write_bytes(b"h5")
        (paths["metadata"] / f"{slide_id}.json").write_text("{}")

    (root / "splits.json").write_text(json.dumps(_valid_splits("slide_001", "slide_002", "slide_003")))
    (root / "labels.json").write_text(json.dumps({"labels": {"slide_001": 0, "slide_002": 1}}))
    return paths


def _mil_profile() -> TaskProfile:
    return TaskProfile(
        task_type="mil_classification",
        asset_level="slide",
        input_modality="wsi",
        label_granularity="slide",
    )


def test_external_request_discovers_pathlab_uploads_layout(tmp_path):
    uploads = tmp_path / "uploads"
    paths = _write_pathlab_uploads(uploads)

    def llm_caller(_prompt: str) -> str:
        return json.dumps(
            {
                "external_validation_requested": True,
                "confidence": "high",
                "external_task_type": "mil_classification",
                "training_data": {"paths": [], "dataset_name": "internal"},
                "external_data": {
                    "paths": [str(uploads)],
                    "dataset_name": "PathLab uploads cohort",
                    "role": "external_validation",
                },
                "missing": [],
            }
        )

    result = infer_external_request(
        question=f"externally test on {uploads}",
        selected_skill="mil_classification",
        data_mounts={str(uploads): "/data/pathlab_uploads"},
        llm_caller=llm_caller,
    )

    assert result.status == "enabled"
    contract = result.contract
    assert contract["external_data_layout"] == "pathlab_uploads"
    assert contract["external_pathlab_uploads_dir"] == "/data/pathlab_uploads"
    assert contract["external_wsi_dir"] == "/data/pathlab_uploads/wsi_files"
    assert contract["external_features_dir"] == "/data/pathlab_uploads/features/virchow2"
    assert contract["external_pathlab_training_dir"] == "/data/pathlab_uploads/training"
    assert contract["external_pathlab_coordinates_dir"] == "/data/pathlab_uploads/coordinates"
    assert contract["external_pathlab_metadata_dir"] == "/data/pathlab_uploads/metadata"
    assert contract["external_pathlab_ai_results_dir"] == "/data/pathlab_uploads/ai_results"
    assert contract["external_pathlab_models_dir"] == "/data/pathlab_uploads/models"
    assert contract["external_pathlab_masks_dir"] == "/data/pathlab_uploads/masks"
    assert contract["external_pathlab_progress_dir"] == "/data/pathlab_uploads/progress"
    assert contract["external_pathlab_logs_dir"] == "/data/pathlab_uploads/logs"
    assert contract["external_splits_file"] == "/data/pathlab_uploads/splits.json"
    assert contract["external_labels_file"] == "/data/pathlab_uploads/labels.json"
    external = next(item for item in contract["datasets"] if item["role"] == "external")
    assert external["role"] == "external"
    assert external["data_layout"] == "pathlab_uploads"
    assert external["features_dir"] == "/data/pathlab_uploads/features/virchow2"
    assert external["pathlab_masks_dir"] == "/data/pathlab_uploads/masks"


def test_external_request_accepts_labels_csv_without_external_split(tmp_path):
    uploads = tmp_path / "uploads"
    features = uploads / "features" / "virchow2"
    wsi_dir = uploads / "WSIs"
    features.mkdir(parents=True)
    wsi_dir.mkdir(parents=True)
    for slide_id in ("slide_001", "slide_002", "slide_003"):
        (features / f"{slide_id}.pt").write_bytes(b"pt")
        (wsi_dir / f"{slide_id}.svs").write_text("wsi", encoding="utf-8")
    (uploads / "label.csv").write_text(
        "dataset,case,slide,class\n"
        "external,case-1,slide_001.svs,negative\n"
        "external,case-2,slide_002.svs,positive\n"
        "external,case-3,slide_003.svs,negative\n",
        encoding="utf-8",
    )

    def llm_caller(_prompt: str) -> str:
        return json.dumps(
            {
                "external_validation_requested": True,
                "confidence": "high",
                "external_task_type": "mil_classification",
                "external_data": {"paths": [str(uploads)], "dataset_name": "external"},
                "missing": [],
            }
        )

    result = infer_external_request(
        question=f"externally test on {uploads}",
        selected_skill="mil_classification",
        data_mounts={str(uploads): "/data/pathlab_uploads"},
        llm_caller=llm_caller,
    )

    assert result.status == "enabled"
    assert result.missing == []
    assert result.contract["external_features_dir"] == "/data/pathlab_uploads/features/virchow2"
    assert result.contract["external_wsi_dir"] == "/data/pathlab_uploads/WSIs"
    assert result.contract["external_labels_file"] == "/data/pathlab_uploads/label.csv"
    assert "external_splits_file" not in result.contract


def test_external_test_template_uses_all_label_csv_rows_when_split_absent(tmp_path, monkeypatch):
    labels_file = tmp_path / "label.csv"
    labels_file.write_text(
        "dataset,case,slide,class\n"
        "PWH,case-1,23S000109-I.svs,Not Intestinal metaplasia\n"
        "PWH,case-1,23S000109-II.svs,Intestinal metaplasia\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("EXTERNAL_SPLITS_FILE", raising=False)
    monkeypatch.setenv("EXTERNAL_LABELS_FILE", str(labels_file))
    monkeypatch.setenv("PATHLAB_MAX_EXTERNAL_SAMPLES", "0")

    template_path = Path(__file__).parent.parent / "domain" / "templates" / "external_test_template.py"
    spec = importlib.util.spec_from_file_location(f"external_test_template_{uuid4().hex}", template_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    splits = module.load_splits(Path(""))

    assert splits["sample_ids"] == ["23S000109-I", "23S000109-II"]
    assert splits["labels"] == {
        "23S000109-I": "Not Intestinal metaplasia",
        "23S000109-II": "Intestinal metaplasia",
    }


def test_external_request_prefers_requested_extractor_feature_leaf(tmp_path):
    uploads = tmp_path / "uploads"
    _write_pathlab_uploads(uploads)
    uni_leaf = uploads / "features" / "uni2"
    uni_leaf.mkdir(parents=True)
    for slide_id in ("slide_001", "slide_002", "slide_003"):
        (uni_leaf / f"{slide_id}.pt").write_bytes(b"pt")

    def llm_caller(_prompt: str) -> str:
        return json.dumps(
            {
                "external_validation_requested": True,
                "confidence": "high",
                "external_task_type": "mil_classification",
                "external_data": {"paths": [str(uploads)], "dataset_name": "external"},
                "missing": [],
            }
        )

    result = infer_external_request(
        question=f"external test with UNI2 features on {uploads}",
        selected_skill="mil_classification",
        data_mounts={str(uploads): "/data/pathlab_uploads"},
        llm_caller=llm_caller,
        config=type("Config", (), {"planned_feature_extractor": "uni2"})(),
    )

    assert result.contract["external_features_dir"] == "/data/pathlab_uploads/features/uni2"


def test_readiness_uses_pathlab_uploads_global_feature_leaf(tmp_path):
    uploads = tmp_path / "uploads"
    paths = _write_pathlab_uploads(uploads)

    result = assess_data_readiness(
        _mil_profile(),
        data_mounts={str(uploads): "/data/pathlab"},
        preferred_feature_extractor="virchow2",
    )

    assert result.status == "features_ready"
    assert result.features_dir == "/data/pathlab/features/virchow2"
    assert result.features_dir_host == str(paths["features"])
    assert result.splits_file == "/data/pathlab/splits.json"




def test_readiness_accepts_sdpc_pathlab_uploads_with_matching_features(tmp_path):
    uploads = tmp_path / "uploads"
    features = uploads / "features" / "virchow2"
    wsi_dir = uploads / "WSIs"
    features.mkdir(parents=True)
    wsi_dir.mkdir(parents=True)
    slide_ids = ["PA2300070,01,", "PA2300072,01,", "PA2300081,01,", "PA2300083,01,"]
    for idx, slide_id in enumerate(slide_ids):
        (wsi_dir / f"{slide_id}.sdpc").write_text("wsi", encoding="utf-8")
        (features / f"{slide_id}.pt").write_bytes(b"pt")
    (uploads / "labels.csv").write_text(
        "slide_id,label\n"
        + "\n".join(f"{slide_id},{idx % 2}" for idx, slide_id in enumerate(slide_ids))
        + "\n",
        encoding="utf-8",
    )
    (uploads / "splits.json").write_text(
        json.dumps({
            "train": slide_ids[:2],
            "val": [slide_ids[2]],
            "test": [slide_ids[3]],
            "labels": {slide_id: idx % 2 for idx, slide_id in enumerate(slide_ids)},
        }),
        encoding="utf-8",
    )

    result = assess_data_readiness(
        _mil_profile(),
        data_mounts={str(uploads): "/data/pathlab"},
        preferred_feature_extractor="virchow2",
    )

    assert result.status == "features_ready"
    assert result.features_dir == "/data/pathlab/features/virchow2"
    assert result.splits_file == "/data/pathlab/splits.json"

def test_readiness_rejects_sparse_missing_features_without_no_tissue_metadata(tmp_path):
    uploads = tmp_path / "uploads"
    features = uploads / "features" / "virchow2"
    wsi_dir = uploads / "wsi_files"
    features.mkdir(parents=True)
    wsi_dir.mkdir(parents=True)
    train_ids = [f"slide_train_{idx:02d}" for idx in range(16)]
    val_ids = ["slide_val_00", "slide_val_01"]
    test_ids = ["slide_test_00", "slide_test_01"]
    split_ids = train_ids + val_ids + test_ids
    missing_slide = train_ids[-1]
    for slide_id in split_ids:
        (wsi_dir / f"{slide_id}.svs").write_text("wsi")
        if slide_id != missing_slide:
            (features / f"{slide_id}.pt").write_bytes(b"pt")
    (uploads / "splits.json").write_text(
        json.dumps(
            {
                "train": train_ids,
                "val": val_ids,
                "test": test_ids,
                "labels": {slide_id: idx % 2 for idx, slide_id in enumerate(split_ids)},
            }
        ),
        encoding="utf-8",
    )
    (uploads / "labels.csv").write_text(
        "slide_id,label\n"
        + "\n".join(f"{slide_id},{idx % 2}" for idx, slide_id in enumerate(split_ids))
        + "\n",
        encoding="utf-8",
    )

    result = assess_data_readiness(
        _mil_profile(),
        data_mounts={str(uploads): "/data/pathlab"},
        preferred_feature_extractor="virchow2",
    )

    assert result.status == "raw_wsi_ready"
    assert result.missing == ["features_dir"]
    assert result.wsi_dir == "/data/pathlab/wsi_files"


def test_readiness_allows_no_tissue_missing_features_when_question_requests_extraction(tmp_path):
    uploads = tmp_path / "uploads"
    features = uploads / "features" / "virchow2"
    wsi_dir = uploads / "wsi_files"
    features.mkdir(parents=True)
    wsi_dir.mkdir(parents=True)
    train_ids = [f"slide_train_{idx:02d}" for idx in range(16)]
    val_ids = ["slide_val_00", "slide_val_01"]
    test_ids = ["slide_test_00", "slide_test_01"]
    split_ids = train_ids + val_ids + test_ids
    missing_slide = train_ids[-1]
    for slide_id in split_ids:
        (wsi_dir / f"{slide_id}.svs").write_text("wsi")
        if slide_id != missing_slide:
            (features / f"{slide_id}.pt").write_bytes(b"pt")
    (uploads / "splits.json").write_text(
        json.dumps(
            {
                "train": train_ids,
                "val": val_ids,
                "test": test_ids,
                "labels": {slide_id: idx % 2 for idx, slide_id in enumerate(split_ids)},
            }
        ),
        encoding="utf-8",
    )
    (uploads / "labels.csv").write_text(
        "slide_id,label\n"
        + "\n".join(f"{slide_id},{idx % 2}" for idx, slide_id in enumerate(split_ids))
        + "\n",
        encoding="utf-8",
    )
    (uploads / "extraction_meta.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "extractor": "virchow2",
                "results": {
                    missing_slide: {
                        "status": "no_tissue",
                        "reason": "No detectable tissue found",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = assess_data_readiness(
        _mil_profile(),
        data_mounts={str(uploads): "/data/pathlab"},
        preferred_feature_extractor="virchow2",
        question="Use virchow2 features if available, and extract any missing features before training.",
    )

    assert result.status == "features_ready"
    assert result.features_dir == "/data/pathlab/features/virchow2"
    assert result.features_dir_host == str(features)
    assert any("ignored 1 no_tissue" in note for note in result.notes)


def test_readiness_allows_low_coverage_when_all_missing_features_are_no_tissue(tmp_path):
    uploads = tmp_path / "uploads"
    features = uploads / "features" / "virchow2"
    wsi_dir = uploads / "wsi_files"
    features.mkdir(parents=True)
    wsi_dir.mkdir(parents=True)
    train_ids = [f"slide_train_{idx:02d}" for idx in range(6)]
    val_ids = ["slide_val_00", "slide_val_01"]
    test_ids = ["slide_test_00", "slide_test_01"]
    split_ids = train_ids + val_ids + test_ids
    missing_ids = {"slide_train_05", "slide_test_01"}
    for slide_id in split_ids:
        (wsi_dir / f"{slide_id}.svs").write_text("wsi")
        if slide_id not in missing_ids:
            (features / f"{slide_id}.pt").write_bytes(b"pt")
    (uploads / "splits.json").write_text(
        json.dumps(
            {
                "train": train_ids,
                "val": val_ids,
                "test": test_ids,
                "labels": {slide_id: idx % 2 for idx, slide_id in enumerate(split_ids)},
            }
        ),
        encoding="utf-8",
    )
    (uploads / "labels.csv").write_text(
        "slide_id,label\n"
        + "\n".join(f"{slide_id},{idx % 2}" for idx, slide_id in enumerate(split_ids))
        + "\n",
        encoding="utf-8",
    )
    (uploads / "extraction_meta.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "extractor": "virchow2",
                "success_rate": 0.8,
                "min_success_rate": 0.95,
                "results": {
                    slide_id: {
                        "status": "no_tissue",
                        "reason": "No detectable tissue found during tiling",
                    }
                    for slide_id in missing_ids
                },
            }
        ),
        encoding="utf-8",
    )

    result = assess_data_readiness(
        _mil_profile(),
        data_mounts={str(uploads): "/data/pathlab"},
        preferred_feature_extractor="virchow2",
    )

    assert result.status == "features_ready"
    assert result.features_dir == "/data/pathlab/features/virchow2"
    assert any("ignored 2 no_tissue" in note for note in result.notes)



def test_readiness_uses_pathlab_wsi_files_for_raw_wsi(tmp_path):
    uploads = tmp_path / "uploads"
    paths = _write_pathlab_uploads(uploads)
    # Remove feature tensors so readiness must fall back to raw WSI layout.
    for pt_file in paths["features"].glob("*.pt"):
        pt_file.unlink()
    for pt_file in paths["task_features"].glob("*.pt"):
        pt_file.unlink()

    (uploads / "labels.csv").write_text(
        "slide_id,label\nslide_001,0\nslide_002,1\nslide_003,0\n",
        encoding="utf-8",
    )

    result = assess_data_readiness(
        _mil_profile(),
        data_mounts={str(uploads): "/data/pathlab"},
    )

    assert result.status == "raw_wsi_ready"
    assert result.wsi_dir == "/data/pathlab/wsi_files"
    assert result.wsi_dir_host == str(paths["wsi_files"])


def test_brief_renders_pathlab_uploads_contract_guidance():
    state = ResearchSessionState.create(
        session_id="sid",
        conversation_id=uuid4(),
        objective=ResearchObjective(question="external test", success_metric="auc"),
    )
    state.grounding["external_test_request"] = {
        "requested": True,
        "source": "llm",
        "status": "enabled",
        "confidence": "high",
        "contract": {
            "external_data_layout": "pathlab_uploads",
            "external_pathlab_uploads_dir": "/data/pathlab",
            "external_wsi_dir": "/data/pathlab/wsi_files",
            "external_features_dir": "/data/pathlab/features/virchow2",
            "external_pathlab_training_dir": "/data/pathlab/training",
            "external_pathlab_coordinates_dir": "/data/pathlab/coordinates",
            "external_pathlab_metadata_dir": "/data/pathlab/metadata",
            "external_pathlab_ai_results_dir": "/data/pathlab/ai_results",
            "external_pathlab_models_dir": "/data/pathlab/models",
            "external_pathlab_masks_dir": "/data/pathlab/masks",
            "external_pathlab_progress_dir": "/data/pathlab/progress",
            "external_pathlab_logs_dir": "/data/pathlab/logs",
        },
        "external_data": {"dataset_name": "PathLab uploads cohort"},
    }

    brief = build_execution_brief(state)

    assert "PathLab uploads layout:" in brief
    assert "wsi_files: /data/pathlab/wsi_files" in brief
    assert "features: /data/pathlab/features/virchow2" in brief
    assert "training: /data/pathlab/training" in brief
    assert "coordinates: /data/pathlab/coordinates" in brief
    assert "metadata: /data/pathlab/metadata" in brief
    assert "masks: /data/pathlab/masks" in brief
    assert "progress: /data/pathlab/progress" in brief
    assert "logs: /data/pathlab/logs" in brief


def test_external_pathlab_contract_env_exposes_all_uploads_dirs():
    config = type(
        "Config",
        (),
        {
            "external_test_contract": {
                "external_pathlab_uploads_dir": "/data/pathlab",
                "external_pathlab_masks_dir": "/data/pathlab/masks",
                "external_pathlab_progress_dir": "/data/pathlab/progress",
                "external_pathlab_logs_dir": "/data/pathlab/logs",
            }
        },
    )()

    env = _external_test_env(config)

    assert env["EXTERNAL_PATHLAB_UPLOADS_DIR"] == "/data/pathlab"
    assert env["EXTERNAL_PATHLAB_MASKS_DIR"] == "/data/pathlab/masks"
    assert env["EXTERNAL_PATHLAB_PROGRESS_DIR"] == "/data/pathlab/progress"
    assert env["EXTERNAL_PATHLAB_LOGS_DIR"] == "/data/pathlab/logs"


def test_raw_wsi_plan_uses_pathlab_generated_features_dir(tmp_path):
    uploads = tmp_path / "uploads"
    paths = _write_pathlab_uploads(uploads)
    for pt_file in paths["features"].glob("*.pt"):
        pt_file.unlink()
    for pt_file in paths["task_features"].glob("*.pt"):
        pt_file.unlink()
    (uploads / "labels.csv").write_text(
        "slide_id,label\nslide_001,0\nslide_002,1\nslide_003,0\n",
        encoding="utf-8",
    )
    readiness = assess_data_readiness(
        _mil_profile(),
        data_mounts={str(uploads): "/data/pathlab"},
    )

    plan = build_execution_plan(
        profile=_mil_profile(),
        selected_skill="mil_classification",
        readiness=readiness,
        data_output_dir="/data/pathlab",
        generated_features_dir="/data/pathlab/features/virchow2",
        extractor_name="virchow2",
    )

    extract = plan.steps[0]
    train = plan.steps[1]
    assert extract.inputs["data_output_dir"] == "/data/pathlab"
    assert extract.outputs["features_dir"] == "/data/pathlab/features/virchow2"
    assert train.inputs["features_dir"] == "/data/pathlab/features/virchow2"


def test_raw_wsi_external_plan_extracts_internal_then_external_before_training(tmp_path):
    uploads = tmp_path / "uploads"
    paths = _write_pathlab_uploads(uploads)
    for pt_file in paths["features"].glob("*.pt"):
        pt_file.unlink()
    for pt_file in paths["task_features"].glob("*.pt"):
        pt_file.unlink()
    (uploads / "labels.csv").write_text(
        "slide_id,label\nslide_001,0\nslide_002,1\nslide_003,0\n",
        encoding="utf-8",
    )
    readiness = assess_data_readiness(
        _mil_profile(),
        data_mounts={str(uploads): "/data/pathlab"},
    )

    plan = build_execution_plan(
        profile=_mil_profile(),
        selected_skill="mil_classification",
        readiness=readiness,
        data_output_dir="/data/internal",
        generated_features_dir="/data/internal/features/virchow2",
        extractor_name="virchow2",
        external_test_enabled=True,
        external_test_contract={
            "external_pathlab_uploads_dir": "/data/external",
            "external_wsi_dir": "/data/external/wsi_files",
            "external_features_dir": "/data/external/features/virchow2",
            "external_splits_file": "/data/external/splits.json",
            "external_features_ready": False,
        },
    )

    assert [step.id for step in plan.steps] == [
        "extract_features",
        "extract_external_features",
        "train_downstream",
        "external_test",
    ]
    assert plan.steps[2].depends_on == ["extract_features", "extract_external_features"]
    assert plan.steps[3].depends_on == ["train_downstream"]


def test_external_plan_extracts_features_when_contract_feature_path_is_missing(tmp_path):
    uploads = tmp_path / "uploads"
    _write_pathlab_uploads(uploads)
    for pt_file in (uploads / "features").rglob("*.pt"):
        pt_file.unlink()
    readiness = DataReadinessResult(
        status="features_ready",
        features_dir="/data/internal/features/virchow2",
        splits_file="/data/internal/splits.json",
    )

    plan = build_execution_plan(
        profile=_mil_profile(),
        selected_skill="mil_classification",
        readiness=readiness,
        data_output_dir="/data/internal",
        generated_features_dir="/data/internal/features/virchow2",
        extractor_name="virchow2",
        external_test_enabled=True,
        external_test_contract={
            "external_data_layout": "pathlab_uploads",
            "external_pathlab_uploads_dir": "/data/external",
            "external_wsi_dir": "/data/external/wsi_files",
            "external_features_dir": "/data/external/features/virchow2",
            "external_splits_file": "/data/external/splits.json",
            "external_features_ready": False,
        },
    )

    steps = {step.id: step for step in plan.steps}
    assert list(steps) == ["extract_external_features", "train_downstream", "external_test"]
    assert steps["extract_external_features"].inputs["data_role"] == "external"
    assert steps["extract_external_features"].inputs["wsi_dir"] == "/data/external/wsi_files"
    assert steps["extract_external_features"].outputs["features_dir"] == "/data/external/features/virchow2"
    assert steps["train_downstream"].depends_on == ["extract_external_features"]
    assert steps["external_test"].depends_on == ["train_downstream"]
    assert steps["external_test"].inputs["external_features_dir"] == "/data/external/features/virchow2"
    assert steps["train_downstream"].inputs["features_dir"] == "/data/internal/features/virchow2"


def test_external_plan_uses_existing_features_when_contract_marks_ready():
    readiness = DataReadinessResult(
        status="features_ready",
        features_dir="/data/internal/features/virchow2",
        splits_file="/data/internal/splits.json",
    )

    plan = build_execution_plan(
        profile=_mil_profile(),
        selected_skill="mil_classification",
        readiness=readiness,
        data_output_dir="/data/internal",
        generated_features_dir="/data/internal/features/virchow2",
        extractor_name="virchow2",
        external_test_enabled=True,
        external_test_contract={
            "external_wsi_dir": "/data/external/wsi_files",
            "external_features_dir": "/data/external/features/virchow2",
            "external_splits_file": "/data/external/splits.json",
            "external_features_ready": True,
        },
    )

    assert [step.id for step in plan.steps] == ["train_downstream", "external_test"]
    assert plan.steps[-1].depends_on == ["train_downstream"]
    assert plan.steps[-1].inputs["external_features_dir"] == "/data/external/features/virchow2"


def test_external_plan_blocks_before_training_when_external_files_are_missing():
    readiness = DataReadinessResult(
        status="features_ready",
        features_dir="/data/internal/features/virchow2",
        splits_file="/data/internal/splits.json",
    )

    plan = build_execution_plan(
        profile=_mil_profile(),
        selected_skill="mil_classification",
        readiness=readiness,
        data_output_dir="/data/internal",
        generated_features_dir="/data/internal/features/virchow2",
        extractor_name="virchow2",
        external_test_enabled=True,
        external_test_contract={
            "external_splits_file": "/data/external/splits.json",
        },
    )

    assert plan.status == "blocked"
    assert plan.steps == []
    assert "external_wsi_dir_or_external_features_dir" in plan.missing


def test_feature_extraction_worker_uses_pathlab_uploads_layout(tmp_path, monkeypatch):
    template = Path(__file__).parent.parent / "domain" / "templates" / "feature_extraction_worker.py"
    spec = importlib.util.spec_from_file_location("feature_extraction_worker", template)
    worker = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(worker)
    uploads = tmp_path / "uploads"
    wsi_dir = uploads / "wsi_files"
    output = tmp_path / "run_output"
    wsi_dir.mkdir(parents=True)
    (wsi_dir / "slide_001.svs").write_text("wsi")
    monkeypatch.setenv("AUTORESEARCH_FAKE_FEATURE_EXTRACTION", "1")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "feature_extraction_worker.py",
            "--rank",
            "0",
            "--world-size",
            "1",
            "--wsi-dir",
            str(wsi_dir),
            "--output-dir",
            str(output),
            "--data-output-dir",
            str(uploads),
            "--extractor",
            "virchow2",
        ],
    )

    worker.main()

    assert (uploads / "features" / "virchow2" / "slide_001.pt").exists()
    assert (uploads / "coordinates" / "slide_001_coords.h5").exists()
    meta = json.loads((output / "worker_meta" / "worker_0.json").read_text())
    assert meta["features_dir"].endswith("features/virchow2")
    assert meta["coords_dir"].endswith("coordinates")


def test_feature_extraction_worker_creates_pathlab_task_feature_links(tmp_path, monkeypatch):
    template = Path(__file__).parent.parent / "domain" / "templates" / "feature_extraction_worker.py"
    spec = importlib.util.spec_from_file_location("feature_extraction_worker", template)
    worker = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(worker)
    uploads = tmp_path / "uploads"
    wsi_dir = uploads / "wsi_files"
    output = tmp_path / "run_output"
    wsi_dir.mkdir(parents=True)
    (wsi_dir / "slide_001.svs").write_text("wsi")
    monkeypatch.setenv("AUTORESEARCH_FAKE_FEATURE_EXTRACTION", "1")
    monkeypatch.setenv("AUTORESEARCH_PATHLAB_TRAINING_TASK_ID", "task_abc")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "feature_extraction_worker.py",
            "--rank",
            "0",
            "--world-size",
            "1",
            "--wsi-dir",
            str(wsi_dir),
            "--output-dir",
            str(output),
            "--data-output-dir",
            str(uploads),
            "--extractor",
            "virchow2",
        ],
    )

    worker.main()

    cached_feature = uploads / "features" / "virchow2" / "slide_001.pt"
    task_feature = uploads / "training" / "task_abc" / "features" / "slide_001.pt"
    assert cached_feature.exists()
    assert task_feature.is_symlink()
    assert task_feature.resolve() == cached_feature
    meta = json.loads((output / "worker_meta" / "worker_0.json").read_text())
    assert meta["task_features_dir"].endswith("training/task_abc/features")



def test_feature_extraction_worker_skips_unwritable_pathlab_task_feature_links(tmp_path, monkeypatch):
    template = Path(__file__).parent.parent / "domain" / "templates" / "feature_extraction_worker.py"
    spec = importlib.util.spec_from_file_location("feature_extraction_worker_unwritable_task", template)
    worker = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(worker)
    uploads = tmp_path / "uploads"
    wsi_dir = uploads / "wsi_files"
    output = tmp_path / "run_output"
    wsi_dir.mkdir(parents=True)
    (wsi_dir / "slide_001.svs").write_text("wsi")

    monkeypatch.setenv("AUTORESEARCH_FAKE_FEATURE_EXTRACTION", "1")
    monkeypatch.setenv("AUTORESEARCH_PATHLAB_TRAINING_TASK_ID", "task_abc")
    original_mkdir = Path.mkdir

    def fail_task_training_mkdir(self, *args, **kwargs):
        if self == uploads / "training" / "task_abc" / "features":
            raise OSError(30, "Read-only file system", str(self))
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_task_training_mkdir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "feature_extraction_worker.py",
            "--rank",
            "0",
            "--world-size",
            "1",
            "--wsi-dir",
            str(wsi_dir),
            "--output-dir",
            str(output),
            "--data-output-dir",
            str(uploads),
            "--extractor",
            "virchow2",
        ],
    )

    worker.main()

    cached_feature = uploads / "features" / "virchow2" / "slide_001.pt"
    assert cached_feature.exists()
    assert not (uploads / "training" / "task_abc" / "features" / "slide_001.pt").exists()
    meta = json.loads((output / "worker_meta" / "worker_0.json").read_text())
    assert meta["successful"] == 1
    assert meta.get("task_features_dir", "") == ""


def test_feature_extraction_quick_check_limits_patches(monkeypatch, tmp_path):
    template = Path(__file__).parent.parent / "domain" / "templates" / "feature_extraction_worker.py"
    spec = importlib.util.spec_from_file_location("feature_extraction_worker_quick", template)
    worker = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(worker)

    class _FakeCoords:
        attrs = {"read_size": 4}

        def __getitem__(self, _key):
            return self

        def __array__(self):
            return np.asarray([[i, i] for i in range(10)])

    class _FakeH5:
        def __enter__(self):
            return {"coords": _FakeCoords()}

        def __exit__(self, *_args):
            return False

    class _FakeH5Py:
        @staticmethod
        def File(_path, _mode):
            return _FakeH5()

    class _FakeSlide:
        def __init__(self):
            self.read_count = 0

        def read_region(self, *_args):
            self.read_count += 1
            return Image.new("RGB", (4, 4))

        def close(self):
            pass

    fake_slide = _FakeSlide()

    class _FakeOpenSlide:
        @staticmethod
        def OpenSlide(_path):
            return fake_slide

    monkeypatch.setitem(sys.modules, "h5py", _FakeH5Py)
    monkeypatch.setitem(sys.modules, "openslide", _FakeOpenSlide)
    monkeypatch.setenv("PATHLAB_QUICK_CHECK", "1")
    monkeypatch.setenv("AUTORESEARCH_QUICK_CHECK_MAX_PATCHES", "3")

    batches = list(
        worker._manual_patch_loader(
            tmp_path / "slide.svs",
            tmp_path / "coords.h5",
            lambda _img: torch.zeros(1),
            batch_size=2,
        )
    )

    assert fake_slide.read_count == 3
    assert [len(batch) for batch in batches] == [2, 1]



def test_feature_extraction_aggregate_tolerates_unwritable_data_output_meta(tmp_path, monkeypatch):
    template = Path(__file__).parent.parent / "domain" / "templates" / "feature_extraction_aggregate.py"
    spec = importlib.util.spec_from_file_location("feature_extraction_aggregate_unwritable_meta", template)
    aggregate = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(aggregate)

    output = tmp_path / "run_output"
    data_output = tmp_path / "data_output"
    worker_meta = output / "worker_meta"
    worker_meta.mkdir(parents=True)
    data_output.mkdir()
    (worker_meta / "worker_0.json").write_text(
        json.dumps(
            {
                "total_assigned": 1,
                "successful": 1,
                "patches_extracted": 12,
                "duration": 1.5,
                "features_dir": str(data_output / "features" / "virchow2"),
                "coords_dir": str(data_output / "coordinates"),
                "results": {"slide_001": {"status": "success"}},
            }
        ),
        encoding="utf-8",
    )

    original_write_text = Path.write_text

    def fail_data_output_meta_write(self, *args, **kwargs):
        if self == data_output / "extraction_meta.json.tmp":
            raise OSError(30, "Read-only file system", str(self))
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_data_output_meta_write)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "feature_extraction_aggregate.py",
            "--output-dir",
            str(output),
            "--data-output-dir",
            str(data_output),
            "--extractor",
            "virchow2",
            "--world-size",
            "1",
        ],
    )

    aggregate.main()

    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["status"] == "completed"
    assert metrics["successful_wsi"] == 1.0
    assert (output / "extraction_meta.json").exists()
    assert not (data_output / "extraction_meta.json").exists()


def test_feature_extraction_aggregate_treats_no_tissue_as_explained_skip(tmp_path, monkeypatch):
    template = Path(__file__).parent.parent / "domain" / "templates" / "feature_extraction_aggregate.py"
    spec = importlib.util.spec_from_file_location("feature_extraction_aggregate_no_tissue", template)
    aggregate = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(aggregate)

    output = tmp_path / "run_output"
    data_output = tmp_path / "data_output"
    worker_meta = output / "worker_meta"
    worker_meta.mkdir(parents=True)
    data_output.mkdir()
    (worker_meta / "worker_0.json").write_text(
        json.dumps(
            {
                "total_assigned": 3,
                "successful": 1,
                "patches_extracted": 12,
                "duration": 1.5,
                "features_dir": str(data_output / "features" / "virchow2"),
                "coords_dir": str(data_output / "coordinates"),
                "results": {
                    "slide_001": {"status": "success"},
                    "slide_002": {
                        "status": "no_tissue",
                        "reason": "No detectable tissue found during tiling",
                    },
                    "slide_003": {
                        "status": "no_tissue",
                        "reason": "No detectable tissue found during tiling",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "feature_extraction_aggregate.py",
            "--output-dir",
            str(output),
            "--data-output-dir",
            str(data_output),
            "--extractor",
            "virchow2",
            "--world-size",
            "1",
        ],
    )

    aggregate.main()

    meta = json.loads((output / "extraction_meta.json").read_text(encoding="utf-8"))
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    assert meta["status"] == "completed"
    assert meta["no_tissue_wsi"] == 2
    assert metrics["no_tissue_wsi"] == 2.0


def test_feature_extraction_launcher_falls_back_to_data_wsi_files():
    launcher = Path(__file__).parent.parent / "domain" / "templates" / "feature_extraction_launcher.sh"
    script = launcher.read_text(encoding="utf-8")

    assert "/data/wsi_files" in script


def test_feature_extraction_launcher_uses_configurable_python_bin():
    launcher = Path(__file__).parent.parent / "domain" / "templates" / "feature_extraction_launcher.sh"
    script = launcher.read_text(encoding="utf-8")

    assert 'PYTHON_BIN:=python3' in script
    assert '"$PYTHON_BIN" feature_extraction_worker.py' in script
    assert '"$PYTHON_BIN" feature_extraction_aggregate.py' in script
    assert "aggregate_status=$?" in script
    assert script.rstrip().endswith("exit $aggregate_status")
    assert 'if [ "$status" -ne 0 ]; then' in script
    assert "python feature_extraction_worker.py" not in script
    assert "python feature_extraction_aggregate.py" not in script


def test_feature_extraction_launcher_exposes_common_extractors_package():
    launcher = Path(__file__).parent.parent / "domain" / "templates" / "feature_extraction_launcher.sh"
    script = launcher.read_text(encoding="utf-8")

    assert "TEMPLATE_COMMON_PARENT" in script
    assert "domain/templates" in script
    assert "PYTHONPATH" in script
    assert "common" in script


def test_training_skills_explain_pathlab_uploads_layout():
    for skill_name in (
        "mil_classification.yaml",
        "feature_extraction.yaml",
        "external_test.yaml",
    ):
        skill = Skill.from_yaml(_SKILLS_DIR / skill_name)
        constraints = skill.get_constraints_prompt()
        assert "PathLab uploads layout" in constraints
        assert "wsi_files/" in constraints
        assert "features/<extractor>/{wsi_id}.pt" in constraints
        assert "coordinates/{wsi_id}_coords.h5" in constraints

    external_yaml = yaml.safe_load((_SKILLS_DIR / "external_test.yaml").read_text())
    assert external_yaml["inputs"]["external_pathlab_uploads_dir"] == "$EXTERNAL_PATHLAB_UPLOADS_DIR"
    assert external_yaml["inputs"]["external_pathlab_masks_dir"] == "$EXTERNAL_PATHLAB_MASKS_DIR"


def test_patch_classification_skill_describes_pathlab_db_selected_images():
    skill = Skill.from_yaml(_SKILLS_DIR / "patch_classification.yaml")

    constraints = skill.get_constraints_prompt()

    assert "PathLab patch layout" in constraints
    assert "DB-selected patch images" in constraints
    assert "on-the-fly" in constraints


def _load_template_module(name: str):
    template = Path(__file__).parent.parent / "domain" / "templates" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), template)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_external_template_writes_classification_result_figures(tmp_path):
    module = _load_template_module("external_test_template.py")

    module._write_classification_result_figures(
        y_true=[0, 0, 1, 1],
        y_pred=[0, 1, 1, 1],
        y_score=[0.1, 0.4, 0.8, 0.9],
        output_dir=tmp_path,
        prefix="external",
        class_names=["negative", "positive"],
    )

    assert (tmp_path / "external_roc_curve.png").is_file()
    assert (tmp_path / "external_confusion_matrix.png").is_file()
    assert (tmp_path / "external_roc_curve.png").stat().st_size > 0
    assert (tmp_path / "external_confusion_matrix.png").stat().st_size > 0


def test_classification_template_loads_pathlab_training_manifest(tmp_path):
    module = _load_template_module("classification_template.py")
    manifest = tmp_path / "pathlab_training_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "items": [
                    {"wsi_id": "slide_001", "label": "Tumor", "split": "train"},
                    {"wsi_id": "slide_002", "label": "Normal", "split": "val"},
                    {"wsi_id": "slide_003", "label": "Tumor", "split": "test"},
                ]
            }
        ),
        encoding="utf-8",
    )

    splits = module.load_splits(str(manifest))

    assert splits["train"] == ["slide_001"]
    assert splits["val"] == ["slide_002"]
    assert splits["test"] == ["slide_003"]
    assert splits["labels"] == {"slide_001": 1, "slide_002": 0, "slide_003": 1}




def test_classification_template_honors_quick_check_sample_caps(monkeypatch):
    monkeypatch.setenv("PATHLAB_QUICK_CHECK", "1")
    monkeypatch.setenv("PATHLAB_MAX_TRAIN_SAMPLES", "3")
    monkeypatch.setenv("PATHLAB_MAX_VAL_SAMPLES", "2")
    monkeypatch.setenv("PATHLAB_MAX_TEST_SAMPLES", "1")
    module = _load_template_module("classification_template.py")
    filtered = {
        "train": [f"train_{idx}" for idx in range(10)],
        "val": [f"val_{idx}" for idx in range(5)],
        "test": [f"test_{idx}" for idx in range(4)],
    }
    labels = {
        slide_id: idx % 2
        for idx, slide_id in enumerate(
            filtered["train"] + filtered["val"] + filtered["test"]
        )
    }
    stats = {
        "raw_counts": {"train": 10, "val": 5, "test": 4},
        "usable_counts": {"train": 10, "val": 5, "test": 4},
        "missing_feature_counts": {"train": 0, "val": 0, "test": 0},
        "missing_label_counts": {"train": 0, "val": 0, "test": 0},
        "missing_feature_ids": {"train": [], "val": [], "test": []},
        "missing_label_ids": {"train": [], "val": [], "test": []},
    }
    limited, limited_labels, limited_stats = module.apply_quick_check_limits(
        filtered,
        labels,
        stats,
    )

    assert limited["train"] == ["train_0", "train_1", "train_2"]
    assert limited["val"] == ["val_0", "val_1"]
    assert limited["test"] == ["test_0"]
    assert set(limited_labels) == {"train_0", "train_1", "train_2", "val_0", "val_1", "test_0"}
    assert limited_stats["usable_counts"] == {"train": 3, "val": 2, "test": 1}
    assert limited_stats["quick_check"] is True
    assert limited_stats["quick_check_limits"] == {"train": 3, "val": 2, "test": 1}

def test_patch_template_loads_pathlab_training_manifest(tmp_path):
    module = _load_template_module("patch_classification_template.py")
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    first = image_dir / "patch_001.png"
    second = image_dir / "patch_002.png"
    third = image_dir / "patch_003.png"
    for path in (first, second, third):
        path.write_bytes(b"fake")
    manifest = tmp_path / "pathlab_training_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "items": [
                    {"wsi_id": "p1", "wsi_path": str(first), "label": "Tumor", "split": "train"},
                    {"wsi_id": "p2", "wsi_path": str(second), "label": "Normal", "split": "val"},
                    {"wsi_id": "p3", "wsi_path": str(third), "label": "Tumor", "split": "test"},
                ]
            }
        ),
        encoding="utf-8",
    )

    loaded = module._load_pathlab_training_manifest(manifest)

    assert loaded is not None
    splits, classes = loaded
    assert classes == ["Normal", "Tumor"]
    assert splits["train"] == [(first, 1)]
    assert splits["val"] == [(second, 0)]
    assert splits["test"] == [(third, 1)]


def test_patch_template_auto_creates_val_from_train_without_reusing_test(tmp_path):
    module = _load_template_module("patch_classification_template.py")
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    train_paths = [image_dir / f"train_{idx:02d}.png" for idx in range(10)]
    test_paths = [image_dir / f"test_{idx:02d}.png" for idx in range(4)]
    for path in [*train_paths, *test_paths]:
        path.write_bytes(b"fake")
    manifest = tmp_path / "pathlab_training_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "wsi_id": path.stem,
                        "wsi_path": str(path),
                        "label": "MSIH" if idx % 2 == 0 else "nonMSIH",
                        "split": "train",
                    }
                    for idx, path in enumerate(train_paths)
                ]
                + [
                    {
                        "wsi_id": path.stem,
                        "wsi_path": str(path),
                        "label": "MSIH" if idx % 2 == 0 else "nonMSIH",
                        "split": "test",
                    }
                    for idx, path in enumerate(test_paths)
                ]
            }
        ),
        encoding="utf-8",
    )

    loaded = module._load_pathlab_training_manifest(manifest)

    assert loaded is not None
    splits, _classes = loaded
    splits = module._ensure_validation_split_from_train(splits)
    assert len(splits["train"]) == 9
    assert len(splits["val"]) == 1
    assert len(splits["test"]) == 4
    assert {path for path, _label in splits["val"]}.issubset(set(train_paths))
    assert {path for path, _label in splits["val"]}.isdisjoint(set(test_paths))


def test_patch_template_keeps_msi_h_as_binary_positive_class(tmp_path, monkeypatch):
    monkeypatch.delenv("PATHLAB_POSITIVE_CLASS", raising=False)
    module = _load_template_module("patch_classification_template.py")
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    msih = image_dir / "msih.png"
    non_msih = image_dir / "non_msih.png"
    for path in (msih, non_msih):
        path.write_bytes(b"fake")
    manifest = tmp_path / "pathlab_training_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "items": [
                    {"wsi_id": "p1", "wsi_path": str(msih), "label": "MSIH", "split": "train"},
                    {"wsi_id": "p2", "wsi_path": str(non_msih), "label": "nonMSIH", "split": "test"},
                ]
            }
        ),
        encoding="utf-8",
    )

    loaded = module._load_pathlab_training_manifest(manifest)

    assert loaded is not None
    splits, classes = loaded
    assert classes == ["nonMSIH", "MSIH"]
    assert splits["train"] == [(msih, 1)]
    assert splits["test"] == [(non_msih, 0)]


def test_patch_template_writes_standard_training_log(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "run"))

    _load_template_module("patch_classification_template.py")

    assert (tmp_path / "run" / "training.log").exists()
    assert not (tmp_path / "run" / "train.log").exists()


def test_patch_template_builds_patch_smoke_metrics_payload(tmp_path):
    module = _load_template_module("patch_classification_template.py")
    checkpoint = tmp_path / "best_model.pth"
    train_items = [(tmp_path / "train_msih.png", 1), (tmp_path / "train_non.png", 0)]
    val_items = [(tmp_path / "val_msih.png", 1)]
    test_items = [(tmp_path / "test_msih.png", 1), (tmp_path / "test_non.png", 0)]

    payload = module._build_metrics_payload(
        test_metrics={
            "auc": 0.75,
            "accuracy": 0.5,
            "f1": 0.3333,
            "confusion_matrix": [[0, 1], [0, 1]],
        },
        best_val_metrics={
            "auc": 0.5,
            "accuracy": 1.0,
            "f1": 1.0,
            "confusion_matrix": [[0, 0], [0, 1]],
        },
        feature_dim=1536,
        classes=["nonMSIH", "MSIH"],
        train_items=train_items,
        val_items=val_items,
        test_items=test_items,
        classifier_head_name="LinearHead",
        checkpoint_path=checkpoint,
        epochs_completed=2,
        training_duration=4.2,
        wall_duration=10.8,
    )

    assert payload["task_level"] == "patch"
    assert payload["mil_aggregation"] is False
    assert payload["positive_class"] == "MSIH"
    assert payload["classifier_head"] == "LinearHead"
    assert payload["checkpoint_path"] == str(checkpoint)
    assert payload["split_class_counts"] == {
        "train": {"nonMSIH": 1, "MSIH": 1},
        "val": {"nonMSIH": 0, "MSIH": 1},
        "test": {"nonMSIH": 1, "MSIH": 1},
    }
    assert payload["val_metrics"]["confusion_matrix"] == [[0, 0], [0, 1]]
    assert payload["test_metrics"]["confusion_matrix"] == [[0, 1], [0, 1]]


def test_run_experiment_accepts_pathlab_feature_cache_output(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    feature_leaf = uploads / "features" / "virchow2"
    feature_leaf.mkdir(parents=True)
    (feature_leaf / "slide_001.pt").write_bytes(b"pt")
    monkeypatch.setenv("AUTORESEARCH_FEATURE_EXTRACTOR", "virchow2")
    config = type("Config", (), {"planned_data_output_dir": str(uploads)})()

    violation = _feature_output_contract_violation_for_test(
        config=config,
        data_output_dir=str(uploads),
        script_text="feature_extraction",
        run_kind="feature_extraction",
    )

    assert violation == ""
