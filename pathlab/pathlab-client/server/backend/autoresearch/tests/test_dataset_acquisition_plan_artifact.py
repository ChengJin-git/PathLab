"""Tests for the .dataset/acquisition_plan.json artifact.

Phase C T8 of docs/plans/2026-04-30-autoresearch-literature-grounded-dataset-discovery-plan.md.

The plan artifact must be written BEFORE the download phase so the agent
can inspect why data wasn't downloaded under stop-before-execution or
download_policy=disabled.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def test_acquisition_plan_path_for_workspace(tmp_path):
    from autoresearch.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )

    assert (
        acquisition_plan_path_for_workspace(tmp_path)
        == tmp_path / ".dataset" / "acquisition_plan.json"
    )


def test_save_acquisition_plan_round_trips(tmp_path):
    from autoresearch.dataset.acquisition_plan import save_acquisition_plan

    path = tmp_path / ".dataset" / "acquisition_plan.json"
    save_acquisition_plan(path, {
        "status": "planned",
        "considered": [{"dataset_id": "x", "allowed": False}],
    })
    payload = json.loads(path.read_text())
    assert payload["status"] == "planned"
    assert payload["considered"][0]["dataset_id"] == "x"


def test_save_creates_parent_directory(tmp_path):
    from autoresearch.dataset.acquisition_plan import save_acquisition_plan

    path = tmp_path / "deep" / "nested" / "plan.json"
    save_acquisition_plan(path, {"status": "ok"})
    assert path.exists()


# ---------------------------------------------------------------- integration


def _hf_record(dataset_id, name, tags=None, organs=None, access="manual",
               remote_id=""):
    from autoresearch.dataset.types import DatasetRecord, DownloadSpec
    return DatasetRecord(
        dataset_id=dataset_id, name=name, provider="huggingface",
        access=access,
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=list(organs or []),
        tags=list(tags or []),
        download=DownloadSpec(kind="hf_dataset", remote_id=remote_id),
    )


class _StubHF:
    provider_name = "huggingface"

    def probe(self, record):
        return record

    def download(self, record, target_dir):
        from autoresearch.dataset.providers.base import DownloadResult
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        return DownloadResult(
            status="failed", raw_root=Path(target_dir), reason="test_stop"
        )


def _msi_profile():
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


def test_acquire_writes_acquisition_plan_with_considered_candidates(tmp_path):
    from autoresearch.dataset.acquisition import DatasetAcquisitionService
    from autoresearch.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )
    from autoresearch.dataset.policy import AcquisitionPolicy
    from autoresearch.dataset.registry import DatasetRegistry

    registry = DatasetRegistry(tmp_path / "datasets.json")
    registry.save([
        _hf_record(
            dataset_id="discovered:crc-msi", name="CRC-MSI",
            tags=["MSI", "MSS", "discovered"], organs=["colorectal"],
            remote_id="org/crc-msi",
        ),
        _hf_record(
            dataset_id="curated:nct-crc", name="NCT-CRC",
            tags=[], organs=["colorectal"], remote_id="org/nct",
            access="public",
        ),
    ])
    workspace = tmp_path / "ws"
    workspace.mkdir()
    service = DatasetAcquisitionService(
        registry=registry,
        providers={"huggingface": _StubHF()},
        normalizers=[],
        cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="public_only", max_download_size_gb=10),
    )
    service.acquire(_msi_profile(), workspace_root=workspace)

    plan_path = acquisition_plan_path_for_workspace(workspace)
    assert plan_path.exists(), "acquire() must write .dataset/acquisition_plan.json"
    payload = json.loads(plan_path.read_text())
    assert "status" in payload
    assert "considered" in payload
    ids = [c.get("dataset_id") for c in payload["considered"]]
    assert "discovered:crc-msi" in ids
    assert "curated:nct-crc" in ids
    # Per-candidate keys.
    sample = next(c for c in payload["considered"] if c["dataset_id"] == "discovered:crc-msi")
    for key in ("dataset_id", "name", "provider", "access", "score", "relevant", "allowed"):
        assert key in sample, f"missing key {key!r}"


def test_plan_records_selected_dataset_when_chosen(tmp_path):
    from autoresearch.dataset.acquisition import DatasetAcquisitionService
    from autoresearch.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )
    from autoresearch.dataset.policy import AcquisitionPolicy
    from autoresearch.dataset.registry import DatasetRegistry

    registry = DatasetRegistry(tmp_path / "datasets.json")
    registry.save([
        _hf_record(
            dataset_id="curated:crc-msi-public", name="CRC-MSI-Public",
            tags=["MSI", "MSS"], organs=["colorectal"],
            remote_id="org/crc-msi", access="public",
        ),
    ])
    workspace = tmp_path / "ws"
    workspace.mkdir()
    service = DatasetAcquisitionService(
        registry=registry,
        providers={"huggingface": _StubHF()},
        normalizers=[],
        cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="public_only", max_download_size_gb=10),
    )
    service.acquire(_msi_profile(), workspace_root=workspace)

    plan_path = acquisition_plan_path_for_workspace(workspace)
    payload = json.loads(plan_path.read_text())
    assert payload.get("selected_dataset_id") == "curated:crc-msi-public"


# -------------------------------------------- Task 0 review blockers --------


def test_plan_exists_before_provider_download(tmp_path):
    """Blocker #1: plan must be written BEFORE provider.download() is called.

    If download() takes minutes (or crashes), reviewers under
    --stop-before-execution still need the plan on disk to see what was
    considered."""
    from autoresearch.dataset.acquisition import DatasetAcquisitionService
    from autoresearch.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )
    from autoresearch.dataset.policy import AcquisitionPolicy
    from autoresearch.dataset.providers.base import DownloadResult
    from autoresearch.dataset.registry import DatasetRegistry
    from autoresearch.dataset.types import DatasetRecord, DownloadSpec, TaskProfile

    workspace = tmp_path / "ws"
    workspace.mkdir()
    registry = DatasetRegistry(tmp_path / "datasets.json")
    registry.save([
        DatasetRecord(
            dataset_id="d1", name="CRC-MSI",
            provider="huggingface", access="public",
            task_types=["patch_classification"],
            asset_types=["patch_images"],
            organs=["colorectal"], tags=["MSI"],
            download=DownloadSpec(kind="hf_dataset", remote_id="org/repo"),
        )
    ])

    class Provider:
        provider_name = "huggingface"
        saw_plan = False
        def probe(self, record): return record
        def download(self, record, target_dir):
            # Plan must exist by this point.
            self.saw_plan = acquisition_plan_path_for_workspace(workspace).exists()
            return DownloadResult(status="failed", raw_root=Path(target_dir), reason="stub")

    provider = Provider()
    service = DatasetAcquisitionService(
        registry=registry,
        providers={"huggingface": provider},
        normalizers=[],
        cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="public_only"),
    )
    profile = TaskProfile(
        task_type="patch_classification",
        asset_level="patch", input_modality="patch_images",
        label_granularity="patch", organ="colorectal",
        required_label_keywords=["MSI"],
    )
    service.acquire(profile, workspace_root=workspace)
    assert provider.saw_plan is True


def test_plan_payload_includes_task_profile(tmp_path):
    """Blocker #5: payload must carry task_profile so reviewers see what was asked."""
    import json
    from autoresearch.dataset.acquisition import DatasetAcquisitionService
    from autoresearch.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )
    from autoresearch.dataset.policy import AcquisitionPolicy
    from autoresearch.dataset.registry import DatasetRegistry
    from autoresearch.dataset.types import DatasetRecord, DownloadSpec, TaskProfile

    workspace = tmp_path / "ws"
    workspace.mkdir()
    registry = DatasetRegistry(tmp_path / "datasets.json")
    registry.save([
        DatasetRecord(
            dataset_id="curated:nct", name="NCT-CRC",
            provider="huggingface", access="public",
            task_types=["patch_classification"],
            asset_types=["patch_images"],
            organs=["colorectal"],
            download=DownloadSpec(kind="hf_dataset", remote_id="x/x"),
        )
    ])
    service = DatasetAcquisitionService(
        registry=registry, providers={}, normalizers=[],
        cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="public_only"),
    )
    profile = TaskProfile(
        task_type="patch_classification",
        asset_level="patch", input_modality="patch_images",
        label_granularity="patch", organ="colorectal",
        prediction_target="microsatellite_instability",
        required_label_keywords=["MSI"],
    )
    service.acquire(profile, workspace_root=workspace)
    payload = json.loads(acquisition_plan_path_for_workspace(workspace).read_text())
    assert "task_profile" in payload
    assert payload["task_profile"]["prediction_target"] == "microsatellite_instability"


