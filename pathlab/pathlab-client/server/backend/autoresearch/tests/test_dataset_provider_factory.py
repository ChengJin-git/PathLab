"""Tests for the centralized dataset provider factory.

Plan-2026-04-30 dataset-provider-repair Task 1: provider construction
moves out of ``orchestrator/runner.py`` into ``dataset/providers/factory.py``
so adding new providers (Kaggle, GDC, ...) doesn't require runner edits.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def test_default_factory_contains_current_core_providers():
    from autoresearch.dataset.providers.factory import build_default_providers

    providers = build_default_providers()
    assert "direct_http" in providers
    assert "zenodo" in providers
    assert "huggingface" in providers


def test_default_factory_returns_provider_instances():
    """Each entry must respect the DatasetProvider Protocol.

    Plan-2026-04-30 dataset-provider-repair Task 5: ``"tcia"`` is an
    intentional alias to the GDC provider, so its ``provider_name`` is
    ``"gdc"``. Skip the strict name match for that alias.
    """
    from autoresearch.dataset.providers.factory import build_default_providers

    aliased = {"tcia": "gdc"}
    providers = build_default_providers()
    for name, p in providers.items():
        assert hasattr(p, "probe"), f"{name} missing probe()"
        assert hasattr(p, "download"), f"{name} missing download()"
        expected_name = aliased.get(name, name)
        assert getattr(p, "provider_name", "") == expected_name, (
            f"{name}: provider_name attribute must match registry key (or its alias)"
        )


def test_default_factory_returns_fresh_instances_each_call():
    """Avoid singleton state leaking between sessions/tests."""
    from autoresearch.dataset.providers.factory import build_default_providers

    a = build_default_providers()
    b = build_default_providers()
    assert a["direct_http"] is not b["direct_http"]


def test_runner_uses_provider_factory(tmp_path, monkeypatch):
    """``_run_acquisition_stage`` must call the factory rather than instantiating
    providers inline; otherwise new providers can't reach the runner without
    a runner edit."""
    import autoresearch.dataset.providers.factory as factory_mod
    import autoresearch.orchestrator.runner as runner_mod

    called = {"hits": 0}
    real = factory_mod.build_default_providers

    def spy():
        called["hits"] += 1
        return real()

    monkeypatch.setattr(factory_mod, "build_default_providers", spy)
    # The runner must look it up via the same module attribute, otherwise
    # patching here wouldn't intercept. Patch the imported reference too.
    if hasattr(runner_mod, "build_default_providers"):
        monkeypatch.setattr(runner_mod, "build_default_providers", spy)

    # Reuse the existing test harness style.
    from autoresearch.orchestrator.types import (
        ResearchObjective,
        ResearchSessionState,
        STAGE_ACQUISITION,
        STAGE_GROUNDING,
    )

    class _Session:
        def __init__(self, root):
            self.workspace_dir = Path(root) / "ws"
            self.workspace_dir.mkdir(parents=True, exist_ok=True)
            self.persistence_root = Path(root)

    class _Config:
        data_mounts: dict = {}
        dataset_cache_dir = ""
        download_policy = "disabled"
        max_download_size_gb = 1.0
        allow_large_downloads = False

    state = ResearchSessionState.create(
        session_id="s",
        conversation_id="c",
        objective=ResearchObjective(question="CRC MSI"),
    )
    state.task_profile = {
        "task_type": "patch_classification",
        "asset_level": "patch",
        "input_modality": "patch_images",
        "label_granularity": "patch",
        "organ": "colorectal",
        "prediction_target": "microsatellite_instability",
        "required_label_keywords": ["MSI"],
    }
    state.grounding = {}
    state.advance(STAGE_GROUNDING)
    state.advance(STAGE_ACQUISITION)

    cfg = _Config()
    cfg.dataset_cache_dir = str(tmp_path / "ds_cache")

    runner_mod._run_acquisition_stage(state, _Session(tmp_path), cfg)
    assert called["hits"] >= 1, "runner must consume build_default_providers()"
