"""Gleason/PANDA acquisition behavior characterization.

Plan-2026-04-30 dataset-provider-repair Task 7: locks the policy contract
for the prototypical large/manual Kaggle dataset (PANDA).

These tests use the *real* curated seed (``dataset/seed_data/pathology_datasets.json``).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


_SEED_PATH = (
    Path(__file__).parent.parent / "dataset" / "seed_data" / "pathology_datasets.json"
)
_PANDA_ID = "kaggle:prostate-cancer-grade-assessment"


def _gleason_profile():
    from pathscientist.dataset.types import TaskProfile
    return TaskProfile(
        task_type="mil_classification",
        asset_level="slide",
        input_modality="wsi",
        label_granularity="slide",
        organ="prostate",
        prediction_target="gleason_grading",
        required_label_keywords=["gleason", "ISUP", "grade"],
    )


def _service(tmp_path, *, policy, providers=None):
    from pathscientist.dataset.acquisition import DatasetAcquisitionService
    from pathscientist.dataset.providers.factory import build_default_providers
    from pathscientist.dataset.registry import DatasetRegistry

    registry = DatasetRegistry(_SEED_PATH)
    return DatasetAcquisitionService(
        registry=registry,
        providers=providers if providers is not None else build_default_providers(),
        normalizers=[],
        cache_root=tmp_path / "cache",
        policy=policy,
    )


def test_panda_is_selected_but_blocked_under_public_only(tmp_path):
    """Gleason → PANDA wins relevance, but public_only refuses access=manual."""
    from pathscientist.dataset.policy import AcquisitionPolicy

    service = _service(
        tmp_path,
        policy=AcquisitionPolicy(
            download_policy="public_only",
            max_download_size_gb=20,
        ),
    )
    result = service.acquire(_gleason_profile(), workspace_root=tmp_path / "ws")
    assert result.status == "skipped_policy"
    assert result.candidate is not None
    assert result.candidate.record.dataset_id == _PANDA_ID
    assert "access=manual" in result.reason


def test_panda_is_blocked_as_too_large_under_manual_without_large_flag(tmp_path):
    """manual_only allows access=manual but max_size=20GB blocks PANDA's 400GB."""
    from pathscientist.dataset.policy import AcquisitionPolicy

    service = _service(
        tmp_path,
        policy=AcquisitionPolicy(
            download_policy="manual_only",
            max_download_size_gb=20,
            allow_large_downloads=False,
        ),
    )
    result = service.acquire(_gleason_profile(), workspace_root=tmp_path / "ws")
    assert result.status == "skipped_policy"
    assert result.candidate.record.dataset_id == _PANDA_ID
    assert result.reason == "too_large"


def test_panda_reaches_kaggle_provider_when_manual_large_allowed(tmp_path, monkeypatch):
    """With manual_only + allow_large + creds, PANDA passes policy and the
    Kaggle CLI runner is invoked. We don't actually shell out — fake runner
    returns a fake archive so the test can confirm download semantics."""
    from pathscientist.dataset.policy import AcquisitionPolicy
    from pathscientist.dataset.providers.factory import build_default_providers
    from pathscientist.dataset.providers.kaggle import KaggleProvider

    monkeypatch.setenv("KAGGLE_USERNAME", "u")
    monkeypatch.setenv("KAGGLE_KEY", "k")

    captured_cmd: list[list[str]] = []

    def fake_runner(cmd, cwd=None):
        captured_cmd.append(list(cmd))
        Path(cwd).mkdir(parents=True, exist_ok=True)
        # Write a non-archive file so the "no normalizer" branch is what
        # actually short-circuits the test (rather than archive extract).
        (Path(cwd) / "train.csv").write_bytes(b"slide_id,label\n1,3\n")
        return 0, "", ""

    providers = build_default_providers()
    providers["kaggle"] = KaggleProvider(runner=fake_runner)

    service = _service(
        tmp_path,
        policy=AcquisitionPolicy(
            download_policy="manual_only",
            max_download_size_gb=500,
            allow_large_downloads=True,
        ),
        providers=providers,
    )
    result = service.acquire(_gleason_profile(), workspace_root=tmp_path / "ws")

    # Policy + provider both passed → the Kaggle CLI was invoked.
    assert captured_cmd, "Kaggle runner must be called"
    download_cmds = [
        cmd for cmd in captured_cmd
        if len(cmd) >= 3
        and Path(cmd[0]).name == "kaggle"
        and cmd[1:3] == ["competitions", "download"]
    ]
    assert download_cmds, "Kaggle competition download must be invoked"
    assert "prostate-cancer-grade-assessment" in download_cmds[0]
    # Selected was PANDA.
    assert result.candidate.record.dataset_id == _PANDA_ID
    # No normalizer is registered (we passed normalizers=[]), so this lands
    # at no_normalizer rather than prepared. Either is acceptable; we only
    # care that we got past policy and into the provider.
    assert result.status in {"failed", "prepared"}
    assert result.status != "skipped_policy"


def test_panda_relevance_does_not_match_msi_profile(tmp_path):
    """Sanity: PANDA must NOT be picked for an MSI/colorectal prompt."""
    from pathscientist.dataset.policy import AcquisitionPolicy
    from pathscientist.dataset.types import TaskProfile

    msi_profile = TaskProfile(
        task_type="patch_classification",
        asset_level="patch", input_modality="patch_images",
        label_granularity="patch", organ="colorectal",
        prediction_target="microsatellite_instability",
        required_label_keywords=["MSI", "MSI-H", "MSS"],
    )
    service = _service(
        tmp_path,
        policy=AcquisitionPolicy(
            download_policy="manual_only", max_download_size_gb=500,
            allow_large_downloads=True,
        ),
    )
    result = service.acquire(msi_profile, workspace_root=tmp_path / "ws")
    if result.candidate is not None:
        assert result.candidate.record.dataset_id != _PANDA_ID
