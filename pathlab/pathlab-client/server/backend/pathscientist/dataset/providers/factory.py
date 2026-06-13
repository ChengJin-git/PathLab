"""Centralized dataset provider factory.

Plan-2026-04-30 dataset-provider-repair Task 1: provider construction
moves out of ``orchestrator/runner.py`` so adding new providers
(``KaggleProvider`` / ``GDCProvider`` / ...) doesn't require a runner
edit each time.

Each call returns *fresh* instances so injected sessions / runners /
credentials in one test or session do not leak into the next.
"""
from __future__ import annotations

from .base import DatasetProvider
from .direct_http import DirectHTTPProvider
from .gdc import GDCProvider
from .huggingface import HuggingFaceProvider
from .kaggle import KaggleProvider
from .scidb import SciDBProvider
from .zenodo import ZenodoProvider


def build_default_providers() -> dict[str, DatasetProvider]:
    """Return the default provider map keyed by ``DatasetRecord.provider``.

    Plan-2026-04-30 dataset-provider-repair Tasks 4 / 5: Kaggle handles
    PANDA-style records; GDC handles TCGA / GDC, with ``"tcia"`` aliased
    to the same instance so legacy seed records reach a meaningful
    adapter rather than ``no_provider:tcia``.
    """
    gdc = GDCProvider()
    return {
        "direct_http": DirectHTTPProvider(),
        "zenodo": ZenodoProvider(),
        "huggingface": HuggingFaceProvider(),
        "kaggle": KaggleProvider(),
        "scidb": SciDBProvider(),
        "gdc": gdc,
        "tcia": gdc,
    }
