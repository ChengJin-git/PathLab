from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.domain.mil_selector import MILModelSelector, detect_explicit_mil_model


def _write_cached_pick(tmp_path: Path, *, name: str = "clam_mb") -> Path:
    cache_path = tmp_path / "mil_model_choice_cache.json"
    canonical = {
        "clam_mb": "CLAM-MB",
        "dtfdmil": "DTFD-MIL",
    }[name]
    cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "lung|nsclc_subtype|mil_classification": {
                        "name": name,
                        "canonical": canonical,
                        "reason": "cached literature pick",
                        "confidence": "high",
                        "ts": "1",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return cache_path


def test_explicit_abmil_in_user_question_overrides_cached_mil_pick(tmp_path, monkeypatch):
    monkeypatch.delenv("PATHSCIENTIST_MIL_MODEL", raising=False)
    selector = MILModelSelector(
        llm_parser=lambda _prompt: json.dumps(
            {"name": "dtfdmil", "reason": "LLM literature pick", "confidence": "high"}
        ),
        cache_path=_write_cached_pick(tmp_path, name="clam_mb"),
    )

    selection = selector.select(
        task_profile={
            "organ": "lung",
            "prediction_target": "nsclc_subtype",
            "task_type": "mil_classification",
            "question": "帮我训练一个NSCLC的分类模型 用ABMIL 和virchow2 feature",
        }
    )

    assert selection.name == "abmil"
    assert selection.canonical == "ABMIL"
    assert selection.source == "user"


def test_explicit_mil_detection_handles_chinese_text_adjacent_to_model_name():
    assert (
        detect_explicit_mil_model(
            {"question": "帮我训练一个NSCLC的分类模型 用ABMIL 和virchow2 feature"}
        )
        == "abmil"
    )


def test_multiple_explicit_mil_models_do_not_freeze_single_architecture(tmp_path, monkeypatch):
    monkeypatch.delenv("PATHSCIENTIST_MIL_MODEL", raising=False)
    selector = MILModelSelector(
        llm_parser=None,
        cache_path=_write_cached_pick(tmp_path, name="clam_mb"),
    )

    selection = selector.select(
        task_profile={
            "organ": "lung",
            "prediction_target": "nsclc_subtype",
            "task_type": "mil_classification",
            "question": "比较 ABMIL 和 TransMIL 在NSCLC上的效果",
        }
    )

    assert selection.name == "clam_mb"
    assert selection.source == "cache"


def test_runner_contract_honors_explicit_abmil_question(tmp_path, monkeypatch):
    from pathscientist.orchestrator.runner import _prepare_data_readiness_and_execution_plan
    from pathscientist.orchestrator.types import ResearchObjective, ResearchSessionState

    monkeypatch.delenv("PATHSCIENTIST_MIL_MODEL", raising=False)
    data_root = tmp_path / "data"
    features_dir = data_root / "features"
    features_dir.mkdir(parents=True)
    (features_dir / "slide_a.pt").write_bytes(b"feature")
    (data_root / "splits.json").write_text(
        json.dumps(
            {
                "train": ["slide_a"],
                "val": ["slide_a"],
                "test": ["slide_a"],
                "labels": {"slide_a": 0},
            }
        ),
        encoding="utf-8",
    )

    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(
            question="帮我训练一个NSCLC的分类模型 用ABMIL 和virchow2 feature"
        ),
    )
    state.task_profile = {
        "task_type": "mil_classification",
        "asset_level": "slide",
        "input_modality": "features",
        "label_granularity": "slide",
        "organ": "lung",
        "prediction_target": "nsclc_subtype",
        "preferred_skill": "mil_classification",
    }
    state.grounding = {"selected_skill": "mil_classification"}
    session = SimpleNamespace(workspace_dir=tmp_path / "ws", persistence_root=tmp_path)
    session.workspace_dir.mkdir(parents=True)
    config = SimpleNamespace(
        data_mounts={str(data_root): "/data"},
        auto_acquire_data=False,
        external_test_enabled=False,
        external_test_contract={},
    )

    _prepare_data_readiness_and_execution_plan(state, session, config)

    extractor_contract = state.grounding["model_selection_contract"]["feature_extractor"]
    mil_contract = state.grounding["model_selection_contract"]["mil_model"]
    train_step = state.execution_plan["steps"][0]
    assert extractor_contract["name"] == "virchow2"
    assert extractor_contract["source"] == "user"
    assert mil_contract["name"] == "abmil"
    assert mil_contract["source"] == "user"
    assert train_step["inputs"]["mil_model_name"] == "abmil"
    assert "Set PATHSCIENTIST_MIL_MODEL=abmil" in train_step["instructions"]
    assert config.planned_mil_model == "abmil"


