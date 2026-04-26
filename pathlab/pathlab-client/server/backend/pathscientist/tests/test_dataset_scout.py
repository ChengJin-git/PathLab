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


# ---- Review fix R2 (P1): relevance gating ----


def test_scout_marks_organ_only_match_as_not_relevant(tmp_path):
    """Organ match without task_type match is NOT relevant — prevents
    picking a patch dataset when the profile asks for MIL."""
    rec = DatasetRecord(
        dataset_id="patch-only", name="Breast Patches",
        provider="huggingface", access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=["breast"], estimated_size_gb=1.0,
        download=DownloadSpec(kind="hf_dataset", remote_id="x/y"),
    )
    reg = DatasetRegistry(tmp_path / "ds.json")
    reg.save([rec])
    scout = DatasetScout(registry=reg)
    profile = TaskProfile(
        task_type="mil_classification", asset_level="slide",
        input_modality="wsi", label_granularity="slide", organ="breast",
    )
    cand = scout.find_candidates(profile, top_k=1)[0]
    assert cand.relevant is False
    assert "not_relevant" in cand.reasons


def test_scout_marks_exact_task_match_as_relevant(tmp_path):
    rec = DatasetRecord(
        dataset_id="patch-public", name="CRC Patches",
        provider="huggingface", access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=["colorectal"], estimated_size_gb=1.0,
        download=DownloadSpec(kind="hf_dataset", remote_id="x/y"),
    )
    reg = DatasetRegistry(tmp_path / "ds.json")
    reg.save([rec])
    scout = DatasetScout(registry=reg)
    profile = TaskProfile(
        task_type="patch_classification", asset_level="patch",
        input_modality="patch_images", label_granularity="patch",
        organ="colorectal",
    )
    cand = scout.find_candidates(profile, top_k=1)[0]
    assert cand.relevant is True
    assert "not_relevant" not in cand.reasons


def test_scout_marks_asset_plus_keyword_as_relevant(tmp_path):
    rec = DatasetRecord(
        dataset_id="x", name="Breast WSI Cohort",
        provider="huggingface", access="public",
        task_types=["segmentation"],
        asset_types=["wsi"],
        organs=["breast"], tags=["histology"],
        estimated_size_gb=1.0,
        download=DownloadSpec(kind="hf_dataset", remote_id="x/y"),
    )
    reg = DatasetRegistry(tmp_path / "ds.json")
    reg.save([rec])
    scout = DatasetScout(registry=reg)
    # Different task_type but same asset + keyword "wsi" hits.
    profile = TaskProfile(
        task_type="mil_classification", asset_level="slide",
        input_modality="wsi", label_granularity="slide", organ="breast",
        dataset_keywords=["wsi"],
    )
    cand = scout.find_candidates(profile, top_k=1)[0]
    assert cand.relevant is True


def test_scout_score_zero_record_is_not_relevant(tmp_path):
    rec = DatasetRecord(
        dataset_id="z", name="Zero Match Lung Survival",
        provider="zenodo", access="public",
        task_types=["survival_analysis"],
        asset_types=["clinical_table"],
        organs=["lung"], estimated_size_gb=1.0,
        download=DownloadSpec(kind="direct_http", urls=["https://example.org/x.zip"]),
    )
    reg = DatasetRegistry(tmp_path / "ds.json")
    reg.save([rec])
    scout = DatasetScout(registry=reg)
    profile = TaskProfile(
        task_type="patch_classification", asset_level="patch",
        input_modality="patch_images", label_granularity="patch",
        organ="colorectal",
    )
    cand = scout.find_candidates(profile, top_k=1)[0]
    assert cand.relevant is False
    assert cand.score == 0


