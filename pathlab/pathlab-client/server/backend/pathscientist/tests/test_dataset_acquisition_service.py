from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataset.acquisition import AcquisitionResult, DatasetAcquisitionService
from dataset.policy import AcquisitionPolicy
from dataset.providers.base import DownloadResult
from dataset.registry import DatasetRegistry
from dataset.types import DatasetRecord, DownloadSpec, TaskProfile


# ---- fakes ----

class _FakeProvider:
    provider_name = "huggingface"

    def __init__(self, status="downloaded", reason="", files_to_create=None):
        self._status = status
        self._reason = reason
        self._files_to_create = files_to_create or []

    def probe(self, record):
        return record

    def download(self, record, target_dir):
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for fname, content in self._files_to_create:
            p = target_dir / fname
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
            files.append(p)
        return DownloadResult(
            status=self._status, raw_root=target_dir, files=files,
            reason=self._reason,
        )


class _FakeNormalizer:
    name = "patch_classification"
    supported_task_types = {"patch_classification"}

    def supports(self, task_type):
        return task_type in self.supported_task_types

    def prepare(self, raw_root, prepared_root):
        prepared_root = Path(prepared_root)
        (prepared_root / "images").mkdir(parents=True, exist_ok=True)
        (prepared_root / "splits.json").write_text("{}")
        return {
            "task_type": "patch_classification",
            "images_dir": str(prepared_root / "images"),
            "splits_file": str(prepared_root / "splits.json"),
            "data_mounts": {str(prepared_root): "/data"},
        }


def _profile(task_type="patch_classification", organ="colorectal"):
    return TaskProfile(
        task_type=task_type, asset_level="patch",
        input_modality="patch_images", label_granularity="patch",
        organ=organ,
    )


def _registry_with(records, tmp_path) -> DatasetRegistry:
    reg = DatasetRegistry(tmp_path / "reg.json")
    reg.save(records)
    return reg


def _public_record(dataset_id="hf:demo/x"):
    return DatasetRecord(
        dataset_id=dataset_id,
        name="Demo",
        provider="huggingface",
        access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=["colorectal"],
        estimated_size_gb=1.0,
        download=DownloadSpec(kind="hf_dataset", remote_id="demo/x"),
    )


# ---- tests ----


def test_acquisition_no_candidate_returns_failed_manifest(tmp_path):
    reg = _registry_with([], tmp_path)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg, providers={}, normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "failed"
    assert result.reason == "no_candidate"
    assert result.manifest_path.exists()
    assert json.loads(result.manifest_path.read_text())["status"] == "failed"
    assert result.evidence_path and result.evidence_path.exists()


def test_acquisition_skips_when_only_candidate_is_policy_rejected(tmp_path):
    reg = _registry_with([
        DatasetRecord(
            dataset_id="g", name="G", provider="huggingface",
            access="gated",
            task_types=["patch_classification"], asset_types=["patch_images"],
            organs=["colorectal"], estimated_size_gb=1.0,
            download=DownloadSpec(kind="hf_dataset", remote_id="g"),
        ),
    ], tmp_path)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": _FakeProvider()},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="public_only"),
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "skipped_policy"
    assert result.manifest.status == "skipped_policy"
    assert "access=gated" in result.reason


def test_acquisition_downloads_prepares_and_writes_manifest(tmp_path):
    reg = _registry_with([_public_record()], tmp_path)
    workspace = tmp_path / "workspace"
    fake_provider = _FakeProvider(
        status="downloaded",
        files_to_create=[("data.bin", b"hello")],
    )
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": fake_provider},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "prepared"
    assert result.manifest_path.exists()
    assert result.manifest.prepared_contract["task_type"] == "patch_classification"
    assert result.manifest.data_mounts
    assert result.manifest.status == "prepared"
    assert result.evidence_path and result.evidence_path.exists()
    ev = json.loads(result.evidence_path.read_text())
    assert ev["status"] == "prepared"


def test_acquisition_failed_when_provider_returns_failed(tmp_path):
    reg = _registry_with([_public_record()], tmp_path)
    workspace = tmp_path / "workspace"
    fake_provider = _FakeProvider(status="failed", reason="auth")
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": fake_provider},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "failed"
    assert "auth" in result.reason


