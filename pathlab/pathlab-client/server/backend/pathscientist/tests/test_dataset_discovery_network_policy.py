"""Tests for the NetworkPolicy dataset_discovery leg.

Phase E T11 of docs/plans/2026-04-30-pathscientist-literature-grounded-dataset-discovery-plan.md.

Backend-only this round. CLI flags / config field land in Phase 1.5
alongside --network=... / --no-online-papers / --allow-auto-ingest
(user CLI WIP territory). The env-var path lands now since it doesn't
touch the user's CLI files.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------- leg


def test_dataset_discovery_disabled_in_local_stage():
    from pathscientist.runtime.network_policy import NetworkPolicy

    policy = NetworkPolicy(stage="local", allow_dataset_discovery=True)
    assert policy.is_leg_enabled("dataset_discovery") is False


def test_dataset_discovery_enabled_in_auto_stage():
    from pathscientist.runtime.network_policy import NetworkPolicy

    policy = NetworkPolicy(stage="auto", allow_dataset_discovery=True)
    assert policy.is_leg_enabled("dataset_discovery") is True
    assert policy.allows_network("dataset_discovery") is True


def test_dataset_discovery_disabled_when_flag_off():
    from pathscientist.runtime.network_policy import NetworkPolicy

    policy = NetworkPolicy(stage="auto", allow_dataset_discovery=False)
    assert policy.is_leg_enabled("dataset_discovery") is False


def test_dataset_discovery_default_is_on():
    """Heuristic discovery is offline-safe so it defaults to enabled."""
    from pathscientist.runtime.network_policy import NetworkPolicy

    policy = NetworkPolicy(stage="auto")
    assert policy.allow_dataset_discovery is True


def test_dataset_discovery_cached_stage_disables_network_but_leg_remains_logical():
    """Stage 'cached' allows local artifacts only — leg is logically enabled
    but no fresh network calls."""
    from pathscientist.runtime.network_policy import NetworkPolicy

    policy = NetworkPolicy(stage="cached", allow_dataset_discovery=True)
    assert policy.is_leg_enabled("dataset_discovery") is True
    assert policy.allows_network("dataset_discovery") is False


# ---------------------------------------------------------------- env var


def test_env_var_disables_dataset_discovery_in_shim(monkeypatch):
    """``PATHSCIENTIST_DATASET_DISCOVERY=0`` disables via network_policy_from_config."""
    from pathscientist.runtime.network_policy import network_policy_from_config

    monkeypatch.setenv("PATHSCIENTIST_DATASET_DISCOVERY", "0")

    class _Cfg:
        pass

    policy = network_policy_from_config(_Cfg())
    assert policy.allow_dataset_discovery is False


def test_env_var_truthy_keeps_dataset_discovery_enabled(monkeypatch):
    """A truthy env value (or absence) leaves the default True alone."""
    from pathscientist.runtime.network_policy import network_policy_from_config

    monkeypatch.delenv("PATHSCIENTIST_DATASET_DISCOVERY", raising=False)

    class _Cfg:
        pass

    policy = network_policy_from_config(_Cfg())
    assert policy.allow_dataset_discovery is True


def test_config_attribute_overrides_default(monkeypatch):
    """``getattr(config, 'dataset_discovery_enabled', True)`` is honored."""
    monkeypatch.delenv("PATHSCIENTIST_DATASET_DISCOVERY", raising=False)
    from pathscientist.runtime.network_policy import network_policy_from_config

    class _Cfg:
        dataset_discovery_enabled = False

    policy = network_policy_from_config(_Cfg())
    assert policy.allow_dataset_discovery is False
