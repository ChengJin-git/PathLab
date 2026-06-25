"""Tests for dataset discovery extraction from grounding outputs.

Phase A T3 of docs/plans/2026-04-30-autoresearch-literature-grounded-dataset-discovery-plan.md.

Source priority (review-update bullets 4 + 5):
1. baselines (structured)
2. sota_target (structured)
3. papers[].datasets (structured)
4. dataset_hint_candidates (LLM hints)
5. passages regex (LAST resort, denylisted)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _profile():
    from autoresearch.dataset.types import TaskProfile
    return TaskProfile(
        task_type="patch_classification",
        asset_level="patch",
        input_modality="patch_images",
        label_granularity="patch",
        organ="colorectal",
        prediction_target="microsatellite_instability",
        required_label_keywords=["MSI", "MSI-H", "MSS"],
    )


# ---------------------------------------------------------------- baselines


def test_extracts_baseline_dataset_with_task_profile_semantics():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    grounding = {
        "baselines": [
            {
                "dataset": "CRC-MSI",
                "method": "DSMIL",
                "paper_id": "openalex:W123",
                "paper_title": "MSI prediction from pathology",
                "context": "DSMIL reports AUC on CRC-MSI.",
            }
        ]
    }
    records = extract_dataset_candidates(grounding, _profile())
    assert len(records) == 1
    rec = records[0]
    assert rec.name == "CRC-MSI"
    assert rec.prediction_target == "microsatellite_instability"
    assert rec.label_keywords == ["MSI", "MSI-H", "MSS"]
    assert rec.task_types == ["patch_classification"]
    assert rec.asset_types == ["patch_images"]
    assert rec.organs == ["colorectal"]
    assert rec.confidence == "medium"
    assert rec.evidence[0].source == "baseline"
    assert rec.evidence[0].paper_id == "openalex:W123"


def test_baseline_paper_id_is_canonicalized_when_legacy_shape():
    """Raw 'W123' (no scheme prefix) gets normalized to 'openalex:W123'."""
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    grounding = {
        "baselines": [
            {"dataset": "CRC-MSI", "paper_id": "W123", "context": "AUC."}
        ]
    }
    records = extract_dataset_candidates(grounding, _profile())
    assert records
    assert records[0].evidence[0].paper_id == "openalex:W123"


# ---------------------------------------------------------------- sota_target


def test_extracts_sota_target_dataset():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    grounding = {
        "sota_target": {
            "dataset": "PANDA",
            "task_type": "patch_classification",
            "metric_name": "kappa",
            "metric_value": 0.85,
            "paper_id": "10.1038/s41591-020-1122-y",
            "paper_title": "PANDA challenge",
        }
    }
    records = extract_dataset_candidates(grounding, _profile())
    assert [r.name for r in records] == ["PANDA"]
    assert records[0].evidence[0].source == "sota_target"
    # DOI canonicalizes to doi:...
    assert records[0].evidence[0].paper_id.startswith("doi:")


# ---------------------------------------------------------------- papers


def test_extracts_papers_datasets_when_present():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    grounding = {
        "papers": [
            {
                "paper_id": "openalex:W42",
                "title": "MSI Survey",
                "datasets": ["TCGA-CRC", "PAIP-CRC"],
            }
        ]
    }
    records = extract_dataset_candidates(grounding, _profile())
    names = {r.name for r in records}
    assert {"TCGA-CRC", "PAIP-CRC"} <= names
    # paper-level datasets default to "low" confidence.
    for r in records:
        assert r.confidence == "low"
        assert r.evidence[0].source == "paper"


def test_papers_without_datasets_field_is_skipped():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    grounding = {
        "papers": [{"paper_id": "openalex:W42", "title": "X"}]
    }
    assert extract_dataset_candidates(grounding, _profile()) == []


# ---------------------------------------------------------------- LLM hints


def test_consumes_dataset_hint_candidates_from_grounding():
    """Review constraint #4: LLM task-profile already wrote `dataset_hint_candidates`."""
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    grounding = {
        "dataset_hint_candidates": [
            {"name": "PANDA", "confidence": "high", "reason": "Gleason grading"},
            {"name": "SICAPv2", "confidence": "medium", "reason": "Gleason grading"},
        ]
    }
    records = extract_dataset_candidates(grounding, _profile())
    names = {r.name for r in records}
    assert {"PANDA", "SICAPv2"} <= names
    panda = [r for r in records if r.name == "PANDA"][0]
    # LLM-supplied confidence flows through.
    assert panda.confidence == "high"
    assert panda.evidence[0].source == "llm_hint"