def test_acquisition_failed_when_no_normalizer_supports_task(tmp_path):
    reg = _registry_with([
        DatasetRecord(
            dataset_id="x", name="X", provider="huggingface",
            access="public",
            task_types=["survival_analysis"],
            asset_types=["clinical_table"],
            organs=["lung"], estimated_size_gb=1.0,
            download=DownloadSpec(kind="hf_dataset", remote_id="x"),
        ),
    ], tmp_path)
    workspace = tmp_path / "workspace"
    fake_provider = _FakeProvider(status="downloaded", files_to_create=[("a.bin", b"x")])
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": fake_provider},
        normalizers=[_FakeNormalizer()],   # only patch_classification
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(
        TaskProfile(
            task_type="survival_analysis", asset_level="slide",
            input_modality="clinical_table", label_granularity="slide", organ="lung",
        ),
        workspace_root=workspace,
    )
    assert result.status == "failed"
    assert "no_normalizer" in result.reason


def test_acquisition_failed_when_no_provider_for_record(tmp_path):
    reg = _registry_with([_public_record()], tmp_path)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={},   # no huggingface provider registered
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "failed"
    assert "no_provider" in result.reason


def test_acquisition_evidence_written_with_safe_id(tmp_path):
    reg = _registry_with([_public_record(dataset_id="hf:org/path")], tmp_path)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": _FakeProvider(status="downloaded", files_to_create=[("a.bin", b"x")])},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.evidence_path.name == "hf_org_path.json"


# ---- Review fix R2 (P1): relevance gate ----


def test_acquisition_failed_when_no_relevant_candidate(tmp_path):
    """Review P1 #3: only-irrelevant-public candidates should NOT be picked.

    Profile = survival_analysis. Registry has only a public patch dataset
    that happens to pass policy. Acquisition must return failed/no_relevant_candidate
    rather than silently selecting the wrong dataset.
    """
    reg = _registry_with([
        DatasetRecord(
            dataset_id="x", name="CRC Patches",
            provider="huggingface", access="public",
            task_types=["patch_classification"],
            asset_types=["patch_images"],
            organs=["colorectal"], estimated_size_gb=1.0,
            download=DownloadSpec(kind="hf_dataset", remote_id="x"),
        ),
    ], tmp_path)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": _FakeProvider(status="downloaded", files_to_create=[("a.bin", b"x")])},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(
        TaskProfile(
            task_type="survival_analysis", asset_level="slide",
            input_modality="clinical_table", label_granularity="slide", organ="lung",
        ),
        workspace_root=workspace,
    )
    assert result.status == "failed"
    assert result.reason == "no_relevant_candidate"


def test_acquisition_skipped_policy_cites_relevant_candidate(tmp_path):
    """Review P1 #3: when the only relevant candidate is policy-blocked,
    skipped_policy evidence should cite the relevant blocked candidate,
    not an irrelevant public one."""
    reg = _registry_with([
        # Irrelevant but public — must NOT be selected.
        DatasetRecord(
            dataset_id="public-patches", name="Public Patches",
            provider="huggingface", access="public",
            task_types=["patch_classification"],
            asset_types=["patch_images"],
            organs=["colorectal"], estimated_size_gb=1.0,
            download=DownloadSpec(kind="hf_dataset", remote_id="x"),
        ),
        # Relevant but gated.
        DatasetRecord(
            dataset_id="gated-mil", name="Gated MIL Cohort",
            provider="huggingface", access="gated",
            task_types=["mil_classification"],
            asset_types=["wsi"],
            organs=["lung"], estimated_size_gb=2.0,
            download=DownloadSpec(kind="hf_dataset", remote_id="g"),
        ),
    ], tmp_path)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": _FakeProvider()},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="public_only"),
    )
    result = service.acquire(
        TaskProfile(
            task_type="mil_classification", asset_level="slide",
            input_modality="wsi", label_granularity="slide", organ="lung",
        ),
        workspace_root=workspace,
    )
    assert result.status == "skipped_policy"
    assert "access=gated" in result.reason
    # Evidence cites the relevant candidate, not the irrelevant public one.
    assert result.candidate is not None
    assert result.candidate.record.dataset_id == "gated-mil"


# ---- Review fix R3 (P1): normalizer empty-output validation ----


def test_acquisition_failed_when_normalizer_raises_normalizer_error(tmp_path):
    """Empty raw layout -> NormalizerError -> manifest.status=failed with normalize_empty reason."""
    from dataset.normalizers.base import NormalizerError

    class _RaisingNormalizer:
        name = "patch_classification"
        supported_task_types = {"patch_classification"}

        def supports(self, task_type):
            return task_type in self.supported_task_types

        def prepare(self, raw_root, prepared_root):
            raise NormalizerError("no_images")

    reg = _registry_with([_public_record()], tmp_path)
    workspace = tmp_path / "workspace"
    fake_provider = _FakeProvider(status="downloaded", files_to_create=[("a.bin", b"x")])
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": fake_provider},
        normalizers=[_RaisingNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "failed"
    assert result.reason.startswith("normalize_empty:no_images")
    assert result.manifest.status == "failed"