def _write_pathlab_uploads_for_runner_test(root: Path) -> None:
    wsi_dir = root / "wsi_files"
    feature_dir = root / "features" / "virchow2" / "paramsabc"
    wsi_dir.mkdir(parents=True)
    feature_dir.mkdir(parents=True)
    for slide_id in ("slide_001", "slide_002", "slide_003"):
        (wsi_dir / f"{slide_id}.svs").write_text("wsi", encoding="utf-8")
        (feature_dir / f"{slide_id}.pt").write_bytes(b"feature")
    (root / "splits.json").write_text(
        json.dumps(
            {
                "train": ["slide_001"],
                "val": ["slide_002"],
                "test": ["slide_003"],
                "labels": {"slide_001": 0, "slide_002": 1, "slide_003": 0},
            }
        ),
        encoding="utf-8",
    )
    (root / "labels.csv").write_text(
        "slide_id,label\nslide_001,0\nslide_002,1\nslide_003,0\n",
        encoding="utf-8",
    )


def test_runner_does_not_use_external_only_mount_as_internal_training_data(tmp_path, monkeypatch):
    from pathscientist.orchestrator.runner import _prepare_data_readiness_and_execution_plan
    from pathscientist.orchestrator.types import ResearchObjective, ResearchSessionState

    monkeypatch.delenv("PATHSCIENTIST_FEATURE_EXTRACTOR", raising=False)
    monkeypatch.delenv("PATHSCIENTIST_MIL_MODEL", raising=False)
    external_uploads = tmp_path / "synthetic_nsclc_external_test"
    _write_pathlab_uploads_for_runner_test(external_uploads)

    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(
            question=(
                "Train TCGA-NSCLC internally, then externally validate on "
                f"synthetic NSCLC external test uploads at {external_uploads}."
            )
        ),
    )
    state.task_profile = {
        "task_type": "mil_classification",
        "asset_level": "slide",
        "input_modality": "wsi",
        "label_granularity": "slide",
        "organ": "lung",
        "prediction_target": "nsclc_subtype",
        "preferred_skill": "mil_classification",
    }
    external_contract = {
        "model_source": "best_run",
        "datasets": [
            {"role": "internal", "dataset_name": "TCGA-NSCLC"},
            {
                "role": "external",
                "dataset_name": "synthetic - NSCLC-external-test",
                "paths": ["/data/synthetic_nsclc_external_test"],
                "wsi_dir": "/data/synthetic_nsclc_external_test/wsi_files",
                "features_dir": "/data/synthetic_nsclc_external_test/features/virchow2/paramsabc",
                "splits_file": "/data/synthetic_nsclc_external_test/splits.json",
                "data_layout": "pathlab_uploads",
            },
        ],
        "external_wsi_dir": "/data/synthetic_nsclc_external_test/wsi_files",
        "external_features_dir": "/data/synthetic_nsclc_external_test/features/virchow2/paramsabc",
        "external_splits_file": "/data/synthetic_nsclc_external_test/splits.json",
    }
    state.grounding = {
        "selected_skill": "mil_classification",
        "external_test_request": {"status": "enabled", "contract": external_contract},
    }
    session = SimpleNamespace(workspace_dir=tmp_path / "ws", persistence_root=tmp_path)
    session.workspace_dir.mkdir(parents=True)
    config = SimpleNamespace(
        data_mounts={str(external_uploads): "/data/synthetic_nsclc_external_test"},
        auto_acquire_data=True,
        external_test_enabled=True,
        external_test_contract=external_contract,
    )

    _prepare_data_readiness_and_execution_plan(state, session, config)

    assert state.data_readiness["status"] == "missing_data"
    assert state.execution_plan["status"] == "needs_acquisition"
    serialized_steps = json.dumps(state.execution_plan.get("steps", []))
    assert "/data/synthetic_nsclc_external_test" not in serialized_steps
