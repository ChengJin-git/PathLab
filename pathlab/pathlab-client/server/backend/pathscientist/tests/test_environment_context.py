"""Tests for context.detect_hf_model_cache + build_environment_context.

Motivated by session_e95aaf19aba4 (2026-04-21) whose agent reasoned
"No network access (can't download UNI2/CONCH). Only cached model is
DINOv2 ViT-S/16 (small)" and fell back to an ImageNet baseline, even
though HF_HOME actually contained UNI/UNI2/CONCH/Virchow/Virchow2/
H-Optimus/Phikon weights.

Root cause: environment_context listed GPUs, packages, PathLab common/
libs but said nothing about the local model cache. The agent read the
"do not use network access" rule literally and concluded HF weights
were unreachable.

This file locks in the fix:

* detect_hf_model_cache surfaces the pathology FMs actually present on
  disk, with load instructions that explicitly say the cache works
  offline.
* build_environment_context includes the new section.
* The "no cache present" branch does not silently claim pathology FMs
  are available when they aren't.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.context import (
    build_environment_context,
    detect_hf_model_cache,
)


def _make_fake_cache(root: Path, model_repos: list[str]) -> None:
    """Populate a fake HF hub directory with empty model dirs."""
    hub = root / "hub"
    hub.mkdir(parents=True, exist_ok=True)
    for repo in model_repos:
        name = "models--" + repo.replace("/", "--")
        (hub / name).mkdir(parents=True, exist_ok=True)


def test_detect_hf_model_cache_lists_pathology_fms(tmp_path, monkeypatch):
    """When HF_HOME holds UNI / CONCH / Virchow dirs, the environment
    block must name each by its common alias (UNI2, CONCH, Virchow2 ...)
    so the agent can pick from them without guessing."""
    _make_fake_cache(
        tmp_path,
        [
            "MahmoodLab/UNI2-h",
            "MahmoodLab/uni",
            "MahmoodLab/conch",
            "paige-ai/Virchow2",
            "bioptimus/H-optimus-1",
        ],
    )
    monkeypatch.setenv("HF_HOME", str(tmp_path))

    out = detect_hf_model_cache()

    assert "UNI2" in out
    assert "UNI " in out or "UNI2" in out  # UNI bare token OR UNI2
    assert "CONCH" in out
    assert "Virchow2" in out
    assert "H-Optimus-1" in out
    assert "no network needed" in out.lower() or "offline" in out.lower()


def test_detect_hf_model_cache_empty_is_explicit(tmp_path, monkeypatch):
    """When the cache exists but has no pathology FMs, the block must
    say so EXPLICITLY so the agent knows to fall back — not invent
    cache contents that aren't there."""
    (tmp_path / "hub").mkdir()
    # Only populate a non-pathology model so the cache is "present but empty"
    # for our purposes.
    _make_fake_cache(tmp_path, ["bert-base-uncased"])
    monkeypatch.setenv("HF_HOME", str(tmp_path))

    out = detect_hf_model_cache()

    # Must not falsely claim UNI / CONCH are available.
    assert "UNI" not in out
    assert "CONCH" not in out
    # Must explicitly tell the agent none of the pathology FMs are cached.
    assert "no pathology foundation models" in out.lower()


def test_detect_hf_model_cache_missing_dir(tmp_path, monkeypatch):
    """When HF_HOME/hub does not exist, surface that clearly. The agent
    must not be misled into thinking pathology FMs are loadable."""
    monkeypatch.setenv("HF_HOME", str(tmp_path / "does-not-exist"))

    out = detect_hf_model_cache()

    # The block must explicitly state the cache is unavailable — this is
    # the signal the agent keys on to avoid attempting fresh downloads.
    assert "not present" in out.lower()
    # There must be NO "loadable offline" / "no network needed" claim in
    # the missing-dir case; that wording is reserved for the populated
    # branch and would mislead the agent here.
    assert "no network needed" not in out.lower()
    assert "loadable offline" not in out.lower()


def test_build_environment_context_includes_hf_cache_section(tmp_path, monkeypatch):
    """build_environment_context must compose the HF cache block into
    the full environment string so it actually reaches the agent system
    prompt."""
    _make_fake_cache(
        tmp_path,
        [
            "MahmoodLab/UNI2-h",
            "MahmoodLab/conch",
        ],
    )
    monkeypatch.setenv("HF_HOME", str(tmp_path))

    out = build_environment_context()

    # New HF cache block must appear alongside the existing GPU / packages
    # / common libs blocks.
    assert "Pre-cached HuggingFace models" in out
    assert "UNI2" in out
    assert "CONCH" in out

    # The explicit no-network-needed statement must survive composition.
    assert "no network" in out.lower() or "offline" in out.lower()


def test_detect_hf_model_cache_surfaces_cache_path(tmp_path, monkeypatch):
    """The cache location must be printed so the agent can inspect it
    via the terminal tool if it needs to verify a model is really there
    before committing to using it."""
    _make_fake_cache(tmp_path, ["MahmoodLab/uni"])
    monkeypatch.setenv("HF_HOME", str(tmp_path))

    out = detect_hf_model_cache()

    assert str(tmp_path) in out
    assert "HF_HOME" in out
