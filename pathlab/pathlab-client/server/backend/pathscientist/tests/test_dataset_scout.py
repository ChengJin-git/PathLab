from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataset.policy import AcquisitionPolicy
from dataset.registry import DatasetRegistry
from dataset.scout import DatasetCandidate, DatasetScout
from dataset.types import DatasetRecord, DownloadSpec, TaskProfile


@pytest.fixture
def populated_registry(tmp_path: Path) -> DatasetRegistry:
    """Three records: matching-task+matching-organ public, matching-task wrong-organ public, off-task gated."""
    records = [
        DatasetRecord(
            dataset_id="a",
            name="CRC patches small",
            provider="huggingface",
            access="public",
            task_types=["patch_classification"],
            asset_types=["patch_images"],
            organs=["colorectal"],
            estimated_size_gb=1.0,
            download=DownloadSpec(kind="hf_dataset", remote_id="org/a"),
        ),
        DatasetRecord(
            dataset_id="b",
            name="Lung patches",
            provider="zenodo",
            access="public",
            task_types=["patch_classification"],
            asset_types=["patch_images"],
            organs=["lung"],
            estimated_size_gb=1.0,
            download=DownloadSpec(kind="direct_http", urls=["https://example.org/b.zip"]),
        ),
        DatasetRecord(
            dataset_id="c",
            name="Survival lung gated",
            provider="tcia",
            access="gated",
            task_types=["survival_analysis"],
            asset_types=["clinical_table"],
            organs=["lung"],
            estimated_size_gb=2.0,
            download=DownloadSpec(kind="manual"),
        ),
    ]
    reg = DatasetRegistry(tmp_path / "datasets.json")
    reg.save(records)
    return reg


def test_scout_ranks_same_task_same_organ_first(populated_registry):
    scout = DatasetScout(registry=populated_registry, policy=AcquisitionPolicy(max_download_size_gb=50))
    profile = TaskProfile(
        task_type="patch_classification",
        asset_level="patch",
        input_modality="patch_images",
        label_granularity="patch",
        organ="colorectal",
    )
    candidates = scout.find_candidates(profile, top_k=3)
    assert candidates[0].record.dataset_id == "a"
    assert candidates[0].decision.allowed is True
    assert "task_type_match" in candidates[0].reasons
    assert "organ_match" in candidates[0].reasons


def test_scout_marks_policy_rejection(populated_registry):
    scout = DatasetScout(registry=populated_registry, policy=AcquisitionPolicy(download_policy="public_only"))
    profile = TaskProfile(
        task_type="survival_analysis",
        asset_level="slide",
        input_modality="clinical_table",
        label_granularity="slide",
        organ="lung",
    )
    candidates = scout.find_candidates(profile, top_k=3)
    rec_c = next(c for c in candidates if c.record.dataset_id == "c")
    assert rec_c.decision.allowed is False
    assert any("policy_reject" in r for r in rec_c.reasons)
    assert rec_c.score < 0


def test_scout_returns_top_k(populated_registry):
    scout = DatasetScout(registry=populated_registry)
    profile = TaskProfile(
        task_type="patch_classification",
        asset_level="patch",
        input_modality="patch_images",
        label_granularity="patch",
        organ="colorectal",
    )
    assert len(scout.find_candidates(profile, top_k=1)) == 1
    assert len(scout.find_candidates(profile, top_k=10)) == 3   # only 3 records exist


def test_scout_default_policy_blocks_oversize_records(tmp_path: Path):
    record = DatasetRecord(
        dataset_id="big",
        name="Big patches",
        provider="huggingface",
        access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=["colorectal"],
        estimated_size_gb=500.0,
        download=DownloadSpec(kind="hf_dataset", remote_id="org/big"),
    )
    reg = DatasetRegistry(tmp_path / "datasets.json")
    reg.save([record])
    scout = DatasetScout(registry=reg)   # default policy: max 20GB
    candidates = scout.find_candidates(
        TaskProfile(
            task_type="patch_classification",
            asset_level="patch",
            input_modality="patch_images",
            label_granularity="patch",
            organ="colorectal",
        ),
        top_k=1,
    )
    assert candidates[0].decision.allowed is False
    assert "too_large" in candidates[0].decision.reason


def test_scout_keyword_match_adds_score(tmp_path: Path):
    rec = DatasetRecord(
        dataset_id="kw",
        name="MSI Colorectal Cohort",
        provider="huggingface",
        access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=[],
        tags=["msi", "colon"],
        estimated_size_gb=1.0,
        download=DownloadSpec(kind="hf_dataset", remote_id="x/y"),
    )
    reg = DatasetRegistry(tmp_path / "ds.json")
    reg.save([rec])
    scout = DatasetScout(registry=reg)
    profile = TaskProfile(
        task_type="patch_classification",
        asset_level="patch",
        input_modality="patch_images",
        label_granularity="patch",
        organ="",
        dataset_keywords=["msi"],
    )
    cand = scout.find_candidates(profile, top_k=1)[0]
    # 5 (task) + 2 (asset) + 1 (keyword msi) = 8
    assert cand.score == pytest.approx(8.0)
    assert any("keyword:msi" in r for r in cand.reasons)


def test_scout_empty_registry_returns_empty(tmp_path: Path):
    reg = DatasetRegistry(tmp_path / "empty.json")
    scout = DatasetScout(registry=reg)
    candidates = scout.find_candidates(
        TaskProfile(
            task_type="patch_classification",
            asset_level="patch",
            input_modality="patch_images",
            label_granularity="patch",
        ),
        top_k=5,
    )
    assert candidates == []
