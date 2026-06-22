"""HF token propagation for generated PathScientist experiment scripts."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.config import PathScientistConfig  # noqa: E402
from pathscientist.tools.run_experiment import (  # noqa: E402
    _build_env_vars_for_test,
    _pathlab_linkage_for_run_for_test,
)


def test_run_experiment_env_forwards_huggingface_token(tmp_path):
    config = PathScientistConfig(huggingface_token="pathlab-hf-token")

    env = _build_env_vars_for_test(
        config=config,
        run_dir=tmp_path / "run",
        script_text="print('train')\n",
    )

    assert env["HF_TOKEN"] == "pathlab-hf-token"
    assert env["HUGGING_FACE_HUB_TOKEN"] == "pathlab-hf-token"
    assert env["PATHSCIENTIST_HUGGINGFACE_TOKEN"] == "pathlab-hf-token"


def test_run_experiment_env_injects_planned_patch_extractor(tmp_path):
    config = PathScientistConfig(
        planned_feature_extractor="virchow2",
    )

    env = _build_env_vars_for_test(
        config=config,
        run_dir=tmp_path / "run",
        script_text="print('patch train')\n",
        run_kind="training",
    )

    assert env["PATHSCIENTIST_FEATURE_EXTRACTOR"] == "virchow2"
    assert env["PATHLAB_EXTRACTOR"] == "virchow2"


def test_run_experiment_env_injects_planned_training_data_paths(tmp_path):
    config = PathScientistConfig(
        planned_features_dir="/data/internal/features/virchow2",
        planned_splits_file="/data/internal/splits.json",
        planned_mil_model="abmil",
    )

    env = _build_env_vars_for_test(
        config=config,
        run_dir=tmp_path / "run",
        script_text="print('train')\n",
        run_kind="training",
    )

    assert env["FEATURES_DIR"] == "/data/internal/features/virchow2"
    assert env["SPLITS_FILE"] == "/data/internal/splits.json"
    assert env["PATHSCIENTIST_MIL_MODEL"] == "abmil"


def test_run_experiment_linkage_records_pathlab_training_artifacts(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    features_dir = uploads / "features" / "conch" / "abc123"
    training_dir = uploads / "training" / "task_123"
    model_path = training_dir / "models" / "best_model.pth"
    run_dir = uploads / "pathscientist" / "session_abc" / "output" / "runs" / "run_a"
    monkeypatch.setenv("PATHLAB_UPLOADS_DIR", str(uploads))

    linkage = _pathlab_linkage_for_run_for_test(
        config=PathScientistConfig(),
        run_kind="training",
        data_output_dir=str(features_dir),
        model_path=str(model_path),
        run_dir=run_dir,
        data_output_artifacts=[str(features_dir / "slide_001.pt")],
    )

    assert linkage["uploads_dir"] == str(uploads)
    assert linkage["features_dir"] == str(features_dir)
    assert linkage["training_dir"] == str(training_dir)
    assert linkage["training_task_id"] == "task_123"
    assert linkage["model_path"] == str(model_path)


def test_run_experiment_linkage_does_not_invent_training_task_id(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    features_dir = uploads / "features" / "uni2" / "params789"
    run_dir = uploads / "pathscientist" / "session_abc" / "output" / "runs" / "run_b"
    monkeypatch.setenv("PATHLAB_UPLOADS_DIR", str(uploads))

    linkage = _pathlab_linkage_for_run_for_test(
        config=PathScientistConfig(),
        run_kind="feature_extraction",
        data_output_dir=str(features_dir),
        model_path=None,
        run_dir=run_dir,
        data_output_artifacts=[str(features_dir / "slide_001.pt")],
    )

    assert linkage["uploads_dir"] == str(uploads)
    assert linkage["features_dir"] == str(features_dir)
    assert "training_task_id" not in linkage
    assert "training_dir" not in linkage


def test_run_experiment_linkage_skips_non_pathlab_artifacts(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    scratch = tmp_path / "scratch"
    monkeypatch.setenv("PATHLAB_UPLOADS_DIR", str(uploads))

    linkage = _pathlab_linkage_for_run_for_test(
        config=PathScientistConfig(),
        run_kind="training",
        data_output_dir=str(scratch / "features"),
        model_path=str(scratch / "models" / "best_model.pth"),
        run_dir=scratch / "runs" / "run_c",
        data_output_artifacts=[str(scratch / "features" / "slide_001.pt")],
    )

    assert linkage == {}