def test_plan_skipped_policy_records_selected_dataset_id(tmp_path):
    """Blocker #6: skipped_policy must record selected_dataset_id (= top relevant candidate).

    Without this, reviewers see status=skipped_policy + selected_dataset_id=""
    and have no idea WHICH candidate was the top relevant pick."""
    import json
    from autoresearch.dataset.acquisition import DatasetAcquisitionService
    from autoresearch.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )
    from autoresearch.dataset.policy import AcquisitionPolicy
    from autoresearch.dataset.registry import DatasetRegistry
    from autoresearch.dataset.types import DatasetRecord, DownloadSpec, TaskProfile

    workspace = tmp_path / "ws"
    workspace.mkdir()
    registry = DatasetRegistry(tmp_path / "datasets.json")
    # Relevant for MSI but access=manual under public_only policy.
    registry.save([
        DatasetRecord(
            dataset_id="curated:crc-msi-manual", name="CRC-MSI",
            provider="huggingface", access="manual",
            task_types=["patch_classification"],
            asset_types=["patch_images"],
            organs=["colorectal"], tags=["MSI", "MSS"],
            download=DownloadSpec(kind="hf_dataset", remote_id="x/x"),
        )
    ])
    service = DatasetAcquisitionService(
        registry=registry, providers={}, normalizers=[],
        cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="public_only"),
    )
    profile = TaskProfile(
        task_type="patch_classification",
        asset_level="patch", input_modality="patch_images",
        label_granularity="patch", organ="colorectal",
        prediction_target="microsatellite_instability",
        required_label_keywords=["MSI", "MSS"],
    )
    service.acquire(profile, workspace_root=workspace)
    payload = json.loads(acquisition_plan_path_for_workspace(workspace).read_text())
    assert payload["status"] == "skipped_policy"
    assert payload["selected_dataset_id"] == "curated:crc-msi-manual"