def test_scout_dataclass_default_relevant_is_false():
    """A bare DatasetCandidate() must default relevant=False."""
    from dataset.scout import DatasetCandidate
    from dataset.policy import PolicyDecision
    rec = DatasetRecord(
        dataset_id="x", name="x", provider="huggingface", access="public",
        task_types=["patch_classification"], asset_types=["patch_images"],
        organs=[], estimated_size_gb=1.0,
        download=DownloadSpec(kind="hf_dataset", remote_id="x"),
    )
    cand = DatasetCandidate(record=rec, score=0.0, decision=PolicyDecision(True, "ok"))
    assert cand.relevant is False


# ---- Review fix R2-followup (P1): relevance is a primary sort key, not a tiebreaker ----


def test_scout_keeps_relevant_blocked_candidate_above_irrelevant_top_k(tmp_path):
    """R2-followup: 11 irrelevant + 1 relevant blocked. The relevant one
    must NOT be truncated out of top_k=10."""
    records = []
    # 11 irrelevant public records (no task match, no asset match against a MIL profile)
    for i in range(11):
        records.append(DatasetRecord(
            dataset_id=f"public-irrel-{i}",
            name=f"Irrelevant {i}",
            provider="huggingface",
            access="public",
            task_types=["patch_classification"],
            asset_types=["patch_images"],
            organs=["colorectal"],
            estimated_size_gb=1.0,
            download=DownloadSpec(kind="hf_dataset", remote_id=f"x/{i}"),
        ))
    # 1 relevant gated MIL record
    records.append(DatasetRecord(
        dataset_id="gated-mil",
        name="Gated MIL Cohort",
        provider="huggingface",
        access="gated",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        organs=["lung"], estimated_size_gb=2.0,
        download=DownloadSpec(kind="hf_dataset", remote_id="g"),
    ))
    reg = DatasetRegistry(tmp_path / "ds.json")
    reg.save(records)
    scout = DatasetScout(registry=reg, policy=AcquisitionPolicy(download_policy="public_only"))
    profile = TaskProfile(
        task_type="mil_classification", asset_level="slide",
        input_modality="wsi", label_granularity="slide", organ="lung",
    )
    candidates = scout.find_candidates(profile, top_k=10)
    # The relevant gated MIL record must appear in the top_k window even
    # though its score is negative (policy rejection penalty).
    relevant = [c for c in candidates if c.relevant]
    assert len(relevant) == 1
    assert relevant[0].record.dataset_id == "gated-mil"
    assert relevant[0].decision.allowed is False


def test_scout_relevant_records_sort_above_irrelevant(tmp_path):
    """Within the candidate list, all relevant records come before irrelevant
    ones, regardless of score sign."""
    records = [
        # Irrelevant high score: task=patch matches against patch profile.
        DatasetRecord(
            dataset_id="hi-irrel",
            name="High score irrel",
            provider="huggingface", access="public",
            task_types=["patch_classification"],
            asset_types=["patch_images"],
            organs=["colorectal"], estimated_size_gb=1.0,
            download=DownloadSpec(kind="hf_dataset", remote_id="x"),
        ),
        # Relevant low score: task=mil + gated penalty.
        DatasetRecord(
            dataset_id="lo-rel",
            name="Low score relevant",
            provider="huggingface", access="gated",
            task_types=["mil_classification"],
            asset_types=["wsi"],
            organs=[], estimated_size_gb=1.0,
            download=DownloadSpec(kind="hf_dataset", remote_id="y"),
        ),
    ]
    # Score against a MIL profile: hi-irrel scores 0 (no match), lo-rel scores 5-100=-95.
    reg = DatasetRegistry(tmp_path / "ds.json")
    reg.save(records)
    scout = DatasetScout(registry=reg, policy=AcquisitionPolicy(download_policy="public_only"))
    profile = TaskProfile(
        task_type="mil_classification", asset_level="slide",
        input_modality="wsi", label_granularity="slide",
    )
    candidates = scout.find_candidates(profile, top_k=5)
    # Even though lo-rel has a much lower score, it should sort first because
    # it's the only relevant candidate.
    assert candidates[0].record.dataset_id == "lo-rel"
    assert candidates[0].relevant is True
    assert candidates[1].record.dataset_id == "hi-irrel"
    assert candidates[1].relevant is False
