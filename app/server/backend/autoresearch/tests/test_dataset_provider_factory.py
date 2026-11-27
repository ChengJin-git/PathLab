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
