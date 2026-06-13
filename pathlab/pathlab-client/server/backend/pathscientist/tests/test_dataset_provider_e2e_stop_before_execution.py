"""Provider-stack e2e smoke: Gleason / PANDA stop-before-execution.

Plan-2026-04-30 dataset-provider-repair Task 9: with factory-built providers,
real curated seed, and ``download_policy="disabled"``, a Gleason prompt must:
- write ``.dataset/discovery.json`` and ``.dataset/acquisition_plan.json``,
- pick PANDA as the top relevant candidate (recorded in plan), and
- NEVER trigger a real Kaggle CLI call.

Like the dataset-discovery T12 e2e, this skips the heavyweight
``run_research_session`` entrypoint (which creates an OpenHands agent +
conversation) and exercises the actual integration directly via
``_run_acquisition_stage`` + ``_stop_before_execution``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


_SEED_PATH = (
    Path(__file__).parent.parent / "dataset" / "seed_data" / "pathology_datasets.json"
)


class _Session:
    def __init__(self, root: Path):
        self.workspace_dir = Path(root) / "ws"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.persistence_root = Path(root)


class _ConvState:
    def __init__(self):
        self.agent_state: dict = {}


class _StubConversation:
    def __init__(self):
        self.state = _ConvState()


class _DisabledPolicyConfig:
    """Mimics ``stop_before_execution=True``, ``download_policy="disabled"``."""

    data_mounts: dict = {}
    dataset_cache_dir: str = ""
    download_policy: str = "disabled"
    max_download_size_gb: float = 1.0
    allow_large_downloads: bool = False
    stop_before_execution: bool = True


def _gleason_state():
    from pathscientist.orchestrator.types import (
        ResearchObjective,
        ResearchSessionState,
        STAGE_ACQUISITION,
        STAGE_GROUNDING,
    )
    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(
            question="Train a Gleason grading model on prostate WSI",
        ),
    )
    state.task_profile = {
        "task_type": "mil_classification",
        "asset_level": "slide",
        "input_modality": "wsi",
        "label_granularity": "slide",
        "organ": "prostate",
        "prediction_target": "gleason_grading",
        "required_label_keywords": ["gleason", "ISUP", "grade"],
    }
    # Empty grounding is fine — the curated seed already has PANDA.
    state.grounding = {}
    state.advance(STAGE_GROUNDING)
    state.advance(STAGE_ACQUISITION)
    return state


def test_gleason_stop_before_execution_writes_discovery_plan_without_download(
    tmp_path, monkeypatch,
):
    from pathscientist.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )
    from pathscientist.dataset.discovery_store import discovery_path_for_workspace
    from pathscientist.orchestrator.runner import (
        _run_acquisition_stage,
        _stop_before_execution,
    )
    from pathscientist.orchestrator.types import STAGE_PRE_EXECUTION_READY

    # Belt-and-suspenders: make sure no Kaggle creds are in this env so
    # KaggleProvider.probe doesn't pretend they exist.
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)

    state = _gleason_state()
    session = _Session(tmp_path)
    cfg = _DisabledPolicyConfig()
    # Have the runner pick the real curated seed by pointing dataset_cache_dir
    # at a fresh dir — the runner copies the seed there on first use.
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, session, cfg)

    discovery_path = discovery_path_for_workspace(session.workspace_dir)
    plan_path = acquisition_plan_path_for_workspace(session.workspace_dir)
    assert discovery_path.exists()
    assert plan_path.exists()

    plan_payload = json.loads(plan_path.read_text())
    # Status under download_policy=disabled is skipped_policy or failed —
    # never prepared, never a crash.
    assert plan_payload["status"] in {"skipped_policy", "failed"}, plan_payload["status"]

    # PANDA is the top relevant Gleason candidate in the seed.
    panda_id = "kaggle:prostate-cancer-grade-assessment"
    assert any(c["dataset_id"] == panda_id for c in plan_payload["considered"])

    # task_profile recorded for review.
    assert plan_payload["task_profile"].get("prediction_target") == "gleason_grading"

    # Now stop-before-execution: brief gets persisted with both paths.
    state = _stop_before_execution(state, session, conversation=_StubConversation())
    assert state.stage == STAGE_PRE_EXECUTION_READY
    assert "Dataset discovery:" in state.execution_brief
    assert "Dataset acquisition plan:" in state.execution_brief


def test_gleason_e2e_does_not_invoke_kaggle_cli(tmp_path, monkeypatch):
    """Even if Kaggle creds happen to be present in env, a ``download_policy=
    "disabled"`` run must NOT shell out to Kaggle. We swap the factory's
    KaggleProvider for a runner-recording stub and assert it was never called."""
    import pathscientist.dataset.providers.factory as factory_mod
    from pathscientist.orchestrator.runner import _run_acquisition_stage

    monkeypatch.setenv("KAGGLE_USERNAME", "u")
    monkeypatch.setenv("KAGGLE_KEY", "k")

    invocations: list[list[str]] = []
    real_factory = factory_mod.build_default_providers

    def spying_factory():
        from pathscientist.dataset.providers.kaggle import KaggleProvider

        providers = real_factory()

        def _block(cmd, cwd=None):
            invocations.append(list(cmd))
            return 1, "", "blocked-by-test"

        providers["kaggle"] = KaggleProvider(runner=_block)
        return providers

    monkeypatch.setattr(factory_mod, "build_default_providers", spying_factory)

    state = _gleason_state()
    session = _Session(tmp_path)
    cfg = _DisabledPolicyConfig()
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    _run_acquisition_stage(state, session, cfg)

    # download_policy=disabled blocks BEFORE provider.download() runs.
    # Therefore the Kaggle CLI runner must never have been called.
    assert invocations == [], f"Kaggle CLI invoked under disabled policy: {invocations}"