def test_plan_considered_entries_include_download_size_license_source_paper_ids(tmp_path):
    """Task 6: plan entries surface provider_available + download.* + size + license + source_paper_ids."""
    import json
    from autoresearch.dataset.acquisition import DatasetAcquisitionService
    from autoresearch.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )
    from autoresearch.dataset.policy import AcquisitionPolicy
    from autoresearch.dataset.registry import DatasetRegistry
    from autoresearch.dataset.types import DatasetRecord, DownloadSpec, TaskProfile

    workspace = tmp_path / "ws"
    workspace.mkdir()
    registry = DatasetRegistry(tmp_path / "datasets.json")
    registry.save([
        DatasetRecord(
            dataset_id="kaggle:panda", name="PANDA",
            provider="kaggle", access="manual",
            task_types=["mil_classification"],
            asset_types=["wsi"],
            organs=["prostate"],
            license="CC-BY-SA-NC-4.0",
            estimated_size_gb=400.0,
            tags=["gleason", "ISUP"],
            source_paper_ids=["doi:10.1038/s41591-021-01620-2"],
            download=DownloadSpec(
                kind="kaggle_competition",
                remote_id="prostate-cancer-grade-assessment",
            ),
        )
    ])
    # Empty providers — provider_available must be False.
    service = DatasetAcquisitionService(
        registry=registry, providers={}, normalizers=[],
        cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="manual_only", max_download_size_gb=10),
    )
    profile = TaskProfile(
        task_type="mil_classification",
        asset_level="slide", input_modality="wsi",
        label_granularity="slide", organ="prostate",
        prediction_target="gleason_grading",
        required_label_keywords=["gleason", "ISUP"],
    )
    service.acquire(profile, workspace_root=workspace)

    payload = json.loads(acquisition_plan_path_for_workspace(workspace).read_text())
    sample = next(c for c in payload["considered"] if c["dataset_id"] == "kaggle:panda")
    assert sample["provider_available"] is False
    assert sample["estimated_size_gb"] == 400.0
    assert sample["license"] == "CC-BY-SA-NC-4.0"
    assert "doi:10.1038/s41591-021-01620-2" in sample["source_paper_ids"]
    assert isinstance(sample["download"], dict)
    assert sample["download"]["kind"] == "kaggle_competition"
    assert sample["download"]["remote_id"] == "prostate-cancer-grade-assessment"


