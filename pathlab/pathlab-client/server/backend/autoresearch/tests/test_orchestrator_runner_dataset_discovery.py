"""Tests for runner integration of literature-grounded dataset discovery.

Phase C T7 of docs/plans/2026-04-30-autoresearch-literature-grounded-dataset-discovery-plan.md.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class _Session:
    def __init__(self, root: Path):
        self.workspace_dir = Path(root) / "ws"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.persistence_root = Path(root)


class _Config:
    """Minimal stand-in for AutoResearchConfig in acquisition tests."""

    data_mounts: dict = {}
    dataset_cache_dir: str = ""
    download_policy: str = "disabled"
    max_download_size_gb: float = 1.0
    allow_large_downloads: bool = False
    external_test_enabled: bool = False
    external_test_contract: dict = {}


def _msi_state(tmp_path):
    from autoresearch.orchestrator.types import (
        ResearchObjective,
        ResearchSessionState,
    )
    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(question="CRC MSI prediction from H&E"),
    )
    state.task_profile = {
        "task_type": "patch_classification",
        "asset_level": "patch",
        "input_modality": "patch_images",
        "label_granularity": "patch",
        "organ": "colorectal",
        "prediction_target": "microsatellite_instability",
        "required_label_keywords": ["MSI", "MSI-H", "MSS"],
    }
    return state


def test_runner_writes_discovery_artifact_when_grounding_has_baselines(tmp_path):
    from autoresearch.dataset.discovery_store import load_discovery_records
    from autoresearch.orchestrator.runner import _run_acquisition_stage

    state = _msi_state(tmp_path)
    state.grounding = {
        "baselines": [
            {"dataset": "CRC-MSI", "paper_id": "openalex:W1", "context": "AUC on CRC-MSI"},
        ],
    }
    cfg = _Config()
    cfg.data_mounts = {}     # let acquisition stage fire
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, _Session(tmp_path), cfg)

    discovery_path = tmp_path / "ws" / ".dataset" / "discovery.json"
    assert discovery_path.exists()
    records = load_discovery_records(discovery_path)
    assert [r.name for r in records] == ["CRC-MSI"]


def test_runner_persists_discovery_and_plan_paths_in_grounding(tmp_path):
    from autoresearch.orchestrator.runner import _run_acquisition_stage

    state = _msi_state(tmp_path)
    state.grounding = {
        "baselines": [
            {"dataset": "CRC-MSI", "paper_id": "openalex:W1"},
        ],
    }
    cfg = _Config()
    cfg.data_mounts = {}
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, _Session(tmp_path), cfg)

    assert "dataset_discovery_path" in state.grounding
    assert "dataset_acquisition_plan_path" in state.grounding
    assert Path(state.grounding["dataset_discovery_path"]).exists()
    assert Path(state.grounding["dataset_acquisition_plan_path"]).exists()


def test_runner_writes_acquisition_plan_artifact(tmp_path):
    from autoresearch.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )
    from autoresearch.orchestrator.runner import _run_acquisition_stage

    state = _msi_state(tmp_path)
    state.grounding = {"baselines": [{"dataset": "CRC-MSI", "paper_id": "openalex:W1"}]}
    cfg = _Config()
    cfg.data_mounts = {}
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, _Session(tmp_path), cfg)

    plan_path = acquisition_plan_path_for_workspace(tmp_path / "ws")
    assert plan_path.exists()
    payload = json.loads(plan_path.read_text())
    assert "considered" in payload


def test_runner_skips_discovery_when_data_mounts_are_ready(tmp_path):
    """Ready user data_mounts skip acquisition and discovery."""
    from autoresearch.orchestrator.runner import _run_acquisition_stage

    state = _msi_state(tmp_path)
    state.grounding = {"baselines": [{"dataset": "CRC-MSI", "paper_id": "openalex:W1"}]}
    dataset_root = tmp_path / "dataset"
    for class_name in ("MSI", "MSS"):
        image_root = dataset_root / "images" / class_name
        image_root.mkdir(parents=True)
        (image_root / f"{class_name.lower()}-patch.png").write_bytes(b"patch")
    split_file = dataset_root / "splits.csv"
    split_file.write_text("slide_id,split\nslide-a,train\n")
    cfg = _Config()
    cfg.data_mounts = {str(dataset_root): "/data"}

    _run_acquisition_stage(state, _Session(tmp_path), cfg)
    discovery_path = tmp_path / "ws" / ".dataset" / "discovery.json"
    assert not discovery_path.exists()
    assert state.acquisition_status == "skipped"


def test_runner_continues_when_grounding_is_empty(tmp_path):
    """Empty grounding → discovery returns []; acquisition still proceeds with curated registry."""
    from autoresearch.orchestrator.runner import _run_acquisition_stage

    state = _msi_state(tmp_path)
    state.grounding = {}
    cfg = _Config()
    cfg.data_mounts = {}
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, _Session(tmp_path), cfg)
    # Discovery file gets created with [] (empty list) so the brief can still
    # link to it; acquisition runs as before.
    discovery_path = tmp_path / "ws" / ".dataset" / "discovery.json"
    assert discovery_path.exists()
    records = json.loads(discovery_path.read_text())
    assert records == []


def test_runner_records_session_registry_path_in_grounding(tmp_path):
    """Task 0 blocker #2: session_registry_path needs to be in grounding so the
    brief / reviewers can find the merged curated+discovered registry."""
    from autoresearch.orchestrator.runner import _run_acquisition_stage

    state = _msi_state(tmp_path)
    state.grounding = {
        "baselines": [{"dataset": "CRC-MSI", "paper_id": "openalex:W1"}],
    }
    cfg = _Config()
    cfg.data_mounts = {}
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, _Session(tmp_path), cfg)

    assert "dataset_session_registry_path" in state.grounding
    assert Path(state.grounding["dataset_session_registry_path"]).exists()


def test_runner_does_not_mutate_seed_registry(tmp_path):
    """Plan T7 step 3 spec: do not mutate dataset/seed_data/pathology_datasets.json."""
    from autoresearch.orchestrator.runner import _run_acquisition_stage

    seed_path = (
        Path(__file__).parent.parent / "dataset" / "seed_data"
        / "pathology_datasets.json"
    )
    seed_before = seed_path.read_text()

    state = _msi_state(tmp_path)
    state.grounding = {"baselines": [{"dataset": "CRC-MSI", "paper_id": "openalex:W1"}]}
    cfg = _Config()
    cfg.data_mounts = {}
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, _Session(tmp_path), cfg)
    assert seed_path.read_text() == seed_before


def test_required_async_value_runs_inside_current_gateway_loop(monkeypatch):
    """Required async reads must not be downgraded to best-effort scheduled tasks."""
    from autoresearch.orchestrator import runner

    async def _work():
        return ["pathlab:dataset"]

    async def _case():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(
            runner,
            "_autoresearch_persistence_module",
            lambda: SimpleNamespace(_gateway_loop=loop, _persist_lock=None),
        )
        return runner._run_async_required_value(_work, "load PathLab datasets")

    assert asyncio.run(_case()) == ["pathlab:dataset"]


def test_pathlab_dataset_records_use_loop_local_direct_db_reader(monkeypatch):
    """PathLab registry reads must not reuse the Gateway SQLAlchemy async pool."""
    import asyncpg
    import backend.database.database as database
    from autoresearch.orchestrator import runner

    def _broken_safe_session():
        raise AssertionError("global SQLAlchemy async engine should not be used")

    class _FakeConnection:
        closed = False

        async def fetch(self, query, *args):
            assert "FROM datasets" in query
            assert args == ()
            return [
                SimpleNamespace(
                    dataset_id="e0470dbc-e5ca-4570-88b0-e6ee7a14c826",
                    name="AutoResearch Nanfang-GC-IM",
                    source_organ="stomach",
                    user_id="owner",
                    is_public=False,
                    data_type="wsi",
                    task_type="classification",
                    slide_count=3417,
                    feature_count=3417,
                )
            ]

        async def close(self):
            self.closed = True

    fake_connection = _FakeConnection()

    async def _fake_connect(dsn):
        assert dsn == "postgresql://pathlab:pathlab@127.0.0.1:15432/pathlab_test"
        return fake_connection

    monkeypatch.setattr(database, "safe_session", _broken_safe_session)
    monkeypatch.setattr(asyncpg, "connect", _fake_connect)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://pathlab:pathlab@127.0.0.1:15432/pathlab_test",
    )

    async def _case():
        return runner._pathlab_dataset_records_from_db(SimpleNamespace(pathlab_user_id=""))

    records = asyncio.run(_case())

    assert fake_connection.closed is True
    assert [record.dataset_id for record in records] == [
        "pathlab:e0470dbc-e5ca-4570-88b0-e6ee7a14c826"
    ]
    assert records[0].name == "AutoResearch Nanfang-GC-IM"
    assert records[0].tags[-1] == "features_ready"


def test_internal_dataset_constraint_uses_llm_when_alias_score_misses(monkeypatch):
    """LLM can resolve user dataset names against PathLab display-name prefixes."""
    from autoresearch.dataset.types import DatasetRecord, DownloadSpec
    from autoresearch.orchestrator import runner
    from autoresearch.orchestrator.types import ResearchObjective, ResearchSessionState
    from autoresearch.runtime import metric_parser

    pwh = DatasetRecord(
        dataset_id="pathlab:pwh",
        name="AutoResearch PWH-GC-IM",
        provider="pathlab",
        access="manual",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        tags=["pathlab", "autoresearch"],
        download=DownloadSpec(kind="pathlab_dataset", remote_id="pwh"),
    )
    nanfang = DatasetRecord(
        dataset_id="pathlab:nanfang",
        name="AutoResearch Nanfang-GC-IM",
        provider="pathlab",
        access="manual",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        tags=["pathlab", "autoresearch"],
        download=DownloadSpec(kind="pathlab_dataset", remote_id="nanfang"),
    )

    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(
            question="Use Nanfang-GC-IM as internal and PWH-GC-IM as external"
        ),
    )
    state.grounding = {
        "external_test_request": {
            "requested": True,
            "enabled": True,
            "training_data": {
                "dataset_name": "Nanfang-GC-IM",
                "paths": [],
                "data_role": "internal",
            },
            "external_data": {
                "dataset_name": "PWH-GC-IM",
                "paths": [],
                "data_role": "external",
            },
            "contract": {
                "datasets": [
                    {"role": "internal", "dataset_name": "Nanfang-GC-IM"},
                    {"role": "external", "dataset_name": "PWH-GC-IM"},
                ]
            },
        }
    }
    config = SimpleNamespace(
        external_test_contract=state.grounding["external_test_request"]["contract"],
        pathlab_user_id="",
    )

    monkeypatch.setattr(
        metric_parser,
        "build_llm_text_caller",
        lambda _config: lambda _prompt: json.dumps(
            {
                "selected_dataset_id": "pathlab:nanfang",
                "confidence": "high",
                "reason": "Nanfang-GC-IM is the requested internal dataset.",
            }
        ),
    )

    filtered = runner._filter_records_for_requested_internal_dataset(
        [pwh, nanfang],
        state,
        config,
    )

    assert filtered == [nanfang]
    assert state.grounding["internal_dataset_constraint_match_source"] in {
        "registered_overlap",
        "llm",
    }
    if state.grounding["internal_dataset_constraint_match_source"] == "llm":
        assert (
            state.grounding["internal_dataset_llm_match"]["selected_dataset_id"]
            == "pathlab:nanfang"
        )


def test_internal_dataset_constraint_uses_llm_before_deterministic_overlap(monkeypatch):
    """LLM semantic matching should choose the requested IM cohort before rules."""
    from autoresearch.dataset.types import DatasetRecord, DownloadSpec
    from autoresearch.orchestrator import runner
    from autoresearch.orchestrator.types import ResearchObjective, ResearchSessionState
    from autoresearch.runtime import metric_parser

    pwh = DatasetRecord(
        dataset_id="pathlab:pwh",
        name="PWH-GC-IM",
        provider="pathlab",
        access="manual",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        organs=["gastric"],
        tags=["pathlab", "autoresearch", "features_ready"],
        download=DownloadSpec(kind="pathlab_dataset", remote_id="pwh"),
    )
    nanfang = DatasetRecord(
        dataset_id="pathlab:nanfang",
        name="Nanfang-GC-IM",
        provider="pathlab",
        access="manual",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        organs=["gastric"],
        tags=["pathlab", "autoresearch", "features_ready"],
        download=DownloadSpec(kind="pathlab_dataset", remote_id="nanfang"),
    )

    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(
            question=(
                "Train on the PWH gastric intestinal metaplasia cohort "
                "for Normal vs IM detection"
            )
        ),
    )
    state.grounding = {
        "external_test_request": {
            "training_data": {
                "dataset_name": "PWH gastric intestinal metaplasia cohort",
                "data_role": "internal",
            }
        }
    }
    config = SimpleNamespace(external_test_contract={}, pathlab_user_id="user-1")

    monkeypatch.setattr(
        metric_parser,
        "build_llm_text_caller",
        lambda _config: lambda _prompt: json.dumps(
            {
                "selected_dataset_id": "pathlab:pwh",
                "confidence": "high",
                "reason": "PWH-GC-IM is the registered PWH intestinal metaplasia cohort.",
            }
        ),
    )

    filtered = runner._filter_records_for_requested_internal_dataset(
        [nanfang, pwh],
        state,
        config,
    )

    assert filtered == [pwh]
    assert state.grounding["internal_dataset_constraint_match_source"] == "llm"
    assert state.grounding["internal_dataset_llm_match"]["selected_dataset_id"] == "pathlab:pwh"


def test_pathlab_dataset_registry_includes_all_datasets_for_admin(monkeypatch):
    """Admin AutoResearch sessions should see registered datasets owned by others."""
    from autoresearch.orchestrator import runner

    queries: list[tuple[str, tuple]] = []

    class FakeConn:
        async def fetch(self, query, *params):
            queries.append((query, params))
            return [
                {
                    "dataset_id": "private-nanfang",
                    "name": "Nanfang-GC-IM",
                    "source_organ": "gastric",
                    "user_id": "other-user",
                    "is_public": False,
                    "data_type": "wsi",
                    "task_type": "wsi_classification",
                    "slide_count": 3,
                    "feature_count": 3,
                }
            ]

        async def close(self):
            return None

    class FakeAsyncpg:
        @staticmethod
        async def connect(_dsn):
            return FakeConn()

    monkeypatch.setitem(sys.modules, "asyncpg", FakeAsyncpg)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")

    records = runner._pathlab_dataset_records_from_db(
        SimpleNamespace(pathlab_user_id="admin-user", pathlab_user_role="admin")
    )

    assert [record.name for record in records] == ["Nanfang-GC-IM"]
    assert "WHERE datasets.user_id" not in queries[0][0]
    assert queries[0][1] == ()


def test_internal_dataset_constraint_prefers_pathlab_over_discovered_exact_match():
    from autoresearch.dataset.types import DatasetRecord, DownloadSpec
    from autoresearch.orchestrator import runner
    from autoresearch.orchestrator.types import ResearchObjective, ResearchSessionState

    discovered = DatasetRecord(
        dataset_id="discovered:nanfang-gc-im",
        name="Nanfang-GC-IM",
        provider="manual",
        access="manual",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        tags=["intestinal_metaplasia", "discovered"],
        download=DownloadSpec(kind="manual"),
    )
    pathlab_nanfang = DatasetRecord(
        dataset_id="pathlab:e0470dbc-e5ca-4570-88b0-e6ee7a14c826",
        name="AutoResearch Nanfang-GC-IM",
        provider="pathlab",
        access="manual",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        tags=["pathlab", "autoresearch", "features_ready"],
        download=DownloadSpec(kind="pathlab_dataset", remote_id="e0470dbc-e5ca-4570-88b0-e6ee7a14c826"),
    )
    pathlab_pwh = DatasetRecord(
        dataset_id="pathlab:48990678-148a-5736-8355-cacc2a5386d1",
        name="AutoResearch PWH-GC-IM",
        provider="pathlab",
        access="manual",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        tags=["pathlab", "autoresearch", "features_ready"],
        download=DownloadSpec(kind="pathlab_dataset", remote_id="48990678-148a-5736-8355-cacc2a5386d1"),
    )
    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(
            question="Use Nanfang-GC-IM as internal and PWH-GC-IM as external"
        ),
    )
    state.grounding = {
        "external_test_request": {
            "training_data": {"dataset_name": "Nanfang-GC-IM", "data_role": "internal"},
            "external_data": {"dataset_name": "PWH-GC-IM", "data_role": "external"},
        }
    }
    config = SimpleNamespace(external_test_contract={}, pathlab_user_id="")

    filtered = runner._filter_records_for_requested_internal_dataset(
        [discovered, pathlab_pwh, pathlab_nanfang],
        state,
        config,
    )

    assert filtered == [pathlab_nanfang]
    assert (
        state.grounding["internal_dataset_constraint_match_source"]
        == "registered_overlap"
    )


def test_internal_dataset_constraint_keeps_best_registered_dataset_only():
    from autoresearch.dataset.types import DatasetRecord, DownloadSpec
    from autoresearch.orchestrator import runner
    from autoresearch.orchestrator.types import ResearchObjective, ResearchSessionState

    def record(dataset_id: str, name: str, organ: str) -> DatasetRecord:
        return DatasetRecord(
            dataset_id=dataset_id,
            name=name,
            provider="pathlab",
            access="public",
            task_types=["mil_classification"],
            asset_types=["wsi"],
            organs=[organ],
            tags=["pathlab", "autoresearch", "features_ready"],
            download=DownloadSpec(kind="pathlab_dataset", remote_id=dataset_id[8:]),
        )

    nsclc = record(
        "pathlab:af8cf4aa-5b8c-56c5-82b8-42b8df7890ef",
        "AutoResearch Nanfang-NSCLC",
        "Lung",
    )
    pwh_gc_im = record(
        "pathlab:48990678-148a-5736-8355-cacc2a5386d1",
        "AutoResearch PWH-GC-IM",
        "Stomach",
    )
    nanfang_gc_im = record(
        "pathlab:e0470dbc-e5ca-4570-88b0-e6ee7a14c826",
        "AutoResearch Nanfang-GC-IM",
        "Stomach",
    )
    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(
            question="Use Nanfang-GC-IM as internal and PWH-GC-IM as external"
        ),
    )
    state.grounding = {
        "external_test_request": {
            "training_data": {"dataset_name": "Nanfang-GC-IM", "data_role": "internal"},
            "external_data": {"dataset_name": "PWH-GC-IM", "data_role": "external"},
        }
    }
    config = SimpleNamespace(external_test_contract={}, pathlab_user_id="")

    filtered = runner._filter_records_for_requested_internal_dataset(
        [nsclc, pwh_gc_im, nanfang_gc_im], state, config
    )

    assert filtered == [nanfang_gc_im]


def test_runner_resolves_pathlab_wsi_files_to_dataset_feature_root(tmp_path):
    from autoresearch.orchestrator.runner import (
        _feature_leaf_for_output_root,
        _resolve_features_data_output_dir,
    )

    dataset_root = tmp_path / "uploads" / "tcga_luad"
    (dataset_root / "wsi_files").mkdir(parents=True)

    output_root = _resolve_features_data_output_dir(
        workspace_root=tmp_path / "workspace",
        wsi_dir=str(dataset_root / "wsi_files"),
        raw_root=str(dataset_root / "wsi_files"),
    )

    assert output_root == dataset_root
    assert _feature_leaf_for_output_root(output_root, "virchow2") == dataset_root / "features" / "virchow2"


def test_runner_keeps_view_feature_dir_for_training_after_missing_feature_extraction(tmp_path):
    from autoresearch.orchestrator.runner import _advance_execution_plan_after_iteration
    from autoresearch.orchestrator.types import ResearchObjective, ResearchSessionState

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    view_root = tmp_path / "view"
    original_root = tmp_path / "original"
    view_features = view_root / "features" / "virchow2"
    original_features = original_root / "features" / "virchow2"
    view_features.mkdir(parents=True)
    original_features.mkdir(parents=True)
    (view_features / "uuid-slide.pt").write_bytes(b"pt")
    (original_features / "raw-slide.pt").write_bytes(b"pt")

    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(question="extract missing features before training"),
    )
    state.data_readiness = {
        "status": "raw_wsi_ready",
        "features_dir": "/data/view/features/virchow2",
        "features_dir_host": str(view_features),
        "splits_file": "/data/view/splits.json",
        "wsi_dir": "/data/view/wsi_files",
    }
    state.execution_plan = {
        "status": "ready",
        "current_step": 0,
        "steps": [
            {
                "id": "extract_features",
                "skill": "feature_extraction",
                "inputs": {
                    "wsi_dir": "/data/view/wsi_files",
                    "data_output_dir": str(original_root),
                    "extractor_name": "virchow2",
                },
                "outputs": {"features_dir": str(original_features)},
            },
            {
                "id": "train_downstream",
                "skill": "mil_classification",
                "inputs": {
                    "features_dir": str(original_features),
                    "splits_file": "/data/view/splits.json",
                },
            },
        ],
    }
    state.grounding = {"execution_plan": state.execution_plan, "data_readiness": state.data_readiness}

    assert _advance_execution_plan_after_iteration(state, workspace_root=workspace)

    train_step = state.execution_plan["steps"][1]
    assert state.execution_plan["current_step"] == 1
    assert train_step["inputs"]["features_dir"] == "/data/view/features/virchow2"
    assert state.data_readiness["features_dir"] == "/data/view/features/virchow2"
    assert state.data_readiness["features_dir_host"] == str(view_features)



def test_runner_links_raw_name_features_into_view_feature_dir_after_extraction(tmp_path, monkeypatch):
    from autoresearch.orchestrator import runner

    monkeypatch.setattr(runner, "_register_autoresearch_features_with_pathlab", lambda **_: {"status": "skipped"})
    from autoresearch.orchestrator.types import ResearchObjective, ResearchSessionState

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    view_root = tmp_path / "view"
    original_root = tmp_path / "original"
    view_features = view_root / "features" / "virchow2"
    original_features = original_root / "features" / "virchow2"
    (view_root / "wsi_files").mkdir(parents=True)
    (original_root / "WSIs").mkdir(parents=True)
    view_features.mkdir(parents=True)
    original_features.mkdir(parents=True)
    (original_features / "raw-slide.pt").write_bytes(b"pt")
    (view_root / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "layout": "pathlab_dataset_view",
                "pathlab_slide_map": [
                    {
                        "slide_id": "uuid-slide",
                        "view_wsi_path": str(view_root / "wsi_files" / "uuid-slide.svs"),
                        "wsi_path": str(original_root / "WSIs" / "raw-slide.svs"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(question="extract missing features before training"),
    )
    state.data_readiness = {
        "status": "raw_wsi_ready",
        "features_dir": "/data/view/features/virchow2",
        "features_dir_host": str(view_features),
        "splits_file": "/data/view/splits.json",
        "wsi_dir": "/data/view/wsi_files",
    }
    state.execution_plan = {
        "status": "ready",
        "current_step": 0,
        "steps": [
            {
                "id": "extract_features",
                "skill": "feature_extraction",
                "inputs": {
                    "wsi_dir": "/data/view/wsi_files",
                    "data_output_dir": str(original_root),
                    "extractor_name": "virchow2",
                },
                "outputs": {"features_dir": str(original_features)},
            },
            {
                "id": "train_downstream",
                "skill": "mil_classification",
                "inputs": {"features_dir": str(original_features)},
            },
        ],
    }
    state.grounding = {"execution_plan": state.execution_plan, "data_readiness": state.data_readiness}

    assert runner._advance_execution_plan_after_iteration(state, workspace_root=workspace)

    view_feature = view_features / "uuid-slide.pt"
    assert view_feature.exists()
    assert view_feature.resolve() == (original_features / "raw-slide.pt").resolve()


def test_runner_preserves_external_features_ready_when_original_root_has_view_features(tmp_path):
    from autoresearch.orchestrator.runner import _rewrite_pathlab_view_external_outputs
    from autoresearch.orchestrator.types import ResearchObjective, ResearchSessionState

    view_root = tmp_path / "view"
    original_root = tmp_path / "original"
    (view_root / "wsi_files").mkdir(parents=True)
    (original_root / "features" / "virchow2").mkdir(parents=True)
    (original_root / "coordinates").mkdir()
    (original_root / "features" / "virchow2" / "uuid-slide.pt").write_bytes(b"pt")
    (view_root / "splits.json").write_text(
        json.dumps({"train": ["uuid-slide"], "val": ["uuid-slide"], "test": ["uuid-slide"], "labels": {"uuid-slide": 0}}),
        encoding="utf-8",
    )
    (view_root / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "layout": "pathlab_dataset_view",
                "dataset_root": str(original_root),
                "pathlab_slide_map": [
                    {
                        "slide_id": "uuid-slide",
                        "view_wsi_path": str(view_root / "wsi_files" / "uuid-slide.svs"),
                        "wsi_path": str(original_root / "WSIs" / "source.svs"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(question="train internal and external test"),
    )
    state.grounding = {
        "external_test_request": {
            "requested": True,
            "enabled": True,
            "contract": {
                "external_pathlab_uploads_dir": "/data/external_view",
                "external_wsi_dir": "/data/external_view/wsi_files",
                "external_splits_file": "/data/external_view/splits.json",
                "external_features_ready": "true",
            },
        }
    }
    cfg = _Config()
    cfg.data_mounts = {str(view_root): "/data/external_view"}
    cfg.external_test_enabled = True
    cfg.external_test_contract = dict(state.grounding["external_test_request"]["contract"])
    data_mounts = dict(cfg.data_mounts)

    _rewrite_pathlab_view_external_outputs(
        state,
        cfg,
        data_mounts=data_mounts,
        extractor_name="virchow2",
    )

    contract = state.grounding["external_test_request"]["contract"]
    assert contract["external_features_dir"] == "/data/external_original/features/virchow2"
    assert contract["external_features_ready"] == "true"
    assert cfg.external_test_contract["external_features_ready"] == "true"



def test_runner_preserves_external_view_features_when_original_features_use_raw_names(tmp_path):
    from autoresearch.orchestrator.runner import _rewrite_pathlab_view_external_outputs
    from autoresearch.orchestrator.types import ResearchObjective, ResearchSessionState

    view_root = tmp_path / "view"
    original_root = tmp_path / "original"
    (view_root / "wsi_files").mkdir(parents=True)
    (view_root / "features" / "virchow2").mkdir(parents=True)
    (original_root / "WSIs").mkdir(parents=True)
    (original_root / "features" / "virchow2").mkdir(parents=True)
    (view_root / "features" / "virchow2" / "uuid-slide.pt").write_bytes(b"pt")
    (original_root / "features" / "virchow2" / "raw-slide.pt").write_bytes(b"pt")
    (view_root / "splits.json").write_text(
        json.dumps(
            {
                "train": ["uuid-slide"],
                "val": ["uuid-slide"],
                "test": ["uuid-slide"],
                "labels": {"uuid-slide": 0},
            }
        ),
        encoding="utf-8",
    )
    (view_root / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "layout": "pathlab_dataset_view",
                "pathlab_slide_map": [
                    {
                        "slide_id": "uuid-slide",
                        "view_wsi_path": str(view_root / "wsi_files" / "uuid-slide.svs"),
                        "wsi_path": str(original_root / "WSIs" / "raw-slide.svs"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(question="train internal and external test"),
    )
    state.grounding = {
        "external_test_request": {
            "requested": True,
            "enabled": True,
            "contract": {
                "external_pathlab_uploads_dir": "/data/external_view",
                "external_wsi_dir": "/data/external_view/wsi_files",
                "external_splits_file": "/data/external_view/splits.json",
                "external_features_dir": "/data/external_view/features/virchow2",
                "external_features_ready": "true",
            },
        }
    }
    cfg = _Config()
    cfg.data_mounts = {str(view_root): "/data/external_view"}
    cfg.external_test_enabled = True
    cfg.external_test_contract = dict(state.grounding["external_test_request"]["contract"])
    data_mounts = dict(cfg.data_mounts)

    _rewrite_pathlab_view_external_outputs(
        state,
        cfg,
        data_mounts=data_mounts,
        extractor_name="virchow2",
    )

    contract = state.grounding["external_test_request"]["contract"]
    assert contract["external_features_dir"] == "/data/external_view/features/virchow2"
    assert contract["external_features_ready"] == "true"
    assert cfg.external_test_contract["external_features_dir"] == "/data/external_view/features/virchow2"
    assert cfg.external_test_contract["external_features_ready"] == "true"


def test_runner_resolves_pathlab_view_to_original_dataset_feature_root(tmp_path):
    from autoresearch.orchestrator.runner import (
        _feature_leaf_for_output_root,
        _resolve_features_data_output_dir,
    )

    original_root = tmp_path / "tmp_test_data" / "Nanfang-NSCLC"
    (original_root / "WSIs").mkdir(parents=True)
    view_root = tmp_path / "uploads" / "autoresearch" / "pathlab_datasets" / "session_inputs" / "abc" / "autoresearch_nanfang"
    (view_root / "wsi_files").mkdir(parents=True)
    (view_root / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "layout": "pathlab_dataset_view",
                "pathlab_slide_map": [
                    {
                        "slide_id": "uuid-slide",
                        "view_wsi_path": str(view_root / "wsi_files" / "uuid-slide.svs"),
                        "wsi_path": str(original_root / "WSIs" / "1025997.svs"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    output_root = _resolve_features_data_output_dir(
        workspace_root=tmp_path / "workspace",
        wsi_dir=str(view_root / "wsi_files"),
        raw_root=str(view_root),
    )

    assert output_root == original_root
    assert _feature_leaf_for_output_root(output_root, "virchow2") == original_root / "features" / "virchow2"


def test_runner_prefers_pathlab_view_manifest_root_over_symlink_target(tmp_path):
    from autoresearch.orchestrator.runner import (
        _feature_leaf_for_output_root,
        _resolve_features_data_output_dir,
    )

    readonly_original_root = tmp_path / "original_data" / "Gastric" / "Chronic_gastritis"
    readonly_original_root.mkdir(parents=True)
    registered_root = tmp_path / "tmp_test_data" / "Chronic-gastritis"
    (registered_root / "WSIs").mkdir(parents=True)
    view_root = tmp_path / "uploads" / "autoresearch" / "pathlab_datasets" / "session_inputs" / "abc" / "autoresearch_chronic"
    (view_root / "wsi_files").mkdir(parents=True)
    (readonly_original_root / "slide_001.tif").touch()
    (registered_root / "WSIs" / "slide_001.tif").symlink_to(
        readonly_original_root / "slide_001.tif"
    )
    (view_root / "wsi_files" / "uuid-slide.tif").symlink_to(
        registered_root / "WSIs" / "slide_001.tif"
    )
    (view_root / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "layout": "pathlab_dataset_view",
                "pathlab_slide_map": [
                    {
                        "slide_id": "uuid-slide",
                        "view_wsi_path": str(view_root / "wsi_files" / "uuid-slide.tif"),
                        "wsi_path": str(registered_root / "WSIs" / "slide_001.tif"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    output_root = _resolve_features_data_output_dir(
        workspace_root=tmp_path / "workspace",
        wsi_dir=str(view_root / "wsi_files"),
        raw_root="",
    )

    assert output_root == registered_root
    assert _feature_leaf_for_output_root(output_root, "virchow2") == registered_root / "features" / "virchow2"


def test_runner_rewrites_external_pathlab_view_outputs_to_original_dataset(tmp_path):
    from autoresearch.orchestrator.runner import (
        _rewrite_pathlab_view_external_outputs,
    )
    from autoresearch.orchestrator.types import ResearchObjective, ResearchSessionState

    original_root = tmp_path / "tmp_test_data" / "Nanfang-NSCLC"
    (original_root / "WSIs").mkdir(parents=True)
    view_root = (
        tmp_path
        / "uploads"
        / "autoresearch"
        / "pathlab_datasets"
        / "session_inputs"
        / "abc"
        / "autoresearch_nanfang"
    )
    (view_root / "wsi_files").mkdir(parents=True)
    manifest = {
        "layout": "pathlab_dataset_view",
        "pathlab_slide_map": [
            {
                "slide_id": "uuid-slide",
                "view_wsi_path": str(view_root / "wsi_files" / "uuid-slide.svs"),
                "wsi_path": str(original_root / "WSIs" / "1025997.svs"),
            }
        ],
    }
    (view_root / "dataset_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(question="Train TCGA-NSCLC and test Nanfang-NSCLC"),
    )
    state.grounding = {
        "external_test_request": {
            "requested": True,
            "enabled": True,
            "contract": {
                "external_pathlab_uploads_dir": "/data/external_view",
                "external_wsi_dir": "/data/external_view/wsi_files",
                "external_splits_file": "/data/external_view/splits.json",
                "external_features_ready": False,
            },
        }
    }
    cfg = _Config()
    cfg.data_mounts = {str(view_root): "/data/external_view"}
    cfg.external_test_enabled = True
    cfg.external_test_contract = dict(
        state.grounding["external_test_request"]["contract"]
    )
    data_mounts = dict(cfg.data_mounts)

    _rewrite_pathlab_view_external_outputs(
        state,
        cfg,
        data_mounts=data_mounts,
        extractor_name="virchow2",
    )

    original_container = "/data/external_original"
    expected_feature_dir = f"{original_container}/features/virchow2"
    contract = state.grounding["external_test_request"]["contract"]
    assert data_mounts[str(original_root)] == original_container
    assert cfg.data_mounts[str(original_root)] == original_container
    assert contract["external_wsi_dir"] == "/data/external_view/wsi_files"
    assert contract["external_data_output_dir"] == original_container
    assert contract["external_pathlab_uploads_dir"] == original_container
    assert contract["external_pathlab_global_features_dir"] == f"{original_container}/features"
    assert contract["external_pathlab_coordinates_dir"] == f"{original_container}/coordinates"
    assert contract["external_generated_features_dir"] == expected_feature_dir
    assert contract["external_features_dir"] == expected_feature_dir
    assert cfg.external_test_contract["external_features_dir"] == expected_feature_dir
    copied_manifest = original_root / "autoresearch_pathlab_view_manifest.json"
    assert copied_manifest.is_file()
    copied = json.loads(copied_manifest.read_text(encoding="utf-8"))
    assert copied["pathlab_slide_map"][0]["slide_id"] == "uuid-slide"



def test_pathlab_registered_contract_preserves_original_slide_stems(tmp_path):
    from autoresearch.orchestrator.runner import _build_pathlab_registered_dataset_contract

    root = tmp_path / "Nanfang-GC-IM"
    wsi_dir = root / "WSIs"
    feature_dir = root / "features" / "virchow2"
    wsi_dir.mkdir(parents=True)
    feature_dir.mkdir(parents=True)
    stems = ["PA2300070,01,", "PA2300072,01,", "PA2300081,01,", "PA2300083,01,"]
    slides = []
    for idx, stem in enumerate(stems):
        source = wsi_dir / f"{stem}.sdpc"
        source.write_text("wsi", encoding="utf-8")
        (feature_dir / f"{stem}.pt").write_bytes(b"pt")
        slides.append(SimpleNamespace(
            wsi_id=f"wsi-{idx}",
            original_filename=source.name,
            case_id=f"case-{idx}",
            label=str(idx % 2),
            split="",
            wsi_path=str(source),
        ))
    payload = _build_pathlab_registered_dataset_contract(
        dataset=SimpleNamespace(dataset_id="dataset-im", name="Nanfang-GC-IM", source_organ="stomach"),
        slides=slides,
        sidecar_dir=tmp_path / "sidecar",
        data_container="/data/nanfang_gc_im",
        contract_container="/data/nanfang_gc_im_contract",
    )

    assert payload is not None
    manifest = json.loads((tmp_path / "sidecar" / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["pathlab_slide_map"][0]["slide_id"] == "PA2300070,01,"
    labels_text = (tmp_path / "sidecar" / "autoresearch_labels.csv").read_text(encoding="utf-8")
    assert "PA2300070,01," in labels_text
    splits = json.loads((tmp_path / "sidecar" / "autoresearch_splits.json").read_text(encoding="utf-8"))
    assert set(stems).issubset(set(splits["labels"]))
    assert payload["contract"]["features_dir"] == "/data/nanfang_gc_im/features/virchow2"

def test_pathlab_registered_container_paths_are_workspace_scoped():
    from autoresearch.orchestrator.runner import _pathlab_registered_container_paths

    slug = "nanfang_gc_im_ff0a3171"
    data_a, contract_a = _pathlab_registered_container_paths(
        slug,
        Path("/tmp/autoresearch_sessions/session_aaaaaaaaaaaa"),
    )
    data_b, contract_b = _pathlab_registered_container_paths(
        slug,
        Path("/tmp/autoresearch_sessions/session_bbbbbbbbbbbb"),
    )

    assert data_a != data_b
    assert contract_a != contract_b
    assert data_a.endswith(f"/{slug}")
    assert contract_a.endswith(f"/{slug}_contract")
    assert "/session_aaaaaaaaaaaa/" in data_a
    assert "/session_bbbbbbbbbbbb/" in data_b


def test_runner_filters_transient_discovered_pathlab_rows():
    """Historical discovered PathLab rows must not seed new acquisition registries."""
    from autoresearch.orchestrator.runner import (
        _pathlab_dataset_record_from_row,
    )

    class Row:
        dataset_id = "9f2950ff-bc82-4089-8951-75d1d5acd804"
        name = "discovered - pwh-gc-im"
        source_organ = ""
        is_public = False
        data_type = "wsi"
        task_type = "classification"
        feature_count = 0

    assert _pathlab_dataset_record_from_row(Row()) is None
