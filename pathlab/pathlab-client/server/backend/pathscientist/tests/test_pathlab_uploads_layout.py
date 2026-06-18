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

from pathscientist.dataset.readiness import DataReadinessResult, assess_data_readiness
from pathscientist.dataset.types import TaskProfile
from pathscientist.domain.skills.base_skill import Skill
from pathscientist.orchestrator.execution_plan import build_execution_plan
from pathscientist.orchestrator.external_request import infer_external_request
from pathscientist.orchestrator.prompts import build_execution_brief
from pathscientist.tools.run_experiment import (
    _external_test_env,
    _feature_output_contract_violation_for_test,
)
from pathscientist.orchestrator.types import ResearchObjective, ResearchSessionState


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
        "features": root / "features" / "virchow2" / "paramsabc",
        "task_features": root / "training" / "task-001" / "features",
        "coordinates": root / "coordinates" / "paramsabc",
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
    assert contract["external_features_dir"] == "/data/pathlab_uploads/features/virchow2/paramsabc"
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
    assert external["features_dir"] == "/data/pathlab_uploads/features/virchow2/paramsabc"
    assert external["pathlab_masks_dir"] == "/data/pathlab_uploads/masks"


def test_external_request_prefers_requested_extractor_feature_leaf(tmp_path):
    uploads = tmp_path / "uploads"
    _write_pathlab_uploads(uploads)
    uni_leaf = uploads / "features" / "uni2" / "paramsuni"
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

    assert result.contract["external_features_dir"] == "/data/pathlab_uploads/features/uni2/paramsuni"


def test_readiness_uses_pathlab_uploads_global_feature_leaf(tmp_path):
    uploads = tmp_path / "uploads"
    paths = _write_pathlab_uploads(uploads)

    result = assess_data_readiness(
        _mil_profile(),
        data_mounts={str(uploads): "/data/pathlab"},
        preferred_feature_extractor="virchow2",
    )

    assert result.status == "features_ready"
    assert result.features_dir == "/data/pathlab/features/virchow2/paramsabc"
    assert result.features_dir_host == str(paths["features"])
    assert result.splits_file == "/data/pathlab/splits.json"


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
            "external_features_dir": "/data/pathlab/features/virchow2/paramsabc",
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
    assert "features: /data/pathlab/features/virchow2/paramsabc" in brief
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


def test_external_plan_extracts_features_when_contract_feature_path_is_missing(tmp_path):
    uploads = tmp_path / "uploads"
    _write_pathlab_uploads(uploads)
    for pt_file in (uploads / "features").rglob("*.pt"):
        pt_file.unlink()
    readiness = DataReadinessResult(
        status="features_ready",
        features_dir="/data/internal/features/virchow2/paramsabc",
        splits_file="/data/internal/splits.json",
    )

    plan = build_execution_plan(
        profile=_mil_profile(),
        selected_skill="mil_classification",
        readiness=readiness,
        data_output_dir="/data/internal",
        generated_features_dir="/data/internal/features/virchow2/paramsabc",
        extractor_name="virchow2",
        external_test_enabled=True,
        external_test_contract={
            "external_data_layout": "pathlab_uploads",
            "external_pathlab_uploads_dir": "/data/external",
            "external_wsi_dir": "/data/external/wsi_files",
            "external_features_dir": "/data/external/features/virchow2/paramsabc",
            "external_splits_file": "/data/external/splits.json",
            "external_features_ready": False,
        },
    )

    steps = {step.id: step for step in plan.steps}
    assert list(steps) == ["train_downstream", "extract_external_features", "external_test"]
    assert steps["extract_external_features"].inputs["data_role"] == "external"
    assert steps["extract_external_features"].inputs["wsi_dir"] == "/data/external/wsi_files"
    assert steps["extract_external_features"].outputs["features_dir"] == "/data/external/features/virchow2"
    assert steps["external_test"].depends_on == ["extract_external_features"]
    assert steps["external_test"].inputs["external_features_dir"] == "/data/external/features/virchow2"
    assert steps["train_downstream"].inputs["features_dir"] == "/data/internal/features/virchow2/paramsabc"


def test_external_plan_uses_existing_features_when_contract_marks_ready():
    readiness = DataReadinessResult(
        status="features_ready",
        features_dir="/data/internal/features/virchow2/paramsabc",
        splits_file="/data/internal/splits.json",
    )

    plan = build_execution_plan(
        profile=_mil_profile(),
        selected_skill="mil_classification",
        readiness=readiness,
        data_output_dir="/data/internal",
        generated_features_dir="/data/internal/features/virchow2/paramsabc",
        extractor_name="virchow2",
        external_test_enabled=True,
        external_test_contract={
            "external_wsi_dir": "/data/external/wsi_files",
            "external_features_dir": "/data/external/features/virchow2/paramsabc",
            "external_splits_file": "/data/external/splits.json",
            "external_features_ready": True,
        },
    )

    assert [step.id for step in plan.steps] == ["train_downstream", "external_test"]
    assert plan.steps[-1].inputs["external_features_dir"] == "/data/external/features/virchow2/paramsabc"


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
    monkeypatch.setenv("PATHSCIENTIST_FAKE_FEATURE_EXTRACTION", "1")
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

    params_hash = worker.compute_pathlab_params_hash()
    assert (uploads / "features" / "virchow2" / params_hash / "slide_001.pt").exists()
    assert (uploads / "coordinates" / params_hash / "slide_001_coords.h5").exists()
    meta = json.loads((output / "worker_meta" / "worker_0.json").read_text())
    assert meta["features_dir"].endswith(f"features/virchow2/{params_hash}")
    assert meta["coords_dir"].endswith(f"coordinates/{params_hash}")


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
    monkeypatch.setenv("PATHSCIENTIST_FAKE_FEATURE_EXTRACTION", "1")
    monkeypatch.setenv("PATHSCIENTIST_PATHLAB_TRAINING_TASK_ID", "task_abc")
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

    params_hash = worker.compute_pathlab_params_hash()
    cached_feature = uploads / "features" / "virchow2" / params_hash / "slide_001.pt"
    task_feature = uploads / "training" / "task_abc" / "features" / "slide_001.pt"
    assert cached_feature.exists()
    assert task_feature.is_symlink()
    assert task_feature.resolve() == cached_feature
    meta = json.loads((output / "worker_meta" / "worker_0.json").read_text())
    assert meta["task_features_dir"].endswith("training/task_abc/features")


def test_feature_extraction_launcher_falls_back_to_data_wsi_files():
    launcher = Path(__file__).parent.parent / "domain" / "templates" / "feature_extraction_launcher.sh"
    script = launcher.read_text(encoding="utf-8")

    assert "/data/wsi_files" in script


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
        assert "features/<extractor>/<params_hash>/" in constraints

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


def test_run_experiment_accepts_pathlab_feature_cache_output(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    feature_leaf = uploads / "features" / "virchow2" / "paramsabc"
    feature_leaf.mkdir(parents=True)
    (feature_leaf / "slide_001.pt").write_bytes(b"pt")
    monkeypatch.setenv("PATHSCIENTIST_FEATURE_EXTRACTOR", "virchow2")
    config = type("Config", (), {"planned_data_output_dir": str(uploads)})()

    violation = _feature_output_contract_violation_for_test(
        config=config,
        data_output_dir=str(uploads),
        script_text="feature_extraction",
        run_kind="feature_extraction",
    )

    assert violation == ""
