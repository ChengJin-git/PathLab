"""Tests for KaggleProvider.

Plan-2026-04-30 dataset-provider-repair Task 4: PANDA / Kaggle datasets
need a real provider. Credentials gate is opt-in via env or
``~/.kaggle/kaggle.json``; CLI runner is injectable for tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _record(kind="kaggle_competition", remote_id="prostate-cancer-grade-assessment"):
    from autoresearch.dataset.types import DatasetRecord, DownloadSpec
    return DatasetRecord(
        dataset_id="kaggle:panda",
        name="PANDA",
        provider="kaggle",
        access="manual",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        organs=["prostate"],
        tags=["gleason", "ISUP"],
        estimated_size_gb=400.0,
        download=DownloadSpec(kind=kind, remote_id=remote_id),
    )


def _download_command(calls: list[list[str]], group: str) -> list[str]:
    for cmd in calls:
        if len(cmd) >= 3 and Path(cmd[0]).name == "kaggle" and cmd[1:3] == [group, "download"]:
            return cmd
    return []


# ---------------------------------------------------------------- probe


def test_kaggle_probe_tags_missing_credentials_via_env(monkeypatch):
    from autoresearch.dataset.providers.kaggle import KaggleProvider

    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    out = KaggleProvider(kaggle_json_path=Path("/missing/kaggle.json")).probe(_record())
    assert out.access == "manual"
    assert "probe:kaggle_credentials_missing" in out.tags


def test_kaggle_probe_tags_credentials_present_via_env(monkeypatch):
    from autoresearch.dataset.providers.kaggle import KaggleProvider

    monkeypatch.setenv("KAGGLE_USERNAME", "u")
    monkeypatch.setenv("KAGGLE_KEY", "k")
    out = KaggleProvider(kaggle_json_path=Path("/missing/kaggle.json")).probe(_record())
    assert out.access == "manual"   # NEVER upgraded by probe
    assert "probe:kaggle_credentials_present" in out.tags


def test_kaggle_probe_tags_credentials_present_via_kaggle_json(tmp_path, monkeypatch):
    from autoresearch.dataset.providers.kaggle import KaggleProvider

    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    json_path = tmp_path / "kaggle.json"
    json_path.write_text('{"username": "u", "key": "k"}')
    out = KaggleProvider(kaggle_json_path=json_path).probe(_record())
    assert "probe:kaggle_credentials_present" in out.tags


# ---------------------------------------------------------------- download


def test_kaggle_download_skips_without_credentials(tmp_path, monkeypatch):
    from autoresearch.dataset.providers.kaggle import KaggleProvider

    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    result = KaggleProvider(kaggle_json_path=Path("/missing/kaggle.json")).download(
        _record(), tmp_path,
    )
    assert result.status == "skipped_policy"
    assert result.reason == "missing_kaggle_credentials"


def test_kaggle_competition_download_invokes_competition_cli(tmp_path, monkeypatch):
    from autoresearch.dataset.providers.kaggle import KaggleProvider

    monkeypatch.setenv("KAGGLE_USERNAME", "u")
    monkeypatch.setenv("KAGGLE_KEY", "k")
    calls: list[list[str]] = []

    def runner(cmd, cwd=None):
        calls.append(list(cmd))
        (tmp_path / "train_images.zip").write_bytes(b"x")
        return 0, "", ""

    result = KaggleProvider(runner=runner).download(_record(), tmp_path)
    assert result.status == "downloaded"
    download_cmd = _download_command(calls, "competitions")
    assert download_cmd
    assert "prostate-cancer-grade-assessment" in download_cmd
    assert "--force" not in download_cmd
    assert any(p.name == "train_images.zip" for p in result.files)


def test_kaggle_dataset_download_invokes_dataset_cli(tmp_path, monkeypatch):
    from autoresearch.dataset.providers.kaggle import KaggleProvider

    monkeypatch.setenv("KAGGLE_USERNAME", "u")
    monkeypatch.setenv("KAGGLE_KEY", "k")
    calls: list[list[str]] = []

    def runner(cmd, cwd=None):
        calls.append(list(cmd))
        (tmp_path / "data.zip").write_bytes(b"x")
        return 0, "", ""

    result = KaggleProvider(runner=runner).download(
        _record(kind="kaggle_dataset", remote_id="owner/name"), tmp_path,
    )
    assert result.status == "downloaded"
    download_cmd = _download_command(calls, "datasets")
    assert download_cmd
    assert "owner/name" in download_cmd
    assert "--force" not in download_cmd


def test_kaggle_download_returns_failed_on_nonzero_exit(tmp_path, monkeypatch):
    from autoresearch.dataset.providers.kaggle import KaggleProvider

    monkeypatch.setenv("KAGGLE_USERNAME", "u")
    monkeypatch.setenv("KAGGLE_KEY", "k")

    def runner(cmd, cwd=None):
        return 1, "", "auth failed"

    result = KaggleProvider(runner=runner).download(_record(), tmp_path)
    assert result.status == "failed"
    assert "kaggle_error" in result.reason
    assert "auth failed" in result.reason


def test_kaggle_unsupported_kind_returns_skipped_policy(tmp_path, monkeypatch):
    from autoresearch.dataset.providers.kaggle import KaggleProvider

    monkeypatch.setenv("KAGGLE_USERNAME", "u")
    monkeypatch.setenv("KAGGLE_KEY", "k")
    result = KaggleProvider(runner=lambda *a, **k: (0, "", "")).download(
        _record(kind="manual", remote_id=""), tmp_path,
    )
    assert result.status == "skipped_policy"
    assert "kaggle_unsupported_kind" in result.reason or "no_remote_id" in result.reason


def test_kaggle_provider_has_provider_name():
    from autoresearch.dataset.providers.kaggle import KaggleProvider
    assert KaggleProvider().provider_name == "kaggle"
