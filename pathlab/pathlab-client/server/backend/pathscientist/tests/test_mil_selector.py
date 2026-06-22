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
    train_step = next(
        step for step in state.execution_plan["steps"]
        if step.get("id") == "train_downstream"
    )
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


def test_runner_inferrs_external_contract_before_internal_readiness(tmp_path, monkeypatch):
    import pathscientist.orchestrator.runner as runner
    from pathscientist.orchestrator.external_request import ExternalRequestInference
    from pathscientist.orchestrator.types import ResearchObjective, ResearchSessionState

    monkeypatch.delenv("PATHSCIENTIST_FEATURE_EXTRACTOR", raising=False)
    monkeypatch.delenv("PATHSCIENTIST_MIL_MODEL", raising=False)
    internal_uploads = tmp_path / "TCGA-NSCLC-subset4"
    external_uploads = tmp_path / "nsclc_external_test"
    _write_pathlab_uploads_for_runner_test(internal_uploads)
    _write_pathlab_uploads_for_runner_test(external_uploads)

    external_contract = {
        "model_source": "best_run",
        "external_task_type": "mil_classification",
        "datasets": [
            {
                "role": "internal",
                "dataset_name": "local - tcga-nsclc-subset4",
                "data_role": "internal",
            },
            {
                "role": "external",
                "dataset_name": "nsclc_external_test",
                "paths": ["/data/nsclc_external_test"],
                "wsi_dir": "/data/nsclc_external_test/wsi_files",
                "features_dir": "/data/nsclc_external_test/features/virchow2/paramsabc",
                "splits_file": "/data/nsclc_external_test/splits.json",
                "labels_file": "/data/nsclc_external_test/labels.csv",
                "data_layout": "pathlab_uploads",
                "data_role": "external",
            },
        ],
        "external_wsi_dir": "/data/nsclc_external_test/wsi_files",
        "external_features_dir": "/data/nsclc_external_test/features/virchow2/paramsabc",
        "external_splits_file": "/data/nsclc_external_test/splits.json",
    }

    def fake_infer_external_request(**_kwargs):
        return ExternalRequestInference(
            requested=True,
            enabled=True,
            confidence="high",
            status="enabled",
            reason="test external validation request",
            contract=external_contract,
            missing=[],
            training_data={
                "paths": [],
                "dataset_name": "local - tcga-nsclc-subset4",
                "data_role": "internal",
            },
            external_data={
                "paths": [str(external_uploads)],
                "dataset_name": "nsclc_external_test",
                "data_role": "external",
            },
            raw={},
            source="llm",
        )

    monkeypatch.setattr(runner, "infer_external_request", fake_infer_external_request)
    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(
            question=(
                "使用内部数据集 local - tcga-nsclc-subset4 训练 NSCLC MIL 模型，"
                "然后用 nsclc_external_test 做 external validation，使用 virchow2 features。"
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
    state.grounding = {"selected_skill": "mil_classification"}
    session = SimpleNamespace(workspace_dir=tmp_path / "ws", persistence_root=tmp_path)
    session.workspace_dir.mkdir(parents=True)
    config = SimpleNamespace(
        data_mounts={
            str(external_uploads): "/data/nsclc_external_test",
            str(internal_uploads): "/data/tcga-nsclc-subset4",
        },
        auto_acquire_data=True,
        external_test_enabled=False,
        external_test_contract={},
    )

    runner._prepare_data_readiness_and_execution_plan(state, session, config)

    train_step = next(
        step for step in state.execution_plan["steps"]
        if step.get("id") == "train_downstream"
    )
    assert state.data_readiness["status"] == "features_ready"
    assert (
        train_step["inputs"]["features_dir"]
        == "/data/tcga-nsclc-subset4/features/virchow2/paramsabc"
    )
    assert "/data/nsclc_external_test" not in json.dumps(train_step)





def test_external_feature_dim_mismatch_triggers_external_extraction(tmp_path, monkeypatch):
    import pathscientist.orchestrator.runner as runner
    from pathscientist.orchestrator.types import ResearchObjective, ResearchSessionState

    monkeypatch.delenv("PATHSCIENTIST_FEATURE_EXTRACTOR", raising=False)
    monkeypatch.delenv("PATHSCIENTIST_MIL_MODEL", raising=False)
    internal_uploads = tmp_path / "TCGA-NSCLC-subset4"
    external_uploads = tmp_path / "nsclc_external_test"
    _write_pathlab_uploads_for_runner_test(internal_uploads)
    _write_pathlab_uploads_for_runner_test(external_uploads)
    (internal_uploads / "dataset_manifest.json").write_text(
        json.dumps({"feature_extractors": [{"name": "virchow2", "feature_dim": 2560}]}),
        encoding="utf-8",
    )
    (external_uploads / "dataset_manifest.json").write_text(
        json.dumps({"feature_extractors": [{"name": "virchow2", "feature_dim": 16}]}),
        encoding="utf-8",
    )

    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(
            question=(
                "使用内部数据集 local - tcga-nsclc-subset4 训练 NSCLC MIL 模型，"
                "然后用 nsclc_external_test 做 external validation，使用 virchow2 features。"
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
    state.grounding = {
        "selected_skill": "mil_classification",
        "external_test_request": {
            "requested": True,
            "enabled": True,
            "status": "enabled",
            "missing": [],
            "contract": {
                "model_source": "best_run",
                "external_task_type": "mil_classification",
                "external_wsi_dir": "/data/nsclc_external_test/wsi_files",
                "external_features_dir": "/data/nsclc_external_test/features/virchow2/paramsabc",
                "external_splits_file": "/data/nsclc_external_test/splits.json",
                "external_features_ready": True,
                "datasets": [
                    {
                        "role": "internal",
                        "dataset_name": "local - tcga-nsclc-subset4",
                        "paths": ["/data/TCGA-NSCLC-subset4"],
                    },
                    {
                        "role": "external",
                        "dataset_name": "nsclc_external_test",
                        "paths": ["/data/nsclc_external_test"],
                    },
                ],
            },
        },
    }
    session = SimpleNamespace(workspace_dir=tmp_path / "ws", persistence_root=tmp_path)
    session.workspace_dir.mkdir(parents=True)
    config = SimpleNamespace(
        data_mounts={
            str(internal_uploads): "/data/TCGA-NSCLC-subset4",
            str(external_uploads): "/data/nsclc_external_test",
        },
        auto_acquire_data=True,
        external_test_enabled=True,
        external_test_contract={},
    )

    runner._prepare_data_readiness_and_execution_plan(state, session, config)

    assert state.data_readiness["status"] == "features_ready"
    assert state.grounding["external_test_request"]["contract"]["external_features_ready"] == "false"
    assert state.grounding["external_test_request"]["contract"]["external_features_incompatible"] == "true"
    assert [step["id"] for step in state.execution_plan["steps"]] == [
        "extract_external_features",
        "train_downstream",
        "external_test",
    ]


def test_pre_execution_replan_preserves_named_internal_over_manifest_cache(tmp_path, monkeypatch):
    import pathscientist.orchestrator.runner as runner
    from pathscientist.orchestrator.types import ResearchObjective, ResearchSessionState

    monkeypatch.delenv("PATHSCIENTIST_FEATURE_EXTRACTOR", raising=False)
    monkeypatch.delenv("PATHSCIENTIST_MIL_MODEL", raising=False)
    broad_internal = tmp_path / "TCGA-NSCLC"
    requested_internal = tmp_path / "TCGA-NSCLC-subset4"
    external_uploads = tmp_path / "nsclc_external_test"
    for root in (broad_internal, requested_internal, external_uploads):
        _write_pathlab_uploads_for_runner_test(root)

    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(
            question=(
                "使用内部数据集 local - tcga-nsclc-subset4 训练 NSCLC MIL 模型，"
                "然后用 nsclc_external_test 做 external validation，使用 virchow2 features。"
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
    state.grounding = {
        "selected_skill": "mil_classification",
        "external_test_request": {
            "requested": True,
            "enabled": True,
            "status": "enabled",
            "missing": [],
            "contract": {
                "model_source": "best_run",
                "external_task_type": "mil_classification",
                "external_features_dir": "/data/nsclc_external_test/features/virchow2/paramsabc",
                "external_splits_file": "/data/nsclc_external_test/splits.json",
                "datasets": [
                    {
                        "role": "internal",
                        "dataset_name": "local - tcga-nsclc-subset4",
                        "paths": ["/data/TCGA-NSCLC-subset4"],
                    },
                    {
                        "role": "external",
                        "dataset_name": "nsclc_external_test",
                        "paths": ["/data/nsclc_external_test"],
                    },
                ],
            },
        },
    }
    session = SimpleNamespace(workspace_dir=tmp_path / "ws", persistence_root=tmp_path)
    session.workspace_dir.mkdir(parents=True)
    config = SimpleNamespace(
        data_mounts={
            str(broad_internal): "/data/raw",
            str(requested_internal): "/data/TCGA-NSCLC-subset4",
            str(external_uploads): "/data/nsclc_external_test",
        },
        auto_acquire_data=True,
        external_test_enabled=True,
        external_test_contract={},
    )

    runner._prepare_data_readiness_and_execution_plan(state, session, config)

    train_step = next(
        step for step in state.execution_plan["steps"]
        if step.get("id") == "train_downstream"
    )
    assert state.execution_plan["status"] == "ready"
    assert train_step["inputs"]["features_dir"].startswith("/data/TCGA-NSCLC-subset4")
    assert state.data_readiness["features_dir_host"].startswith(str(requested_internal))


def test_internal_readiness_mounts_exclude_manifest_cache_when_internal_path_is_explicit(tmp_path):
    import pathscientist.orchestrator.runner as runner

    broad_internal = tmp_path / "TCGA-NSCLC"
    requested_internal = tmp_path / "TCGA-NSCLC-subset4"
    external_uploads = tmp_path / "nsclc_external_test"
    for root in (broad_internal, requested_internal, external_uploads):
        root.mkdir(parents=True)

    state = SimpleNamespace(
        grounding={
            "external_test_request": {
                "enabled": True,
                "missing": [],
                "contract": {
                    "datasets": [
                        {
                            "role": "internal",
                            "dataset_name": "local - tcga-nsclc-subset4",
                            "paths": ["/data/TCGA-NSCLC-subset4"],
                        },
                        {
                            "role": "external",
                            "dataset_name": "nsclc_external_test",
                            "paths": ["/data/nsclc_external_test"],
                        },
                    ],
                    "external_features_dir": "/data/nsclc_external_test/features/conch/paramsconch",
                },
            }
        }
    )
    config = SimpleNamespace(external_test_contract={})
    manifest_mounts = {str(broad_internal): "/data/raw"}
    data_mounts = {
        str(broad_internal): "/data/raw",
        str(requested_internal): "/data/TCGA-NSCLC-subset4",
        str(external_uploads): "/data/nsclc_external_test",
    }

    filtered = runner._internal_readiness_data_mounts(
        state,
        config,
        manifest_mounts=manifest_mounts,
        data_mounts=data_mounts,
    )

    assert str(requested_internal) in filtered
    assert str(broad_internal) not in filtered
    assert str(external_uploads) not in filtered


def test_cache_readiness_resolves_named_internal_and_external_cache_datasets(tmp_path, monkeypatch):
    import pathscientist.orchestrator.runner as runner
    from pathscientist.orchestrator.external_request import ExternalRequestInference
    from pathscientist.orchestrator.types import ResearchObjective, ResearchSessionState

    monkeypatch.delenv("PATHSCIENTIST_FEATURE_EXTRACTOR", raising=False)
    monkeypatch.delenv("PATHSCIENTIST_MIL_MODEL", raising=False)
    cache_root = tmp_path / "cache"
    wrong_internal = cache_root / "TCGA-NSCLC"
    requested_internal = cache_root / "TCGA-NSCLC-subset4"
    external_uploads = cache_root / "nsclc_external_test"
    for root in (wrong_internal, requested_internal, external_uploads):
        _write_pathlab_uploads_for_runner_test(root)

    external_contract = {
        "model_source": "best_run",
        "external_task_type": "mil_classification",
        "datasets": [
            {
                "role": "internal",
                "dataset_name": "local - tcga-nsclc-subset4",
                "data_role": "internal",
            },
            {
                "role": "external",
                "dataset_name": "nsclc_external_test",
                "task_type": "mil_classification",
                "data_role": "external",
            },
        ],
    }

    def fake_infer_external_request(**_kwargs):
        return ExternalRequestInference(
            requested=True,
            enabled=True,
            confidence="high",
            status="missing_external_data",
            reason="external dataset named but no path supplied by LLM",
            contract=external_contract,
            missing=["external_data_path", "external dataset path for nsclc_external_test"],
            training_data={
                "paths": [],
                "dataset_name": "local - tcga-nsclc-subset4",
                "data_role": "internal",
            },
            external_data={
                "paths": [],
                "dataset_name": "nsclc_external_test",
                "data_role": "external",
            },
            raw={},
            source="llm",
        )

    monkeypatch.setattr(runner, "infer_external_request", fake_infer_external_request)
    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(
            question=(
                "使用内部数据集 local - tcga-nsclc-subset4 训练一个快速的 NSCLC "
                "LUAD vs LUSC MIL 分类模型，优先使用已有的 virchow2 features。"
                "然后用 nsclc_external_test 作为 external validation。"
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
    state.grounding = {"selected_skill": "mil_classification"}
    session = SimpleNamespace(workspace_dir=tmp_path / "ws", persistence_root=tmp_path)
    session.workspace_dir.mkdir(parents=True)
    config = SimpleNamespace(
        data_mounts={},
        dataset_cache_dir=str(cache_root),
        auto_acquire_data=True,
        external_test_enabled=False,
        external_test_contract={},
    )

    result = runner._skip_acquisition_if_cache_features_ready(state, session, config)

    assert result is state
    assert state.data_readiness["status"] == "features_ready"
    selected_feature_dir = Path(state.data_readiness["features_dir_host"])
    assert selected_feature_dir.is_relative_to(requested_internal)
    assert not selected_feature_dir.is_relative_to(wrong_internal)
    train_step = next(
        step for step in state.execution_plan["steps"]
        if step.get("id") == "train_downstream"
    )
    external_step = next(
        step for step in state.execution_plan["steps"]
        if step.get("skill") == "external_test"
    )
    assert train_step["inputs"]["features_dir"].startswith("/data/TCGA-NSCLC-subset4")
    assert external_step["inputs"]["external_features_dir"] == (
        "/data/nsclc_external_test/features/virchow2/paramsabc"
    )
    assert external_step["inputs"]["external_splits_file"] == "/data/nsclc_external_test/splits.json"
    assert state.execution_plan["status"] == "ready"
    assert state.grounding["external_test_request"]["status"] == "enabled"
    assert not state.grounding["external_test_request"].get("missing")


def test_cache_readiness_persists_named_role_mounts_when_internal_needs_feature_extraction(tmp_path, monkeypatch):
    import pathscientist.orchestrator.runner as runner
    from pathscientist.orchestrator.external_request import ExternalRequestInference
    from pathscientist.orchestrator.types import ResearchObjective, ResearchSessionState

    monkeypatch.delenv("PATHSCIENTIST_FEATURE_EXTRACTOR", raising=False)
    monkeypatch.delenv("PATHSCIENTIST_MIL_MODEL", raising=False)
    cache_root = tmp_path / "cache"
    requested_internal = cache_root / "TCGA-NSCLC-subset4"
    external_uploads = cache_root / "nsclc_external_test"
    _write_pathlab_uploads_for_runner_test(requested_internal)
    _write_pathlab_uploads_for_runner_test(external_uploads)
    for feature_file in (requested_internal / "features").rglob("*.pt"):
        feature_file.unlink()

    external_contract = {
        "model_source": "best_run",
        "external_task_type": "mil_classification",
        "datasets": [
            {
                "role": "internal",
                "dataset_name": "local - tcga-nsclc-subset4",
                "data_role": "internal",
            },
            {
                "role": "external",
                "dataset_name": "nsclc_external_test",
                "task_type": "mil_classification",
                "data_role": "external",
            },
        ],
    }

    def fake_infer_external_request(**_kwargs):
        return ExternalRequestInference(
            requested=True,
            enabled=True,
            confidence="high",
            status="missing_external_data",
            reason="named internal and external datasets must resolve from cache mounts",
            contract=external_contract,
            missing=["external_data_path"],
            training_data={
                "paths": [],
                "dataset_name": "local - tcga-nsclc-subset4",
                "data_role": "internal",
            },
            external_data={
                "paths": [],
                "dataset_name": "nsclc_external_test",
                "data_role": "external",
            },
            raw={},
            source="llm",
        )

    monkeypatch.setattr(runner, "infer_external_request", fake_infer_external_request)
    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(
            question=(
                "使用内部数据集 local - tcga-nsclc-subset4 训练 NSCLC MIL 模型，"
                "然后用 nsclc_external_test 做 external validation。"
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
    state.grounding = {"selected_skill": "mil_classification"}
    session = SimpleNamespace(workspace_dir=tmp_path / "ws", persistence_root=tmp_path)
    session.workspace_dir.mkdir(parents=True)
    config = SimpleNamespace(
        data_mounts={},
        dataset_cache_dir=str(cache_root),
        auto_acquire_data=True,
        external_test_enabled=False,
        external_test_contract={},
        planned_data_output_dir="",
    )

    result = runner._skip_acquisition_if_cache_features_ready(state, session, config)

    assert result is state
    assert state.data_readiness["status"] == "raw_wsi_ready"
    assert str(requested_internal) in config.data_mounts
    assert str(external_uploads) in config.data_mounts
    runner._prepare_data_readiness_and_execution_plan(state, session, config)
    assert state.execution_plan["status"] == "ready"
    assert state.data_readiness["wsi_dir_host"].startswith(str(requested_internal))