def test_skips_llm_hint_with_empty_name():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    grounding = {"dataset_hint_candidates": [{"name": "", "confidence": "low"}]}
    assert extract_dataset_candidates(grounding, _profile()) == []


# ---------------------------------------------------------------- passages


def test_extracts_provider_hints_from_passages():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    grounding = {
        "passages": [
            {
                "paper_id": "openalex:W9",
                "section": "Data availability",
                "text": "The CRC-MSI dataset is available at https://zenodo.org/records/12345.",
            }
        ]
    }
    records = extract_dataset_candidates(grounding, _profile())
    assert records
    rec = records[0]
    assert rec.provider_hints
    hint = rec.provider_hints[0]
    assert hint.provider == "zenodo"
    assert "zenodo.org/records/12345" in hint.url


def test_passage_denylist_drops_generic_phrases():
    """Review constraint #5: passage regex must not turn generic phrases into datasets."""
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    grounding = {
        "passages": [
            {
                "paper_id": "openalex:W1",
                "section": "Data availability",
                "text": "Data Availability Section. Supplementary Materials below.",
            }
        ]
    }
    # Should NOT extract "Data Availability" or "Supplementary Materials" as datasets.
    records = extract_dataset_candidates(grounding, _profile())
    bad = {"Data Availability", "Supplementary Materials", "Data Availability Section"}
    assert not (bad & {r.name for r in records})


def test_passage_with_url_lifts_confidence_to_medium():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    grounding = {
        "passages": [
            {
                "paper_id": "openalex:W1",
                "text": "TCGA-CRC dataset at https://huggingface.co/datasets/foo/crc.",
            }
        ]
    }
    records = extract_dataset_candidates(grounding, _profile())
    assert records
    rec = records[0]
    assert rec.confidence == "medium"
    # huggingface.co URL → hf provider hint.
    assert any(h.provider == "huggingface" for h in rec.provider_hints)


# ---------------------------------------------------------------- merging


def test_merges_evidence_when_same_dataset_appears_in_baseline_and_passage():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    grounding = {
        "baselines": [
            {"dataset": "CRC-MSI", "paper_id": "openalex:W1", "context": "AUC."}
        ],
        "passages": [
            {
                "paper_id": "openalex:W2",
                "text": "CRC-MSI dataset is at https://zenodo.org/records/77.",
            }
        ],
    }
    records = extract_dataset_candidates(grounding, _profile())
    crc = [r for r in records if r.name == "CRC-MSI"]
    assert len(crc) == 1, "same dataset name must dedup, not duplicate"
    rec = crc[0]
    assert len(rec.evidence) == 2
    assert {e.source for e in rec.evidence} == {"baseline", "passage"}
    # Provider hint from passage propagates.
    assert any(h.provider == "zenodo" for h in rec.provider_hints)


def test_dedup_is_case_insensitive():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    grounding = {
        "baselines": [
            {"dataset": "CRC-MSI", "paper_id": "openalex:W1"},
            {"dataset": "crc-msi", "paper_id": "openalex:W2"},
        ]
    }
    records = extract_dataset_candidates(grounding, _profile())
    assert len(records) == 1
    assert len(records[0].evidence) == 2


# ---------------------------------------------------------------- empty


def test_empty_grounding_returns_empty():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    assert extract_dataset_candidates({}, _profile()) == []


def test_no_profile_still_works_with_empty_label_semantics():
    """Profile is only used to copy task_types/asset_types/etc. — not required."""
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    grounding = {"baselines": [{"dataset": "X", "paper_id": "openalex:W1"}]}
    records = extract_dataset_candidates(grounding, None)
    assert [r.name for r in records] == ["X"]
    assert records[0].label_keywords == []


# ---------------------------------------------------------------- bad data


# --------------------------------------- Task 2: hardened provider hints ---


def test_passage_direct_file_url_creates_direct_http_hint():
    """Catch-all: any *file-like* URL outside known providers becomes a
    ``direct_http`` provider hint with the URL preserved verbatim."""
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates
    from autoresearch.dataset.types import TaskProfile

    profile = TaskProfile(
        task_type="patch_classification",
        asset_level="patch", input_modality="patch_images",
        label_granularity="patch", organ="breast",
        required_label_keywords=["BRACS"],
    )
    grounding = {
        "passages": [{
            "paper_id": "openalex:W1",
            "text": "The BRACS dataset is available at https://example.org/bracs.zip",
        }]
    }
    records = extract_dataset_candidates(grounding, profile)
    assert any(r.name == "BRACS" for r in records)
    rec = next(r for r in records if r.name == "BRACS")
    direct = [h for h in rec.provider_hints if h.provider == "direct_http"]
    assert direct, "direct file URL must produce a direct_http hint"
    assert direct[0].url == "https://example.org/bracs.zip"