def test_plan_provider_available_true_when_provider_registered(tmp_path):
    """provider_available reflects ``self._providers`` membership at write time."""
    import json
    from autoresearch.dataset.acquisition import DatasetAcquisitionService
    from autoresearch.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )
    from autoresearch.dataset.policy import AcquisitionPolicy
    from autoresearch.dataset.providers.base import DownloadResult
    from autoresearch.dataset.registry import DatasetRegistry
    from autoresearch.dataset.types import DatasetRecord, DownloadSpec, TaskProfile

    workspace = tmp_path / "ws"
    workspace.mkdir()
    registry = DatasetRegistry(tmp_path / "datasets.json")
    registry.save([
        DatasetRecord(
            dataset_id="d1", name="CRC-MSI",
            provider="huggingface", access="public",
            task_types=["patch_classification"],
            asset_types=["patch_images"],
            organs=["colorectal"], tags=["MSI"],
            download=DownloadSpec(kind="hf_dataset", remote_id="org/x"),
        )
    ])

    class Stub:
        provider_name = "huggingface"
        def probe(self, record): return record
        def download(self, record, target_dir):
            return DownloadResult(status="failed", raw_root=Path(target_dir), reason="stub")

    service = DatasetAcquisitionService(
        registry=registry, providers={"huggingface": Stub()},
        normalizers=[], cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="public_only"),
    )
    profile = TaskProfile(
        task_type="patch_classification",
        asset_level="patch", input_modality="patch_images",
        label_granularity="patch", organ="colorectal",
        required_label_keywords=["MSI"],
    )
    service.acquire(profile, workspace_root=workspace)
    payload = json.loads(acquisition_plan_path_for_workspace(workspace).read_text())
    sample = next(c for c in payload["considered"] if c["dataset_id"] == "d1")
    assert sample["provider_available"] is True


def test_plan_status_failed_when_no_relevant_candidate(tmp_path):
    from autoresearch.dataset.acquisition import DatasetAcquisitionService
    from autoresearch.dataset.acquisition_plan import (
        acquisition_plan_path_for_workspace,
    )
    from autoresearch.dataset.policy import AcquisitionPolicy
    from autoresearch.dataset.registry import DatasetRegistry

    registry = DatasetRegistry(tmp_path / "datasets.json")
    # No MSI-related records → not relevant.
    registry.save([
        _hf_record(
            dataset_id="curated:nct-crc", name="NCT-CRC",
            tags=[], organs=["colorectal"], remote_id="org/nct",
            access="public",
        ),
    ])
    workspace = tmp_path / "ws"
    workspace.mkdir()
    service = DatasetAcquisitionService(
        registry=registry,
        providers={"huggingface": _StubHF()},
        normalizers=[],
        cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="public_only", max_download_size_gb=10),
    )
    service.acquire(_msi_profile(), workspace_root=workspace)

    plan_path = acquisition_plan_path_for_workspace(workspace)
    payload = json.loads(plan_path.read_text())
    assert payload["status"] == "failed"
    assert payload.get("selected_dataset_id") in ("", None)
    # The considered list still surfaces the irrelevant candidate.
    assert any(c["dataset_id"] == "curated:nct-crc" for c in payload["considered"])