def test_passage_huggingface_url_extracts_remote_id():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates
    from autoresearch.dataset.types import TaskProfile

    profile = TaskProfile(
        task_type="patch_classification",
        asset_level="patch", input_modality="patch_images",
        label_granularity="patch", organ="colorectal",
        required_label_keywords=["MSI"],
    )
    grounding = {
        "passages": [{
            "paper_id": "W1",
            "text": "MSI corpus at https://huggingface.co/datasets/org/msi-corpus",
        }]
    }
    records = extract_dataset_candidates(grounding, profile)
    assert records
    hf = [
        h for r in records for h in r.provider_hints if h.provider == "huggingface"
    ]
    assert hf, "huggingface URL must produce a huggingface hint"
    assert hf[0].remote_id == "org/msi-corpus"


def test_passage_kaggle_competition_url_extracts_slug_and_competition_kind():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates
    from autoresearch.dataset.types import TaskProfile

    profile = TaskProfile(
        task_type="mil_classification",
        asset_level="slide", input_modality="wsi",
        label_granularity="slide", organ="prostate",
        required_label_keywords=["PANDA"],
    )
    grounding = {
        "passages": [{
            "paper_id": "W1",
            "text": "PANDA challenge data at https://www.kaggle.com/competitions/prostate-cancer-grade-assessment/data",
        }]
    }
    records = extract_dataset_candidates(grounding, profile)
    assert records
    kaggle = [
        h for r in records for h in r.provider_hints if h.provider == "kaggle"
    ]
    assert kaggle
    assert kaggle[0].kind == "kaggle_competition"
    assert kaggle[0].remote_id == "prostate-cancer-grade-assessment"


def test_passage_kaggle_dataset_url_extracts_owner_slug_and_dataset_kind():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates
    from autoresearch.dataset.types import TaskProfile

    profile = TaskProfile(
        task_type="patch_classification",
        asset_level="patch", input_modality="patch_images",
        label_granularity="patch", organ="prostate",
        required_label_keywords=["PANDA"],
    )
    grounding = {
        "passages": [{
            "paper_id": "W1",
            "text": "PANDA at https://www.kaggle.com/datasets/owner/panda-corpus",
        }]
    }
    records = extract_dataset_candidates(grounding, profile)
    kaggle = [
        h for r in records for h in r.provider_hints if h.provider == "kaggle"
    ]
    assert kaggle
    assert kaggle[0].kind == "kaggle_dataset"
    assert kaggle[0].remote_id == "owner/panda-corpus"


def test_passage_zenodo_record_url_extracts_record_id():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates
    from autoresearch.dataset.types import TaskProfile

    profile = TaskProfile(
        task_type="patch_classification",
        asset_level="patch", input_modality="patch_images",
        label_granularity="patch", organ="colorectal",
        required_label_keywords=["CRC-MSI"],
    )
    grounding = {
        "passages": [{
            "paper_id": "W1",
            "text": "CRC-MSI hosted at https://zenodo.org/records/12345/files/data.zip",
        }]
    }
    records = extract_dataset_candidates(grounding, profile)
    assert records
    zen = [
        h for r in records for h in r.provider_hints if h.provider == "zenodo"
    ]
    assert zen
    assert zen[0].remote_id == "12345"
    # File URL preserved verbatim for the downloader.
    assert zen[0].url == "https://zenodo.org/records/12345/files/data.zip"


def test_passage_baseline_with_blank_dataset_is_skipped():
    """Sanity: blank dataset names from baselines remain skipped after Task 2 changes."""
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates
    from autoresearch.dataset.types import TaskProfile

    profile = TaskProfile(
        task_type="patch_classification",
        asset_level="patch", input_modality="patch_images",
        label_granularity="patch",
    )
    assert extract_dataset_candidates(
        {"baselines": [{"dataset": "", "paper_id": "openalex:W1"}]}, profile,
    ) == []


def test_baseline_with_blank_dataset_is_skipped():
    from autoresearch.dataset.discovery_extractor import extract_dataset_candidates

    grounding = {
        "baselines": [
            {"dataset": "", "paper_id": "openalex:W1"},
            {"dataset": "  ", "paper_id": "openalex:W2"},
        ]
    }
    assert extract_dataset_candidates(grounding, _profile()) == []
